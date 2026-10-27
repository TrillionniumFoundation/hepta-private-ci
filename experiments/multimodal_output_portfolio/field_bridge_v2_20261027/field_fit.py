"""Fit only completed registered exploration paths; freeze before audit access."""

import argparse
import json
from pathlib import Path
import time

from ..field_bridge_20261027.run import write_json, digest, object_hash
from ..field_bridge_v2_20261027_review.gate_audit import fitting_rows_digest
from .field_bank import source_freeze, B
from .field_predictor import fit
from .learning import P


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", required=True)
    parser.add_argument("--registered-commit", required=True)
    args = parser.parse_args()
    root = Path(args.bank).resolve()
    if any(root.glob("audit-*/BANK.json")) or (root / "PREDICTOR_FREEZE.json").exists():
        raise ValueError("Audit already started or predictors already frozen; preserve that run")
    sources = source_freeze()
    records, input_files = [], {}
    recipe = next(r for r in P["candidates"] if r["name"] == B["selected_recipe"])
    steps = list(range(0, recipe["steps"], B["macro_steps"]))
    for seed in P["seeds"]:
        path = root / f"fit-{seed}" / "BANK.json"
        complete = json.loads(path.with_name("COMPLETE.json").read_text())
        if digest(path) != complete["bank_sha256"] or complete["source_files"] != sources:
            raise ValueError("Fitting bank differs from completed source/record identity")
        bank = json.loads(path.read_text())
        current = bank["records"]
        expected = {(seed, t, s) for t in B["fit_trajectory_ids"] for s in steps}
        actual = {(r["seed"], r["trajectory"], r["step"]) for r in current if r["partition"] == "fit"}
        if len(current) != len(expected) or actual != expected:
            raise ValueError("Incomplete, duplicate or non-fitting trajectory grid")
        records.extend(current)
        input_files[str(path.relative_to(root))] = digest(path)
    out = root / "controllers"
    out.mkdir(exist_ok=False)
    identities, file_identities, summary = {}, {}, {}
    started = time.perf_counter_ns()
    for seed in P["seeds"]:
        subset = [r for r in records if r["seed"] == seed]
        identities[str(seed)], summary[str(seed)] = {}, {}
        for mode in ("field", "generic", "richer"):
            then = time.perf_counter_ns()
            controller = fit(subset, mode)
            path = out / f"{seed}-{mode}.json"
            write_json(path, controller)
            identities[str(seed)][mode] = object_hash(controller)
            file_identities[str(path.relative_to(root))] = digest(path)
            selected = controller["cv"]["candidates"][controller["selected_index"]]
            summary[str(seed)][mode] = {"selected": selected, "fit_wall_ns": time.perf_counter_ns() - then}
            print(f"seed={seed} {mode}: selected={controller['selected_candidate']} CV MSE={selected['mean_mse']:.7g}", flush=True)
    if source_freeze() != sources:
        raise RuntimeError("Source changed during predictor fitting")
    freeze = {"schema": "hepta.field-bridge.v2.pre-audit-freeze.1", "registered_source_commit": args.registered_commit,
        "source_files": sources, "decision_steps": steps, "fit_rows_sha256": fitting_rows_digest(records),
        "controller_sha256": identities, "controller_files_sha256": file_identities,
        "fit_bank_files_sha256": input_files, "fit_summary": summary, "wall_ns": time.perf_counter_ns() - started,
        "audit_trajectories_accessed": False, "test_retention_scored": False,
        "fit_candidate_evaluations": len(P["seeds"]) * 3 * 161,
        "prediction_scope": "New optimizer trajectories on the same training value panel; not new labels"}
    write_json(root / "PREDICTOR_FREEZE.json", freeze)
    print("PREDICTORS FROZEN; commit complete controllers and this receipt before any audit trajectory.", flush=True)


if __name__ == "__main__":
    main()
