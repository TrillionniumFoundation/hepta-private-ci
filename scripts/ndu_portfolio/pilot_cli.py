"""Execute separately bounded collect -> score -> fit -> development stages.

Every stage needs the externally pinned plan; stage inputs are separately pinned.
Run each invocation under the existing outer command meter. No stage retries or
silently omits failed attempts, and no stage can produce scientific/native PASS.
"""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import time
import uuid

import torch

from .pilot_data import (
    CASE_IDS,
    SCHEDULES,
    STRATEGIES,
    SUCCESS,
    code_binding,
    load_pool,
    make_plan,
    read_plan,
    score_episode,
    training_rows,
    tune_fixed,
)
from .real_controllers import Controller, check_equal_opportunity
from .real_encoding import FrozenSmolEncoder
from .real_execution import _sha, _write, execute, load_predictor
from .real_predictor import Opportunity, PredictiveModel, digest, fit_predictive


@contextmanager
def phase(plan, output, name, roster):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time(), time.perf_counter()
    report = {
        "phase": name,
        "attempt_id": uuid.uuid4().hex,
        "plan_digest": digest(plan),
        "source_sha": plan["source_sha"],
        "code_sha256": code_binding(),
        "status": "started",
        "claim_status": "HOLD",
        "native_owner_verified": False,
        "cost_scope": "inclusive_current_process_phase; nested_episode_and_fit_times_are_not_additive",
        "entries": [{**row, "status": "not_started"} for row in roster],
        "unknown_costs": [
            "energy",
            "accelerator_charge",
            "prior_phases",
            "outer_process_and_final_write",
        ],
    }
    _write(output / "PHASE.json", report)
    try:
        yield report, start[1]
        report["status"] = (
            "completed"
            if all(
                row["status"] in ("completed", SUCCESS, "abstained")
                for row in report["entries"]
            )
            else "incomplete"
        )
    except (Exception, KeyboardInterrupt) as error:
        report.update(
            status="cancelled" if isinstance(error, KeyboardInterrupt) else "failed",
            error={"type": type(error).__name__, "message": str(error)},
        )
        raise
    finally:
        report.update(
            cpu_seconds=time.process_time() - start[0],
            wall_seconds=time.perf_counter() - start[1],
        )
        if (
            report["wall_seconds"] > plan["profile"]["phase_wall_seconds"]
            and report["status"] == "completed"
        ):
            report["status"] = "budget_exhausted"
        _write(output / "PHASE.json", report)


def before_task(plan, start, row, reserve_seconds=0):
    if (
        time.perf_counter() - start + reserve_seconds
        >= plan["profile"]["phase_wall_seconds"]
    ):
        row["status"] = "not_started_budget_exhausted"
        return False
    return True


def inputs(path, sha, plan, phase_name, *, require_complete=True):
    path = Path(path)
    if not sha or _sha(path) != sha:
        raise ValueError("Prior phase differs from its external pin")
    report = json.loads(path.read_text())
    if report["plan_digest"] != digest(plan) or report["phase"] != phase_name:
        raise ValueError("Prior phase belongs to another plan/stage")
    if require_complete and report["status"] != "completed":
        raise ValueError("An incomplete physical roster cannot be silently reduced")
    return report


def backend_for(plan, args):
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.local_models import (
        LocalModels,
    )

    profile = plan["profile"]
    backend = LocalModels(
        Path(args.models) / "vlm",
        Path(args.models) / "sd",
        threads=profile["threads"],
        device=profile["device"],
        dtype=profile["dtype"],
    )
    backend._placement()  # Actual CUDA/dtype preflight before model setup; no CPU fallback.
    if profile["device"].startswith("cuda"):
        if (
            not args.device_smoke
            or not args.device_smoke_sha256
            or _sha(args.device_smoke) != args.device_smoke_sha256
        ):
            raise ValueError("CUDA pilot needs a separately pinned actual device smoke")
        smoke = json.loads(Path(args.device_smoke).read_text())
        actual = backend.identity()
        if (
            smoke["status"] != "completed"
            or smoke["gpu_execution_verified"] is not True
            or smoke["source_sha"] != plan["source_sha"]
            or any(
                smoke["backend"][key] != actual[key]
                for key in ("device", "dtype", "reviewed_model_pins", "versions")
            )
        ):
            raise ValueError(
                "Actual device smoke does not qualify this exact runtime profile"
            )
    return backend


def actor(plan, model, strategy, schedule):
    return Controller(
        model,
        strategy,
        Opportunity(**plan["opportunity"]),
        fixed=tuple(schedule),
        gamma=plan["gamma"],
        cost_weight=plan["profile"]["cost_weight"],
        failure_score=plan["failure_score"],
        discount=plan["discount"],
        allowed_actions=plan["allowed_actions"],
    )


def episode(plan, pool, case, backend, controller, output, *, collect=False):
    from ndu_semantic_state.source_pool import load_candidate_public_case

    profile = plan["profile"]
    # Only this projection crosses into online code. Source/reference metadata stays outside.
    public = load_candidate_public_case(pool, case)
    fit_id = (
        None
        if controller.model.fit_receipt is None
        else controller.model.fit_receipt["attempt_id"]
    )
    return execute(
        public,
        backend,
        controller,
        FrozenSmolEncoder(backend),
        output,
        binding={
            "task_id": case["id"],
            "source_group": case["source_group_id"],
            "episode_group": case["episode_group_id"],
            "fit_id": fit_id,
            "native_request_id": None,
            "incumbent_checkpoint_digest": None,
        },
        seed=17,
        horizon=plan["horizon"],
        required_modalities=("text",),
        initial_actions=("text",) if controller.strategy == "initial" else (),
        cost_budget=profile["episode_cost"],
        wall_budget=profile["episode_wall_seconds"],
        cpu_tariff=profile["cpu_tariff"],
        wall_tariff=profile["wall_tariff"],
        collect_transition_features=collect,
    )


def collect(plan, args):
    roster = [
        {"key": f"case-{i:02d}-schedule-{j}", "case_id": c, "schedule_index": j}
        for i, c in enumerate(CASE_IDS)
        for j in range(len(SCHEDULES))
    ]
    with phase(plan, args.output, "collect", roster) as (report, start):
        cases, report["candidate_admission"] = load_pool(args.pool)
        backend = backend_for(plan, args)
        for row in report["entries"]:
            if not before_task(
                plan, start, row, plan["profile"]["episode_wall_seconds"]
            ):
                continue
            case = next(c for c in cases if c["id"] == row["case_id"])
            # Unfitted carrier is unused by fixed acquisition; it never forecasts a score.
            model = PredictiveModel(1, **plan["predictor"])
            controller = actor(
                plan, model, "tuned_fixed", SCHEDULES[row["schedule_index"]]
            )
            result = episode(
                plan,
                args.pool,
                case,
                backend,
                controller,
                Path(args.output) / row["key"],
                collect=case["project_split"] == "train",
            )
            row.update(
                status=result["status"],
                run_id=result["run_id"],
                total_cost=result["total_cost"],
                episode_sha256=_sha(Path(args.output) / row["key"] / "episode.json"),
            )
            _write(Path(args.output) / "PHASE.json", report)
        report["backend"] = backend.identity()
    return report


def score(plan, args):
    prior = inputs(
        args.input, args.input_sha256, plan, args.input_phase, require_complete=False
    )
    with phase(plan, args.output, "score_" + args.input_phase, prior["entries"]) as (
        report,
        start,
    ):
        report["input_sha256"] = args.input_sha256
        cases, report["candidate_admission"] = load_pool(args.pool)
        grades, rows = {}, []
        for row, source in zip(report["entries"], prior["entries"], strict=True):
            if not before_task(plan, start, row) or "episode_sha256" not in source:
                row["status"] = "missing_execution"
                continue
            case = next(c for c in cases if c["id"] == row["case_id"])
            trace, grade = score_episode(
                args.pool,
                case,
                Path(args.input).parent / row["key"],
                source["episode_sha256"],
            )
            grades[row["key"]] = grade
            row.update(
                status="completed",
                evaluation_digest=digest(grade),
                score=grade["terminal"]["score"],
                execution_status=trace["status"],
            )
            if (
                args.input_phase == "collect"
                and case["project_split"] == "train"
                and trace["status"] == SUCCESS
            ):
                rows.extend(training_rows(case, trace, grade))
            _write(Path(args.output) / "PHASE.json", report)
        _write(Path(args.output) / "SCORES.json", grades)
        report["scores_sha256"] = _sha(Path(args.output) / "SCORES.json")
        if args.input_phase == "collect":
            _write(Path(args.output) / "TRAINING_ROWS.json", rows)
            report["training_rows_sha256"] = _sha(
                Path(args.output) / "TRAINING_ROWS.json"
            )
            report["training_rows"] = len(rows)
            report["full_collection_complete"] = (
                prior["status"] == "completed"
                and len(prior["entries"]) == plan["counts"]["collection_episodes"]
                and all(row["status"] == SUCCESS for row in prior["entries"])
            )
            if report["full_collection_complete"] and len(grades) == len(
                prior["entries"]
            ):
                report["fixed_selection"] = tune_fixed(
                    plan, {"episodes": prior["entries"]}, grades
                )
    return report


def fit(plan, args):
    scored = inputs(args.input, args.input_sha256, plan, "score_collect")
    if not scored["full_collection_complete"] or "fixed_selection" not in scored:
        raise ValueError(
            "Failed/incomplete collection remains recorded; no reduced-data fit"
        )
    rows_path = Path(args.input).parent / "TRAINING_ROWS.json"
    if _sha(rows_path) != scored["training_rows_sha256"]:
        raise ValueError("Physical training data changed after offline evaluation")
    rows = json.loads(rows_path.read_text())
    roster = [
        {
            "key": f"seed-{seed}-{core}-{regime}",
            "seed": seed,
            "core": core,
            "regime": regime,
        }
        for seed in plan["fit_seeds"]
        for core in plan["cores"]
        for regime in plan["regimes"]
    ]
    with phase(plan, args.output, "fit", roster) as (report, start):
        cases, report["candidate_admission"] = load_pool(args.pool)
        report.update(
            input_sha256=args.input_sha256,
            training_rows_sha256=scored["training_rows_sha256"],
            fixed_selection=scored["fixed_selection"],
            predictor_device="cpu",
            predictor_dtype="float32",
        )
        sources = {c["source_group_id"] for c in cases if c["project_split"] == "train"}
        torch.set_num_threads(plan["profile"]["threads"])
        for row in report["entries"]:
            if not before_task(
                plan, start, row, plan["opportunity"]["fit_wall_seconds"]
            ):
                continue
            try:
                torch.manual_seed(row["seed"])
                model = PredictiveModel(
                    len(rows[0]["observation"]["encoding"]),
                    core=row["core"],
                    **plan["predictor"],
                )
                result = fit_predictive(
                    model,
                    rows,
                    Opportunity(**plan["opportunity"]),
                    allowed_sources=sources,
                    regime=row["regime"],
                    seed=row["seed"],
                    output=Path(args.output) / row["key"],
                )
                row.update(
                    status=result["status"],
                    attempt_id=result["attempt_id"],
                    checkpoint_sha256=_sha(Path(args.output) / row["key"] / "model.pt"),
                    fit_receipt_sha256=_sha(
                        Path(args.output) / row["key"] / "fit.json"
                    ),
                )
            except Exception as error:
                row.update(
                    status="failed",
                    error={"type": type(error).__name__, "message": str(error)},
                )
            _write(Path(args.output) / "PHASE.json", report)
    return report


def evaluate(plan, args):
    fits = inputs(args.input, args.input_sha256, plan, "fit")
    expected = {
        (s, c, r)
        for s in plan["fit_seeds"]
        for c in plan["cores"]
        for r in plan["regimes"]
    }
    if {
        (r["seed"], r["core"], r["regime"]) for r in fits["entries"]
    } != expected or len(fits["entries"]) != 12:
        raise ValueError("Complete registered physical-fit matrix required")
    roster = [
        {
            "key": f"{f['key']}-dev-{i}-{strategy}",
            "fit_key": f["key"],
            "case_id": case,
            "strategy": strategy,
        }
        for f in fits["entries"]
        for i, case in enumerate(CASE_IDS[:3])
        for strategy in STRATEGIES
    ]
    with phase(plan, args.output, "evaluate", roster) as (report, start):
        cases, report["candidate_admission"] = load_pool(args.pool)
        report["input_sha256"] = args.input_sha256
        backend = backend_for(plan, args)
        schedule = SCHEDULES[fits["fixed_selection"]["selected_index"]]
        for row in report["entries"]:
            if not before_task(
                plan, start, row, plan["profile"]["episode_wall_seconds"]
            ):
                continue
            record = next(r for r in fits["entries"] if r["key"] == row["fit_key"])
            model = load_predictor(
                Path(args.input).parent / row["fit_key"] / "model.pt",
                record["checkpoint_sha256"],
            )
            policies = [
                actor(plan, model, strategy, schedule) for strategy in STRATEGIES
            ]
            check_equal_opportunity(policies)
            controller = next(p for p in policies if p.strategy == row["strategy"])
            case = next(c for c in cases if c["id"] == row["case_id"])
            result = episode(
                plan,
                args.pool,
                case,
                backend,
                controller,
                Path(args.output) / row["key"],
            )
            row.update(
                status=result["status"],
                run_id=result["run_id"],
                total_cost=result["total_cost"],
                episode_sha256=_sha(Path(args.output) / row["key"] / "episode.json"),
            )
            _write(Path(args.output) / "PHASE.json", report)
        report["backend"] = backend.identity()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("plan", "collect", "score", "fit", "evaluate")
    )
    for name in ("output", "pool"):
        parser.add_argument("--" + name, required=True)
    for name in (
        "profile",
        "source-sha",
        "plan",
        "plan-sha256",
        "models",
        "input",
        "input-sha256",
        "device-smoke",
        "device-smoke-sha256",
    ):
        parser.add_argument("--" + name)
    parser.add_argument(
        "--input-phase", choices=("collect", "evaluate"), default="collect"
    )
    args = parser.parse_args()
    if args.stage == "plan":
        load_pool(args.pool)
        result = make_plan(args.source_sha, json.loads(Path(args.profile).read_text()))
        with Path(args.output).open("x") as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(
            json.dumps(
                {
                    "plan_sha256": _sha(args.output),
                    "counts": result["counts"],
                    "claim_status": "HOLD",
                }
            )
        )
        return 0
    plan = read_plan(args.plan, args.plan_sha256)
    result = {"collect": collect, "score": score, "fit": fit, "evaluate": evaluate}[
        args.stage
    ](plan, args)
    print(
        json.dumps(
            {
                "status": result["status"],
                "phase_sha256": _sha(Path(args.output) / "PHASE.json"),
                "claim_status": "HOLD",
            }
        )
    )
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
