"""Development-only end-to-end preflight; never touches registered test seeds."""

import argparse
import json
from pathlib import Path

import numpy as np

from experiments.continuous_boundary_flow.execution import behavior_data
from experiments.continuous_boundary_flow.models import fit_boundary
from experiments.continuous_boundary_flow.native.adapter import NativeBridge
from experiments.continuous_boundary_flow.scenarios import load_contexts
from .common import ARMS, CONTROLS, canonical, save_json, sha
from .execution import run_context
from .native.bridge import ScoreBridge
from .training import train_arm


def run(output, native, score):
    output.mkdir(parents=True, exist_ok=False)
    binaries = {"native": native, "score": score}
    contexts = load_contexts(991, "training", 2)
    development = load_contexts(991, "development", 1)
    diagnostic = load_contexts(991, "diagnostic", 1)
    histories = [behavior_data(context, 991, 2) for context in contexts]
    boundary = fit_boundary(contexts)
    results = []
    for arm in ARMS:
        item, receipt = train_arm(
            output,
            binaries,
            991,
            arm,
            contexts,
            histories,
            development,
            boundary,
            epochs=4,
            candidate_indices=[1],
            development_paths=2,
        )
        checkpoint = json.loads((output / item["path"]).read_text())
        bridge = (
            NativeBridge(native, output / "diagnostic" / arm)
            if arm == "native_sparse"
            else ScoreBridge(score, output / "diagnostic" / arm)
        )
        try:
            if arm == "native_sparse":
                bridge.load_profile(output / checkpoint["profile_path"])
            result = run_context(
                diagnostic[0],
                seed=991,
                phase="diagnostic",
                paths=4,
                arm=arm,
                checkpoint_sha256=item["sha256"],
                checkpoint=checkpoint,
                bridge=bridge,
            )
        finally:
            cost = bridge.close()
        if not np.isfinite(result["utility"]).all() or len(result["records"]) != 4:
            raise ValueError("Preflight failed")
        save_json(output / "records" / f"{arm}.json", result["records"])
        results.append(
            {
                "arm": arm,
                "episodes": 4,
                "counts": result["counts"],
                "cost": cost,
                "training": receipt["cost"],
            }
        )
    for arm in CONTROLS:
        result = run_context(
            diagnostic[0],
            seed=991,
            phase="diagnostic",
            paths=4,
            arm=arm,
            checkpoint_sha256=sha(canonical({"arm": arm})),
        )
        save_json(output / "records" / f"{arm}.json", result["records"])
        results.append({"arm": arm, "episodes": 4, "counts": result["counts"]})
    summary = {
        "schema": "hepta.continuous-boundary-policy.preflight.v1",
        "seed": 991,
        "registered_confirmation_accessed": False,
        "arms": results,
        "episodes": 52,
    }
    save_json(output / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--score-binary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.native_binary, args.score_binary)))
