"""Exercise real Docker containers, crash/recreate persistence and delete. Synthetic sentinel vectors only."""

import argparse
import json
import subprocess
import time
import uuid

import redis
from qdrant_client import QdrantClient, models

from scripts.common import REPORTS, ROOT, metadata, write_json


def compose(args, wsl):
    if wsl:
        cmd = [
            "wsl",
            "-d",
            "Ubuntu",
            "-u",
            "root",
            "--",
            "docker",
            "compose",
            "--project-directory",
            "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:],
            "-f",
            "compose.retrieval.yaml",
            *args,
        ]
    else:
        cmd = ["docker", "compose", "-f", str(ROOT / "compose.retrieval.yaml"), *args]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError("Compose failed: " + result.stderr.decode("utf-8", errors="replace")[-2000:])
    return result.stdout.decode("utf-8", errors="replace")


def main(wsl=False):
    report = {
        "metadata": metadata("real_infrastructure"),
        "synthetic_probe": "sentinel vectors; not retrieval quality data",
        "checks": {},
        "compose_file": "compose.retrieval.yaml",
    }
    client = QdrantClient(url="http://127.0.0.1:6333", timeout=10)
    cache = redis.Redis(host="127.0.0.1", port=6379)
    name = "ko_persistence_" + uuid.uuid4().hex
    key = "knowledgeops:persistence:" + uuid.uuid4().hex
    try:
        report["compose_before"] = compose(["ps", "--format", "json"], wsl)
        report["server_version"] = client.info().version
        existing = {c.name: client.count(c.name).count for c in client.get_collections().collections}
        report["preexisting_collections"] = existing
        client.create_collection(
            name, vectors_config=models.VectorParams(size=8, distance=models.Distance.COSINE)
        )
        point_id = str(uuid.uuid4())
        client.upsert(
            name,
            points=[models.PointStruct(id=point_id, vector=[1.0] + [0.0] * 7, payload={"probe": "persist"})],
            wait=True,
        )
        cache.set(key, "persisted")
        cache.execute_command("WAITAOF", 1, 0, 5000)
        report["checks"]["write"] = client.count(name).count == 1 and cache.get(key) == b"persisted"
        # Stop is a real container/process termination. Recreate removes old containers but retains named volumes.
        compose(["stop", "qdrant", "redis"], wsl)
        compose(["up", "-d", "--force-recreate", "qdrant", "redis"], wsl)
        deadline = time.monotonic() + 45
        while True:
            try:
                if cache.ping() and client.collection_exists(name):
                    break
            except Exception:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("Containers did not recover")
            time.sleep(0.5)
        report["checks"]["persistence_after_container_recreation"] = (
            client.count(name).count == 1 and cache.get(key) == b"persisted"
        )
        report["collections_after_recreation"] = {name: client.count(name).count for name in existing}
        report["checks"]["existing_real_indexes_preserved"] = (
            existing == report["collections_after_recreation"]
        )
        hits = client.query_points(name, query=[1.0] + [0.0] * 7, limit=1).points
        report["checks"]["search"] = len(hits) == 1 and str(hits[0].id) == point_id
        client.delete(name, points_selector=models.PointIdsList(points=[point_id]), wait=True)
        report["checks"]["delete"] = client.count(name).count == 0
        report["compose_after"] = compose(["ps", "--format", "json"], wsl)
        report["passed"] = all(report["checks"].values())
    except Exception as exc:
        report.update(passed=False, error=type(exc).__name__ + ": " + str(exc))
    finally:
        try:
            client.delete_collection(name)
            cache.delete(key)
        except Exception:
            pass
        client.close()
        cache.close()
    write_json(REPORTS / "real-infrastructure.json", report)
    print(json.dumps(report["checks"], indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wsl", action="store_true")
    main(parser.parse_args().wsl)
