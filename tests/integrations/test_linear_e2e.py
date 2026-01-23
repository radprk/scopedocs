import pytest
import requests

from tests.integrations.conftest import integration_enabled, wait_for_condition
from tests.integrations.postgres_utils import fetch_table_counts, postgres_enabled

pytestmark = pytest.mark.skipif(
    not integration_enabled(), reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests."
)


def test_linear_issue_update(base_url, stats_fetcher):
    before_stats = stats_fetcher()

    payload = {
        "type": "Issue",
        "action": "update",
        "data": {
            "id": "linear-issue-1",
            "identifier": "LIN-123",
            "title": "Integration test issue",
            "description": "Checking webhook ingestion",
            "state": {"name": "In Progress"},
            "team": {"name": "Platform"},
            "assignee": {"name": "Dev Tester"},
            "labels": [{"name": "integration"}],
        },
    }

    response = requests.post(f"{base_url}/api/webhooks/linear", json=payload, timeout=10)
    response.raise_for_status()

    def _stats_updated() -> bool:
        after_stats = stats_fetcher()
        return after_stats["work_items"] >= before_stats["work_items"] + 1

    wait_for_condition(_stats_updated)

    if postgres_enabled():
        counts = fetch_table_counts()
        assert counts.get("work_items", 0) >= 1
        assert counts.get("artifact_events", 0) >= 1

    assert response.json().get("status") == "ok"
