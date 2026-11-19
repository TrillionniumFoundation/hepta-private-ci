"""Measure the complete child and preserve every artifact in one bounded phase."""

import base64
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import zipfile

from io_contract import identity, require, save, verify_sources


def main(root, stage_started):
    request = json.loads((root / "REQUEST.json").read_text())
    cap = request["budget"]["whole_seconds"]
    resource.setrlimit(resource.RLIMIT_AS, (request["budget"]["address_space_bytes"],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (cap,) * 2)
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    verify_sources(root)
    child_started = time.monotonic()
    with (root / "child.stdout").open("xb") as stdout, (root / "child.stderr").open("xb") as stderr:
        child = subprocess.Popen([sys.executable, "-B", str(root / "runner.py"), str(root), str(stage_started)],
                                 stdout=stdout, stderr=stderr, cwd=root, start_new_session=True)
        killed = False
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() - stage_started >= cap - 15:
                os.killpg(child.pid, signal.SIGKILL); killed = True
                _, status, usage = os.wait4(child.pid, 0); break
            time.sleep(.05)
        child.returncode = os.waitstatus_to_exitcode(status)
    child_cost = {"schema": "full-D-calibration-child-cost-v1", "exit_code": child.returncode, "killed_at_phase_limit": killed,
                  "full_child_wall_seconds": time.monotonic() - child_started,
                  "full_child_cpu_seconds": usage.ru_utime + usage.ru_stime, "child_peak_rss_kib": usage.ru_maxrss,
                  "includes": "Python child startup, imports, runtime/input verification, all attempted fits, independent arithmetic, receipts and child finalization",
                  "excludes": "Native service startup, supervisor setup/archive, controller transport and publication",
                  "stdout": identity(root / "child.stdout"), "stderr": identity(root / "child.stderr")}
    save(root / "CHILD_COST.json", child_cost)
    source = verify_sources(root)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    require(all(not p.is_symlink() for p in files), "regular archive entries")
    expected = {str(p.relative_to(root)): identity(p) for p in files}
    archive = root / "calibration-originals.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for path in files:
            handle.write(path, arcname=str(path.relative_to(root)))
    with zipfile.ZipFile(archive) as handle:
        require(set(handle.namelist()) == set(expected), "complete archive members")
        import hashlib
        for name, record in expected.items():
            require(hashlib.sha256(handle.read(name)).hexdigest() == record["sha256"], "lossless archive member")
    encoded_parts = []
    with archive.open("rb") as stream:
        index = 0
        while block := stream.read(45000):
            path = root / ("archive-part-%03d.b64" % index)
            with path.open("xb") as target:
                target.write(base64.b64encode(block) + b"\n")
            encoded_parts.append(identity(path)); index += 1
    archive_record = {"schema": "D-temperature-originals-transport-v1", "archive": identity(archive),
                      "members": expected, "parts": encoded_parts, "all_member_hashes_match": True}
    save(root / "ARCHIVE.json", archive_record)
    elapsed = time.monotonic() - stage_started
    final = {"schema": "bounded-D-calibration-stage-terminal-v1", "child": child_cost, "source_freeze": source,
             "archive": identity(root / "ARCHIVE.json"), "stage_elapsed_before_terminal_receipt_seconds": elapsed,
             "whole_stage_cap_seconds": cap, "within_phase_cap_before_terminal_write": elapsed < cap,
             "cost_scope": "From dispatch wrapper monotonic timestamp after its standard-library imports through archive/transport-file creation; native startup and final terminal serialization/exit remain outside this timer.",
             "source_parent_commit": request["source_parent_commit"], "E_access": False, "E_execution_authorized": False,
             "scientific_admission": "HOLD", "automatic_retries": 0}
    save(root / "STAGE_TERMINAL.json", final)
    print(json.dumps(final, sort_keys=True), flush=True)
    return child.returncode if elapsed < cap else 2


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), float(sys.argv[2])))
