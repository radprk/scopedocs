#!/usr/bin/env python3
"""
🔗 Backend Integrations Verification Script

Tests that Slack, GitHub, and Linear integrations are working.

Run from: /Users/radprk/scopedocs
Command: python scripts/verify_integrations.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

def header(text):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")

def success(text):
    print(f"{GREEN}✅ {text}{RESET}")

def fail(text):
    print(f"{RED}❌ {text}{RESET}")

def info(text):
    print(f"{YELLOW}ℹ️  {text}{RESET}")

def step(name):
    print(f"\n{BOLD}Testing: {name}{RESET}")
    print("-" * 40)


# =============================================================================
# Test GitHub
# =============================================================================
def test_github():
    step("GitHub Integration")
    
    token = os.environ.get('GITHUB_TOKEN')
    
    if not token:
        info("GITHUB_TOKEN not set")
        return None
    
    success(f"GITHUB_TOKEN found (starts with {token[:10]}...)")
    
    try:
        import httpx
        
        response = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            user = response.json()
            success(f"Authenticated as: {user.get('login')}")
            
            # Get repos
            repos_response = httpx.get(
                "https://api.github.com/user/repos?per_page=5",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if repos_response.status_code == 200:
                repos = repos_response.json()
                print(f"\n  Recent repos ({len(repos)} shown):")
                for repo in repos[:5]:
                    print(f"    - {repo['full_name']}")
                return True
        else:
            fail(f"GitHub API error: {response.status_code}")
            print(f"  Response: {response.text[:200]}")
            return False
            
    except Exception as e:
        fail(f"GitHub test failed: {e}")
        return False


# =============================================================================
# Test Slack
# =============================================================================
def test_slack():
    step("Slack Integration")
    
    token = os.environ.get('SLACK_BOT_TOKEN')
    
    if not token:
        info("SLACK_BOT_TOKEN not set")
        return None
    
    success(f"SLACK_BOT_TOKEN found (starts with {token[:15]}...)")
    
    try:
        import httpx
        
        # Test auth
        response = httpx.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        data = response.json()
        
        if data.get('ok'):
            success(f"Authenticated to workspace: {data.get('team')}")
            success(f"Bot user: {data.get('user')}")
            
            # Get channels
            channels_response = httpx.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 5, "types": "public_channel"}
            )
            
            channels_data = channels_response.json()
            
            if channels_data.get('ok'):
                channels = channels_data.get('channels', [])
                print(f"\n  Channels bot can see ({len(channels)} shown):")
                for ch in channels[:5]:
                    member = "✓ member" if ch.get('is_member') else "✗ not member"
                    print(f"    - #{ch['name']} ({member})")
            
            return True
        else:
            fail(f"Slack auth failed: {data.get('error')}")
            return False
            
    except Exception as e:
        fail(f"Slack test failed: {e}")
        return False


# =============================================================================
# Test Linear
# =============================================================================
def test_linear():
    step("Linear Integration")
    
    api_key = os.environ.get('LINEAR_API_KEY')
    
    if not api_key:
        info("LINEAR_API_KEY not set")
        return None
    
    success(f"LINEAR_API_KEY found (starts with {api_key[:15]}...)")
    
    try:
        import httpx
        
        query = """
        query {
            viewer {
                id
                name
                email
            }
            teams {
                nodes {
                    id
                    name
                }
            }
        }
        """
        
        response = httpx.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": api_key},
            json={"query": query}
        )
        
        data = response.json()
        
        if 'errors' in data:
            fail(f"Linear API error: {data['errors']}")
            return False
        
        viewer = data.get('data', {}).get('viewer', {})
        teams = data.get('data', {}).get('teams', {}).get('nodes', [])
        
        success(f"Authenticated as: {viewer.get('name')} ({viewer.get('email')})")
        
        print(f"\n  Teams:")
        for team in teams:
            print(f"    - {team['name']}")
        
        return True
            
    except Exception as e:
        fail(f"Linear test failed: {e}")
        return False


# =============================================================================
# Test Database
# =============================================================================
def test_database():
    step("Supabase Database")
    
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')
    
    if not dsn:
        info("POSTGRES_DSN not set")
        return None
    
    # Mask password for display
    import re
    masked = re.sub(r':([^@]+)@', ':***@', dsn)
    success(f"DSN found: {masked[:50]}...")
    
    try:
        import asyncio
        import asyncpg
        
        async def check_db():
            try:
                conn = await asyncpg.connect(dsn)
                success("Connected to Supabase!")
                
                # Check tables
                tables = await conn.fetch("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)
                
                print(f"\n  Tables in database ({len(tables)}):")
                for t in tables:
                    print(f"    - {t['table_name']}")
                
                await conn.close()
                return True
                
            except Exception as e:
                fail(f"Database connection failed: {e}")
                return False
        
        return asyncio.run(check_db())
        
    except ImportError:
        fail("asyncpg not installed")
        info("Run: pip install asyncpg")
        return False


# =============================================================================
# Main
# =============================================================================
def main():
    header("🔗 Backend Integrations Verification")
    
    results = {
        'github': test_github(),
        'slack': test_slack(),
        'linear': test_linear(),
        'database': test_database(),
    }
    
    header("📊 Summary")
    
    for name, result in results.items():
        if result is True:
            success(name.upper())
        elif result is None:
            info(f"{name.upper()} (not configured)")
        else:
            fail(name.upper())
    
    working = sum(1 for v in results.values() if v is True)
    total = len(results)
    
    print(f"\n{working}/{total} integrations working")


if __name__ == "__main__":
    main()
