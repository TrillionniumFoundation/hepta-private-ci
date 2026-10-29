"""Small all-arm engineering smoke; seed 9002 never enters confirmation."""

import json
from pathlib import Path
from experiments.continuous_boundary_flow.common import ARMS, save_json
from experiments.continuous_boundary_flow.scenarios import load_contexts
from experiments.continuous_boundary_flow.execution import behavior_data, run_context
from experiments.continuous_boundary_flow.models import fit_boundary
from experiments.continuous_boundary_flow.native.adapter import NativeBridge
from experiments.continuous_boundary_flow.training import train_arm


def run_smoke(output, binary):
    root = Path(output)
    root.mkdir(exist_ok=False)
    binary = Path(binary)
    seed = 9002
    training = load_contexts(seed, "training", 2)
    dev = load_contexts(seed, "development", 2)
    histories = [behavior_data(c, seed, 4) for c in training]
    boundary = fit_boundary(training)
    checks = []
    for arm in ARMS:
        checkpoint, item, receipt = train_arm(
            root,
            binary,
            seed,
            arm,
            training,
            histories,
            dev,
            boundary,
            candidate_indices=[1, 2],
            dev_paths=4,
        )
        bridge = NativeBridge(binary, root / "eval" / arm)
        key = bridge.load_profile(root / checkpoint["profile_path"])
        episodes = []
        try:
            for phase in ["test_id", "test_ood"]:
                for context in load_contexts(seed, phase, 2):
                    outcome = run_context(
                        context,
                        seed=seed,
                        phase=phase,
                        paths=4,
                        arm=arm,
                        checkpoint_sha256=item["sha256"],
                        bridge=bridge,
                        profile_sha=key,
                        candidate=checkpoint["candidate"],
                        boundary_weights=checkpoint["boundary_weights"],
                    )
                    episodes.extend(outcome["records"])
        finally:
            cost = bridge.close()
        save_json(root / f"{arm}.json", episodes)
        checks.append(
            {
                "arm": arm,
                "selected": checkpoint["candidate_index"],
                "episodes": len(episodes),
                "cost": cost,
            }
        )
        print(
            json.dumps(
                {
                    "arm": arm,
                    "episodes": len(episodes),
                    "native_calls": cost["counters"]["actual_kernel_calls"],
                }
            ),
            flush=True,
        )
    save_json(
        root / "SMOKE.json",
        {
            "scope": "engineering diagnostic only; seed9002 excluded from preregistered study",
            "checks": checks,
            "passed": True,
        },
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    run_smoke(args.output, args.binary)
