"""Run actual paid/live acceptance with private credentials and a fresh legacy-test index.

Use the chosen Python environment to invoke this module (CUDA environment for GPU tests).
All real integrations remain opt-in via this explicit command; no provider fallback occurs.
"""

import argparse
import os
import subprocess
import sys
import uuid

from dotenv import dotenv_values

from scripts.common import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    private = dotenv_values(ROOT / "data/acceptance/service.env")
    if not private.get("KO_API_KEY") or not private.get("DEEPSEEK_API_KEY"):
        raise ValueError("Run scripts.prepare_acceptance first")
    # Qdrant Local's on-disk format is not a cross-client-version interchange format.
    # Preserve old indexes; each run rebuilds the legacy retrieval-substitute fixture from its public snapshots.
    root = ROOT / "data" / "acceptance" / ("deepseek-test-" + uuid.uuid4().hex)
    env = {**os.environ, **private, "KO_RUN_LIVE_TESTS": "1", "KO_TEST_BASE_URL": args.base_url,
           "KO_RUN_FOUR_CONTAINER_TESTS": "1", "KO_DOCKER_IN_WSL": "1" if args.wsl else "0",
           "KO_EXPERIMENT_DEVICE": args.device, "KO_RUN_DEEPSEEK_TESTS": "1",
           "KO_RUN_RETRIEVAL_TESTS": "1", "KO_RUN_RAG_TESTS": "1", "PYTHONUTF8": "1",
           "KO_DEEPSEEK_TEST_DATA_DIR": str(root)}
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", *args.tests,
               "--junitxml=reports/pytest.xml", "--cov=knowledgeops",
               "--cov-report=json:reports/coverage.json", "--cov-report=xml:reports/coverage.xml"]
    subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
