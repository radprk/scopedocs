import argparse
import os

import requests

DEFAULT_BASE_URL = "http://localhost:8001"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a Slack message event via webhook")
    parser.add_argument("--base-url", default=os.getenv("INTEGRATION_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--issue-id", default="LIN-123")
    args = parser.parse_args()

    payload = {
        "type": "event_callback",
        "event_id": "EvSeedSlack",
        "event": {
            "type": "message",
            "channel": "C999",
            "user": "U999",
            "text": f"Seeding Slack message for {args.issue_id}",
            "event_ts": "1710000000.999900",
        },
    }

    response = requests.post(f"{args.base_url.rstrip('/')}/api/webhooks/slack", json=payload, timeout=10)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
