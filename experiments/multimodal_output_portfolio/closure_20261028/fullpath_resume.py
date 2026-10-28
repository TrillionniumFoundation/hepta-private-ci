"""Resume only complete arms after an explicit shared-resource interruption.

No interrupted optimizer state is approximated. Completed arms are inherited
byte-for-byte; every missing arm starts from its original prior and seed.
"""

import argparse
import json
from pathlib import Path
import platform
import shutil

import numpy as np
import torch

from ..v6.plan_training import ControlledSnapshot
from ..continuation_20261027.joint.data import historical_corpus
from ..continuation_20261027.joint.run import reference_observer
from ..unified_20261028.profile import digest
from .fullpath_model import file_sha
from .fullpath_protocol import P, profiles, write_json
from .fullpath_train import fit


def inherited_arms(original):
    runtime = json.loads((original / "RUNTIME.json").read_text())
    protocol = json.loads((original / "PROTOCOL.json").read_text())
    if protocol.pop("smoke_only") or digest(protocol) != digest(P):
        raise ValueError("Only the same non-smoke preregistered study can resume")
    if runtime["qualification_predictions"] or (original / "QUALIFICATION_CLAIM.json").exists():
        raise ValueError("A qualification-consumed study cannot become new development")
    interruption = json.loads((original / "RESOURCE_INTERRUPTION.json").read_text())
    if interruption.get("changes_to_model_law_hyperparameters_sources_or_gates") is not False:
        raise ValueError("A resource-only interruption record is required")
    for name, expected in interruption["boundary_files"].items():
        if file_sha(original / name) != expected:
            raise ValueError("Completed boundary evidence changed")
    package = Path(__file__).resolve().parent
    for name, expected in runtime["executed_source_sha256"].items():
        if file_sha(package / name) != expected or file_sha(original / "executed-source" / name) != expected:
            raise ValueError("Training or qualification semantics changed during the interruption")
    inherited = {}
    freeze_path = original / "RESOURCE_RESUME_FREEZE.json"
    if freeze_path.exists():
        if file_sha(freeze_path) != runtime["resume_freeze_sha256"]:
            raise ValueError("An inherited resource-continuation freeze changed")
        previous = json.loads(freeze_path.read_text())
        if file_sha(Path(previous["original_development"]) / "RESOURCE_INTERRUPTION.json") != previous["original_interruption_sha256"]:
            raise ValueError("The prior complete-arm boundary identity changed")
        for entry in previous["completed_arms"]:
            record_path, selection_path = Path(entry["training_record"]), Path(entry["selection_record"])
            if file_sha(record_path) != entry["training_record_sha256"] or file_sha(selection_path) != entry["selection_record_sha256"]:
                raise ValueError("A transitively inherited arm changed")
            inherited[(entry["seed"], entry["arm"])] = (json.loads(record_path.read_text()),
                                                       json.loads(selection_path.read_text()), entry)
    for seed in P["training_seeds"]:
        for arm in P["arms"]:
            directory = original / f"seed-{seed}-{arm}"
            record_path, selection_path = directory / "TRAINING.json", directory / "validation/SELECTION.json"
            if not record_path.exists() or not selection_path.exists():
                continue
            record, selection = json.loads(record_path.read_text()), json.loads(selection_path.read_text())
            if (record["training_counts"]["optimizer_steps"] != 4 * P["steps_per_stage"]
                    or record["seed"] != seed or record["arm"] != arm or selection["seed"] != seed):
                raise ValueError("Incomplete or incorrectly identified arm at resume boundary")
            for candidate in selection["candidates"]:
                if candidate["path"] and file_sha(candidate["path"]) != candidate["checkpoint_sha256"]:
                    raise ValueError("A completed candidate checkpoint changed")
            inherited[(seed, arm)] = (record, selection, {"seed": seed, "arm": arm,
                "training_record": str(record_path), "training_record_sha256": file_sha(record_path),
                "selection_record": str(selection_path), "selection_record_sha256": file_sha(selection_path)})
    ordered = [(seed, arm) for seed in P["training_seeds"] for arm in P["arms"]]
    if not inherited or set(inherited) != set(ordered[:len(inherited)]):
        raise ValueError("Resource resume must preserve a complete execution-order prefix, without selecting arms by performance")
    for (seed, arm), (record, selection, _) in inherited.items():
        if (record["seed"] != seed or record["arm"] != arm or selection["seed"] != seed
                or record["training_counts"]["optimizer_steps"] != 4 * P["steps_per_stage"]):
            raise ValueError("An inherited arm is incomplete or misidentified")
        for candidate in selection["candidates"]:
            if candidate["path"] and file_sha(candidate["path"]) != candidate["checkpoint_sha256"]:
                raise ValueError("An inherited checkpoint changed")
    return inherited, runtime


def resume(assets, baseline, original, output, oracle):
    completed, old_runtime = inherited_arms(original)
    if file_sha(baseline) != P["reference_checkpoint_sha256"]:
        raise ValueError("The strong inherited prior changed")
    package = Path(__file__).resolve().parent
    proof = json.loads(oracle.read_text())
    if not proof["passed"] or proof["source_sha256"] != {name: file_sha(package / name) for name in proof["source_sha256"]}:
        raise ValueError("The independent estimator or density oracle changed")
    primary, mean, semantics = profiles(assets / "ndu-runs/full-002/reward-observer.pt")
    if (digest(semantics) != digest(json.loads((original / "SEMANTICS.json").read_text()))
            or digest(primary.to_dict()) != digest(json.loads((original / "PROFILE.json").read_text()))
            or digest(mean.to_dict()) != digest(json.loads((original / "MEAN_CONTROL_PROFILE.json").read_text()))):
        raise ValueError("The original objective and deployment law must remain exact")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("PROTOCOL.json", "PROFILE.json", "MEAN_CONTROL_PROFILE.json", "SEMANTICS.json", "SOURCE_ALLOCATION.json"):
        shutil.copyfile(original / name, output / name)
    names = list(dict.fromkeys([*old_runtime["executed_source_sha256"], "fullpath_resume.py"]))
    (output / "executed-source").mkdir()
    for name in names:
        shutil.copyfile(package / name, output / "executed-source" / name)
    shutil.copyfile(oracle, output / "INDEPENDENT_GRADIENT_ORACLE.json")
    write_json(output / "RESOURCE_RESUME_FREEZE.json", {"schema": "hepta.ndu.fullpath-complete-arm-resume.v1",
        "original_development": str(original.resolve()),
        "original_interruption_sha256": file_sha(original / "RESOURCE_INTERRUPTION.json"),
        "source_allocation_sha256": file_sha(original / "SOURCE_ALLOCATION.json"),
        "completed_arms": [value[2] for value in completed.values()],
        "remaining_arms": [[seed, arm] for seed in P["training_seeds"] for arm in P["arms"] if (seed, arm) not in completed],
        "total_effective_optimizer_steps": 6144, "new_effective_optimizer_steps": (6 - len(completed)) * 4 * P["steps_per_stage"],
        "resource_pause": "an external PAUSE_AFTER_ARM file requests a normal return only after a complete saved arm",
        "resume_retrains_completed_arms": False, "approximate_optimizer_resume": False,
        "interrupted_partial_next_arm": "preserved as resource-interrupted overhead; never promoted or counted as a completed model path",
        "hyperparameter_objective_source_and_gate_changes": False, "qualification_predictions": 0})
    write_json(output / "RUNTIME.json", {"python": platform.python_version(), "torch": torch.__version__,
        "threads": P["threads"], "cuda": torch.cuda.is_available(), "baseline_sha256": file_sha(baseline),
        "executed_source_sha256": {name: file_sha(package / name) for name in names},
        "original_development": str(original.resolve()),
        "resume_freeze_sha256": file_sha(output / "RESOURCE_RESUME_FREEZE.json"),
        "audit_observer_loaded": False, "qualification_predictions": 0})
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    reference, observer = ControlledSnapshot.load(baseline), reference_observer(assets, "reward")
    corpus, selections, boundary_files = historical_corpus(assets), [], {}
    for seed in P["training_seeds"]:
        matched = []
        for arm, profile in (("lax_mean", mean), ("lax_risk", primary)):
            if (seed, arm) in completed:
                record, selection, _ = completed[(seed, arm)]
                if record["profile_sha256"] != profile.digest:
                    raise ValueError("Inherited training objective differs")
            else:
                record, selection = fit(reference, corpus, observer, profile, primary, seed, arm,
                                        output / f"seed-{seed}-{arm}")
            selections.append({"arm": arm, **selection}); matched.append(record)
            if (seed, arm) not in completed:
                for relative in (f"seed-{seed}-{arm}/TRAINING.json", f"seed-{seed}-{arm}/validation/SELECTION.json"):
                    boundary_files[relative] = file_sha(output / relative)
                if (output / "PAUSE_AFTER_ARM").exists():
                    write_json(output / "RESOURCE_INTERRUPTION.json", {
                        "schema": "hepta.ndu.resource-boundary-watch.v1", "boundary_files": boundary_files,
                        "changes_to_model_law_hyperparameters_sources_or_gates": False,
                        "effective_completed_optimizer_steps": len(selections) * 4 * P["steps_per_stage"],
                        "remaining_prespecified_optimizer_steps": (6 - len(selections)) * 4 * P["steps_per_stage"],
                        "interruption_signal": "normal return at requested complete-arm boundary", "qualification_predictions": 0})
                    print(json.dumps({"resource_pause": True, "completed_arms": len(selections)}), flush=True)
                    return
        for field in ("schedule_sha256", "training_counts", "before_modules"):
            if matched[0][field] != matched[1][field]:
                raise ValueError(f"Matched inherited/new training arms differ: {field}")
    write_json(output / "SELECTIONS.json", selections)
    risks = [row for row in selections if row["arm"] == "lax_risk"]
    means = {row["seed"]: row for row in selections if row["arm"] == "lax_mean"}
    gains = {"greedy": [], "same_law": [], "matched_mean": []}
    for row in risks:
        gains["greedy"].append(row["selected"]["quality_ce"] - row["candidates"][0]["quality_ce"])
        gains["same_law"].append(row["selected"]["quality_ce"] - row["candidates"][1]["quality_ce"])
        gains["matched_mean"].append(row["selected"]["quality_ce"] - means[row["seed"]]["selected"]["quality_ce"])
    gate = {"risk_gain_vs_greedy": float(np.mean(gains["greedy"])) >= .002,
            "risk_gain_vs_same_law": float(np.mean(gains["same_law"])) >= .002,
            "risk_gain_vs_matched_mean": float(np.mean(gains["matched_mean"])) >= 0,
            "at_least_one_learned_risk_selection": any(row["selected"]["path"] for row in risks),
            "retention_all_selected": all(row["selected"]["eligible"] for row in risks), "not_smoke": True}
    write_json(output / "DEVELOPMENT_SEAL.json", {"profile_sha256": primary.digest,
        "protocol_sha256": file_sha(output / "PROTOCOL.json"), "selection_sha256": file_sha(output / "SELECTIONS.json"),
        "source_allocation_sha256": file_sha(output / "SOURCE_ALLOCATION.json"),
        "resource_resume_freeze_sha256": file_sha(output / "RESOURCE_RESUME_FREEZE.json"),
        "smoke_only": False, "qualification_predictions": 0, "admission_checks": gate,
        "development_gains": gains, "qualification_admitted": all(gate.values())})
    print(json.dumps({"development_admission": gate, "gains": gains}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "baseline", "original", "output", "oracle"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    resume(args.assets, args.baseline, args.original, args.output, args.oracle)
