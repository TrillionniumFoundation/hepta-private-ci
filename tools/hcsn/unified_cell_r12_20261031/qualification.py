"""Collect deterministic implementation evidence without confirmation data.

Usage:
  python -m tools.hcsn.unified_cell_r12_20261031.qualification --output RUN_DIR

The first registered seed's completed selected training checkpoints are pinned
by their current file hashes.  These are hashes captured during qualification,
not retroactive records of the sources present when each training job started.
The separate campaign freeze remains the holdout-before-generation contract.
"""

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import resource
import shutil
import sys
import time
import traceback

import numpy as np
import scipy
from threadpoolctl import threadpool_limits

from .audit import run_audit
from .cell import Cell
from .estimators import restore_model
from .fit import atomic_json
from .mechanisms import run_mechanisms
from .policy_audit import run_policy_fixture
from .scalar_qvi_reference import run_scalar_reference


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KINDS = ("hx_distribution", "gru", "continuous_diagonal_ssm")


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _children_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime+usage.ru_stime


def _source_manifest():
    names = ("qualification.py", "audit.py", "native_probe.c", "cell.py", "data.py",
             "estimators.py", "recurrent.py", "fit.py", "task_value.py", "mechanisms.py",
             "policy_audit.py", "scalar_qvi_reference.py", "grid_refinement.py",
             "PROTOCOL.json", "IMPLEMENTATION.json", "BASELINE.json", "requirements-numpy.txt")
    paths = [HERE/name for name in names]
    paths.append(HERE.parent/"calibrated_operator_r11_20261031"/"numerics"/"kernel.py")
    if (HERE/"dual_reference.py").exists():
        paths.append(HERE/"dual_reference.py")
    return {str(path.relative_to(ROOT)): _hash(path) for path in sorted(paths)}


def _existing_grid_result():
    path = HERE/"grid_refinement_result.json"
    result = json.loads(path.read_text())
    if result.get("schema") != "hcsn-r12-independent-finite-grid-refinement-v1":
        raise ValueError("Unrecognized saved grid refinement evidence")
    for field, source in (("source_sha256", "grid_refinement.py"), ("cell_sha256", "cell.py")):
        if result.get(field) != _hash(HERE/source):
            raise ValueError("Saved grid refinement evidence is stale for " + source)
    protocol = json.loads((HERE/"PROTOCOL.json").read_text())
    if result["physical_parameters"] != protocol["baseline_financial_parameters"]:
        raise ValueError("Grid refinement evidence uses different financial parameters")
    return {"reuse": "Copied existing evidence; expensive grid sweep was not rerun",
            "source_artifact": str(path.relative_to(ROOT)), "artifact_sha256": _hash(path),
            "recorded_original_cpu_seconds": result["cpu_seconds"],
            "current_source_bindings_verified": True, "result": result}


def _policy_fixtures(output, protocol):
    seed = int(protocol["seeds"][0])
    fits, artifacts = {}, {}
    for kind in KINDS:
        path = output/str(seed)/(kind+".json")
        digest = _hash(path)
        fit = json.loads(path.read_text())
        if (fit.get("status") != "completed" or fit.get("seed") != seed
                or fit.get("kind") != kind or fit.get("budget_cpu_seconds") != 20.):
            raise ValueError("The first registered seed needs all three completed 20-CPU-second fits")
        if fit["selected_model"]["kind"] != kind:
            raise ValueError("Selected checkpoint does not match its fitted core")
        fits[kind] = fit
        artifacts[str(path.relative_to(output))] = digest
    selected_ordinary = min(KINDS[1:], key=lambda kind: fits[kind]["selected_validation_joint_ce"])
    freeze_path = output/"FREEZE.json"
    freeze = None
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text())
        for relative, digest in artifacts.items():
            if freeze["artifacts"].get(relative) != digest:
                raise ValueError("Qualification checkpoint does not match candidate freeze: " + relative)
        if freeze["selection"][str(seed)]["kind"] != selected_ordinary:
            raise ValueError("Validation-only core selection disagrees with candidate freeze")
    hx = restore_model(fits["hx_distribution"]["selected_model"])
    fitted_cell = hx.build_cell()
    fixtures = {}
    for kind in KINDS:
        fixtures[kind] = run_policy_fixture(fitted_cell, restore_model(fits[kind]["selected_model"]))
    for relative, digest in artifacts.items():
        if _hash(output/relative) != digest:
            raise ValueError("A selected training artifact changed during its policy audit")
    return {"seed": seed, "selection_basis": "preconfirmation validation joint-posterior cross entropy only",
            "selected_ordinary_kind": selected_ordinary,
            "validation_joint_ce": {kind: fits[kind]["selected_validation_joint_ce"] for kind in KINDS},
            "selected_updates": {kind: fits[kind]["selected_update"] for kind in KINDS},
            "checkpoint_artifact_sha256": artifacts,
            "hash_capture_time": "qualification execution, not training job startup",
            "global_candidate_freeze_present": freeze is not None,
            "freeze_sha256": _hash(freeze_path) if freeze is not None else None,
            "checkpoint_status": "completed, validation-selected checkpoints pinned unchanged during this audit",
            "fixtures": fixtures,
            "scope": "One fixed development prefix per core in the fitted world; no confirmation episodes or true-world quality inference"}


def run(output, report_name="QUALIFICATION.json"):
    """Write a complete evidence report plus full per-stage JSON sidecars."""
    output = Path(output).resolve()
    if Path(report_name).name != report_name or not report_name.endswith(".json"):
        raise ValueError("report name must be a plain JSON filename")
    report_path = output/report_name
    evidence_dir = output/(Path(report_name).stem.lower()+"_evidence")
    if report_path.exists() or evidence_dir.exists():
        raise FileExistsError("Qualification evidence already exists; preserve it and use another --report-name")
    started, wall, child_start = time.process_time(), time.perf_counter(), _children_cpu()
    protocol = json.loads((HERE/"PROTOCOL.json").read_text())
    source_files = _source_manifest()
    output.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir()
    stages = {}

    def stage(name, operation):
        cpu, elapsed, child = time.process_time(), time.perf_counter(), _children_cpu()
        try:
            result = operation()
            # Check serializability before declaring the stage completed.
            json.dumps(result, allow_nan=False)
            record = {"status": "completed", "result": result}
        except Exception as error:
            record = {"status": "failed", "error_type": type(error).__name__,
                      "error": str(error), "traceback": traceback.format_exc()}
        record.update(parent_cpu_seconds=time.process_time()-cpu,
                      child_cpu_seconds=_children_cpu()-child,
                      wall_seconds=time.perf_counter()-elapsed)
        path = evidence_dir/(name+".json")
        atomic_json(path, record)
        record["artifact"] = {"path": str(path.relative_to(output)), "sha256": _hash(path)}
        stages[name] = record
        print(json.dumps({"stage": name, "status": record["status"],
                          "parent_cpu_seconds": record["parent_cpu_seconds"],
                          "child_cpu_seconds": record["child_cpu_seconds"]}), flush=True)

    with threadpool_limits(limits=1):
        stage("audit", lambda: run_audit(Cell(), include_native=True))
        stage("mechanisms", lambda: run_mechanisms(Cell()))
        stage("scalar_reference", run_scalar_reference)
        stage("grid_refinement", _existing_grid_result)
        stage("deployed_policy", lambda: _policy_fixtures(output, protocol))
        if (HERE/"dual_reference.py").exists():
            def dual():
                module = importlib.import_module(__package__+".dual_reference")
                return module.run_dual_reference(Cell())
            stage("dual_reference", dual)
        else:
            stages["dual_reference"] = {
                "status": "not_available", "optional_stage": True,
                "reason": "dual_reference.py is absent; this diagnostic was not run or certified"}
            print(json.dumps({"stage": "dual_reference", "status": "not_available"}), flush=True)
    final_sources = _source_manifest()
    changed_sources = [path for path in set(source_files) | set(final_sources)
                       if source_files.get(path) != final_sources.get(path)]
    failures = [name for name, value in stages.items() if value["status"] == "failed"]
    omissions = [name for name, value in stages.items() if value["status"] == "not_available"]
    if changed_sources:
        failures.append("source_changed_during_qualification")
    cpu, child_cpu = time.process_time()-started, _children_cpu()-child_start
    report = {
        "schema": "hcsn-r13-qualification-evidence-v1",
        "status": "failed" if failures else ("completed_with_explicit_omissions" if omissions else "completed"),
        "stages": stages, "failed_stages": failures, "omitted_stages": omissions,
        "source_files_sha256": source_files, "source_files_after_sha256": final_sources,
        "source_changed_during_qualification": sorted(changed_sources),
        "hash_capture_scope": "Current qualification sources/checkpoints only. Per-training-job startup source hashes were not captured; no retroactive claim is made.",
        "holdout_contract": "The separate campaign FREEZE pins final sources, models and selection before confirmation generation.",
        "confirmation_data_generated": False, "confirmation_data_read": False,
        "thresholds_changed": False, "first_registered_seed": int(protocol["seeds"][0]),
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "scipy": scipy.__version__, "platform": platform.platform(),
                    "rustc_available": shutil.which("rustc") is not None,
                    "cargo_available": shutil.which("cargo") is not None},
        "parent_cpu_seconds": cpu, "child_cpu_seconds": child_cpu,
        "parent_plus_child_cpu_seconds": cpu+child_cpu,
        "parent_process_cpu_at_report_measurement": time.process_time(),
        "wall_seconds": time.perf_counter()-wall,
        "cost_scope": "Qualification work measured from runner entry. Child CPU includes native compiler/probes. Final evidence serialization follows this measurement; no speed or energy benefit is inferred.",
        "production_activation": False, "production_rust_validated": False,
        "rust_status": "Production Rust execution is unavailable in this environment and was not run; independent C evidence is research-only.",
        "full_financial_fp32_admitted": False, "finite_grid_is_continuum": False,
        "all_scientific_blockers_closed": False,
        "scope": "Implementation and deterministic development diagnostics. Completion does not imply task superiority, general language capability, production admission or continuum optimality.",
    }
    atomic_json(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Existing experiment directory containing training fits")
    parser.add_argument("--report-name", default="QUALIFICATION.json",
                        help="Use a new name to preserve a previous qualification attempt")
    args = parser.parse_args()
    result = run(args.output, args.report_name)
    print(json.dumps({"status": result["status"], "report": str(Path(args.output)/args.report_name),
                      "failed_stages": result["failed_stages"], "omitted_stages": result["omitted_stages"],
                      "parent_plus_child_cpu_seconds": result["parent_plus_child_cpu_seconds"]}), flush=True)
    if result["failed_stages"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
