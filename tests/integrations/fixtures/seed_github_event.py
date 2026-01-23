import argparse
import os

import requests

DEFAULT_BASE_URL = "http://localhost:8001"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a GitHub pull_request event via webhook")
    parser.add_argument("--base-url", default=os.getenv("INTEGRATION_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--issue-id", default="LIN-123")
    parser.add_argument("--pr-number", type=int, default=100)
    args = parser.parse_args()

    payload = {
        "action": "opened",
        "pull_request": {
            "number": args.pr_number,
            "title": f"{args.issue_id} Add integration webhook",
            "body": f"Implements {args.issue_id} for testing",
            "user": {"login": "integration-bot"},
            "merged": False,
            "merged_at": None,
        },
        "repository": {"full_name": "example/scopedocs-test"},
    }

    response = requests.post(f"{args.base_url.rstrip('/')}/api/webhooks/github", json=payload, timeout=10)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
