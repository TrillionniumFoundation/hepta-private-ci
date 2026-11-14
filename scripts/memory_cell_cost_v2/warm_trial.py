"""Freeze a 20-query development proposal; execution is a separate explicit CLI."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from historical_inventory import save
from receipt_reader import load_summary, read_receipt, total
from storage_ledger import file_record
from warm_worker import GENERATION_LIMITS


HERE = Path(__file__).resolve().parent


def pin(path):
    row, _ = file_record(Path(path).resolve())
    return {k: row[k] for k in ("path", "bytes", "sha256")}


def checked(entry):
    if pin(entry["path"]) != entry:
        raise ValueError("pinned input changed: " + entry["path"])


def validate(p):
    jobs = p["jobs"]
    if (
        p["schema"] != "hepta.memory.warm-cost-proposal.v2"
        or len(jobs) != 20
        or p["order"] != ["retrieval", "memory"]
        or [(j["phase"], j["index"]) for j in jobs]
        != [("warmup", i) for i in range(2)] + [("measured", i) for i in range(18)]
        or p["budget"]["decoder_calls_including_warmup_max"] != 20
        or p["budget"]["training_updates"] != 0
        or p["generation_limits"] != GENERATION_LIMITS
        or p["budget"]["max_new_tokens_per_decoder"] != GENERATION_LIMITS["new_tokens"]
        or p["budget"]["max_complete_prompt_tokens"]
        != GENERATION_LIMITS["prompt_tokens"]
    ):
        raise ValueError("registered 2+18 query, zero-training protocol required")
    declared = {row["path"] for row in p["implementation"]}
    if not {str(path) for path in HERE.glob("*.py")} <= declared:
        raise ValueError("executed implementation is not the pinned source tree")
    if Path(p["python"]).resolve() != Path(sys.executable).resolve():
        raise ValueError("controller Python differs from frozen runtime")


def freeze(args):
    args.output.mkdir(parents=True, exist_ok=False)
    dev = args.development.resolve()
    historical = json.loads((dev / "protocol.json").read_bytes())
    payload = json.loads((dev / "runs/24041/adapter-request.json").read_bytes())[
        "payload"
    ]
    codes = [["F401"], ["E731"], ["E731", "F401"]]
    jobs = [
        {
            "phase": "warmup",
            "index": i,
            "query_id": str(i),
            "question": historical["questions"][i],
            "codes": codes[i],
        }
        for i in range(2)
    ]
    jobs += [
        {
            "phase": "measured",
            "index": i,
            "query_id": str(i % 3),
            "question": historical["questions"][i % 3],
            "codes": codes[i % 3],
        }
        for i in range(18)
    ]
    inventory_pin = pin(args.inventory)
    inventory = json.loads(args.inventory.read_bytes())
    inputs = [
        {k: row[k] for k in ("path", "bytes", "sha256")} for row in inventory["files"]
    ]
    sources = [
        pin(dev / "teaching" / code / "observation.json") for code in ("F401", "E731")
    ]
    implementation = [pin(path) for path in sorted(HERE.glob("*.py"))]
    supervisor = args.repo.resolve() / "scripts/memory_cell_evaluation"
    implementation += [
        pin(supervisor / name) for name in ("process_meter_v2.py", "bounded_process.py")
    ]
    proposal = {
        "schema": "hepta.memory.warm-cost-proposal.v2",
        "status": "frozen_proposal_not_executed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "implementation": implementation,
        "inventory": inventory_pin,
        "inputs": inputs,
        "python": str(Path(sys.executable)),
        "supervisor": str(supervisor),
        "jobs": jobs,
        "order": ["retrieval", "memory"],
        "sources": sources,
        "operations": list(historical["fixed_operations"]),
        "model_request": payload,
        "model_code": str(args.repo.resolve() / "scripts/memory_cell"),
        "generation_limits": dict(GENERATION_LIMITS),
        "judge": {
            "expected": historical["expected_development_operations"]
            + [historical["retrieval_operation"]],
            "normalization": "strip outer whitespace only",
            "raw_text_retained": True,
            "required_operation_exact": 18,
            "new_task_execution": False,
            "historical_76_test_evidence": pin(dev / "runs/retrieval-task/result.json"),
        },
        "limits": {
            "cpu_seconds": 120,
            "wall_seconds": 150,
            "address_bytes": 8 * 1024**3,
            "output_file_bytes": 4 * 1024**2,
        },
        "budget": {
            "training_updates": 0,
            "decoder_calls_including_warmup_max": 20,
            "retrieval_calls_including_warmup_max": 20,
            "automatic_retries": 0,
            "warmups_per_arm": 2,
            "measured_per_arm": 18,
            "threads": 1,
            "concurrency": 1,
            "max_new_tokens_per_decoder": 16,
            "max_complete_prompt_tokens": 192,
            "input_token_upper_bound": 3840,
            "output_token_upper_bound": 320,
            "address_limit_is_not_rss": True,
            "rss_hard_limit": None,
        },
        "quality_scope": {
            "exposed_historical_task_groups": 1,
            "independent_future_groups": 0,
            "three_query_forms_are_not_three_independent_tasks": True,
            "net_compression_gain": None,
            "strong_rag_qualified": False,
        },
        "method": [
            "Same frozen diagnostic questions and typed codes, single process per arm, fixed retrieval-first order.",
            "Retrieval verifies original tool-observation bytes and intersects actual successful operations; strong only for this closed typed two-rule contract.",
            "Memory receives no source values or expected answers; only frozen checkpoint, source digests and questions. This is prompt separation, not hostile-process isolation.",
            "No arbitrary repair solver or new semantic task run is included; operation accuracy is reported separately from retained historical 76-test success.",
            "All startup, warmup, measured and failed work retained; decoder-start/finish markers precede generation and survive later validation failure.",
            "Actual generate entry enforces at most 20 attempts, full prompt <=192 tokens and max_new_tokens exactly16; returned output must fit16. Failed entered calls remain spent.",
            "Report raw samples and nearest-rank p50/p95, failed/unattempted denominators; 18 repeated queries cannot establish scale or an SLA.",
            "Closed-loop throughput uses the complete measured interval including journal gaps. Arm order/cache effects are not randomized causal evidence.",
            "Per-child wait4 is charged once; in-process samples are attribution only. Whole-host CPU, energy, dollars and transient-byte-time remain null.",
            "A separate controller receipt meters self CPU and complete execute wall, including both inventory admissions, child waiting and final result serialization; child CPU is added once, never included in self CPU.",
            "Parent-alive worker timeout/process-group cleanup only; no parent-death containment or hostile same-UID isolation claim.",
            "Any source/runtime/implementation drift stops execution. Post-format source needs a new explicit protocol or an audited publication binding.",
        ],
    }
    save(args.output / "protocol.json", proposal)
    return pin(args.output / "protocol.json")


def execute_body(args):
    raw = args.protocol.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.protocol_sha256:
        raise ValueError("protocol pin mismatch")
    p = json.loads(raw)
    validate(p)
    rows, results, error, admitted, post_integrity_error = [], {}, None, False, None
    try:
        checked(p["inventory"])
        for entry in p["inputs"] + p["implementation"]:
            checked(entry)
        admitted = True
        sys.path.insert(0, p["supervisor"])
        from process_meter_v2 import run

        for arm in p["order"]:
            request = {
                "mode": arm,
                "jobs": p["jobs"],
                "generation_limits": p["generation_limits"],
                "protocol_sha256": args.protocol_sha256,
            }
            request.update(
                {
                    k: p[k]
                    for k in (
                        ("sources", "operations")
                        if arm == "retrieval"
                        else ("model_code", "model_request")
                    )
                }
            )
            path = args.output / (arm + "-request.json")
            save(path, request)
            environment = dict(
                os.environ,
                PYTHONDONTWRITEBYTECODE="1",
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                TOKENIZERS_PARALLELISM="false",
                OMP_NUM_THREADS="1",
                MKL_NUM_THREADS="1",
                RAYON_NUM_THREADS="1",
                CUDA_VISIBLE_DEVICES="",
            )
            process = run(
                [
                    p["python"],
                    "-B",
                    str(HERE / "warm_worker.py"),
                    "--request",
                    str(path),
                    "--request-sha256",
                    pin(path)["sha256"],
                ],
                HERE,
                args.output / arm,
                p["limits"],
                environment,
            )
            cost = read_receipt(
                args.output / arm / "process.json",
                format_name="wait4-v2",
                attempt_id=arm,
            )
            rows.append(cost)
            events, parse_errors = [], []
            for line in (args.output / arm / "stdout").read_bytes().splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError as caught:
                    parse_errors.append(repr(caught))
            samples = [r for r in events if r.get("event") == "sample"]
            measured = [r for r in samples if r["phase"] == "measured"]
            exact = sum(
                r["success"]
                and r["result"]["text"].strip()
                == p["judge"]["expected"][int(r["query_id"])]
                for r in measured
            )
            metrics = load_summary(samples, 18)
            interval = metrics["measurement_interval_ns"]
            results[arm] = {
                "metrics": metrics,
                "operation_exact": exact,
                "correct_operation_queries_per_second": exact * 1_000_000_000 / interval
                if interval
                else None,
                "parse_errors": parse_errors,
                "startup": [r for r in events if r.get("event") == "startup"],
                "decoder_started": sum(
                    r.get("event") == "decoder_started" for r in events
                ),
                "decoder_finished": sum(
                    r.get("event") == "decoder_finished" for r in events
                ),
                "queries_started": sum(
                    r.get("event") == "query_started" for r in events
                ),
                "completed_samples": len(samples),
                "events": events,
                "started_without_sample": sum(
                    r.get("event") == "query_started" for r in events
                )
                - len(samples),
            }
            if (
                process["returncode"] != 0
                or cost["failed"]
                or len(samples) != 20
                or parse_errors
            ):
                raise ValueError(
                    "worker incomplete or failed; retain all partial work, no retry"
                )
    except Exception as caught:
        error = repr(caught)
    finally:
        if admitted:
            try:
                for entry in p["inputs"] + p["implementation"]:
                    checked(entry)
            except Exception as caught:
                post_integrity_error = repr(caught)
    report = {
        "schema": "hepta.memory.warm-cost-result.v2",
        "protocol_sha256": args.protocol_sha256,
        "error": error or post_integrity_error,
        "post_integrity_error": post_integrity_error,
        "arms": results,
        "charged_process_cost": total(rows),
        "new_training_updates": 0,
        "independent_future_tasks": 0,
        "net_compression_gain": None,
    }
    save(args.output / "result.json", report)
    return report


def execute(args):
    wall, cpu = time.monotonic_ns(), time.process_time_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    result, error = None, None
    try:
        result = execute_body(args)
        return result
    except Exception as caught:
        error = repr(caught)
        raise
    finally:
        self_cpu, elapsed = time.process_time_ns() - cpu, time.monotonic_ns() - wall
        child_cpu = (
            result["charged_process_cost"]["dimensions"]["cpu_ns"]["total"]
            if result
            else None
        )
        save(
            args.output / "controller-cost.json",
            {
                "schema": "hepta.memory.warm-controller-cost.v1",
                "error": error or (result.get("error") if result else None),
                "self_cpu_ns": self_cpu,
                "whole_execute_wall_ns": elapsed,
                "charged_child_cpu_ns": child_cpu,
                "controller_plus_child_cpu_ns": None
                if child_cpu is None
                else self_cpu + child_cpu,
                "self_cpu_excludes_child_cpu": True,
                "cutoff": "after execute_body returns/raises, including result serialization; excludes this receipt serialization",
                "whole_host_cpu_ns": None,
                "energy_joules": None,
                "billing_usd": None,
            },
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    for name in ("repo", "development", "inventory", "output"):
        prepare.add_argument("--" + name, type=Path, required=True)
    run = sub.add_parser("execute")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--protocol-sha256", required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = freeze(args) if args.command == "freeze" else execute(args)
    print(
        json.dumps(result if args.command == "freeze" else {"error": result["error"]})
    )
    sys.exit(0 if args.command == "freeze" or result["error"] is None else 1)
