"""Post-run descriptive diagnostics; never fit, select, or modify a candidate.

Oracle routing is labelled as an unavailable-information diagnostic. Repeated
seeds and related version snapshots are never counted as independent requests.
"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from adapter import Adapter
from baselines import wording_audit
import tasks


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   indent=2, allow_nan=False) + "\n")


def paired(left, right):
    a = {row["id"]: row for row in left["predictions"]}
    b = {row["id"]: row for row in right["predictions"]}
    if a.keys() != b.keys():
        raise ValueError("Unpaired evaluation requests")
    return {"requests": len(a),
            "left_only_correct": sum(a[k]["correct"] and not b[k]["correct"] for k in a),
            "right_only_correct": sum(b[k]["correct"] and not a[k]["correct"] for k in a),
            "both_correct": sum(a[k]["correct"] and b[k]["correct"] for k in a),
            "both_incorrect": sum(not a[k]["correct"] and not b[k]["correct"] for k in a)}


def route_diagnostic(directory, name, features, rows):
    network = read(directory / name / "network.json")
    experts = [Adapter.load(directory / name / f"expert-{i}.npz")
               for i in range(len(network["partition"]))]
    router = np.load(directory / name / "router.npy", allow_pickle=False)
    scores = np.column_stack([features, np.ones(len(features))]) @ router
    choices = np.argsort(-scores, axis=1, kind="stable")[:, :network["top_k"]]
    group_for = {label: group for group, labels in enumerate(network["partition"])
                 for label in labels}
    actual = {row["id"]: row for row in read(directory / f"test-{name}.json")["predictions"]}
    diagnostic = []
    for index, row in enumerate(rows):
        group = group_for[row["label"]]
        local = int(experts[group].predict(features[index:index + 1])[0])
        oracle_label = network["partition"][group][local]
        oracle = tasks.score_prediction(row, oracle_label)
        diagnostic.append({"id": row["id"], "true_group": group,
                           "chosen_groups": choices[index].tolist(),
                           "true_group_in_top_k": bool(group in choices[index]),
                           "unavailable_oracle_label": oracle_label,
                           "unavailable_oracle_correct": oracle["correct"],
                           "actual_prediction": actual[row["id"]]["prediction"],
                           "actual_correct": actual[row["id"]]["correct"]})
    return {"requests": len(rows),
            "true_group_coverage": sum(row["true_group_in_top_k"] for row in diagnostic),
            "oracle_diagnostic_correct": sum(row["unavailable_oracle_correct"] for row in diagnostic),
            "actual_correct": sum(row["actual_correct"] for row in diagnostic),
            "oracle_uses_gold_label": True, "oracle_is_not_an_achieved_result": True,
            "no_selection_or_training_uses_this_analysis": True, "rows": diagnostic}


def main():
    evidence = ROOT / "evidence"
    run = evidence / "run"
    inputs = evidence / "inputs"
    directory = Path(__file__).resolve().parent
    results = read(run / "RESULTS.json")
    rows = read(inputs / "test_rows.json")
    with np.load(inputs / "test_features.npz", allow_pickle=False) as saved:
        features = saved["X"]
    wording = wording_audit(read(inputs / "train_rows.json"), rows)
    write(directory / "WORDING.json", wording)
    seeds, routes = [], {}
    for seed in results["results"]:
        base = run / f"seed-{seed['seed']}"
        selection = read(base / "SELECTION.json")
        initial = read(base / "test-single.json")
        final = read(base / "frontier-6/retention-replay.json")
        by_skill = {}
        for left, right in zip(initial["predictions"], final["predictions"]):
            if left["id"] != right["id"]:
                raise ValueError("Retention order changed")
            skill = left["expected_skill"]
            row = by_skill.setdefault(skill, dict(before=0, after=0, lost=0, gained=0, total=0))
            row["before"] += int(left["correct"])
            row["after"] += int(right["correct"])
            row["lost"] += int(left["correct"] and not right["correct"])
            row["gained"] += int(right["correct"] and not left["correct"])
            row["total"] += 1
        pairs = {name: paired(read(base / f"test-{name}.json"), initial)
                 for name in ("ridge", "nearest", "centroid", "continue", "wide",
                              "fixed", "random", "learned", "interference")}
        seeds.append({"seed": seed["seed"], "selected": seed["selected"],
                      "calibration_correct": {name: value["correct"] for name, value in selection["validation"].items()},
                      "test_correct": {name: value["correct"] for name, value in seed["test"].items()},
                      "paired_vs_single": pairs,
                      "final_retention_paired": paired(initial, final),
                      "retention_by_skill": by_skill,
                      "corrected_project_profiles": [{"frontier": phase["frontier"],
                           "replay": phase["profile"]["replay"]["correct"],
                           "no_replay": phase["profile"]["no_replay"]["correct"],
                           "frozen": phase["profile"]["frozen"]["correct"],
                           "exact_kv": phase["profile"]["profile_exact"]["correct"],
                           "retention_replay": phase["retention"]["replay"]["correct"],
                           "retention_no_replay": phase["retention"]["no_replay"]["correct"]}
                           for phase in seed["updates"]]})
        routes[str(seed["seed"])] = {name: route_diagnostic(base, name, features, rows)
                                    for name in ("fixed", "random", "learned", "interference")}
    write(directory / "ROUTING_DIAGNOSTIC.json", routes)
    costs = read(run / "LATENCY_COST.json")
    setup = costs["setup"]
    summary = costs["summaries"]
    scenarios = {}
    for name in summary:
        neural = name not in ("bm25", "exact_store")
        if name == "single_adapter":
            build = costs["training_evidence"]["receipts"]["single"]["seconds"]
            build += setup["adapter_checkpoint_load"]["wall_seconds"]
        else:
            build = setup["index_build_or_ridge_fit"][name]["wall_seconds"]
        if neural:
            build += setup["encoder_stats"]["load_seconds"]
            build += setup["train_feature_encoding"]["wall_seconds"]
        per_request = summary[name]["measurements"]["total_wall_ms"]["mean"] / 1000
        scenarios[name] = {
            "quality_correct_of_72": summary[name]["unique_correct"],
            "measured_startup_build_components_seconds": build,
            "observed_mean_request_seconds": per_request,
            "component_seconds_at_reads": {str(n): build + n * per_request
                                           for n in (100, 1000, 10000, 100000)},
            "assumptions": "serial warm requests drawn from the observed task distribution; one model generation",
            "is_complete_economic_cost": False,
            "omitted_costs": ["source ingestion", "checkpoint serialization", "updates and failed candidates",
                              "RAM pricing", "network", "queueing", "recovery", "energy"]}
    write(directory / "COST_SCENARIOS.json", scenarios)
    output = {"schema": "hepta.memory-cell-v13.postrun-analysis.v1",
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "seeds": seeds, "held_requests": len(rows),
              "repeated_seeds_do_not_multiply_sample_size": True,
              "wording_summary": {k: v for k, v in wording.items() if k != "pairs"},
              "claims": {"finite_parametric_binding_demonstrated": True,
                         "old_skill_retention_preserved": False,
                         "complete_cost_positive_task_found": False,
                         "specialized_cells_exclusive_advantage": False,
                         "beneficial_learned_split_demonstrated": False,
                         "general_memory_emergence_demonstrated": False},
              "cross_node_result": "See migration-local and migration-ci receipts; not inferred from local analysis."}
    write(directory / "ANALYSIS.json", output)
    print(json.dumps({"seeds": len(seeds), "held_requests": len(rows),
                      "claim_status": output["claims"]}, sort_keys=True))


if __name__ == "__main__":
    main()
