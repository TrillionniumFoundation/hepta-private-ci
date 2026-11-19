"""Independent arithmetic checks for every causal online policy trace."""

import numpy as np
from scipy.special import expit

from online_audit_common import check, close, reference_waits


MODES = ("fixed", "direct", "value", "full")


def verify_decision(tick, mode, snr, cost, remaining, horizon, policy, tables):
    decision, raw = tick["decision"], tick["raw_log_odds"]
    logits = np.asarray(tick["logits"], dtype=np.float32)
    check(logits.shape == (2,) and np.isfinite(logits).all(), "binary finite logits")
    check(float(logits[1] - logits[0]) == raw, "raw actor odds arithmetic")
    odds, forced = raw / policy["temperature"], remaining == 0
    confidence = float(expit(abs(odds)))
    close(
        decision["calibrated_log_odds"],
        odds,
        "temperature-adjusted odds",
        atol=1e-12,
        rtol=0,
    )
    close(decision["confidence"], confidence, "confidence", atol=1e-12, rtol=0)
    close(
        decision["predicted_error_probability"],
        1 - confidence,
        "estimated task error",
        atol=1e-12,
        rtol=0,
    )
    check(decision["forced_terminal"] == forced, "finite deadline flag")
    score, value_error = decision["continue_score"], None
    check(np.isfinite(score), "finite action score")
    check(
        decision["stop"] == (forced or score <= 0), "policy action from declared score"
    )
    if mode == "value":
        check(
            decision["score_kind"] == "value_model_advantage",
            "genuine value score kind",
        )
        close(
            decision["stopping_value"],
            confidence,
            "genuine immediate task reward",
            atol=1e-12,
            rtol=0,
        )
        if forced:
            check(
                decision["continuation_value"] is None and score == -1,
                "terminal constraint is not a fake continuation value",
            )
        else:
            key = (snr, cost, horizon)
            if key not in tables:
                tables[key] = reference_waits(*key)
            grid, waits = tables[key]
            reference = float(np.interp(odds, grid, waits[remaining]))
            value_error = abs(decision["continuation_value"] - reference)
            close(
                decision["continuation_value"],
                reference,
                "independent finite-grid continuation value",
                atol=1e-9,
                rtol=0,
            )
            close(
                score,
                reference - confidence,
                "task continuation advantage",
                atol=1e-9,
                rtol=0,
            )
    else:
        check(
            decision["stopping_value"] is None
            and decision["continuation_value"] is None,
            "threshold/horizon score must not be called a task value",
        )
        if mode == "full":
            check(
                decision["score_kind"] == "fixed_horizon_constraint",
                "full-horizon score kind",
            )
            check(score == (-1 if forced else 1), "full-horizon action")
        else:
            check(
                decision["score_kind"] == "threshold_confidence_advantage",
                "threshold score kind",
            )
            if forced:
                check(score == -1, "threshold terminal constraint")
            else:
                threshold = policy["fixed"]["threshold"]
                if mode == "direct":
                    parameters = policy["direct"]["parameters"]
                    feature = np.array([np.log1p(remaining), np.log(snr), np.log(cost)])
                    threshold = 0.5 + 0.4999 * expit(
                        parameters["direct_bias"]
                        + feature @ parameters["direct_context"]
                    )
                close(
                    score,
                    threshold - confidence,
                    "fixed/direct confidence threshold",
                    atol=5e-7,
                    rtol=0,
                )
    return value_error


def audit_record(
    record, mode, episode_id, snr, cost, horizon, policy, tables, native=False
):
    check(
        record["mode"] == mode and record["episode_id"] == episode_id,
        "episode/policy identity",
    )
    count, trace = record["observations"], record["trace"]
    check(
        type(count) is int and 1 <= count <= horizon and len(trace) == count,
        "actual paid read count",
    )
    check(
        [tick["step"] for tick in trace] == list(range(1, count + 1)),
        "contiguous causal task cursor",
    )
    check(
        record["processed_rows"] == count
        and record["avoided_model_steps"] == horizon - count,
        "actual incremental work accounting",
    )
    check(
        [tick["actual_stop"] for tick in trace] == [False] * (count - 1) + [True],
        "no observation after consumed STOP",
    )
    check(record["post_stop_read_rejected"], "post-STOP source guard")
    close(
        record["cost"],
        cost * count,
        "all observations including first are charged",
        atol=1e-12,
        rtol=0,
    )
    check(
        record["predicted_class"] == int(trace[-1]["raw_log_odds"] >= 0),
        "final classification",
    )
    check(record["final_decision"] == trace[-1]["decision"], "final decision receipt")
    errors = []
    for tick in trace:
        error = verify_decision(
            tick, mode, snr, cost, horizon - tick["step"], horizon, policy, tables
        )
        if error is not None:
            errors.append(error)
        check(np.isfinite(tick["natural_margin_mean"]), "finite natural margin")
        check(
            0 <= tick["event_activity_mean"] <= 1, "interval event probability domain"
        )
        check(
            type(tick["state_bytes"]) is int and tick["state_bytes"] > 0,
            "stream state receipt",
        )
        if not native:
            check(
                tick["native"] is None
                and tick["actual_stop"] == tick["decision"]["stop"],
                "Python consumes its causal policy action",
            )
    for name in (
        "reset_cpu_seconds",
        "loop_cpu_seconds",
        "loop_wall_seconds",
        "total_cpu_seconds",
        "total_wall_seconds",
        "snapshot_cpu_seconds",
        "snapshot_wall_seconds",
    ):
        check(
            np.isfinite(record[name]) and record[name] >= 0,
            "finite nonnegative task cost",
        )
    check(
        record["total_cpu_seconds"] + 1e-8
        >= record["reset_cpu_seconds"] + record["loop_cpu_seconds"],
        "nested task CPU scopes",
    )
    if not native:
        check(
            record["snapshot_cpu_seconds"] == 0 and record["native_recovery"] is None,
            "primary task timings exclude verification replay",
        )
    return errors


def recompute_metrics(rows, labels):
    correct = np.array(
        [
            row["predicted_class"] == int(label)
            for row, label in zip(rows, labels, strict=True)
        ]
    )
    costs = np.array([row["cost"] for row in rows])
    return {
        "episodes": len(rows),
        "accuracy": float(correct.mean()),
        "mean_observations": float(np.mean([r["observations"] for r in rows])),
        "mean_cost": float(costs.mean()),
        "net_utility": float((correct - costs).mean()),
        "total_processed_rows": sum(r["processed_rows"] for r in rows),
        "total_avoided_model_steps": sum(r["avoided_model_steps"] for r in rows),
        "loop_cpu_seconds": sum(r["loop_cpu_seconds"] for r in rows),
        "loop_wall_seconds": sum(r["loop_wall_seconds"] for r in rows),
        "all_post_stop_reads_rejected": all(r["post_stop_read_rejected"] for r in rows),
    }
