"""Freeze H12, equal-width generic and rich30 predictors from enriched fit only."""

import argparse
import json
from pathlib import Path
import time

from ..field_bridge_20261027.run import write_json, digest, object_hash
from ..field_bridge_v2_20261027_review.gate_audit import fitting_rows_digest
from .directional_bank import source_freeze
from .directional_predictor import fit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", required=True)
    parser.add_argument("--registered-commit", required=True)
    args = parser.parse_args()
    root = Path(args.bank).resolve()
    if any(root.glob("audit-*/BANK.json")) or (root / "PREDICTOR_FREEZE.json").exists():
        raise ValueError("Directional predictors already frozen or audit accessed")
    sources, steps, records, inputs = source_freeze(), list(range(0, 288, 8)), [], {}
    for seed in (17, 29, 43):
        path = root / f"fit-{seed}" / "BANK.json"
        complete = json.loads(path.with_name("COMPLETE.json").read_text())
        if digest(path) != complete["bank_sha256"] or complete["source_files"] != sources:
            raise ValueError("Directional fitting source or data changed")
        current = json.loads(path.read_text())["records"]
        expected = {(seed, t, s) for t in range(8) for s in steps}
        if len(current) != len(expected) or {(r["seed"], r["trajectory"], r["step"]) for r in current if r["partition"] == "fit"} != expected:
            raise ValueError("Incomplete enriched fitting grid")
        records.extend(current)
        inputs[str(path.relative_to(root))] = digest(path)
    (root / "controllers").mkdir(exist_ok=False)
    identities, file_hashes, summaries = {}, {}, {}
    started = time.perf_counter_ns()
    for seed in (17, 29, 43):
        identities[str(seed)], summaries[str(seed)] = {}, {}
        for mode in ("field", "generic", "richer"):
            then = time.perf_counter_ns()
            controller = fit([r for r in records if r["seed"] == seed], mode)
            path = root / "controllers" / f"{seed}-{mode}.json"
            write_json(path, controller)
            identities[str(seed)][mode] = object_hash(controller)
            file_hashes[str(path.relative_to(root))] = digest(path)
            selected = controller["cv"]["candidates"][controller["selected_index"]]
            summaries[str(seed)][mode] = {"selected": selected, "fit_wall_ns": time.perf_counter_ns() - then}
            print(f"directional seed={seed} {mode}: {controller['selected_candidate']} CV MSE={selected['mean_mse']:.7g}", flush=True)
    if source_freeze() != sources:
        raise RuntimeError("Directional fitting source changed")
    write_json(root / "PREDICTOR_FREEZE.json", {"schema": "hepta.field-bridge.v2.directional-pre-audit.1",
        "registered_source_commit": args.registered_commit, "source_files": sources, "decision_steps": steps,
        "fit_rows_sha256": fitting_rows_digest(records), "fit_bank_files_sha256": inputs,
        "controller_sha256": identities, "controller_files_sha256": file_hashes, "fit_summary": summaries,
        "wall_ns": time.perf_counter_ns() - started, "fit_candidate_evaluations": 1449,
        "audit_trajectory_ids": list(range(16, 24)), "parent_H7_audit_used_for_fitting": False,
        "test_retention_scored": False})
    print("DIRECTIONAL PREDICTORS FROZEN; commit before conditional fresh-path audit.", flush=True)


if __name__ == "__main__":
    main()
