"""Bind the strong success reference and reserve a wholly new source role."""

import argparse
import json
from pathlib import Path
import time

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_next.settings import MANIFEST, MANIFEST_SHA, REPO, SEEDS, model_path, OBSERVER_SHA
from ...v7.data import VIEWS
from ..training.train import PLAN, source_pins as original_training_pins


HERE = Path(__file__).parent
PRIOR = HERE.parent / "training"
RUNS = REPO.parent / "abc4-repair-runs"
ARMS = ("matched_floor", "matched_floor_warmdual")
ALL_ARMS = ("mean", "old_constraint", *ARMS)
INITIAL_DUAL = {"matched_floor": 0., "matched_floor_warmdual": 1.}


def source_pins():
    result = original_training_pins()
    for path in [HERE / (name + ".py") for name in ("protocol", "train", "evaluate", "analysis", "allocation_audit", "assigned_source")]:
        result[str(path.relative_to(REPO))] = file_sha(path)
    for path in (PRIOR / "evaluate.py", REPO / "experiments/multimodal_output_portfolio/abc_recovery/statistics.py"):
        result[str(path.relative_to(REPO))] = file_sha(path)
    return result


def baseline_models():
    prior = json.loads((PRIOR / "TRAINING_RESULTS.json").read_text())
    if prior["status"] != "completed":
        raise ValueError("Strong reference has not finished training")
    models = {}
    for seed in SEEDS:
        entries = {}
        for name, arm in (("mean", "mean"), ("old_constraint", "risk_success")):
            rows = [r for r in prior["models"] if (r["seed"], r["arm"]) == (seed, arm)]
            if len(rows) != 1 or file_sha(rows[0]["model_path"]) != rows[0]["model_file_sha256"]:
                raise ValueError("Missing or changed matched baseline")
            entries[name] = {"path": rows[0]["model_path"], "sha256": rows[0]["model_file_sha256"]}
        warm = model_path(seed, "output_mean")
        entries["warm"] = {"path": str(warm), "sha256": file_sha(warm)}
        models[str(seed)] = entries
    return models


def source_identity():
    manifest = json.loads(MANIFEST.read_text())
    allocation_path = HERE / "SOURCE_ALLOCATION.json"
    allocation = json.loads(allocation_path.read_text())
    import hashlib
    ids = manifest["roles"]["unallocated_test"]["source_ids"]
    digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    # The supplement is independently audited before this protocol is frozen.
    selected = allocation["allocation"]
    excluded = allocation["all_other_manifest_roles_excluded"]
    other_roles = set(manifest["roles"]) - {"unallocated_test"}
    pixels = {value.rsplit(":", 1)[1] for value in ids}
    if (file_sha(MANIFEST) != MANIFEST_SHA or allocation["manifest_sha256"] != MANIFEST_SHA
            or len(ids) != 2000 or len(set(ids)) != 2000
            or len(pixels) != 2000 or {r["role"] for r in excluded} != other_roles
            or selected["source_role"] != "unallocated_test" or selected["source_pairs"] != 1000
            or selected["ordered_source_ids_sha256"] != digest
            or selected["pair_start"] != 0 or selected["pair_end_exclusive"] != 1000
            or any(r["individual_id_overlap"] or r["pixel_sha256_overlap"]
                   for r in allocation["all_other_manifest_roles_excluded"])
            or allocation["metadata_scan"]["candidate_individual_id_overlap"]
            or allocation["metadata_scan"]["candidate_pixel_sha256_overlap"]
            or allocation["audit_code_sha256"] != file_sha(HERE / "allocation_audit.py")):
        raise ValueError("New-source allocation is not the complete unallocated test role")
    for role in other_roles:
        others = manifest["roles"][role]["source_ids"]
        if set(ids) & set(others) or pixels & {v.rsplit(":", 1)[1] for v in others}:
            raise ValueError("Reserved original images overlap another role")
    return selected


def freeze(path, output, steps=400, seeds=SEEDS):
    from .assigned_source import ASSIGNMENT, verify_assignment
    if steps < 1 or not set(seeds) <= set(SEEDS):
        raise ValueError("Invalid training budget or seed")
    identity = source_identity()
    verify_assignment()
    prior = json.loads((PRIOR / "RESULTS.json").read_text())
    if prior["primary_conjunction_passed"]:
        raise ValueError("This protocol explicitly follows the documented failed conjunction")
    write_json(path, {"schema": "hepta.abc4.success-reference-repair-training.v1",
        "unix_ns": time.time_ns(), "output": str(output.resolve()),
        "steps": steps, "seeds": list(seeds), "arms": ARMS,
        "conditions": 16, "scenarios": 8, "threads": 2,
        "learning_rate": .0001, "gamma": 2., "auxiliary_weight": .05,
        "dual_initial": INITIAL_DUAL, "dual_rate": .1, "dual_cap": 5.,
        "plan": PLAN, "source_role": "train", "manifest_sha256": MANIFEST_SHA,
        "source_sha256": source_pins(), "baselines": baseline_models(),
        "source_allocation_sha256": file_sha(HERE / "SOURCE_ALLOCATION.json"),
        "role_assignment_sha256": file_sha(ASSIGNMENT),
        "prospective_source_identity": identity,
        "prior_results_sha256": file_sha(PRIOR / "RESULTS.json"),
        "prior_training_results_sha256": file_sha(PRIOR / "TRAINING_RESULTS.json"),
        "prior_evaluation_protocol_sha256": file_sha(PRIOR / "EVALUATION_PROTOCOL.json"),
        "prior_failed_final_retained": True,
        "adaptation": "New research round motivated by the prior failed final; never relabel or overwrite that evaluation. No prior final rows enter gradient fitting.",
        "constraint": "candidate failure probability <= fixed same-seed new mean failure probability; zero margin",
        "reference_selection": "the already frozen same-seed mean continuation, trained only on train sources; no new-source selection",
        "identification": "matched_floor vs old_constraint changes reference only; warmdual vs matched_floor changes initial dual only",
        "gradient": "risk F_gamma plus .05 supervised plus predictable lambda_old*actual_failure; update dual only for next batch",
        "matched_rng": "same batch/candidate/reference draw schedules as the prior 400-step three-arm study",
        "model_selection": "last fixed update; no outcome checkpoint selection",
        "primary_candidate": "matched_floor_warmdual", "primary_reference": "mean",
        "primary_gate": "joint CE lower97.5>0 AND exact-success difference lower97.5>=0; zero margin",
        "other_comparisons": "descriptive95 only; cannot substitute another candidate for the prespecified primary",
        "formal_new_holdout_opened": False, "global_cross_round_error_control_claimed": False})
    print(json.dumps({"protocol": str(path), "sha256": file_sha(path)}), flush=True)


def verify(spec):
    from .assigned_source import ASSIGNMENT, verify_assignment
    verify_assignment()
    if (spec["schema"] != "hepta.abc4.success-reference-repair-training.v1"
            or spec["source_sha256"] != source_pins()
            or spec["manifest_sha256"] != file_sha(MANIFEST)
            or spec["baselines"] != baseline_models()
            or spec["source_allocation_sha256"] != file_sha(HERE / "SOURCE_ALLOCATION.json")
            or spec["role_assignment_sha256"] != file_sha(ASSIGNMENT)
            or spec["prospective_source_identity"] != source_identity()
            or spec["prior_results_sha256"] != file_sha(PRIOR / "RESULTS.json")
            or spec["prior_training_results_sha256"] != file_sha(PRIOR / "TRAINING_RESULTS.json")
            or spec["prior_evaluation_protocol_sha256"] != file_sha(PRIOR / "EVALUATION_PROTOCOL.json")
            or spec["dual_initial"] != INITIAL_DUAL or tuple(spec["arms"]) != ARMS
            or tuple(spec["plan"]) != PLAN or spec["source_role"] != "train"):
        raise ValueError("Repair source, baseline or protocol identity changed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=RUNS / "training-001")
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    args = parser.parse_args()
    freeze(args.protocol, args.output, args.steps, args.seeds)
