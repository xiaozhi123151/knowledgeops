"""Runs against four actual services and interrupts the real worker. Paid API opt-in."""

import os

import pytest


@pytest.mark.live
def test_four_container_real_worker_restart_and_citations():
    if os.getenv("KO_RUN_FOUR_CONTAINER_TESTS") != "1":
        pytest.skip("UNVERIFIED: set KO_RUN_FOUR_CONTAINER_TESTS=1 with the actual four-service acceptance stack")
    from scripts.verify_four_container import verify

    report = verify(wsl=os.getenv("KO_DOCKER_IN_WSL") == "1",
                    base_url=os.getenv("KO_TEST_BASE_URL", "http://127.0.0.1:18000"))
    assert report["passed"] and all(report["checks"].values())
    assert report["validated_citations"] > 0
