"""Prepare a fresh admitted native allocation while its inclusive owner is live."""

import argparse
import os
from pathlib import Path
import shutil
import stat
import time

from . import counterfactual as k
from . import native_common as n
from . import native_environment as environment
from . import native_owner as owner
from . import native_receipts as receipts
from .native_receipts import verify_archived_owner as verify_archived_owner


def preparation_directory(path_id):
    return n.ROOT / "preparation" / path_id


def qualification_disposition(reason, count):
    k.need(reason in (None, "EXACT_RUNTIME_MISMATCH", "ORIGINAL_JOINT_RESOURCE_QUALIFICATION_FAILED"),
           "Unknown qualification failure cannot authorize resource reallocation")
    return {
        "eligible": reason is not None, "reason": reason, "max_total_allocations": receipts.MAX_ALLOCATIONS,
        "allocation_ordinal": count + 1, "scientific_archive_downloads": 0, "scientific_payloads_decoded": False,
        "physical_training_microsteps": 0, "first_scientific_worker_started": False,
        "evidence_scope": "State at the original runtime qualification boundary, before portable inputs or any native worker.",
    }


def check_plan(contract):
    plan = n.read(contract["preparation_plan"])
    own = n.descriptor(n.OWN / "native_execution_plan.json")
    k.need(all(contract["preparation_plan"][key] == own[key] for key in ("bytes", "sha256")),
           "Execution preparation differs from the source-registered plan")
    k.need(plan.get("schema") == "hepta.visited-counterfactual.preparation-plan.1"
           and plan.get("execution_episode") == n.EPISODE
           and plan.get("max_total_allocations") == receipts.MAX_ALLOCATIONS
           and plan.get("maximum_prior_qualification_failures") == receipts.MAX_ALLOCATIONS - 1
           and plan.get("only_pre_science_exact_runtime_or_original_capacity_refusal_may_reallocate") is True
           and plan.get("automatic_retries") is False and plan.get("scientific_failures_retried") is False
           and plan.get("fixed_trajectory_paths") == plan.get("fixed_score_paths") == list(n.PATHS),
           "Preparation, fixed population or allocation policy differs")
    from . import native_capacity_basis

    basis = n.read(contract["resource_qualification"])
    native_capacity_basis.check(basis, contract["resources"])
    return plan, basis


def run(args):
    from . import native_capacity_basis
    from . import native_provider

    contract, item, binding = n.load_contract(args.contract, args.expected_contract_sha256)
    owner.phase_path(args.phase, args.path_id)
    producer = n.actual_actions_identity()
    k.need(producer["job"] == args.phase, "Unexpected current preparation producer")
    directory = preparation_directory(args.path_id)
    directory.mkdir(parents=True, exist_ok=False)
    owner_directory, _ = owner.paths(args.phase, args.path_id)
    plan = n.read(n.descriptor(owner_directory / "PLAN.json"))
    k.need(plan["contract"] == item and plan["current_producer"] == producer, "Preparation owner plan differs")
    health = owner.Health(contract["resources"], plan)
    result = {
        "schema": "hepta.visited-counterfactual.preparation-child.1", "execution_episode": n.EPISODE,
        "phase": args.phase, "path_id": args.path_id, "contract": item, "current_producer": producer,
        "resource_profile": contract["resources"], "status": "FAILED", "commands": [],
        "original_source_commit": binding["provider"]["head_sha"], "source_inventory": None,
        "runtime_qualification": None, "sdk": None, "portable_completion": None,
        "qualification_disposition": None, "prior_qualification_failures": [], "automatic_retry": False,
    }

    def command(label, argv, env=None):
        measured = owner.command(args, item, health, directory, label, argv, env)
        result["commands"].append({"label": label, "argv": argv, "owned": measured})
        return measured

    try:
        health(0)
        basis = n.read(contract["resource_qualification"])
        result["prior_capacity_acquisition"] = native_capacity_basis.acquire(basis, health)
        check_plan(contract)
        history = native_provider.collect_qualification_history(
            item, args.phase, args.path_id, directory / "qualification_history_downloads")
        result["prior_qualification_failures"] = receipts.compact_history(history["items"])
        receipts.history_checked(result["prior_qualification_failures"], producer, args.phase, args.path_id)
        k.need(history.get("complete") is True and history.get("current_producer") == producer,
               "Actual allocation history did not close")
        result["allocation_history"] = n.write(directory / "ALLOCATION_HISTORY.json", {
            "schema": "hepta.visited-counterfactual.compact-allocation-history.1", "execution_episode": n.EPISODE,
            "phase": args.phase, "path_id": args.path_id, "contract": item, "current_producer": producer,
            "current_provider_job": history["current_provider_job"],
            "prior_qualification_failures": result["prior_qualification_failures"],
            "maximum_total_allocations": receipts.MAX_ALLOCATIONS, "old_archives_embedded": False,
        })
        environment_result = environment.source_and_runtime(binding, directory, command)
        result.update(source_inventory=environment_result["source"], runtime_qualification=environment_result["runtime"],
                      qualification_disposition=qualification_disposition(environment_result["reason"], len(history["items"])))
        health(0)
        if environment_result["reason"] is not None:
            result["status"] = "QUALIFICATION_BLOCKED"
            receipts.preparation_checked(result, receipts.Literals(), contract, item, args.phase, args.path_id, producer)
            n.write(directory / "CHILD_COMPLETE.json", result)
            return 3
        result["sdk"] = environment.sdk(directory, command)
        _, adapter, _ = n.portable()
        command("portable", [environment_result["python"], "-B", str(Path(adapter.__file__).resolve()),
                             "--binding", contract["portable_binding"]["path"], "--expected-binding-sha256",
                             contract["portable_binding"]["sha256"], "--output", "/work/deployment_activity"])
        result["portable_completion"] = n.descriptor(Path("/work/deployment_activity/COMPLETE.json"))
        portable = n.read(result["portable_completion"])
        k.need(portable.get("complete") is True and portable.get("binding") == contract["portable_binding"]
               and portable.get("current_replay_identity") == producer, "Portable admission did not close under this producer")
        health(0)
        n.load_contract(args.contract, args.expected_contract_sha256)
        result["status"] = "COMPLETE"
        receipts.preparation_checked(result, receipts.Literals(), contract, item, args.phase, args.path_id, producer)
        n.write(directory / "CHILD_COMPLETE.json", result)
        return 0
    except BaseException as error:
        result.update(status="FAILED", error_type=type(error).__name__)
        if not (directory / "CHILD_COMPLETE.json").exists():
            n.write(directory / "CHILD_COMPLETE.json", result)
        return 2


def seal_preparation(contract, item, phase, path_id, child_item, measured, plan):
    prepared = n.read(child_item)
    producer = n.actual_actions_identity()
    commands = receipts.preparation_checked(prepared, receipts.Literals(), contract, item, phase, path_id, producer)
    k.need(prepared["status"] == "COMPLETE" and measured["result"]["exit_code"] == 0,
           "Failed preparation cannot be sealed")
    checked = receipts.verify_wait4(measured["measurement"], receipts.Literals(), {
        "execution_episode": n.EPISODE, "execution_contract": item, "phase": "preparation:" + phase + ":" + path_id,
    }, pinned_core=True)
    k.need(measured["result"] == checked["wait4"] and plan["current_producer"] == producer
           and all(command["intent"]["controller_identity"] == checked["start"]["identity"] for command in commands.values()),
           "Preparation command costs are not inside the actual preparation child")
    directory, _ = owner.paths(phase, path_id)
    return n.write(preparation_directory(path_id) / "COMPLETE.json", {
        "schema": "hepta.visited-counterfactual.preparation-complete.1", "complete": True,
        "execution_episode": n.EPISODE, "phase": phase, "path_id": path_id, "contract": item,
        "current_producer": producer, "resource_profile": contract["resources"], "child_completion": child_item,
        "preparation_owned_wait4": measured, "live_owner_intent": n.descriptor(directory / "inclusive_measurement/INTENT.json"),
        "portable_completion": prepared["portable_completion"], "runtime_qualification": prepared["runtime_qualification"],
        "original_source_commit": prepared["original_source_commit"], "source_inventory": prepared["source_inventory"],
        "allocation_history": prepared["allocation_history"], "prior_qualification_failures": prepared["prior_qualification_failures"],
        "nested_costs_are_attribution_not_additional": True,
    })


def verify_preparation(contract, contract_item, *, path_id, phase):
    owner.phase_path(phase, path_id)
    completion = n.descriptor(preparation_directory(path_id) / "COMPLETE.json")
    record = n.read(completion)
    producer = n.actual_actions_identity()
    k.need(record.get("schema") == "hepta.visited-counterfactual.preparation-complete.1"
           and record.get("complete") is True and record.get("execution_episode") == n.EPISODE
           and record.get("contract") == contract_item and record.get("phase") == phase and record.get("path_id") == path_id
           and record.get("current_producer") == producer and record.get("resource_profile") == contract["resources"],
           "Native preparation closure differs")
    commands = receipts.preparation_checked(n.read(record["child_completion"]), receipts.Literals(),
                                            contract, contract_item, phase, path_id, producer)
    row = record["preparation_owned_wait4"]
    checked = receipts.verify_wait4(row["measurement"], receipts.Literals(), {
        "execution_episode": n.EPISODE, "execution_contract": contract_item,
        "phase": "preparation:" + phase + ":" + path_id,
    }, pinned_core=True)
    k.need(row["result"] == checked["wait4"]
           and all(command["intent"]["controller_identity"] == checked["start"]["identity"] for command in commands.values()),
           "Preparation nested ownership differs")
    intent = n.read(record["live_owner_intent"])
    k.need(intent["binding"]["execution_contract"] == contract_item
           and intent["binding"]["phase"] == "inclusive:" + phase + ":" + path_id,
           "Native task is bound to another live owner")
    original = intent["controller_identity"]
    core = owner.fixed_core()
    k.need(core.proc_identity(original["pid"]) == original, "Inclusive owner is not live")
    ancestors, pid = [], os.getpid()
    for _ in range(32):
        current = core.proc_identity(pid)
        ancestors.append(pid)
        pid = current["parent_pid"]
        if pid <= 0:
            break
    directory, _ = owner.paths(phase, path_id)
    k.need(original["pid"] != os.getpid() and original["pid"] in ancestors
           and not (directory / "inclusive_measurement/CLOSURE.json").exists()
           and not (directory / "COMPLETE.json").exists(), "Native execution escaped its still-live inclusive owner")
    return {"completion": completion, "record": record, "cost": checked["wait4"], "identity": producer}


def packet_files(phase, path_id):
    directory, control = owner.paths(phase, path_id)
    roots = [directory, preparation_directory(path_id), control, Path("/work/deployment_activity"),
             Path("/work/preparation"), Path("/work/native_binding"), Path("/work/binding"), Path("/work/native_capacity"),
             n.ROOT / "archives" / phase / path_id]
    if phase == "global":
        roots += [n.ROOT / "global_restore", n.ROOT / "global_metadata"]
    if phase == "analysis":
        roots += [n.ROOT / "score_metadata"]
    excluded = {"qualification_history_downloads", "provider_inputs", "artifacts", "staged", "upload_root", "readback",
                "downloads", "received_receipts", "node_modules", "payload"}
    result = {}
    for root in roots:
        if not root.exists():
            continue
        k.need(root.resolve() == root and root.is_dir(), "Metadata root is linked or noncanonical")
        for base, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in excluded)
            for name in directories:
                k.need(not (Path(base) / name).is_symlink(), "Linked metadata directory")
            for name in sorted(files):
                path = Path(base) / name
                if path.suffix not in (".json", ".jsonl", ".log"):
                    continue
                k.need(stat.S_ISREG(path.lstat().st_mode) and path.resolve() == path, "Nonregular metadata packet member")
                result[str(path)] = path
    # The exact input/runtime declarations are also stored outside the preparation tree.
    child_path = preparation_directory(path_id) / "CHILD_COMPLETE.json"
    if child_path.exists():
        child = n.read(n.descriptor(child_path))
        if child.get("source_inventory"):
            source = n.read(child["source_inventory"])
            for key in ("input_contract", "runtime_contract"):
                path = n.checked(source[key])
                result[str(path)] = path
    for name in ("GLOBAL_INPUTS.json", "GLOBAL_TRAJECTORIES.json", "GLOBAL_SCORE_INPUTS.json", "RESULTS.json"):
        path = n.ROOT / name
        if path.exists():
            result[str(path)] = path
    return [result[key] for key in sorted(result)]


def delivery_packet(contract, item, phase, path_id, completion):
    started, cpu = time.monotonic(), time.process_time()
    directory = n.ROOT / "shard_receipts" / path_id
    directory.mkdir(parents=True, exist_ok=False)
    completed = n.read(completion)
    child = n.read(completed["child_result"]) if completed.get("child_result") else {}
    rows, total = [], 0
    for source in packet_files(phase, path_id):
        original = n.descriptor(source)
        total += original["bytes"]
        k.need(total <= 512 * 1024**2 and len(rows) < 50000, "Bounded metadata packet capacity exhausted")
        relative = "payload/" + str(source).lstrip("/")
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as stream, target.open("xb") as output:
            shutil.copyfileobj(stream, output)
            output.flush()
            os.fsync(output.fileno())
        current = n.descriptor(target)
        k.need(n.descriptor(source) == original and all(current[key] == original[key] for key in ("bytes", "sha256")),
               "Metadata packet copy changed literal bytes")
        rows.append({"path": relative, "original_path": str(source), "bytes": original["bytes"], "sha256": original["sha256"]})
    archived = child.get("science_archive_ack")
    return n.write(directory / "RECEIPT.json", {
        "schema": "hepta.visited-counterfactual.shard-delivery.1", "execution_episode": n.EPISODE,
        "phase": phase, "path_id": path_id, "contract": item, "current_producer": completed["current_producer"],
        "status": completed["status"], "inclusive_owner_complete": completion,
        "native_owner_complete": child.get("native_owner_complete"),
        "science_archive_ack": None if archived is None else archived["ack"],
        "qualification_disposition": completed.get("qualification_disposition"), "files": rows,
        "metadata_copy_self_cpu_seconds_before_receipt": time.process_time() - cpu,
        "metadata_copy_wall_seconds_before_receipt": time.monotonic() - started,
        "delivery_cost_scope": "After inclusive owner wait4; final receipt serialization and provider upload CPU remain separate and unknown.",
        "old_history_payloads_recursively_embedded": False, "artifact_retention_days": 90,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--phase", choices=("trajectories", "scores", "global", "analysis"), required=True)
    parser.add_argument("--path-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
