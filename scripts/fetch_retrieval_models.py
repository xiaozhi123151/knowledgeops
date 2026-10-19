"""Download pinned first-party dense/reranker files, without optional ONNX/ColBERT/sparse weights."""

import hashlib
import json

from huggingface_hub import snapshot_download

from scripts.common import ROOT, write_json


def main():
    records = []
    pins = json.loads((ROOT / "evals" / "public_technical" / "models.json").read_text(encoding="utf-8"))
    for pin in pins:
        model, revision = pin["model"], pin["revision"]
        path = ROOT / "data" / "models" / model.split("/")[-1]
        print(f"Downloading {model}@{revision}", flush=True)
        weight = path / pin["weight_file"]
        already_valid = False
        if weight.exists():
            with weight.open("rb") as stream:
                already_valid = hashlib.file_digest(stream, "sha256").hexdigest() == pin["weight_sha256"]
        if not already_valid:
            snapshot_download(
                model,
                revision=revision,
                local_dir=path,
                max_workers=3,
                allow_patterns=["*.json", "*.model", pin["weight_file"], "1_Pooling/*", "README.md"],
                ignore_patterns=["onnx/*"],
            )
        with weight.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != pin["weight_sha256"]:
            raise ValueError("MODEL_WEIGHT_SHA256_MISMATCH: " + model)
        records.append(
            {
                "model": model,
                "revision": revision,
                "path": path.relative_to(ROOT).as_posix(),
                "weight_sha256": digest,
                "weight_bytes": weight.stat().st_size,
                "files": [
                    {"name": str(f.relative_to(path)), "bytes": f.stat().st_size}
                    for f in path.rglob("*")
                    if f.is_file() and ".cache" not in f.parts
                ],
            }
        )
        write_json(ROOT / "data" / "models" / "manifest.json", records)
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
