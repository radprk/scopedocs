import os
import time
from typing import Callable, Dict

import pytest
import requests

DEFAULT_BASE_URL = "http://localhost:8001"


def _base_url() -> str:
    return os.getenv("INTEGRATION_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def base_url() -> str:
    return _base_url()


@pytest.fixture(scope="session")
def stats_fetcher(base_url: str) -> Callable[[], Dict[str, int]]:
    def _fetch() -> Dict[str, int]:
        response = requests.get(f"{base_url}/api/stats", timeout=10)
        response.raise_for_status()
        return response.json()

    return _fetch


def wait_for_condition(condition_fn: Callable[[], bool], timeout_s: float = 5.0, interval_s: float = 0.25) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition_fn():
            return
        time.sleep(interval_s)
    raise AssertionError("Timed out waiting for condition")


def integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS") == "1"

