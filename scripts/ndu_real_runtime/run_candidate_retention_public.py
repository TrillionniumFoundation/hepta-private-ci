"""Execute fresh-source MEM6 retention pairs with the frozen public selector.

Both arms use the existing isolated actor/host path. Only current-only versus
bounded candidate retention differs. Raw failures remain in all denominators;
scoring begins after all actors have exited. No cross-session benefit is claimed.
"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from pathlib import Path
import time
import traceback

from ndu_real_materials.common import (
    binding,
    strict_json,
    write_json,
)
from .candidate_retention_public_plan import freeze, require
from .run_candidate_selection import collect_evidence, recover_attempts, run_pair


def run(request_path, output, *, report_generator=None):
    from . import run_candidate_retention as legacy

    request = strict_json(Path(request_path).read_bytes())
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), legacy._usage()
    receipt = {
        "schema": "ndu.real.candidate-retention-public-run.v1",
        "status": "Failed",
        "source_commit": request.get("source_commit"),
        "training_executed": False,
        "fixed_selector_mode": "public_rule",
        "memory_scope": "within_episode_working_state",
        "cross_session_memory_evaluated": False,
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
            "schema": "ndu.real.candidate-retention-public-evidence.v1",
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
            process_cost_accounting=(
                "Whole-run CPU/wall includes overlapping episode and verification "
                "envelopes; do not add levels"
            ),
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
        from .candidate_retention_public_report import generate

        receipt = run(args.request, args.output, report_generator=generate)
    else:
        receipt = run(args.request, args.output)
    if receipt["status"] != "Completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
