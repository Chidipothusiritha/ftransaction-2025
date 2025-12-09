#!/usr/bin/env python3
"""
Check if admin_notifications table exists
"""

import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

dsn = os.getenv("DATABASE_URL", "postgresql://ftms_user:ftms_password@localhost:5432/ftms_db")

def check_table():
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'admin_notifications'
                )
            """)
            exists = cur.fetchone()[0]
            
            if exists:
                print("✓ admin_notifications table EXISTS")
                
                # Show columns
                cur.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'admin_notifications'
                    ORDER BY ordinal_position
                """)
                print("\nTable structure:")
                for row in cur.fetchall():
                    print(f"  - {row[0]}: {row[1]}")
                
                # Count rows
                cur.execute("SELECT COUNT(*) FROM admin_notifications")
                count = cur.fetchone()[0]
                print(f"\nTotal notifications: {count}")
                
                # Count unread
                cur.execute("SELECT COUNT(*) FROM admin_notifications WHERE is_read = FALSE")
                unread = cur.fetchone()[0]
                print(f"Unread notifications: {unread}")
                
            else:
                print("✗ admin_notifications table DOES NOT EXIST")
                print("\nYou need to create it by running schema.sql:")
                print("  psql -d ftms_db -f schema.sql")

if __name__ == "__main__":
    try:
        check_table()
    except Exception as e:
        print(f"Error: {e}")