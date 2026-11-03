"""Sanitized post-run fresh-process runner. This file never opens a gold file or uses network.

An approved manifest enumerates local pinned raw bytes, not pre-parsed parents.
No real-data run is authorized by the existence of this executable. The CLI
requires either a synthetic-only attestation or a separately supplied explicit
execution-GO record. This is an audit gate, not an access-control boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import re
import selectors
import signal
import subprocess
import sys
import time
import traceback

from retrieval import ARMS, PRIMARY_ARMS, Retriever

HERE = Path(__file__).resolve().parent
PARSER_PATH = HERE / "raw_markdown.py"
CONFIG_PATH = HERE / "CONFIG.json"
REQUIRED_FREEZE_FILES = {
    "raw_markdown.py", "retrieval.py", "runner.py", "scoring.py", "freeze.py",
    "toy_fixture.py", "CONFIG.json", "PROTOCOL.template.json", "README.md",
    "tests/test_evaluator.py", "tests/test_raw_markdown.py", "tests/test_release.py",
}

THREAD_ENV = {name: "1" for name in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS")}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    """Charged durable output; preserve prior files by rejecting overwrite."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_parser():
    spec = importlib.util.spec_from_file_location("pilot_raw_markdown", PARSER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_inputs(manifest_path: Path, queries_path: Path, arm: str):
    """Read raw bytes on demand, verifying both declared pins before parsing."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    queries = json.loads(queries_path.read_text(encoding="utf-8"))
    if not isinstance(queries, list) or not queries:
        raise ValueError("Queries must be a nonempty list")
    ids = []
    for query in queries:
        if set(query) != {"id", "question"} or not all(isinstance(v, str) and v for v in query.values()):
            raise ValueError("Query input must contain only nonempty id and question, no gold")
        ids.append(query["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate query IDs")
    parser_module = load_parser()
    locations, entries = {}, []
    for row in manifest["files"]:
        identity = (row["source"], row["path"])
        if identity in locations:
            raise ValueError("Duplicate raw file")
        # A relative local path is relative to the frozen manifest, never fetched.
        path = Path(row["local_path"])
        if not path.is_absolute():
            path = manifest_path.parent / path
        locations[identity] = (path, row)
        entries.append(parser_module.Entry(row["source"], row["path"], row["git_blob_sha1"], row["sha256"]))
    load_count, raw_bytes, load_seconds = 0, 0, 0.0
    load_failures = []

    def loader(source, path):
        nonlocal load_count, raw_bytes, load_seconds
        started = time.perf_counter()
        local_path, row = locations[(source, path)]
        try:
            body = local_path.read_bytes()
            load_count += 1
            raw_bytes += len(body)
            if hashlib.sha256(body).hexdigest() != row["sha256"]:
                raise ValueError("Raw SHA256 mismatch")
            blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            if blob != row["git_blob_sha1"]:
                raise ValueError("Raw Git blob mismatch")
            return body
        except Exception as error:
            load_failures.append(f"{source}:{path}:{type(error).__name__}:{error}")
            raise
        finally:
            load_seconds += time.perf_counter() - started

    extract_links = arm in ("links", "hash_links")
    parser = parser_module.Parser(entries, loader, commit=manifest["commit"], extract_links=extract_links,
                                  repository=manifest.get("repository", "example/synthetic-docs"))
    parents, decisions = [], []
    for entry in entries:
        document = parser.parse(entry.source, entry.path)
        decisions.append({"source": entry.source, "path": entry.path,
                          "status": document.status, "reason": document.reason})
        parents.extend(document.parents)
    if load_failures:
        # The parser intentionally converts loader exceptions into document
        # rejections. A corrupted/missing approved input is an execution failure.
        raise ValueError("Raw input loading failed: " + "; ".join(load_failures))
    docs, audit = parser.to_mechanics(parents)
    if not docs:
        raise ValueError("No supported nonempty canonical parents")
    representation = {i: {k: d[k] for k in ("source", "title", "text", "citation")}
                      for i, d in docs.items()}
    return docs, queries, {
        "raw_load_count": load_count, "raw_bytes": raw_bytes, "raw_load_seconds": load_seconds,
        "parent_count": len(docs), "extract_links": extract_links, "parser_audit": audit,
        "decisions": decisions,
        "canonical_representation_sha256": canonical_digest({"documents": representation, "decisions": decisions}),
    }


def percentile(values, p):
    """Fixed nearest-rank percentile; no interpolated observation invented."""
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)]


def emit(event):
    print(json.dumps(event, sort_keys=True, allow_nan=False), flush=True)


def child(arm: str, manifest: Path, queries: Path, output: Path):
    started = time.perf_counter()
    cpu_started = time.process_time()
    config = json.loads(CONFIG_PATH.read_text())
    resource.setrlimit(resource.RLIMIT_AS, (config["address_space_limit_bytes"], config["address_space_limit_bytes"]))
    resource.setrlimit(resource.RLIMIT_CPU, (config["process_timeout_seconds"], config["process_timeout_seconds"]))
    emit({"event": "started", "child_started_monotonic": started})
    phase = "input_and_parse"
    try:
        t = time.perf_counter()
        docs, task_queries, audit = load_inputs(manifest, queries, arm)
        parse_seconds = time.perf_counter() - t
        phase = "index"
        t = time.perf_counter()
        retriever = Retriever(docs, arm)
        index_seconds = time.perf_counter() - t
        phase = "cold_query_and_pack"
        t = time.perf_counter()
        results = [{"id": q["id"], "pack": retriever.retrieve(q["question"])} for q in task_queries]
        query_seconds = time.perf_counter() - t
        phase = "cold_output_write"
        t = time.perf_counter()
        write_json(output / "cold_results.json", {"arm": arm, "audit": audit, "results": results})
        write_seconds = time.perf_counter() - t
        cold_finished = time.perf_counter()
        cold_cpu = time.process_time() - cpu_started
        emit({"event": "cold_complete", "cold_finished_monotonic": cold_finished,
              "child_cold_seconds": cold_finished - started, "cold_cpu_seconds": cold_cpu,
              "raw_load_parse_graph_seconds": parse_seconds, "index_seconds": index_seconds,
              "query_pack_seconds": query_seconds, "output_write_seconds": write_seconds,
              "cold_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "canonical_representation_sha256": audit["canonical_representation_sha256"]})
        phase = "awaiting_parent_warm_ack"
        if sys.stdin.readline() != "ACK_WARM\n":
            raise RuntimeError("Parent did not acknowledge the cold timing boundary")
        warm_started = time.perf_counter()
        emit({"event": "warm_started", "warm_started_monotonic": warm_started})
        phase = "warm_repeats"
        warm_durations, repeat_seconds = [], []
        cold_digest = canonical_digest(results)
        for repeat in range(config["warm_repeats"]):
            t_repeat = time.perf_counter()
            warm_results = []
            for query in task_queries:
                t = time.perf_counter()
                result = retriever.retrieve(query["question"])
                warm_durations.append(time.perf_counter() - t)
                warm_results.append({"id": query["id"], "pack": result})
            if canonical_digest(warm_results) != cold_digest:
                raise RuntimeError("Cold/warm result mismatch")
            write_json(output / f"warm_{repeat + 1}.json", {"arm": arm, "results": warm_results})
            repeat_seconds.append(time.perf_counter() - t_repeat)
        phase = "cost_output_write"
        costs = {"arm": arm, "status": "SUCCESS", "warm_repeats": config["warm_repeats"],
                 "warm_queries": len(warm_durations), "warm_query_seconds": warm_durations,
                 "warm_p50_seconds": percentile(warm_durations, .5),
                 "warm_p95_seconds": percentile(warm_durations, .95),
                 "warm_repeat_including_output_seconds": repeat_seconds,
                 "cpu_seconds": time.process_time() - cpu_started,
                 "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                 "rss_units": "Linux ru_maxrss KiB converted to bytes",
                 "actual_rlimit_as_bytes": list(resource.getrlimit(resource.RLIMIT_AS)),
                 "actual_rlimit_cpu_seconds": list(resource.getrlimit(resource.RLIMIT_CPU)),
                 "warm_started_monotonic": warm_started,
                 "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
                 "child_total_before_cost_output_seconds": time.perf_counter() - started}
        write_json(output / "costs.json", costs)
        emit({"event": "complete", "status": "SUCCESS", "child_total_seconds": time.perf_counter() - started})
        return 0
    except BaseException as error:
        # Keep traceback and incomplete outputs. Never map failures to success.
        failure = {"event": "failure", "status": "FAILED", "phase": phase,
                   "error": type(error).__name__, "detail": str(error),
                   "elapsed_seconds": time.perf_counter() - started,
                   "cpu_seconds": time.process_time() - cpu_started,
                   "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
        try:
            emit(failure)
        finally:
            traceback.print_exc(file=sys.stderr)
        return 1


def execute_arm(arm, manifest, queries, output, timeout=300):
    """Parent-observed cold time includes spawn/import/read/parse/index/pack/write."""
    output.mkdir()
    start = time.perf_counter()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    environment = dict(os.environ, **THREAD_ENV, PYTHONHASHSEED="0")
    stderr_path = output / "stderr.log"
    events, stdout_chunks = [], []
    timed_out = False
    with stderr_path.open("wb") as stderr:
        process = subprocess.Popen([sys.executable, str(HERE / "runner.py"), "--child", arm,
                                    "--manifest", str(manifest), "--queries", str(queries),
                                    "--output", str(output)], stdout=subprocess.PIPE, stderr=stderr,
                                   stdin=subprocess.PIPE, text=False, bufsize=0, env=environment, start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        pending = b""

        def record_line(line):
            event = json.loads(line.decode("utf-8"))
            event["parent_observed_since_spawn_seconds"] = time.perf_counter() - start
            events.append(event)
            if event["event"] == "cold_complete" and process.poll() is None:
                # Binary unbuffered pipe avoids TextIOWrapper prefetch hiding a
                # cold event from select while the child blocks waiting for ACK.
                try:
                    process.stdin.write(b"ACK_WARM\n")
                    process.stdin.flush()
                    event["warm_ack_sent_since_spawn_seconds"] = time.perf_counter() - start
                except BrokenPipeError:
                    event["warm_ack_error"] = "child_pipe_closed"

        while True:
            elapsed = time.perf_counter() - start
            if elapsed >= timeout and process.poll() is None:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                break
            ready = selector.select(timeout=min(.1, max(.001, timeout - elapsed)))
            if ready:
                chunk = os.read(process.stdout.fileno(), 65536)
                if chunk:
                    stdout_chunks.append(chunk)
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        if line:
                            record_line(line)
                elif process.poll() is not None:
                    break
            elif process.poll() is not None:
                break
        process.wait()
        remainder = process.stdout.read()
        if remainder:
            stdout_chunks.append(remainder)
            pending += remainder
        for line in pending.splitlines():
            if line:
                record_line(line)
        selector.close()
        process.stdout.close()
        process.stdin.close()
    total = time.perf_counter() - start
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    (output / "stdout.log").write_bytes(b"".join(stdout_chunks))
    cold = next((e for e in events if e["event"] == "cold_complete"), None)
    started = next((e for e in events if e["event"] == "started"), None)
    complete = any(e["event"] == "complete" and e["status"] == "SUCCESS" for e in events)
    success = process.returncode == 0 and complete and cold is not None and not timed_out
    result = {"arm": arm, "status": "SUCCESS" if success else ("TIMEOUT" if timed_out else "FAILED"),
              "returncode": process.returncode, "process_total_seconds": total,
              "process_timeout_seconds": timeout, "events": events,
              "cold_end_to_end_seconds": cold["parent_observed_since_spawn_seconds"] if success else None,
              "cold_child_endpoint_since_spawn_seconds": cold["cold_finished_monotonic"] - start if cold else None,
              "cold_event_parent_receipt_seconds": cold["parent_observed_since_spawn_seconds"] if cold else None,
              "cold_clock_definition": "parent before Popen to parent receiving child fsynced cold-output event; child blocks for parent ACK before warm work",
              "cold_time_censored_lower_bound_seconds": timeout if timed_out and cold is None else None,
              "startup_seconds": started["child_started_monotonic"] - start if started else None,
              "failed_work_charged_seconds": total if not success else 0,
              "child_cpu_seconds_including_failed_work": (children_after.ru_utime + children_after.ru_stime
                  - children_before.ru_utime - children_before.ru_stime),
              "failed_peak_rss_bytes": next((e["peak_rss_bytes"] for e in events if e["event"] == "failure"), None),
              "failed_peak_rss_note": "A hard-killed child may not emit RSS; null means unavailable, never zero cost.",
              "completed_cold_before_later_failure": cold is not None and not success}
    write_json(output / "parent_costs.json", result)
    return result


def verify_freeze(freeze_path: Path):
    freeze = json.loads(freeze_path.read_text())
    if freeze.get("schema") != "sanitized-pilot-code-freeze-v1" or set(freeze.get("files", {})) != REQUIRED_FREEZE_FILES:
        raise ValueError("Freeze must contain the exact required code/config/parser/protocol inventory")
    for relative, expected in freeze["files"].items():
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError("Invalid frozen SHA256")
        path = (HERE / relative).resolve()
        if sha256(path) != expected:
            raise ValueError(f"Frozen artifact hash mismatch: {relative}")
    return sha256(freeze_path)


def suite(manifest, queries, output, authorization, freeze):
    config = json.loads(CONFIG_PATH.read_text())
    freeze_hash = verify_freeze(freeze)
    authorization_record = json.loads(authorization.read_text())
    data = json.loads(manifest.read_text())
    mode = authorization_record.get("kind")
    if mode == "synthetic_engineering_only":
        if data.get("fixture_kind") != "self_authored_synthetic":
            raise ValueError("Synthetic authorization cannot run a real corpus")
    elif mode == "explicit_pilot_execution_go":
        if not authorization_record.get("user_authorization_evidence"):
            raise ValueError("Real pilot requires recorded explicit execution GO")
    else:
        raise ValueError("No recognized execution authorization")
    for name, path in (("manifest_sha256", manifest), ("queries_sha256", queries), ("freeze_sha256", freeze)):
        if authorization_record.get(name) != sha256(path):
            raise ValueError(f"Authorization mismatch: {name}")
    output.mkdir(parents=True, exist_ok=False)
    runs = [execute_arm(arm, manifest, queries, output / arm,
                        timeout=config["process_timeout_seconds"]) for arm in config["arm_order"]]
    fingerprints = {next(e["canonical_representation_sha256"] for e in row["events"]
                         if e["event"] == "cold_complete") for row in runs if row["status"] == "SUCCESS"}
    consistent = len(fingerprints) == 1 and all(row["status"] == "SUCCESS" for row in runs)
    primary_failure = any(row["status"] != "SUCCESS" for row in runs if row["arm"] in PRIMARY_ARMS)
    primary_fingerprints = {next(e["canonical_representation_sha256"] for e in row["events"]
                                if e["event"] == "cold_complete")
                            for row in runs if row["arm"] in PRIMARY_ARMS and row["status"] == "SUCCESS"}
    primary_consistent = len(primary_fingerprints) == 1 and not primary_failure
    diagnostic_status = {}
    for row in runs:
        if row["arm"] not in PRIMARY_ARMS:
            fingerprint = next((e["canonical_representation_sha256"] for e in row["events"]
                                if e["event"] == "cold_complete"), None)
            diagnostic_status[row["arm"]] = ("SUCCESS" if row["status"] == "SUCCESS" and
                fingerprint in primary_fingerprints else "FAILED_OR_REPRESENTATION_MISMATCH")
    result = {"scope": mode, "freeze_sha256": freeze_hash, "runs": runs,
              "canonical_representations_equal": consistent,
              "primary_canonical_representations_equal": primary_consistent,
              "diagnostic_status": diagnostic_status,
              "execution_status": "SUCCESS" if primary_consistent else "FAILED_OR_INCONSISTENT",
              "efficacy_status": "NOT_SCORED",
              "primary_execution_failure": primary_failure,
              "execution_gate": "NO_GO" if not primary_consistent else "AWAIT_INDEPENDENT_SCORING",
              "all_process_seconds_including_failed_work": sum(row["process_total_seconds"] for row in runs)}
    write_json(output / "suite.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", choices=ARMS)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--freeze", type=Path, default=HERE / "FREEZE.json")
    args = parser.parse_args()
    if args.child:
        return child(args.child, args.manifest.resolve(), args.queries.resolve(), args.output.resolve())
    if args.authorization is None:
        parser.error("--authorization is required; implementation is not execution GO")
    result = suite(args.manifest.resolve(), args.queries.resolve(), args.output.resolve(),
                   args.authorization.resolve(), args.freeze.resolve())
    print(json.dumps({"execution_status": result["execution_status"], "efficacy_status": "NOT_SCORED"}))
    return 0 if result["execution_status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
