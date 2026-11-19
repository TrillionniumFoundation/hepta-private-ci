"""Bounded fresh children, complete costs, and a test-access selection seal."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import signal
import subprocess
import sys
import time


def write_json(path, value):
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value, indent=2)+"\n")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resources():
    memory = {line.split(":", 1)[0]: int(line.split()[1])*1024
              for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")}
    return {**memory, "cpu_affinity": sorted(os.sched_getaffinity(0)),
            "observation_unix_seconds": time.time(), "cgroup_limits_enforced_here": False}


def start_child(command, directory, cpu, ceiling):
    directory.mkdir(parents=True, exist_ok=False)
    stdout, stderr = (directory/"stdout").open("xb"), (directory/"stderr").open("xb")
    env = os.environ.copy()
    env.update({k: "1" for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")})
    env["PYTHONHASHSEED"] = "0"
    def limits():
        os.sched_setaffinity(0, {cpu})
        resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (ceiling, ceiling+10))
    request = {"command": command, "cpu": cpu, "address_space_bytes": 4*1024**3,
               "wall_deadline_seconds": ceiling, "started_unix": time.time()}
    write_json(directory/"REQUEST.json", request)
    started = time.perf_counter()
    try:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env,
                                   preexec_fn=limits, start_new_session=True)
    except Exception:
        stdout.close()
        stderr.close()
        raise
    return {"process": process, "directory": directory, "started": started,
            "stdout": stdout, "stderr": stderr, "cpu": cpu, "deadline": ceiling,
            "kill_sent": False}


def run_stage(tasks, root, protocol, cpus):
    waiting, live, completed = list(tasks), {}, []
    def not_started(name, reason):
        directory = root/name
        directory.mkdir(parents=True, exist_ok=True)
        cost = {"directory": name, "exit_code": None, "status": "NOT_STARTED",
                "reason": reason, "wall_seconds": 0., "cpu_seconds": 0., "maxrss_kib": 0,
                "child_exec_completed": False, "model_calls": 0, "optimizer_calls": 0}
        write_json(directory/"COST.json", cost)
        completed.append(cost)
    while waiting or live:
        for cpu in cpus:
            if cpu not in live and waiting:
                name, command = waiting.pop(0)
                try:
                    observation = resources()
                    if observation["MemAvailable"] < 2*1024**3:
                        raise RuntimeError("frozen 2 GiB MemAvailable start floor not met")
                    write_json_parent = root/name
                    write_json_parent.mkdir(parents=True, exist_ok=False)
                    write_json(write_json_parent/"OBSERVATION.json", observation)
                    # The admission directory exists, while the process
                    # request directory is a distinct child.
                    live[cpu] = start_child(command, root/name/"process", cpu,
                                            protocol["child_deadline_seconds"])
                    live[cpu]["identity_directory"] = root/name
                except Exception as error:
                    not_started(name, repr(error))
                    for remaining, _ in waiting:
                        not_started(remaining, "intake stopped after admission/spawn failure")
                    waiting.clear()
                    break
        for cpu, job in list(live.items()):
            process = job["process"]
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if not pid:
                if time.perf_counter()-job["started"] > job["deadline"] and not job["kill_sent"]:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        job["kill_sent"] = True
                    except ProcessLookupError:
                        # A naturally completed child is still collected by
                        # wait4; an exit/kill race must not lose its cost.
                        pass
                continue
            process.returncode = os.waitstatus_to_exitcode(status)
            job["stdout"].close()
            job["stderr"].close()
            cost = {"exit_code": process.returncode, "wall_seconds": time.perf_counter()-job["started"],
                    "cpu_seconds": usage.ru_utime+usage.ru_stime, "maxrss_kib": usage.ru_maxrss,
                    "deadline_kill_sent": job["kill_sent"], "cpu_affinity": [cpu],
                    "stdout_bytes": (job["directory"]/"stdout").stat().st_size,
                    "stderr_bytes": (job["directory"]/"stderr").stat().st_size}
            write_json(job["identity_directory"]/"COST.json", cost)
            completed.append({"directory": job["identity_directory"].name, **cost})
            print(json.dumps({"completed": job["identity_directory"].name, "exit": process.returncode,
                              "wall": cost["wall_seconds"]}), flush=True)
            del live[cpu]
        time.sleep(.05)
    return completed


def main():
    parser = argparse.ArgumentParser()
    for name in ("protocol", "data", "output", "source-commit"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    protocol_path = Path(args.protocol).resolve()
    protocol = json.loads(protocol_path.read_text())
    cpus = protocol["cpu_affinity"]
    if not set(cpus) <= os.sched_getaffinity(0):
        raise RuntimeError("declared CPUs unavailable")
    write_json(root/"CAMPAIGN_REQUEST.json", {"source_commit": args.source_commit,
               "protocol_sha256": digest(protocol_path), "resources": resources(),
               "scientific_wall_budget_seconds_per_fit": protocol["budget_seconds"],
               "declared_roster": len(protocol["arms"])*len(protocol["seeds"])})
    roster = [(arm, seed) for seed in protocol["seeds"] for arm in protocol["arms"]]
    random.Random(20261119).shuffle(roster)
    common = ["--data", str(Path(args.data).resolve()), "--protocol", str(protocol_path)]
    fit_root = root/"fits"
    tasks = [(f"{arm}-s{seed}", [sys.executable, "-m", "qualification.hcsn_network.benchmark_train",
              "--arm", arm, "--seed", str(seed), "--output", str(fit_root/f"{arm}-s{seed}"), *common])
             for arm, seed in roster]
    campaign_started = time.perf_counter()
    fit_costs = run_stage(tasks, root/"fit-processes", protocol, cpus)
    write_json(root/"FIT_COSTS.json", fit_costs)
    seal_rows = []
    costs_by_fit = {row["directory"]: row for row in fit_costs}
    for arm, seed in roster:
        directory = fit_root/f"{arm}-s{seed}"
        selected, result = directory/"selected.pt", directory/"RESULT.json"
        terminal = costs_by_fit[directory.name]
        result_value = json.loads(result.read_text()) if result.exists() else {}
        eligible = (terminal["exit_code"] == 0 and result_value.get("status") == "COMPLETED_WALL_BUDGET"
                    and selected.exists())
        ordinal = result_value["validations"].index(result_value["selected"]) if eligible else None
        validation = directory/f"validation-{ordinal:03}.npz" if eligible else None
        seal_rows.append({"arm": arm, "seed": seed, "directory": directory.name,
                          "selected_sha256": digest(selected) if selected.exists() else None,
                          "result_sha256": digest(result) if result.exists() else None,
                          "terminal_exit_code": terminal["exit_code"], "eligible_for_test": eligible,
                          "terminal_cost_sha256": digest(root/"fit-processes"/directory.name/"COST.json"),
                          "selected_validation_index": ordinal,
                          "selected_validation_sha256": digest(validation) if eligible else None})
    seal = {"sealed_unix_seconds": time.time(), "protocol_sha256": digest(protocol_path),
            "source_commit": args.source_commit, "test_examples_evaluated_before_seal": 0,
            "fits": seal_rows}
    write_json(root/"EVALUATION_SEAL.json", seal)
    if not all(row["eligible_for_test"] for row in seal_rows):
        write_json(root/"COMPLETE.json", {"status": "TRAINING_FAILED_TEST_NOT_RUN",
                   "wall_seconds": time.perf_counter()-campaign_started, "fit_children": len(fit_costs),
                   "all_live_children_collected": True, "test_examples_evaluated": 0})
        raise SystemExit(1)
    evaluation_root = root/"evaluation"
    tasks = [(row["directory"], [sys.executable, "-m", "qualification.hcsn_network.benchmark_evaluate",
              "--seal", str(root/"EVALUATION_SEAL.json"), "--fit", str(fit_root/row["directory"]),
              "--output", str(evaluation_root/row["directory"]), *common])
             for row in seal_rows if row["selected_sha256"] is not None and row["result_sha256"] is not None]
    evaluation_costs = run_stage(tasks, root/"evaluation-processes", protocol, cpus)
    write_json(root/"EVALUATION_COSTS.json", evaluation_costs)
    write_json(root/"COMPLETE.json", {"wall_seconds": time.perf_counter()-campaign_started,
               "fit_children": len(fit_costs), "evaluation_children": len(evaluation_costs),
               "fit_failures": sum(r["exit_code"] != 0 for r in fit_costs),
               "evaluation_failures": sum(r["exit_code"] != 0 for r in evaluation_costs),
               "all_training_selections_preceded_test_access": True})


if __name__ == "__main__":
    main()
