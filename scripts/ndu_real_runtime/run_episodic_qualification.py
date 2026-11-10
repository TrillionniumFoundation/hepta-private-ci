"""Fresh-process MEM6 mechanism fixtures, never a neural task-benefit benchmark.

The producer, consumer processes, read receipts and actual delivery files are
retained. Expected values are checked by the parent after each consumer exits;
they are absent from consumer requests. This is not an OS trust-domain boundary.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .episodic_memory import EpisodicStore, WorkingState, canonical_bytes
from .episodic_retrieval import read_memory, verify_read_receipt


def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical_bytes(value) + b"\n")


def pin(path, root):
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def worker(request_path):
    """Consume only the public fixture query, then publish an actual delivery."""
    started, cpu = time.perf_counter(), time.process_time()
    raw = request_path.read_bytes()
    if len(raw) > 16384:
        raise ValueError("bounded fixture request required")
    request = json.loads(raw)
    if set(request) != {
        "session_id",
        "namespace",
        "source_ids",
        "key",
        "query",
        "strategy",
        "mode",
        "snapshot",
    }:
        raise ValueError("closed consumer request required; no evaluator fields")
    root = request_path.parent.parent
    snapshot = request.pop("snapshot")
    if snapshot is not None and snapshot != "before-update.json":
        raise ValueError("only the retained fixture snapshot is permitted")
    namespace = request.pop("namespace")
    store = (
        None
        if request["mode"] == "off"
        else EpisodicStore(root / "authority.sqlite", namespace=namespace, create=False)
    )
    working = WorkingState(request["session_id"])
    result = read_memory(
        store,
        **request,
        limit=8,
        max_context_bytes=4096,
        snapshot_path=None if snapshot is None else root / snapshot,
    )
    if not verify_read_receipt(result):
        raise ValueError("read receipt does not match actual delivered bytes")
    delivery = {
        "schema": "hepta.mem6.fixture-delivery.v1",
        "texts": [row["text"] for row in result["records"]],
        "record_ids": result["receipt"]["delivered_ids"],
        "context": result["context"],
    }
    path = request_path.with_name("delivery.json")
    write(path, delivery)
    response = {
        "schema": "hepta.mem6.fixture-consumer.v1",
        "pid": os.getpid(),
        "session_id": request["session_id"],
        "receipt": result["receipt"],
        "delivery": pin(path, root),
        "working_state_empty": not working._values,
        "model_calls": 0,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
    }
    write(request_path.with_name("response.json"), response)


def producer(request_path):
    """Finish one fixture mutation batch before any successor reader starts."""
    request = json.loads(request_path.read_bytes())
    root = request_path.parent.parent
    store = EpisodicStore(
        root / "authority.sqlite",
        namespace="owner-a",
        max_records=32,
        max_serialized_bytes=65536,
    )
    records = {}
    for operation in request:
        action = operation["action"]
        if action == "put":
            arguments = dict(operation["arguments"])
            arguments["dependencies"] = [
                records[k]["record_id"] for k in operation.get("depends_on", [])
            ]
            records[operation["name"]] = store.put(**arguments)
        elif action == "revoke":
            store.revoke(**operation["arguments"])
        elif action == "snapshot":
            store.export_snapshot(root / "before-update.json")
        else:
            raise ValueError("unknown fixture mutation")
    write(
        request_path.with_suffix(".response.json"),
        {"pid": os.getpid(), "records": records},
    )


SCENARIOS = (
    "exact_on",
    "persistence_off",
    "retrieval_off",
    "delivery_off",
    "association_unavailable",
    "association_disabled",
    "bm25",
    "uniform_replay",
    "icl_context",
    "irrelevant_source",
    "other_namespace",
    "similar_other_flow",
    "updated_fact",
    "stale_snapshot",
    "dependent_fact_invalidated",
    "revoked_fact",
    "revoked_snapshot",
    "unrelated_fact_preserved",
)


def run(output, source_commit=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    repository = Path(__file__).resolve().parents[2]
    sources = [
        Path(__file__),
        Path(__file__).with_name("episodic_memory.py"),
        Path(__file__).with_name("episodic_retrieval.py"),
        Path(__file__).with_name("episodic_receipt.py"),
    ]
    plan = {
        "schema": "hepta.mem6.mechanism-plan.v1",
        "source_commit": source_commit,
        "source_pins": [pin(path, repository) for path in sources],
        "scenarios": list(SCENARIOS),
        "fixture_data": "synthetic",
        "consumer": "deterministic evidence delivery; no neural model",
        "independent_trust_domain": False,
        "scientific_acceptance": "HOLD",
    }
    write(output / "PLAN.json", plan)
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(repository / "scripts") + os.pathsep + str(repository),
    }
    (output / "mutations").mkdir()
    producer_receipts = []

    def mutate(name, operations):
        request = output / "mutations" / (name + ".json")
        write(request, operations)
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "ndu_real_runtime.run_episodic_qualification",
                "--producer",
                str(request),
            ],
            cwd=repository,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        request.with_suffix(".stdout.txt").write_bytes(completed.stdout)
        request.with_suffix(".stderr.txt").write_bytes(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(
                "fixture producer failed; retained stderr: " + str(request)
            )
        response = request.with_suffix(".response.json")
        producer_receipts.append(
            {
                "request": pin(request, output),
                "response": pin(response, output),
                "returncode": completed.returncode,
                "writer_exited_before_successor": True,
            }
        )
        return json.loads(response.read_bytes())["records"]

    def provenance(text, episode):
        return {
            "source_uri": "fixture://mem6/" + episode,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_version": episode,
            "episode_id": episode,
        }

    original = "Delivery address is Cedar Street."
    updated = "Delivery address is Maple Street."
    other_flow = "Review the request before submitting."
    learned = mutate(
        "learn",
        [
            {
                "action": "put",
                "name": "fact",
                "arguments": {
                    "source_id": "source-address",
                    "key": "address",
                    "text": original,
                    "provenance": provenance(original, "learn-1"),
                },
            },
            {
                "action": "put",
                "name": "derived",
                "depends_on": ["fact"],
                "arguments": {
                    "source_id": "source-derived",
                    "key": "route",
                    "text": "Route package to Cedar Street.",
                    "provenance": provenance(
                        "Route package to Cedar Street.", "learn-2"
                    ),
                },
            },
            {
                "action": "put",
                "name": "flow",
                "arguments": {
                    "source_id": "source-flow",
                    "key": "address",
                    "text": other_flow,
                    "provenance": provenance(other_flow, "learn-3"),
                },
            },
            {"action": "snapshot"},
        ],
    )
    fact = learned["fact"]
    rows, pids = [], set()

    def check(
        name,
        expected_texts,
        *,
        mode="on",
        strategy="exact_kv",
        source="source-address",
        key="address",
        namespace="owner-a",
        query="",
        snapshot=None,
        expected_receipt=None,
    ):
        directory = output / name
        directory.mkdir()
        request = {
            "session_id": "fresh-" + name,
            "namespace": namespace,
            "source_ids": [source],
            "key": key,
            "query": query,
            "strategy": strategy,
            "mode": mode,
            "snapshot": snapshot,
        }
        request_path = directory / "request.json"
        write(request_path, request)
        launched = time.perf_counter()
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "ndu_real_runtime.run_episodic_qualification",
                    "--worker",
                    str(request_path),
                ],
                cwd=repository,
                env=env,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            completed = subprocess.CompletedProcess(
                [], 124, error.stdout or b"", error.stderr or b""
            )
        (directory / "stdout.txt").write_bytes(completed.stdout)
        (directory / "stderr.txt").write_bytes(completed.stderr)
        row = {
            "scenario": name,
            "expected_texts": expected_texts,
            "returncode": completed.returncode,
            "passed": False,
            "wall_seconds_with_startup": time.perf_counter() - launched,
            "request": pin(request_path, output),
        }
        if completed.returncode == 0:
            response_path = directory / "response.json"
            response = json.loads(response_path.read_bytes())
            delivery = json.loads((directory / "delivery.json").read_bytes())
            receipt = response["receipt"]
            row["passed"] = (
                delivery["texts"] == expected_texts
                and delivery["record_ids"] == receipt["delivered_ids"]
                and response["delivery"] == pin(directory / "delivery.json", output)
                and response["working_state_empty"] is True
                and response["pid"] != os.getpid()
                and response["session_id"] == request["session_id"]
                and response["model_calls"] == 0
                and all(
                    receipt.get(k) == v for k, v in (expected_receipt or {}).items()
                )
            )
            pids.add(response["pid"])
            row.update(
                response=pin(response_path, output),
                receipt=receipt,
                actual_texts=delivery["texts"],
            )
        rows.append(row)

    check("exact_on", [original], expected_receipt={"store_read": True})
    check(
        "persistence_off",
        [],
        mode="off",
        expected_receipt={"store_read": False, "retrieval_executed": False},
    )
    check(
        "retrieval_off",
        [],
        mode="retrieval_off",
        expected_receipt={"store_read": True, "retrieval_executed": False},
    )
    check(
        "delivery_off",
        [],
        mode="delivery_off",
        expected_receipt={
            "store_read": True,
            "retrieval_executed": True,
            "retrieved_ids": [fact["record_id"]],
            "delivered_ids": [],
        },
    )
    check(
        "association_unavailable",
        [original],
        expected_receipt={"association_status": "unavailable"},
    )
    check(
        "association_disabled",
        [original],
        mode="association_off",
        expected_receipt={"association_status": "disabled"},
    )
    check("bm25", [original], strategy="bm25", query="delivery address")
    check("uniform_replay", [original], strategy="uniform_replay")
    check("icl_context", [original], strategy="icl")
    check("irrelevant_source", [], source="absent-source")
    check("other_namespace", [], namespace="owner-b")
    check("similar_other_flow", [other_flow], source="source-flow")
    mutate(
        "update",
        [
            {
                "action": "put",
                "name": "updated",
                "arguments": {
                    "source_id": "source-address",
                    "key": "address",
                    "text": updated,
                    "provenance": provenance(updated, "update-1"),
                },
            }
        ],
    )
    check("updated_fact", [updated])
    check("stale_snapshot", [], snapshot="before-update.json")
    check("dependent_fact_invalidated", [], source="source-derived", key="route")
    mutate(
        "revoke",
        [
            {
                "action": "revoke",
                "arguments": {"source_id": "source-address", "key": "address"},
            }
        ],
    )
    check("revoked_fact", [])
    check("revoked_snapshot", [], snapshot="before-update.json")
    check("unrelated_fact_preserved", [other_flow], source="source-flow")
    report = {
        "schema": "hepta.mem6.mechanism-report.v1",
        "plan": pin(output / "PLAN.json", output),
        "rows": rows,
        "producer_receipts": producer_receipts,
        "planned_scenarios": len(SCENARIOS),
        "completed_scenarios": len(rows),
        "passed_scenarios": sum(row["passed"] for row in rows),
        "fresh_process_invocations": len(rows),
        "distinct_observed_pids": len(pids),
        "status": "PASS"
        if len(rows) == len(SCENARIOS) and all(row["passed"] for row in rows)
        else "FAIL",
        "wall_seconds": time.perf_counter() - started,
        "parent_cpu_seconds": time.process_time() - cpu,
        "source_pins_unchanged": plan["source_pins"]
        == [pin(p, repository) for p in sources],
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
        "unseen_task_benefit_evaluated": False,
        "neural_association_evaluated": False,
        "actual_effect": "local fixture delivery file only",
        "full_owner_cold_recovery": False,
        "independent_trust_domain": False,
        "deletion_scope": "logical read exclusion, not physical snapshot erasure",
    }
    if not report["source_pins_unchanged"]:
        report["status"] = "FAIL"
    write(output / "REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--worker", type=Path)
    group.add_argument("--producer", type=Path)
    group.add_argument("--output", type=Path)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return 0
    if args.producer:
        producer(args.producer)
        return 0
    report = run(args.output, args.source_commit)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "passed_scenarios", "scientific_acceptance")
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
