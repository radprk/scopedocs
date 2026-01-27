#!/usr/bin/env python3
"""
ScopeDocs Integration Test Suite
Run: python scripts/test_app.py

Tests the full flow: signup → connect → sync → query
"""
import sys
import httpx
import json
import time

BASE = "http://localhost:8000"
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
INFO = "\033[94mINFO\033[0m"

results = {"pass": 0, "fail": 0, "skip": 0}


def test(name, response, expected_status=200):
    """Check a response and print result."""
    ok = response.status_code == expected_status
    status = PASS if ok else FAIL
    results["pass" if ok else "fail"] += 1
    print(f"  [{status}] {name} (HTTP {response.status_code})")
    if not ok:
        print(f"         Expected {expected_status}, body: {response.text[:200]}")
    return ok


def skip(name, reason):
    results["skip"] += 1
    print(f"  [{SKIP}] {name} - {reason}")


def main():
    email = f"test-{int(time.time())}@scopedocs.ai"
    print(f"\n{'='*60}")
    print(f"  ScopeDocs Test Suite")
    print(f"  Server: {BASE}")
    print(f"  Test user: {email}")
    print(f"{'='*60}\n")

    client = httpx.Client(base_url=BASE, timeout=30)

    # ---- Health ----
    print("1. Health Check")
    r = client.get("/health")
    test("GET /health", r)

    # ---- Auth ----
    print("\n2. Authentication")
    r = client.post(f"/auth/signup?email={email}&name=Test+User")
    test("POST /auth/signup (new user)", r)
    token = r.json().get("user_id") if r.status_code == 200 else None

    if not token:
        print(f"\n  [{FAIL}] Cannot continue without token")
        return

    headers = {"Authorization": f"Bearer {token}"}
    print(f"  [{INFO}] Token: {token}")

    # Signup again (should return same user)
    r = client.post(f"/auth/signup?email={email}&name=Test+User")
    test("POST /auth/signup (existing user)", r)
    same_id = r.json().get("user_id") == token if r.status_code == 200 else False
    print(f"  [{PASS if same_id else FAIL}] Returns same user_id for same email")

    r = client.get("/auth/me", headers=headers)
    test("GET /auth/me", r)
    if r.status_code == 200:
        user = r.json()
        print(f"  [{INFO}] User: {user.get('name')} ({user.get('email')})")
        print(f"  [{INFO}] Integrations: {[i['provider'] for i in user.get('integrations', [])]}")

    # Bad token
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-uuid"})
    test("GET /auth/me (bad token) → 401", r, 401)

    # ---- OAuth URLs ----
    print("\n3. OAuth Authorize URLs")
    for provider in ["linear", "github", "slack"]:
        r = client.get(f"/oauth/{provider}/authorize", headers=headers)
        if r.status_code == 200:
            url = r.json().get("authorize_url", "")
            has_client_id = "client_id=None" not in url and "client_id=&" not in url
            test(f"GET /oauth/{provider}/authorize", r)
            if has_client_id:
                print(f"  [{PASS}] {provider} client_id is set")
            else:
                print(f"  [{FAIL}] {provider} client_id is MISSING - add {provider.upper()}_CLIENT_ID to .env")
                results["fail"] += 1
        else:
            test(f"GET /oauth/{provider}/authorize", r)

    r = client.get("/oauth/invalid/authorize", headers=headers)
    test("GET /oauth/invalid/authorize → 400", r, 400)

    # ---- Integrations (repos/channels) ----
    print("\n4. Integration Data (repos/channels)")
    r = client.get("/integrations/github/repos", headers=headers)
    if r.status_code == 200:
        data = r.json()
        repo_count = len(data.get("repos", []))
        test("GET /integrations/github/repos", r)
        source = "OAuth" if data.get("account", {}).get("user_name") else "ENV token"
        print(f"  [{INFO}] Source: {source}, Repos: {repo_count}")
        if repo_count > 0:
            print(f"  [{INFO}] First 3: {[r['full_name'] for r in data['repos'][:3]]}")
    else:
        skip("GET /integrations/github/repos", "GitHub not connected and no GITHUB_TOKEN in .env")

    r = client.get("/integrations/slack/channels", headers=headers)
    if r.status_code == 200:
        data = r.json()
        ch_count = len(data.get("channels", []))
        test("GET /integrations/slack/channels", r)
        source = "OAuth" if data.get("account", {}).get("team_name") else "ENV token"
        print(f"  [{INFO}] Source: {source}, Channels: {ch_count}")
        if ch_count > 0:
            print(f"  [{INFO}] First 3: {[c['name'] for c in data['channels'][:3]]}")
    else:
        skip("GET /integrations/slack/channels", "Slack not connected and no SLACK_BOT_TOKEN in .env")

    # ---- Sync ----
    print("\n5. Data Sync")

    # Linear
    r = client.post("/sync/linear", headers=headers)
    test("POST /sync/linear", r)
    if r.status_code == 200:
        data = r.json()
        if "linear_issues" in data:
            print(f"  [{INFO}] Synced {data['linear_issues']} issues")
        elif "linear_error" in data:
            print(f"  [{INFO}] {data['linear_error']}")

    # GitHub (need repos)
    r = client.post("/sync/github?repos=radprk/scopedocs", headers=headers)
    test("POST /sync/github?repos=radprk/scopedocs", r)
    if r.status_code == 200:
        data = r.json()
        if "github_prs" in data:
            print(f"  [{INFO}] Synced {data['github_prs']} PRs")
        elif "github_error" in data:
            print(f"  [{INFO}] {data['github_error']}")

    # GitHub without repos
    r = client.post("/sync/github", headers=headers)
    test("POST /sync/github (no repos)", r)

    # Slack (need channels)
    r = client.post("/sync/slack?channels=team-core", headers=headers)
    test("POST /sync/slack?channels=team-core", r)
    if r.status_code == 200:
        data = r.json()
        if "slack_messages" in data:
            print(f"  [{INFO}] Synced {data['slack_messages']} messages")
        elif "slack_error" in data:
            print(f"  [{INFO}] {data['slack_error']}")

    # ---- Query ----
    print("\n6. Query Endpoints")

    r = client.get("/stats", headers=headers)
    test("GET /stats", r)
    if r.status_code == 200:
        stats = r.json()
        print(f"  [{INFO}] Issues: {stats.get('linear_issues', 0)}, PRs: {stats.get('github_prs', 0)}, "
              f"Messages: {stats.get('slack_messages', 0)}, Links: {stats.get('links', 0)}")

    r = client.get("/issues?limit=5", headers=headers)
    test("GET /issues", r)
    if r.status_code == 200:
        issues = r.json()
        print(f"  [{INFO}] Returned {len(issues)} issues")
        if issues:
            first = issues[0]
            issue_id = first.get("identifier")
            print(f"  [{INFO}] First: {issue_id} - {first.get('title', '')[:50]}")

            # Context
            r = client.get(f"/context/{issue_id}", headers=headers)
            test(f"GET /context/{issue_id}", r)
            if r.status_code == 200:
                ctx = r.json()
                print(f"  [{INFO}] PRs: {len(ctx.get('prs', []))}, Discussions: {len(ctx.get('discussions', []))}")

    r = client.get("/context/NONEXISTENT-999", headers=headers)
    test("GET /context/NONEXISTENT-999 → 404", r, 404)

    r = client.get("/search?q=test", headers=headers)
    test("GET /search?q=test", r)
    if r.status_code == 200:
        data = r.json()
        total = len(data.get("issues", [])) + len(data.get("prs", [])) + len(data.get("messages", []))
        print(f"  [{INFO}] Search results: {total}")

    # ---- Multi-tenant isolation ----
    print("\n7. Multi-tenant Isolation")
    other_email = f"other-{int(time.time())}@example.com"
    r = client.post(f"/auth/signup?email={other_email}&name=Other+User")
    other_token = r.json().get("user_id") if r.status_code == 200 else None
    other_headers = {"Authorization": f"Bearer {other_token}"}

    r = client.get("/stats", headers=other_headers)
    test("GET /stats (other user)", r)
    if r.status_code == 200:
        stats = r.json()
        all_zero = all(v == 0 for v in stats.values())
        status = PASS if all_zero else FAIL
        results["pass" if all_zero else "fail"] += 1
        print(f"  [{status}] New user sees zero data (tenant isolation)")

    r = client.get("/issues", headers=other_headers)
    test("GET /issues (other user)", r)
    if r.status_code == 200:
        status = PASS if len(r.json()) == 0 else FAIL
        results["pass" if len(r.json()) == 0 else "fail"] += 1
        print(f"  [{status}] New user sees no issues (tenant isolation)")

    # ---- Summary ----
    print(f"\n{'='*60}")
    total = results["pass"] + results["fail"] + results["skip"]
    print(f"  Results: {results['pass']} passed, {results['fail']} failed, {results['skip']} skipped ({total} total)")
    if results["fail"] == 0:
        print(f"  \033[92mAll tests passed!\033[0m")
    else:
        print(f"  \033[91m{results['fail']} tests failed\033[0m")
    print(f"{'='*60}\n")

    return results["fail"]


if __name__ == "__main__":
    sys.exit(main())
