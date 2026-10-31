"""Independent closed-file census and secondary selected-action diagnostics.

This review was added before prospective collection completed. It does not
change the frozen primary analysis or use outcomes to select another policy.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while data := stream.read(1024 * 1024): value.update(data)
    return value.hexdigest()


def utility_ce(values):
    values = -2 * np.asarray(values, dtype=np.float64)
    upper = values.max()
    return float(-.5 * (upper + np.log(np.exp(values - upper).mean())))


def identity(row):
    return tuple(row[k] for k in ("seed", "case", "view", "draw", "policy"))


def run(directory, output):
    registration = json.loads((directory / "registration.json").read_text())
    completion = json.loads((directory / "completion.json").read_text())
    primary = json.loads((directory / "analysis.json").read_text())
    spec = registration["spec"]
    if completion["failures"] != 0 or primary["failures"] != 0:
        raise ValueError("Cannot certify an incomplete run")
    for name, expected in completion["files_sha256"].items():
        if sha(directory / name) != expected: raise ValueError("Changed closed evidence")
    for row in completion["model_loads"]:
        for name, expected in row["graph_sha256"].items():
            if sha(directory / f"compiled-seed-{row['seed']}" / name) != expected:
                raise ValueError("Changed actually executed frozen graph")
    allocation = json.loads(Path(spec["source"]["allocation"]).read_text())
    writers = allocation["roles"]["control"]["pair_writer_ids"]
    clusters = sorted(set(writers)); inverse = {w: i for i, w in enumerate(clusters)}
    cluster_by_case = np.asarray([inverse[w] for w in writers])
    scored = {}
    with gzip.open(directory / "scored.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            key = identity(row)
            if key in scored: raise ValueError("Duplicate score identity")
            scored[key] = row
    utilities, success, wall = defaultdict(list), defaultdict(list), defaultdict(list)
    calibration, media_count, stops, feedback = defaultdict(list), 0, 0, Counter()
    selected_policies = {}
    with (directory / "media.bin").open("rb") as media, gzip.open(directory / "requests.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            key = identity(row); score = scored.pop(key)
            for name in ("terminal", "calibration_stop"):
                if name in row:
                    media.seek(row[name]["offset"]); raw = media.read(204)
                    if hashlib.sha256(raw).hexdigest() != row[name]["sha256"]:
                        raise ValueError("Actual saved media changed")
                    media_count += 1
            p = row["policy"]
            utilities[p].append(score["scores"]["primary"]["utility"])
            success[p].append(score["scores"]["primary"]["joint_fact_correct"])
            wall[p].append(row["wall_ns"] / 1e6)
            if p in ("cached_teacher", "compiled_teacher", "fresh_feedback", "stale_feedback"):
                selected_policies[key] = {"path": row["path"], "media": row["terminal"]["sha256"],
                    "root": (row["decisions"][0]["action"], row["decisions"][0]["public_sha256"]),
                    "second": row["decisions"][1] if len(row["decisions"]) == 2 else None}
            if "stop_scores" not in score: continue
            step = row["decisions"][-1]
            before = score["stop_scores"]["primary"]["utility"]
            after = score["scores"]["primary"]["utility"]
            cost = .002 * (step["action"] != "stop")
            actual = float(np.exp(-2 * (after - cost)) - np.exp(-2 * before))
            prediction = step["predicted_action_minus_stop_moment"]
            if step["action"] == "stop":
                if actual != 0 or prediction != 0 or row["terminal"]["sha256"] != row["calibration_stop"]["sha256"]:
                    raise ValueError("Stop did not preserve its actual draft/moment exactly")
                stops += 1
            calibration[p].append({"case": row["case"], "writer": cluster_by_case[row["case"]],
                "seed": row["seed"], "action": step["action"], "prediction": prediction,
                "actual": actual, "before": before, "after": after, "cost": cost,
                "strict_gain": score["scores"]["primary"]["joint_fact_correct"] - score["stop_scores"]["primary"]["joint_fact_correct"]})
    if scored: raise ValueError("Scores without corresponding actual execution")
    max_summary_error = 0.
    for policy in spec["policies"]:
        for key, recomputed in (("CE", utility_ce(utilities[policy])), ("success", float(np.mean(success[policy]))), ("mean_wall_ms", float(np.mean(wall[policy])))):
            max_summary_error = max(max_summary_error, abs(primary["policies"][policy][key] - recomputed))
    if max_summary_error > 1e-10: raise ValueError("Independent summary differs")
    for key, old in list(selected_policies.items()):
        if key[-1] != "cached_teacher": continue
        compiled = selected_policies[(*key[:-1], "compiled_teacher")]
        fresh = selected_policies[(*key[:-1], "fresh_feedback")]
        stale = selected_policies[(*key[:-1], "stale_feedback")]
        if old["path"] != compiled["path"] or old["media"] != compiled["media"]:
            raise ValueError("Compiled action/media mismatch")
        if old["path"] != fresh["path"] or old["media"] != fresh["media"] or fresh["root"] != stale["root"]:
            raise ValueError("Feedback root or fresh-teacher mismatch")
        feedback["paired_requests"] += 1
        if fresh["second"]:
            a, b = fresh["second"], stale["second"]
            if (a["public_sha256"] != b["public_sha256"] or a["fresh_action"] != b["fresh_action"]
                    or a["stale_action"] != b["stale_action"] or not a["new_draft_delivered"] or not b["new_draft_delivered"]):
                raise ValueError("Fresh/stale comparison lacks the same pre-choice current draft")
            feedback["same_actual_child_draft"] += 1
            feedback["actual_draft_changed_since_root"] += int(a["observed_draft_changed"])
            feedback["second_action_disagreements"] += int(a["action"] != b["action"])
    rng = np.random.default_rng(202610251499)
    weights = rng.multinomial(len(clusters), np.full(len(clusters), 1 / len(clusters)), size=4000)
    def summary(values):
        if not values: return {"n": 0}
        groups = np.asarray([x["writer"] for x in values])
        pred = np.asarray([x["prediction"] for x in values]); actual = np.asarray([x["actual"] for x in values])
        counts = np.bincount(groups, minlength=len(clusters))
        denominator = weights @ counts
        result = {"n": len(values), "represented_writers": int((counts > 0).sum()),
            "mean_predicted_action_minus_stop_moment": float(pred.mean()),
            "mean_actual_action_minus_stop_moment": float(actual.mean()),
            "prediction_bias": float((pred - actual).mean()), "MSE": float(((pred - actual) ** 2).mean()),
            "raw_terminal_CE_gain_from_actual_stop": utility_ce([x["after"] for x in values]) - utility_ce([x["before"] for x in values]),
            "action_cost_adjusted_terminal_CE_gain_from_actual_stop": utility_ce([x["after"] - x["cost"] for x in values]) - utility_ce([x["before"] for x in values]),
            "strict_success_gain": float(np.mean([x["strict_gain"] for x in values])),
            "bootstrap_replicates_without_selected_rows": int((denominator == 0).sum())}
        if (denominator == 0).any():
            result["intervals"] = None
        else:
            samples = weights @ np.bincount(groups, weights=actual, minlength=len(clusters)) / denominator
            result["actual_moment_difference_nominal95"] = np.quantile(samples, [.025, .975]).tolist()
            error_samples = weights @ np.bincount(groups, weights=pred - actual, minlength=len(clusters)) / denominator
            result["prediction_bias_nominal95"] = np.quantile(error_samples, [.025, .975]).tolist()
        return result
    diagnostic = {}
    for policy, values in calibration.items():
        non_stop = [x for x in values if x["action"] != "stop"]
        diagnostic[policy] = {"all_selected_H1": summary(values), "nonstop_only_H1": summary(non_stop),
            "by_action": {action: summary([x for x in values if x["action"] == action]) for action in ("stop", "refine_image", "refine_text", "couple")},
            "nonstop_by_predicted_bin": [{"range": [lo, hi], **summary([x for x in non_stop if lo <= x["prediction"] < hi])}
                for lo, hi in ((-10., -.1), (-.1, -.025), (-.025, 0.), (0., 10.))]}
    result = {"schema": "hepta.next.control-independent-review.v1", "status": "passed",
        "actual_media_records_verified": media_count, "exact_stop_records": stops,
        "maximum_aggregate_recomputation_error": max_summary_error, "feedback": dict(feedback),
        "source_pairs": len(writers), "writers": len(clusters), "selected_action_diagnostics": diagnostic,
        "scope": "Secondary diagnostics requested before collection ended; nominal pointwise 95% writer-cluster intervals, no multiplicity or uniform conditional guarantee. Public latent384 always retained, so feedback contrast concerns only explicit decoded-draft information.",
        "registered_primary_analysis_changed": False,
        "inputs_sha256": {name: sha(directory / name) for name in ("registration.json", "completion.json", "analysis.json", "media.bin", "requests.jsonl.gz", "scored.jsonl.gz")}}
    if output.exists(): raise FileExistsError("Do not overwrite an independent review")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream: json.dump(result, stream, sort_keys=True, indent=2); stream.write("\n")
    print(json.dumps({"status": result["status"], "media_records": media_count, "feedback": result["feedback"],
        "nonstop_calibration": {p: v["nonstop_only_H1"] for p, v in diagnostic.items()}}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.directory, a.output)
