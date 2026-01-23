import argparse
import os

import requests

DEFAULT_BASE_URL = "http://localhost:8001"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a Linear issue update via webhook")
    parser.add_argument("--base-url", default=os.getenv("INTEGRATION_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--issue-id", default="LIN-123")
    args = parser.parse_args()

    payload = {
        "type": "Issue",
        "action": "update",
        "data": {
            "id": "linear-seed-1",
            "identifier": args.issue_id,
            "title": "Seeded Linear issue",
            "description": "Manual testing seed for integration",
            "state": {"name": "In Progress"},
            "team": {"name": "Platform"},
            "assignee": {"name": "Integration Tester"},
            "labels": [{"name": "seed"}],
        },
    }

    response = requests.post(f"{args.base_url.rstrip('/')}/api/webhooks/linear", json=payload, timeout=10)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
