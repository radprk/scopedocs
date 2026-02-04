#!/usr/bin/env python3
"""
🧪 Multi-Tenant OAuth Test Script

Tests the OAuth flow for each provider and verifies org IDs are captured.

Usage:
1. Start the server: uvicorn backend.server:app --reload --port 8000
2. Start ngrok: ngrok http 8000
3. Update BASE_URL in backend/.env with ngrok URL
4. Run this script for guidance
"""

import os
import sys
import asyncio
import asyncpg
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
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

def link(text, url):
    print(f"{CYAN}🔗 {text}:{RESET}")
    print(f"   {BOLD}{url}{RESET}")
    print()


async def get_workspace_info():
    """Get the ScopeDocs workspace info."""
    dsn = os.environ.get('POSTGRES_DSN')
    conn = await asyncpg.connect(dsn)
    
    workspace = await conn.fetchrow(
        "SELECT * FROM workspaces WHERE slug = 'scopedocs'"
    )
    
    if not workspace:
        fail("ScopeDocs workspace not found!")
        return None
    
    # Get connected integrations
    tokens = await conn.fetch("""
        SELECT integration, data FROM integration_tokens 
        WHERE workspace_id = $1
    """, str(workspace['id']))
    
    await conn.close()
    
    return {
        'id': str(workspace['id']),
        'name': workspace['name'],
        'github_org_id': workspace['github_org_id'],
        'slack_team_id': workspace['slack_team_id'],
        'linear_org_id': workspace['linear_org_id'],
        'tokens': {t['integration']: t['data'] for t in tokens}
    }


def main():
    header("🧪 Multi-Tenant OAuth Test")
    
    base_url = os.environ.get('BASE_URL', 'http://localhost:8000')
    
    # Check if ngrok is set up
    if 'localhost' in base_url:
        info("BASE_URL is localhost - OAuth callbacks won't work!")
        info("Start ngrok and update BASE_URL in backend/.env")
        print()
    
    # Get workspace info
    workspace = asyncio.run(get_workspace_info())
    
    if not workspace:
        return
    
    print(f"📦 Workspace: {workspace['name']}")
    print(f"   ID: {workspace['id']}")
    print()
    
    # Show current state
    print("📊 Current Integration Status:")
    print("-" * 40)
    
    # GitHub
    if 'github' in workspace['tokens']:
        meta = workspace['tokens']['github']
        success(f"GitHub: Connected as {meta.get('user_login')}")
        if meta.get('org_login'):
            print(f"        Org: {meta.get('org_login')} (ID: {meta.get('org_id')})")
        if workspace['github_org_id']:
            success(f"        Workspace org_id set: {workspace['github_org_id']}")
    else:
        info("GitHub: Not connected")
    
    # Slack
    if 'slack' in workspace['tokens']:
        meta = workspace['tokens']['slack']
        success(f"Slack: Connected to {meta.get('team_name')}")
        print(f"        Team ID: {meta.get('team_id')}")
        if workspace['slack_team_id']:
            success(f"        Workspace team_id set: {workspace['slack_team_id']}")
    else:
        info("Slack: Not connected")
    
    # Linear
    if 'linear' in workspace['tokens']:
        meta = workspace['tokens']['linear']
        success(f"Linear: Connected to {meta.get('org_name')}")
        print(f"        Org ID: {meta.get('org_id')}")
        if workspace['linear_org_id']:
            success(f"        Workspace org_id set: {workspace['linear_org_id']}")
    else:
        info("Linear: Not connected")
    
    print()
    
    # Show OAuth URLs
    header("🔗 OAuth Connect URLs")
    
    print(f"Use workspace_id: {workspace['id']}")
    print()
    
    link("GitHub OAuth", 
         f"{base_url}/api/oauth/github/connect?workspace_id={workspace['id']}")
    
    link("Slack OAuth (User Token)", 
         f"{base_url}/api/oauth/slack/connect?workspace_id={workspace['id']}")
    
    link("Linear OAuth", 
         f"{base_url}/api/oauth/linear/connect?workspace_id={workspace['id']}")
    
    # Instructions
    header("📝 Test Steps")
    
    print("1. Make sure server is running:")
    print(f"   {CYAN}uvicorn backend.server:app --reload --port 8000{RESET}")
    print()
    
    print("2. Make sure ngrok is pointing to port 8000:")
    print(f"   {CYAN}ngrok http 8000{RESET}")
    print()
    
    print("3. Update BASE_URL in backend/.env with ngrok URL")
    print()
    
    print("4. Click each OAuth link above to connect")
    print()
    
    print("5. After connecting, run this script again to verify org IDs were captured")
    print()
    
    # Multi-tenant verification
    header("🔒 Multi-Tenant Verification")
    
    all_orgs_set = all([
        workspace['github_org_id'] if 'github' in workspace['tokens'] else True,
        workspace['slack_team_id'] if 'slack' in workspace['tokens'] else True,
        workspace['linear_org_id'] if 'linear' in workspace['tokens'] else True,
    ])
    
    if all_orgs_set and len(workspace['tokens']) > 0:
        success("Multi-tenant setup verified!")
        print()
        print("When another user connects the same GitHub org, Slack workspace,")
        print("or Linear team, they can be auto-joined to this workspace (future feature).")
    else:
        info("Connect integrations to verify multi-tenant org ID capture")


if __name__ == "__main__":
    main()
