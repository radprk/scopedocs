import pytest
import requests

from tests.integrations.conftest import integration_enabled, wait_for_condition
from tests.integrations.postgres_utils import fetch_relationship_count, postgres_enabled

pytestmark = pytest.mark.skipif(
    not integration_enabled(), reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests."
)


def test_github_pull_request_ingest_creates_relationship(base_url, stats_fetcher):
    linear_payload = {
        "type": "Issue",
        "action": "update",
        "data": {
            "id": "linear-issue-2",
            "identifier": "LIN-456",
            "title": "Integration test relationship",
            "description": "Seed for relationship test",
            "state": {"name": "In Progress"},
        },
    }
    requests.post(f"{base_url}/api/webhooks/linear", json=linear_payload, timeout=10).raise_for_status()

    before_stats = stats_fetcher()

    payload = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "LIN-456 Add webhook ingestion",
            "body": "Implements LIN-456 with webhook handling",
            "user": {"login": "tester"},
            "merged": False,
            "merged_at": None,
        },
        "repository": {"full_name": "example/scopedocs-test"},
    }

    response = requests.post(f"{base_url}/api/webhooks/github", json=payload, timeout=10)
    response.raise_for_status()

    def _stats_updated() -> bool:
        after_stats = stats_fetcher()
        return after_stats["pull_requests"] >= before_stats["pull_requests"] + 1

    wait_for_condition(_stats_updated)

    relationships = requests.get(f"{base_url}/api/relationships", timeout=10).json()
    assert any(rel.get("relationship_type") == "implements" for rel in relationships)

    if postgres_enabled():
        assert fetch_relationship_count() >= 1

    assert response.json().get("status") == "ok"
