-- =========================================
-- SCHEMA: Financial Transaction Monitoring
-- =========================================

-- Enable citext extension FIRST
CREATE EXTENSION IF NOT EXISTS citext;

-- Enums (idempotent)
DO $$ BEGIN CREATE TYPE txn_status_enum   AS ENUM ('approved','declined','reversed','pending_verification','cancelled'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE alert_status_enum AS ENUM ('open','cleared','confirmed');     EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE alert_severity_enum AS ENUM ('low','med','high');             EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE transaction_direction_enum AS ENUM ('debit', 'credit'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- -----------------------------
-- Core Tables
-- -----------------------------

CREATE TABLE IF NOT EXISTS customers (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(120) UNIQUE,
  signup_ts TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS accounts (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_type VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'Active',
  balance NUMERIC(14,2) NOT NULL DEFAULT 0,
  opened_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT accounts_customer_type_key UNIQUE (customer_id, account_type)
);

CREATE TABLE IF NOT EXISTS merchants (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  category VARCHAR(50),
  risk_tier VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS devices (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  fingerprint VARCHAR(128) NOT NULL,
  first_seen_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  last_seen_ts TIMESTAMP,
  label VARCHAR(100),
  CONSTRAINT ux_devices_customer_fingerprint UNIQUE (customer_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS transactions (
  id SERIAL PRIMARY KEY,
  account_id INT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  merchant_id INT REFERENCES merchants(id),
  device_id INT REFERENCES devices(id),
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  direction transaction_direction_enum NOT NULL DEFAULT 'debit',
  ts TIMESTAMP NOT NULL DEFAULT NOW(),
  status txn_status_enum NOT NULL DEFAULT 'approved'
);

CREATE TABLE IF NOT EXISTS alerts (
  id SERIAL PRIMARY KEY,
  transaction_id INT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  rule_code VARCHAR(50) NOT NULL,
  created_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  severity alert_severity_enum NOT NULL DEFAULT 'med',
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  status alert_status_enum NOT NULL DEFAULT 'open',
  CONSTRAINT ux_alert_unique_per_rule UNIQUE (transaction_id, rule_code)
);

CREATE TABLE IF NOT EXISTS device_events (
  id SERIAL PRIMARY KEY,
  device_id INT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  event_type VARCHAR(30) NOT NULL,
  ip_addr INET,
  user_agent TEXT,
  geo_city VARCHAR(80),
  geo_country VARCHAR(80),
  created_ts TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  channel VARCHAR(20) NOT NULL DEFAULT 'in_app',
  title VARCHAR(120) NOT NULL,
  body TEXT NOT NULL,
  created_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Auth table for user portal (MUST BE HERE!)
CREATE TABLE IF NOT EXISTS customer_auth (
  customer_id    BIGINT PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
  email          CITEXT UNIQUE NOT NULL,
  password_hash  TEXT NOT NULL,
  pin_hash       TEXT,
  created_ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_ts  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    card_type   VARCHAR(10) NOT NULL,
    name_on_card TEXT NOT NULL,
    card_number  VARCHAR(16) NOT NULL,
    last4 VARCHAR(4),
    expiry_month INTEGER NOT NULL,
    expiry_year  INTEGER NOT NULL,
    cvv          VARCHAR(3) NOT NULL,
    cvv_mask     VARCHAR(3) DEFAULT '***',
    created_ts   TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_notifications (
  id SERIAL PRIMARY KEY,
  customer_id INT REFERENCES customers(id) ON DELETE CASCADE,
  transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL,
  message TEXT NOT NULL,
  type VARCHAR(50) NOT NULL DEFAULT 'info',
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_ts TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_txn_account_ts  ON transactions (account_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_txn_merchant_ts ON transactions (merchant_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_status   ON alerts (status, created_ts DESC);
CREATE INDEX IF NOT EXISTS ix_admin_notif_unread ON admin_notifications (is_read, created_ts DESC);

-- ============================
-- FRAUD DETECTION RULES
-- ============================

CREATE OR REPLACE FUNCTION rule_new_device(txn_id INT)
RETURNS INT AS $$
DECLARE
  v_cust INT;
  v_dev INT;
  v_alert_id INT;
BEGIN
  SELECT a.customer_id, t.device_id
    INTO v_cust, v_dev
  FROM transactions t
  JOIN accounts a ON a.id = t.account_id
  WHERE t.id = txn_id;

  IF v_dev IS NULL THEN
    RETURN NULL;
  END IF;

  IF EXISTS (
     SELECT 1 FROM devices d
     WHERE d.id = v_dev AND d.first_seen_ts > now() - interval '1 minute'
  ) THEN
     INSERT INTO alerts (transaction_id, rule_code, severity, details, status)
     VALUES (txn_id, 'NEW_DEVICE', 'med',
             jsonb_build_object('device_id', v_dev),
             'open')
     ON CONFLICT (transaction_id, rule_code) DO NOTHING
     RETURNING id INTO v_alert_id;

     INSERT INTO notifications (customer_id, channel, title, body, meta)
     VALUES (
       v_cust, 'in_app',
       'New device sign-in',
       'We noticed activity from a new device on your account.',
       jsonb_build_object('transaction_id', txn_id, 'device_id', v_dev)
     );
     RETURN v_alert_id;
  END IF;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION rule_velocity_3in2min(txn_id INT)
RETURNS INT AS $$
DECLARE
  v_acct INT;
  v_now  TIMESTAMP;
  v_cnt  INT;
  v_alert_id INT;
BEGIN
  SELECT account_id, ts INTO v_acct, v_now
  FROM transactions WHERE id = txn_id;

  IF v_acct IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT COUNT(*) INTO v_cnt
  FROM transactions
  WHERE account_id = v_acct
    AND ts BETWEEN v_now - interval '2 minutes' AND v_now;

  IF v_cnt >= 3 THEN
    INSERT INTO alerts (transaction_id, rule_code, severity, details, status)
    VALUES (
      txn_id,
      'VELOCITY_3_IN_2MIN',
      'med',
      jsonb_build_object('count', v_cnt, 'window','2m'),
      'open'
    )
    ON CONFLICT (transaction_id, rule_code) DO NOTHING
    RETURNING id INTO v_alert_id;

    RETURN v_alert_id;
  END IF;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_or_create_device(p_customer_id INT, p_fingerprint VARCHAR, p_label VARCHAR DEFAULT NULL)
RETURNS INT AS $$
DECLARE v_id INT;
BEGIN
  SELECT id INTO v_id FROM devices
  WHERE customer_id = p_customer_id AND fingerprint = p_fingerprint;

  IF v_id IS NULL THEN
    INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
    VALUES (p_customer_id, p_fingerprint, p_label, NOW(), NOW())
    RETURNING id INTO v_id;
  ELSE
    UPDATE devices SET last_seen_ts = NOW() WHERE id = v_id;
  END IF;

  RETURN v_id;
END;
$$ LANGUAGE plpgsql;