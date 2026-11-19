"""Read-only admission quotes from frozen geometry and actual historical receipts."""

import json
from pathlib import Path

from independent.accounting import WorkLedger
from independent.mixed_training import mixed_step_work
from ndu_training.estimators import weighted_work
from ndu_training.mechanism_readout.anchor_cv import correction_work
from ndu_training.reinfer_d1.kernels import pullback_work

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIMS = (202, 12, 192, 32)
ELEMENTS = 7288


def plan():
    return json.loads((HERE / "plan.json").read_text())


def histories():
    p = plan()
    original = json.loads((ROOT / p["original_run"] / "result.json").read_text())
    diagnostic = ROOT / p["TRAIN_and_reference_run"]
    ref = json.loads((diagnostic / "result.json").read_text())
    final = json.loads(
        (ROOT / "ndu_training/reinfer_d1/evidence/run-d1.txt").read_text()
    )
    common_cpu = final["physical_cpu_after_final_write"] - sum(
        sum(stages.values()) for stages in ref["stage_cpu"].values()
    )
    return {
        "base_cpu": original["shared_cpu_seconds"],
        "base_units": original["shared_ledger"]["consumed_units"],
        "reference_cpu": common_cpu,
        "reference_units": ref["common_units"]["consumed_units"],
        "note": "full original shared receipt, and full reconstruction shared receipt for CV; no free historical cache",
    }


def norm_work(elements=ELEMENTS):
    return dict(scalar_ops=2 * elements - 1, sqrt_ops=1)


def cv_work(n=64, hidden=32, elements=ELEMENTS, weighted=True):
    parts = (pullback_work(n, hidden, weighted), correction_work(elements))
    result = {
        key: sum(part.get(key, 0) for part in parts) for key in set().union(*parts)
    }
    result["scalar_ops"] += n
    return result


def update_quote(group, kind, low_rows=None, record_norms=True):
    arm, estimator = group.split("-")
    work = mixed_step_work(DIMS, arm, 64, low_rows)
    extra = []
    if kind == "stratified":
        extra.append(weighted_work(64))
    if estimator == "CV":
        extra.append(cv_work(weighted=kind == "stratified"))
    if record_norms:
        extra.extend([norm_work()] * (2 if estimator == "CV" else 1))
    for part in extra:
        for key, value in part.items():
            work[key] = work.get(key, 0) + value
    return WorkLedger("quote").estimate_kernel(**work)


def quote():
    p, h = plan(), histories()
    rows = {}
    for group in p["groups"]:
        estimator = group.split("-")[1]
        cv = estimator == "CV"
        history_units = h["base_units"] + (h["reference_units"] if cv else 0)
        history_cpu = h["base_cpu"] + (h["reference_cpu"] if cv else 0)
        worst_round = sum(
            update_quote(group, kind)
            for _ in p["model_seeds"]
            for kind in p["samplers"]
        )
        typical_round = sum(
            update_quote(group, kind, 32)
            for _ in p["model_seeds"]
            for kind in p["samplers"]
        )
        minimum_training_cpu = (
            6
            * p["minimum_matched_steps"]
            * p["update_cpu_forecast_CV" if cv else "update_cpu_forecast_plain"]
        )
        minimum_cpu = (
            history_cpu
            + p["initial_common_cpu_forecast"]
            + p["setup_cpu_forecast_each_group"]
            + minimum_training_cpu
            + p["tail_cpu_reserve_each_group"]
        )
        minimum_units = (
            history_units
            + p["tail_units_reserve_each_group"]
            + p["minimum_matched_steps"] * worst_round
        )
        rows[group] = {
            "historical_cpu_fully_attributed": history_cpu,
            "historical_units_fully_attributed": history_units,
            "complete_128_round_units_envelope": minimum_units,
            "complete_128_round_cpu_forecast": minimum_cpu,
            "one_round_units_envelope": worst_round,
            "one_round_units_with_32_low_rows_each_batch": typical_round,
            "possible_rounds_by_operator_envelope": (
                p["operator_units_each_group"]
                - history_units
                - p["tail_units_reserve_each_group"]
            )
            // worst_round,
            "forecast_fits_both_caps": minimum_units < p["operator_units_each_group"]
            and minimum_cpu < p["complete_cpu_seconds_each_group"],
        }
    return {
        "history": h,
        "groups": rows,
        "service_requests_each_group": 6 * 48 * 64,
        "service_requests_total": 4 * 6 * 48 * 64,
        "service_units_each_group": 6 * 48 * 64 * 19236,
        "forecast_only": True,
        "initial_runtime_admission_required": True,
        "no_model_or_TRAIN_predictions": True,
        "ready_for_review": all(v["forecast_fits_both_caps"] for v in rows.values()),
    }
