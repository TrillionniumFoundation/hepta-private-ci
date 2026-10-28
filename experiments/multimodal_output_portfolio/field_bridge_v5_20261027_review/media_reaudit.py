"""Independently reconstruct targets and rescore every retained V5 endpoint.

Reuse the audited V3 independent batch reconstruction and scalar utility
implementation. No generator is constructed, trained or executed.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..field_bridge_v3_20261027.source_roles import load_corpus_roles
from ..field_bridge_v3_20261027.training_common import file_hash, require, write_json
from ..field_bridge_v3_20261027_review.training_hard_score_audit import (
    GroupedObserver, load_observers, rebuild_panel, verify_hard,
)
from ..field_bridge_v5_20261027.records import verify_complete
from ..field_bridge_v5_20261027.run import check_freeze


def audit(run, freeze_path, assets, diagnostic_report=None):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    portfolio = Path(__file__).resolve().parents[1]
    dependencies = ["field_bridge_v3_20261027_review/training_hard_score_audit.py",
                    "field_bridge_v3_20261027_review/native_session_audit.py",
                    "field_bridge_v5_20261027_review/media_reaudit.py"]
    source_identities = {name: file_hash(portfolio / name) for name in dependencies}
    run, freeze_path, assets = Path(run), Path(freeze_path), Path(assets)
    freeze_identity = file_hash(freeze_path)
    protocol, freeze = check_freeze(freeze_path)
    audit_identity = file_hash(run / "AUDIT.json")
    prior = json.loads((run / "AUDIT.json").read_text())
    diagnostic, diagnostic_identity = None, None
    if diagnostic_report is None:
        require(prior["integrity_status"] == "PASS"
                and prior["source_freeze_sha256"] == file_hash(freeze_path), "Artifact audit must pass first")
    else:
        diagnostic_report = Path(diagnostic_report)
        diagnostic_identity = file_hash(diagnostic_report)
        diagnostic = json.loads(diagnostic_report.read_text())
        require(prior["integrity_status"] == "FAIL" and prior["error_type"] == "ValueError"
                and prior["error"] == "Ordinary48 historical endpoint regression failed",
                "Diagnostic media verification is restricted to the preserved historical replay failure")
        require(diagnostic["within_run_integrity"] == "PASS" and diagnostic["overall_status"] == "FAIL"
                and diagnostic["historical_regression_status"] == "FAIL" and diagnostic["admission"] is False
                and diagnostic["failed_frozen_audit_sha256"] == audit_identity
                and diagnostic["source_freeze_sha256"] == file_hash(freeze_path), "Incomplete diagnostic binding")
    require(torch.__version__ == protocol["runtime"]["torch"]
            and np.__version__ == protocol["runtime"]["numpy"], "Pinned runtime mismatch")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    seals, stages, starts, asset_records = {}, {}, {}, []
    protocol_identity = file_hash(Path(__file__).resolve().parents[1] / "field_bridge_v5_20261027/PROTOCOL.json")
    for phase in ("train", "evaluate"):
        for seed in protocol["seeds"]:
            directory = run / phase / str(seed)
            stages[f"{phase}/{seed}"] = verify_complete(directory, {
                "phase": phase, "seed": seed, "study_id": protocol["study_id"],
                "freeze_sha256": file_hash(freeze_path), "protocol_sha256": protocol_identity,
                "registered_commit": freeze["registered_commit"], "new_holdout_access": False})
            starts[f"{phase}/{seed}"] = json.loads((directory / "START.json").read_text())
            seals[f"{phase}/{seed}"] = file_hash(directory / "COMPLETE.json")
            if phase == "evaluate":
                asset_records.append(json.loads((directory / "ASSETS.json").read_text()))
    require(all(stages[f"train/{seed}"]["train_paths"] == 24 for seed in protocol["seeds"]), "Incomplete training census")
    require(min(starts[f"evaluate/{seed}"]["started_unix_ns"] for seed in protocol["seeds"])
            >= max(stages[f"train/{seed}"]["completed_unix_ns"] for seed in protocol["seeds"]), "Endpoint timing barrier violated")
    expected_seals = {str(seed): seals[f"train/{seed}"] for seed in protocol["seeds"]}
    require(all(stages[f"evaluate/{seed}"]["training_seals"] == expected_seals
                for seed in protocol["seeds"]), "Evaluation bound a different training census")
    require(diagnostic is None or diagnostic["phase_seals"] == seals, "Diagnostic belongs to different phase seals")
    v3 = json.loads((portfolio / "field_bridge_v3_20261027/PROTOCOL.json").read_text())
    p = v3["training"]
    require(p["panel_batch_size"] == 128 and p["refinement_charge"] == .002, "Independent arithmetic scope changed")
    observers, identities = load_observers(assets, asset_records)
    arithmetic = GroupedObserver(observers, {name: value["parameter_sha256"] for name, value in identities.items()})
    roles = protocol["source_roles_evaluation"]
    require(roles == ["development_task", "development_clean"], "Undeclared endpoint role")
    corpus = load_corpus_roles(assets / "ndu-data", roles)
    require(list(corpus.splits) == roles, "Unexpected loaded roles")
    files = {}
    for seed in protocol["seeds"]:
        directory = run / "evaluate" / str(seed)
        metadata = json.loads((directory / "PANELS.json").read_text())
        panels = {name: rebuild_panel(corpus.splits["development_" + name], "development_" + name, seed,
                  p["conditions"] if name == "task" else ["clean"], p, metadata[name])
                  for name in ("task", "clean")}
        charge = p["refinement_charge"] * (1 + (p["fixed_actions"][str(seed)] != 0))
        with np.load(directory / "ENDPOINTS.npz", allow_pickle=False) as saved:
            arrays = {name: saved[name] for name in saved.files}
        for name in ("task", "clean"):
            path = directory / ("original-" + name + ".npz")
            files[str(path.relative_to(run))] = verify_hard(path, panels[name], arrays["frozen_" + name], arithmetic, charge)
        for mi, method in enumerate(protocol["methods"]):
            for si, schedule in enumerate(protocol["schedules"]):
                for name in ("task", "clean"):
                    path = directory / method / str(schedule) / (name + ".npz")
                    files[str(path.relative_to(run))] = verify_hard(path, panels[name], arrays[name][mi, si], arithmetic, charge)
        print(json.dumps({"seed": seed, "verified_files": len(files)}), flush=True)
    expected_files = len(protocol["seeds"]) * (1 + len(protocol["methods"]) * len(protocol["schedules"])) * 2
    require(len(files) == expected_files, "Incomplete retained media census")
    check_freeze(freeze_path)
    require(file_hash(freeze_path) == freeze_identity, "Source freeze changed during media verification")
    for relative, identity in seals.items():
        verify_complete(run / relative)
        require(file_hash(run / relative / "COMPLETE.json") == identity, "Phase seal changed during media verification")
    require(file_hash(run / "AUDIT.json") == audit_identity, "Artifact audit changed during media verification")
    require(diagnostic_report is None or file_hash(diagnostic_report) == diagnostic_identity,
            "Diagnostic changed during media verification")
    require(source_identities == {name: file_hash(portfolio / name) for name in dependencies},
            "Independent verification source changed during execution")
    return {"schema": "hepta.field-bridge.v5.independent-media-audit.1", "passed": True,
            "scope": "media arithmetic only; cannot change the frozen audit or grant admission",
            "frozen_audit_status": prior["integrity_status"], "diagnostic_audit_sha256": diagnostic_identity,
            "admission": False, "new_holdout_authorized": False,
            "study_id": protocol["study_id"], "registered_commit": freeze["registered_commit"],
            "source_freeze_sha256": freeze_identity, "artifact_audit_sha256": audit_identity,
            "phase_seals": seals, "script_sha256": file_hash(__file__),
            "independent_arithmetic_sources": source_identities,
            "files": files, "media_files": len(files), "media_outputs": sum(v["rows"] for v in files.values()),
            "observer_values_verified": sum(v["observer_values_verified"] for v in files.values()),
            "maximum_value_error": 0., "all_exact": True, "observer_identities": identities,
            "verification_costs": arithmetic.costs(), "generator_calls": 0, "new_holdout_access": False,
            "cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - started}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--diagnostic-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite media audit")
    result = audit(args.run_root, args.freeze, args.assets, args.diagnostic_report)
    write_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("passed", "media_files", "media_outputs", "observer_values_verified")}))
