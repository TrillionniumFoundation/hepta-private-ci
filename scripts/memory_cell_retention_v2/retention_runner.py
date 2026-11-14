"""Run the already frozen screen serially; never tune or retry after observation."""

import argparse
import os
from pathlib import Path
import shutil
import time

from retention_common import (
    base_inventory,
    digest,
    file_digest,
    read_json,
    remaining_timeout,
    require,
    retain,
    retained_bytes,
    verify_source_pin,
)
from retention_read import read_panels, summarize, withdrawal_probe
from memory_service import MemoryService
from model_process import ChildFailure, run_child


def bounded_state(output, protocol, started):
    verify_source_pin(
        output / "source-identity.json", protocol["source_identity_sha256"]
    )
    require(
        retained_bytes(output) < protocol["limits"]["retained_bytes"],
        "artifact budget exhausted",
    )
    require(
        shutil.disk_usage(output).free >= 250_000_000, "shared disk reserve exhausted"
    )
    require(
        time.monotonic() - started < protocol["limits"]["whole_screen_seconds"],
        "whole-screen time reservation exhausted",
    )


def run_trial(output, trial, protocol, started):
    directory = output / trial["trial_id"]
    request = read_json(directory / "train-request.json")
    require(digest(request) == trial["train_request_sha256"], "frozen arm changed")
    snapshot = read_json(directory / "snapshot.json")
    previous = read_json(directory / "previous-snapshot.json")
    panels = read_json(directory / "panels.json")
    require(
        digest(snapshot) == trial["snapshot_sha256"]
        and digest(previous) == trial["previous_sha256"]
        and digest(panels) == trial["panels_sha256"],
        "frozen diagnostic/source panel changed",
    )
    bounded_state(output, protocol, started)
    attempt = dict(
        trial_id=trial["trial_id"],
        started_unix_ns=time.time_ns(),
        reserved_training_forwards=256,
        budget_refund=0,
        request_sha256=trial["train_request_sha256"],
    )
    retain(directory / "attempt.json", attempt)
    result = dict(
        trial_id=trial["trial_id"],
        arm=trial["arm"],
        seed=trial["seed"],
        status="failed",
        charged_training_forwards=256,
        budget_refund=0,
        training=None,
        scores=None,
        withdrawal=None,
    )
    try:
        deadline = started + protocol["limits"]["whole_screen_seconds"]
        try:
            process = run_child(
                Path(__file__).with_name("train_worker.py"),
                [
                    "--request",
                    str(directory / "train-request.json"),
                    "--request-sha256",
                    trial["train_request_sha256"],
                ],
                timeout=remaining_timeout(
                    deadline, protocol["limits"]["train_seconds"]
                ),
                cwd=directory,
                receipt_dir=directory / "processes",
                operation="retention-v2-train",
            )
        except ChildFailure as error:
            retain(directory / "training-process.json", error.receipt)
            if (directory / "train-result.json").exists():
                result["training"] = read_json(directory / "train-result.json")
            raise
        retain(directory / "training-process.json", process)
        training = read_json(directory / "train-result.json")
        result["training"] = training
        require(
            training["status"] == "published"
            and training["source_pin_after"]
            and training["request_sha256"] == trial["train_request_sha256"],
            "fresh training did not complete with intact source pins",
        )
        bounded_state(output, protocol, started)
        service = MemoryService(
            request["service_root"],
            request["scope"],
            request["cell_id"],
            request["role"],
        )
        result["scores"] = read_panels(
            service,
            request,
            snapshot,
            previous,
            panels,
            directory,
            protocol["limits"]["reader_seconds"],
            deadline,
        )
        result["withdrawal"] = withdrawal_probe(service, snapshot)
        retain(directory / "withdrawal-probe.json", result["withdrawal"])
        bounded_state(output, protocol, started)
        result["status"] = "complete"
    except Exception as error:
        result["error"] = repr(error)[:3000]
    finally:
        retain(directory / "trial-result.json", result)
    return result


def costs(trials, output):
    trained = [t["training"] for t in trials if t.get("training") is not None]
    writes = [t["write_receipt"] for t in trained if t.get("write_receipt") is not None]
    reads = [t["scores"]["decoder_cost"] for t in trials if t.get("scores") is not None]
    processes = [read_json(p) for p in sorted(output.glob("*/processes/*.result.json"))]
    return dict(
        planned_trials=len(trials),
        attempted_trials=sum(t["status"] != "unexecuted" for t in trials),
        charged_training_forwards=sum(t["charged_training_forwards"] for t in trials),
        completed_training_forwards=sum(
            t["forward_audit"]["completed_model_forwards"]
            for t in trained
            if "forward_audit" in t
        ),
        unmeasured_training_attempts=sum(
            t["status"] != "unexecuted"
            and (t.get("training") is None or "forward_audit" not in t["training"])
            for t in trials
        ),
        completed_optimizer_updates=sum(w["steps"] for w in writes),
        completed_training_input_tokens=sum(w["input_tokens"] for w in writes),
        completed_training_supervised_tokens=sum(
            w["supervised_tokens"] for w in writes
        ),
        completed_training_fit_seconds=sum(w["seconds"] for w in writes),
        completed_panel_queries=sum(r["queries"] for r in reads),
        completed_panel_input_tokens=sum(r["input_tokens"] for r in reads),
        completed_panel_generated_tokens=sum(r["generated_tokens"] for r in reads),
        completed_panel_generation_seconds=sum(r["generation_seconds"] for r in reads),
        retained_process_receipts=len(processes),
        process_ids=[p["pid"] for p in processes],
        process_wall_seconds=sum(p["wall_seconds"] for p in processes),
        retained_bytes_before_result=retained_bytes(output),
        failed_panel_totals_are_lower_bounds=True,
        duplicated_checkpoint_training_receipts_counted=False,
    )


def run(output, expected):
    output = Path(output).resolve()
    protocol = read_json(output / "protocol.json")
    require(
        digest(protocol)
        == expected
        == read_json(output / "freeze.json")["protocol_sha256"],
        "registered screen protocol changed",
    )
    require(
        len(protocol["trials"]) == 9 and protocol["expected_training_forwards"] == 2304,
        "complete nine-trial reservation required",
    )
    for trial in protocol["trials"]:
        require(
            not (output / trial["trial_id"] / "attempt.json").exists(),
            "screen attempts are immutable and cannot be retried",
        )
    started = time.monotonic()
    bounded_state(output, protocol, started)
    base = read_json(output / protocol["trials"][0]["trial_id"] / "train-request.json")[
        "base"
    ]
    require(
        base_inventory(base) == read_json(output / "base-inventory.json"),
        "fixed base changed after registration",
    )
    affinity = None
    if hasattr(os, "sched_getaffinity"):
        affinity = sorted(os.sched_getaffinity(0))[:2]
        os.sched_setaffinity(0, affinity)
    retain(
        output / "launch.json",
        dict(
            protocol_sha256=expected,
            pid=os.getpid(),
            started_unix_ns=time.time_ns(),
            cpu_affinity=affinity,
        ),
    )
    results, stopped = [], False
    for trial in protocol["trials"]:
        if stopped:
            result = dict(
                trial_id=trial["trial_id"],
                arm=trial["arm"],
                seed=trial["seed"],
                status="unexecuted",
                charged_training_forwards=0,
                reason="earlier execution/integrity/resource failure; no retry",
            )
            retain(output / trial["trial_id"] / "trial-result.json", result)
        else:
            print(f"START {trial['trial_id']}", flush=True)
            try:
                result = run_trial(output, trial, protocol, started)
            except Exception as error:
                result = dict(
                    trial_id=trial["trial_id"],
                    arm=trial["arm"],
                    seed=trial["seed"],
                    status="unexecuted",
                    charged_training_forwards=0,
                    error=repr(error)[:2000],
                )
                retain(output / trial["trial_id"] / "trial-result.json", result)
            stopped = result["status"] != "complete"
            print(f"FINISH {trial['trial_id']} {result['status']}", flush=True)
        results.append(result)
    final = dict(
        schema="hepta.retention-v2.screen-result.v1",
        protocol_sha256=expected,
        trials=results,
        selection=summarize(protocol, results),
        costs=costs(results, output),
        wall_seconds=time.monotonic() - started,
        source_unchanged=False,
        base_unchanged=False,
        complete=not stopped,
        production_accepted=False,
    )
    try:
        verify_source_pin(
            output / "source-identity.json", protocol["source_identity_sha256"]
        )
        final["source_unchanged"] = True
        final["base_unchanged"] = base_inventory(base) == read_json(
            output / "base-inventory.json"
        )
        require(final["base_unchanged"], "fixed model bytes changed during screen")
    except Exception as error:
        final["integrity_error"] = repr(error)[:2000]
        final["complete"] = False
        final["selection"]["selected_arm"] = None
    inventory = {
        str(p.relative_to(output)): dict(bytes=p.stat().st_size, sha256=file_digest(p))
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    retain(output / "artifact-inventory-before-result.json", inventory)
    retain(output / "result.json", final)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    args = parser.parse_args()
    completed = run(args.output, args.protocol_sha256)
    print(completed["selection"], flush=True)
    if not completed["complete"]:
        raise SystemExit(1)
