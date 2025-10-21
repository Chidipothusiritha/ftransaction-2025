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
