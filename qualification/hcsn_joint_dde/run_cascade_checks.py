"""Retain exact-source complete native Torch test receipts, including failures."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    files = ["qualification/hcsn_joint_dde/"+name for name in
             ("torch_cascade.py", "test_torch_cascade.py", "run_cascade_checks.py", "model.py")]
    files += ["qualification/hcsn_boundary_audit/"+name for name in
              ("spatial_generator.py", "refractory_transport.py")]

    def hashes():
        return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}

    before = hashes()
    command = [sys.executable, "-B", "-m", "unittest",
               "qualification.hcsn_joint_dde.test_torch_cascade", "-v"]
    preexecution = dict(source_sha256=before, command=command,
        runtime=dict(python=platform.python_version(), **{name: importlib.metadata.version(name)
                     for name in ("torch", "numpy", "scipy")}), timeout_seconds=600)
    (args.output/"PREEXECUTION.json").write_text(json.dumps(preexecution, indent=2, sort_keys=True)+"\n")
    wall, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    failure = None
    try:
        child = subprocess.run(command, cwd=root, capture_output=True, timeout=600, check=False)
        code, stdout, stderr = child.returncode, child.stdout, child.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr, failure = None, exc.stdout or b"", exc.stderr or b"", "timeout"
    (args.output/"stdout.log").write_bytes(stdout)
    (args.output/"stderr.log").write_bytes(stderr)
    after, child_usage = hashes(), resource.getrusage(resource.RUSAGE_CHILDREN)
    text = stderr.decode("utf-8", errors="replace")
    count = re.search(r"Ran (\d+) tests? in", text)
    success = (code == 0 and before == after and count and int(count.group(1)) == 6
               and not re.search(r"skipped|expected failure|unexpected success", text, re.I)
               and re.search(r"\nOK\s*\Z", text))
    report = dict(schema="hcsn-torch-cascade-checks-v1", source_before=before, source_after=after,
        source_unchanged=before == after, command=command, returncode=code, failure=failure,
        tests=int(count.group(1)) if count else 0, complete_no_skip_pass=bool(success),
        stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        wall_seconds=time.perf_counter()-wall,
        child_cpu_seconds=child_usage.ru_utime+child_usage.ru_stime-usage.ru_utime-usage.ru_stime,
        child_peak_rss_kib=child_usage.ru_maxrss, runtime=preexecution["runtime"],
        scope="finite uniform-mesh CPU FP64 autograd research oracle",
        graded_mesh_gradients=False, network_training=False, independent_future=0,
        full_hcsn_qualification=False, production_qualified=False)
    (args.output/"RESULT.json").write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
