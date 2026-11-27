"""Run the frozen writer/read pair once; retain failures and all charged work."""

import argparse
import json
from pathlib import Path
import time

from fitting_common import (
    base_inventory,
    bounded,
    canonical,
    file_digest,
    read_json,
    remaining_timeout,
    require,
    resource_state,
    retain,
    retained_bytes,
    two_cpus,
    validate_protocol,
    verify_pin,
)
from fitting_observation import classify
from model_process import ChildFailure, run_child


def event_totals(directory):
    counts = dict(
        entered=0, completed=0, rejected_before_forward=0, entered_input_tokens=0
    )
    incomplete_lines = 0
    for path in sorted(directory.glob("*-forward-events.jsonl")):
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
                if type(event) is not dict or event.get("event") not in (
                    "entered",
                    "completed",
                    "rejected_before_forward",
                ):
                    raise ValueError("unrecognized forward event")
                name = event["event"]
                if name == "entered" and (
                    type(event.get("input_ids")) is not list
                    or not 1 <= len(event["input_ids"]) <= 208
                    or any(type(i) is not int or i < 0 for i in event["input_ids"])
                ):
                    raise ValueError("invalid entered input IDs")
            except (ValueError, TypeError):
                incomplete_lines += 1
                continue
            counts[name] += 1
            if name == "entered":
                counts["entered_input_tokens"] += len(event["input_ids"])
    return counts | dict(
        incomplete_event_lines=incomplete_lines,
        partial_forward_cost_unknown=bool(incomplete_lines)
        or counts["entered"] != counts["completed"],
    )


def seal_result(directory, result, limit):
    """Include final evidence overhead before deciding the retained result status."""
    result["retained_bytes_before_final_files"] = retained_bytes(directory)
    inventory = {
        str(p.relative_to(directory)): dict(
            bytes=p.stat().st_size, sha256=file_digest(p)
        )
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    inventory_bytes = len(canonical(inventory)) + 1
    projected = (
        result["retained_bytes_before_final_files"]
        + inventory_bytes
        + len(canonical(result))
        + 1
    )
    if projected > limit:
        result["status"] = "failed"
        result["artifact_limit_failure"] = dict(
            bytes_before_result=projected, limit=limit
        )
    retain(directory / "artifact-inventory-before-result.json", inventory)
    retain(directory / "result.json", result)


def run(directory, expected):
    directory = Path(directory).resolve()
    protocol = validate_protocol(directory, expected)
    require(
        not (directory / "attempt.json").exists(), "diagnostic attempt cannot repeat"
    )
    require(
        base_inventory(protocol["base"])
        == read_json(directory / "base-inventory.json"),
        "fixed base changed",
    )
    started = time.monotonic()
    deadline = started + 600
    retain(
        directory / "attempt.json",
        dict(
            started_unix_ns=time.time_ns(),
            protocol_sha256=expected,
            cpu_affinity=two_cpus(),
            resources=resource_state(directory),
            charged_forward_reservation=376,
            budget_refund=0,
            retry=False,
        ),
    )
    result = dict(
        schema="hepta.fitting-diagnostic.result.v1",
        protocol_sha256=expected,
        status="failed",
        charged_forward_reservation=376,
        budget_refund=0,
        automatic_retry=False,
        workers={},
        classification=None,
        source_unchanged=False,
        base_unchanged=False,
        autoregressive_generations=0,
        future_gate_satisfied=False,
        production_accepted=False,
    )
    try:
        for phase in ("train", "read"):
            bounded(directory, protocol)
            print("START " + phase, flush=True)
            try:
                process = run_child(
                    Path(__file__).with_name("fitting_worker.py"),
                    [
                        "--out",
                        str(directory),
                        "--protocol-sha256",
                        expected,
                        "--phase",
                        phase,
                    ],
                    timeout=remaining_timeout(deadline, 600),
                    cwd=directory,
                    receipt_dir=directory / "processes",
                    operation="fitting-" + phase,
                )
            except ChildFailure as error:
                retain(directory / f"{phase}-process.json", error.receipt)
                raise
            retain(directory / f"{phase}-process.json", process)
            worker = read_json(directory / f"{phase}-result.json")
            result["workers"][phase] = {
                "status": worker["status"],
                "pid": worker["pid"],
                "receipt_sha256": file_digest(directory / f"{phase}-result.json"),
            }
            require(
                worker["status"] == "complete" and worker["source_pin_after"],
                "diagnostic worker failed",
            )
            print("FINISH " + phase, flush=True)
        result["classification"] = classify(
            read_json(directory / "memory-teacher.json"),
            read_json(directory / "reload-teacher.json"),
            read_json(directory / "reload-prefill.json"),
        )
        totals = event_totals(directory)
        require(
            totals["entered"] == totals["completed"] == 376
            and totals["rejected_before_forward"]
            == totals["incomplete_event_lines"]
            == 0,
            "actual diagnostic forward sequence differs from complete reservation",
        )
        bounded(directory, protocol)
        verify_pin(directory, protocol)
        result["source_unchanged"] = True
        result["base_unchanged"] = base_inventory(protocol["base"]) == read_json(
            directory / "base-inventory.json"
        )
        require(
            result["base_unchanged"] and time.monotonic() <= deadline,
            "base or whole-run bound changed",
        )
        result["status"] = "complete"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"[:3000]
    finally:
        result["actual_forward_events"] = event_totals(directory)
        result["wall_seconds"] = time.monotonic() - started
        result["final_resources"] = resource_state(directory)
        seal_result(directory, result, protocol["limits"]["artifact_bytes"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    args = parser.parse_args()
    final = run(args.out, args.protocol_sha256)
    print(json.dumps(final["classification"]), flush=True)
    raise SystemExit(0 if final["status"] == "complete" else 1)
