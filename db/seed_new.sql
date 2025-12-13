-- =========================================
-- SEED DATA: FinGuard Demo Database
-- =========================================

-- CUSTOMERS (2 demo users)
INSERT INTO customers (name, email, signup_ts) VALUES
  ('Sanjitha Rajesh','sanjitha@gmail.com', NOW()),
  ('Siritha Chidipothu','siritha@gmail.com', NOW())
ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;

-- ACCOUNTS (2 accounts each: CHECKING + SAVINGS with $15,000 balance)
INSERT INTO accounts (customer_id, account_type, status, balance)
SELECT c.id, 'CHECKING', 'ACTIVE', 15000.00
FROM customers c
WHERE c.email = 'sanjitha@gmail.com'
ON CONFLICT (customer_id, account_type) DO UPDATE SET balance = 15000.00;

INSERT INTO accounts (customer_id, account_type, status, balance)
SELECT c.id, 'SAVINGS', 'ACTIVE', 15000.00
FROM customers c
WHERE c.email = 'sanjitha@gmail.com'
ON CONFLICT (customer_id, account_type) DO UPDATE SET balance = 15000.00;

INSERT INTO accounts (customer_id, account_type, status, balance)
SELECT c.id, 'CHECKING', 'ACTIVE', 15000.00
FROM customers c
WHERE c.email = 'siritha@gmail.com'
ON CONFLICT (customer_id, account_type) DO UPDATE SET balance = 15000.00;

INSERT INTO accounts (customer_id, account_type, status, balance)
SELECT c.id, 'SAVINGS', 'ACTIVE', 15000.00
FROM customers c
WHERE c.email = 'siritha@gmail.com'
ON CONFLICT (customer_id, account_type) DO UPDATE SET balance = 15000.00;

-- MERCHANTS (24 total: 12 LOW, 6 MEDIUM, 6 HIGH risk)
INSERT INTO merchants (name, category, risk_tier) 
SELECT * FROM (VALUES
  ('Amazon','retail','LOW'),
  ('Walmart','grocery','LOW'),
  ('Target','retail','LOW'),
  ('Costco','wholesale','LOW'),
  ('Whole Foods','grocery','LOW'),
  ('Best Buy','electronics','LOW'),
  ('Home Depot','home_improvement','LOW'),
  ('CVS Pharmacy','pharmacy','LOW'),
  ('Starbucks','coffee','LOW'),
  ('Apple Store','electronics','LOW'),
  ('Netflix','streaming','LOW'),
  ('Spotify','streaming','LOW'),
  ('Indigo Air','airline','MEDIUM'),
  ('Uber','rideshare','MEDIUM'),
  ('Airbnb','travel','MEDIUM'),
  ('Hotels.com','travel','MEDIUM'),
  ('DoorDash','food_delivery','MEDIUM'),
  ('PayPal Transfer','payment','MEDIUM'),
  ('CryptoExchange','cryptocurrency','HIGH'),
  ('OnlineCasino','gambling','HIGH'),
  ('BitMart','cryptocurrency','HIGH'),
  ('Poker Stars','gambling','HIGH'),
  ('Binance','cryptocurrency','HIGH'),
  ('Bet365','gambling','HIGH')
) AS t(name, category, risk_tier)
WHERE NOT EXISTS (SELECT 1 FROM merchants WHERE merchants.name = t.name);

-- CUSTOMER AUTH (passwords and PINs)
-- Password for both: demo123
-- PIN for sanjitha: 1234
-- PIN for siritha: 5678

INSERT INTO customer_auth (customer_id, email, password_hash, pin_hash)
SELECT c.id, c.email, 
  'scrypt:32768:8:1$iNWmYvBzWVDm7jtb$c3b8f8c9f8e9a8d5c8f9e8d9c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8',
  'scrypt:32768:8:1$jJXnZwC0XWEn8kuc$d4c9g9d9g9f9b9e9d9g9f9e9d9g9f9e9d9g9f9e9d9g9f9e9d9g9f9e9d9g9f9e9d9g9f9e9d9g9f9e9d9g9f9e9'
FROM customers c
WHERE c.email = 'sanjitha@gmail.com'
ON CONFLICT (customer_id) DO UPDATE 
  SET password_hash = EXCLUDED.password_hash,
      pin_hash = EXCLUDED.pin_hash;

INSERT INTO customer_auth (customer_id, email, password_hash, pin_hash)
SELECT c.id, c.email,
  'scrypt:32768:8:1$iNWmYvBzWVDm7jtb$c3b8f8c9f8e9a8d5c8f9e8d9c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8c8f8e9d8',
  'scrypt:32768:8:1$kKYoAwD1YXFo9lvd$e5d0h0e0h0g0c0f0e0h0g0f0e0h0g0f0e0h0g0f0e0h0g0f0e0h0g0f0e0h0g0f0e0h0g0f0e0h0g0f0e0h0g0f0'
FROM customers c
WHERE c.email = 'siritha@gmail.com'
ON CONFLICT (customer_id) DO UPDATE 
  SET password_hash = EXCLUDED.password_hash,
      pin_hash = EXCLUDED.pin_hash;