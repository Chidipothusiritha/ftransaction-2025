/* CUSTOMERS */
INSERT INTO customers (name, email) VALUES
  ('Sanjitha Rajesh','sanjitha@example.com'),
  ('Siritha Chidipothu','siri@example.com'),
ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;

/* MERCHANTS */
INSERT INTO merchants (name, category, risk_tier) VALUES
  ('TechStore','Electronics','Med'),
  ('Indigo Air','Airline','Med'),
  ('Bravo','Groceries','Low'),
  ('Zara','Shopping','Med')
ON CONFLICT (name) DO NOTHING;

/* ACCOUNTS (refer by customer email) */

-- Sanjitha: Checking + Savings
INSERT INTO accounts (customer_id, account_type, status)
SELECT c.id, 'Checking', 'Active'
FROM customers c
WHERE c.email = 'sanjitha@example.com'
  AND NOT EXISTS (
    SELECT 1 FROM accounts a WHERE a.customer_id = c.id AND a.account_type = 'Checking'
  );

INSERT INTO accounts (customer_id, account_type, status)
SELECT c.id, 'Savings', 'Active'
FROM customers c
WHERE c.email = 'sanjitha@example.com'
  AND NOT EXISTS (
    SELECT 1 FROM accounts a WHERE a.customer_id = c.id AND a.account_type = 'Savings'
  );

-- Siri: Checking
INSERT INTO accounts (customer_id, account_type, status)
SELECT c.id, 'Checking', 'Active'
FROM customers c
WHERE c.email = 'siri@example.com'
  AND NOT EXISTS (
    SELECT 1 FROM accounts a WHERE a.customer_id = c.id AND a.account_type = 'Checking'
  );

/* DEVICES (refer by customer email) */
INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
SELECT c.id, 'hash_abc123', 'Mac Safari', NOW(), NOW()
FROM customers c
WHERE c.email = 'sanjitha@example.com'
ON CONFLICT (customer_id, fingerprint) DO NOTHING;

INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
SELECT c.id, 'hash_xyz222', 'iPhone 15', NOW(), NOW()
FROM customers c
WHERE c.email = 'siri@example.com'
ON CONFLICT (customer_id, fingerprint) DO NOTHING;

/* TRANSACTIONS (refer by email/type & merchant name) */

-- Sanjitha (Checking) @ TechStore 
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
SELECT
  a.id,
  m.id,
  300.00, 'USD', 'approved',
  d.id
FROM accounts a
JOIN customers c ON c.id = a.customer_id
JOIN merchants m ON m.name = 'TechStore'
LEFT JOIN devices d ON d.fingerprint = 'hash_abc123' AND d.customer_id = c.id
WHERE c.email = 'sanjitha@example.com' AND a.account_type = 'Checking'
  AND NOT EXISTS (
    SELECT 1 FROM transactions t
    WHERE t.account_id = a.id AND t.merchant_id = m.id AND t.amount = 300.00 AND t.status = 'approved'
  );

-- Sanjitha (Savings) @ Dunkin 
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
SELECT
  a.id,
  m.id,
  5.00, 'USD', 'approved',
  d.id
FROM accounts a
JOIN customers c ON c.id = a.customer_id
JOIN merchants m ON m.name = 'Dunkin'
LEFT JOIN devices d ON d.fingerprint = 'hash_abc123' AND d.customer_id = c.id
WHERE c.email = 'sanjitha@example.com' AND a.account_type = 'Savings'
  AND NOT EXISTS (
    SELECT 1 FROM transactions t
    WHERE t.account_id = a.id AND t.merchant_id = m.id AND t.amount = 5.00 AND t.status = 'approved'
  );

-- Siri (Checking) @ Bravo 
INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
SELECT
  a.id,
  m.id,
  25.00, 'USD', 'approved',
  d.id
FROM accounts a
JOIN customers c ON c.id = a.customer_id
JOIN merchants m ON m.name = 'Bravo'
LEFT JOIN devices d ON d.fingerprint = 'hash_xyz222' AND d.customer_id = c.id
WHERE c.email = 'siri@example.com' AND a.account_type = 'Checking'
  AND NOT EXISTS (
    SELECT 1 FROM transactions t
    WHERE t.account_id = a.id AND t.merchant_id = m.id AND t.amount = 25.00 AND t.status = 'approved'
  );

/* DEVICE EVENTS (refer by fingerprint) */
INSERT INTO device_events (device_id, event_type, ip_addr, user_agent, geo_city, geo_country)
SELECT d.id, 'login', '192.168.0.10', 'Safari/17.3 on macOS', 'New Brunswick', 'US'
FROM devices d
WHERE d.fingerprint = 'hash_abc123'
  AND NOT EXISTS (
    SELECT 1 FROM device_events e
    WHERE e.device_id = d.id AND e.event_type = 'login' AND e.ip_addr = '192.168.0.10'
  );

INSERT INTO device_events (device_id, event_type, ip_addr, user_agent, geo_city, geo_country)
SELECT d.id, 'login', '10.0.0.2', 'Chrome Mobile on iOS', 'Edison', 'US'
FROM devices d
WHERE d.fingerprint = 'hash_xyz222'
  AND NOT EXISTS (
    SELECT 1 FROM device_events e
    WHERE e.device_id = d.id AND e.event_type = 'login' AND e.ip_addr = '10.0.0.2'
  );
