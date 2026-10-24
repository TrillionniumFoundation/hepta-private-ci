"""Execute every frozen action on clean source pairs; local Linux research only."""

import ctypes
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from operational_cohort_plan import canonical, digest
from prospective_action_inputs import sha_file


def close_owned_process_group(group):
    """Reap only this command's group; do not assume /proc shares our PID namespace."""
    def present():
        try:
            os.killpg(group, 0)
            return True
        except ProcessLookupError:
            return False
    before = present()
    if before:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline, reaped = time.monotonic() + 2, []
    while time.monotonic() < deadline:
        try:
            pid, status, usage = os.wait4(-group, os.WNOHANG)
        except ChildProcessError:
            break
        if pid:
            reaped.append({"pid": pid, "returncode": os.waitstatus_to_exitcode(status),
                "cpu_ns": round((usage.ru_utime + usage.ru_stime) * 1e9),
                "peak_rss_bytes": usage.ru_maxrss * 1024})
        else:
            time.sleep(.01)
    remaining = present()
    return {"group_present_after_leader_exit": before, "process_group_still_present": remaining,
            "reaped_descendants": reaped, "orphan_child_cpu_ns": sum(r["cpu_ns"] for r in reaped),
            "orphan_cpu_unmeasured": remaining,
            "scope": "Owned private session/process group only; escaped sessions are not measured."}


def observe(command, profile, cwd, output, limits):
    """Observe a bounded real command, with per-child wait4 CPU accounting."""
    output, cwd = Path(output).resolve(), Path(cwd).resolve()
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
    if libc.prctl(36, 1, 0, 0, 0):  # Linux PR_SET_CHILD_SUBREAPER, process-local adoption only.
        raise OSError(ctypes.get_errno(), "cannot adopt owned command descendants")
    output.mkdir(parents=True, exist_ok=False)
    observer = Path(__file__).with_name("prospective_action_observer.py")
    args = list(command["args"])
    if command["runner"] == "pytest" and profile["plain_pytest"]:
        args = ["--assert=plain", *args]
    paths = [cwd]
    for value in profile.get("source_paths", []):
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("runtime source paths must remain inside the checkout")
        paths.append(cwd / relative)
    environment = {"PATH": str(Path(profile["python"]).parent) + ":/usr/bin:/bin",
        "LANG": "C.UTF-8", "PYTHONPATH": os.pathsep.join(map(str, paths)),
        "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(output / "fresh-bytecode-cache"),
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    argv = [profile["python"], str(observer), "--runner", command["runner"],
        "--output", str(output / "observation.json"), "--cpu-seconds", str(limits["cpu_seconds"]),
        "--address-space-bytes", str(limits["address_space_bytes"]),
        "--log-bytes", str(limits["log_file_bytes"]), "--", *args]
    start, cpu, timeout = time.perf_counter_ns(), time.thread_time_ns(), False
    with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        child = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=stdout, stderr=stderr,
                                 start_new_session=True)
        (output / "launch.json").write_bytes(canonical({"pid": child.pid, "private_process_group": child.pid,
            "command": argv, "child_created": True}))
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                break
            if (time.perf_counter_ns() - start) / 1e9 > limits["wall_timeout_seconds"]:
                timeout = True
                os.killpg(child.pid, signal.SIGKILL)
                pid, status, usage = os.wait4(child.pid, 0)
                break
            time.sleep(0.01)
        child.returncode = os.waitstatus_to_exitcode(status)
    cleanup = close_owned_process_group(child.pid)
    wall_ns, parent_ns = time.perf_counter_ns() - start, time.thread_time_ns() - cpu
    observed = output / "observation.json"
    observation, observation_error = None, None
    if observed.is_file():
        try:
            observation = json.loads(observed.read_bytes())
        except (ValueError, UnicodeDecodeError) as error:
            observation_error = type(error).__name__ + ": " + str(error)
    if (timeout or child.returncode < 0 or observation is None or cleanup["group_present_after_leader_exit"]
            or not isinstance(observation, dict) or observation.get("returncode") != child.returncode
            or observation.get("outcome") not in ("pass", "test_failure", "infrastructure_error", "uninformative")):
        outcome = "infrastructure_error"
    else:
        outcome = observation["outcome"]
    result = {"schema": "hepta.prospective-command-observation.v1", "command": argv,
        "candidate_key": command["key"], "original_args": command["args"],
        "effective_args": args, "runner": command["runner"], "cwd": str(cwd),
        "returncode": child.returncode, "timed_out": timeout, "outcome": outcome,
        "owned_process_group_cleanup": cleanup,
        "observation": observation, "observation_error": observation_error,
        "environment": environment, "limits": limits,
        "observer_sha256": sha_file(observer), "wall_ns": wall_ns,
        "parent_thread_cpu_ns": parent_ns,
        "child_cpu_ns": round((usage.ru_utime + usage.ru_stime) * 1e9) + cleanup["orphan_child_cpu_ns"],
        "child_peak_rss_bytes": max([usage.ru_maxrss * 1024, *[r["peak_rss_bytes"] for r in cleanup["reaped_descendants"]]]),
        "cost_scope": "Child launch/wait and waited descendants; excludes enclosing source checkout and receipt write. Linux process max RSS, not concurrent aggregate.",
        "files": {p.name: {"sha256": sha_file(p), "bytes": p.stat().st_size}
                  for p in sorted(output.iterdir()) if p.is_file()}}
    (output / "execution.json").write_bytes(canonical(result))
    return result


def validate_case(output, binding, plan_sha):
    output = Path(output)
    result = json.loads((output / "result.json").read_bytes())
    if (result["case_sha256"] != binding["sha256"] or result["execution_plan_sha256"] != plan_sha
            or result["proposed_action_keys"] != [a["key"] for a in binding["actions"]]):
        raise ValueError("case execution belongs to a different frozen proposal/plan")
    for name, record in result["files"].items():
        p = output / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size != record["bytes"] or sha_file(p) != record["sha256"]:
            raise ValueError("execution evidence changed")
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if actual != set(result["files"]) | {"result.json"}:
        raise ValueError("extra or missing execution evidence")
    return result


def run_case(binding, source_store, profile, output, work_root, limits, plan_sha):
    """Outcome-independent candidate execution; every absent result stays explicit."""
    case_path, output = Path(binding["path"]).resolve(), Path(output).resolve()
    raw_case = case_path.read_bytes()
    if digest(raw_case) != binding["sha256"]:
        raise ValueError("prepared source case changed")
    if output.exists():
        return validate_case(output, binding, plan_sha)
    case = json.loads(raw_case)
    if case["bug"]["revisions"] != binding["source_revisions"]:
        raise ValueError("proposed source revisions differ from prepared case")
    source_store = Path(source_store).resolve()
    output.mkdir(parents=True, exist_ok=False)
    working = Path(work_root).resolve() / (binding["project"] + "-" + str(binding["bug_id"]))
    working.mkdir(parents=True, exist_ok=False)
    checkouts, commands, pairs, errors, observer_attempts, tainted = {}, [], {}, [], 0, set()
    overlay_sha = None
    started, parent_cpu = time.perf_counter_ns(), time.thread_time_ns()

    def git(*args, allow_error=False):
        argv = ["git", *map(str, args)]
        p = subprocess.run(argv, capture_output=True, timeout=60)
        commands.append({"command": argv, "returncode": p.returncode,
                         "stdout": p.stdout.decode(errors="replace"),
                         "stderr": p.stderr.decode(errors="replace")})
        if p.returncode and not allow_error:
            raise RuntimeError("pinned working source operation failed")
        return p.returncode

    try:
        for i, role in enumerate(("base", "candidate")):
            path = working / ("implementation-" + str(i))
            git("--git-dir=" + str(source_store), "worktree", "add", "--detach", path,
                binding["source_revisions"][role])
            checkouts[role] = path
        snapshot = working / "fixed-test-snapshot"
        snapshot.mkdir()
        overlay = []
        for name in case["fixed_test_paths"]:
            source, target = checkouts["candidate"] / name, snapshot / name
            if source.is_symlink() and not source.resolve().is_relative_to(checkouts["candidate"].resolve()):
                raise ValueError("test source link leaves pinned checkout")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
            raw = os.readlink(source).encode() if source.is_symlink() else source.read_bytes()
            overlay.append([name, source.is_symlink(), digest(raw)])
        overlay_sha = digest(canonical(overlay))
        roots = [p for p in case["test_tree_roots"]
                 if not any(p.startswith(q + "/") for q in case["test_tree_roots"] if p != q)]
        for action in binding["actions"]:
            pair = {}
            for role, directory in checkouts.items():
                if role in tainted:
                    errors.append({"action": action["key"], "role": role, "type": "QuarantinedSource",
                                   "message": "earlier owned descendants did not terminate; no unsafe reset"})
                    continue
                try:
                    git("-C", directory, "reset", "--hard", binding["source_revisions"][role])
                    git("-C", directory, "clean", "-ffdx")
                    for root in roots:
                        target = directory / root
                        if target.exists():
                            shutil.rmtree(target)
                        shutil.copytree(snapshot / root, target, symlinks=True)
                    for name in case["fixed_test_paths"]:
                        if any(name.startswith(root + "/") for root in roots):
                            continue
                        target = directory / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(snapshot / name, target, follow_symlinks=False)
                    observer_attempts += 1
                    pair[role] = observe(action, profile, directory, output / action["key"] / role, limits)
                    if pair[role]["owned_process_group_cleanup"]["process_group_still_present"]:
                        tainted.add(role)
                        raise RuntimeError("owned test descendants still active; source reset unsafe")
                except Exception as error:
                    errors.append({"action": action["key"], "role": role,
                                   "type": type(error).__name__, "message": str(error)})
            pairs[action["key"]] = pair
    except Exception as error:
        errors.append({"stage": "case_setup", "type": type(error).__name__, "message": str(error)})
    finally:
        for role, directory in checkouts.items():
            if role in tainted:
                errors.append({"stage": "quarantined_owned_worktree", "path": str(directory),
                               "message": "retained because owned descendants are still active"})
                continue
            try:
                git("--git-dir=" + str(source_store), "worktree", "remove", "--force", directory, allow_error=True)
            except Exception as error:
                errors.append({"stage": "owned_worktree_cleanup", "type": type(error).__name__,
                               "message": str(error), "path": str(directory)})
        if working.exists() and not tainted:
            try:
                shutil.rmtree(working)
            except OSError as error:
                errors.append({"stage": "owned_directory_cleanup", "type": type(error).__name__,
                               "message": str(error), "path": str(working)})
    (output / "setup.json").write_bytes(canonical({"commands": commands, "errors": errors,
        "fixed_test_tree_sha256": overlay_sha, "fixed_test_files": len(case["fixed_test_paths"])}))
    launch_counts = {a["key"]: sum((output / a["key"] / r / "launch.json").is_file()
                                  for r in ("base", "candidate")) for a in binding["actions"]}
    result = {"schema": "hepta.prospective-action-case-execution.v1", "case_sha256": binding["sha256"],
        "execution_plan_sha256": plan_sha, "project": binding["project"], "bug_id": binding["bug_id"],
        "group_id": case["bug"]["group_id"], "split": binding["role"],
        "proposed_action_keys": [a["key"] for a in binding["actions"]], "pairs": pairs,
        "missing_action_keys": [a["key"] for a in binding["actions"] if a["key"] not in pairs],
        "errors": errors, "fixed_test_tree_sha256": overlay_sha,
        "physical_command_executions": sum(launch_counts.values()), "action_launch_counts": launch_counts,
        "complete_command_observations": sum(len(pair) for pair in pairs.values()),
        "observer_call_attempts": observer_attempts,
        "observer_attempts_without_launch_receipt": observer_attempts - sum(launch_counts.values()),
        "case_wall_ns": time.perf_counter_ns() - started,
        "case_parent_thread_cpu_ns": time.thread_time_ns() - parent_cpu,
        "case_cost_scope": "Inclusive case source setup, observations and cleanup; overlaps nested command wall/parent CPU and excludes result serialization. Git child CPU not measured here.",
        "outcome_dependent_stopping": False,
        "files": {p.relative_to(output).as_posix(): {"sha256": sha_file(p), "bytes": p.stat().st_size}
                  for p in sorted(output.rglob("*")) if p.is_file()}}
    (output / "result.json").write_bytes(canonical(result))
    return result
