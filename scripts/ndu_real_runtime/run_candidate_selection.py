"""Execute released prospective selector pairs with complete failure accounting.

The selector modes share bounded memory and the frozen model/OCR/control inputs.
Each actor additionally compares both selectors on its actual shared support.
Those shadow choices are not counterfactual terminal deliveries. Sealed-role
host/evaluator guards are unchanged. Optional independent reporting runs only
after every actor lifetime has ended.
"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import multiprocessing
from pathlib import Path
import time
import traceback

from ndu_real_materials.common import (
    binding,
    read_bound,
    read_relative,
    strict_json,
    write_json,
)
from .candidate_selection_plan import freeze, require


def recover_attempts(root, pair, error):
    """Never erase an earlier successful arm when its paired worker fails later."""
    rows = []
    for job in pair:
        operation = job["expected"]["original_operation_id"]
        path = root / "attempts" / (operation + ".json")
        row = {
            "original_operation_id": operation,
            "status": "Unknown",
            "error": {"type": type(error).__name__, "message": str(error)},
            "wall_seconds": None,
            "cpu_seconds": None,
            "retry_of": None,
        }
        if path.is_file():
            try:
                retained = strict_json(path.read_bytes())
                require(
                    isinstance(retained, dict)
                    and retained.get("original_operation_id") == operation
                    and isinstance(retained.get("status"), str)
                    and retained["status"]
                    in {"Completed", "Failed", "BudgetStop", "Timeout", "Unknown"},
                    "Retained attempt identity or terminal status is invalid",
                )
                row = retained
            except Exception as invalid:
                row.update(
                    comparison_invariant_failure="retained_attempt",
                    retained_attempt=binding(path, root),
                    retained_attempt_error=str(invalid),
                )
        rows.append(row)
    return rows


def run_episode(request, root, job, frozen_ocr):
    from . import run_candidate_retention as legacy
    from .episode import EpisodeHost

    root = Path(root)
    expected = job["expected"]
    operation = expected["original_operation_id"]
    wall, cpu = time.perf_counter(), legacy._usage()
    record = {
        "original_operation_id": operation,
        "selector_mode": expected["selector_mode"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "Unknown",
        "retry_of": None,
    }
    legacy.event(root, {**record, "event": "started"})
    invariant_stage = "before_episode"
    try:
        legacy.verify_sources(request)
        require(
            legacy.ocr_inventory(request["config"]) == frozen_ocr,
            "OCR inventory changed before the episode",
        )
        invariant_stage = None
        profile = {
            "original_operation_id": operation,
            "weights": request["model"]["weights"]["path"],
            "model_sha256": expected["weights_sha256"],
            "training_receipt_sha256": request["model"]["receipt"]["sha256"],
            "core": request["model"]["core"],
            "controller": "tuned_fixed",
            "control_plan": str(root / "CONTROL.json"),
            "control_plan_sha256": expected["control_plan_sha256"],
            "candidate_memory": expected["candidate_memory_profile"],
            "candidate_selector": expected["candidate_selector_profile"],
        }
        result = EpisodeHost(
            request["config"], job["case"], profile, root / "episodes" / operation
        ).run()
        record["status"] = result["terminal_status"]
        invariant_stage = "after_episode"
        legacy.verify_sources(request)
        require(
            legacy.ocr_inventory(request["config"]) == frozen_ocr,
            "OCR inventory changed during the episode",
        )
        invariant_stage = None
    except Exception as error:
        record.update(
            status="Failed",
            error={
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        if invariant_stage is not None:
            record["comparison_invariant_failure"] = invariant_stage
    record.update(
        wall_seconds=time.perf_counter() - wall,
        cpu_seconds=legacy._usage() - cpu,
        energy_joules=None,
        provider_charges=None,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    path = root / "attempts" / (operation + ".json")
    write_json(path, record)
    legacy.event(
        root,
        {
            "event": "finished",
            "original_operation_id": operation,
            "status": record["status"],
            "receipt": binding(path, root),
        },
    )
    return record


def run_pair(request, root, pair, plan_sha):
    root = Path(root)
    raw = read_relative(root, "PLAN.json", limit=8 * 1024**2)
    require(
        hashlib.sha256(raw).hexdigest() == plan_sha,
        "Original pre-execution selection plan changed",
    )
    frozen_ocr = strict_json(raw)["ocr_inventory"]
    return [run_episode(request, root, job, frozen_ocr) for job in pair]


def collect_evidence(root, expected):
    from .run_candidate_retention import evidence

    item = evidence(root, expected)
    item["selector_audits"] = []
    if item["trajectory"] is None:
        return item
    directory = root / "episodes" / expected["original_operation_id"]
    try:
        trajectory = strict_json(read_bound(root, item["trajectory"]))
        for step in trajectory["steps"]:
            audit = step.get("selector_audit")
            if audit is None:
                item["selector_audits"].append(None)
                continue
            require(
                isinstance(audit, dict)
                and isinstance(audit.get("path"), str)
                and Path(audit["path"]).name == audit["path"]
                and audit["path"] not in {".", ".."},
                "Selector audit must be a direct actor-output child",
            )
            # Preserve actor-provided byte/hash identities even if a file is damaged.
            item["selector_audits"].append(
                {
                    **audit,
                    "path": (directory / "actor-output" / audit["path"])
                    .relative_to(root)
                    .as_posix(),
                }
            )
    except Exception as error:
        item["selector_collection_error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    return item


def run(request_path, output, *, report_generator=None):
    from . import run_candidate_retention as legacy

    request = strict_json(Path(request_path).read_bytes())
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), legacy._usage()
    receipt = {
        "schema": "ndu.real.candidate-selection-run.v1",
        "status": "Failed",
        "source_commit": request.get("source_commit"),
        "training_executed": False,
        "evaluation_role": "prospective_development_validation",
        "confirmation_evaluated": False,
        "energy_joules": None,
        "provider_charges": None,
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
    }
    try:
        write_json(output / "REQUEST.json", request)
        (output / "runner.jsonl").touch(exist_ok=False)
        (output / "attempts").mkdir()
        plan, jobs = freeze(request, output)
        plan_sha = legacy.file_sha(output / "PLAN.json")
        receipt.update(
            model_load=binding(output / "MODEL.json", output),
            weights_sha256_before=strict_json((output / "MODEL.json").read_bytes())[
                "actual_weights_sha256"
            ],
        )
        records = []
        with ProcessPoolExecutor(
            max_workers=request["max_workers"],
            mp_context=multiprocessing.get_context("spawn"),
        ) as pool:
            futures = {
                pool.submit(run_pair, request, str(output), pair, plan_sha): pair
                for pair in jobs
            }
            for future in as_completed(futures):
                try:
                    records.extend(future.result())
                except Exception as error:
                    records.extend(recover_attempts(output, futures[future], error))
        require(
            len(records) == len(plan["episodes"])
            and len({r["original_operation_id"] for r in records}) == len(records)
            and {r["original_operation_id"] for r in records}
            == {r["original_operation_id"] for r in plan["episodes"]},
            "Complete planned operation roster differs from returned attempts",
        )
        receipt.update(
            planned_episodes=len(plan["episodes"]),
            source_group_count=len({r["source_group_id"] for r in plan["episodes"]}),
            terminal_status_counts=dict(Counter(r["status"] for r in records)),
            attempts=records,
            plan_sha256=plan_sha,
            independent_training_repeats=0,
            frozen_checkpoint_count=1,
        )
        # All worker/actor lifetimes ended before independent report generation.
        manifest = {
            "schema": "ndu.real.candidate-selection-evidence.v1",
            "plan_sha256": plan_sha,
            "episodes": [collect_evidence(output, row) for row in plan["episodes"]],
        }
        write_json(output / "EVIDENCE.json", manifest)
        require(
            legacy.file_sha(output / "PLAN.json") == plan_sha,
            "Original pre-execution plan changed; report withheld",
        )
        require(
            not any(r.get("comparison_invariant_failure") for r in records),
            "Comparison invariant failed; report withheld and raw evidence preserved",
        )
        legacy.verify_sources(request)
        require(
            legacy.ocr_inventory(request["config"]) == plan["ocr_inventory"],
            "Frozen OCR inventory changed",
        )
        for pin in (
            request["catalog"],
            request["exclusion_manifest"],
            request["training_records"],
            *request["exposure_ledgers"],
            *request["prior_episode_plan_pins"],
        ):
            legacy.read_pin(pin, request["config"]["material_root"])
        for pin in request["model"].values():
            if isinstance(pin, dict):
                legacy.read_pin(pin, request["config"]["material_root"])
        if report_generator is not None:
            report = report_generator(
                output,
                request["config"]["material_root"],
                plan_sha,
                legacy.file_sha(output / "EVIDENCE.json"),
            )
            write_json(output / "REPORT.json", report)
            receipt.update(
                report_status="GENERATED",
                report_sha256=legacy.file_sha(output / "REPORT.json"),
            )
        else:
            receipt["report_status"] = "PENDING_INDEPENDENT_REPORT"
        receipt.update(
            status="Completed"
            if all(r["status"] != "Unknown" for r in records)
            else "Unresolved",
            all_actor_episodes_completed=all(
                r["status"] == "Completed" for r in records
            ),
            weights_sha256_after=legacy.file_sha(request["model"]["weights"]["path"]),
            source_pins_unchanged=True,
            process_cost_accounting="Whole-run CPU/wall includes overlapping episode and verification envelopes; do not add levels",
        )
    except Exception as error:
        receipt["error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
    receipt.update(
        wall_seconds=time.perf_counter() - started, cpu_seconds=legacy._usage() - cpu
    )
    write_json(output / "RUN_RECEIPT.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--independent-report", action="store_true")
    args = parser.parse_args()
    if args.independent_report:
        from .candidate_selection_report import generate

        receipt = run(args.request, args.output, report_generator=generate)
    else:
        receipt = run(args.request, args.output)
    if receipt["status"] != "Completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
