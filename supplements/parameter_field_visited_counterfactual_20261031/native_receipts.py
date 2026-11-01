"""Literal, portable ownership verification; recorded inodes are historical only."""

import hashlib
import math
import os
from pathlib import Path

from . import counterfactual as k
from . import native_common as n

MAX_ALLOCATIONS = 16
CORE_SHA = "ad6f049d5d2beb2f999921bc796908c5b4b37b1c4a22094e4669d480cd3cca01"
MEASUREMENT_NAMES = {"intent": "INTENT.json", "attempt_intent": "001.INTENT.json",
                     "start": "001.START.json", "wait4": "001.WAIT4.json", "closure": "CLOSURE.json"}


class Literals:
    def __init__(self, restored=None):
        self.restored = restored

    def item(self, original):
        k.need(type(original) is dict and set(original) == {"path", "bytes", "sha256"}, "Exact original descriptor required")
        actual = original if self.restored is None else self.restored[original["path"]]
        k.need((actual["bytes"], actual["sha256"]) == (original["bytes"], original["sha256"]),
               "Relocated evidence differs from its original literal pin")
        n.checked(actual)
        return actual

    def read(self, original):
        return n.read(self.item(original))


def finite_nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def measurement(directory, literals):
    directory = Path(directory)
    if literals.restored is None:
        return {key: n.descriptor(directory / name) for key, name in MEASUREMENT_NAMES.items()}
    return {key: {**literals.restored[str(directory / name)], "path": str(directory / name)}
            for key, name in MEASUREMENT_NAMES.items()}


def identity(value):
    k.need(type(value) is dict and set(value) == {"pid", "parent_pid", "pgid", "sid", "start_ticks"}
           and all(type(number) is int and number > 0 for number in value.values()), "Invalid original process identity")
    return value


def verify_wait4(items, literals, expected_binding, *, exit_code=0, argv=None, pinned_core=False):
    k.need(type(items) is dict and set(items) == set(MEASUREMENT_NAMES), "All five original ownership files are required")
    directories = {str(Path(item["path"]).parent) for item in items.values()}
    k.need(len(directories) == 1 and all(Path(items[key]["path"]).name == name for key, name in MEASUREMENT_NAMES.items()),
           "Ownership files were spliced across measurements")
    intent, attempt, start, waited, closure = (literals.read(items[key]) for key in MEASUREMENT_NAMES)
    binding = intent.get("binding", {})
    k.need(intent.get("schema") == "hepta.execution06.owned-children.intent.1"
           and closure.get("schema") == "hepta.execution06.owned-children.closure.1"
           and closure.get("binding") == binding
           and all(binding.get(key) == value for key, value in expected_binding.items())
           and binding.get("component_schema_is_implementation_version_not_execution_episode") is True,
           "Original owned-child schema or actual execution binding differs")
    if pinned_core:
        k.need(binding.get("owned_core_sha256") == CORE_SHA, "Owned implementation source differs")
    controller = identity(intent["controller_identity"])
    child = identity(start["identity"])
    k.need(closure.get("controller_identity") == controller and waited.get("identity") == child
           and child["parent_pid"] == controller["pid"] == start.get("wait4_owner_pid")
           and waited.get("pid") == child["pid"] != controller["pid"]
           and start.get("process_groups_changed") is False and start.get("attempt") == 1,
           "Actual wait4 parent and child identities do not join")
    actual_argv = attempt.get("argv")
    k.need(type(actual_argv) is list and bool(actual_argv)
           and all(type(value) is str for value in actual_argv) and Path(actual_argv[0]).is_absolute()
           and attempt.get("executable") == actual_argv[0]
           and start.get("argv") == actual_argv and start.get("cwd") == attempt.get("cwd")
           and (argv is None or actual_argv == argv)
           and attempt.get("constructor_environment_values_recorded") is False,
           "Owned command identity or literal argument vector differs")
    k.need(closure.get("all_returned_direct_children_reaped") is True
           and closure.get("accounting_complete_for_attempted_direct_workers") is True
           and closure.get("attempt_count") == closure.get("returned_children") == 1
           and len(closure.get("attempts", [])) == len(closure.get("children", [])) == 1
           and closure.get("construction_wait4_unavailable") is False
           and closure.get("original_exception") is None
           and closure.get("receipt_errors") == closure.get("cleanup_errors") == []
           and closure.get("pending_signal") is None and closure.get("scientific_completion_claim") is False,
           "Incomplete, interrupted or unknown owned-child accounting")
    closed_attempt = closure["attempts"][0]
    k.need(attempt.get("number") == closed_attempt.get("number") == 1
           and closed_attempt.get("construction_entered") is True and closed_attempt.get("returned_child") is True
           and closed_attempt.get("construction_wait4_unavailable") is False
           and all(closed_attempt.get(key) == attempt.get(key)
                   for key in ("argv", "cwd", "executable", "started_monotonic")), "Construction history differs")
    closed_child = closure["children"][0]
    k.need(closed_child.get("attempt") == 1 and closed_child.get("pid") == child["pid"]
           and closed_child.get("identity") == child and closed_child.get("wait4") == waited
           and closed_child.get("wait4_receipt") == items["wait4"]
           and closed_child.get("wait4_unavailable") is None and closed_child.get("signals") == []
           and waited.get("scientific_completion_claim") is False, "Wait4 literal and closure differ")
    k.need(type(waited.get("wait_status")) is int and os.waitstatus_to_exitcode(waited["wait_status"]) == exit_code
           and waited.get("exit_code") == exit_code and closure.get("return_value") == exit_code,
           "Original child did not exit with the required disposition")
    fields = ("cpu_seconds", "user_cpu_seconds", "system_cpu_seconds", "wall_seconds", "peak_rss_bytes")
    k.need(all(finite_nonnegative(waited.get(key)) for key in fields)
           and all(finite_nonnegative(closure.get(key)) for key in
                   ("direct_workers_cpu_seconds", "own_cpu_seconds_until_summary", "wall_seconds_until_summary"))
           and math.isclose(waited["cpu_seconds"], waited["user_cpu_seconds"] + waited["system_cpu_seconds"], rel_tol=0, abs_tol=1e-9)
           and math.isclose(closure["direct_workers_cpu_seconds"], waited["cpu_seconds"], rel_tol=0, abs_tol=1e-9),
           "Unknown, nonfinite or inconsistent measured CPU")
    times = [intent.get("started_unix"), attempt.get("started_unix"), start.get("returned_unix"), waited.get("waited_unix")]
    k.need(all(finite_nonnegative(value) for value in times) and times == sorted(times), "Ownership event times differ")
    return {"intent": intent, "attempt": attempt, "start": start, "wait4": waited,
            "closure": closure, "measurement": items}


def command_costs(prepared, literals, item, phase, path_id):
    expected = ["source_init", "source_remote", "source_fetch", "source_checkout", "python_download",
                "python_extract", "venv", "packages", "torch", "qualification"]
    if prepared["status"] == "COMPLETE":
        expected += ["sdk", "portable"]
    rows = prepared.get("commands")
    k.need(type(rows) is list and [row.get("label") for row in rows] == expected,
           "Preparation command population or qualification boundary differs")
    result = {}
    for row in rows:
        cost = row["owned"]
        checked = verify_wait4(cost["measurement"], literals, {
            "execution_episode": n.EPISODE, "execution_contract": item,
            "phase": "command:" + phase + ":" + path_id + ":" + row["label"],
        }, argv=row["argv"], pinned_core=True)
        k.need(cost["result"] == checked["wait4"], "Preparation command summary differs from real wait4")
        literals.item(cost["log"])
        result[row["label"]] = checked
    return result


def compact_history(items):
    return [{
        "provider_job": {key: row["provider_job"][key] for key in
                         ("id", "run_id", "run_attempt", "head_sha", "name", "status", "conclusion")},
        "artifact": row["artifact"],
        "delivery_receipt": {key: row["delivery_receipt"][key] for key in ("bytes", "sha256")},
        "original_owner_complete": row["original_owner_complete"],
        "cpu_seconds": row["verified_owner"]["cpu_seconds"], "wall_seconds": row["verified_owner"]["wall_seconds"],
    } for row in items]


def history_checked(rows, producer, phase, path_id):
    k.need(type(rows) is list and len(rows) <= MAX_ALLOCATIONS - 1, "Allocation history exceeds the prospective cap")
    ids, attempts = [], []
    for row in rows:
        k.need(set(row) == {"provider_job", "artifact", "delivery_receipt", "original_owner_complete", "cpu_seconds", "wall_seconds"},
               "History must contain compact literal pins, not recursive prior evidence")
        job = row["provider_job"]
        k.need(job.get("run_id") == int(producer["run_id"]) and job.get("head_sha") == producer["head_sha"]
               and job.get("name") == phase + " / " + path_id and job.get("status") == "completed"
               and job.get("conclusion") == "failure" and type(job.get("run_attempt")) is int
               and 0 < job["run_attempt"] < int(producer["run_attempt"])
               and type(job.get("id")) is int and job["id"] > 0,
               "Prior allocation is from another phase, source or producer")
        k.need(finite_nonnegative(row["cpu_seconds"]) and finite_nonnegative(row["wall_seconds"]), "Prior cost is unknown")
        k.sha(row["delivery_receipt"]["sha256"])
        k.sha(row["artifact"]["sha256"])
        k.sha(row["original_owner_complete"]["sha256"])
        ids.append(job["id"])
        attempts.append(job["run_attempt"])
    k.need(len(set(ids)) == len(ids) and attempts == sorted(set(attempts)), "Repeated or unordered allocation history")


def preparation_checked(prepared, literals, contract, item, phase, path_id, producer):
    from . import native_environment as environment
    from . import native_prepare as prepare

    k.need(prepared.get("schema") == "hepta.visited-counterfactual.preparation-child.1"
           and prepared.get("execution_episode") == n.EPISODE and prepared.get("contract") == item
           and prepared.get("phase") == phase and prepared.get("path_id") == path_id
           and prepared.get("current_producer") == producer and prepared.get("resource_profile") == contract["resources"]
           and prepared.get("status") in ("COMPLETE", "QUALIFICATION_BLOCKED"), "Preparation identity or disposition differs")
    history_checked(prepared["prior_qualification_failures"], producer, phase, path_id)
    commands = command_costs(prepared, literals, item, phase, path_id)
    source = literals.read(prepared["source_inventory"])
    c, _, _ = n.portable()
    binding = n.read(contract["portable_binding"])
    commit = binding["provider"]["head_sha"]
    for key in ("input_contract", "runtime_contract"):
        desc = source[key]
        relative = Path(desc["path"]).relative_to(n.SOURCE).as_posix()
        raw = c.git(n.ADDON, "show", commit + ":" + relative)
        raw = raw.encode() if isinstance(raw, str) else raw
        k.need(len(raw) == desc["bytes"] and hashlib.sha256(raw).hexdigest() == desc["sha256"],
               "Original source declaration does not exist at its immutable commit")
        literals.item(desc)
    target = literals.read(source["input_contract"])
    reason = environment.assess_runtime(literals.read(prepared["runtime_qualification"]), target)
    k.need(source.get("schema") == "hepta.visited-counterfactual.original-source-preparation.1"
           and source.get("source_commit") == prepared.get("original_source_commit") == commit
           and source.get("canonical_source") == str(n.SOURCE) and source.get("source_pristine") is True
           and source.get("scientific_inputs_downloaded") is False and source.get("scientific_values_decoded") is False
           and source.get("scientific_workers_started") == 0, "Source preparation was not the registered pre-science scope")
    expected_argv = [target["python"], "-B", str(n.SOURCE / "tools/parameter_field_executor/diagnose.py"),
                     "--output", prepared["runtime_qualification"]["path"]]
    k.need(commands["qualification"]["attempt"]["argv"] == expected_argv, "Qualification ran another program")
    k.need(prepared["qualification_disposition"] == prepare.qualification_disposition(reason, len(prepared["prior_qualification_failures"])),
           "Qualification disposition differs from actual runtime evidence")
    blocked = prepared["status"] == "QUALIFICATION_BLOCKED"
    k.need(blocked is (reason is not None), "Preparation status contradicts runtime evidence")
    if blocked:
        k.need(prepared.get("portable_completion") is None and prepared.get("sdk") is None,
               "Qualification retry was requested after scientific artifact preparation")
    else:
        portable = literals.read(prepared["portable_completion"])
        k.need(portable.get("complete") is True and portable.get("current_replay_identity") == producer
               and portable.get("binding") == contract["portable_binding"], "Fresh portable admission did not close")
        literals.item(prepared["sdk"])
    return commands


def native_costs(native, literals, item, phase, path_id, launcher):
    result = {}
    for name in ("runtime", "native"):
        row = native[name + "_wait4"]["result"]
        files = measurement(Path(row["wait4_receipt"]["path"]).parent, literals)
        checked = verify_wait4(files, literals, {
            "execution_episode": n.EPISODE, "execution_contract": item,
            "phase": name + ":" + phase + ":" + path_id,
        })
        k.need(checked["intent"]["controller_identity"] == launcher["start"]["identity"],
               "Native child measurement is outside the actual launcher subtree")
        k.need(row["wait4_receipt"] == files["wait4"] and row["ownership_closure"] == files["closure"]
               and all(row[key] == checked["wait4"][key] for key in
                       ("pid", "exit_code", "cpu_seconds", "wall_seconds", "peak_rss_bytes")),
               "Native measured summary differs from its original five files")
        result[name] = checked
    child = literals.read(native["child_completion"])
    k.need(child.get("complete") is True and child.get("execution_episode") == n.EPISODE
           and child.get("contract") == item and child.get("phase") == phase and child.get("path_id") == path_id
           and child.get("current_producer") == native["current_producer"] and child.get("output") == native["shard_complete"],
           "Native scientific child closure differs")
    return result


def verify_archived_owner(delivery_receipt_descriptor, restored_files, contract_item, provider_job, *, require_status=None):
    delivery = n.read(delivery_receipt_descriptor)
    contract = n.read(contract_item)
    literals = Literals(restored_files)
    original_item = delivery["inclusive_owner_complete"]
    owner = literals.read(original_item)
    phase, path_id = owner["phase"], owner["path_id"]
    producer = {"repository": "TrillionniumFoundation/hepta-private-ci", "run_id": str(provider_job["run_id"]),
                "run_attempt": str(provider_job["run_attempt"]), "head_sha": provider_job["head_sha"], "job": phase}
    k.need(delivery.get("schema") == "hepta.visited-counterfactual.shard-delivery.1"
           and owner.get("schema") == "hepta.visited-counterfactual.inclusive-owner.1"
           and provider_job.get("name") == phase + " / " + path_id and provider_job.get("status") == "completed"
           and all(record.get("execution_episode") == n.EPISODE and record.get("contract") == contract_item
                   and record.get("current_producer") == producer and record.get("phase") == phase
                   and record.get("path_id") == path_id for record in (owner, delivery)),
           "Inclusive owner, provider job and immutable delivery identities differ")
    status = owner.get("status")
    k.need(status in ("COMPLETE", "QUALIFICATION_BLOCKED") and delivery.get("status") == status
           and (require_status is None or status == require_status) and owner.get("automatic_retry") is False,
           "Failure or unknown owner cannot enter a success or reallocation population")
    blocked = status == "QUALIFICATION_BLOCKED"
    code = 3 if blocked else 0
    k.need(provider_job.get("conclusion") == ("failure" if blocked else "success")
           and owner.get("complete") is (not blocked) and owner.get("inclusive_exit_code") == code,
           "Provider and owned exit disposition differ")
    checked = verify_wait4(owner["inclusive_measurement"], literals, {
        "execution_episode": n.EPISODE, "execution_contract": contract_item,
        "phase": "inclusive:" + phase + ":" + path_id,
    }, exit_code=code, argv=owner["inclusive_argv"], pinned_core=True)
    child, plan = literals.read(owner["child_result"]), literals.read(owner["owner_plan"])
    k.need(child.get("schema") == "hepta.visited-counterfactual.lifecycle-child.1"
           and plan.get("schema") == "hepta.visited-counterfactual.inclusive-owner-plan.1"
           and all(record.get("execution_episode") == n.EPISODE and record.get("contract") == contract_item
                   and record.get("phase") == phase and record.get("path_id") == path_id
                   and record.get("current_producer") == producer for record in (child, plan))
           and plan.get("resource_profile") == contract["resources"] and child.get("status") == status
           and child.get("qualification_disposition") == owner.get("qualification_disposition") == delivery.get("qualification_disposition")
           and child.get("prior_qualification_failures") == owner.get("prior_qualification_failures"),
           "Inclusive child and plan closure differ")
    prepared = literals.read(child["preparation_child"])
    commands = preparation_checked(prepared, literals, contract, contract_item, phase, path_id, producer)
    k.need(prepared["prior_qualification_failures"] == owner["prior_qualification_failures"], "Preparation history differs")
    prep_row = child["preparation_owned_wait4"]
    prep = verify_wait4(prep_row["measurement"], literals, {
        "execution_episode": n.EPISODE, "execution_contract": contract_item,
        "phase": "preparation:" + phase + ":" + path_id,
    }, exit_code=code, pinned_core=True)
    k.need(prep_row["result"] == prep["wait4"]
           and prep["intent"]["controller_identity"] == checked["start"]["identity"]
           and all(command["intent"]["controller_identity"] == prep["start"]["identity"] for command in commands.values()),
           "Preparation and command wait4 costs are outside their actual inclusive parent subtree")
    if blocked:
        k.need(child.get("stage_reached") == "qualification_refused" and child.get("scientific_worker_started") is False
               and all(child.get(key) is None for key in ("preparation_complete", "native_owner_complete", "science_archive_ack"))
               and delivery.get("native_owner_complete") is None and delivery.get("science_archive_ack") is None,
               "Qualification refusal is not before scientific preparation and work")
    else:
        seal = literals.read(child["preparation_complete"])
        k.need(seal.get("schema") == "hepta.visited-counterfactual.preparation-complete.1" and seal.get("complete") is True
               and seal.get("execution_episode") == n.EPISODE and seal.get("contract") == contract_item
               and seal.get("phase") == phase and seal.get("path_id") == path_id and seal.get("current_producer") == producer
               and seal.get("resource_profile") == contract["resources"] and seal.get("child_completion") == child["preparation_child"]
               and seal.get("preparation_owned_wait4") == prep_row
               and child.get("stage_reached") == "native_and_required_archival_closed" and child.get("scientific_worker_started") is True,
               "Preparation seal or completed native stage differs")
        native = literals.read(child["native_owner_complete"])
        k.need(native.get("complete") is True and native.get("contract") == contract_item and native.get("phase") == phase
               and native.get("path_id") == path_id and native.get("current_producer") == producer
               and native.get("preparation") == child["preparation_complete"]
               and delivery.get("native_owner_complete") == child["native_owner_complete"], "Native owner identity differs")
        launcher_row = child["native_launcher_wait4"]
        launcher = verify_wait4(launcher_row["measurement"], literals, {
            "execution_episode": n.EPISODE, "execution_contract": contract_item,
            "phase": "command:" + phase + ":" + path_id + ":native",
        }, pinned_core=True)
        k.need(launcher_row["result"] == launcher["wait4"]
               and launcher["intent"]["controller_identity"] == checked["start"]["identity"],
               "Native launcher cost is outside the inclusive owner subtree")
        native_costs(native, literals, contract_item, phase, path_id, launcher)
        if phase in ("trajectories", "scores"):
            from . import native_transport

            archived = child["science_archive_ack"]
            k.need(delivery.get("science_archive_ack") == archived["ack"], "Delivery binds another archive ACK")
            ack, manifest = literals.read(archived["ack"]), literals.read(archived["manifest"])
            native_transport.validate_ack_metadata(ack, manifest, archived["binding"], manifest["files"])
            k.need(ack["identity"] == producer and archived["binding"]["native_owner_complete"] == child["native_owner_complete"],
                   "Science archive belongs to another actual owner")
        else:
            k.need(child.get("science_archive_ack") is None and delivery.get("science_archive_ack") is None
                   and child.get("global_output") == native["shard_complete"], "Global output closure differs")
            literals.item(child["global_output"])
    return {"owner_complete": literals.item(original_item), "owner": owner, "wait4": checked["wait4"],
            "cpu_seconds": checked["wait4"]["cpu_seconds"], "wall_seconds": checked["wait4"]["wall_seconds"],
            "qualification_eligible": blocked,
            "cost_scope": "Inclusive preparation through required archive readback; nested costs are not added. Final receipt delivery is separate."}
