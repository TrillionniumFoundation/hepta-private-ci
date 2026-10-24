"""Fit a separately pinned 15/15 artifact; never relabel 3/3 scientific results."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from ..v7_media.endpoint import four_modal_labeler
from .evaluation import load_reward
from .forecast import CategoricalForecast
from .forecast_data import collect_scenarios
from .forecast_fit import fit_forecast
from .plans import ControlledSnapshot
from .sources import canonical, load_roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "manifest", "model", "observer", "motion", "pcm-audit", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    module = Path(__file__).resolve().parent
    spec_path = module / "four_forecast_spec.json"
    spec = json.loads(spec_path.read_text())
    if hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest() != spec["source_manifest_file_sha256"]:
        raise ValueError("The independently audited source registration changed")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    used = {
        "v7": ("sources", "data", "model", "snapshot", "plans", "metric", "evaluation", "forecast", "forecast_data", "forecast_fit", "forecast_four_modal"),
        "v6": ("data", "neural", "observer", "plan_training"),
        "v7_media": ("endpoint", "audit", "media", "models", "motion", "pcm_audit"),
    }
    sources = [module.parent / package / f"{name}.py" for package, names in used.items() for name in names] + [spec_path]
    pins = {str(path.relative_to(module.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    snapshot = ControlledSnapshot.load(args.model, expected_file_sha256=spec["generator_checkpoint_sha256"])
    observer, observer_record = load_reward(args.observer, spec["reward_observer_checkpoint_sha256"])
    labeler = four_modal_labeler(observer, observer_file_sha256=spec["reward_observer_checkpoint_sha256"],
                                 motion_path=args.motion, motion_file_sha256=spec["motion_checkpoint_sha256"],
                                 pcm_audit_path=args.pcm_audit, pcm_audit_sha256=spec["pcm_audit_sha256"])
    if (labeler.contract_sha256 != spec["expected_metric_contract_sha256"]
            or (labeler.contract.required_output_mask, labeler.contract.forecast_metric_mask) != (15, 15)):
        raise ValueError("The actual four-modal metric/producer contract differs from registration")
    corpus = load_roles(args.cache, args.manifest, tuple(spec["source_roles"]))
    if corpus.manifest["manifest_sha256"] != observer_record["source_manifest_sha256"]:
        raise ValueError("Frozen observer and fitting corpus source registration differ")
    stamp = {"schema": "hepta.ndu-v7.four-modal-forecast-run.v1", "source_sha256": pins,
             "specification": spec, "source_manifest_sha256": corpus.manifest["manifest_sha256"],
             "snapshot_sha256": snapshot.fingerprint, "metric_contract_sha256": labeler.contract_sha256,
             "required_output_mask": 15, "forecast_metric_mask": 15, "authority": "deny_all",
             "formal_holdout_or_neuron_calibration_access": False, "scientific_superiority_claim": False}
    (output / "status.json").write_bytes(canonical({**stamp, "status": "running"}) + b"\n")
    torch.set_num_threads(spec["threads"])
    started = time.perf_counter_ns()
    print(json.dumps({"stage": "collect_fit", "contract": labeler.contract_sha256}), flush=True)
    fitting = collect_scenarios(snapshot, corpus, "forecast_fit", labeler, spec["fit_pairs"], output / "fit",
                                scenarios=spec["fit_latent_scenarios"])
    print(json.dumps({"stage": "collect_calibration"}), flush=True)
    calibration = collect_scenarios(snapshot, corpus, "forecast_calibration", labeler, spec["calibration_pairs"],
                                    output / "calibration", scenarios=spec["calibration_latent_scenarios"])
    print(json.dumps({"stage": "fit_source_group_oof"}), flush=True)
    artifact, evidence = fit_forecast(snapshot, fitting, calibration, labeler.contract,
                                      seed=spec["training_seed"], steps=spec["steps_per_fit"],
                                      folds=spec["source_pair_oof_folds"], batch_size=spec["batch_size"],
                                      alpha=spec["finite_family_alpha"])
    file_sha = artifact.save(output / "forecast.pt")
    restored = CategoricalForecast.load(output / "forecast.pt", expected_file_sha256=file_sha)
    restored.verify_integrity()
    labeler.verify_integrity()
    snapshot.verify_integrity()
    if pins != {str(path.relative_to(module.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}:
        raise RuntimeError("Registered four-modal forecast sources changed during fitting")
    (output / "fit-evidence.json").write_bytes(canonical(evidence) + b"\n")
    completed = {**stamp, "status": "completed", "forecast_file_sha256": file_sha,
                 "forecast_fingerprint": restored.fingerprint, "metric_sha256": restored.metric_digest,
                 "temperature": restored.temperature, "finite_family_calibration": restored.calibration,
                 "wall_ns": time.perf_counter_ns() - started,
                 "offline_cost_is_native_latency": False, "neuron_admission_established": False}
    (output / "status.json").write_bytes(canonical(completed) + b"\n")
    print(json.dumps(completed, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
