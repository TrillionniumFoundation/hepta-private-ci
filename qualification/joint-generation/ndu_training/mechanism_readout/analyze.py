"""Derive identifiable outcome masses from saved aggregates, not new requests."""

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from data import outcome_from_observations, templates  # noqa: E402

HERE = Path(__file__).resolve().parent
RUN = ROOT / "runs/codex-cloud-ndu-training-train-d1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decoder_support(seed):
    # Only the saved twelve-code decoder and fixed scoring templates are used.
    # No input rows, encoder/head forward, sampling or dataset construction.
    with np.load(RUN / f"base-{seed}.npz", allow_pickle=False) as saved:
        pixels = 1 / (1 + np.exp(-np.clip(saved["decoder"] + saved["decoder_bias"], -700, 700)))
    distances = ((pixels[:, None, :] - templates()[None, :, :]) ** 2).mean(2)
    ids = distances.argmin(1)
    np.testing.assert_array_equal(ids, np.arange(12))
    assert distances.max() < .25  # Proves the quality clipping is inactive.
    reward = outcome_from_observations((np.arange(12), ids, pixels, distances))
    target = np.arange(12)[:, None, None]
    correct_t = np.arange(12)[None, :, None] == target
    correct_i = ids[None, None, :] == target
    agreement = (np.arange(12)[:, None] == ids[None, :])[None, :, :]
    negative = np.broadcast_to(~correct_t & ~correct_i & ~agreement, reward.shape)
    assert np.array_equal(negative, reward < 0)
    wrong = ~np.eye(12, dtype=bool)
    return {"maximum_distance": float(distances.max()), "quality_clipping_inactive": True,
            "decoded_ids": ids.tolist(), "negative_is_both_wrong_disagree": True,
            "negative_reward_range": [float(reward[negative].min()), float(reward[negative].max())],
            "correct_distance_range": [float(np.diag(distances).min()), float(np.diag(distances).max())],
            "wrong_distance_range": [float(distances[wrong].min()), float(distances[wrong].max())]}


def identify(metrics, support):
    u, j, c, mse = (metrics[key] for key in ("task_utility", "joint_success", "consistency", "pixel_mse"))
    # S is the mean SUM of the two true-head probabilities, not either head alone.
    s = (u - .3*j - .1*(1-4*mse) + .35*(1-c))/.3
    result = {"true_head_probability_sum": s, "both_correct": j,
              "exactly_one_correct": s-2*j, "both_wrong": 1-s+j,
              "both_wrong_agree": c-j, "both_wrong_disagree_negative": 1-s+2*j-c}
    assert all(value >= -1e-12 for value in result.values())
    assert abs(j + result["exactly_one_correct"] + result["both_wrong"] - 1) < 1e-12
    correct_min, correct_max = support["correct_distance_range"]
    wrong_min, wrong_max = support["wrong_distance_range"]
    image_lower = max(0., (wrong_min-mse)/(wrong_min-correct_min))
    image_upper = min(1., (wrong_max-mse)/(wrong_max-correct_max))
    result["image_correct_probability_bounds"] = [image_lower, image_upper]
    result["text_correct_probability_bounds"] = [max(0., s-image_upper), min(1., s-image_lower)]
    errors = 3072*(1-metrics["greedy_joint_success"])
    assert abs(errors-round(errors)) < 1e-8
    result["greedy_error_count"] = round(errors)
    return result


def compare(a_metrics, n_metrics, support):
    a, n = (identify(x, support) for x in (a_metrics, n_metrics))
    keys = ("true_head_probability_sum", "both_correct", "exactly_one_correct",
            "both_wrong", "both_wrong_agree", "both_wrong_disagree_negative")
    delta = {key: n[key]-a[key] for key in keys}
    components = {"true_head_marginals": .3*delta["true_head_probability_sum"],
        "joint_bonus": .3*delta["both_correct"],
        "image_quality": -.4*(n_metrics["pixel_mse"]-a_metrics["pixel_mse"]),
        "agreement_penalty": .35*(n_metrics["consistency"]-a_metrics["consistency"])}
    utility_delta = n_metrics["task_utility"]-a_metrics["task_utility"]
    residual = sum(components.values())-utility_delta
    assert abs(residual) < 1e-12
    low, high = support["negative_reward_range"]
    tail_a, tail_n = a["both_wrong_disagree_negative"], n["both_wrong_disagree_negative"]
    tail_bounds = [low*tail_n-high*tail_a, high*tail_n-low*tail_a]
    fa, fn = a["greedy_error_count"], n["greedy_error_count"]
    return {"A": a, "N": n, "N_minus_A": delta, "utility_delta": utility_delta,
            "utility_components": components, "decomposition_residual": residual,
            "negative_reward_contribution_delta_bounds": tail_bounds,
            "maximum_negative_tail_share_of_positive_utility_gain": tail_bounds[1]/utility_delta,
            "greedy_net_added_errors": fn-fa,
            "greedy_changed_status_row_count_bounds": [abs(fn-fa), fa+fn],
            "warning": "aggregate identities do not identify which requests/sources/heads changed or greedy-error overlap"}


if __name__ == "__main__":
    started = time.process_time()
    raw = json.loads((RUN / "result.json").read_text())
    manifest = json.loads((RUN / "train-manifest.json").read_text())
    assert manifest["rows"] == 3072 and manifest["source_count"] == 192
    supports = {str(seed): decoder_support(seed) for seed in (11, 23, 47)}
    report = {"scope": "existing all-TRAIN aggregates plus saved decoder arrays; zero per-request encoder/head forwards",
        "source_result_sha256": digest(RUN / "result.json"),
        "all_recorded_train_rows": 3072, "all_recorded_physical_sources": 192,
        "new_training": False, "new_request_predictions": False,
        "code_support_recomputation": True, "new_physical_source_construction": False,
        "decoder_support_recomputation": "12-code fixed reward support, not recovery of historical per-request probabilities",
        "missing": ["per-row p/q", "labels/source IDs and row mapping", "per-row reward/entropic normalizer",
                    "per-head correctness/margins", "which greedy statuses changed", "adjacent final-iterate checkpoints"],
        "decoder_support": supports, "samplers": {}}
    for kind in ("iid", "stratified"):
        rows = []
        for seed in (11, 23, 47):
            a, n = (raw["systems"][arm]["candidates"][f"{kind}-{seed}"] for arm in ("A", "N"))
            row = {"seed": seed, "matched128": compare(a["matched"]["train"], n["matched"]["train"], supports[str(seed)]),
                   "final": compare(a["train"], n["train"], supports[str(seed)])}
            best_greedy_a = max(raw["systems"]["A"]["candidates"][f"{other}-{seed}"]["train"]["greedy_joint_success"]
                                for other in ("iid", "stratified"))
            row["final_N_greedy_net_added_errors_vs_endpointwise_best_A"] = round(3072*(best_greedy_a-n["train"]["greedy_joint_success"]))
            rows.append(row)
        report["samplers"][kind] = rows
    report["analysis_body_cpu_seconds"] = time.process_time()-started
    report["process_cpu_before_write_seconds"] = time.process_time()
    with (HERE / "aggregate-mechanism.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({kind: [{"seed": row["seed"], "delta": row["final"]["N_minus_A"],
        "gain_parts": row["final"]["utility_components"],
        "negative_tail_gain_share_upper": row["final"]["maximum_negative_tail_share_of_positive_utility_gain"],
        "added_greedy_errors": row["final"]["greedy_net_added_errors"]} for row in rows]
        for kind, rows in report["samplers"].items()}, indent=2))
