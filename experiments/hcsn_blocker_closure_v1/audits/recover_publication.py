"""Recover an exact public research publication and verify every byte.

The receipt hash, source commit, execution seal and run id come from an
independent GitHub read. No credentials, mutable branch URLs, or archive
extraction are used by this transport helper.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import urllib.request


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
LIMIT = 512000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(name):
    value = PurePosixPath(name)
    if (value.is_absolute() or not value.parts or any(p in ("..", ".") for p in value.parts)
            or value.as_posix() != name or "\\" in name):
        raise ValueError("Unsafe publication filename")
    return value


def fetch(commit, path, expected_bytes=None):
    relative(path)
    url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{path}"
    with urllib.request.urlopen(url, timeout=45) as response:
        if response.status != 200:
            raise ValueError("Unexpected HTTP status")
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT or (expected_bytes is not None and len(raw) != expected_bytes):
        raise ValueError("Publication file length mismatch")
    return raw


def recover(args):
    cpu0, wall0 = time.process_time(), time.perf_counter()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("Expected an immutable full Git commit")
    if not re.fullmatch(r"[0-9a-f]{64}", args.receipt_sha256):
        raise ValueError("Expected an independently observed receipt digest")
    raw_receipt = fetch(args.commit, args.receipt_path)
    if digest(raw_receipt) != args.receipt_sha256:
        raise ValueError("Receipt digest mismatch")
    receipt = json.loads(raw_receipt)
    if receipt["execution_seal"] != args.seal or str(receipt["github_run_id"]) != args.run_id:
        raise ValueError("Source seal or workflow run mismatch")
    prefix = relative(receipt["source_root"])
    if prefix.as_posix() not in (
            "experiments/hcsn_blocker_closure_v1",
            "experiments/hcsn_blocker_closure_v1/av"):
        raise ValueError("Unexpected research publication prefix")
    names = {args.receipt_path}
    total = len(raw_receipt)
    for row in receipt["files"]:
        path = relative(row["path"])
        if (not path.is_relative_to(prefix) or row["path"] in names
                or not 0 <= row["bytes"] <= LIMIT
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise ValueError("Invalid receipt inventory")
        names.add(row["path"])
        total += row["bytes"]
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < total + 128 * 1024**2:
        raise OSError("Insufficient free disk for the complete publication")

    def save(path, data):
        target = root.joinpath(*relative(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("Unsafe output target")
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError("Existing output differs; refusing overwrite")
        else:
            with target.open("xb") as stream:
                stream.write(data)

    save(args.receipt_path, raw_receipt)

    def one(row):
        existing = root.joinpath(*relative(row["path"]).parts)
        if existing.is_symlink() or not existing.resolve().is_relative_to(root):
            raise ValueError("Unsafe existing target")
        data = existing.read_bytes() if existing.exists() else fetch(args.commit, row["path"], row["bytes"])
        if len(data) != row["bytes"] or digest(data) != row["sha256"]:
            raise ValueError(f"File integrity mismatch: {row['path']}")
        save(row["path"], data)
        return len(data)

    count = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(one, row) for row in receipt["files"]]):
            future.result()
            count += 1
            if count % 100 == 0:
                print(json.dumps({"verified_files": count, "total_files": len(receipt["files"])}), flush=True)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != names:
        raise ValueError("Missing or unlisted recovered files")
    return {
        "schema": "hcsn-publication-local-recovery.v1", "passed": True,
        "repository": REPOSITORY, "evidence_commit": args.commit,
        "execution_seal": args.seal, "github_run_id": args.run_id,
        "receipt_path": args.receipt_path, "receipt_sha256": args.receipt_sha256,
        "verified_files": len(names), "download_bytes": total,
        "cpu_seconds": time.process_time() - cpu0,
        "wall_seconds": time.perf_counter() - wall0,
        "scope": "Exact publication transport only; scientific and archive validation are separate."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--receipt-path", required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--seal", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit-output", required=True, type=Path)
    args = parser.parse_args()
    result = recover(args)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    with args.audit_output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
