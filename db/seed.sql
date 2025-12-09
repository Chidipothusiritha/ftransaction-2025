-- CUSTOMERS
INSERT INTO customers (name, email, signup_ts) VALUES
  ('Sanjitha Rajesh','sanjitha@gmail.com', NOW()),
  ('Siritha Chidipothu','siri@gmail.com', NOW())
ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;

-- MERCHANTS
INSERT INTO merchants (name, category, risk_tier) VALUES
  ('Amazon','retail','LOW'),
  ('CryptoExchange','cryptocurrency','HIGH'),
  ('Indigo Air','airline','MEDIUM'),
  ('Walmart','grocery','LOW'),
  ('OnlineCasino','gambling','HIGH'),
  ('Target','retail','LOW'),
  ('BitMart','cryptocurrency','HIGH')
ON CONFLICT (name) DO NOTHING;

-- ACCOUNTS (refer by customer email)

-- Sanjitha: Checking + Savings
INSERT INTO accounts (customer_id, account_type, status)
SELECT c.id, 'CHECKING', 'ACTIVE'
FROM customers c
WHERE c.email = 'sanjitha@gmail.com'
  AND NOT EXISTS (
    SELECT 1 FROM accounts a WHERE a.customer_id = c.id AND a.account_type = 'CHECKING'
  );

INSERT INTO accounts (customer_id, account_type, status)
SELECT c.id, 'SAVINGS', 'ACTIVE'
FROM customers c
WHERE c.email = 'sanjitha@gmail.com'
  AND NOT EXISTS (
    SELECT 1 FROM accounts a WHERE a.customer_id = c.id AND a.account_type = 'SAVINGS'
  );

-- Siri: Checking
INSERT INTO accounts (customer_id, account_type, status)
SELECT c.id, 'CHECKING', 'ACTIVE'
FROM customers c
WHERE c.email = 'siri@gmail.com'
  AND NOT EXISTS (
    SELECT 1 FROM accounts a WHERE a.customer_id = c.id AND a.account_type = 'CHECKING'
  );

-- DEVICES (refer by customer email)
INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
SELECT c.id, 'device-fp-sanjitha-001', 'MacBook Pro Chrome', NOW(), NOW()
FROM customers c
WHERE c.email = 'sanjitha@gmail.com'
ON CONFLICT (customer_id, fingerprint) DO NOTHING;

INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
SELECT c.id, 'device-fp-siri-001', 'iPhone 15 Safari', NOW(), NOW()
FROM customers c
WHERE c.email = 'siri@gmail.com'
ON CONFLICT (customer_id, fingerprint) DO NOTHING;

-- TRANSACTIONS (refer by email/type & merchant name)

-- Sanjitha (Checking) @ Amazon - debit
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, direction, device_id, ts)
SELECT
  a.id,
  m.id,
  150.00, 'USD', 'approved', 'debit',
  d.id,
  NOW() - INTERVAL '2 days'
FROM accounts a
JOIN customers c ON c.id = a.customer_id
JOIN merchants m ON m.name = 'Amazon'
LEFT JOIN devices d ON d.fingerprint = 'device-fp-sanjitha-001' AND d.customer_id = c.id
WHERE c.email = 'sanjitha@gmail.com' AND a.account_type = 'CHECKING'
  AND NOT EXISTS (
    SELECT 1 FROM transactions t
    WHERE t.account_id = a.id AND t.merchant_id = m.id AND t.amount = 150.00 AND t.status = 'approved'
  );

-- Siri (Checking) @ Walmart - debit
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, direction, device_id, ts)
SELECT
  a.id,
  m.id,
  75.00, 'USD', 'approved', 'debit',
  d.id,
  NOW() - INTERVAL '1 day'
FROM accounts a
JOIN customers c ON c.id = a.customer_id
JOIN merchants m ON m.name = 'Walmart'
LEFT JOIN devices d ON d.fingerprint = 'device-fp-siri-001' AND d.customer_id = c.id
WHERE c.email = 'siri@gmail.com' AND a.account_type = 'CHECKING'
  AND NOT EXISTS (
    SELECT 1 FROM transactions t
    WHERE t.account_id = a.id AND t.merchant_id = m.id AND t.amount = 75.00 AND t.status = 'approved'
  );

-- DEVICE EVENTS (refer by fingerprint)
INSERT INTO device_events (device_id, event_type, ip_addr, user_agent, geo_city, geo_country)
SELECT d.id, 'login', '192.168.1.100', 'Mozilla/5.0 Chrome/120.0', 'Piscataway', 'US'
FROM devices d
WHERE d.fingerprint = 'device-fp-sanjitha-001'
  AND NOT EXISTS (
    SELECT 1 FROM device_events e
    WHERE e.device_id = d.id AND e.event_type = 'login' AND e.ip_addr = '192.168.1.100'
  );

INSERT INTO device_events (device_id, event_type, ip_addr, user_agent, geo_city, geo_country)
SELECT d.id, 'login', '192.168.1.101', 'Mozilla/5.0 Safari/17.0', 'Edison', 'US'
FROM devices d
WHERE d.fingerprint = 'device-fp-siri-001'
  AND NOT EXISTS (
    SELECT 1 FROM device_events e
    WHERE e.device_id = d.id AND e.event_type = 'login' AND e.ip_addr = '192.168.1.101'
  );

-- INITIAL BALANCES FOR DEMO ACCOUNTS

-- Sanjitha: set all her accounts to 50,000
UPDATE accounts a
SET balance = 50000.00
FROM customers c
WHERE a.customer_id = c.id
  AND c.email = 'sanjitha@gmail.com';

-- Siri: set all her accounts to 50,000
UPDATE accounts a
SET balance = 50000.00
FROM customers c
WHERE a.customer_id = c.id
  AND c.email = 'siri@gmail.com';