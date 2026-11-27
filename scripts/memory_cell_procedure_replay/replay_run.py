"""Execute every frozen historical replay arm and retain actual outcomes."""

import argparse
from collections import Counter
import difflib
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import sys
import time

from replay_bundle import (
    ROOT,
    SOURCE_PATHS,
    TEST_PATH,
    digest,
    file_record,
    load_json,
    save_json,
)


class Retrieval:
    def __init__(self, cases):
        self.documents = [case["query"] for case in cases]
        self.counts = [
            Counter(re.findall(r"[a-z0-9_]+", doc.lower())) for doc in self.documents
        ]
        frequency = Counter(token for count in self.counts for token in count)
        self.idf = {
            token: 1 + math.log((len(cases) + 1) / (count + 1))
            for token, count in frequency.items()
        }
        self.vectors = [self.vector(count) for count in self.counts]

    def vector(self, count):
        vector = {
            token: (1 + math.log(n)) * self.idf[token]
            for token, n in count.items()
            if token in self.idf
        }
        norm = math.sqrt(sum(value * value for value in vector.values()))
        return {token: value / norm for token, value in vector.items()} if norm else {}

    def exact(self, query):
        return self.documents.index(query) if query in self.documents else None

    def tfidf(self, query):
        vector = self.vector(Counter(re.findall(r"[a-z0-9_]+", query.lower())))
        scores = [
            sum(value * doc.get(token, 0) for token, value in vector.items())
            for doc in self.vectors
        ]
        return max(
            range(len(scores)), key=lambda index: (scores[index], -index)
        ), scores


def run_command(command, cwd, environment, log_path, timeout, max_bytes):
    """Bound stdout without changing the child resource limits or source guards."""
    started = time.time()
    begin = time.monotonic()
    reason = None
    child = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    os.set_blocking(child.stdout.fileno(), False)
    usage = None
    exited = False
    eof = False
    observed = 0
    retained = 0
    with log_path.open("xb") as log:
        os.chmod(log_path, 0o600)
        while not (exited and eof):
            if not exited:
                pid, status, usage_now = os.wait4(child.pid, os.WNOHANG)
                if pid:
                    child.returncode = os.waitstatus_to_exitcode(status)
                    usage, exited = usage_now, True
            if not reason and time.monotonic() - begin > timeout:
                reason = "timeout"
            if reason:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if not eof:
                ready, _, _ = select.select([child.stdout], [], [], 0.02)
                if ready:
                    block = os.read(child.stdout.fileno(), 65536)
                    if not block:
                        eof = True
                    else:
                        observed += len(block)
                        keep = block[: max(0, max_bytes - retained)]
                        log.write(keep)
                        retained += len(keep)
                        if observed > max_bytes:
                            reason = "output_limit"
            elif not exited:
                time.sleep(0.01)
    child.stdout.close()
    return {
        "command": command,
        "cwd": str(cwd),
        "started_unix_seconds": started,
        "wall_seconds": time.monotonic() - begin,
        "exit_code": child.returncode,
        "limit_failure": reason,
        "log": log_path.name,
        "log_record": file_record(log_path),
        "observed_log_bytes": observed,
        "retained_log_bytes": retained,
        "cpu_user_seconds": usage.ru_utime,
        "cpu_system_seconds": usage.ru_stime,
        "peak_rss_kib": usage.ru_maxrss,
        "rss_platform_unit": "Linux KiB",
    }


def source_records(root):
    return {path: file_record(root / path) for path in SOURCE_PATHS}


def environment_record(environment, source):
    import ast

    names, prefixes = set(), ()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if "UNREVIEWED_ENVIRONMENT_KEYS" in targets:
                names = set(ast.literal_eval(node.value.args[0]))
            if "UNREVIEWED_ENVIRONMENT_PREFIXES" in targets:
                prefixes = ast.literal_eval(node.value)
    present = sorted(
        key
        for key, value in environment.items()
        if value and (key in names or key.startswith(prefixes))
    )
    return {
        "overrides": {"PYTHONDONTWRITEBYTECODE": "1"},
        "guarded_names_present": present,
        "guarded_values_sha256": {
            key: digest(environment[key].encode()) for key in present
        },
        "loader_paths_injected": False,
        "python_executable": shutil.which("python3", path=environment.get("PATH")),
        "git_executable": shutil.which("git", path=environment.get("PATH")),
        "path_sha256": digest(environment.get("PATH", "").encode()),
    }


def verify_plan(plan_path, expected):
    if digest(plan_path.read_bytes()) != expected:
        raise ValueError("Plan digest mismatch")
    plan = load_json(plan_path)
    for path, record in plan["inputs"].items():
        if file_record(ROOT / path) != record:
            raise ValueError(f"Input changed: {path}")
    for path, record in plan["code"].items():
        if file_record(ROOT / path) != record:
            raise ValueError(f"Frozen code changed: {path}")
    for case in plan["cases"]:
        if file_record(plan_path.parent / case["patch"]) != case["patch_record"]:
            raise ValueError("Action patch changed")
    return plan


def execute(plan_path, expected, output):
    if sys.platform != "linux":
        raise ValueError("This bounded replay records Linux wait4 RSS units")
    plan = verify_plan(plan_path, expected)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    last_source = ROOT / "source_bundle" / plan["cases"][-1]["before"] / SOURCE_PATHS[0]
    env_record = environment_record(environment, last_source.read_text())
    save_json(output / "environment.json", env_record)
    fit_started, fit_cpu = time.monotonic(), time.process_time()
    retrieval = Retrieval(plan["cases"])
    fit_cost = {
        "wall_seconds": time.monotonic() - fit_started,
        "cpu_seconds": time.process_time() - fit_cpu,
    }
    receipts = []
    for index, case in enumerate(plan["cases"]):
        for arm in plan["arms"]:
            arm_started = time.monotonic()
            directory = output / case["id"] / arm
            work = directory / "work"
            work.mkdir(parents=True)
            original = ROOT / "source_bundle" / case["before"]
            for path in SOURCE_PATHS:
                target = work / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original / path, target)
            before = source_records(work)
            select_started, select_cpu = time.monotonic(), time.process_time()
            scores = None
            if arm == "no-op":
                selected = None
            elif arm == "wrong-action":
                selected = (index + 1) % len(plan["cases"])
            elif arm == "oracle":
                selected = index
            elif arm == "exact":
                selected = retrieval.exact(case["query"])
            else:
                selected, scores = retrieval.tfidf(case["query"])
            selector = {
                "wall_seconds": time.monotonic() - select_started,
                "cpu_seconds": time.process_time() - select_cpu,
                "scores": scores,
            }
            commands = []

            def command(args, name):
                receipt = run_command(
                    args,
                    work,
                    environment,
                    directory / name,
                    plan["timeouts_seconds"],
                    plan["max_log_bytes"],
                )
                commands.append(receipt)
                return receipt

            action = plan["cases"][selected] if selected is not None else None
            action_status = "no_action"
            if action:
                if before[TEST_PATH]["sha256"] != action["preimage"]:
                    action_status = "rejected_preimage"
                else:
                    init = command(["git", "init", "-q"], "git-init.log")
                    if init["exit_code"] != 0 or init["limit_failure"]:
                        action_status = "init_failed"
                    else:
                        patch = str(plan_path.parent / action["patch"])
                        check = command(
                            ["git", "apply", "--check", patch], "git-apply-check.log"
                        )
                        if check["exit_code"] != 0 or check["limit_failure"]:
                            action_status = "patch_check_failed"
                        else:
                            applied = command(["git", "apply", patch], "git-apply.log")
                            action_status = (
                                "applied"
                                if applied["exit_code"] == 0
                                and not applied["limit_failure"]
                                else "patch_failed"
                            )
            after_action = source_records(work)
            diff = "".join(
                difflib.unified_diff(
                    (original / TEST_PATH).read_text().splitlines(keepends=True),
                    (work / TEST_PATH).read_text().splitlines(keepends=True),
                    fromfile=f"a/{TEST_PATH}",
                    tofile=f"b/{TEST_PATH}",
                )
            )
            (directory / "actual.diff").write_text(diff)
            tests = command(plan["command"], "tests.log")
            final = source_records(work)
            raw_log = (directory / "tests.log").read_text(errors="replace")
            count = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", raw_log)
            guard_unchanged = all(
                before[path] == after_action[path] == final[path]
                for path in SOURCE_PATHS
                if path != TEST_PATH
            )
            source_stable = after_action == final
            expected_hash = (
                action["postimage"] if action_status == "applied" else case["preimage"]
            )
            exact_source = after_action[TEST_PATH]["sha256"] == expected_hash
            tests_pass = tests["exit_code"] == 0 and tests["limit_failure"] is None
            receipt = {
                "case": case["id"],
                "arm": arm,
                "selected_action": action["id"] if action else None,
                "action_status": action_status,
                "selector": selector,
                "commands": commands,
                "before": before,
                "after_action": after_action,
                "after_tests": final,
                "actual_diff": file_record(directory / "actual.diff"),
                "test_change_audit": action["test_change_audit"]
                if action_status == "applied"
                else None,
                "observer": {
                    "tests_pass": tests_pass,
                    "executed_tests": int(count[1]) if count else None,
                    "suite_reported_seconds": float(count[2]) if count else None,
                    "failure_signature_seen": all(
                        part in raw_log for part in case["failure_signature"]
                    ),
                    "production_and_workflow_unchanged": guard_unchanged,
                    "test_source_unchanged_during_execution": source_stable,
                    "source_matches_admitted_action": exact_source,
                    "qualified_target_suite_pass": tests_pass
                    and guard_unchanged
                    and source_stable
                    and exact_source,
                },
                "total_arm_wall_seconds": time.monotonic() - arm_started,
            }
            save_json(directory / "receipt.json", receipt)
            receipts.append(receipt)
            print(
                json.dumps(
                    {
                        "case": case["id"],
                        "arm": arm,
                        "action": action_status,
                        "exit_code": tests["exit_code"],
                        **receipt["observer"],
                    }
                ),
                flush=True,
            )
    summaries = []
    for case in plan["cases"]:
        rows = [row for row in receipts if row["case"] == case["id"]]
        no_op = next(row for row in rows if row["arm"] == "no-op")["observer"]
        reproduced = no_op["failure_signature_seen"] and not no_op["tests_pass"]
        summaries.append(
            {
                "case": case["id"],
                "reproduction": "reproduced" if reproduced else "nonreproduced",
                "baseline_pass": no_op["tests_pass"],
                "arms": [
                    {
                        "arm": row["arm"],
                        "action_status": row["action_status"],
                        "suite_pass": row["observer"]["qualified_target_suite_pass"],
                        "repair_effect": (
                            row["observer"]["qualified_target_suite_pass"]
                            if reproduced
                            else None
                        ),
                    }
                    for row in rows
                ],
            }
        )
    commands = [command for row in receipts for command in row["commands"]]
    result = {
        "schema": plan["schema"],
        "plan_sha256": expected,
        "scope": plan["scope"],
        "cases": summaries,
        "learned_route": plan["learned_route"],
        "environment": env_record,
        "cost": {
            "test_processes": len(receipts),
            "subprocesses_including_patch_commands": len(commands),
            "git_apply_commands": sum(
                row["action_status"] == "applied" for row in receipts
            ),
            "wall_seconds": time.monotonic() - started,
            "retrieval_fit": fit_cost,
            "command_cpu_user_seconds": sum(
                command["cpu_user_seconds"] for command in commands
            ),
            "command_cpu_system_seconds": sum(
                command["cpu_system_seconds"] for command in commands
            ),
            "max_command_peak_rss_kib": max(
                command["peak_rss_kib"] for command in commands
            ),
            "raw_log_bytes": sum(command["retained_log_bytes"] for command in commands),
            "model_calls": 0,
            "training_updates": 0,
            "source_bundle_bytes": sum(
                row["bytes"]
                for name, row in plan["inputs"].items()
                if name.startswith("source_bundle/")
            ),
            "patch_library_bytes": sum(
                case["patch_record"]["bytes"] for case in plan["cases"]
            ),
            "output_bytes_before_result": sum(
                path.stat().st_size for path in output.rglob("*") if path.is_file()
            ),
        },
        "limitations": plan["limitations"],
    }
    verify_plan(plan_path, expected)
    save_json(output / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    execute(
        arguments.plan.resolve(),
        arguments.expected_plan_sha256,
        arguments.output.resolve(),
    )
