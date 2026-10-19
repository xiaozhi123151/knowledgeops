"""Real HTTP + Redis durable queue + killed/restarted Worker acceptance; no provider substitutes.

Start compose.yaml + compose.acceptance.yaml first. Credentials are loaded privately.
Run --wsl when Docker is hosted in WSL2 rather than the Windows host.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time

import httpx
from dotenv import dotenv_values

from scripts.common import REPORTS, ROOT, metadata, request, wait_task, write_json


class Compose:
    def __init__(self, wsl):
        self.prefix = ["wsl", "-d", "Ubuntu", "-u", "root", "--"] if wsl else []
        self.folder = str(ROOT)
        if wsl:
            self.folder = "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:]

    def run(self, *args):
        command = ["docker", "compose", "--project-directory", self.folder,
                   "--env-file", self.folder + "/data/acceptance/compose.env", "-p", "knowledgeops-acceptance",
                   "-f", self.folder + "/compose.yaml", "-f", self.folder + "/compose.acceptance.yaml", *args]
        return subprocess.run(self.prefix + command, capture_output=True, timeout=90, check=True).stdout.decode()

    def inventory(self):
        return [json.loads(line) for line in self.run("ps", "--format", "json").splitlines() if line.strip()]


def verify(wsl=False, base_url="http://127.0.0.1:18000"):
    private = {**dotenv_values(ROOT / "data/acceptance/service.env"), **os.environ}
    key = private.get("KO_API_KEY")
    if not key:
        raise ValueError("Run scripts.prepare_acceptance first")
    compose = Compose(wsl)
    report = {"metadata": metadata("real_four_container"), "base_url": base_url, "checks": {},
              "configuration": "compose.yaml + compose.acceptance.yaml; CPU float32 BGE pair, real DeepSeek"}
    target = REPORTS / "four-container.json"
    try:
        before = compose.inventory()
        report["containers_before"] = [{k: r.get(k) for k in ("ID", "Service", "Image", "State", "Health")}
                                       for r in before]
        assert {r["Service"] for r in before if r["State"] == "running"} == {"api", "worker", "qdrant", "redis"}
        # Verify deployed source, rather than assuming a tag was rebuilt/recreated correctly.
        source_code = (
            "import hashlib,json,sys; from pathlib import Path; from importlib.metadata import version; "
            "root=Path('/app/src'); h=hashlib.sha256(); "
            "files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix in "
            "('.py','.js','.css','.html','.tiktoken')); "
            "[(h.update(p.relative_to(root).as_posix().encode()+b'\\0'+p.read_bytes())) for p in files]; "
            "print(json.dumps({'source_sha256':h.hexdigest(),'files':len(files),'python':sys.version.split()[0],"
            "'dependencies':{n:version(n) for n in ['torch','sentence-transformers','transformers','qdrant-client']}}))"
        )
        local_hash = hashlib.sha256()
        for path in sorted(p for p in (ROOT / "src").rglob("*") if p.is_file()
                           and p.suffix in (".py", ".js", ".css", ".html", ".tiktoken")):
            local_hash.update(path.relative_to(ROOT / "src").as_posix().encode() + b"\0" + path.read_bytes())
        report["deployed_environment"] = {}
        for service in ("api", "worker"):
            actual = json.loads(compose.run("exec", "-T", service, "python", "-c", source_code))
            report["deployed_environment"][service] = actual
            assert actual["source_sha256"] == local_hash.hexdigest(), "Deployed source differs from checkout"
            assert "+cpu" in actual["dependencies"]["torch"]
        report["checks"]["both_container_sources_match_checkout"] = True
        with httpx.Client(base_url=base_url, headers={"X-API-Key": key}, timeout=190) as client:
            ready = client.get("/health/ready")
            ready.raise_for_status()
            info = ready.json()
            report["readiness"] = info
            assert info["mode"] == "live" and not info["llm_is_mock"] and not info["retrieval_is_mock"]
            assert info["llm_provider"] == "deepseek" and info["qdrant_backend"] == "server"
            report["checks"]["four_live_services"] = True
            compose.run("kill", "-s", "SIGKILL", "worker")
            # restart: unless-stopped may restart a killed service; explicitly stop to test queued durability.
            compose.run("stop", "worker")
            payload = b"Four-container durable queue probe: Redis AOF persists writes to an append-only file."
            created = request(client, "POST", "/documents", files={"file": ("four-container-probe.txt", payload)})
            task_id = created["task_id"]
            time.sleep(2)
            queued = request(client, "GET", "/tasks/" + task_id)
            assert queued["status"] == "queued", queued["status"]
            report["checks"]["api_queues_while_worker_stopped"] = True
            report["queued_task_id"] = task_id
            compose.run("start", "worker")
            completed = wait_task(client, task_id, timeout=600)
            assert completed["status"] == "succeeded", completed["error"]
            report["checks"]["restarted_worker_consumes_durable_task"] = True
            report["ingest_result"] = completed["result"]
            result = request(client, "POST", "/query", json={"query": "What does Redis AOF persist?", "rerank": True})
            assert result["hits"] and result["hits"][0]["rerank_score"] is not None
            report["query"] = result
            report["checks"]["real_dense_hybrid_cross_encoder"] = True
            # PDF upload is a real HTTP request, processed only by the separate worker.
            created = request(client, "POST", "/documents",
                              files={"file": ("sample.pdf", (ROOT / "examples/sample.pdf").read_bytes())})
            pdf = wait_task(client, created["task_id"], timeout=600)
            assert pdf["status"] == "succeeded", pdf["error"]
            report["checks"]["pdf_http_ingestion"] = True
            t = time.perf_counter()
            created = request(client, "POST", "/research", json={"question":
                "Explain Redis AOF persistence using the imported documents. Compare any available evidence, "
                "call knowledge_search, compare_evidence and build_report, cite exact sources, "
                "and state if production throughput cannot be confirmed."})
            # Kill a real worker after an actual paid LLM call; verify persisted budget/checkpoint recovery.
            deadline = time.monotonic() + 180
            while True:
                checkpoint_events = request(client, "GET", "/tasks/" + created["task_id"] + "/events")["events"]
                partial = request(client, "GET", "/tasks/" + created["task_id"])
                if any(e["type"] == "llm_completed" for e in checkpoint_events):
                    break
                assert partial["status"] not in ("failed", "succeeded"), "No interruption window after LLM call"
                if time.monotonic() > deadline:
                    raise TimeoutError("No completed LLM call before interruption")
                time.sleep(0.2)
            compose.run("kill", "-s", "SIGKILL", "worker")
            compose.run("stop", "worker")
            interrupted = request(client, "GET", "/tasks/" + created["task_id"])
            assert interrupted["budget"]["llm_calls"] > 0 and interrupted["budget"]["tokens"] > 0
            report["budget_at_worker_kill"] = interrupted["budget"]
            compose.run("start", "worker")
            task = wait_task(client, created["task_id"], timeout=600)
            report["research_elapsed_ms"] = (time.perf_counter() - t) * 1000
            report["research"] = task
            events = request(client, "GET", "/tasks/" + created["task_id"] + "/events")["events"]
            report["events"] = events
            assert task["status"] == "succeeded", task["error"]
            assert task["budget"]["llm_calls"] > 0 and task["budget"]["tool_calls"] > 0
            assert task["budget"]["tokens"] > 0 and not task["budget"]["estimated"]
            assert task["budget"]["llm_calls"] >= interrupted["budget"]["llm_calls"]
            assert task["budget"]["tokens"] >= interrupted["budget"]["tokens"]
            assert any(e["type"] == "claimed" and e["data"].get("resumed") for e in events)
            report["checks"]["inflight_worker_sigkill_checkpoint_and_budget_recovery"] = True
            tool_names = {e["data"]["name"] for e in events if e["type"] == "tool_started"}
            assert {"knowledge_search", "compare_evidence", "build_report"} <= tool_names
            report["tool_names"] = sorted(tool_names)
            citations = task["result"]["citations"]
            assert citations
            for citation in citations:
                chunk = request(client, "GET", f"/documents/{citation['doc_id']}/chunks/{citation['chunk_id']}")
                assert citation["quote"] in chunk["text"]
            report["checks"]["deepseek_tool_call_and_exact_citations"] = True
            report["validated_citations"] = len(citations)
        report["containers_after"] = [{k: r.get(k) for k in ("ID", "Service", "Image", "State", "Health")}
                                      for r in compose.inventory()]
        report["passed"] = True
    except Exception as exc:
        # Exception bodies from external SDKs can contain secrets; record type only.
        report.update(passed=False, error_type=type(exc).__name__)
        raise
    finally:
        write_json(target, report)
        print(json.dumps({"passed": report.get("passed"), "checks": report["checks"]}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    verify(args.wsl, args.base_url)
