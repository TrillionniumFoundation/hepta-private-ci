"""Run the frozen real-source command pairs with typed failures and bounded children.

Local Linux research execution only. Each command starts from a clean pinned
implementation and the same immutable fixed-revision test tree. Corpus groups,
test candidates and conditional stopping are sealed before the first command.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from operational_cohort_plan import canonical, digest


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def execute_command(command, python, cwd, output, limits):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    observation_path = output / "observation.json"
    observer = Path(__file__).with_name("operational_observer.py")
    argv = [str(python), str(observer), "--runner", command["runner"], "--output", str(observation_path),
        "--cpu-seconds", str(limits["cpu_seconds"]), "--address-space-bytes", str(limits["address_space_bytes"]),
        "--log-bytes", str(limits["log_file_bytes"]), "--", *command["args"]]
    environment = {"PATH": str(Path(python).parent) + os.pathsep + "/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    start, timed_out = time.perf_counter_ns(), False
    with (output / "stdout.log").open("wb") as stdout, (output / "stderr.log").open("wb") as stderr:
        child = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            code = child.wait(timeout=limits["wall_timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGKILL)
            code = child.wait(timeout=5)
    observation = json.loads(observation_path.read_bytes()) if observation_path.is_file() else None
    if timed_out or code < 0 or observation is None or observation.get("returncode") != code:
        outcome = "infrastructure_error"
    else:
        outcome = observation["outcome"]
    result = {"schema": "hepta.operational-command-execution.v1", "command": argv, "cwd": str(cwd),
        "command_id": command["id"], "runner": command["runner"], "args": command["args"],
        "returncode": code, "timed_out": timed_out, "outcome": outcome,
        "wall_ns": time.perf_counter_ns() - start, "limits": limits, "environment": environment,
        "observer_sha256": sha_file(observer), "observation": observation,
        "files": {path.name: {"sha256": sha_file(path), "bytes": path.stat().st_size}
                  for path in sorted(output.iterdir()) if path.is_file()}}
    (output / "execution.json").write_bytes(canonical(result))
    return result


def command_pair_qualifies(pair):
    return pair["base"]["outcome"] == "test_failure" and pair["candidate"]["outcome"] == "pass"


def validate_result(directory, expected_case_sha, expected_plan_sha):
    value = json.loads((Path(directory) / "result.json").read_bytes())
    if value["case_sha256"] != expected_case_sha or value["execution_plan_sha256"] != expected_plan_sha:
        raise ValueError("completed execution belongs to different source or plan")
    for name, record in value["files"].items():
        path = Path(directory) / name
        if path.stat().st_size != record["bytes"] or sha_file(path) != record["sha256"]:
            raise ValueError("completed execution evidence changed")
    actual = {str(p.relative_to(directory)) for p in Path(directory).rglob("*") if p.is_file()}
    if actual != set(value["files"]) | {"result.json"}:
        raise ValueError("unsealed extra or missing execution files")
    return value


def run_case(case_path, sources, output, work_root, python, limits, plan_sha):
    raw = Path(case_path).read_bytes()
    case = json.loads(raw)
    bug = case["bug"]
    output = Path(output)
    if output.exists():
        return validate_result(output, digest(raw), plan_sha)
    output.mkdir(parents=True)
    store = Path(sources) / (bug["project"] + ".git")
    working = Path(work_root) / (bug["project"] + "-" + str(bug["bug_id"]))
    working.mkdir(parents=True, exist_ok=False)
    checkouts, setup_commands = {}, []
    def git(*args):
        command = ["git", *args]
        result = subprocess.run(command, capture_output=True, timeout=60)
        setup_commands.append({"command": command, "returncode": result.returncode,
            "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace")})
        if result.returncode:
            raise RuntimeError("pinned worktree preparation failed")
    selected_primary, selected_control, pairs, error = None, None, {}, None
    overlay_sha = None
    try:
        for index, role in enumerate(("base", "candidate")):
            directory = working / ("implementation-" + str(index))
            git("--git-dir=" + str(store), "worktree", "add", "--detach", str(directory), bug["revisions"][role])
            checkouts[role] = directory
        snapshot = working / "test-snapshot"
        snapshot.mkdir()
        overlay = []
        for name in case["fixed_test_paths"]:
            source = checkouts["candidate"] / name
            if source.is_symlink() and not source.resolve().is_relative_to(checkouts["candidate"].resolve()):
                raise ValueError("test fixture symlink leaves the pinned checkout")
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
            raw_file = os.readlink(source).encode() if source.is_symlink() else source.read_bytes()
            overlay.append([name, source.is_symlink(), digest(raw_file)])
        overlay_sha = digest(canonical(overlay))
        roots = [p for p in case["test_tree_roots"] if not any(p.startswith(q + "/") for q in case["test_tree_roots"] if p != q)]
        def pair(command):
            key = digest(canonical([command["runner"], command["args"]]))[:20]
            if key in pairs:
                return key, pairs[key]
            records = {}
            for role, directory in checkouts.items():
                git("-C", str(directory), "reset", "--hard", bug["revisions"][role])
                git("-C", str(directory), "clean", "-ffdx")
                for root in roots:
                    target = directory / root
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(snapshot / root, target, symlinks=True)
                for name in case["declared_test_files"]:
                    source, target = snapshot / name, directory / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target, follow_symlinks=False)
                records[role] = execute_command(command, python, directory, output / key / role, limits)
            pairs[key] = records
            return key, records
        for command in case["commands"]:
            primary_key, result = pair(command)
            if not command_pair_qualifies(result):
                continue
            selected_primary = command["id"]
            for control in command["comparators"]:
                control_key, result = pair(control)
                if all(record["outcome"] == "pass" for record in result.values()):
                    selected_control = control["id"]
                    break
            break
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        for directory in checkouts.values():
            git("--git-dir=" + str(store), "worktree", "remove", "--force", str(directory))
        if working.exists():
            shutil.rmtree(working)
    (output / "setup.json").write_bytes(canonical({"commands": setup_commands, "error": error,
        "fixed_test_tree_sha256": overlay_sha, "declared_overlay_files": case["declared_test_files"],
        "complete_fixed_test_file_count": len(case["fixed_test_paths"])}))
    result = {"schema": "hepta.operational-paired-case-result.v1", "case_sha256": digest(raw),
        "execution_plan_sha256": plan_sha, "group_id": bug["group_id"], "split": bug["split"],
        "project": bug["project"], "bug_id": bug["bug_id"], "selected_primary": selected_primary,
        "selected_control": selected_control, "pairs": pairs, "harness_error": error,
        "fixed_test_tree_sha256": overlay_sha, "physical_command_executions": 2 * len(pairs),
        "not_executed_policy": "Stop after first supported declared regression and first informative frozen comparator; other predeclared candidates remain unexecuted.",
        "files": {str(p.relative_to(output)): {"sha256": sha_file(p), "bytes": p.stat().st_size}
                  for p in sorted(output.rglob("*")) if p.is_file()}}
    (output / "result.json").write_bytes(canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "prepared", "sources", "python", "runtime-lock", "output", "work-root"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    protocol, prepared = json.loads(Path(args.protocol).read_bytes()), Path(args.prepared)
    manifest = json.loads((prepared / "manifest.json").read_bytes())
    if not 1 <= args.workers <= protocol["execution_policy"]["workers"]:
        raise ValueError("concurrency exceeds the frozen upper bound")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    code = {name: sha_file(Path(__file__).with_name(name)) for name in
            ("operational_execute.py", "operational_observer.py", "operational_case_views.py", "operational_cohort_plan.py")}
    plan = {"schema": "hepta.operational-execution-plan.v1", "protocol_sha256": sha_file(args.protocol),
        "prepared_manifest_sha256": sha_file(prepared / "manifest.json"), "runtime_lock_sha256": sha_file(args.runtime_lock),
        "python_sha256": sha_file(args.python), "code_sha256": code, "limits": protocol["execution_policy"], "workers": args.workers,
        "conditional_execution": "First declared regression that actually fails before/passes after; then first of at most3 frozen comparators that passes both. No corpus membership change.",
        "source_bank_manifest_sha256": sha_file(Path(args.sources) / "manifest.json")}
    plan_path = output / "execution-plan.json"
    if plan_path.exists() and plan_path.read_bytes() != canonical(plan):
        raise ValueError("execution plan/code/runtime changed; use a new evidence namespace")
    if not plan_path.exists():
        plan_path.write_bytes(canonical(plan))
    plan_sha, results = digest(canonical(plan)), []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = []
        for bug in protocol["bugs"]:
            name = bug["project"] + "-" + str(bug["bug_id"]) + ".json"
            path = prepared / name
            if sha_file(path) != manifest["cases"][name]["sha256"]:
                raise ValueError("frozen comparator/source view changed")
            jobs.append(pool.submit(run_case, path, args.sources, output / name[:-5], args.work_root,
                                    args.python, protocol["execution_policy"], plan_sha))
        for job in as_completed(jobs):
            result = job.result()
            results.append(result)
            print(json.dumps({key: result[key] for key in ("group_id", "selected_primary", "selected_control", "physical_command_executions", "harness_error")}), flush=True)
    summary = {"schema": "hepta.operational-execution-summary.v1", "execution_plan_sha256": plan_sha,
        "groups": len(results), "supported_regressions": sum(r["selected_primary"] is not None for r in results),
        "supported_diagnostic_choices": sum(r["selected_control"] is not None for r in results),
        "physical_commands": sum(r["physical_command_executions"] for r in results),
        "case_results": {r["group_id"]: sha_file(output / (r["project"] + "-" + str(r["bug_id"])) / "result.json") for r in results}}
    if any(sha_file(Path(__file__).with_name(name)) != value for name, value in code.items()):
        raise ValueError("execution code changed while running")
    (output / "summary.json").write_bytes(canonical(summary))
    print(json.dumps({k: v for k, v in summary.items() if k != "case_results"}), flush=True)


if __name__ == "__main__":
    main()
