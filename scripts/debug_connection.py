#!/usr/bin/env python3
"""Debug script to test Supabase connection."""
import asyncio
import os
import sys
import re
from pathlib import Path

# Load .env
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / 'backend' / '.env'
print(f"Loading .env from: {env_path}")
print(f"File exists: {env_path.exists()}")
load_dotenv(env_path)

dsn = os.environ.get('POSTGRES_DSN')
print(f"\nPOSTGRES_DSN loaded: {dsn is not None}")
if dsn:
    # Mask password for display
    masked = re.sub(r':([^:@]+)@', r':****@', dsn)
    print(f"DSN (masked): {masked}")

# Parse manually
def parse_dsn(dsn):
    pattern = r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
    match = re.match(pattern, dsn)
    if not match:
        raise ValueError(f"Invalid DSN format")
    return {
        'user': match.group(1),
        'password': match.group(2),
        'host': match.group(3),
        'port': int(match.group(4)),
        'database': match.group(5),
    }

if dsn:
    print("\nParsing DSN...")
    try:
        config = parse_dsn(dsn)
        print(f"  user: {config['user']}")
        print(f"  host: {config['host']}")
        print(f"  port: {config['port']}")
        print(f"  database: {config['database']}")
        print(f"  password: {'*' * len(config['password'])}")
    except Exception as e:
        print(f"  Parse error: {e}")
        sys.exit(1)

    print("\nTrying asyncpg connection...")
    import asyncpg

    async def test():
        try:
            print(f"  Connecting with ssl='require'...")
            conn = await asyncpg.connect(
                user=config['user'],
                password=config['password'],
                host=config['host'],
                port=config['port'],
                database=config['database'],
                ssl='require'
            )
            print("  ✅ Connected!")
            version = await conn.fetchval("SELECT version()")
            print(f"  PostgreSQL: {version[:50]}...")
            await conn.close()
        except Exception as e:
            print(f"  ❌ Connection error: {e}")
            import traceback
            traceback.print_exc()

    asyncio.run(test())
else:
    print("❌ POSTGRES_DSN not set!")
