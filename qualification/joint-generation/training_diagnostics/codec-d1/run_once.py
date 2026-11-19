"""One fixed TRAIN-only ABBA comparison; no formal evaluator is invoked."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path(__file__).resolve().parent
ENVIRONMENT = "ccarenv_b64_Y2NhcmVudl8wOGNhYzlkMjdjYjg4MTkxOWJkMDY0MGIyMDBhYTA5OA"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def persist_terminal(out, terminal):
    """Keep the first real failure when either persistence destination fails."""
    name = "COMPLETED.json" if terminal["fault"] is None else "PARTIAL.json"
    errors = []
    for target in (out / name, DIRECTORY / name):
        try:
            write(target, terminal)
        except Exception as error:
            errors.append({"target": str(target), "type": type(error).__name__, "error": str(error)})
    if errors:
        terminal.update(exit_code=1, persistence_errors=errors)
        terminal["fault"] = terminal["fault"] or errors[0]
        for target in (DIRECTORY / "PARTIAL.json", out / "PARTIAL.json"):
            if not target.exists():
                try:
                    write(target, terminal)
                except Exception as error:
                    print(json.dumps({"terminal_persistence_error": str(error), "target": str(target)}), file=sys.stderr)
    return terminal


def source_guard(freeze_path):
    frozen, plan = read(freeze_path), read(DIRECTORY / "plan.json")
    if (frozen["experiment_id"] != "codec-train-d1" or frozen["plan"] != plan
            or frozen["plan_sha256"] != sha(DIRECTORY / "plan.json")
            or plan.get("qualification_eligible") is not False):
        raise ValueError("fixed TRAIN diagnostic/freeze changed")
    paths = list(ROOT.glob("*.py")) + list((ROOT / "independent").glob("*.py"))
    paths += list((ROOT / "independent").glob("*.c"))
    identity = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    if frozen["sources"] != identity:
        raise ValueError("complete frozen source inventory changed")
    bound = {**identity, "training_diagnostics/codec-d1/plan.json": frozen["plan_sha256"],
             plan["protocol_path"]: plan["protocol_sha256"]}
    for field in ("diagnostic_driver", "diagnostic_analysis"):
        row = plan[field]
        if sha(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("diagnostic script changed: " + row["path"])
        bound[row["path"]] = row["sha256"]
    for name, expected in bound.items():
        payload = subprocess.check_output(["git", "show", frozen["source_commit"]
            + ":qualification/joint-generation/" + name], cwd=ROOT)
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("uncommitted frozen bytes: " + name)
    if sha(ROOT / plan["protocol_path"]) != plan["protocol_sha256"]:
        raise ValueError("protocol bytes changed")
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(key) != "1":
            raise ValueError("single-thread environment required: " + key)
    return frozen, plan


def protected_files():
    """Hash sealed evidence without loading its data, metrics or labels."""
    run = ROOT / "runs/codex-cloud-core-c1-t2"
    manifest = read(run / "retained-manifest.json")
    protected = {str((run / row["file"]).relative_to(ROOT)): row["sha256"]
                 for row in manifest["files"]}
    paths = ("plan.json", "independent/plan.json", "core_confirmation/plan.json",
             "core_confirmation/core-c1-test-opened.json", "runs/codex-cloud-core-c1-t2/retained-manifest.json")
    protected.update({name: sha(ROOT / name) for name in paths})
    verify_protected(protected)
    return protected


def verify_protected(protected):
    if (ROOT / "independent/efficient-r2-test-opened.json").exists():
        raise ValueError("r2 formal marker appeared")
    for name, expected in protected.items():
        if sha(ROOT / name) != expected:
            raise ValueError("protected previous evidence changed: " + name)


def execute_slot(index, variant, freeze_path, run, console, reference):
    command = [sys.executable, "-m", "independent.run", "--experiment", "codec-train-d1", "train",
               "--freeze", str(freeze_path), "--out", str(run), "--variant", variant,
               "--build-index", str(index)]
    if reference is not None:
        command += ["--reference-receipt", str(reference)]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started, wall = utc(), time.perf_counter_ns()
    with console.open("x") as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"slot_index": index, "codec_variant": variant, "command": command,
               "started_utc": started, "completed_utc": utc(), "exit_code": result.returncode,
               "outer_wall_ns": time.perf_counter_ns() - wall,
               "full_child_cpu_ns": round(((after.ru_utime + after.ru_stime)
                   - (before.ru_utime + before.ru_stime)) * 1e9)}
    if run.is_dir():
        shutil.copyfile(console, run / "console.log")
        if sha(console) != sha(run / "console.log"):
            raise ValueError("console retention mismatch")
        console.unlink()
        write(run / "execution.json", receipt)
    return receipt


def risk_observation(paths, plan, out):
    """Report-only TRAIN monitor observation, never model selection or updates."""
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from model import JointModel
    from independent.accounting import WorkLedger
    from independent.inference import FrozenGenerator
    from independent.learning import CachedObjective

    started = time.process_time_ns()
    rows, values = [], {}
    for index, path in enumerate(paths):
        selection = read(path / "selection.json")
        with np.load(path / "train-evidence/monitor.npz", allow_pickle=False) as archive:
            x, labels = archive["full"], archive["labels"]
        for row in selection["selected"]:
            model_path = path / row["model_file"]
            if sha(model_path) != row["model_sha256"]:
                raise ValueError("risk report selected model changed")
            model = JointModel.load(model_path)
            before, ledger = model.digest(), WorkLedger("postbuild-risk-observer")
            generator = FrozenGenerator(model, prepare_low=False)
            p, q = generator.forward_full(x, ledger, stage="risk_report")
            objective = CachedObjective("N", model, rho=plan["rho"], ce_anchor=plan["ce_anchor"],
                                        ledger=ledger, stage="risk_report")
            risk = objective.utility_values(p, q, labels, ledger=ledger, stage="risk_report")
            if before != model.digest():
                raise ValueError("report-only observation changed content")
            key = f"slot{index}-{row['system']}-{row['seed']}"
            values[key] = risk
            rows.append({"slot_index": index, "system": row["system"], "seed": row["seed"],
                         "risk_mean": float(risk.mean()), "ledger": ledger.snapshot()})
    np.savez_compressed(out / "risk-observer-values.npz", **values)
    return {"schema": "hepta.codec-train-risk-report.v1", "rows": rows,
            "process_cpu_ns_after_numpy_import_through_array_persistence": time.process_time_ns() - started,
            "scope": "Additional report-only TRAIN monitor inference/observation; no update, selection or stop use. "
                     "R&D cost outside capped builds, never a budget credit; master CPU also retains imports."}


def main():
    entire_started, entire_own = utc(), time.process_time_ns()
    entire_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    frozen, plan = source_guard(args.freeze.resolve())
    out = args.out.resolve()
    expected = (ROOT / plan["training_diagnostic"]["output_root"]).resolve()
    if out != expected or out.exists():
        raise ValueError("fixed diagnostic output path exists or changed")
    protected = protected_files()
    import analyze
    started, own = utc(), time.process_time_ns()
    record = {"schema": "hepta.codec-train-once.v1", "experiment_id": "codec-train-d1",
              "started_utc": started, "source_commit": frozen["source_commit"],
              "plan_sha256": frozen["plan_sha256"], "freeze_sha256": sha(args.freeze),
              "environment_id": ENVIRONMENT, "cwd": str(ROOT), "output": str(out),
              "build_order": plan["training_diagnostic"]["build_order"],
              "protected_sha256": protected, "qualification_eligible": False}
    record.update(python_executable=sys.executable, python_version=sys.version,
        execution_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    write(DIRECTORY / "START.json", record)
    receipts, paths, attempted, fault = [], [], [], None
    reference = out / "reference.json"
    try:
        out.mkdir()
        for index, variant in enumerate(record["build_order"]):
            source_guard(args.freeze)
            verify_protected(protected)
            path = out / f"slot-{index}-{variant}"
            attempted.append(index)
            receipt = execute_slot(index, variant, args.freeze.resolve(), path,
                out / f"slot-{index}-console.log", None if index == 0 else reference)
            receipts.append(receipt)
            write(out / f"slot-{index}-execution.json", receipt)
            verify_protected(protected)
            if receipt["exit_code"] not in (0, 2) or not (path / "selection.json").is_file():
                raise RuntimeError(f"slot {index} hard failure; exit {receipt['exit_code']}")
            paths.append(path)
            audit = analyze.audit_builds(paths)
            write(out / f"audit-through-slot-{index}.json", audit)
            size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
            if size > plan["training_diagnostic"]["max_build_bytes"]:
                raise ValueError(f"slot {index} retained raw bytes {size} exceed frozen bound")
            if index == 0:
                selection = read(path / "selection.json")
                write(reference, {"schema": "hepta.codec-train-reference.v1", "experiment_id": "codec-train-d1",
                    "plan_sha256": frozen["plan_sha256"], "source_commit": frozen["source_commit"],
                    "freeze_sha256": sha(args.freeze), "first_selection_path": str(path / "selection.json"),
                    "first_selection_sha256": sha(path / "selection.json"),
                    "reference_full_cpu_ns": selection["common"]["reference_full_cpu_ns"]})
        summary = analyze.describe_builds(paths)
        risk = risk_observation(paths, plan, out)
        write(out / "risk-observer.json", risk)
        summary["additional_risk_observer"] = "risk-observer.json"
        by_identity = {(row["slot_index"], row["system"], row["seed"]): row["risk_mean"] for row in risk["rows"]}
        for pair in summary["pairs"]:
            for system, report in pair["methods"].items():
                values = [by_identity[(pair["cached_index"], system, seed)]
                    - by_identity[(pair["rowwise_index"], system, seed)] for seed in (11, 23, 47)]
                report["across_seeds"]["entropic_risk"] = analyze._spread(values)
        summary["missing_riskfield"] = False
        summary["risk_status"] = "Separate report-only TRAIN observer, fully retained as additional R&D."
        summary["conclusion"] = {
            "engineering_directions_met": all(summary["engineering_directions"].values())
                and summary["audit"]["prefix_complete"],
            "prefix_complete": summary["audit"]["prefix_complete"],
            "engineering_directions": summary["engineering_directions"],
            "scientific_benefit_confirmed": False,
            "scope": "Predeclared engineering directions only. Every monitor outcome remains reported; "
                     "more updates or lower cost does not establish content/NDU/dynamic benefit."}
        write(out / "comparison.json", summary)
        verify_protected(protected)
    except BaseException as error:
        fault = {"type": type(error).__name__, "error": str(error)}
    terminal = {**record, "completed_utc": utc(), "build_receipts": receipts,
                "attempted_slots": attempted,
                "unexecuted_slots": [index for index in range(4) if index not in attempted],
                "attempted_without_returned_receipt": [index for index in attempted
                    if index not in {row["slot_index"] for row in receipts}], "fault": fault,
                "master_own_cpu_ns_since_start": time.process_time_ns() - own,
                "full_child_cpu_ns": sum(row["full_child_cpu_ns"] for row in receipts),
                "scope": "TRAIN-only development comparison; no formal confirmation or AV. "
                         "Master analysis/risk/retention CPU is separate R&D, not a capped-model credit."}
    all_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    terminal.update(entire_entry_utc=entire_started,
        master_own_cpu_ns_since_entry=time.process_time_ns() - entire_own,
        all_child_cpu_ns_since_entry=round(((all_children.ru_utime + all_children.ru_stime)
            - (entire_children.ru_utime + entire_children.ru_stime)) * 1e9))
    if fault is None:
        terminal["diagnostic_summary"] = summary["conclusion"]
        terminal["exit_code"] = 0 if summary["conclusion"]["engineering_directions_met"] else 2
    else:
        terminal["exit_code"] = 1
    payload = sum(path.stat().st_size for path in out.rglob("*")
        if path.is_file() and not any(path.is_relative_to(build) for build in paths))
    # A failed slot can have artifacts without a complete selection/path entry.
    for index in attempted:
        child = out / f"slot-{index}-{record['build_order'][index]}"
        if child not in paths:
            payload -= sum(path.stat().st_size for path in child.rglob("*") if path.is_file())
    payload += sum(path.stat().st_size for path in DIRECTORY.glob("*.json")
        if path.name == "START.json" or path.name.startswith("SLOT-"))
    reserve = 2 * len(json.dumps(terminal, sort_keys=True, indent=2).encode()) + 4096
    terminal.update(master_retained_payload_bytes_before_terminal=payload,
                    reserved_terminal_bytes=reserve)
    if payload + reserve > plan["training_diagnostic"]["max_master_bytes"]:
        terminal["fault"] = terminal["fault"] or {"type": "ValueError", "error": "master retained-byte bound exceeded"}
        terminal["exit_code"] = 1
    terminal = persist_terminal(out, terminal)
    print(json.dumps({key: terminal[key] for key in ("exit_code", "fault", "unexecuted_slots")}, sort_keys=True))
    return terminal["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
