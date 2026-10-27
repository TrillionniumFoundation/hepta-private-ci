"""Independent prospective 512-pair primary/retention arithmetic audit.

Streams delivered-row records without importing the study analyzer, fitting a
model, loading an observer or reading media. Media authenticity has a separate
audit. Constants encode the independently agreed primary comparison protocol.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

SEEDS = (17, 29, 43)
ARMS = ("A_frozen_fixed", "B_ordinary_fixed", "C_field_fixed", "D_frozen_native", "E_field_native",
        "F_field_history", "G_ordinary_native", "H_frozen_history", "I_field_reset", "J_generic_fixed", "K_richer_fixed")
CONDITIONS = {"test": ("clean", "occlusion", "missing", "heavy_noise"), "retention": ("clean",)}
PAIRS = 512
PRIMARY = ((ARMS[1], ARMS[0]), (ARMS[2], ARMS[1]), (ARMS[3], ARMS[0]),
           (ARMS[4], ARMS[2]), (ARMS[4], ARMS[6]), (ARMS[4], ARMS[5]))
RETENTION = tuple(arm for arm in ARMS if arm not in (ARMS[0], ARMS[8]))
OBSERVERS = ("reward", "audit")
WEIGHTS = {"text_fact": .30, "relation": .15, "image_fact": .35,
           "crossmodal_disagreement": .10, "pixel_mse": .10}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tables(root):
    values = {(split, observer, arm): np.full((3, PAIRS, len(conditions)), np.nan)
              for split, conditions in CONDITIONS.items() for observer in OBSERVERS for arm in ARMS}
    actions = {(split, arm): np.full((3, PAIRS, len(conditions)), -1, dtype=int)
               for split, conditions in CONDITIONS.items() for arm in ARMS}
    pair_identities, image_owner, seen, count, inputs = {}, {}, set(), 0, {}
    for seed in SEEDS:
        path = root / "eval" / str(seed) / "rows.jsonl.gz"
        inputs[str(path.relative_to(root))] = digest(path)
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                split, arm, pair, condition = (row[k] for k in ("split", "arm", "pair", "corruption"))
                if (row["seed"] != seed or split not in CONDITIONS or arm not in ARMS
                        or type(pair) is not int or not 0 <= pair < PAIRS or condition not in CONDITIONS[split]):
                    raise ValueError("Row outside the preregistered evaluation grid")
                key = (seed, arm, split, pair, condition)
                if key in seen:
                    raise ValueError("Duplicated primary observation")
                seen.add(key)
                sources = tuple(row["source_ids"])
                if len(sources) != 2 or len(set(sources)) != 2:
                    raise ValueError("Invalid independent source-pair identity")
                cluster = (split, pair)
                if pair_identities.setdefault(cluster, sources) != sources:
                    raise ValueError("Paired conditions/models/arms have different sources")
                for source in sources:
                    pixel_hash = source.rsplit(":", 1)[-1]
                    if image_owner.setdefault(pixel_hash, cluster) != cluster:
                        raise ValueError("Pixel identity overlaps allegedly independent clusters")
                action = row["action"]
                if (type(action) is not int or not 0 <= action < 5
                        or row["refinement_count"] != 1 + (action != 0)):
                    raise ValueError("Actual continuation or refinement cost changed")
                index = (SEEDS.index(seed), pair, CONDITIONS[split].index(condition))
                actions[split, arm][index] = action
                for observer in OBSERVERS:
                    score = row[observer]
                    components = np.asarray([score[name] for name in WEIGHTS], dtype=float)
                    if not np.isfinite(components).all() or components.min() < 0 or components.max() > 1:
                        raise ValueError("Invalid hard-score components")
                    joint = sum(WEIGHTS[name] * score[name] for name in WEIGHTS)
                    if (abs(joint - score["joint_loss"]) > 1e-12
                            or abs(1 - 2 * joint - score["utility"]) > 1e-12):
                        raise ValueError("Net utility differs from the declared hard-output formula")
                    values[split, observer, arm][index] = score["utility"] - .002 * row["refinement_count"]
                count += 1
    if count != 84480 or len(pair_identities) != 1024 or len(image_owner) != 2048:
        raise ValueError("Incomplete prospective cohort or source identities")
    if any(not np.isfinite(value).all() for value in values.values()) or any(np.any(a < 0) for a in actions.values()):
        raise ValueError("Missing seed/pair/condition/arm entries")
    return values, actions, inputs


def ce(values):
    return float(-np.log(np.exp(-2 * values).mean()) / 2)


def calculate(values, actions, bootstrap_seed):
    samples = {split: np.random.default_rng(bootstrap_seed + index).integers(PAIRS, size=(4000, PAIRS))
               for index, split in enumerate(CONDITIONS)}
    ce_samples = {key: -.5 * np.log(np.exp(-2 * value).mean(axis=(0, 2))[samples[key[0]]].mean(axis=1))
                  for key, value in values.items()}

    def contrast(split, candidate, baseline, tail):
        result = {}
        for observer in OBSERVERS:
            left, right = values[split, observer, candidate], values[split, observer, baseline]
            difference = left - right
            paired = difference.mean(axis=(0, 2))
            interval = np.quantile(paired[samples[split]].mean(axis=1), [tail, 1 - tail]).tolist()
            by_seed = difference.mean(axis=(1, 2))
            result[observer] = {"mean_net_return_difference": float(difference.mean()),
                "paired_cluster_interval": interval,
                "per_seed_mean_differences": [{"seed": seed, "difference": float(v)} for seed, v in zip(SEEDS, by_seed)],
                "positive_in_every_fixed_seed": bool(np.all(by_seed > 0)),
                "gain_supported": bool(interval[0] > 0 and np.all(by_seed > 0)),
                "pooled_ce_difference": ce(left) - ce(right),
                "pooled_ce_descriptive_95_interval": np.quantile(
                    ce_samples[split, observer, candidate] - ce_samples[split, observer, baseline], [.025, .975]).tolist()}
        return result

    retention, primary = [], []
    for candidate in RETENTION:
        observers = contrast("retention", candidate, ARMS[0], .05 / 18)
        for check in observers.values():
            check["noninferiority_supported"] = check["paired_cluster_interval"][0] >= -.01
        retention.append({"candidate": candidate, "control": ARMS[0], "observers": observers,
                          "both_observers_noninferior": all(x["noninferiority_supported"] for x in observers.values())})
    retention_pass = {entry["candidate"]: entry["both_observers_noninferior"] for entry in retention}
    for candidate, baseline in PRIMARY:
        observers = contrast("test", candidate, baseline, .05 / 12)
        gain = all(x["gain_supported"] for x in observers.values())
        primary.append({"candidate": candidate, "control": baseline, "observers": observers,
                        "both_observers_gain_supported": gain,
                        "candidate_retention_vs_frozen_supported": retention_pass[candidate],
                        "accepted_with_retention": gain and retention_pass[candidate]})
    interaction = {}
    for observer in OBSERVERS:
        difference = (values["test", observer, ARMS[4]] - values["test", observer, ARMS[2]]
                      - values["test", observer, ARMS[3]] + values["test", observer, ARMS[0]])
        interval = np.quantile(difference.mean(axis=(0, 2))[samples["test"]].mean(axis=1), [.025, .975])
        interaction[observer] = {"mean_net_return_interaction": float(difference.mean()),
            "descriptive_95_interval": interval.tolist(),
            "per_seed": [{"seed": seed, "difference": float(v)}
                         for seed, v in zip(SEEDS, difference.mean(axis=(1, 2)))]}
    summaries = {}
    for split in CONDITIONS:
        for arm in ARMS:
            result = {"observers": {observer: {"mean_net_return": float(values[split, observer, arm].mean()),
                      "pooled_ce": ce(values[split, observer, arm])} for observer in OBSERVERS},
                      "action_counts": np.bincount(actions[split, arm].ravel(), minlength=5).tolist(),
                      "mean_actual_refinements": float(1 + np.mean(actions[split, arm] != 0))}
            summaries[split + "/" + arm] = result
    return {"primary_contrasts": primary, "retention_vs_frozen": retention,
            "interaction_descriptive": {"observers": interaction}, "summaries": summaries,
            "native_state_reset_action_diagnostic": {split: {
                "action_changes": int(np.count_nonzero(actions[split, ARMS[4]] != actions[split, ARMS[8]])),
                "paired_rows": int(actions[split, ARMS[4]].size)} for split in CONDITIONS},
            "all_six_primary_gains_accepted": all(row["accepted_with_retention"] for row in primary)}


def compare(computed, original):
    errors = []

    def check(first, second, path):
        if isinstance(first, dict):
            for key, value in first.items():
                if key not in second:
                    raise ValueError(f"Reported result missing {path}/{key}")
                check(value, second[key], path + "/" + key)
        elif isinstance(first, list):
            if len(first) != len(second):
                raise ValueError(f"Reported list cardinality differs at {path}")
            for index, (left, right) in enumerate(zip(first, second, strict=True)):
                check(left, right, path + f"/{index}")
        elif isinstance(first, bool) or isinstance(first, str) or isinstance(first, int):
            if first != second:
                raise ValueError(f"Reported categorical/count decision differs at {path}")
        else:
            error = abs(first - second)
            errors.append(error)
            if not np.isfinite(error) or error > 1e-12:
                raise ValueError(f"Reported numeric result differs at {path}: {error}")
    check(computed, original, "")
    return max(errors, default=0.)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).parent.parent / "field_bridge_v2_20261027" / "PRIMARY_PROTOCOL.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    required = {"test_pairs": 512, "retention_pairs": 512, "bootstrap_samples": 4000,
                "family_alpha": .05, "retention_margin": .01}
    if any(protocol[key] != value for key, value in required.items()):
        raise ValueError("Primary constants differ from the independently agreed protocol")
    if (protocol["primary_contrasts"] != [list(pair) for pair in PRIMARY]
            or protocol["retention_family"] != list(RETENTION)
            or any(protocol[split + "_conditions"] != list(conditions) for split, conditions in CONDITIONS.items())):
        raise ValueError("Primary comparison/condition families changed")
    seed = protocol["bootstrap_seed"]
    if type(seed) is not int or seed < 0:
        raise ValueError("Invalid registered bootstrap seed")
    values, actions, inputs = load_tables(args.run)
    inputs[str(args.protocol)] = digest(args.protocol)
    results = calculate(values, actions, seed)
    error = None
    if args.result is not None:
        error = compare(results, json.loads(args.result.read_text()))
        inputs[str(args.result)] = digest(args.result)
    output = {"schema": "hepta.field-bridge.v2.primary-independent-arithmetic.v1",
              "rows": 84480, "independent_source_pairs": {"test": 512, "retention": 512},
              "unique_source_images": 2048, "input_files_sha256": inputs,
              "script_sha256": digest(Path(__file__)), "bootstrap_seed": seed, "maximum_result_discrepancy": error,
              "computed": results,
              "scope": "Independent arithmetic conditional on three fixed models, using paired source clusters. No analyzer import, model fit, observer call or scientific effect assumed in advance. Media/source authenticity checked separately."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as destination:
        json.dump(output, destination, indent=2, sort_keys=True, allow_nan=False)
        destination.write("\n")
    print(json.dumps({"rows": output["rows"], "maximum_result_discrepancy": error,
                      "primary_accepted": sum(x["accepted_with_retention"] for x in results["primary_contrasts"])}))


if __name__ == "__main__":
    main()
