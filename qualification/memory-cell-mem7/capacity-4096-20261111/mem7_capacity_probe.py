"""Measure a public-API MEM7 chain at its 4096-record bound, without adoption."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import resource
import sqlite3
import subprocess
import sys
import time

SOURCE_SHA256 = "1afcc4a3b3f2b5dbbb0150a97d7513daad4e7226982576f600ae639bef787440"
SOURCE_COMMIT = "4c3b1fb6d40de7c85aedd1964357e138fc7aa9d8"
SOURCE_BLOB = "0294daca0a0dee3221be4dc94d563b6816156da1"


def checked(condition, message):
    if not condition:
        raise RuntimeError(message)


def pin(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def module(path):
    checked(pin(path)["sha256"] == SOURCE_SHA256, "source pin mismatch")
    spec = importlib.util.spec_from_file_location("fixed_mem7", path)
    owner = importlib.util.module_from_spec(spec)
    raw = Path(path).read_bytes()
    checked(hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, "load pin mismatch")
    exec(compile(raw, str(path), "exec"), owner.__dict__)
    return owner


def usage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "process_cpu_seconds": own.ru_utime + own.ru_stime,
        "child_cpu_seconds": child.ru_utime + child.ru_stime,
        "process_peak_rss": own.ru_maxrss,
        "child_peak_rss": child.ru_maxrss,
        "peak_rss_unit": "KiB" if sys.platform.startswith("linux") else "bytes",
    }


def child(args):
    owner = module(args.source)
    store = owner.EpisodicStore(args.store, namespace="capacity-probe", create=False)
    current, old = store.view(), store.view(args.snapshot)
    checked(current["receipt"]["authority_generation"] == 4097, "cold generation")
    checked(len(current["records"]) == args.expected, "cold current count")
    checked(old["records"] == [], "old snapshot reactivated records")
    checked(old["receipt"]["snapshot_rejections"] == 4096, "cold rejection count")
    print(json.dumps({"passed": True, "current": current["receipt"],
                      "snapshot": old["receipt"], "resources": usage()}, sort_keys=True))


def run(args):
    start = time.perf_counter()
    source_pin, harness_pin = pin(args.source), pin(__file__)
    owner = module(args.source)
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    events = root / "EVENTS.jsonl"

    def emit(value):
        value = {"elapsed_wall_seconds": time.perf_counter() - start,
                 "resources": usage(), **value}
        with events.open("a") as output:
            output.write(json.dumps(value, sort_keys=True) + "\n")
            output.flush()
        print(json.dumps(value, sort_keys=True), flush=True)
        return value

    result = {
        "schema": "hepta.mem7.capacity-measurement.v1",
        "source_commit": SOURCE_COMMIT,
        "source_git_blob": SOURCE_BLOB,
        "source": source_pin,
        "harness": harness_pin,
        "platform": platform.platform(),
        "python": sys.version,
        "protocol": {"records": 4096, "declared_edges": 4095,
                     "population_writer": "EpisodicStore.put public API, sequential",
                     "shape": "one root; reverse-key-ordered one-dependency chain",
                     "namespace_count": 1, "source_group_count": 1,
                     "data": "synthetic fixture", "max_serialized_bytes": 16 * 1024**2,
                     "wall_budget_seconds": args.wall_budget},
        "science": {"new_independent_real_tasks": 0, "adoption": "NoUpdate",
                    "qualification": "HOLD", "complete_effect_owner_recovery": False,
                    "max_32_dependency_dense_graph_measured": False,
                    "memory_benefit_evaluated": False, "required_repo_ci_evaluated": False},
        "cost_scope": {"wall": "harness entry through checks and final source read",
                       "cpu": "getrusage self and child processes, cumulative",
                       "rss": "OS cumulative process peaks, not per-phase allocations",
                       "included": "4096 public writes, snapshot, SQLite copies, mutations, cold readers",
                       "excluded": "source upload, interpreter/import startup, final report serialization, transport",
                       "energy_joules": None, "full_physical_cost_observed": False},
    }
    try:
        store = owner.EpisodicStore(root / "seed.sqlite", namespace="capacity-probe",
                                   max_records=4096, max_serialized_bytes=16 * 1024**2)
        provenance = {"source_uri": "fixture://capacity-probe", "source_sha256": "a" * 64,
                      "source_version": "1", "episode_id": "capacity-probe"}
        previous, ids = None, []
        population_start = time.perf_counter()
        for index in range(4096):
            checked(time.perf_counter() - start < args.wall_budget, "wall budget exceeded")
            record = store.put("synthetic-source", "root" if index == 0 else f"{4096-index:04d}",
                               f"Synthetic fact {index}", provenance=provenance,
                               dependencies=[] if previous is None else [previous])
            previous = record["record_id"]
            ids.append(previous)
            if (index + 1) % 512 == 0:
                emit({"phase": "public_population", "records": index + 1})
        result["population_wall_seconds"] = time.perf_counter() - population_start
        original = store.view()
        checked(len(original["records"]) == 4096, "population count")
        checked(original["receipt"]["authority_generation"] == 4096, "population generation")
        snapshot = root / "before.json"
        store.export_snapshot(snapshot)
        result["initial_view"] = original["receipt"]
        result["snapshot_pin"] = pin(snapshot)
        result["record_inventory_sha256"] = owner.digest(ids)
        result["mutations"] = []
        for action in ("update", "revoke"):
            path = root / f"{action}.sqlite"
            with sqlite3.connect(store.path) as source, sqlite3.connect(path) as target:
                source.backup(target)
            candidate = owner.EpisodicStore(path, namespace="capacity-probe", create=False)
            before_wall, before_cpu = time.perf_counter(), time.process_time()
            if action == "update":
                replacement = candidate.put("synthetic-source", "root", "Explicit new root",
                                            provenance={**provenance, "source_version": "2"})
                expected = [replacement]
            else:
                receipt = candidate.revoke("synthetic-source", "root")
                checked(set(receipt["affected_ids"]) == set(ids), "revocation closure mismatch")
                expected = []
            mutation_wall = time.perf_counter() - before_wall
            mutation_cpu = time.process_time() - before_cpu
            current, restored = candidate.view(), candidate.view(snapshot)
            checked(current["records"] == expected, "current records mismatch")
            checked(current["receipt"]["authority_generation"] == 4097, "generation advanced more than once")
            checked(restored["records"] == [], "stale snapshot reactivated")
            checked(restored["receipt"]["snapshot_rejections"] == 4096, "snapshot rejection mismatch")
            command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                       "--source", str(Path(args.source).resolve()), "--child", "--store", str(path),
                       "--snapshot", str(snapshot), "--expected", str(len(expected))]
            cold = subprocess.run(command, capture_output=True, text=True, timeout=60)
            (root / f"{action}-cold.stdout").write_text(cold.stdout)
            (root / f"{action}-cold.stderr").write_text(cold.stderr)
            checked(cold.returncode == 0 and not cold.stderr, "cold reader failed")
            cold_result = json.loads(cold.stdout)
            checked(cold_result["passed"], "cold reader rejected")
            item = {"action": action, "mutation_wall_seconds": mutation_wall,
                    "mutation_cpu_seconds": mutation_cpu, "current": current["receipt"],
                    "snapshot": restored["receipt"], "cold_process": cold_result,
                    "cold_returncode": cold.returncode, "cold_stdout_pin": pin(root/f"{action}-cold.stdout")}
            result["mutations"].append(item)
            emit({"phase": action, "passed": True, "mutation_wall_seconds": mutation_wall,
                  "mutation_cpu_seconds": mutation_cpu})
        checked(store.view() == original, "seed authority modified")
        checked(pin(args.source) == source_pin and pin(__file__) == harness_pin, "source drift")
        result["passed"] = True
        result["source_unchanged"] = True
    except Exception as error:
        result.update(passed=False, error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result.update(wall_seconds=time.perf_counter()-start, resources=usage())
        with (root/"RESULT.json").open("x") as output:
            json.dump(result, output, indent=2, sort_keys=True)
            output.write("\n")
        emit({"phase": "complete", "passed": result["passed"], "result_pin": pin(root/"RESULT.json")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output")
    parser.add_argument("--wall-budget", type=float, default=1200.0)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--store")
    parser.add_argument("--snapshot")
    parser.add_argument("--expected", type=int)
    args = parser.parse_args()
    child(args) if args.child else run(args)
