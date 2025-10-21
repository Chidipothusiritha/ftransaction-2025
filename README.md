# ftransaction-2025  
### Financial Transaction Monitoring (Fraud Detection Base)

A database-driven system that simulates how banks and fintech platforms detect potential fraudulent activity.  
Built with **PostgreSQL**, **Flask**, and **Python (psycopg)**.

## Overview
The project demonstrates:
- Relational data modeling for customers, accounts, merchants, transactions, and devices  
- Fraud-rule simulation (e.g., high-amount or new-device alerts)  
- Flask-based SQL console for secure querying and updates and to display input/output  
- Modular structure ready for automation, dashboards, or ML extension

SCHEMA DESIGN:

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

CREATE TABLE IF NOT EXISTS devices (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  fingerprint VARCHAR(128) NOT NULL,
  first_seen_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  last_seen_ts TIMESTAMP,
  label VARCHAR(100),
  CONSTRAINT ux_devices_customer_fingerprint UNIQUE (customer_id, fingerprint)
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
  channel VARCHAR(20) NOT NULL DEFAULT 'in_app',   -- 'in_app','email','sms'
  title VARCHAR(120) NOT NULL,
  body TEXT NOT NULL,
  created_ts TIMESTAMP NOT NULL DEFAULT NOW(),
  meta JSONB NOT NULL DEFAULT '{}'::jsonb
);



MIDTERM DEMO QUERIES:

1. Show existing data:
SELECT * FROM customers;
SELECT * FROM accounts;
SELECT * FROM merchants;
SELECT * FROM transactions;
SELECT * FROM alerts;

3. Normal transactions 
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
VALUES (8, 9, 150.00, 'USD', 'approved', 4);

INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
VALUES (8, 9, 200.00, 'USD', 'approved', 4);

3. Suspicious transactions:
High amount:
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
VALUES (8, 9, 9500.00, 'USD', 'approved', 4);

High velocity:
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
VALUES (8, 9, 100.00, 'USD', 'approved', 4);

INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
VALUES (8, 9, 110.00, 'USD', 'approved', 4);

INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
VALUES (8, 9, 120.00, 'USD', 'approved', 4);

4. Show alerts:
SELECT * FROM alerts;
