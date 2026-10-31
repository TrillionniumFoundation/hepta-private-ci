"""Freeze the mechanism matrix before generating any formal test episodes."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


NAMESPACE = Path("experiments/hcsn_mechanism_content_v2")


def make(root, python, output):
    root, output = Path(root).resolve(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = NAMESPACE / "results/mechanism001/jobs"
    jobs = []
    for train_seed, episode_seed, grid_seed in ((1701, 4101, 6101), (1801, 4201, 6201), (1901, 4301, 6301)):
        fit_id = f"fit_s{train_seed}"
        fit_path = results / fit_id
        checkpoint = fit_path / "ordinary.pt"
        jobs.append(dict(id=fit_id, argv=[str(python), "-m",
            "experiments.hcsn_mechanism_content_v2.mechanism", "fit", "--output", str(fit_path),
            "--seed", str(train_seed), "--train-size", "8192", "--epochs", "80",
            "--width", "128", "--cap", "32"], outputs=[str(fit_path / name)
                for name in ("job.json", "training.json", "training.npz", "ordinary.pt")]))
        for condition in ("matched", "hidden_refractory_mismatch"):
            run_id = f"test_s{train_seed}_{condition}"
            path = results / run_id
            jobs.append(dict(id=run_id, depends=[fit_id], argv=[str(python), "-m",
                "experiments.hcsn_mechanism_content_v2.mechanism", "run", "--output", str(path),
                "--checkpoint", str(checkpoint), "--split", "test", "--seed", str(episode_seed),
                "--episodes", "256", "--particles", "4", "--read-cost", "0.04",
                "--light-threshold", "0.28", "--condition", condition],
                outputs=[str(path / name) for name in ("job.json", "selection.json", "summary.json",
                    "trace.jsonl", "access.jsonl", "predictions.jsonl", "episodes.jsonl")]))
        diag_id = f"diagnostics_s{train_seed}"
        path = results / diag_id
        jobs.append(dict(id=diag_id, depends=[fit_id], argv=[str(python), "-m",
            "experiments.hcsn_mechanism_content_v2.mechanism_diagnostics", "--output", str(path),
            "--checkpoint", str(checkpoint), "--seed", str(grid_seed), "--cases", "128",
            "--samples-per-case", "256", "--repeats", "3"], outputs=[str(path / name)
                for name in ("job.json", "selection.json", "summary.json", "cases.jsonl", "predictions.jsonl")]))
    files = [NAMESPACE / name for name in ("__init__.py", "renewal.py", "mechanism.py",
        "mechanism_diagnostics.py", "study.py", "protocol_mechanism.py")]
    freeze = [dict(path=str(path), sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
              for path in files]
    plan = dict(schema="hcsn-fourtrack-mechanism-protocol.v1",
        frozen_at_utc=datetime.now(timezone.utc).isoformat(), repository_root=str(root),
        source_base_commit="9709af902dc029efc007e4122425c6a72f0559b9",
        frozen_files=freeze, jobs=jobs,
        development="Separate development seeds and kernel fixtures; no formal test episodes opened before this freeze",
        primary=dict(contrast="analytic/task_value minus ordinary_gated/task_value",
            condition="matched", metric="accuracy_minus_0.04_per_READ",
            scoring="four mandatory content outputs; STOP disables future reads but does not remove outputs",
            uncertainty="paired episodes, hierarchical bootstrap over 3 fitted seeds and episodes; descriptive 95% interval",
            success="primary interval above zero; complete computation cost must still be reported separately"),
        secondary=dict(contrasts=["B-A", "D-C", "C-A", "(D-C)-(B-A)"],
            metrics=["accuracy", "nll", "brier", "reads", "arm_wall_seconds", "core_calls"],
            mismatch="episode-constant true refractory is nominal times .65 or 1.45; no dynamic-drift claim",
            interventions=["forecast-risk suppression in policy only", "ordinary on analytic action schedule",
                           "frozen content on analytic action schedule"],
            alias_test="equal first two moments but different full gap posteriors",
            kernel_precision="analytic and independent density quadrature max count-probability error <=1e-8",
            kernel_work="CDF terms and density-integrand evaluations; neither is called neural network updates"),
        accounting=dict(complete_worker="fresh interpreter through evidence serialization, Linux wait4 CPU/RSS",
            amortization="ordinary fit billed once per training seed, not once per reported arm or condition",
            inclusive="controller time includes core calls; do not add their inclusive timings",
            energy_joules=None, raw_media_or_network=False,
            monetary_reward="READ tariff only; actual compute is a separate measured axis"),
        limits=["known stationary renewal structure favors the correct analytic inductive prior",
            "ordinary baseline is a gated feedforward propagator, not an SSM or foundation model",
            "same observed information and content matrix, unequal core parameter counts reported",
            "receding one-planned-read heuristic is not a globally optimal QVI controller",
            "three fits are not sufficient to claim general neural architecture superiority"])
    with (output / "plan.json").open("x") as stream:
        json.dump(plan, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps({"plan": str(output / "plan.json"), "jobs": len(jobs),
                      "sha256": hashlib.sha256((output / "plan.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    make(args.root, args.python, args.output)
