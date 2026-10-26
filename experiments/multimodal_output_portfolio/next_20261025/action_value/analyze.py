"""Writer-cluster confirmation of real action gains, prediction and total cost."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


ACTIONS = ("stop", "refine_semantic", "refine_image", "refine_text", "couple")
VIEWS = ("clean", "noise", "occlusion", "missing_trusted", "conflict_untrusted",
         "missing_untrusted", "missing_unknown", "both_missing")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while part := stream.read(1024 * 1024): value.update(part)
    return value.hexdigest()


def ce(values):
    scaled = -2 * np.asarray(values); upper = scaled.max()
    return float(-(upper + np.log(np.exp(scaled - upper).mean())) / 2)


def interval(point, samples, level=.975):
    tail = (1 - level) / 2
    return {"estimate": float(point), "lower": float(np.quantile(samples, tail)),
            "upper": float(np.quantile(samples, 1 - tail)), "nominal_level": level}


def key(row):
    return tuple(row[k] for k in ("seed", "case", "view", "draw", "policy"))


def run(directory):
    registration = json.loads((directory / "registration.json").read_text())
    completion = json.loads((directory / "completion.json").read_text())
    spec = registration["spec"]; policies = spec["policies"]
    if completion["failures"]: raise ValueError("Failed actual requests block quality inference")
    for name, expected in completion["files_sha256"].items():
        if sha(directory / name) != expected: raise ValueError("Closed evidence changed")
    allocation_path = Path(spec["source"]["allocation"])
    if sha(allocation_path) != spec["source_allocation_sha256"]:
        raise ValueError("Writer/source allocation changed after registration")
    allocation = json.loads(allocation_path.read_text())
    cluster_ids = allocation["pair_writer_ids"]; writers = sorted(set(cluster_ids))
    source_records = allocation["source_records"]
    if (len(cluster_ids) != 512 or len(writers) != 256 or len(source_records) != 1024
            or set(Counter(cluster_ids).values()) != {2}
            or [x["writer"] for x in source_records[::2]] != cluster_ids
            or [x["writer"] for x in source_records[1::2]] != cluster_ids):
        raise ValueError("Registered 512-pair/256-writer census changed")
    mapping = {w: i for i, w in enumerate(writers)}
    pair_cluster = np.asarray([mapping[w] for w in cluster_ids])
    seeds = [x["seed"] for x in spec["candidates"]]
    shape = (len(policies), len(seeds), len(cluster_ids), len(VIEWS), spec["draws"])
    utility, success, secondary, root_utility, wall, cpu = (np.full(shape, np.nan) for _ in range(6))
    root_prediction = np.full(shape, np.nan); lengths = np.full(shape, np.nan)
    def index(row):
        return policies.index(row["policy"]), seeds.index(row["seed"]), row["case"], VIEWS.index(row["view"]), row["draw"]
    seen, state, work, actual_media_records = set(), {}, {p: Counter() for p in policies}, 0
    with (directory / "media.bin").open("rb") as media, gzip.open(directory / "requests.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            identity = key(row)
            if identity in seen or row["status"] != "completed": raise ValueError("Duplicate or failed primary request")
            seen.add(identity); idx = index(row)
            expected_sources = [x["source_id"] for x in source_records[2 * row["case"]:2 * row["case"] + 2]]
            if row["source_ids"] != expected_sources:
                raise ValueError("Actual request identities do not bind the allocated writer cluster")
            for name in ("terminal", "root_stop"):
                record = row[name]; media.seek(record["offset"]); raw = media.read(204)
                if hashlib.sha256(raw).hexdigest() != record["sha256"]: raise ValueError("Actual request media changed")
                actual_media_records += 1
            root = row["decisions"][0]
            root_prediction[idx] = root["predicted_action_differences"][ACTIONS.index(root["action"])]
            lengths[idx] = len(row["path"]); wall[idx] = row["wall_ns"] / 1e6; cpu[idx] = row["cpu_ns"] / 1e6
            state[identity] = {"root": root["public_sha256"], "path": row["path"], "media": row["terminal"]["sha256"],
                "decisions": row["decisions"], "H1": row["decisions"][-1]["remaining"] == 1}
            work[row["policy"]].update(row["work"])
    expected = {(s, c, v, d, p) for s in seeds for c in range(len(cluster_ids)) for v in VIEWS for d in range(spec["draws"]) for p in policies}
    if seen != expected: raise ValueError("Primary request census differs")
    with gzip.open(directory / "scored.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            idx = index(row)
            if np.isfinite(utility[idx]): raise ValueError("Duplicate primary score")
            utility[idx] = row["scores"]["primary"]["utility"]
            success[idx] = row["scores"]["primary"]["joint_fact_correct"]
            secondary[idx] = row["scores"]["secondary"]["utility"]
            root_utility[idx] = row["root_stop_scores"]["primary"]["utility"]
    if any(not np.isfinite(x).all() for x in (utility, success, secondary, root_utility, wall, cpu, root_prediction, lengths)):
        raise ValueError("Incomplete primary scores or timing")
    commits = Counter()
    with gzip.open(directory / "commitments.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            identity = key(row); decision = commits[identity]
            if row["decision_index"] != decision or any(row[k] != v for k, v in state[identity]["decisions"][decision].items()):
                raise ValueError("Pre-innovation action commitment differs")
            commits[identity] += 1
    if set(commits) != seen or any(commits[k] != len(v["decisions"]) for k, v in state.items()):
        raise ValueError("Incomplete actual action journal")
    parity, initial = 0, 0
    for identity, value in state.items():
        if identity[-1] != "cached_teacher": continue
        other = state[(*identity[:-1], "rich_paired")]
        if value["root"] != other["root"]: raise ValueError("Paired policies lack the same actual initial state")
        initial += 1
        if value["path"] == other["path"]:
            if value["media"] != other["media"]: raise ValueError("Shared policy paths have different actual media")
            parity += 1
    rng = np.random.default_rng(spec["inference"]["bootstrap_seed"])
    bw = rng.multinomial(len(writers), np.full(len(writers), 1 / len(writers)), size=spec["inference"]["replicates"])
    sizes = np.bincount(pair_cluster, minlength=len(writers))
    def means(values):
        pair = values.mean(axis=(1, 3, 4))
        sums = np.stack([pair[:, pair_cluster == i].sum(-1) for i in range(len(writers))], -1)
        return sums @ bw.T / (bw @ sizes)
    def ces(values):
        shift = (-2 * values).max(axis=(1, 2, 3, 4))
        return -(np.log(means(np.exp(-2 * values - shift[:, None, None, None, None]))) + shift[:, None]) / 2
    a, b = policies.index("rich_paired"), policies.index("cached_teacher")
    quality = {}
    for name, values, exponential in (("raw_CE", utility, True), ("success", success, False), ("secondary_CE", secondary, True),
                                      ("mean_wall_ms", wall, False), ("mean_cpu_ms", cpu, False)):
        draws = ces(values) if exponential else means(values)
        point = ce(values[a]) - ce(values[b]) if exponential else values[a].mean() - values[b].mean()
        quality[name] = interval(point, draws[a] - draws[b])
    for clock, costs in (("wall", wall), ("cpu", cpu)):
        points, boot = [], []
        for price in spec["inference"]["prices"]:
            adjusted = utility - price * costs; draws = ces(adjusted)
            points.append(ce(adjusted[a]) - ce(adjusted[b])); boot.append(draws[a] - draws[b])
        radius = float(np.quantile(np.max(np.abs(np.stack(boot) - np.asarray(points)[:, None]), axis=0), .95))
        quality[clock + "_price_curve"] = [{"price": price, "estimate": point, "simultaneous_lower": point - radius,
            "simultaneous_upper": point + radius} for price, point in zip(spec["inference"]["prices"], points)]
    diagnostics, diagnostic_seen = [], set()
    with (directory / "media.bin").open("rb") as media, gzip.open(directory / "counterfactual-scored.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            identity = (row["seed"], row["case"], row["view"], row["draw"], "rich_paired")
            if identity in diagnostic_seen or not state[identity]["H1"]: raise ValueError("Wrong/repeated diagnostic state")
            diagnostic_seen.add(identity); last = state[identity]["decisions"][-1]
            if (row["parent_public_sha256"] != last["public_sha256"] or row["prediction"] != last["predicted_action_differences"]
                    or row["selected_action"] != last["action"] or not row["not_visible_to_policy"]):
                raise ValueError("Diagnostic state or pre-outcome predictions differ")
            if [x["action"] for x in row["alternatives"]] != list(ACTIONS) or [x["action"] for x in row["outcomes"]] != list(ACTIONS):
                raise ValueError("Counterfactual action census differs")
            for alternative in row["alternatives"]:
                saved = alternative["media"]; media.seek(saved["offset"])
                if hashlib.sha256(media.read(204)).hexdigest() != saved["sha256"]: raise ValueError("Counterfactual media changed")
                actual_media_records += 1
                if alternative["action"] == last["action"] and saved["sha256"] != state[identity]["media"]:
                    raise ValueError("Selected counterfactual does not equal actual executed result")
            utilities = np.asarray([x["scores"]["primary"]["utility"] for x in row["outcomes"]])
            actual = np.exp(-2 * (utilities - .002 * np.asarray([0, 1, 1, 1, 1]))) - np.exp(-2 * utilities[0])
            prediction = np.asarray([x if x is not None else np.nan for x in row["prediction"]])
            teacher = np.asarray([x if x is not None else np.nan for x in row["old_teacher_prediction_same_public_state"]])
            selected = ACTIONS.index(last["action"]); feasible = np.asarray([2, 3, 4])
            if selected == 1 or prediction[0] != 0 or actual[0] != 0 or not np.isfinite(prediction[feasible]).all():
                raise ValueError("Stop identity or H1 semantic dominance violated")
            diagnostics.append({"writer": pair_cluster[row["case"]], "case": row["case"], "action": selected,
                "prediction": float(prediction[selected]), "actual": float(actual[selected]),
                "MSE": float(((prediction[feasible] - actual[feasible]) ** 2).mean()),
                "zero_MSE": float((actual[feasible] ** 2).mean()), "teacher_MSE": float(((teacher[feasible] - actual[feasible]) ** 2).mean()),
                "private_hindsight_regret": float(actual[selected] - np.min(actual[[0, 2, 3, 4]])),
                "all_predictions": prediction[feasible].tolist(), "all_actual_differences": actual[feasible].tolist()})
    expected_diagnostic = {k for k, v in state.items() if k[-1] == "rich_paired" and v["H1"]}
    if diagnostic_seen != expected_diagnostic or len(diagnostics) != completion["H1_counterfactual_nodes"]:
        raise ValueError("Incomplete selected-state counterfactual census")
    def event_interval(events, values):
        if not len(events): return None
        groups = np.asarray([x["writer"] for x in events])
        sums = np.bincount(groups, weights=np.asarray(values), minlength=len(writers))
        counts = np.bincount(groups, minlength=len(writers)); denominator = bw @ counts
        if not (denominator > 0).all(): return {"estimate": float(np.mean(values)), "lower": None, "upper": None, "reason": "Some writer resamples contain no selected event"}
        return interval(np.mean(values), bw @ sums / denominator)
    def selected_summary(events):
        return {"n": len(events), "actual_action_minus_stop_moment": event_interval(events, [x["actual"] for x in events]),
            "prediction_bias": event_interval(events, [x["prediction"] - x["actual"] for x in events]),
            "MSE": float(np.mean([(x["prediction"] - x["actual"]) ** 2 for x in events])) if events else None,
            "private_hindsight_moment_regret": float(np.mean([x["private_hindsight_regret"] for x in events])) if events else None}
    non_stop = [x for x in diagnostics if x["action"] != 0]
    learned = {"same_state_MSE_minus_zero": event_interval(diagnostics, [x["MSE"] - x["zero_MSE"] for x in diagnostics]),
        "same_state_MSE_minus_teacher": event_interval(diagnostics, [x["MSE"] - x["teacher_MSE"] for x in diagnostics]),
        "candidate_MSE": float(np.mean([x["MSE"] for x in diagnostics])) if diagnostics else None,
        "zero_MSE": float(np.mean([x["zero_MSE"] for x in diagnostics])) if diagnostics else None,
        "teacher_MSE": float(np.mean([x["teacher_MSE"] for x in diagnostics])) if diagnostics else None,
        "all_selected": selected_summary(diagnostics), "nonstop_only": selected_summary(non_stop),
        "by_action": {ACTIONS[action]: selected_summary([x for x in diagnostics if x["action"] == action]) for action in (0, 2, 3, 4)},
        "nonstop_bins": [{"interval": [lo, hi], **selected_summary([x for x in non_stop if lo <= x["prediction"] < hi])}
                         for lo, hi in ((-10., -.1), (-.1, -.025), (-.025, 0.), (0., 10.))]}
    value_mse, value_gain = learned["same_state_MSE_minus_zero"], learned["nonstop_only"]["actual_action_minus_stop_moment"]
    value_pass = bool(value_mse and value_gain and value_mse["upper"] is not None and value_gain["upper"] is not None and value_mse["upper"] < 0 and value_gain["upper"] < 0)
    replacement = quality["raw_CE"]["lower"] >= -.005 and quality["success"]["lower"] >= -.005 and quality["mean_wall_ms"]["upper"] < 0
    policy_summary = {p: {"raw_CE": ce(utility[i]), "success": float(success[i].mean()), "secondary_CE": ce(secondary[i]),
        "mean_wall_ms": float(wall[i].mean()), "mean_cpu_ms": float(cpu[i].mean()),
        "wall_p50_p95_p99_max_ms": np.quantile(wall[i], [.5, .95, .99, 1.]).tolist(), "work": dict(work[p]),
        "selected_H2_moment_prediction_bias": float((root_prediction[i] - (np.exp(-2 * (utility[i] - .002 * lengths[i])) - np.exp(-2 * root_utility[i]))).mean())}
        for i, p in enumerate(policies)}
    result = {"schema": "hepta.next.rich-action-value-analysis.v1", "status": "completed", "requests": len(seen), "failures": 0,
        "new_source_pairs": len(cluster_ids), "writer_clusters": len(writers), "fixed_trained_seeds": seeds,
        "same_initial_state_pairs": initial, "same_path_actual_media_parity_pairs": parity, "actual_media_records_verified": actual_media_records,
        "H1_diagnostic_nodes": len(diagnostics), "policies": policy_summary, "candidate_minus_teacher": quality,
        "action_value_diagnostics": learned, "action_value_family_pass": value_pass, "original_replacement_family_pass": replacement,
        "qualified_replacement": value_pass and replacement, "protocol_sha256": registration["protocol_sha256"],
        "interval_scope": "Nominal97.5% writer-cluster bootstrap, fixed trained-seed panel. Price bands95% separately per clock. No finite-sample or conditional-uniform guarantee.",
        "regret_scope": "After-selection actual H1 alternatives privately scored after choices; realized hindsight regret cannot be attained online and is not a conditional optimality certificate.",
        "source_sha256": sha(__file__), "completion_sha256": sha(directory / "completion.json")}
    with (directory / "analysis.json").open("x") as stream: json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({"requests": len(seen), "writers": len(writers), "policies": policy_summary, "candidate_minus_teacher": quality,
                      "action_value_family_pass": value_pass, "original_replacement_family_pass": replacement,
                      "same_state_MSE_minus_zero": learned["same_state_MSE_minus_zero"], "nonstop": learned["nonstop_only"]}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--directory", type=Path, required=True)
    a = p.parse_args(); run(a.directory)
