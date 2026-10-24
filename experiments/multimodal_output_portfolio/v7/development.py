"""Reproducible development-only execution. No test, retention or Audit-B access."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from ..v6.neural import parameter_hash
from ..v6.observer import METRIC_DIGEST, fit_observer
from .evaluation import evaluate_development, load_reward
from .snapshot import Snapshot
from .sources import canonical, digest, load_roles
from .training import TrainConfig, train_profiles


def _source_pins():
    root = Path(__file__).resolve().parents[1]
    files = [*(root / "v7" / f"{name}.py" for name in
               ("sources", "data", "model", "snapshot", "training", "evaluation", "development")),
             root / "v7" / "development_spec.json",
             *(root / "v6" / f"{name}.py" for name in ("data", "neural", "observer"))]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=("observer", "base"), required=True)
    args = parser.parse_args()
    spec_path = Path(__file__).with_name("development_spec.json")
    spec = json.loads(spec_path.read_text())
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    pins = _source_pins()
    stamp = {"stage": args.stage, "specification_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
             "source_sha256": pins, "formal_outcome_access": False, "audit_b_access": False}
    stage_path = output / f"{args.stage}-status.json"
    if stage_path.exists():
        raise FileExistsError("Preserve earlier development attempt; choose a new output directory")
    stage_path.write_bytes(canonical({**stamp, "status": "running"}) + b"\n")
    torch.set_num_threads(spec["threads"])
    roles = ("reward",) if args.stage == "observer" else ("train", "development")
    corpus = load_roles(args.cache, args.manifest, roles)
    started = time.perf_counter_ns()
    if args.stage == "observer":
        observer_spec = spec["reward_observer"]
        model, report = fit_observer(corpus.splits["reward"], steps=observer_spec["steps"],
                                     seed=observer_spec["seed"])
        record = {"schema": "hepta.ndu-v7.reward-observer.v1", "state_dict": model.state_dict(),
                  "parameter_sha256": parameter_hash(model), "metric_sha256": METRIC_DIGEST,
                  "source_manifest_sha256": corpus.manifest["manifest_sha256"], "report": report}
        torch.save(record, output / "reward-observer.pt")
        report["file_sha256"] = hashlib.sha256((output / "reward-observer.pt").read_bytes()).hexdigest()
        report["parameter_sha256"] = record["parameter_sha256"]
        report["source_manifest_sha256"] = corpus.manifest["manifest_sha256"]
        (output / "reward-observer.json").write_bytes(canonical(report) + b"\n")
        result = report
    else:
        reward_report = json.loads((output / "reward-observer.json").read_text())
        observer, record = load_reward(output / "reward-observer.pt", reward_report["file_sha256"])
        if record["source_manifest_sha256"] != corpus.manifest["manifest_sha256"]:
            raise ValueError("Reward and generator source registrations differ")
        config = TrainConfig(seed=spec["development_seed"], steps=spec["base_steps"],
                             batch_size=spec["batch_size"], scenarios=spec["latent_scenarios"],
                             learning_rate=spec["learning_rate"], risk_aversion=spec["risk_aversion"],
                             noise_scale=spec["noise_scale"], horizon=spec["control_horizon"],
                             threads=spec["threads"])
        snapshots, reports = train_profiles(corpus, config, lambda profile, row:
                                            print(json.dumps({"profile": profile, **row}), flush=True))
        (output / "training.json").write_text(json.dumps(reports, sort_keys=True, indent=2) + "\n")
        result = {}
        for profile, snapshot in snapshots.items():
            path = output / f"{profile}.pt"
            sha = snapshot.save(path)
            restored = Snapshot.load(path, expected_file_sha256=sha)
            reports[profile]["checkpoint_file_sha256"] = sha
            summary = evaluate_development(restored, corpus, observer, output / f"evaluation-{profile}",
                                            pairs=spec["development_role_pairs"]["count"],
                                            offset=spec["development_role_pairs"]["start"],
                                            actions=tuple(spec["development_actions"]))
            gates = spec["development_competence_gates"]
            checks = {
                "clean": summary["per_view"]["clean"]["joint_fact_correct"] >= gates["clean_joint_fact_min"],
                "sufficient_mixture": summary["sufficient_diagnostic"]["joint_fact_correct"] >= gates["sufficient_views_joint_fact_min"],
                "each_sufficient_view": all(summary["per_view"][view]["joint_fact_correct"] >=
                    gates["each_sufficient_view_joint_fact_min"] for view in spec["views"][:5]),
            }
            result[profile] = {"checkpoint_file_sha256": sha, "competence_gates": checks,
                               "all_competence_gates_passed": all(checks.values()),
                               "strict_full_census": summary["strict_full_census"],
                               "global_scientific_success": False}
        (output / "training.json").write_text(json.dumps(reports, sort_keys=True, indent=2) + "\n")
    if pins != _source_pins():
        raise RuntimeError("Executed development source files changed during the run")
    completed = {**stamp, "status": "completed", "wall_ns": time.perf_counter_ns() - started,
                 "source_manifest_sha256": corpus.manifest["manifest_sha256"], "result": result}
    stage_path.write_bytes(canonical(completed) + b"\n")
    print(json.dumps(completed, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
