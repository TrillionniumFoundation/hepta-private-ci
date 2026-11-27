"""Create-only deployment and exact-identity launch of the separately approved C2.

The caller wraps this entire process in GNU time. This bootstrap performs no
model forward/backward/step and execs the frozen controller exactly once.
"""
from __future__ import annotations

import os
import time

STARTED = time.monotonic()

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import resource
import stat
import sys
import traceback
import zipfile

SOURCE_SHA = "95d53c9a8fd7b6d0d60388b29d58519160c1d04357069bd805e5f4bfa2c91079"
MANIFEST_SHA = "322eb8f76cce589ba44ed66eff822f7b497e6507106a1ad56a65bdc8c83f7f57"
CONTRACT_SHA = "bc814b8913f5d5777f771030623bcd1f862a526f35144a8da0164e1da60f8e51"
DECISION_SHA = "bee192193f0f12599f783f348b6dea8c10b2a18df359487c3cc0c0c44d071370"
EXPECTED_NAMES = [f"hcsn-s{seed}-lr{lr}" for seed in (101, 211, 307) for lr in ("0.001", "0.003")]


def identity(path: Path | str) -> dict:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("expected a regular original file: " + str(path))
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write(path: Path, value: object) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def extract(archive: Path, target: Path) -> dict:
    if identity(archive) != {"bytes": 209455, "sha256": SOURCE_SHA}:
        raise ValueError("v4 source capsule changed")
    with zipfile.ZipFile(archive) as zipped:
        infos = zipped.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or sum(info.file_size for info in infos) > 8 * 1024**2:
            raise ValueError("duplicate or oversized source capsule")
        for info in infos:
            name = PurePosixPath(info.filename)
            if (name.is_absolute() or ".." in name.parts or "\\" in info.filename
                    or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("unsafe source member")
        if zipped.testzip() is not None:
            raise ValueError("source CRC failed")
        target.mkdir(exist_ok=False)
        for info in infos:
            path = target / info.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(zipped.read(info))
    manifest = target / "PROGRAM-MANIFEST.json"
    if identity(manifest)["sha256"] != MANIFEST_SHA:
        raise ValueError("v4 manifest changed")
    expected = json.loads(manifest.read_bytes())["files"]
    if set(names) != set(expected) | {"PROGRAM-MANIFEST.json"}:
        raise ValueError("capsule/manifest roster mismatch")
    for name, value in expected.items():
        if identity(target / name) != value:
            raise ValueError("extracted source mismatch: " + name)
    return {str(target / name): identity(target / name) for name in names}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--controller-output", type=Path, required=True)
    parser.add_argument("--bootstrap-output", type=Path, required=True)
    args = parser.parse_args()
    out = args.bootstrap_output.resolve()
    out.mkdir(exist_ok=False)
    report = {
        "schema": "hcsn-c2-native-execution-bootstrap-v1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "status": "preparing_exact_source",
        "automatic_retry": False,
        "bootstrap_model_forward_backward_optimizer_steps": 0,
        "controller_execution_intended": True,
        "scientific_admission": "HOLD",
        "numerical_admission": "HOLD",
        "original_directories_written": False,
        "source_capsule": identity(args.source_archive),
        "decision": identity(args.decision),
        "bootstrap_program": identity(__file__),
        "host_observation": {
            "cpu_count": os.cpu_count(), "load_average": list(os.getloadavg()),
            "nice": os.getpriority(os.PRIO_PROCESS, 0),
            "memory_info_original": Path("/proc/meminfo").read_text(),
            "available_filesystem_bytes": os.statvfs(out).f_bavail * os.statvfs(out).f_frsize,
        },
        "argv": sys.argv,
    }
    write(out / "INTENT.json", report)
    try:
        if report["decision"] != {"bytes": 7524, "sha256": DECISION_SHA}:
            raise ValueError("root decision bytes changed")
        if args.controller_output.exists():
            raise ValueError("controller output already exists; no automatic repeat")
        program = args.program.resolve()
        report["program_source_before"] = extract(args.source_archive, program)
        sys.path.insert(0, str(program))
        from c2_controller import verify_roster
        from c2_io import runtime_identity
        from c2_runner import bind_program, require_decision
        manifest, contract_path = program / "PROGRAM-MANIFEST.json", program / "CONTRACT.json"
        if identity(contract_path)["sha256"] != CONTRACT_SHA:
            raise ValueError("frozen contract differs")
        report["bound_program_inputs"] = bind_program(manifest)
        decision = require_decision(args.decision, DECISION_SHA, contract_path, manifest)
        contract = json.loads(contract_path.read_bytes())
        if (decision["fit_names"] != EXPECTED_NAMES or contract["fit_names"] != EXPECTED_NAMES
                or (decision["workers"], contract["workers"]) != (6, 6)
                or contract["cumulative_active_wall_seconds"] != 43200
                or contract["maximum_epochs"] != 200 or contract["finalization_reserve_seconds"] != 600):
            raise ValueError("approved roster or fixed resource policy differs")
        if contract["python"] != sys.executable:
            raise ValueError("bootstrap interpreter differs from approved original runtime")
        runtime_path = Path(contract["runtime_identity_path"])
        if identity(runtime_path)["sha256"] != contract["runtime_identity_sha256"]:
            raise ValueError("original runtime receipt changed")
        report["actual_runtime"] = runtime_identity()
        if report["actual_runtime"] != json.loads(runtime_path.read_bytes()):
            raise ValueError("actual runtime differs from the original training runtime")
        parent_result = Path(contract["parent_campaign"]) / "RESULT.json"
        parent_plan = Path(contract["parent_campaign_plan"])
        if (identity(parent_result)["sha256"] != contract["parent_campaign_result_sha256"]
                or identity(parent_plan)["sha256"] != contract["parent_campaign_plan_sha256"]):
            raise ValueError("original parent roster/plan changed")
        report["parent_result"] = identity(parent_result)
        report["parent_plan"] = identity(parent_plan)
        parents = verify_roster(contract, json.loads(parent_result.read_bytes()))
        report["eligible_parent_outer_records"] = parents
        command = [contract["python"], "-B", str(program / "c2_controller.py"),
            "--contract", str(contract_path), "--program-manifest", str(manifest),
            "--output", str(args.controller_output.resolve()), "--execute",
            "--decision", str(args.decision.resolve()), "--decision-sha256", DECISION_SHA]
        report.update(status="verified_ready_to_exec_once", controller_command=command,
            bootstrap_wall_seconds=time.monotonic() - STARTED,
            bootstrap_cpu_seconds=time.process_time(),
            bootstrap_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            whole_process_cost_scope="The caller's GNU time includes bootstrap, exec, controller and all children; overlapping controller/wait4 views are not additive.")
        write(out / "READY.json", report)
        print(json.dumps({"status": report["status"], "ready_receipt": str(out / "READY.json"),
            "controller_output": str(args.controller_output), "pid": os.getpid()}), flush=True)
        os.execv(command[0], command)
    except BaseException:
        report.update(status="bootstrap_failed_before_controller_exec", error=traceback.format_exc(),
            bootstrap_wall_seconds=time.monotonic() - STARTED,
            bootstrap_cpu_seconds=time.process_time(),
            bootstrap_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        write(out / "RESULT.json", report)
        raise


if __name__ == "__main__":
    main()
