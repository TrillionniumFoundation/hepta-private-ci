"""A live inclusive owner for preparation, native work and archive readback."""

import argparse
import importlib.util
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from . import counterfactual as k
from . import native_common as n

CORE_PATH = n.ADDON / "operational/parameter_field_recovery06/owned_children.py"
CORE_SHA = "ad6f049d5d2beb2f999921bc796908c5b4b37b1c4a22094e4669d480cd3cca01"
CONTRACT_PATH = Path("/work/native_binding/CONTRACT.json")
PACKAGE = "supplements.parameter_field_visited_counterfactual_20261031"
MEASUREMENT_FILES = {"intent": "INTENT.json", "attempt_intent": "001.INTENT.json",
                     "start": "001.START.json", "wait4": "001.WAIT4.json", "closure": "CLOSURE.json"}


def fixed_core():
    k.need(n.descriptor(CORE_PATH)["sha256"] == CORE_SHA, "Original owned-child core differs")
    spec = importlib.util.spec_from_file_location("_visited_owned_children_fixed_c2", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measurement(directory):
    return {key: n.descriptor(directory / name) for key, name in MEASUREMENT_FILES.items()}


def owned(argv, directory, *, binding, health, env=None, cwd=None):
    directory = Path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    empty = directory.parent / "empty_cwd"
    empty.mkdir(exist_ok=True)
    log = directory.with_name(directory.name + ".log")
    core = fixed_core()
    scope = core.OwnedChildren(directory, {
        "component_schema_is_implementation_version_not_execution_episode": True,
        "owned_core_sha256": CORE_SHA, **binding,
    }, term_grace_seconds=30, kill_wait_seconds=30)
    selector = selectors.DefaultSelector()
    failure = None
    result = None
    saved = {}

    def interrupted(number, frame):
        raise InterruptedError("Owned lifecycle received signal " + str(number))

    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            saved[number] = signal.signal(number, interrupted)
        health(0)
        with log.open("xb", buffering=0) as output:
            child = scope.spawn(subprocess.Popen, argv, cwd=str(cwd or empty),
                                env={**os.environ, "PYTHONPATH": str(n.SOURCE) + ":" + str(n.ADDON),
                                     "PYTHONDONTWRITEBYTECODE": "1", **(env or {})},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            total = 0
            while True:
                health(0)
                scope.health_check()
                code = child.poll()
                for event, _ in selector.select(0.2):
                    chunk = os.read(event.fd, 65536)
                    if chunk:
                        total += len(chunk)
                        k.need(total <= 4 * 1024**2, "Owned command log exceeded its registered bound")
                        output.write(chunk)
                    else:
                        selector.unregister(event.fileobj)
                if code is not None and not selector.get_map():
                    result = dict(child.wait4)
                    break
            os.fsync(output.fileno())
    except BaseException as error:
        failure = error
    finally:
        selector.close()
        for number in saved:
            signal.signal(number, signal.SIG_IGN)
        try:
            scope.close(failure, None if result is None else result["exit_code"])
        finally:
            for number, handler in saved.items():
                signal.signal(number, handler)
    if failure is not None:
        raise failure
    return {"measurement": measurement(directory), "result": result, "log": n.descriptor(log)}


def cpu_usage():
    rows = dict(line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines())
    value = int(rows["usage_usec"])
    k.need(value >= 0, "Invalid actual cgroup CPU counter")
    return value


class Health:
    def __init__(self, resources, plan=None):
        self.resources = resources
        self.started_cpu = cpu_usage() if plan is None else plan["cgroup_cpu_start_usec"]
        kwargs = {} if plan is None else {"started": plan["started_monotonic"], "oom": plan["oom"]}
        self.storage = n.Health(resources, "task", n.ROOT, **kwargs)

    def __call__(self, required=0):
        self.storage(required)
        delta = cpu_usage() - self.started_cpu
        k.need(0 <= delta < self.resources["task_cpu_seconds"] * 1000000,
               "Inclusive live cgroup CPU budget exhausted")


def phase_path(phase, path_id):
    k.need(phase in ("trajectories", "scores", "global", "analysis"), "Unknown native phase")
    k.need(path_id in n.PATHS if phase in ("trajectories", "scores") else path_id == phase,
           "Path is outside the fixed phase population")


def paths(phase, path_id):
    phase_path(phase, path_id)
    owner = n.ROOT / "owners" / phase / path_id
    control = {"trajectories": n.ROOT / "jobs" / path_id, "scores": n.ROOT / "score_jobs" / path_id,
               "global": n.ROOT / "global_job", "analysis": n.ROOT / "analysis_job"}[phase]
    return owner, control


def command(args, item, health, base, label, argv, env=None):
    row = owned(argv, base / "commands" / label, binding={
        "execution_episode": n.EPISODE, "execution_contract": item, "stage": args.phase,
        "path_id": args.path_id, "phase": "command:" + args.phase + ":" + args.path_id + ":" + label,
    }, health=health, env=env)
    k.need(row["result"]["exit_code"] == 0, "Owned command failed: " + label)
    return row


def native_arguments(args, item, inputs):
    argv = ["/opt/runtime/venv/bin/python", "-B", "-m", PACKAGE + ".native_runner", "--contract", item["path"],
            "--expected-contract-sha256", item["sha256"]]
    if args.phase == "trajectories":
        return argv + ["--path-id", args.path_id]
    registry = inputs["archive_registry"]
    if args.phase == "scores":
        global_item = inputs["global_trajectories"]
        argv += ["--score-path-id", args.path_id, "--global-trajectories", global_item["path"],
                 "--expected-global-sha256", global_item["sha256"]]
    else:
        argv += ["--seal-trajectories" if args.phase == "global" else "--analyze-scores"]
    return argv + ["--archive-registry", registry["path"], "--expected-archive-registry-sha256", registry["sha256"]]


def child(args):
    from . import native_prepare as prepare

    contract, item, _ = n.load_contract(args.contract, args.expected_contract_sha256)
    owner, control = paths(args.phase, args.path_id)
    plan = n.read(n.descriptor(owner / "PLAN.json"))
    identity = n.actual_actions_identity()
    k.need(plan["contract"] == item and plan["current_producer"] == identity, "Inclusive owner plan changed")
    health = Health(contract["resources"], plan)
    result = {
        "schema": "hepta.visited-counterfactual.lifecycle-child.1", "execution_episode": n.EPISODE,
        "phase": args.phase, "path_id": args.path_id, "contract": item, "current_producer": identity,
        "status": "FAILED", "stage_reached": "before_preparation", "scientific_worker_started": False,
        "preparation_complete": None, "native_owner_complete": None, "science_archive_ack": None,
        "qualification_disposition": None, "prior_qualification_failures": [],
    }
    try:
        argv = [sys.executable, "-B", "-m", PACKAGE + ".native_prepare", "--contract", item["path"],
                "--expected-contract-sha256", item["sha256"], "--phase", args.phase, "--path-id", args.path_id]
        prepared_owned = owned(argv, owner / "preparation_measurement", binding={
            "execution_episode": n.EPISODE, "execution_contract": item,
            "phase": "preparation:" + args.phase + ":" + args.path_id,
        }, health=health)
        prepared_item = n.descriptor(prepare.preparation_directory(args.path_id) / "CHILD_COMPLETE.json")
        prepared = n.read(prepared_item)
        result.update(preparation_child=prepared_item, preparation_owned_wait4=prepared_owned,
                      qualification_disposition=prepared["qualification_disposition"],
                      prior_qualification_failures=prepared["prior_qualification_failures"])
        if prepared_owned["result"]["exit_code"] == 3:
            k.need(prepared["status"] == "QUALIFICATION_BLOCKED", "Exit 3 without a closed qualification refusal")
            result.update(status="QUALIFICATION_BLOCKED", stage_reached="qualification_refused")
            n.write(owner / "CHILD_RESULT.json", result)
            return 3
        k.need(prepared_owned["result"]["exit_code"] == 0 and prepared["status"] == "COMPLETE", "Preparation failed")
        result["preparation_complete"] = prepare.seal_preparation(
            contract, item, args.phase, args.path_id, prepared_item, prepared_owned, plan)
        result["stage_reached"] = "prepared"
        inputs = {}
        if args.phase != "trajectories":
            from . import native_collector

            if args.phase == "scores":
                inputs = native_collector.collect_score_inputs(item, args.path_id, owner / "provider_inputs")
            else:
                inputs["archive_registry"] = native_collector.collect_population(
                    item, phase="trajectories" if args.phase == "global" else "scores", output_dir=owner / "provider_inputs")
        health(0)
        result.update(scientific_worker_started=True, stage_reached="native_worker")
        result["native_launcher_wait4"] = command(args, item, health, owner, "native", native_arguments(args, item, inputs))
        native_item = n.descriptor(control / "COMPLETE.json")
        native = n.read(native_item)
        k.need(native.get("complete") is True and native["contract"] == item
               and native["phase"] == args.phase and native["path_id"] == args.path_id, "Native owner did not close")
        result["native_owner_complete"] = native_item
        if args.phase in ("trajectories", "scores"):
            from . import native_transport

            binding = {
                "execution_episode": n.EPISODE, "stage": args.phase, "execution_contract": item,
                "path_id": args.path_id, "ordinal": n.PATHS.index(args.path_id) + 1,
                "parent_ids": [row["id"] for row in k.PARENTS.values() if row["path_id"] == args.path_id],
                "shard_complete": native["shard_complete"], "native_owner_complete": native_item,
                "original_source_commit": prepared["original_source_commit"],
                "registered_addon_commit": contract["addon"]["registered_commit"],
            }
            if args.phase == "scores":
                binding["global_barrier"] = inputs["global_trajectories"]
            population = native_transport.population(args.path_id, args.phase)
            archived = native_transport.archive_shard(args.path_id, population, binding,
                n.ROOT / "archives" / args.phase / args.path_id, health_check=lambda: health(0))
            native_transport.verify_shard(archived, binding, population)
            result["science_archive_ack"] = archived
        else:
            result["global_output"] = native["shard_complete"]
        health(0)
        result.update(status="COMPLETE", stage_reached="native_and_required_archival_closed")
        n.write(owner / "CHILD_RESULT.json", result)
        return 0
    except BaseException as error:
        result.update(status="FAILED", error_type=type(error).__name__, error=str(error)[:4096], automatic_retry=False)
        if not (owner / "CHILD_RESULT.json").exists():
            n.write(owner / "CHILD_RESULT.json", result)
        return 2


def run(args):
    from . import native_prepare as prepare

    started, cpu = time.monotonic(), time.process_time()
    k.need(args.contract == CONTRACT_PATH, "Contract must have the same canonical path on every host")
    item = n.descriptor(args.contract)
    k.need(item["sha256"] == args.expected_contract_sha256, "Contract digest mismatch")
    contract = n.read(item)
    k.need(contract.get("schema") == n.SCHEMA and contract.get("execution_episode") == n.EPISODE, "Wrong contract")
    owner, _ = paths(args.phase, args.path_id)
    identity = n.actual_actions_identity()
    k.need(identity["job"] == args.phase and not n.ROOT.exists(), "A fresh registered phase allocation is required")
    owner.mkdir(parents=True)
    health = Health(contract["resources"])
    health(0)
    plan = n.write(owner / "PLAN.json", {
        "schema": "hepta.visited-counterfactual.inclusive-owner-plan.1", "execution_episode": n.EPISODE,
        "phase": args.phase, "path_id": args.path_id, "contract": item, "current_producer": identity,
        "started_monotonic": started, "started_unix": time.time(), "cgroup_cpu_start_usec": health.started_cpu,
        "oom": n.cgroup(), "resource_profile": contract["resources"], "preparation_not_started": True,
        "engineering_bootstrap_cost_scope": {
            "outside_inclusive": ["container image pull", "base OS packages", "owner source checkout", "control resolution"],
            "cpu_seconds": None,
        }, "automatic_reallocation": False,
    })
    argv = [sys.executable, "-B", "-m", PACKAGE + ".native_owner", "--contract", item["path"],
            "--expected-contract-sha256", item["sha256"], "--phase", args.phase, "--path-id", args.path_id, "--child"]
    measured = None
    error_type = None
    try:
        measured = owned(argv, owner / "inclusive_measurement", binding={
            "execution_episode": n.EPISODE, "execution_contract": item,
            "phase": "inclusive:" + args.phase + ":" + args.path_id,
        }, health=health)
    except BaseException as error:
        error_type = type(error).__name__
    child_item = n.descriptor(owner / "CHILD_RESULT.json") if (owner / "CHILD_RESULT.json").exists() else None
    record = n.read(child_item) if child_item else {}
    code = None if measured is None else measured["result"]["exit_code"]
    status = {0: "COMPLETE", 3: "QUALIFICATION_BLOCKED"}.get(code, "FAILED")
    if record.get("status") != status:
        status = "FAILED"
    inclusive_items = measured["measurement"] if measured else None
    if inclusive_items is None:
        try:
            inclusive_items = measurement(owner / "inclusive_measurement")
        except (OSError, ValueError):
            pass
    completion = n.write(owner / "COMPLETE.json", {
        "schema": "hepta.visited-counterfactual.inclusive-owner.1", "execution_episode": n.EPISODE,
        "phase": args.phase, "path_id": args.path_id, "contract": item, "current_producer": identity,
        "status": status, "complete": status == "COMPLETE", "owner_plan": plan, "child_result": child_item,
        "inclusive_measurement": inclusive_items, "inclusive_argv": argv, "inclusive_exit_code": code,
        "qualification_disposition": record.get("qualification_disposition"),
        "prior_qualification_failures": record.get("prior_qualification_failures", []),
        "launcher_self_cpu_seconds_before_final_receipt": time.process_time() - cpu,
        "launcher_wall_seconds_before_final_receipt": time.monotonic() - started,
        "inclusive_cost_scope": "Preparation through required independent archive readback; nested costs are attribution, not extra CPU.",
        "post_owner_receipt_packaging_and_delivery_outside_inclusive": True,
        "automatic_retry": False, "error_type": error_type,
    })
    prepare.delivery_packet(contract, item, args.phase, args.path_id, completion)
    return {"COMPLETE": 0, "QUALIFICATION_BLOCKED": 3}.get(status, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--phase", choices=("trajectories", "scores", "global", "analysis"), required=True)
    parser.add_argument("--path-id", required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    raise SystemExit(child(args) if args.child else run(args))


if __name__ == "__main__":
    main()
