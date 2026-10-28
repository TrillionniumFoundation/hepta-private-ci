"""Summarize a completed sealed LAX development study without loading a model."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize(development, output):
    development = Path(development)
    seal, protocol = read(development / "DEVELOPMENT_SEAL.json"), read(development / "PROTOCOL.json")
    for key, name in (("protocol_sha256", "PROTOCOL.json"), ("selection_sha256", "SELECTIONS.json"),
                      ("source_allocation_sha256", "SOURCE_ALLOCATION.json")):
        if seal[key] != sha(development / name):
            raise ValueError("Completed development evidence differs from its seal")
    if seal["smoke_only"] or seal["qualification_predictions"] != 0:
        raise ValueError("Only the full untouched-qualification development study is summarized here")
    selections = read(development / "SELECTIONS.json")
    expected = {(seed, arm) for seed in protocol["training_seeds"] for arm in protocol["arms"]}
    if len(selections) != len(expected) or {(row["seed"], row["arm"]) for row in selections} != expected:
        raise ValueError("The completed matched study omitted a prespecified arm")
    inherited = {}
    freeze = development / "RESOURCE_RESUME_FREEZE.json"
    if freeze.exists():
        if seal["resource_resume_freeze_sha256"] != sha(freeze):
            raise ValueError("The complete-arm resource continuation changed")
        inherited = {(row["seed"], row["arm"]): row for row in read(freeze)["completed_arms"]}
    arms, counts, total_cpu, total_wall, matched = [], {}, 0, 0, {}
    for selection in selections:
        seed, arm = selection["seed"], selection["arm"]
        if (seed, arm) in inherited:
            record_path = Path(inherited[(seed, arm)]["training_record"])
            if sha(record_path) != inherited[(seed, arm)]["training_record_sha256"]:
                raise ValueError("An inherited training record changed")
        else:
            record_path = development / f"seed-{seed}-{arm}" / "TRAINING.json"
        record = read(record_path)
        if record["training_counts"]["optimizer_steps"] != len(protocol["stages"]) * protocol["steps_per_stage"]:
            raise ValueError("A supposedly completed arm has a shortened optimizer budget")
        all_nonzero = all(math.isfinite(value) and value > 0 for stage in record["stages"]
                          for value in stage["actual_objective_gradient_norm_sum"].values())
        opened = record["stages"][-1]["enabled_modules"]
        every_final_path_changed = all(record["before_modules"][name] != record["after_modules"][name]
                                       for name in opened)
        auxiliary = [name for name in record["before_modules"] if name not in opened]
        if not all_nonzero or not every_final_path_changed:
            raise ValueError("The declared opened paths lack actual objective gradients or parameter changes")
        for key, value in record["training_counts"].items():
            counts[key] = counts.get(key, 0) + value
        total_cpu += record["cpu_ns"]; total_wall += record["wall_ns"]
        matched.setdefault(seed, []).append(record)
        prior, same_law = selection["candidates"][:2]
        selected = selection["selected"]
        arms.append({"seed": seed, "arm": arm, "selected_stage": selected["stage"],
            "selected_checkpoint_sha256": selected.get("checkpoint_sha256"),
            "selected_emission_mode": "greedy_prior" if selected["deterministic"] else "stochastic",
            "quality_ce": selected["quality_ce"], "retention_ce": selected["retention_ce"],
            "quality_gain_vs_strong": selected["quality_ce"] - prior["quality_ce"],
            "quality_gain_vs_same_law": selected["quality_ce"] - same_law["quality_ce"],
            "retention_difference_vs_strong": selected["retention_ce"] - prior["retention_ce"],
            "all_opened_module_gradient_sums_positive": all_nonzero,
            "all_opened_generation_modules_changed": every_final_path_changed,
            "opened_generation_module_count": len(opened), "total_model_module_count": len(record["before_modules"]),
            "unopened_auxiliary_modules": auxiliary,
            "auxiliary_parameters_unchanged": all(record["before_modules"][name] == record["after_modules"][name] for name in auxiliary),
            "stage_gradients": [{"stage": stage["stage"], "module_norm_sums": stage["actual_objective_gradient_norm_sum"]}
                               for stage in record["stages"]],
            "training_record_sha256": sha(record_path), "candidates": selection["candidates"]})
    for pair in matched.values():
        for field in ("schedule_sha256", "before_modules", "training_counts"):
            if len(pair) != 2 or pair[0][field] != pair[1][field]:
                raise ValueError("The compared mean/risk arms differ in initial state, work, or random schedule")
    means = {key: math.fsum(values) / len(values) for key, values in seal["development_gains"].items()}
    report = {"schema": "hepta.ndu.fullpath-lax-development-summary.v1",
        "profile_sha256": seal["profile_sha256"], "protocol_sha256": seal["protocol_sha256"],
        "source_allocation_sha256": seal["source_allocation_sha256"], "development_seal_sha256": sha(development / "DEVELOPMENT_SEAL.json"),
        "admission_checks": seal["admission_checks"], "qualification_admitted": seal["qualification_admitted"],
        "mean_selected_risk_development_gains": means, "per_seed_arm": arms,
        "total_effective_training_counts": counts, "effective_training_cpu_seconds": total_cpu / 1e9,
        "sum_arm_training_wall_seconds": total_wall / 1e9,
        "completed_arms_inherited_without_retraining": len(inherited),
        "resource_interrupted_partial_work_counted_as_completed_training": False,
        "training_includes_actual_control_variate_roundtrips": True,
        "all_matched_work_and_module_gradient_checks_passed": True,
        "new_qualification_predictions": 0,
        "fresh_qualification_success_established": False,
        "complete_physical_CPU_cost_certificate": False,
        "proxy_used_as_reward_or_selection_metric": False,
        "global_optimality_established": False,
        "summary_source_sha256": sha(__file__),
        "scope": "consumed development data under the frozen primary observer and work tariff; fresh qualification is separate and gated"}
    with Path(output).open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False); stream.write("\n")
    print(json.dumps({key: report[key] for key in ("admission_checks", "qualification_admitted", "mean_selected_risk_development_gains",
                                                 "effective_training_cpu_seconds")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summarize(args.development, args.output)
