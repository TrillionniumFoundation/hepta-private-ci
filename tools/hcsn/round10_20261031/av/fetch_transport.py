"""Fetch only the fixed, hash-bound AV feature transport; never decode arrays."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
COMMIT = "dca9febc8143c682077fe27d40dbeaa1137bcaa4"
PREFIX = "experiments/hcsn_blocker_closure_v1/av/transport_41156412198/"
HERE = Path(__file__).resolve().parent


def fetch(output, workers):
    manifest = json.loads((HERE / "source_transport.json").read_text())
    parts = [part for record in manifest["files"] for part in record["parts"]]
    output.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    started = time.perf_counter()

    def one(part):
        target = (output / part["path"]).resolve()
        if not target.is_relative_to(output):
            raise ValueError("part path escapes output directory")
        exists = target.exists()
        if exists:
            data = target.read_bytes()
        else:
            url = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{PREFIX}{part['path']}"
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        if len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise ValueError((part["path"], "transport identity mismatch"))
        if not exists:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return {"path": part["path"], "bytes": len(data), "sha256": part["sha256"],
                "downloaded": not exists}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(one, parts))
    receipt = {"repository": REPOSITORY, "commit": COMMIT, "prefix": PREFIX,
               "verified_parts": len(records), "downloaded_parts": sum(r["downloaded"] for r in records),
               "wall_seconds": time.perf_counter() - started, "parts": records,
               "scope": "Transport bytes only; no decoding or test-array access"}
    (output / "DOWNLOAD_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ["verified_parts", "downloaded_parts", "wall_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("workers must be in [1, 16]")
    fetch(args.output, args.workers)
