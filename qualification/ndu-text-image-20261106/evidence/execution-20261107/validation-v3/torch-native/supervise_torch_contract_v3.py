"""Run one immutable, bounded CPU engineering-contract qualification."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import signal
import stat
import subprocess
import sys
import time
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--supervisor-sha256", required=True)
    args = parser.parse_args()
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    started_at = datetime.now(timezone.utc).isoformat()
    base = args.base.resolve(strict=True)
    archive, manifest_path = base / "final-source-v3.zip", base / "FINAL_SOURCE_MANIFEST_V3.json"
    assert sha(Path(__file__)) == args.supervisor_sha256, "Supervisor hash changed"
    assert sha(archive) == args.bundle_sha256, "Bundle hash mismatch"
    assert sha(manifest_path) == args.manifest_sha256, "Manifest hash mismatch"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["bundle_sha256"] == args.bundle_sha256
    assert manifest["bundle_bytes"] == archive.stat().st_size
    expected = manifest["source_files"]
    source = base / "source"
    source.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == set(expected), "Bundle file inventory mismatch"
        assert len(zipped.namelist()) == len(expected), "Duplicate ZIP entries"
        for member in zipped.infolist():
            name = PurePosixPath(member.filename)
            assert not name.is_absolute() and ".." not in name.parts
            assert not member.is_dir() and not member.flag_bits & 1
            assert not stat.S_ISLNK(member.external_attr >> 16)
            content = zipped.read(member)
            assert hashlib.sha256(content).hexdigest() == expected[member.filename]
            target = source / member.filename
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(content)
    before = {name: sha(source / name) for name in expected}
    assert before == expected
    save(base / "source-admission.json", {
        "schema": "ndu-torch-source-admission-v1", "started_at": started_at,
        "bundle_sha256": args.bundle_sha256, "manifest_sha256": args.manifest_sha256,
        "supervisor_sha256": args.supervisor_sha256, "source_files": before,
        "source_matches_supplied_manifest": True, "file_count": len(before),
        "scope": "Engineering contract inputs only; no scientific admission."
    })
    output = base / "qualification"
    argv = [sys.executable, "-B", "-m", "ndu_portfolio.qualify_text_image", "--require-torch",
            "--torch-only", "--output", str(output)]
    child_env = dict(os.environ)
    child_env.update(PYTHONPATH=str(source / "scripts"), PYTHONDONTWRITEBYTECODE="1",
                     PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                     OPENBLAS_NUM_THREADS="1")
    child_start = time.perf_counter()
    usage_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    with (base / "stdout.bin").open("xb") as out, (base / "stderr.bin").open("xb") as err:
        proc = subprocess.Popen(argv, cwd=source, env=child_env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=err, start_new_session=True)
        try:
            returncode = proc.wait(timeout=240)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                returncode = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                returncode = proc.wait()
    child_wall = time.perf_counter() - child_start
    usage_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    after = {name: sha(source / name) for name in expected}
    receipt = json.loads((output / "receipt.json").read_text()) if (output / "receipt.json").is_file() else None
    passed = (returncode == 0 and not timed_out and before == after == expected
              and receipt is not None and receipt["status"] == "PASS_CONTRACTS"
              and receipt["tests_run"] == 3 and receipt["failures"] == receipt["errors"] == 0
              and receipt["skipped"] == [] and receipt["require_torch"] is True
              and receipt["torch_only"] is True and receipt["source_before"] == expected
              and receipt["source_after"] == expected)
    artifacts = {}
    for path in [base / "source-admission.json", base / "stdout.bin", base / "stderr.bin",
                 output / "receipt.json", output / "tests.log"]:
        if path.is_file():
            artifacts[str(path.relative_to(base))] = {"sha256": sha(path), "bytes": path.stat().st_size}
    result = {
        "schema": "ndu-torch-supervised-execution-v1", "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_ENGINEERING_CONTRACTS" if passed else "FAILED_ENGINEERING_CONTRACTS",
        "argv": argv, "cwd": str(source), "python_executable_sha256": sha(Path(sys.executable).resolve()),
        "bundle_sha256": args.bundle_sha256, "manifest_sha256": args.manifest_sha256,
        "supervisor_sha256": args.supervisor_sha256, "source_before": before, "source_after": after,
        "source_matches_supplied_manifest": before == after == expected,
        "returncode": returncode, "timed_out": timed_out, "child_pid": proc.pid,
        "child_wall_seconds": child_wall,
        "child_user_cpu_seconds": usage_end.ru_utime - usage_start.ru_utime,
        "child_system_cpu_seconds": usage_end.ru_stime - usage_start.ru_stime,
        "child_peak_rss_bytes": usage_end.ru_maxrss * 1024,
        "supervisor_wall_seconds_so_far": time.perf_counter() - wall_start,
        "supervisor_cpu_seconds_so_far": time.process_time() - cpu_start,
        "timing_scope": "Child includes Python startup/imports/test/report exit; wrapper measurement excludes its interpreter startup, final summary write and Hepta transport.",
        "maxrss_scope": "Linux RUSAGE_CHILDREN high-water RSS; this supervisor started exactly one child.",
        "limits_requested": {"wall_seconds": 240, "hepta_wall_seconds": 300,
                             "cpu_quota_percent": 100, "memory_max_bytes": 2147483648, "nice": 10},
        "unknown_costs": {"energy_joules": None, "provider_charges": None,
                          "prior_setup_cpu_seconds": None, "transfer_cpu_seconds": None,
                          "shared_host_overhead": None},
        "full_research_or_deployment_cost_complete": False,
        "gpu_allocated": False, "new_dependencies_installed": False,
        "scientific_admission": "HOLD", "real_models_executed": False,
        "scope": "Three Torch CPU contract tests; not a real frozen/joint factorial experiment.",
        "artifacts": artifacts,
    }
    save(base / "execution.json", result)
    print(json.dumps({key: result[key] for key in ("status", "returncode", "timed_out",
          "source_matches_supplied_manifest", "child_wall_seconds", "child_user_cpu_seconds",
          "child_system_cpu_seconds", "child_peak_rss_bytes")}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
