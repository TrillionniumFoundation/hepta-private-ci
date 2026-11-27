"""Descriptive paired contrasts for every predeclared mechanism ablation.

This reporting supplement reuses the frozen comparison/bootstrap functions.
It changes neither the primary comparator nor its acceptance rule, and makes
no additional confirmatory or family-wise significance claim.
"""

from pathlib import Path
import json

from .aggregate import (BOOTSTRAP_SEEDS, DATASETS, PairedBootstrap, compare,
                        group_layout, load_block, paired_counterfactual,
                        selected_checkpoints)
from .prepare_data import load_data, sha, write_once


ROOT = Path(__file__).resolve().parent
ABLATIONS = ("fp_no_rollover", "rr_mean_maturity", "rr_shuffle_maturity",
             "rr_fixed_boundary", "rr_frozen_resource")


def run():
    design_path = ROOT/"mechanism_reporting_design.json"
    design = json.loads(design_path.read_text())
    if design["reporter_sha256"] != sha(__file__):
        raise ValueError("The reporting supplement differs from its declared design")
    matrix = json.loads((ROOT/"results/evaluation_matrix_status.json").read_text())
    if not matrix["all_completed"]:
        raise ValueError("All original evaluations must complete before reporting contrasts")
    main_path = ROOT/"results/aggregate.json"
    main = json.loads(main_path.read_text())
    freeze_path, selection_path = ROOT/"pre_data_freeze.json", ROOT/"selection.json"
    freeze_hash, selection_hash = sha(freeze_path), sha(selection_path)
    frozen = json.loads(freeze_path.read_text())
    for name, digest in frozen["source_sha256"].items():
        if sha(ROOT/name) != digest:
            raise ValueError("A frozen implementation used by the supplement has changed")
    for name in ("selection.json", "pre_data_freeze.json", "experiment_protocol.json"):
        if main["sources_sha256"].get(name) != sha(ROOT/name):
            raise ValueError("Main aggregate identity differs from the reporting supplement")
    predeclared = frozen["mechanism_controls"]["ablations"]
    if list(ABLATIONS) != predeclared:
        raise ValueError("The complete predeclared ablation set must be retained")
    checkpoints = selected_checkpoints(json.loads(selection_path.read_text()))
    sources = {}
    result = {"schema": "rrsnn.v4-descriptive-mechanism-contrasts.1",
              "reporter_sha256": sha(__file__), "main_aggregate_sha256": sha(main_path),
              "reporting_design_sha256": sha(design_path),
              "pre_data_protocol_sha256": freeze_hash, "selection_sha256": selection_hash,
              "all_predeclared_ablations_reported": list(ABLATIONS),
              "primary_acceptance_changed": False,
              "scope": "Post-freeze descriptive reporting supplement for all predeclared ablation families; uses frozen paired comparison/bootstrap code and its original seeds/draws. No comparator, checkpoint, task or primary gate is changed. No additional confirmatory or family-wise significance claim.",
              "sign": "Every contrast is rr_full minus the named ablation.",
              "datasets": {}, "sources_sha256": sources}
    for dataset in DATASETS:
        scenarios, arrays, metadata, manifest = load_data(dataset, freeze_path)
        groups, indices = group_layout(metadata, dataset == "paired")
        bootstrap = PairedBootstrap(len(groups), BOOTSTRAP_SEEDS[dataset])
        context = (scenarios, metadata, arrays["oracle_utility"], manifest, freeze_path)
        blocks = {name: load_block(name, checkpoints[name], dataset, context,
                                   selection_hash, freeze_hash, sources)
                  for name in ("rr_full", *ABLATIONS)}
        entry = {"full_minus_ablation": {name: compare(blocks["rr_full"], blocks[name],
                                                        indices, bootstrap)
                                         for name in ABLATIONS}}
        if dataset == "paired":
            interactions = {name: paired_counterfactual(block, metadata, bootstrap)[1]
                            for name, block in blocks.items()}
            entry["shock_interaction_full_minus_ablation"] = {
                name: bootstrap.summary(interactions["rr_full"]-interactions[name])
                for name in ABLATIONS}
        result["datasets"][dataset] = entry
    for name, digest in sources.items():
        if main["sources_sha256"].get(name) != digest:
            raise ValueError("Supplement does not use the exact main-table evidence")
    path = ROOT/"results/mechanism_contrasts.json"
    write_once(path, (json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n").encode())
    return result


if __name__ == "__main__":
    report = run()
    print(json.dumps({"datasets": list(report["datasets"]),
                      "ablations": list(ABLATIONS), "scope": report["scope"]}))
