"""Train-only raw-gain critic and paired complete-service CPU calibration.

Every probe produces its real PNG/JSON. Only the routing threshold is calibrated;
the qualification price/reference and the complete measured costs remain intact.
The caller owns the encompassing build CPU timer, including this helper's work.
"""

import hashlib
import json
import math
import statistics
import time

import numpy as np

from control import Controller, fit_controller
from independent.accounting import BudgetExceeded, WorkLedger
from independent.calibration import calibration_manifest
from independent.evaluation import measure, output_work
from independent.inference import FrozenGenerator, _sum_work
from independent.learning import CachedObjective, setup_work, value_work


SCHEMA = "hepta.joint-generation.controller-cost-calibration.v1"
GAIN_OBJECTIVE = "raw-decoded-task-utility"
AFFINE_KIND = "low-hidden-instruction-affine-v1"


def _affine(plan):
    kind = None if plan is None else plan.get("controller", {}).get("gain_head")
    if kind not in (None, "probability-ridge-v1", AFFINE_KIND):
        raise ValueError("unsupported controller gain-head profile")
    return kind == AFFINE_KIND


def _hash(values):
    return hashlib.sha256(json.dumps(list(values), separators=(",", ":")).encode()).hexdigest()


def _ridge_extra(n, k=12):
    return {"sqrt_ops": 2 * k + 7, "log_ops": 2,
            "compare_ops": 2 * n + 2 * k + 5, "scalar_ops": 2 * k + 8}


def controller_work(model, trainrows, calrows, repeats, *, raw_reward_cached=True, plan=None):
    """Flat declared inventory, including fit, every service probe and preparation."""
    if (any(type(n) is not int or not 1 <= n <= 65536 for n in (trainrows, calrows))
            or repeats != 3 or type(repeats) is not int or type(raw_reward_cached) is not bool):
        raise ValueError("bounded row counts and exactly three paired repeats required")
    gen = FrozenGenerator(model, prepare_low=False)
    n, k, pixels = trainrows, model.dimensions[1], model.dimensions[2]
    if _affine(plan):
        from independent.gain_head import fit_work, head_work
        fitting = fit_work(model.dimensions[3], n, plan)
        prediction = head_work(model.dimensions[3], calrows)
    else:
        fit = WorkLedger("critic-inventory")
        fit.critic_fit("critic_fit", rows=n, classes=k)
        fitting = _sum_work({key[3:]: value for key, value in fit.totals.items() if key.startswith("op_")},
                            _ridge_extra(n, k))
        prediction = gen.critic_work(calrows)
    row = _sum_work(gen.low_work(calrows), prediction,
        {key: calrows * value for key, value in output_work(k, pixels).items()},
        {"scalar_ops": 3 * calrows * pixels, "compare_ops": 2 * calrows * pixels,
         "exp_ops": calrows * pixels, "div_ops": calrows * pixels})
    pair = _sum_work(row, row, gen.full_work(calrows), gen.prepare_work(), gen.prepare_work())
    return _sum_work(gen.prepare_work(), gen.low_work(n), gen.full_work(n),
        value_work("additive", n, k), value_work("additive", n, k), fitting,
        {"scalar_ops": 2 * n - 1, "compare_ops": 2 * (n - 1), "div_ops": 1},
        {} if raw_reward_cached else setup_work(model.dimensions, "additive"),
        {key: repeats * value for key, value in pair.items()},
        {"scalar_ops": repeats + 1, "div_ops": repeats + 1, "compare_ops": 1, "sort_items": repeats})


def _branch(report, n, continuing, ledger):
    cost = report["cost"]
    if report["budget_violations"] or report["model_forwards"] != n * (1 + continuing):
        raise ValueError("forced calibration route or service budget changed")
    work = sum(report["per_row_cost"]["work_units"])
    prepare = cost["prepare"]["consumed_units"]
    counts = _sum_work(cost["operator_totals"], cost["prepare"]["totals"])
    if counts.pop("consumed_units") != work + prepare:
        raise ValueError("probe work/prepare receipt does not conserve cost")
    ledger.record("controller_calibration", units=work + prepare, **counts)
    cpu = sum(batch["cpu_ns"] for batch in cost["batches"])
    if type(cpu) is not int or cpu < 0 or len(report["per_row_cost"]["work_units"]) != n:
        raise ValueError("invalid complete-service CPU/row receipt")
    compact = {key: cost[key] for key in ("batches", "operator_totals", "runtime_batch_size",
               "cpu_ns", "wall_ns", "prepare_cpu_ns", "prepare_wall_ns", "request_cap_units")}
    return {"rows": n, "cpu_ns": cpu, "prepare_cpu_ns": cost["prepare_cpu_ns"],
            "work_units": work, "prepare_units": prepare,
            "model_forwards": report["model_forwards"], "cost": compact}


def fit_and_calibrate(model, train_data, calibration_data, plan, runtime_plan, ledger,
                      reference_full_cpu_ns, seed, raw_reward=None):
    """Return (raw-gain Controller, routing threshold, bounded provenance receipt).

    A supplied reward is a trusted internal cache bound to this fixed decoder;
    it is validated without recomputing its already-paid observation kernel.
    """
    started = time.process_time()
    if not isinstance(ledger, WorkLedger):
        raise TypeError("WorkLedger required")
    if train_data.get("split") != "train" or calibration_data.get("split") != "train":
        raise ValueError("controller fitting and calibration require training-only data")
    reference, price = float(reference_full_cpu_ns), float(plan["compute_price"])
    if not math.isfinite(reference) or reference <= 0 or not math.isfinite(price) or price < 0:
        raise ValueError("positive reference and nonnegative unchanged compute price required")
    if type(seed) is not int or seed not in plan["model_seeds"] or not 0 <= seed < 2**63 - 2018:
        raise ValueError("declared model seed required")
    n, repeats = plan["calibration_rows"], plan["calibration_repeats"]
    x, y = np.asarray(train_data["full"]), np.asarray(train_data["labels"])
    cal = np.asarray(calibration_data["full"])
    if (x.ndim != 2 or x.shape[1] != 202 or y.shape != (len(x),) or y.dtype.kind not in "iu"
            or np.any(y < 0) or np.any(y >= 12) or not np.isfinite(x).all()
            or cal.shape != (n, 202) or not np.isfinite(cal).all()):
        raise ValueError("matching finite train/calibration tensors required")
    identity = calibration_manifest(calibration_data, np.arange(n))
    actual_hashes = [hashlib.sha256(row.astype("<f8").tobytes()).hexdigest() for row in cal]
    if (actual_hashes != identity["selected_input_hashes"]
            or not set(actual_hashes).issubset(set(train_data["input_hashes"]))):
        raise ValueError("calibration identities must bind actual training input bytes")
    before, units_before = model.digest(), ledger.consumed_units
    inventory = controller_work(model, len(x), n, repeats, raw_reward_cached=raw_reward is not None, plan=plan)
    if ledger.estimate_kernel(**inventory) > ledger.remaining_units:
        raise BudgetExceeded("raw critic plus complete paired calibration exceeds remaining work")
    if raw_reward is None:
        raw_reward = CachedObjective("additive", model, ledger=ledger, stage="critic_targets").reward
    reward = np.asarray(raw_reward, dtype=np.float64)
    if reward.shape != (12, 12, 12) or not np.isfinite(reward).all():
        raise ValueError("finite fixed decoder-bound raw reward table required")
    gen = FrozenGenerator(model, ledger, "critic_targets")
    affine = _affine(plan)
    if affine:
        pl, ql, hidden = gen.forward_low_state(x, ledger, "critic_targets")
    else:
        pl, ql = gen.forward_low(x, ledger, "critic_targets")
    pf, qf = gen.forward_full(x, ledger, "critic_targets")
    values = []
    for p, q in ((pl, ql), (pf, qf)):
        ledger.charge_kernel("critic_targets", "raw_utility_value", **value_work("additive", len(x)))
        values.append(np.sum(p * np.einsum("nij,nj->ni", reward[y], q), axis=1))
    ledger.charge_kernel("critic_targets", "raw_gain_and_summary", scalar_ops=2 * len(x) - 1,
                         compare_ops=2 * (len(x) - 1), div_ops=1)
    target = values[1] - values[0]
    fit_receipt = None
    if affine:
        from independent.gain_head import AffineGainHead
        critic, fit_receipt = AffineGainHead.fit(hidden, x[:, 192:], target, plan, seed, ledger,
                                               stage="critic_fit")
        forced = {name: critic.with_bounds(np.array([bound, bound]))
                  for name, bound in (("stop", 0.0), ("continue", 1.0))}
    else:
        ledger.critic_fit("critic_fit", rows=len(x), classes=12)
        ledger.charge_kernel("critic_fit", "ridge_extra", **_ridge_extra(len(x)))
        critic = fit_controller(pl, ql, target, regularization=plan["controller"]["ridge_regularization"])
        forced = {name: Controller(critic.classes, critic.mean, critic.scale, critic.weights,
                  critic.intercept, np.array([bound, bound])) for name, bound in (("stop", 0.0), ("continue", 1.0))}
    pairs, deltas = [], []
    for repeat in range(repeats):
        order = ["stop", "continue"] if (repeat + plan["model_seeds"].index(seed)) % 2 == 0 else ["continue", "stop"]
        sample_seed = seed + 1009 * repeat
        pair = {"repeat": repeat, "order": order, "sample_seed": sample_seed}
        for branch in order:
            measured = measure(model, forced[branch], "continuation", calibration_data,
                {**runtime_plan, "compute_price": price, "decision_price": 0.5}, reference,
                seed=sample_seed, observe=False)
            pair[branch] = _branch(measured, n, int(branch == "continue"), ledger)
        delta = (pair["continue"]["cpu_ns"] - pair["stop"]["cpu_ns"]) / n
        pair["delta_cpu_ns_per_request"] = delta
        deltas.append(delta)
        pairs.append(pair)
    ledger.charge_kernel("controller_calibration", "decision_cost_formula", scalar_ops=repeats + 1,
                         div_ops=repeats + 1, compare_ops=1, sort_items=repeats)
    median = float(statistics.median(deltas))
    incremental, ratio = max(0.0, median), max(0.0, median) / reference
    decision = price * ratio
    if model.digest() != before:
        raise ValueError("controller calibration changed content parameters")
    receipt = {"schema": SCHEMA, "gain_objective": GAIN_OBJECTIVE, "model_digest": before,
        "critic_kind": getattr(critic, "kind", "probability-ridge-v1"), "gain_head_fit": fit_receipt,
        "seed": seed, "calibration_inputs_sha256": identity["inputs_sha256"],
        "calibration_identity": identity, "paired_cpu_deltas_ns_per_request": deltas,
        "median_incremental_cpu_ns_per_request": median,
        "nonnegative_incremental_cpu_ns_per_request": incremental,
        "reference_full_cpu_ns": reference, "cost_ratio": ratio, "compute_price": price,
        "decision_price": decision, "pairs": pairs, "forced_decision_price": 0.5,
        "raw_target": {"objective": GAIN_OBJECTIVE, "formula": "E[p_full R_y q_full] - E[p_low R_y q_low]",
            "rows": len(x), "train_inputs_sha256": _hash(train_data["input_hashes"]),
            "reward_sha256": hashlib.sha256(reward.astype("<f8").tobytes()).hexdigest(),
            "values_sha256": hashlib.sha256(target.astype("<f8").tobytes()).hexdigest(),
            "min": float(target.min()), "mean": float(target.mean()), "max": float(target.max())},
        "accounting_units": ledger.consumed_units - units_before, "model_unchanged": True,
        "helper_cpu_seconds": time.process_time() - started,
        "cost_boundary": "Complete service pair CPU includes one actual output per branch; all probe preparation/build CPU remains charged to NC, not subtracted."}
    return critic, decision, receipt
