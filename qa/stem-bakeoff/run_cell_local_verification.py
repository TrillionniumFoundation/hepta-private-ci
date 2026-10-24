"""Run the preserved local integration suite plus every new phase test once.

The legacy operation observer runs under its pinned Python3.8 environment; the
model/interface/learning tests run under the pinned ML environment. No remote
workflow or CI status is queried. Run repository formatting after this gate.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

BASE = "4b3081c25af86f707a5c0d50c688c959a04af446"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def worker(modules, output):
    loader = unittest.TestLoader()
    suites = {name: loader.loadTestsFromName(name) for name in modules}
    counts = {name: suite.countTestCases() for name, suite in suites.items()}
    started = time.perf_counter_ns()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites.values()))
    report = {"modules": modules, "module_test_counts": counts, "planned_tests": sum(counts.values()),
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses), "loader_errors": list(loader.errors),
        "elapsed_seconds": (time.perf_counter_ns()-started)/1e9,
        "executable": sys.executable, "python": platform.python_version(),
        "failures_detail": [{"test": str(test), "traceback": error} for test, error in result.failures],
        "errors_detail": [{"test": str(test), "traceback": error} for test, error in result.errors]}
    report["success"] = (result.wasSuccessful() and result.testsRun == sum(counts.values())
        and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses and not loader.errors)
    write(output, report)
    return report


def run(repo, previous_plan, observer_python, output):
    repo, output = Path(repo), Path(output)
    source = repo / "qa/stem-bakeoff"
    previous = json.loads(Path(previous_plan).read_bytes())
    if len(previous["modules"]) != 31 or previous["planned_tests"] != 195:
        raise ValueError("preserve the exact previous195-test/31-module local plan")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()
    untracked = git("ls-files", "--others", "--exclude-standard", "--", "qa/stem-bakeoff").splitlines()
    if any(Path(path).parent.as_posix() == "qa/stem-bakeoff" and path.endswith((".py", ".md", ".json", ".txt")) for path in untracked):
        raise ValueError("all direct research source/config files must be committed before final verification")
    added = git("diff", "--name-only", "--diff-filter=A", BASE, "HEAD", "--", "qa/stem-bakeoff").splitlines()
    new_modules = [Path(path).stem for path in added if Path(path).parent.as_posix() == "qa/stem-bakeoff"
                   and Path(path).name.startswith("test_") and path.endswith(".py")]
    modules = sorted(set(previous["modules"]) | set(new_modules))
    if "test_operational_observer" not in modules or len(new_modules) < 20:
        raise ValueError("new local phase integration test inventory is incomplete")
    def hashes():
        paths = [p for p in source.iterdir() if p.is_file() and p.suffix in (".py", ".md", ".json", ".txt", ".sh")]
        return {str(p.relative_to(repo)): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(paths)}
    before, head = hashes(), git("rev-parse", "HEAD")
    output.mkdir(parents=True, exist_ok=False)
    write(output / "source_hashes_before.json", before)
    groups = {"ml": (sys.executable, [m for m in modules if m != "test_operational_observer"]),
              "legacy-observer": (observer_python, ["test_operational_observer"])}
    plan = {"schema": "hepta.cell-local-final-verification.v1", "baseline": BASE,
        "preserved_plan_sha256": sha(previous_plan), "runner_sha256": sha(__file__),
        "git_head_before": head, "git_tree": git("rev-parse", "HEAD^{tree}"),
        "module_groups": {name: {"python": str(python), "modules": items} for name, (python, items) in groups.items()},
        "source_files": len(before), "remote_ci_queried": False, "started_at_ns": time.time_ns()}
    write(output / "verification_plan.json", plan)
    results = {}
    for name, (python, items) in groups.items():
        command = [str(python), str(Path(__file__).absolute()), "--worker", "--modules", ",".join(items),
                   "--output", str(output / (name + ".json"))]
        environment = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        with (output / (name + ".log")).open("x") as log:
            completed = subprocess.run(command, cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT)
        result_path = output / (name + ".json")
        results[name] = json.loads(result_path.read_bytes()) if result_path.exists() else {
            "success": False, "tests_run": 0, "failures": 0, "errors": 1, "skipped": 0,
            "error": "worker terminated before producing its report"}
        results[name]["process_exit_code"] = completed.returncode
    after = hashes()
    write(output / "source_hashes_after.json", after)
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    report = {"schema": plan["schema"], "groups": results, "module_count": len(modules),
              "tests_run": sum(r["tests_run"] for r in results.values()),
              "failures": sum(r["failures"] for r in results.values()), "errors": sum(r["errors"] for r in results.values()),
              "skipped": sum(r["skipped"] for r in results.values()), "changed_source_files": changed,
              "git_head_after": git("rev-parse", "HEAD"), "finished_at_ns": time.time_ns(),
              "remote_ci_queried": False, "quality_qualification": False}
    report["success"] = (all(r["success"] and r["process_exit_code"] == 0 for r in results.values())
        and not changed and report["git_head_after"] == head and report["tests_run"] >= 195)
    write(output / "verification_summary.json", report)
    write(output / "manifest.json", {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)}
                                     for p in sorted(output.iterdir()) if p.is_file()})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--modules")
    for name in ("repo", "previous-plan", "observer-python"):
        parser.add_argument("--" + name)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = worker(args.modules.split(","), args.output) if args.worker else run(
        args.repo, args.previous_plan, args.observer_python, args.output)
    print(json.dumps({key: report[key] for key in ("tests_run", "failures", "errors", "skipped", "success")}))
    raise SystemExit(0 if report["success"] else 1)
