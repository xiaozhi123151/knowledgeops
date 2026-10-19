"""Pinned CPython release/library documentation, plus existing first-party DeepSeek snapshots."""

import hashlib
from datetime import datetime, timezone

import httpx

from scripts.common import ROOT, write_json

CORPUS = ROOT / "evals" / "public_technical"


def main():
    target = CORPUS / "documents"
    target.mkdir(parents=True, exist_ok=True)
    records = []
    paths = [
        (f"python-{v}", f"v{v}.0", f"Doc/whatsnew/{v}.rst")
        for v in ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"]
    ]
    paths += [
        (name, "v3.12.0", f"Doc/library/{name}.rst")
        for name in [
            "asyncio-task",
            "asyncio-sync",
            "asyncio-queue",
            "asyncio-stream",
            "asyncio-subprocess",
            "concurrent.futures",
        ]
    ]
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for name, tag, path in paths:
            url = f"https://raw.githubusercontent.com/python/cpython/{tag}/{path}"
            response = client.get(url)
            response.raise_for_status()
            # RST is imported as plain text: retain source syntax for exact anchors, no rewritten summaries.
            data = response.content
            (target / (name + ".txt")).write_bytes(data)
            records.append(
                {
                    "id": name,
                    "filename": name + ".txt",
                    "url": url,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "downloaded_utc": datetime.now(timezone.utc).isoformat(),
                    "license": "PSF-2.0",
                }
            )
    for name in ["DeepSeek-V2", "DeepSeek-V3", "DeepSeek-V4.1-Flash"]:
        import json

        old = ROOT / "data" / "deepseek_validation" / "documents"
        record = next(
            s
            for s in json.loads((old / "manifest.json").read_text(encoding="utf-8"))["documents"]
            if s["version"] == name
        )
        data = (old / record["filename"]).read_bytes()
        (target / (name + ".md")).write_bytes(data)
        records.append(
            {
                "id": name,
                "filename": name + ".md",
                "url": record["url"],
                "sha256": hashlib.sha256(data).hexdigest(),
                "downloaded_utc": record.get("downloaded_utc"),
                "license": "see upstream model card/repository",
            }
        )
    write_json(CORPUS / "manifest.json", {"sources": records})
    print(
        f"Fetched {len(records)} original documents; bytes={sum(f.stat().st_size for f in target.iterdir())}"
    )


if __name__ == "__main__":
    main()
