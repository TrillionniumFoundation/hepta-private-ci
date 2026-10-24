"""Run the already registered actual-output plan stage on training sources."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from ..v6.neural import PROFILES
from .evaluation import evaluate_development, load_reward
from .metric import text_image_labeler
from .plan_training import fit_plan_head
from .plans import ControlledSnapshot
from .snapshot import Snapshot
from .sources import canonical, load_roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--base-run", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base_run, output = Path(args.base_run), Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    module_dir = Path(__file__).resolve().parent
    spec_path = module_dir / "plan_spec.json"
    spec = json.loads(spec_path.read_text())
    dev_spec = json.loads((module_dir / "development_spec.json").read_text())
    source_files = [*(module_dir / f"{name}.py" for name in
                     ("sources", "data", "model", "snapshot", "evaluation", "metric", "plans", "plan_training", "plan_development")),
                    spec_path, module_dir / "development_spec.json",
                    *(module_dir.parent / "v6" / f"{name}.py" for name in ("data", "neural", "observer", "plan_training"))]
    source_pins = {str(path.relative_to(module_dir.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in source_files}
    base_status = json.loads((base_run / "base-status.json").read_text())
    if base_status.get("status") != "completed" or base_status.get("formal_outcome_access"):
        raise ValueError("Plan stage requires completed development-only bases")
    reward = json.loads((base_run / "reward-observer.json").read_text())
    observer, observer_record = load_reward(base_run / "reward-observer.pt", reward["file_sha256"])
    labeler = text_image_labeler(observer, observer_file_sha256=reward["file_sha256"])
    corpus = load_roles(args.cache, args.manifest, ("train", "development"))
    if (observer_record["source_manifest_sha256"] != corpus.manifest["manifest_sha256"]
            or base_status["source_manifest_sha256"] != corpus.manifest["manifest_sha256"]):
        raise ValueError("Source roles are not bound to the same registration")
    stamp = {"schema": "hepta.ndu-v7.plan-development-run.v1", "formal_holdout_opened": False,
             "audit_b_access": False, "source_sha256": source_pins,
             "base_status_file_sha256": hashlib.sha256((base_run / "base-status.json").read_bytes()).hexdigest(),
             "source_manifest_sha256": corpus.manifest["manifest_sha256"]}
    (output / "status.json").write_bytes(canonical({**stamp, "status": "running"}) + b"\n")
    torch.set_num_threads(2)
    started, result = time.perf_counter_ns(), {}
    for profile in PROFILES:
        print(json.dumps({"stage": "enumeration_started", "profile": profile}), flush=True)
        base_sha = base_status["result"][profile]["checkpoint_file_sha256"]
        base = Snapshot.load(base_run / f"{profile}.pt", expected_file_sha256=base_sha)
        snapshot, evidence = fit_plan_head(base, corpus, labeler, profile, dev_spec["development_seed"],
                                          output / f"training-{profile}", fit_pairs=spec["fit_pairs"],
                                          steps=spec["optimizer_steps"], scenarios=spec["latent_scenarios"],
                                          risk_aversion=spec["risk_aversion"])
        sha = snapshot.save(output / f"{profile}.pt")
        restored = ControlledSnapshot.load(output / f"{profile}.pt", expected_file_sha256=sha)
        summary = evaluate_development(restored, corpus, observer, output / f"evaluation-{profile}",
                                        pairs=dev_spec["development_role_pairs"]["count"],
                                        offset=dev_spec["development_role_pairs"]["start"], actions=())
        thresholds = dev_spec["development_competence_gates"]
        gates = {
            "clean": summary["per_view"]["clean"]["joint_fact_correct"] >= thresholds["clean_joint_fact_min"],
            "sufficient_mixture": summary["sufficient_diagnostic"]["joint_fact_correct"] >= thresholds["sufficient_views_joint_fact_min"],
            "each_sufficient_view": all(summary["per_view"][view]["joint_fact_correct"] >=
                                         thresholds["each_sufficient_view_joint_fact_min"] for view in spec["views"][:5]),
        }
        result[profile] = {"snapshot_sha256": snapshot.fingerprint, "file_sha256": sha,
                           "evidence_file_sha256": hashlib.sha256((output / f"training-{profile}" / "evidence.json").read_bytes()).hexdigest(),
                           "competence_gates": gates, "all_competence_gates_passed": all(gates.values()),
                           "strict_full_census": summary["strict_full_census"],
                           "initial_mixture_ce": evidence["initial_mixture_ce"],
                           "final_mixture_ce": evidence["final_mixture_ce"],
                           "deployment_argmax_ce": evidence["deployment_argmax_ce"],
                           "gate_gradient_abs_sum_max": evidence["gate_gradient_abs_sum_max"],
                           "global_scientific_success": False}
        print(json.dumps({"profile": profile, **result[profile]}, sort_keys=True), flush=True)
    if source_pins != {str(path.relative_to(module_dir.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in source_files}:
        raise RuntimeError("Executed plan-training source changed during the run")
    completed = {**stamp, "status": "completed", "wall_ns": time.perf_counter_ns() - started, "result": result}
    (output / "status.json").write_bytes(canonical(completed) + b"\n")
    print(json.dumps(completed, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
