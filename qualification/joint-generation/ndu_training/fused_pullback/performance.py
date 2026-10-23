"""Fixed read-only hand microbenchmark and conditional complete-budget projections."""

import hashlib
import json
import time

import numpy as np

from independent.accounting import WorkLedger
from ndu_training.cv_train_d2.budget import ROOT, histories
from ndu_training.estimators import WeightedObjective
from ndu_training.fused_pullback.hand import draw
from ndu_training.fused_pullback.kernel import form_gradients, gradient_work
from ndu_training.reinfer_d1.kernels import flat
from ndu_training.reinfer_d1.service import WILLIAMS


def multiply(work, count):
    return {key: value * count for key, value in work.items()}


def benchmark(model, bound, arrays, p, ledger, blocks):
    modes = p["performance_modes"]
    for arm in ("A", "N"):
        objective = WeightedObjective(
            arm, model, ledger=ledger, stage="performance_objective"
        )
        for kind in ("iid", "stratified"):
            values = draw(arrays, p, kind, p["performance_low_count"])
            for step in p["performance_steps"]:
                case = f"{arm}-{kind}-step{step}"
                warm = {}
                for mode in modes:
                    _, grads, info = form_gradients(
                        model, objective, *values, bound, mode, ledger, step=step
                    )
                    assert all(np.isfinite(value).all() for value in grads.values())
                    warm[mode] = {
                        "vector_sha256": hashlib.sha256(
                            flat(grads).tobytes()
                        ).hexdigest(),
                        "path": info,
                    }
                for wave in range(p["performance_waves"]):
                    ci = (
                        (0 if arm == "A" else 1)
                        + (0 if kind == "iid" else 2)
                        + (0 if step == 64 else 1)
                    )
                    for position in WILLIAMS[(wave + ci) % 4]:
                        mode = modes[position]
                        n = p["performance_repetitions_each_block"]
                        options = (
                            None,
                            "observed",
                            "empty_moments",
                            "hidden_cancellation",
                            "mean_cancellation",
                        )
                        worst = max(
                            ledger.estimate_kernel(
                                **gradient_work(
                                    model.dimensions,
                                    arm,
                                    64,
                                    32,
                                    kind == "stratified",
                                    mode,
                                    observed=step == 64,
                                    fallback=fallback,
                                )
                            )
                            for fallback in options
                        )
                        if ledger.remaining_units < n * worst:
                            raise RuntimeError(
                                "complete benchmark block operator admission"
                            )
                        began, wall, completed = (
                            time.process_time_ns(),
                            time.perf_counter_ns(),
                            0,
                        )
                        last_info = None
                        try:
                            for _ in range(n):
                                _, grads, last_info = form_gradients(
                                    model, objective, *values, bound, mode, step=step
                                )
                                completed += 1
                        finally:
                            used, elapsed = (
                                time.process_time_ns() - began,
                                time.perf_counter_ns() - wall,
                            )
                            if completed:
                                actual = gradient_work(
                                    model.dimensions,
                                    arm,
                                    64,
                                    32,
                                    kind == "stratified",
                                    mode,
                                    observed=step == 64,
                                    fallback=last_info["fallback"],
                                )
                                ledger.charge_kernel(
                                    "benchmark", mode, **multiply(actual, completed)
                                )
                                blocks.append(
                                    {
                                        "case": case,
                                        "arm": arm,
                                        "sampler": kind,
                                        "step": step,
                                        "wave": wave,
                                        "mode": mode,
                                        "calls": completed,
                                        "cpu_ns": used,
                                        "wall_ns": elapsed,
                                        "path": last_info,
                                        "work_each_call": ledger.estimate_kernel(
                                            **actual
                                        ),
                                    }
                                )
                        digest = hashlib.sha256(flat(grads).tobytes()).hexdigest()
                        if digest != warm[mode]["vector_sha256"]:
                            raise RuntimeError(
                                "read-only repetitions changed gradient bytes"
                            )
    return blocks


def projections(blocks, bind_cpu, bind_units, p, ledger):
    old = json.loads(
        (ROOT / "runs/codex-cloud-ndu-CV-TRAIN-d2/result.json").read_text()
    )
    h = histories()
    result = {
        "per_arm_step": {},
        "groups": {},
        "all_old_failures_preserved": True,
        "warning": "hand timing projections conditional on transfer to real training; no learning outcome or seed-generalization claim",
    }
    for arm in ("A", "N"):
        means = {}
        wave_savings = {}
        for step in p["performance_steps"]:
            means[str(step)] = {
                mode: float(
                    np.mean(
                        [
                            row["cpu_ns"] / row["calls"]
                            for row in blocks
                            if row["arm"] == arm
                            and row["step"] == step
                            and row["mode"] == mode
                        ]
                    )
                )
                for mode in p["performance_modes"]
            }
            wave_savings[str(step)] = []
            for wave in range(4):
                row = {
                    mode: float(
                        np.mean(
                            [
                                b["cpu_ns"] / b["calls"]
                                for b in blocks
                                if b["arm"] == arm
                                and b["step"] == step
                                and b["wave"] == wave
                                and b["mode"] == mode
                            ]
                        )
                    )
                    for mode in ("CV-d2", "CV-hybrid")
                }
                wave_savings[str(step)].append((row["CV-d2"] - row["CV-hybrid"]) / 1e9)
        result["per_arm_step"][arm] = {
            "mean_cpu_ns": means,
            "all_four_wave_savings_seconds": wave_savings,
        }
        g = arm + "-CV"
        rows = old["groups"][g]["candidates"]
        old_steps = next(iter(rows.values()))["steps"]
        old_adapt = old["actual_phase_cpu"][g]["adaptation"]
        old_full = old_adapt / (6 * old_steps)
        group = {
            "old_CV_steps_each_candidate": old_steps,
            "old_plain_steps_each_candidate": next(
                iter(old["groups"][arm + "-plain"]["candidates"].values())
            )["steps"],
            "old_observed_full_update_cpu": old_full,
            "old_adaptation_envelope_seconds": old_adapt,
            "base_history_CPU_unchanged": h["base_cpu"],
            "reference_history_CPU_unchanged": h["reference_cpu"],
            "base_history_units_unchanged": h["base_units"],
            "reference_history_units_unchanged": h["reference_units"],
            "old_current_reference_load_CPU_unchanged": old["actual_phase_cpu"][g][
                "reference_cache_load"
            ],
            "additional_three_reference_bind_CPU": 3 * bind_cpu,
            "additional_three_reference_bind_units": 3 * bind_units,
            "projection": {},
        }
        for scenario in ("mean", "least_favorable_wave"):
            saved_regular = (
                (means["65"]["CV-d2"] - means["65"]["CV-hybrid"]) / 1e9
                if scenario == "mean"
                else min(wave_savings["65"])
            )
            saved_observed = (
                (means["64"]["CV-d2"] - means["64"]["CV-hybrid"]) / 1e9
                if scenario == "mean"
                else min(wave_savings["64"])
            )
            regular, observed = old_full - saved_regular, old_full - saved_observed
            if min(regular, observed) <= 0:
                group["projection"][scenario] = {
                    "valid": False,
                    "reason": "microbenchmark transfer yields impossible update CPU",
                }
                continue
            feasible = 0
            for steps in range(1, 1025):
                nobs = 1 + steps // 64
                predicted_cpu = 3 * bind_cpu + 6 * (
                    (steps - nobs) * regular + nobs * observed
                )
                # Keep the old actually used adaptation envelope, not unused headroom.
                if predicted_cpu > old_adapt:
                    break
                feasible = steps
            group["projection"][scenario] = {
                "valid": True,
                "regular_update_cpu": regular,
                "observed_update_cpu": observed,
                "predicted_steps_with_same_adaptation_envelope": feasible,
                "observed_steps_count": 1 + feasible // 64,
                "predicted_extra_steps": feasible - old_steps,
            }
        # Operators retain all reference and tail charges; observations use old path.
        cap = (
            12_000_000_000
            - h["base_units"]
            - h["reference_units"]
            - 430_000_000
            - 3 * bind_units
        )
        e, arrays_count = 7288, 6
        adam = {
            "scalar_ops": 13 * e + 4 * arrays_count,
            "div_ops": 3 * e + 1,
            "sqrt_ops": e + 1,
            "pow_ops": 2 * arrays_count,
            "compare_ops": e + 2,
        }
        q = WorkLedger("future-quote")
        costs = {
            step: sum(
                q.estimate_kernel(
                    **gradient_work(
                        (202, 12, 192, 32),
                        arm,
                        64,
                        32,
                        weighted,
                        "CV-hybrid",
                        observed=step == 64,
                        fallback="observed" if step == 64 else None,
                    )
                )
                + q.estimate_kernel(**adam)
                for _ in range(3)
                for weighted in (False, True)
            )
            for step in (64, 65)
        }
        feasible = 0
        for steps in range(1, 1025):
            nobs = 1 + steps // 64
            if nobs * costs[64] + (steps - nobs) * costs[65] > cap:
                break
            feasible = steps
        group["operator_prediction_no_extra_cancellation_fallbacks"] = feasible
        group["regular_hybrid_still_vs_optimized_plain_cpu_ratio"] = (
            means["65"]["CV-hybrid"] / means["65"]["plain"]
        )
        group["unmeasured_limits"] = (
            "real-state guard frequency, live optimizer transfer, host drift; d2 common CV-file hash leak is not retroactively subtracted"
        )
        result["groups"][arm] = group
    ledger.charge_kernel(
        "projection",
        "scalar_summaries",
        scalar_ops=20000,
        div_ops=2000,
        compare_ops=10000,
    )
    return result
