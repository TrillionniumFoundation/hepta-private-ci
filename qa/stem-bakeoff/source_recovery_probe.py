"""Exact source recovery is measured independently of semantic task prediction.

The bank preserves full original issue text, including bytes outside the model's
context. Source IDs and revisions address this bank; no Head is asked to memorize
source text. The child verifies archive integrity and explicit version matches.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def recover(archive, expected_sha256, requests):
    archive = Path(archive)
    if archive.stat().st_size > 64 * 1024**2:
        raise ValueError("source archive exceeds budget")
    raw = archive.read_bytes()
    if digest(raw) != expected_sha256:
        raise ValueError("source archive integrity differs from trusted request")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    if not isinstance(requests, list) or not 1 <= len(requests) <= 4098:
        raise ValueError("bounded source requests required")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
        expanded = zipped.read(128 * 1024**2 + 1)
    if len(expanded) > 128 * 1024**2:
        raise ValueError("decompressed source bank exceeds budget")
    rows = [json.loads(line) for line in expanded.splitlines()]
    if not 1 <= len(rows) <= 4096:
        raise ValueError("bounded source bank required")
    bank = {}
    for row in rows:
        key = (row["source_id"], row["source_version"])
        if key in bank:
            raise ValueError("ambiguous source revision")
        bank[key] = row
    load = {"wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": time.process_time_ns() - cpu,
            "decompressed_source_bytes": len(expanded)}
    results = []
    for request in requests:
        if set(request) != {"source_id", "source_version"}:
            raise ValueError("source queries may contain only identity and revision")
        started = time.perf_counter_ns()
        source = bank.get((request["source_id"], request["source_version"]))
        payload = None if source is None else canonical(source)
        results.append({**request, "found": source is not None,
            "recovered_sha256": None if payload is None else digest(payload),
            "recovered_bytes": 0 if payload is None else len(payload),
            "wall_ns": time.perf_counter_ns() - started})
    return {"load": load, "results": results, "source_count": len(bank),
            "head_parameters_used": 0, "encoder_forward_calls": 0}


def run_probe(dataset, parquet, acquisition, output):
    import pyarrow.parquet as pq
    dataset_bytes = Path(dataset).read_bytes()
    data = json.loads(dataset_bytes)
    acquired = json.loads(Path(acquisition).read_bytes())
    parquet_bytes = Path(parquet).read_bytes()
    if digest(parquet_bytes) != acquired["sha256"] or len(parquet_bytes) != acquired["bytes"]:
        raise ValueError("raw source corpus differs from its pinned acquisition")
    original = {row["instance_id"]: row for row in pq.read_table(io.BytesIO(parquet_bytes)).to_pylist()}
    rows = []
    for row in data["rows"]:
        raw = original[row["source_id"]]
        version = "sha256:" + digest(canonical(row["source_version"]))
        rows.append({"source_id": row["source_id"], "source_version": version,
                     "repo": raw["repo"], "created_at": raw["created_at"],
                     "problem_statement": raw["problem_statement"]})
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    payload = b"".join(canonical(row) + b"\n" for row in rows)
    archive = root / "sources.jsonl.gz"
    archive.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))
    archive_sha = digest(archive.read_bytes())
    requests = [{key: row[key] for key in ("source_id", "source_version")} for row in rows]
    # Negative reads must reject missing sources and stale revisions explicitly.
    requests += [{"source_id": rows[0]["source_id"], "source_version": "stale:0"},
                 {"source_id": "missing:source", "source_version": rows[0]["source_version"]}]
    plan = {"schema": "hepta.exact-source-recovery.v1", "archive_sha256": archive_sha,
            "dataset_sha256": digest(dataset_bytes), "requests": requests}
    plan_path = root / "requests.json"
    plan_path.write_bytes(canonical(plan) + b"\n")
    result_path = root / "restored.json"
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "read", "--archive", str(archive),
                    "--plan", str(plan_path), "--output", str(result_path)], check=True, timeout=60,
                   capture_output=True)
    cost = {"wall_ns": time.perf_counter_ns() - started,
            "parent_cpu_ns": time.process_time_ns() - cpu,
            "child_cpu_ns": None, "includes_process_startup": True}
    restored = json.loads(result_path.read_bytes())
    matches = [result["recovered_sha256"] == digest(canonical(row)) and result["found"]
               for row, result in zip(rows, restored["results"][:len(rows)], strict=True)]
    negatives = restored["results"][len(rows):]
    if not all(matches) or any(row["found"] for row in negatives):
        raise ValueError("fresh-process exact source or stale-version recovery failed")
    report = {"schema": plan["schema"], "dataset_sha256": plan["dataset_sha256"],
        "archive_sha256": archive_sha, "source_count": len(rows), "byte_exact_recoveries": sum(matches),
        "missing_or_stale_rejections": len(negatives), "fresh_process": True,
        "original_issue_bytes_retained": sum(len(row["problem_statement"].encode()) for row in rows),
        "compressed_archive_bytes": archive.stat().st_size,
        "request_index_bytes": plan_path.stat().st_size, "restore_cost": cost,
        "child_load": restored["load"], "read_results": restored["results"],
        "uses_gold_patch": False, "semantic_generalization_measured": False,
        "filesystem_access_isolated": False, "external_publisher_authenticity_verified": False,
        "head_parameters_used": 0, "encoder_forward_calls": 0}
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read")
    for name in ("archive", "plan", "output"):
        read.add_argument("--" + name, required=True)
    run = sub.add_parser("run")
    for name in ("dataset", "parquet", "acquisition", "output"):
        run.add_argument("--" + name, required=True)
    args = vars(parser.parse_args())
    if args.pop("command") == "run":
        report = run_probe(**args)
        print(json.dumps({key: report[key] for key in ("source_count", "byte_exact_recoveries", "compressed_archive_bytes")}))
    else:
        plan = json.loads(Path(args.pop("plan")).read_bytes())
        output = Path(args.pop("output"))
        report = recover(args["archive"], plan["archive_sha256"], plan["requests"])
        with output.open("xb") as stream:
            stream.write(canonical(report) + b"\n")


if __name__ == "__main__":
    main()
