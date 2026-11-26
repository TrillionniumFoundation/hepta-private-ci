"""Run the unchanged retained arithmetic verifier once in an isolated view."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import resource
import signal
import subprocess
import sys
import time
import traceback


EXPECTED = {
    "read_only": True,
    "retained_runs": 4,
    "retained_query_rows": 24,
    "quantity_error_rows": 192,
    "new_analytic_reference_calls": 0,
    "new_model_calls": 0,
    "new_spatial_or_dde_runs": 0,
    "status": "HOLD_NO_GO",
}
CHILD = r'''
import json, platform, resource, runpy, sys
resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
resource.setrlimit(resource.RLIMIT_AS, (1_073_741_824, 1_073_741_824))
resource.setrlimit(resource.RLIMIT_FSIZE, (8_388_608, 8_388_608))
if sys.version_info[:2] != (3, 12) or sys.flags.optimize:
    raise RuntimeError("original Python 3.12 workflow family without -O required")
forbidden = {"qualification", "torch", "scipy", "mpmath"}
class RejectModelImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in forbidden:
            raise RuntimeError("model/oracle import forbidden: " + fullname)
        return None
sys.meta_path.insert(0, RejectModelImports())
import numpy as np
if np.__version__ != "2.3.5":
    raise RuntimeError("original NumPy 2.3.5 required")
print(json.dumps({"kind": "runtime", "python": platform.python_version(),
                  "numpy": np.__version__, "optimize": sys.flags.optimize}), flush=True)
print(json.dumps({"kind": "verifier_start", "path": sys.argv[1]}), flush=True)
runpy.run_path(sys.argv[1], run_name="__main__")
present = sorted(k for k in sys.modules if k.split(".", 1)[0] in forbidden)
if present:
    raise RuntimeError("unexpected model/oracle module present")
print(json.dumps({"kind": "imports_checked", "forbidden_modules_present": present}), flush=True)
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def inspect_snapshot(base, snapshot):
    assembly_bytes = (base / "ASSEMBLY.json").read_bytes()
    assembly = json.loads(assembly_bytes)
    index_bytes = (snapshot / "INDEX.json").read_bytes()
    index = json.loads(index_bytes)
    require(index["status"] == "BYTE_BINDING_PASS_NUMERICS_NOT_RUN", "byte gate missing")
    require(index["assembly_sha256"] == sha(assembly_bytes), "assembly binding differs")
    require(index["materializer_sha256"] == sha((base / "materialize_frozen_views.py").read_bytes()),
            "materializer binding differs")
    entries = assembly["profiles"]["firstcycle"]
    records = {entry["path"]: entry for entry in index["profiles"]["firstcycle"]}
    require(len(entries) == len(records) == 22, "retained file denominator differs")
    view = snapshot / "firstcycle"
    hashes = {}
    for entry in entries:
        name = entry["path"]
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts and "\\" not in name
                and str(path) == name, "invalid retained relative path")
        require(name not in hashes, "duplicate retained path")
        location = view / name
        require(not location.is_symlink() and location.resolve().is_relative_to(view.resolve()),
                "retained path escapes isolated view")
        raw = location.read_bytes()
        require(len(raw) <= 2_000_000, "retained input exceeds fixed size cap")
        digest = sha(raw)
        require(blob(raw) == entry["git_blob_sha1"], "retained Git blob differs: " + name)
        require(digest == records[name]["sha256"], "materialized SHA256 differs: " + name)
        require(entry["sha256"] is None or digest == entry["sha256"],
                "original SHA256 pin differs: " + name)
        hashes[name] = digest
    require({str(p.relative_to(view)) for p in view.rglob("*") if p.is_file()} == set(hashes),
            "isolated retained view contains unexpected files")
    hashes["../INDEX.json"] = sha(index_bytes)
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    snapshot = args.snapshot.expanduser().resolve()
    output = args.output.expanduser().resolve()
    require(not output.is_relative_to(snapshot), "result must be outside immutable snapshot")
    output.mkdir(parents=False, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    process = None
    before, after, events = None, None, []
    result = {"schema": "retained-firstcycle-isolated-readback-v1", "status": "FAILED",
              "scientific_status": "HOLD_NO_GO", "whole_repository_qualified": False,
              "new_model_calls": 0, "new_oracle_calls": 0, "new_training_calls": 0,
              "new_spatial_or_dde_runs": 0, "original_manifest_edits": 0,
              "production_source_overwrites": 0, "child_processes_started": 0,
              "wrapper_python": platform.python_version(), "error": None}
    try:
        require(sys.platform.startswith("linux"), "registered Linux limits required")
        require(sys.version_info[:2] == (3, 12) and not sys.flags.optimize,
                "original workflow Python 3.12 family without -O required")
        before = inspect_snapshot(base, snapshot)
        script = snapshot / "firstcycle/qualification/hcsn_firstcycle_review/verify_retained.py"
        environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                           MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
        command = [sys.executable, "-I", "-B", "-c", CHILD, str(script)]
        with (output / "verifier.stdout").open("xb") as stdout, \
                (output / "verifier.stderr").open("xb") as stderr:
            process = subprocess.Popen(command, cwd=snapshot / "firstcycle", env=environment,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            result["child_processes_started"] = 1
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
                raise TimeoutError("single retained verifier exceeded 45 seconds") from None
        result["exit_code"] = process.returncode
        lines = (output / "verifier.stdout").read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.strip():
                events.append(json.loads(line))
        after = inspect_snapshot(base, snapshot)
        require(process.returncode == 0, "original retained verifier failed")
        require(len(events) == 4, "unexpected verifier output denominator")
        require(events[0]["kind"] == "runtime" and events[0]["numpy"] == "2.3.5"
                and events[0]["optimize"] == 0, "runtime readback differs")
        require(events[1] == {"kind": "verifier_start", "path": str(script)},
                "original verifier entry differs")
        require(events[2] == EXPECTED, "original retained result differs")
        require(events[3] == {"kind": "imports_checked", "forbidden_modules_present": []},
                "model/oracle import exclusion failed")
        require(before == after, "isolated sources/evidence changed during verification")
        result.update(status="RETAINED_CUSTODY_ARITHMETIC_PASS", runtime=events[0],
                      original_verifier_result=events[2], raw_npz_archives_loaded=4)
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc),
                           "traceback": traceback.format_exc()}
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        if before is not None and after is None:
            try:
                after = inspect_snapshot(base, snapshot)
            except Exception as exc:
                result["post_source_check_error"] = str(exc)
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if not events and (output / "verifier.stdout").exists():
        for line in (output / "verifier.stdout").read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                events.append(json.loads(line))
            except (ValueError, TypeError):
                result["unparsed_stdout_line_present"] = True
    result.update(source_before=before, source_after=after,
                  source_unchanged=before is not None and before == after,
                  original_verifier_start_records=sum(
                      isinstance(event, dict) and event.get("kind") == "verifier_start"
                      for event in events),
                  wall_seconds=time.perf_counter() - start,
                  wrapper_cpu_seconds=time.process_time() - cpu,
                  child_cpu_seconds=(usage_after.ru_utime + usage_after.ru_stime)
                  - (usage_before.ru_utime + usage_before.ru_stime),
                  child_peak_rss_kib=usage_after.ru_maxrss,
                  wrapper_sha256=sha(Path(__file__).read_bytes()),
                  stdout_sha256=sha((output / "verifier.stdout").read_bytes())
                  if (output / "verifier.stdout").exists() else None,
                  stderr_sha256=sha((output / "verifier.stderr").read_bytes())
                  if (output / "verifier.stderr").exists() else None)
    with (output / "RESULT.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "scientific_status": "HOLD_NO_GO",
                      "error": result["error"]}, sort_keys=True))
    return 0 if result["status"] == "RETAINED_CUSTODY_ARITHMETIC_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
