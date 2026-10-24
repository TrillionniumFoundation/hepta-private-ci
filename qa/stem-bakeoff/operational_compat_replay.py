"""Uniform compatibility replay of entire affected repositories, without source repairs.

Original outcomes remain immutable. This condition supplies declared test/build
dependencies, a legacy pytest API, plain Python assertions, and Black's normal
version-file generation. The semantic transition gate is imported unchanged.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import operational_execute as execution
from operational_cohort_plan import canonical, digest

AFFECTED_PROJECTS = ("thefuck", "luigi", "PySnooper", "black")
ORIGINAL_EXECUTE = execution.execute_command


def compatibility_execute(command, python, cwd, output, limits):
    output, cwd = Path(output), Path(cwd)
    output.parent.mkdir(parents=True, exist_ok=True)
    adapted = {**command, "args": list(command["args"])}
    compatibility = {"original_args": command["args"], "source_implementation_changed": False,
        "assertion_policy": "native Python assert statements remain active; only pytest AST rewriting disabled",
        "build": None}
    if command["runner"] == "pytest":
        adapted["args"] = ["--assert=plain", *adapted["args"]]
    if cwd.parent.name.startswith("black-"):
        code = ("import resource,runpy,sys;"
            f"resource.setrlimit(resource.RLIMIT_CPU,({limits['cpu_seconds']},{limits['cpu_seconds'] + 1}));"
            f"resource.setrlimit(resource.RLIMIT_AS,({limits['address_space_bytes']},{limits['address_space_bytes']}));"
            f"resource.setrlimit(resource.RLIMIT_FSIZE,({limits['log_file_bytes']},{limits['log_file_bytes']}));"
            "sys.argv=['setup.py','--version'];runpy.run_path('setup.py',run_name='__main__')")
        argv = [str(python), "-c", code]
        logs = {kind: output.parent / (output.name + ".build." + kind + ".log") for kind in ("stdout", "stderr")}
        start, timeout = time.perf_counter_ns(), False
        env = {"PATH": str(Path(python).parent) + os.pathsep + "/usr/bin:/bin", "LANG": "C.UTF-8",
               "PYTHONNOUSERSITE": "1", "PIP_NO_INDEX": "1", "PYTHONHASHSEED": "0"}
        with logs["stdout"].open("wb") as stdout, logs["stderr"].open("wb") as stderr:
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                returncode = child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                timeout = True
                os.killpg(child.pid, signal.SIGKILL)
                returncode = child.wait(timeout=5)
        generated = cwd / "_black_version.py"
        compatibility["build"] = {"command": argv, "returncode": returncode, "timed_out": timeout,
            "wall_ns": time.perf_counter_ns() - start,
            "generated_version_file": None if not generated.is_file() else {
                "sha256": execution.sha_file(generated), "bytes": generated.stat().st_size,
                "contents": generated.read_text()},
            "logs": {kind: {"path": str(path), "sha256": execution.sha_file(path), "bytes": path.stat().st_size}
                     for kind, path in logs.items()}}
    result = ORIGINAL_EXECUTE(adapted, python, cwd, output, limits)
    if compatibility["build"] is not None and compatibility["build"]["returncode"] != 0:
        result["outcome"] = "infrastructure_error"
        compatibility["eligibility_rejection"] = "normal package build preparation did not complete"
    result["compatibility"] = compatibility
    (output / "execution.json").write_bytes(canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "prepared", "sources", "python", "runtime-lock", "original-executions", "output", "work-root"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    protocol = json.loads(Path(args.protocol).read_bytes())
    if not 1 <= args.workers <= 2:
        raise ValueError("compatibility replay permits at most two concurrent commands")
    prepared, output = Path(args.prepared), Path(args.output)
    manifest = json.loads((prepared / "manifest.json").read_bytes())
    original = Path(args.original_executions)
    original_summary = json.loads((original / "summary.json").read_bytes())
    if original_summary["groups"] != len(protocol["bugs"]):
        raise ValueError("complete original condition required before compatibility replay")
    selected = [bug for bug in protocol["bugs"] if bug["project"] in AFFECTED_PROJECTS]
    code = {name: execution.sha_file(Path(__file__).with_name(name)) for name in
            ("operational_compat_replay.py", "operational_execute.py", "operational_observer.py", "operational_case_views.py", "operational_cohort_plan.py")}
    plan = {"schema": "hepta.operational-compatibility-execution-plan.v1",
        "protocol_sha256": execution.sha_file(args.protocol),
        "prepared_manifest_sha256": execution.sha_file(prepared / "manifest.json"),
        "original_execution_summary_sha256": execution.sha_file(original / "summary.json"),
        "runtime_lock_sha256": execution.sha_file(args.runtime_lock), "python_sha256": execution.sha_file(args.python),
        "affected_projects": list(AFFECTED_PROJECTS), "groups": [bug["group_id"] for bug in selected],
        "workers": args.workers, "code_sha256": code, "limits": protocol["execution_policy"],
        "eligibility_gate_changed": False, "source_revisions_and_comparators_changed": False,
        "model_quality_seen": False, "selection": "All groups in each affected repository, regardless of original result.",
        "compatibility": "pytest3.10.1 with --assert=plain; missing declared test dependencies; normal Black setup.py --version generation"}
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "execution-plan.json"
    if plan_path.exists() and plan_path.read_bytes() != canonical(plan):
        raise ValueError("compatibility runtime or code changed; use a new output directory")
    if not plan_path.exists():
        plan_path.write_bytes(canonical(plan))
    binding, results = digest(canonical(plan)), []
    execution.execute_command = compatibility_execute
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = []
        for bug in selected:
            stem = bug["project"] + "-" + str(bug["bug_id"])
            path = prepared / (stem + ".json")
            if execution.sha_file(path) != manifest["cases"][path.name]["sha256"]:
                raise ValueError("pre-outcome source/action view changed")
            execution.validate_result(original / stem, execution.sha_file(path), original_summary["execution_plan_sha256"])
            jobs.append(pool.submit(execution.run_case, path, args.sources, output / stem, args.work_root,
                                    args.python, protocol["execution_policy"], binding))
        for job in as_completed(jobs):
            result = job.result()
            results.append(result)
            print(json.dumps({key: result[key] for key in ("group_id", "selected_primary", "selected_control", "physical_command_executions", "harness_error")}), flush=True)
    summary = {"schema": "hepta.operational-compatibility-execution-summary.v1", "execution_plan_sha256": binding,
        "groups": len(results), "supported_regressions": sum(r["selected_primary"] is not None for r in results),
        "supported_diagnostic_choices": sum(r["selected_control"] is not None for r in results),
        "physical_commands": sum(r["physical_command_executions"] for r in results),
        "package_build_commands": sum(e.get("compatibility", {}).get("build") is not None for r in results for pair in r["pairs"].values() for e in pair.values()),
        "case_results": {r["group_id"]: execution.sha_file(output / (r["project"] + "-" + str(r["bug_id"])) / "result.json") for r in results}}
    if any(execution.sha_file(Path(__file__).with_name(name)) != value for name, value in code.items()):
        raise ValueError("compatibility execution implementation changed")
    (output / "summary.json").write_bytes(canonical(summary))
    print(json.dumps({k: v for k, v in summary.items() if k != "case_results"}), flush=True)


if __name__ == "__main__":
    main()
