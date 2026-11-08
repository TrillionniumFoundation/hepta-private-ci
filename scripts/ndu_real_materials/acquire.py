"""Acquire fixed public SROIE bytes; no actor, evaluation, or confirmation access."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.request

REPOSITORY = "jsdnrs/ICDAR2019-SROIE"
REVISION = "bffe40c26759f3376ec2b3ae9031dbba54cd587c"
FILES = (
    "README.md",
    "LICENSE",
    "NOTICE",
    "data/train-00000-of-00001.parquet",
    "data/test-00000-of-00001.parquet",
)
MAX_FILE_BYTES = 512 * 1024 * 1024


def acquire(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    upstream = root / "private" / "upstream"
    upstream.mkdir(parents=True, mode=0o700)
    (root / "private").chmod(0o700)
    started = time.perf_counter()
    metadata_url = f"https://huggingface.co/api/datasets/{REPOSITORY}/revision/{REVISION}?blobs=true"
    with urllib.request.urlopen(metadata_url, timeout=90) as response:
        metadata_bytes = response.read(2 * 1024 * 1024)
    metadata = json.loads(metadata_bytes)
    if metadata.get("sha") != REVISION:
        raise ValueError(
            "Dataset revision did not match the prospectively fixed source"
        )
    (upstream / "repository.json").write_bytes(metadata_bytes)
    entries = {row["rfilename"]: row for row in metadata["siblings"]}

    def download(relative):
        begin = time.perf_counter()
        url = f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{REVISION}/{relative}"
        target = upstream / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "path": str(target.relative_to(root)),
            "source_url": url,
            "status": "Failed",
            "bytes": 0,
            "sha256": None,
            "error": None,
        }
        digest = hashlib.sha256()
        try:
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                target.open("xb") as output,
            ):
                while block := response.read(1024 * 1024):
                    record["bytes"] += len(block)
                    if record["bytes"] > MAX_FILE_BYTES:
                        raise ValueError(
                            "Public source exceeds the declared byte bound"
                        )
                    digest.update(block)
                    output.write(block)
            record["sha256"] = digest.hexdigest()
            lfs = entries[relative].get("lfs", {})
            expected = lfs.get("sha256") or lfs.get("oid")
            if expected and expected.removeprefix("sha256:") != record["sha256"]:
                raise ValueError(
                    "Downloaded bytes differ from the fixed Hugging Face LFS identity"
                )
            if lfs.get("size") is not None and lfs["size"] != record["bytes"]:
                raise ValueError("Downloaded size differs from the fixed LFS identity")
            record["upstream_lfs_sha256"] = expected
            record["status"] = "Verified"
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
        record["wall_seconds"] = time.perf_counter() - begin
        print(json.dumps(record, sort_keys=True), flush=True)
        return record

    with ThreadPoolExecutor(max_workers=2) as executor:
        records = list(executor.map(download, FILES))
    result = {
        "schema": "ndu.real.acquisition.v1",
        "repository": REPOSITORY,
        "revision": REVISION,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "repository_metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "files": records,
        "wall_seconds": time.perf_counter() - started,
        "bytes": sum(row["bytes"] for row in records),
        "status": "Verified"
        if all(row["status"] == "Verified" for row in records)
        else "Failed",
        "actor_executed": False,
        "confirmation_evaluated": False,
        "license_declared_by_distributor": "CC-BY-4.0",
        "pretraining_exposure": "UNKNOWN",
        "scientific_admission": "HOLD",
    }
    (root / "acquisition.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps({key: result[key] for key in ("status", "bytes", "wall_seconds")}),
        flush=True,
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if acquire(args.output)["status"] == "Verified" else 1)
