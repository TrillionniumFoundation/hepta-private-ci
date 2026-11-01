"""Acquire only preregistered, hash-pinned public media after candidate freeze."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(row, destination, source_commit):
    start, cpu = time.perf_counter(), time.thread_time()
    clip = row["clip"]
    if not re.fullmatch(r"\d{4}_(DFA|IOM)_[A-Z]{3}_XX", clip):
        raise ValueError("Invalid registered clip name")
    expected = ("https://media.githubusercontent.com/media/CheyneyComputerScience/CREMA-D/"
                + source_commit + "/VideoFlash/" + clip + ".flv")
    if row["url"] != expected or not 0 < row["bytes"] < 10000000:
        raise ValueError("Unexpected source or size")
    target = destination / (clip + ".flv")
    record = dict(clip=clip, url=expected, expected_sha256=row["sha256"], bytes=row["bytes"])
    try:
        if target.exists():
            if target.stat().st_size != row["bytes"] or digest(target) != row["sha256"]:
                raise ValueError("Existing media differs from the frozen source")
            record.update(status="verified_existing", downloaded_bytes=0)
        else:
            temporary = target.with_suffix(".partial")
            with urllib.request.urlopen(expected, timeout=45) as response, temporary.open("xb") as stream:
                size = 0
                while block := response.read(65536):
                    size += len(block)
                    if size > row["bytes"]:
                        raise ValueError("Media exceeds registered size")
                    stream.write(block)
            if size != row["bytes"] or digest(temporary) != row["sha256"]:
                raise ValueError("Downloaded media identity mismatch")
            temporary.replace(target)
            record.update(status="downloaded_verified", downloaded_bytes=size)
        record["actual_sha256"] = digest(target)
    except Exception as error:
        record.update(status="failed", error=repr(error))
    record.update(wall_seconds=time.perf_counter() - start,
                  thread_cpu_seconds=time.thread_time() - cpu)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    if digest(args.freeze) != args.freeze_sha256:
        raise ValueError("Candidate freeze changed before acquisition")
    manifest = json.loads(args.manifest.read_text())
    manifest_sha = digest(args.manifest)
    # The candidate freeze must explicitly include the preregistered cohort hash.
    freeze = json.loads(args.freeze.read_text())
    if manifest_sha not in json.dumps(freeze, sort_keys=True):
        raise ValueError("Candidate freeze does not identify this cohort")
    args.destination.mkdir(parents=True, exist_ok=True)
    if args.receipt.exists():
        raise FileExistsError(args.receipt)
    started = datetime.now(timezone.utc).isoformat()
    start, cpu = time.perf_counter(), time.process_time()
    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, row, args.destination, manifest["source_commit"])
                   for row in manifest["records"]]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            if len(rows) % 12 == 0 or row["status"] == "failed":
                print(json.dumps(dict(completed=len(rows), total=len(futures),
                                      last_clip=row["clip"], status=row["status"])), flush=True)
    receipt = dict(schema="hcsn.av.confirmation-acquisition.v1", started_utc=started,
        finished_utc=datetime.now(timezone.utc).isoformat(), source_sha256=digest(__file__),
        cohort_sha256=manifest_sha, candidate_freeze_sha256=args.freeze_sha256,
        source_commit=manifest["source_commit"], actors=manifest["actors"],
        files=sorted(rows, key=lambda row: row["clip"]),
        wall_seconds=time.perf_counter() - start, cpu_seconds=time.process_time() - cpu,
        downloaded_bytes=sum(row.get("downloaded_bytes", 0) for row in rows),
        failed=sum(row["status"] == "failed" for row in rows), energy_joules=None,
        scope="Download and checksum only; no decoding, feature extraction or evaluation")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: receipt[key] for key in ("failed", "downloaded_bytes", "wall_seconds", "cpu_seconds")}))
    return 1 if receipt["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
