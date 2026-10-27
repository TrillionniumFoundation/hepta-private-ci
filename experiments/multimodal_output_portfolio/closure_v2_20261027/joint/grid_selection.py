"""Freeze the identical two-sigma development budget before qualification."""

import argparse
import json
from pathlib import Path
import shutil

import torch

from .actor import LatentActor, LatentSnapshot
from .grid_guard import verify_development_run
from .protocol import PROTOCOL as P, checksum, write_json
from .run import base_model


def combine(prior, runs, output):
    specification = Path(__file__).with_name("STUDY_GRID.json")
    grid = json.loads(specification.read_text())
    if output.exists():
        raise FileExistsError("A frozen selection must not be overwritten")
    protocols = [json.loads((run / "PROTOCOL.json").read_text()) for run in runs]
    pins = [verify_development_run(run) for run in runs]
    if len({pin["baselines_sha256"] for pin in pins}) != 1:
        raise ValueError("Candidate runs used different baseline checkpoints")
    if [p["sigma"] for p in protocols] != grid["candidate_standard_deviations"]:
        raise ValueError("The predeclared sigma grid differs")
    for protocol, run in zip(protocols, runs):
        completed = json.loads((run / "COMPLETED.json").read_text())
        if completed["steps"] != P["steps"] or completed["seeds"] != P["seeds"]:
            raise ValueError("Incomplete fixed training grid")
        if checksum(run / "SELECTIONS.json") != completed["selection_sha256"]:
            raise ValueError("A development selection changed")
        if {k: v for k, v in protocol.items() if k != "sigma"} != {k: v for k, v in P.items() if k != "sigma"}:
            raise ValueError("More than sigma differs between candidate protocols")
    output.mkdir(parents=True)
    selections, budgets = [], []
    for seed in P["seeds"]:
        base, _ = base_model(prior, seed)
        for arm in ("direct_mean", "direct_risk"):
            all_candidates, original_ce = [], None
            for run, protocol in zip(runs, protocols):
                report = json.loads((run / f"SELECTION-{seed}-{arm}.json").read_text())
                if original_ce is not None and report["original_ce"] != original_ce:
                    raise ValueError("The common original validation outputs differ")
                original_ce = report["original_ce"]
                for candidate in report["candidates"]:
                    all_candidates.append({"source_run": str(run), "sigma": protocol["sigma"],
                        "step": candidate["step"], "checkpoint": candidate["checkpoint"],
                        "eligible": candidate["eligible"],
                        "quality_ce": candidate["metrics"]["quality"]["ce"],
                        "retention_ce": candidate["metrics"]["retention"]["ce"]})
                training = json.loads((run / f"TRAINING-{seed}-{arm}.json").read_text())
                budgets.append({"seed": seed, "arm": arm, "source_run": str(run), "sigma": protocol["sigma"],
                    "training_record_sha256": checksum(run / f"TRAINING-{seed}-{arm}.json"),
                    "training_counts": training["training_counts"], "training_cpu_ns": training["cpu_ns"],
                    "training_wall_ns": training["wall_ns"],
                    "validation_model_count": len(report["candidates"]) + 1,
                    "validation_delivered_examples": (len(report["candidates"]) + 1) * (4 * P["validation_pairs"] + P["validation_retention_pairs"]),
                    "validation_actor_examples": len(report["candidates"]) * (4 * P["validation_pairs"] + P["validation_retention_pairs"]),
                    "pca_shared_per_seed_per_run": {"encoder_examples": 512, "gate_examples": 512, "transition_examples": 1024, "svd_calls": 1},
                    "original_pca_validation_cpu_measured": False})
            candidates = [r for r in all_candidates if r["eligible"]]
            candidates.sort(key=lambda row: (-row["quality_ce"], row["sigma"], row["step"]))
            chosen = candidates[0] if candidates else None
            fallback = chosen is None or chosen["quality_ce"] <= original_ce["quality"] + 1e-12
            row = {"seed": seed, "arm": arm, "kind": "original_fallback" if fallback else "stochastic_actor",
                "selected_eligible": True, "original_ce": original_ce, "candidates": all_candidates,
                "selected_path": None, "selected_sha256": None, "selected_step": 0,
                "source_run": None, "sigma": 0., "selected_ce": original_ce}
            if not fallback:
                run = Path(chosen["source_run"])
                path = output / f"seed-{seed}-{arm}-selected.pt"
                if chosen["checkpoint"] is None:
                    torch.manual_seed(seed * 73 + 19)
                    actor = LatentActor(4 * base._base._model.hidden, P["dimensions"], P["hidden"])
                    basis = torch.load(run / f"BASIS-{seed}.pt", weights_only=True, map_location="cpu")
                    LatentSnapshot(base, actor, basis, chosen["sigma"]).save(path)
                else:
                    shutil.copyfile(run / chosen["checkpoint"], path)
                row.update(selected_path=path.name, selected_sha256=checksum(path),
                           selected_step=chosen["step"], source_run=chosen["source_run"], sigma=chosen["sigma"],
                           selected_ce={"quality": chosen["quality_ce"], "retention": chosen["retention_ce"]})
            selections.append(row)
    for seed in P["seeds"]:
        left = [r for r in budgets if r["seed"] == seed and r["arm"] == "direct_mean"]
        right = [r for r in budgets if r["seed"] == seed and r["arm"] == "direct_risk"]
        for x, y in zip(left, right):
            for key in ("training_counts", "validation_model_count", "validation_delivered_examples", "validation_actor_examples"):
                if x[key] != y[key]:
                    raise ValueError("The full matched development budget differs")
    write_json(output / "SELECTIONS.json", selections)
    shutil.copyfile(runs[0] / "BASELINES.json", output / "BASELINES.json")
    write_json(output / "BUDGET_ACCOUNTING.json", {
        "rows": budgets, "shared_pca_counting": "One PCA per seed per run is physically performed before both arms; do not count it twice when summing actual work.",
        "pilot": "development-001 separately spent 100 steps in both objectives for seed17; exploratory counts and CPU remain in its original training receipts.",
        "timing_limit": "Training CPU/wall were measured. Original PCA and validation CPU/wall were not separately timed; logical counts are exact, total study CPU is not claimed.",
        "same_budget_pair": ["direct_mean", "direct_risk"]})
    write_json(output / "COMPLETED.json", {"schema": "hepta.ndu.direct-grid-selection.v1", "seeds": P["seeds"],
        "steps_per_run": P["steps"], "total_steps_per_seed_per_objective": 2 * P["steps"],
        "grid_specification_sha256": checksum(specification), "grid": grid,
        "runs": [{"path": str(run), "protocol_sha256": checksum(run / "PROTOCOL.json"),
                  "selection_sha256": checksum(run / "SELECTIONS.json"),
                  "development_pins": pin} for run, pin in zip(runs, pins)],
        "selection_sha256": checksum(output / "SELECTIONS.json"),
        "budget_sha256": checksum(output / "BUDGET_ACCOUNTING.json"),
        "audit_or_new_test_used": False})
    print(json.dumps([{k: row[k] for k in ("seed", "arm", "kind", "sigma", "selected_step", "selected_ce")} for row in selections]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    combine(args.prior, args.runs, args.output)
