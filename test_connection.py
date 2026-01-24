#!/usr/bin/env python3
"""
Simple script to test Supabase/PostgreSQL connection.
Run: python test_connection.py
"""
import os
import sys

def test_connection():
    # Check for connection string
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')

    if not dsn:
        print("❌ ERROR: No database connection string found!")
        print("")
        print("Please set one of these environment variables:")
        print("  export POSTGRES_DSN='postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres'")
        print("")
        print("Or create a .env file in the backend folder with:")
        print("  POSTGRES_DSN=postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres")
        return False

    # Mask password for display
    display_dsn = dsn
    if '@' in dsn and ':' in dsn:
        parts = dsn.split('@')
        if ':' in parts[0]:
            user_pass = parts[0].split(':')
            if len(user_pass) >= 3:
                display_dsn = f"{user_pass[0]}:{user_pass[1]}:[HIDDEN]@{parts[1]}"

    print(f"🔍 Found connection string: {display_dsn[:50]}...")
    print("")

    try:
        import asyncpg
        import asyncio

        async def connect():
            print("📡 Attempting to connect to Supabase...")
            conn = await asyncpg.connect(dsn)

            # Test query
            version = await conn.fetchval('SELECT version()')
            print(f"✅ Connected successfully!")
            print(f"   PostgreSQL version: {version[:50]}...")

            # Check if we can create tables
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS _connection_test (
                    id SERIAL PRIMARY KEY,
                    test_time TIMESTAMP DEFAULT NOW()
                )
            ''')
            await conn.execute('INSERT INTO _connection_test DEFAULT VALUES')
            count = await conn.fetchval('SELECT COUNT(*) FROM _connection_test')
            print(f"   Test table created, {count} row(s) inserted")

            # Clean up
            await conn.execute('DROP TABLE _connection_test')
            print(f"   Test table cleaned up")

            await conn.close()
            return True

        return asyncio.run(connect())

    except ImportError:
        print("❌ ERROR: asyncpg not installed")
        print("   Run: pip install asyncpg")
        return False
    except Exception as e:
        print(f"❌ ERROR: Connection failed!")
        print(f"   {type(e).__name__}: {e}")
        print("")
        print("Common issues:")
        print("  1. Wrong password in connection string")
        print("  2. Supabase project is paused (check dashboard)")
        print("  3. IP not allowed (check Supabase network settings)")
        print("  4. Wrong connection string format")
        return False

if __name__ == '__main__':
    success = test_connection()
    sys.exit(0 if success else 1)
