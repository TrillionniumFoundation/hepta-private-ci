"""Independent arithmetic audit of the frozen actuator pilot, with no generation."""

import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np

CAPTION = re.compile(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)")


def semantic_key(row):
    match = CAPTION.fullmatch(row[0].strip())
    return (None if match is None else match.groups(), row[1:])


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def near(first, second):
    if not np.isclose(first, second, rtol=0., atol=1e-12):
        raise AssertionError(f"Recorded arithmetic differs: {first!r} versus {second!r}")


def output_check(output, specification):
    values = np.asarray(output["values"], dtype=np.float64)
    expected = specification["pairs"] * len(specification["conditions"])
    assert values.shape == (expected,) and np.isfinite(values).all()
    assert len(output["decisions"]) == expected and len(output["output_sha256"]) == expected
    assert all(len(x) == 64 and set(x) <= set("0123456789abcdef") for x in output["output_sha256"])
    near(float(values.mean()), output["value"])
    condition_values = values.reshape(len(specification["conditions"]), specification["pairs"])
    assert set(output["by_condition"]) == set(specification["conditions"])
    for condition, group in zip(specification["conditions"], condition_values, strict=True):
        near(float(group.mean()), output["by_condition"][condition])


def audit(run_dir):
    run_dir = Path(run_dir).resolve()
    source_root = Path(__file__).resolve().parent.parent
    protocol_path = source_root / "field_bridge_v2_20261027" / "PILOT_PROTOCOL.json"
    protocol = json.loads(protocol_path.read_text())
    result_path = run_dir / "PILOT_RESULT.json"
    result = json.loads(result_path.read_text())
    freeze = json.loads((run_dir / "SOURCE_FREEZE.json").read_text())
    assert result["protocol_sha256"] == digest(protocol_path)
    for relative, expected in freeze["files"].items():
        assert digest(source_root / relative) == expected, f"Frozen source changed: {relative}"
    assert result["audit_observer_loaded"] is False
    assert result["test_retention_scored"] is False
    assert result["allowed_to_open_new_test"] is False
    assert set(result["results"]) == set(map(str, protocol["seeds"]))
    counts = {"candidate_results": 0, "failed_candidates": 0, "hard_output_rows_recomputed": 0}
    candidate_statistics = []
    source_ids = {}
    for seed in protocol["seeds"]:
        block = result["results"][str(seed)]
        baseline = json.loads((run_dir / str(seed) / "BASELINE.json").read_text())
        assert len(baseline["actions"]) == 5
        for action in baseline["actions"]:
            output_check(action, protocol["selection_panel"])
            counts["hard_output_rows_recomputed"] += len(action["values"])
        selected_action = int(np.argmax([x["value"] for x in baseline["actions"]]))
        assert baseline["action"] == selected_action == block["action"]
        near(block["baseline_value"], baseline["actions"][selected_action]["value"])
        output_check(baseline["response"], protocol["response_panel"])
        output_check(baseline["clean"], protocol["clean_probe"])
        counts["hard_output_rows_recomputed"] += len(baseline["response"]["values"]) + len(baseline["clean"]["values"])
        source_ids[seed] = {}
        for name, specification in (("response", protocol["response_panel"]),
                                    ("clean", protocol["clean_probe"]),
                                    ("selection", protocol["selection_panel"])):
            pairs = baseline["source_ids"][name]
            assert len(pairs) == specification["pairs"] and all(len(pair) == 2 for pair in pairs)
            ids = [source for pair in pairs for source in pair]
            assert len(set(ids)) == len(ids)
            source_ids[seed][name] = set(ids)
        for first, second in (("response", "clean"), ("response", "selection"), ("clean", "selection")):
            assert not source_ids[seed][first] & source_ids[seed][second]
        assert len(block["candidates"]) == len(protocol["candidates"])
        candidate_values = [baseline["response"]["value"]]
        for recipe, candidate in zip(protocol["candidates"], block["candidates"], strict=True):
            counts["candidate_results"] += 1
            assert candidate["recipe"] == recipe
            suffix = ".FAILED.json" if candidate.get("failed") else ".json"
            recorded = json.loads((run_dir / str(seed) / (recipe["name"] + suffix)).read_text())
            assert recorded == candidate
            if candidate.get("failed"):
                counts["failed_candidates"] += 1
                continue
            for name, specification in (("response", protocol["response_panel"]),
                                        ("selection", protocol["selection_panel"]),
                                        ("clean", protocol["clean_probe"])):
                output_check(candidate[name], specification)
                counts["hard_output_rows_recomputed"] += len(candidate[name]["values"])
            original_selection = baseline["actions"][selected_action]
            gain = candidate["selection"]["value"] - original_selection["value"]
            clean_change = candidate["selection"]["by_condition"]["clean"] - original_selection["by_condition"]["clean"]
            probe_change = candidate["clean"]["value"] - baseline["clean"]["value"]
            changed = float(np.mean([a != b for a, b in zip(candidate["response"]["decisions"],
                                    baseline["response"]["decisions"], strict=True)]))
            semantic_changed = float(np.mean([semantic_key(a) != semantic_key(b) for a, b in
                zip(candidate["response"]["decisions"], baseline["response"]["decisions"], strict=True)]))
            near(changed, semantic_changed)
            near(gain, candidate["development_gain"])
            near(clean_change, candidate["development_clean_change"])
            near(probe_change, candidate["clean_probe_change"])
            near(changed, candidate["response_decision_change_fraction"])
            assert candidate["zero_effect_initialization_exact"] is True
            assert candidate["base_unchanged"] is True
            assert candidate["gradient_examples"] == recipe["steps"] * protocol["batch_size"]
            assert candidate["history"][0]["step"] == 0
            assert candidate["history"][-1]["step"] == recipe["steps"]
            near(candidate["history"][0]["response_value"], baseline["response"]["value"])
            near(candidate["history"][-1]["response_value"], candidate["response"]["value"])
            candidate_values.append(candidate["response"]["value"])
            candidate_statistics.append({"seed": seed, "recipe": recipe["name"], "gain": gain,
                                         "clean_change": clean_change, "decision_change_fraction": changed})
        near(float(np.ptp(candidate_values)), block["response_candidate_range"])
    first_seed = protocol["seeds"][0]
    assert all(source_ids[seed] == source_ids[first_seed] for seed in protocol["seeds"])

    rankings = []
    for index, recipe in enumerate(protocol["candidates"]):
        candidates = [result["results"][str(seed)]["candidates"][index] for seed in protocol["seeds"]]
        passed = all(not x.get("failed") for x in candidates)
        eligible = passed and all(x["development_gain"] >= protocol["ordinary_gate"]["minimum_each_seed_gain"]
            and x["development_clean_change"] >= protocol["ordinary_gate"]["minimum_each_seed_development_clean_change"]
            for x in candidates)
        mean_gain = float(np.mean([x["development_gain"] for x in candidates])) if passed else None
        rankings.append({"name": recipe["name"], "index": index, "eligible": eligible, "mean_gain": mean_gain})
    assert rankings == result["rankings"]
    eligible = [x for x in rankings if x["eligible"]]
    selected = max(eligible, key=lambda x: (x["mean_gain"], -x["index"])) if eligible else None
    assert selected == result["selected"]
    actuator = selected is not None and all(
        block["response_candidate_range"] >= protocol["actuator_gate"]["minimum_per_seed_candidate_value_range"]
        and block["candidates"][selected["index"]]["response_decision_change_fraction"] >=
        protocol["actuator_gate"]["minimum_per_seed_selected_semantic_or_image_decision_change_fraction"]
        for block in result["results"].values())
    ordinary = selected is not None and selected["mean_gain"] >= protocol["ordinary_gate"]["minimum_pooled_development_gain"]
    assert bool(actuator) == result["actuator_identified"]
    assert bool(ordinary) == result["ordinary_qualified"]
    assert bool(actuator and ordinary) == result["allowed_to_fit_field"]
    return {"schema": "hepta.field-bridge.v2.pilot-independent-arithmetic.1", "status": "pass",
        "result_sha256": digest(result_path), "source_files_unchanged": len(freeze["files"]),
        "source_ids_disjoint_across_response_clean_selection": True,
        "raw_caption_change_counts_equal_parsed_semantic_change_counts": True,
        "seed_panels_share_same_underlying_source_ids": True,
        "recomputed_candidate_statistics": candidate_statistics, "rankings": rankings,
        "selected": selected, "actuator_identified": bool(actuator), "ordinary_qualified": bool(ordinary),
        "allowed_to_fit_field": bool(actuator and ordinary), **counts,
        "scope": "Arithmetic/source-identity review of recorded development data; no model generation or new efficacy claim",
        "auditor_source_sha256": digest(__file__)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.run_dir)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"recomputed_candidate_statistics", "rankings"}}))


if __name__ == "__main__":
    main()
