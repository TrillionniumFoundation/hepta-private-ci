"""Independent paired statistics and complete-grid checks for runtime audit."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np

from analysis_contract import bootstrap_family
from runtime_audit_support import ARMS, file_sha, object_sha, open_profile, records, require, verify_unchanged


def terminal(actions):
    require(isinstance(actions, list) and 1 <= len(actions) <= 3 and
            all(type(action) is int and action in range(5) for action in actions), "Illegal selected action sequence")
    require(0 not in actions[:-1] and (actions[-1] == 0 or len(actions) == 3), "Decision after stop or incomplete episode")
    node, depth = 0, 0
    for action in actions:
        if action:
            node = 4 * node + action
            depth += 1
    return node, depth


def collect_seed(rows, *, seed, profile, protocol, registry, policies):
    """Validate every prespecified cell; do not drop missing/invalid episodes."""
    conditions = protocol["runtime"]["conditions"]
    pair_count = protocol["runtime"]["audit_pairs"]
    identities = registry["roles"]["runtime_audit"]["identities"]
    require(len(identities) == 2 * pair_count and len(set(identities)) == len(identities), "Runtime source role count differs")
    arrays = {observer: {arm: np.full((pair_count, len(conditions)), np.nan) for arm in ARMS}
              for observer in ("reward", "audit")}
    seen, resources, batches, depths, decisions = set(), Counter(), {}, {arm: Counter() for arm in ARMS}, {arm: 0 for arm in ARMS}
    for row in rows:
        arm, condition, pair = row["arm"], row["condition"], row["pair_index"]
        require(row["seed"] == seed and row["profile"] == profile and row["role"] == "runtime_audit",
                "Selected episode scope differs")
        require(arm in ARMS and condition in conditions and type(pair) is int and 0 <= pair < pair_count, "Unexpected selected grid cell")
        key = (arm, condition, pair)
        require(key not in seen, "Duplicate selected source-pair/condition/arm cell")
        seen.add(key)
        case = f"runtime_audit-{seed}-{condition}-{pair:06d}"
        require(row["case_id"] == case and row["source_ids"] == identities[2 * pair:2 * pair + 2], "Selected source/case identity differs")
        require(row["controller_sha256"] == object_sha(policies[arm]) and row["unchosen_continuations_executed"] == 0,
                "Selected controller or executed action opportunity differs")
        node, depth = terminal(row["actions"])
        require(row["terminal_node"] == node and row["depth"] == depth and len(row["media"]) == 1 + depth and
                len(row["feedback"]) == min(depth, 2) and len(row["decisions"]) == len(row["actions"]),
                "Selected action/media/feedback depth accounting differs")
        require(set(row["scores"]) == {"reward", "audit"}, "Both observer outcomes are required")
        for observer in arrays:
            utility, net = row["scores"][observer]["utility"], row["scores"][observer]["net_utility"]
            require(type(utility) in (int, float) and type(net) in (int, float) and np.isfinite([utility, net]).all() and
                    -1 - 1e-12 <= utility <= 1 + 1e-12 and abs(net - (utility - .002 * (1 + depth))) <= 1e-12,
                    "Net utility is not the registered actual-transition charge")
            arrays[observer][arm][pair, conditions.index(condition)] = net
        deliveries = 1 + depth
        for name in ("encoder_examples", "encoder_batches"):
            resources[name] += 1
        for name in ("transition_examples", "transition_batches", "decoder_examples", "decoder_batches", "media_logical_deliveries_read_back"):
            resources[name] += deliveries
        resources["public_feature_observer_digit_examples"] += 2 * (1 + min(depth, 2))
        resources["simulated_feedback_packets"] += min(depth, 2)
        resources["selection_rows"] += len(row["actions"])
        resources["native_tick_calls"] += 2 * len(row["actions"]) if arm in ("native", "reset_native") else 0
        for observer in arrays:
            resources[observer + "_outcome_observer_digit_examples"] += 2
        batch = (arm, condition, pair // protocol["runtime"]["batch_size"])
        batches[batch] = max(batches.get(batch, 0), len(row["actions"]))
        depths[arm][depth] += 1
        decisions[arm] += len(row["actions"])
    expected = len(ARMS) * pair_count * len(conditions)
    require(len(seen) == expected and all(np.isfinite(value).all() for methods in arrays.values() for value in methods.values()),
            "Incomplete prespecified selected-runtime grid")
    resources["selection_batches"] = sum(batches.values())
    resources["unchosen_continuations_executed"] = 0
    return arrays, {"episodes": expected, "resources_reconstructed": dict(resources),
                    "depths_by_arm": {arm: dict(value) for arm, value in depths.items()}, "decisions_by_arm": decisions}


def analyze(profile_data, protocol):
    require(len(profile_data) == len(protocol["seeds"]), "Incomplete fixed model family")
    arrays = {observer: {arm: np.stack([data[observer][arm] for data in profile_data])[:, None]
                         for arm in ARMS} for observer in ("reward", "audit")}
    gate = protocol["runtime_audit_gate"]
    comparisons = [{"name": name, "panel": "runtime", "left": name.split("-")[0],
                    "right": name.split("-")[1], "kind": "gain"} for name in gate["gain_contrasts"]]
    clean_index = protocol["runtime"]["conditions"].index("clean")
    comparisons += [{"name": arm + "-fixed-clean", "panel": "runtime", "left": arm, "right": gate["retention_reference"],
                     "kind": "noninferiority", "margin": -gate["clean_ci_lower_strict_min"], "condition_indices": [clean_index]}
                    for arm in gate["retention_candidates"]]
    return bootstrap_family({"runtime": arrays}, comparisons, draws=gate["bootstrap_samples"],
                            rng_seed=gate["bootstrap_seed"], family_alpha=gate["family_alpha"],
                            family_comparisons=gate["family_comparisons"], expected_seeds=len(protocol["seeds"]), expected_rollouts=1)


def execute(run, profile, source, freeze):
    bundle = open_profile(run, profile, source, freeze)
    arrays, evidence = [], []
    for item in bundle["seeds"]:
        values, summary = collect_seed((row for row, _ in records(item["selected"] / "rows.jsonl.gz")),
            seed=item["seed"], profile=profile, protocol=bundle["protocol"], registry=bundle["registry"], policies=item["policies"])
        require(all(item["complete"]["resources"][name] == value for name, value in summary["resources_reconstructed"].items()),
                "Reported selected work differs from actual episode paths")
        arrays.append(values)
        evidence.append({"seed": item["seed"], "profile": profile, **summary,
            "parent_complete_sha256": item["input_sha256"]["parent_complete"],
            "selected_complete_sha256": item["input_sha256"]["selected_complete"],
            "rows_sha256": item["input_sha256"]["rows.jsonl.gz"],
            "events_sha256": item["input_sha256"]["events.jsonl.gz"], "readouts_sha256": item["input_sha256"]["readouts"],
            "fit_complete_sha256": item["input_sha256"]["fit_complete"]})
    result = analyze(arrays, bundle["protocol"])
    verify_unchanged(bundle)
    return {"schema": "hepta.field-bridge.v3.independent-runtime-results.1", "status": "pass",
            "passed": result["complete_family_pass"], "profile": profile,
            "protocol_sha256": bundle["protocol_sha256"], "freeze_sha256": bundle["freeze_sha256"],
            "source_manifest_sha256": bundle["protocol"]["source_manifest_sha256"], "seeds": evidence,
            "independent_gate": result, "generator_forwards": 0, "observer_forwards": 0,
            "scientific_acceptance_requires": "Matching complete media/feedback and native replay audits; this arithmetic receipt alone is insufficient",
            "claim_scope": "Frozen profile is independently registered; ordinary/field are only components of the prespecified all-three-profile conjunction",
            "reviewer_source_files": {name: file_sha(Path(__file__).with_name(name))
                                      for name in ("runtime_results_audit.py", "runtime_audit_support.py", "analysis_contract.py")}}


def main():
    parser = argparse.ArgumentParser()
    for name in ("run", "source", "freeze", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--profile", required=True, choices=("frozen", "ordinary", "field"))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    require(not output.is_relative_to((Path(args.run) / "runtime").resolve()), "Audit receipts must stay outside frozen runtime evidence")
    started = time.monotonic()
    result = execute(args.run, args.profile, args.source, args.freeze)
    result["elapsed_seconds"] = time.monotonic() - started
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("status", "passed", "profile", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
