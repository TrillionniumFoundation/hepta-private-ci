"""One new seed137 repair child with separate180CPU/300wall limits.

The dedicated systemd scope is1GiB/oneCPU/64tasks/330seconds including cleanup.
Unknown or interrupted execution is not reported as zero. No automatic retry,
parent83 process, inherited old-budget borrowing, or production action exists.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
CAPS = dict(forwards=25, body_ticks=150, paired_queries=768, backwards=16,
    optimizer_steps=16, analytic_solves=2, trace_linear_replays=0, cached_inverse_targets=24,
    scalar_inverse_targets=0, root_cells=0, root_bisections=0, root_interval_evaluations=0,
    root_point_evaluations=0, lagrange_iterations=256, proposal_directions=3)


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def check_sources(binding, helper, core, transfer):
    for directory, group in ((HERE, "adapter_files"), (helper, "helper_files"),
            (core, "core_files"), (transfer, "transfer_files")):
        for name, item in binding[group].items():
            raw = (directory/name).read_bytes()
            if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("frozen repair source identity differs: "+name)


def typed_counts(value):
    if (not isinstance(value, dict) or set(value) != set(CAPS)
            or any(type(v) is not int or v < 0 or v > CAPS[k] for k,v in value.items())):
        raise ValueError("repair counters differ from their independent caps")
    return dict(value)


def main():
    if len(sys.argv) != 7:
        raise SystemExit("supervise.py BINDING HELPER CORE TRANSFER PREPARED NEW_OUTPUT")
    binding_path, helper, core, transfer, prepared, output = (Path(v).resolve() for v in sys.argv[1:])
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    binding_raw = binding_path.read_bytes()
    binding = json.loads(binding_raw)
    result = dict(schema="hepta.transfer137.repair-supervisor.v1", status="NOT_STARTED",
        seed=137, independent_new_attempt=True, original_failed_attempt_preserved=True,
        processes_started=0, retries=0, new_limits=CAPS, cpu_seconds_limit=180, wall_seconds_limit=300,
        supervisor_lifetime_seconds=330, actual_counts={k:0 for k in CAPS}, counts_complete=True,
        unknown_operations=[], counts_semantics="Reported started operations and returned primitive counts; lower bounds whenever incomplete.",
        new_holdout=False, native_owner=False, production=False, old_per_parent_fit_cap_not_claimed_unchanged=True,
        preparation_cost_separate=True, conversational_planning_cost="UNAVAILABLE_NOT_MEASURED_ZERO")
    pid, waited, root, before_cpu, old = None, False, None, None, None
    failure = None
    try:
        if (binding["status"] != "FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW"
                or binding["seed"] != 137 or binding["new_limits"] != CAPS):
            raise ValueError("unreviewed separate repair binding")
        check_sources(binding, helper, core, transfer)
        prep = json.loads((prepared/"PREPARED.json").read_text())
        if prep["binding_sha256"] != hashlib.sha256(binding_raw).hexdigest():
            raise ValueError("prepared repair inputs use a different binding")
        spec = importlib.util.spec_from_file_location("frozen_custody_helpers", transfer/"supervise.py")
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        root, limits = old.cgroup()
        custody = old.exclusive_supervisor(root)
        available = sorted(os.sched_getaffinity(0))
        if not available:
            raise ValueError("no allowed CPU")
        os.sched_setaffinity(0, {available[0]})
        before_cpu = old.cpu_usage(root)
        result.update(status="STARTED", cgroup=limits, cpu_affinity=[available[0]], initial_custody=custody)
        save(output/"START.json", result)
        stdout, stderr = (output/"repair137.stdout").open("xb"), (output/"repair137.stderr").open("xb")
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                resource.setrlimit(resource.RLIMIT_CPU, (180, 181))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                os.dup2(stdout.fileno(), 1)
                os.dup2(stderr.fileno(), 2)
                env = dict(os.environ)
                env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                    NUMEXPR_NUM_THREADS="1", CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1")
                args = [sys.executable, str(HERE/"repair_runner.py"), str(binding_path), str(helper),
                    str(core), str(transfer), str(prepared/"parent137"), str(prepared/"cached137"), str(output/"repair137")]
                os.execve(sys.executable, args, env)
            except BaseException:
                os._exit(127)
        result.update(processes_started=1, child_pid=pid, fresh_process=True)
        save(output/"CHILD_STARTED.json", dict(child_pid=pid, seed=137, retries=0, independent_new_attempt=True))
        stdout.close()
        stderr.close()
        stopped = None
        while True:
            ended, status, usage = os.wait4(pid, os.WNOHANG)
            if ended:
                waited = True
                break
            wall, consumed = time.monotonic()-started, (old.cpu_usage(root)-before_cpu)/1e6
            if stopped is None and (wall >= 300 or consumed >= 180):
                stopped = "REPAIR_WALL" if wall >= 300 else "REPAIR_CPU"
                old.stop_owned_unreaped_child(pid)
            time.sleep(.2)
        code = os.waitstatus_to_exitcode(status)
        result.update(child_exit_code=code, stop_reason=stopped, wait4_reaped=True,
            user_seconds=usage.ru_utime, system_seconds=usage.ru_stime, max_rss_kib=usage.ru_maxrss,
            last_complete_call_record=old.last_record(output/"repair137/calls.jsonl"))
        pid = None
        result["post_child_custody"] = old.exclusive_supervisor(root)
        result_path = output/"repair137/RESULT.json"
        if result_path.is_file():
            raw = result_path.read_bytes()
            if len(raw) > 2097152:
                raise ValueError("repair result exceeds fixed cap")
            experiment = json.loads(raw)
            result.update(child_status=experiment["status"], child_result_sha256=hashlib.sha256(raw).hexdigest())
            if experiment["counts"] is None:
                result["counts_complete"] = False
                result["unknown_operations"].append("NO_TYPED_CALL_LEDGER")
            else:
                result["actual_counts"] = typed_counts(experiment["counts"])
            rerun = experiment.get("rerun_status", {})
            if (experiment["status"] != "REPAIR_COMPLETED"
                    or rerun.get("fit_internal_iteration_counts_complete") is False
                    or rerun.get("root_receipt_replay_count_complete") is False):
                result["counts_complete"] = False
                result["unknown_operations"].append("ABORTED_OR_UNRETURNED_OPERATIONS")
            if code != 0 or experiment["status"] != "REPAIR_COMPLETED" or experiment.get("integrity_errors"):
                raise RuntimeError("repair child failed; original and new failures retained; no retry")
        else:
            result.update(child_status="UNKNOWN_PARTIAL_EXECUTION", counts_complete=False)
            witness = result["last_complete_call_record"]
            if witness and witness["record"]:
                result["actual_counts"] = typed_counts(witness["record"].get("counts"))
            result["unknown_operations"].append("NO_FINAL_RESULT_COUNTS_ARE_LOWER_BOUNDS")
            raise RuntimeError("repair child produced no final result; no retry")
        check_sources(binding, helper, core, transfer)
        result["status"] = "REPAIR_COMPLETED"
    except BaseException as error:
        failure = error
        result.update(status="REPAIR_FAILED", error=repr(error))
        if pid is not None and not waited:
            old.stop_owned_unreaped_child(pid)
            _, status, usage = os.wait4(pid, 0)
            result.update(cleanup_child_exit_code=os.waitstatus_to_exitcode(status), cleanup_wait4_reaped=True,
                counts_complete=False)
            result["unknown_operations"].append("SUPERVISOR_FAILURE_DURING_OWNED_CHILD")
            witness = old.last_record(output/"repair137/calls.jsonl")
            result["last_complete_call_record"] = witness
            if witness and witness["record"]:
                result["actual_counts"] = typed_counts(witness["record"].get("counts"))
    finally:
        result["wall_seconds"] = time.monotonic()-started
        if root is not None:
            result["aggregate_cgroup_cpu_seconds"] = None if before_cpu is None else (old.cpu_usage(root)-before_cpu)/1e6
            result["cgroup_memory_events"] = (root/"memory.events").read_text().splitlines()
            try:
                result["final_custody"] = old.exclusive_supervisor(root)
            except BaseException as error:
                result["final_custody_unknown"] = repr(error)
                result["status"] = "REPAIR_FAILED"
                failure = failure or error
        result["combined_known_counts"] = {key:binding["old_transfer_actual_counts"].get(key, 0)+value
            for key,value in result["actual_counts"].items()}
        result["counts_complete_refers_to_new_repair_only"] = True
        result["original_outer_counts_complete_flag_preserved"] = binding["original_outer_counts_complete"]
        result["combined_counts_are_lower_bounds_if_incomplete"] = (
            not result["counts_complete"] or not binding["original_outer_counts_complete"])
        result["original_failed_fit_cost_included_once"] = True
        result["combined_fit_cap_is_new_repair_budget_not_original_per_parent_budget"] = True
        save(output/"OUTER_RESULT.json", result)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
