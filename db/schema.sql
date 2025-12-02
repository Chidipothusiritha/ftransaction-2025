-- =========================================
-- SCHEMA: Financial Transaction Monitoring
-- =========================================

-- Enums (idempotent)
DO $$ BEGIN CREATE TYPE txn_status_enum   AS ENUM ('approved','declined','reversed'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE alert_status_enum AS ENUM ('open','cleared','confirmed');     EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE alert_severity_enum AS ENUM ('low','med','high');             EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- -----------------------------
-- Core Tables
-- -----------------------------

CREATE TABLE IF NOT EXISTS customers (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(120) UNIQUE,         -- UNIQUE defined inline (keep this)
  signup_ts TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS accounts (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_type VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'Active',
  opened_ts TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS merchants (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  category VARCHAR(50),
  risk_tier VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS transactions (
  id SERIAL PRIMARY KEY,
  account_id INT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  merchant_id INT NOT NULL REFERENCES merchants(id),
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  currency CHAR(3) NOT NULL DEFAULT 'USD',
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

-- Helpful indexes
CREATE INDEX IF NOT EXISTS ix_txn_account_ts  ON transactions (account_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_txn_merchant_ts ON transactions (merchant_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_status   ON alerts (status, created_ts DESC);

-- -----------------------------
-- Rule: Amount Spike
-- -----------------------------
CREATE OR REPLACE FUNCTION rule_amount_spike(txn_id INT)
RETURNS VOID AS $$
DECLARE v_amount NUMERIC(12,2);
BEGIN
  SELECT amount INTO v_amount FROM transactions WHERE id = txn_id;
  IF v_amount IS NULL THEN RETURN; END IF;

  IF v_amount > 5000 THEN
    INSERT INTO alerts (transaction_id, rule_code, severity, details)
    VALUES (txn_id, 'AMOUNT_SPIKE', 'high', jsonb_build_object('amount', v_amount))
    ON CONFLICT ON CONSTRAINT ux_alert_unique_per_rule DO NOTHING;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- ============================
-- DEVICE + NOTIFICATION SUPPORT
-- ============================

-- 1) Devices table (note the built-in unique constraint)
CREATE TABLE IF NOT EXISTS devices (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  fingerprint VARCHAR(128) NOT NULL,
  first_seen_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  last_seen_ts TIMESTAMP,
  label VARCHAR(100),
  CONSTRAINT ux_devices_customer_fingerprint UNIQUE (customer_id, fingerprint) -- UNIQUE defined here
);

-- 2) Device events
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

-- 3) Link transactions to devices
ALTER TABLE IF EXISTS transactions
  ADD COLUMN IF NOT EXISTS device_id INT REFERENCES devices(id);

-- 4) Notifications table
CREATE TABLE IF NOT EXISTS notifications (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  channel VARCHAR(20) NOT NULL DEFAULT 'in_app',   -- 'in_app','email','sms'
  title VARCHAR(120) NOT NULL,
  body TEXT NOT NULL,
  created_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 5) Rule: NEW_DEVICE
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

  -- "New" = device created within the last minute
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

-- 6) Helper: get_or_create_device
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

-- 7) Rule: velocity (3 txns in 2 min for same account)
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

-- Auth table for user portal
CREATE TABLE IF NOT EXISTS customer_auth (
  customer_id    BIGINT PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
  email          CITEXT UNIQUE NOT NULL,
  password_hash  TEXT NOT NULL,
  created_ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_ts  TIMESTAMPTZ
);

-- Idempotent unique constraint on merchants.name
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'merchants_name_key'
  ) THEN
    ALTER TABLE merchants
      ADD CONSTRAINT merchants_name_key UNIQUE (name);
  END IF;
END $$;

-- Idempotent unique constraint on (accounts.customer_id, account_type)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'accounts_customer_type_key'
  ) THEN
    ALTER TABLE accounts
      ADD CONSTRAINT accounts_customer_type_key UNIQUE (customer_id, account_type);
  END IF;
END $$;
