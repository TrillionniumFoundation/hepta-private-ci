"""Read-only native closure audit, lossless union, and frozen CPU analysis.

This is a separate continuation control, not part of the qualified numerical or
training source. It cannot submit a provider job, train, select, evaluate an
episode, mutate the owner ledger, or clear a HALTED owner. A binding is supplied
only after the final native owner and any explicitly reviewed recovery chain are
known. A finite watcher deadline stops observation only.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time


MAX_EVENTS = 4096
MAX_LEDGER_BYTES = 512 * 1024**2
MAX_UNION_BYTES = 16 * 1024**3
MAX_RECEIPT_BYTES = 16 * 1024**2
TERMINAL = {"COMPLETED", "FAILED", "TIMEOUT"}


class ClosureError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ClosureError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    canonical(value)
    return value


def safe(path):
    path = Path(path).absolute()
    require(".." not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)), "Unsafe path")
    return path


def version(item):
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def bytes_at(path, limit=MAX_RECEIPT_BYTES):
    path = safe(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit, "Unsafe/oversized file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(version(os.fstat(stream.fileno())) == version(before), "File changed before read")
        raw = stream.read(limit + 1)
    require(len(raw) == before.st_size and version(path.lstat()) == version(before), "File changed during read")
    return raw


def read(path, expected=None):
    raw = bytes_at(path)
    require(expected is None or sha(raw) == expected, "Evidence SHA256 mismatch: " + str(path))
    return strict(raw)


def exclusive(path, value):
    path = safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else canonical(value)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def pinned_module(name, path, expected):
    raw = bytes_at(path)
    require(sha(raw) == expected, "Pinned control changed")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def dependencies(control_root, control_pins):
    root = safe(control_root)
    for name, expected in control_pins.items():
        require(sha(bytes_at(root / name)) == expected, "Control identity changed: " + name)
    owner = pinned_module("hcsn_closure_owner", root / "native_owner.py", control_pins["native_owner.py"])
    capsule = pinned_module("hcsn_closure_capsule", root / "capsule_contract.py", control_pins["capsule_contract.py"])
    return owner, capsule


def ledger_snapshot(owner, config, root, allowed_recovery_events=()):
    """Replay without constructing Ledger, taking its lock, or writing its tree."""
    directory = safe(root) / "events"
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    require(len(paths) <= MAX_EVENTS, "Ledger event bound exceeded; no truncated accounting")
    state, previous, total, records = owner.initial_state(config), None, 0, []
    for number, path in enumerate(paths, 1):
        raw = bytes_at(path)
        total += len(raw)
        require(total <= MAX_LEDGER_BYTES, "Ledger byte bound exceeded; no truncated accounting")
        event = strict(raw)
        require(path.name == f"{number:06d}.json" and event["sequence"] == number
                and event["previous_sha256"] == previous, "Broken native ledger chain")
        owner.validate_state_transition(state, event["state"], event["kind"], event.get("evidence"))
        digest = sha(raw)
        if state["halted"] is not None and event["state"]["halted"] is None:
            require(digest in allowed_recovery_events, "HALTED state cleared without an explicitly bound reviewed recovery event")
        records.append(dict(path=str(path), bytes=len(raw), sha256=digest, event=event, before=state))
        previous, state = digest, event["state"]
    return dict(state=state, head=previous, records=records, bytes=total)


def progress(snapshot):
    state = snapshot["state"]
    counts = dict(Counter(row["state"] for row in state["fits"].values()))
    known = [row.get("optimizer_updates_completed") for row in state["fits"].values() if row["ever_claimed"]]
    return dict(registered_fit_count=len(state["fits"]), fit_counts=counts,
                ever_claimed_fit_count=sum(row["ever_claimed"] for row in state["fits"].values()),
                known_optimizer_updates_lower_bound=sum(x for x in known if type(x) is int and x >= 0),
                missing_update_counter_count=sum(type(x) is not int for x in known),
                reserved_is_not_a_training_attempt=True, registered_is_not_successful=True,
                active=state["active"], halted=state["halted"], execution_finished=state["execution_finished"],
                ledger_head=snapshot["head"], full_physical_energy_joules=None, monetary_cost=None)


def validate_closure(config, snapshot, handoff, handoff_path, source_root):
    state = snapshot["state"]
    require(len(state["fits"]) == 160 and len(state["groups"]) == 8, "Global denominator differs")
    require(state["active"] is None and state["halted"] is None and state["execution_finished"] is True,
            "Owner is active, halted, or not execution-closed")
    require(all(row["state"] in TERMINAL for row in state["fits"].values()), "Not all registered identities have known terminals")
    require(snapshot["records"] and snapshot["records"][-1]["event"]["kind"] == "EXECUTION_CLOSED", "Native closure event missing")
    require(state["final_handoff"] == dict(path=str(handoff_path), sha256=sha(bytes_at(handoff_path))), "Handoff is not the ledger-bound original")
    last = snapshot["records"][-1]["event"]
    require(last["previous_sha256"] == handoff["ledger_head_before_closure"], "Handoff ledger head differs")
    require(handoff.get("schema") == "hcsn-mechanism-full-study-analysis-handoff-v1"
            and handoff.get("status") == "EXECUTION_CLOSED_ANALYSIS_PENDING", "Handoff status/schema differs")
    for key in ("identity", "published_plan_commit", "published_plan_ref", "publication_receipt", "control_pins", "qualified_input"):
        require(handoff.get(key) == config[key], "Handoff identity differs: " + key)
    require(handoff.get("source_root") == str(source_root)
            and handoff.get("plan_path") == str(Path(source_root) / config["plan_relative_path"]), "Handoff source/plan path differs")
    require(handoff["ledger_events_directory"] == str(Path(config["state_root"]) / "events")
            and handoff["adapter_calls_directory"] == str(Path(config["state_root"]) / "adapter-calls"), "Handoff evidence root differs")
    require([g["group_id"] for g in handoff["groups"]] == [g["group_id"] for g in config["groups"]], "Eight-group roster differs")
    for row, expected in zip(handoff["groups"], config["groups"]):
        group = state["groups"][row["group_id"]]
        require(row["fit_ids"] == expected["fit_ids"] and group["phase"] == "done"
                and set(group["ever_claimed_fit_ids"]) == set(expected["fit_ids"]), "Group identity/claims not closed")
        require(row["capsule"] == group["prior_capsule"] and row["selected_ids"] == group["selected_ids"]
                and row["selection_lock_sha256"] == group["verified_selection_lock_sha256"], "Final capsule/selection differs from ledger")
        require(set(group["evaluations"]) == set(group["selected_ids"])
                and all(x["state"] in TERMINAL for x in group["evaluations"].values()), "Selected evaluations have unknown/missing terminals")


def capsule_chains(owner, capsule, config, snapshot):
    """Authenticate each accepted native producer and immutable parent transition."""
    chains, costs, receipt_files = {}, [], {}
    for record in snapshot["records"]:
        event = record["event"]
        if event["kind"] != "CAPSULE_ACCEPTED":
            continue
        active, evidence = record["before"]["active"], event["evidence"]
        require(active is not None and all(evidence.get(k) is True for k in
                ("provider_terminal_verified", "full_capsule_verified", "final_state_attested")), "Accepted event lacks native proof")
        remote, artifacts = evidence["producer"], evidence["artifact_verification"]
        owner.validate_remote(remote, active, config)
        require(remote["job"]["state"] == "succeeded" and active["terminal_observation"] == remote, "Accepted provider terminal differs")
        directory = owner.verified_artifacts(artifacts, remote, active)
        execution = read(directory / "execution.json")
        require(execution.get("schema") == "hcsn-mechanism-colab-batch-v3", "Not an actual Colab execution receipt")
        owner.validate_execution_producer(execution, remote, active)
        owner.validate_materialization(read(directory / "asset-materialization.json"), active)
        for key in ("request_id", "group_id", "phase", "identity", "source_pins", "control_pins", "plan_sha256",
                    "published_plan_commit", "published_plan_ref", "planned_fit_ids", "planned_evaluation_ids", "qualified_input", "prior_capsule"):
            require(execution.get(key) == active[key], "Execution differs from dispatch: " + key)
        require(execution.get("status") == "EXPORTED" and execution.get("halt_owner") is False
                and all(execution.get(k) is True for k in ("source_unchanged", "environment_verified", "worker_children_stopped", "final_state_attested", "capsule_verified")), "Unaccepted execution cannot close analysis")
        owner.check_environment(config["execution_environment"], execution["observed_environment"]["environment"])
        require(execution["observed_environment"]["check"].get("matched") is True, "Execution environment proof missing")
        group_id = active["group_id"]
        cap = event["state"]["groups"][group_id]["prior_capsule"]
        proof = execution["capsule"]
        require(cap["native_manifest_path"] == str(directory / "capsule-manifest.json")
                and cap["native_archive_path"] == str(directory / "study-capsule.tar.gz")
                and cap["execution_path"] == str(directory / "execution.json"), "Native capsule path differs")
        require(cap["execution_sha256"] == sha(bytes_at(directory / "execution.json"))
                and cap["request_id"] == active["request_id"]
                and cap["colab_producer"] == owner.validate_remote(remote, active, config), "Capsule producer binding differs")
        for name in ("manifest_sha256", "archive_sha256", "archive_bytes"):
            require(cap[name] == proof[name], "Capsule artifact receipt differs")
        inventory = {row["path"]: row for row in artifacts["files"]}
        require(inventory["study-capsule.tar.gz"]["bytes"] == cap["archive_bytes"]
                and inventory["study-capsule.tar.gz"]["sha256"] == cap["archive_sha256"], "Capsule archive differs from authenticated actual bytes")
        manifest = read(cap["native_manifest_path"], cap["manifest_sha256"])
        require(manifest["archive"] == dict(bytes=cap["archive_bytes"], sha256=cap["archive_sha256"]), "Archive and manifest disagree")
        expected = next(g for g in config["groups"] if g["group_id"] == group_id)
        require(manifest["identity"] == config["identity"] and manifest["group_id"] == group_id
                and manifest["expected_group_fit_ids"] == expected["fit_ids"], "Capsule group identity differs")
        prior = chains.get(group_id)
        require(active["prior_capsule"] == (prior["capsule"] if prior else None), "Native producer chain skipped/replaced a parent")
        capsule.validate_transition(prior["manifest"] if prior else None, manifest,
                                    active["ever_claimed_fit_ids"], active["ever_claimed_evaluation_ids"])
        chains[group_id] = dict(capsule=cap, manifest=manifest)
        costs.append(dict(request_id=active["request_id"], group_id=group_id, phase=active["phase"],
                          native_event_sha256=record["sha256"], execution_path=cap["execution_path"],
                          execution_sha256=cap["execution_sha256"], costs=execution.get("costs")))
        require(evidence.get("execution_costs") == execution.get("costs"), "Native cost receipt differs from the original execution")
        for item in artifacts["files"]:
            path = str(directory / item["path"])
            receipt_files[path] = dict(bytes=item["bytes"], sha256=item["sha256"])
    for group_id, group in snapshot["state"]["groups"].items():
        require(group_id in chains and chains[group_id]["capsule"] == group["prior_capsule"], "Latest accepted group capsule missing")
    return chains, dict(provider_execution_receipts=costs, authenticated_artifact_inventory=receipt_files,
                       scope="Per-provider run_batch, supervisor, worker, bootstrap and GPU intervals are nested; no grand wall/energy sum",
                       complete_total_cost=False,
                       other_required_cost_sources=["One-time bundle precompute metadata", "Qualification/search/failed transport records before this formal owner", "Provider queue/startup/finalization", "External deployment and retention tasks"],
                       full_physical_energy_joules=None, monetary_cost=None)


def assemble(owner, capsule, config, plan, snapshot, handoff, chains, destination, restoration_root):
    destination, restoration_root = safe(destination), safe(restoration_root)
    require(not destination.exists() and not restoration_root.exists(), "Assembly/restoration output already exists; never overwrite")
    restored, files, dirs, semantics, members, origin, study_origins = [], {}, set(), set(), set(), {}, []
    for row in handoff["groups"]:
        group_id, cap = row["group_id"], row["capsule"]
        manifest = chains[group_id]["manifest"]
        require(cap == chains[group_id]["capsule"], "Handoff capsule is not the accepted final parent")
        require(set(manifest["claimed_fit_ids"]) == set(row["fit_ids"]) and not members.intersection(row["fit_ids"]), "Group claims incomplete/overlapping")
        require(set(manifest["claimed_evaluation_ids"]) == set(row["selected_ids"]), "Selected evaluation claim set differs")
        group_path = restoration_root / group_id
        capsule.restore_capsule(cap["native_archive_path"], manifest, group_path, config["identity"], group_id, row["fit_ids"],
                                row["fit_ids"], row["selected_ids"])
        selected, lock_sha = owner.verify_selection(group_path, dict(group_id=group_id, fit_ids=row["fit_ids"]), plan, config)
        require(selected == row["selected_ids"] and lock_sha == row["selection_lock_sha256"], "Selection differs from frozen validation-only evidence")
        outcomes, evaluations = owner.inspect_claims(group_path, manifest, config, "evaluation", selected, lock_sha)
        require(outcomes == {i: snapshot["state"]["fits"][i] for i in row["fit_ids"]}, "Training terminal differs from global ledger")
        require(evaluations == snapshot["state"]["groups"][group_id]["evaluations"], "Evaluation terminal differs from global ledger")
        block = read(group_path / "blocks" / group_id / "terminal.json")
        require(block.get("identity") == config["identity"] and block.get("group_id") == group_id
                and block.get("selection_lock_sha256") == lock_sha
                and block.get("training_terminal_status") == {i: outcomes[i]["state"] for i in row["fit_ids"]}, "Block terminal differs")
        members.update(row["fit_ids"])
        semantics.add(manifest["study_semantic_sha256"])
        study_origins.append(dict(group_id=group_id, raw=manifest["files"]["study.json"]))
        dirs.update(manifest["directories"])
        for name, pin in manifest["files"].items():
            if name == "study.json" and name in files:
                continue  # Every exact original remains in its restored group directory.
            require(name not in files or files[name] == pin, "Conflicting immutable cross-group path: " + name)
            if name not in files:
                files[name], origin[name] = pin, group_path / name
        restored.append(dict(group_id=group_id, manifest_sha256=cap["manifest_sha256"], archive_sha256=cap["archive_sha256"], path=str(group_path)))
    require(len(members) == 160 and members == set(snapshot["state"]["fits"]) and len(semantics) == 1, "Full-study union differs")
    require(not set(files).intersection(dirs) and sum(p["bytes"] for p in files.values()) <= MAX_UNION_BYTES, "Union conflict/size bound; no truncation")
    destination.mkdir(parents=True, exist_ok=False)
    for name in sorted(dirs, key=lambda x: (x.count("/"), x)):
        (destination / name).mkdir(exist_ok=False)
    for name, pin in files.items():
        raw = bytes_at(origin[name], capsule.MAX_FILE_BYTES)
        require(dict(bytes=len(raw), sha256=sha(raw)) == pin, "Restored input changed before union")
        exclusive(destination / name, raw)
    actual_files, _, actual_dirs = capsule._inventory(destination)
    require(actual_files == files and set(actual_dirs) == dirs, "Materialized full-study bytes differ")
    return dict(schema="hcsn-full-study-lossless-union-v1", identity=config["identity"], registered_fit_count=160,
                successful_fit_count=sum(x["state"] == "COMPLETED" for x in snapshot["state"]["fits"].values()),
                terminal_counts=dict(Counter(x["state"] for x in snapshot["state"]["fits"].values())),
                files=files, directories=sorted(dirs), groups=restored, study_semantic_sha256=next(iter(semantics)),
                study_json_originals=study_origins, study_json_policy="Exact first group bytes used; every group original retained separately; only created_at may differ",
                failed_attempts_and_losing_lr_checkpoints_preserved=True, automatic_training_or_evaluation=False)


def explicit_stopped(returncode, state):
    return ((returncode == 0 and state.get("ActiveState") in {"inactive", "failed"})
            or (returncode in (0, 1) and state.get("LoadState") == "not-found"
                and state.get("ActiveState") == "inactive" and state.get("SubState") == "dead"))


def child_alive(child):
    require(type(child.get("pid")) is int and child["pid"] > 0
            and child.get("identity", {}).get("kind") == "proc_start_ticks", "Invalid child identity")
    try:
        fields = (Path("/proc") / str(child["pid"]) / "stat").read_text().rsplit(")", 1)[1].split()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return boot + ":" + fields[19] == child["identity"]["value"] and fields[0] not in {"Z", "X"}
    except FileNotFoundError:
        return False


def owner_observation(binding):
    expected, root = binding["owner"], safe(binding["owner"]["job_directory"])
    documents, pins = {}, {}
    for name in ("started.json", "owner-intent.json", "child.json"):
        raw = bytes_at(root / name)
        require(sha(raw) == expected["launch_file_sha256"][name], "Native launch metadata changed")
        documents[name], pins[name] = strict(raw), sha(raw)
    require(pins["started.json"] == pins["owner-intent.json"], "Owner intent/start bytes differ")
    start = documents["started.json"]
    require(start.get("job_id") == expected["job_id"] and start.get("launch_nonce") == expected["launch_nonce"]
            and start.get("invocation_id") == expected["invocation_id"], "Native owner launch identity differs")
    try:
        process = subprocess.run(["systemctl", "--user", "show", "hepta-runtime-job-" + expected["job_id"] + ".service",
                                  "--no-pager", "--property=LoadState,ActiveState,SubState,InvocationID,ExecMainStatus,Result"],
                                 capture_output=True, text=True, timeout=10)
        code, text, error = process.returncode, process.stdout, None
    except (OSError, subprocess.TimeoutExpired) as exception:
        code, text, error = None, "", type(exception).__name__
    state = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    require(state.get("InvocationID") in (None, "", expected["invocation_id"]), "Native unit was rebound")
    result = dict(systemd=state, status_returncode=code, status_error=error, launch_pins=pins,
                  child_alive=child_alive(documents["child.json"]), explicit_stopped=explicit_stopped(code, state),
                  state="RUNNING_OR_UNKNOWN", terminal=None)
    ep, wp = root / "exit.json", root / "exit.witness.json"
    if ep.exists() and wp.exists():
        eraw, wraw = bytes_at(ep), bytes_at(wp)
        terminal, witness = strict(eraw), strict(wraw)
        for value in (terminal, witness):
            require(value.get("job_id") == expected["job_id"] and value.get("launch_nonce") == expected["launch_nonce"]
                    and value.get("invocation_id", expected["invocation_id"]) == expected["invocation_id"]
                    and type(value.get("terminal_publication_protocol")) is int and value["terminal_publication_protocol"] == 1,
                    "Native terminal identity/protocol differs")
        require(witness.get("exit_sha256") == sha(eraw) and type(terminal.get("exit_code")) is int, "Unwitnessed native terminal")
        result.update(terminal=terminal, terminal_pins=dict(exit=sha(eraw), witness=sha(wraw)))
        result["state"] = "TERMINAL_VERIFIED" if result["explicit_stopped"] and not result["child_alive"] else "TERMINAL_DRAIN"
    return result


def expected_owner_launch(binding, config, owner):
    """Derive the executed owner command from actual pinned files, not a receipt label."""
    paths = {name: str(safe(binding[name])) for name in ("source_root", "control_root", "config_path")}
    require(all(binding[name] == value for name, value in paths.items()), "Launch paths must be exact absolute paths")
    relative = Path(config["plan_relative_path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe frozen plan path")
    paths["plan_path"] = str(safe(Path(paths["source_root"]) / relative))
    paths["owner_source_path"] = str(safe(Path(paths["control_root"]) / "native_owner.py"))
    expected_sha = config["control_pins"]["native_owner.py"]
    plan = read(paths["plan_path"], config["plan_sha256"])
    logical = owner.CONTROL_RELATIVE + "/native_owner.py"
    require(plan.get("status") == "FROZEN" and plan.get("source_pins", {}).get(logical) == expected_sha
            and sha(bytes_at(paths["owner_source_path"])) == expected_sha
            and sha(bytes_at(Path(paths["source_root"]) / logical)) == expected_sha,
            "Actual owner source differs from frozen plan/config pins")
    command = [config["provider"]["native_python"], "-B", paths["owner_source_path"],
               "--config", paths["config_path"], "--source-root", paths["source_root"],
               "--plan", paths["plan_path"], "--control-root", paths["control_root"],
               "--published-plan-commit", config["published_plan_commit"],
               "--published-plan-ref", config["published_plan_ref"]]
    return dict(paths, owner_source_sha256=expected_sha, owner_command=command)


def verify_launch_role(binding, config, owner):
    """Bridge actual h_start identity to the separately reviewed exact wrapper.

    Native started/child files have no argv. Therefore matching their opaque
    hashes is not sufficient: the actual h_start response, its request digest,
    exact -c script bytes and actual pre-exec admission receipt are all bound.
    The wrapper's exact source must be reviewed before its hash enters binding;
    an authenticated/one_owner boolean alone never proves this relation.
    """
    proof = binding["native_launch"]
    response = read(proof["receipt_path"], proof["receipt_sha256"])
    job, launch = response["job"], response["launch"]
    expected = binding["owner"]
    require(job.get("id") == expected["job_id"] and job.get("host") == binding["native_host"]
            and job.get("remote_job_dir") == expected["job_directory"]
            and job.get("unit") == "hepta-runtime-job-" + expected["job_id"], "Native start receipt is for another job")
    require(job.get("execution_mode") == "operator" and job.get("launch_state") == "launched"
            and job.get("launch_error") is None and launch.get("backend") == "systemd"
            and launch.get("ok") is True and launch.get("unit") == job["unit"], "Native start was not the bound systemd launch")
    require(job.get("request_digest") == proof["request_digest"]
            and job.get("idempotency_key") == proof["idempotency_key"], "Native request identity differs")
    arguments = job.get("args")
    require(job.get("executable") == proof["wrapper_executable"] and job.get("cwd") == binding["control_root"]
            and isinstance(arguments, list) and len(arguments) == 2 and arguments[0] == "-c"
            and isinstance(arguments[1], str), "Native executable/actual -c launch schema differs")
    require(sha(arguments[1].encode()) == proof["launch_script_sha256"]
            and sha(canonical([job["executable"], *arguments])) == proof["command_sha256"],
            "Actual launch command/script is not the separately reviewed bytes")
    admission = read(proof["admission_path"], proof["admission_sha256"])
    require(admission.get("schema") == "hcsn-colab-native-formal-owner-launch-admission-v3"
            and admission.get("status") == "native_admission_verified_before_owner_exec", "Actual pre-exec admission schema differs")
    require(admission.get("config_sha256") == binding["config_sha256"]
            and admission.get("config_canonical_sha256") == owner.digest(config), "Launched owner admitted another config")
    for key in ("plan_sha256", "published_plan_commit", "published_plan_ref", "publication_receipt", "control_pins"):
        require(admission.get(key) == config[key], "Launched owner admission differs: " + key)
    require(admission.get("owner_python") == config["provider"]["native_python"]
            and admission.get("provider_binding") == config["provider_binding"], "Actual owner interpreter/provider binding differs")
    expected_launch = expected_owner_launch(binding, config, owner)
    for key, value in expected_launch.items():
        require(admission.get(key) == value, "Actual owner command/source admission differs: " + key)
    require(admission.get("registered_fits") == 160 and admission.get("updates_per_fit") == 400
            and admission.get("fit_timeout_seconds") == 480 and admission.get("provider_limit_seconds") == 3000,
            "Launched owner admitted another fixed budget")
    return dict(receipt_sha256=proof["receipt_sha256"], request_digest=job["request_digest"],
                launch_script_sha256=proof["launch_script_sha256"], command_sha256=proof["command_sha256"],
                admission_sha256=proof["admission_sha256"], owner_source_sha256=expected_launch["owner_source_sha256"],
                owner_command_sha256=sha(canonical(expected_launch["owner_command"])))


def recheck_binding_inputs(binding, config, owner):
    require(read(binding["config_path"], binding["config_sha256"]) == config, "Bound owner config changed")
    source_root = Path(binding["source_root"])
    owner.validate_config(config, source_root, source_root / config["plan_relative_path"], binding["control_root"],
                          config["published_plan_commit"], config["published_plan_ref"])
    return verify_launch_role(binding, config, owner)


def same_stopped(before, after):
    return all(row["state"] == "TERMINAL_VERIFIED" and row["explicit_stopped"] and not row["child_alive"] for row in (before, after)) and all(before.get(k) == after.get(k) for k in ("launch_pins", "terminal_pins", "terminal"))


def analysis_result_gate(result, config, snapshot):
    require(result.get("schema") == "hcsn-mechanism-pilot-analysis-v1" and result.get("identity") == config["identity"]
            and result.get("registered_full_fit_count") == 160 and len(result.get("contrasts", [])) == 20, "Frozen analysis output identity/denominator differs")
    require(result.get("scientific_status") in {"EXPLORATORY_MATRIX_COMPLETE", "INCOMPLETE_OR_FAILED_MATRIX_RETAINED"}, "Unknown frozen analysis status")
    rows = result.get("registered_fit_terminal_status", [])
    require([row["fit"] for row in rows] == config["ordered_roster"]
            and {row["fit"]["fit_id"]: row["status"] for row in rows} == {i: value["state"] for i, value in snapshot["state"]["fits"].items()},
            "Analysis did not account for every original terminal")
    require(result.get("expansion_decision") == "HOLD" and result.get("complete_cost") is False
            and result.get("physical_energy_joules") is None and result.get("original_campaign_completion_credit") == 0
            and result.get("hepta_ndu_completion_credit") == 0, "Analysis scope/energy/admission drift")
    for row in result["contrasts"]:
        if not row.get("all_four_registered_seeds_present") or not row.get("inferential_eligible"):
            require(row.get("holm_adjusted_p_above_mud") == 1. and row.get("exploratory_effect_gate_pass") is False,
                    "Missing/ineligible contrast escaped the fixed family")


def run_analysis(config, source_root, bundle, study, output, environment):
    """One CPU-only frozen analysis process; no worker/fit/evaluation dispatch."""
    import numpy
    import scipy
    require(dict(python=sys.version.split()[0], numpy=numpy.__version__, scipy=scipy.__version__) == environment,
            "CPU analysis environment differs from the separately bound host capability")
    require("torch" not in sys.modules, "Analysis continuation unexpectedly imported Torch")
    started, usage = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", CUDA_VISIBLE_DEVICES="",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    env.pop("PYTHONPATH", None)
    args = [sys.executable, "-B", "-m", "qualification.hcsn_regenerative.mechanism_analysis", "--study", str(study),
            "--bundle", str(bundle), "--plan", str(source_root / config["plan_relative_path"]), "--output", str(output / "analysis.json")]
    exclusive(output / "analysis-started.json", dict(arguments=args, at=datetime.now(timezone.utc).isoformat(),
              environment=environment, timeout_seconds=600, automatic_retry=False, full_physical_energy_joules=None))
    timed_out = False
    with (output / "analysis.stdout.log").open("xb") as stdout, (output / "analysis.stderr.log").open("xb") as stderr:
        child = subprocess.Popen(args, cwd=source_root, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            child.wait(timeout=600)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = dict(returncode=child.returncode, timed_out=timed_out, wall_seconds=time.monotonic()-started,
                   child_user_cpu_seconds=after.ru_utime-usage.ru_utime, child_system_cpu_seconds=after.ru_stime-usage.ru_stime,
                   children_peak_rss_kib_since_continuation_start=after.ru_maxrss, full_physical_energy_joules=None,
                   provider_submissions=0, training_operations=0, episode_evaluation_operations=0,
                   environment=environment, automatic_retry=False)
    exclusive(output / "analysis-process-completion.json", receipt)
    require(child.returncode == 0 and not timed_out and (output / "analysis.json").is_file(), "Frozen CPU analysis failed; inputs retained, no retry")
    return read(output / "analysis.json"), receipt


def retain_native_history(config, snapshot, output):
    """Preserve raw failed/unknown calls as well as accepted provider receipts."""
    event_pins = {}
    for record in snapshot["records"]:
        raw = bytes_at(record["path"])
        require(sha(raw) == record["sha256"], "Native ledger changed before evidence retention")
        exclusive(output / "native-events" / Path(record["path"]).name, raw)
        event_pins[record["path"]] = dict(bytes=len(raw), sha256=sha(raw))
    adapter = Path(config["state_root"]) / "adapter-calls"
    calls, total, call_pins = sorted(adapter.glob("*.json")), 0, {}
    require(len(calls) <= 32768, "Adapter call bound exceeded; no truncated costs")
    for path in calls:
        raw = bytes_at(path)
        total += len(raw)
        require(total <= MAX_LEDGER_BYTES, "Adapter cost byte bound exceeded; no truncation")
        call_pins[str(path)] = dict(bytes=len(raw), sha256=sha(raw))
        exclusive(output / "native-adapter-calls" / path.name, raw)
    input_inventory, requests = {}, {}
    for record in snapshot["records"]:
        active = record["event"]["state"].get("active")
        if active is not None:
            requests[active["request_id"]] = active
    for request_id, active in requests.items():
        job_root = Path(config["state_root"]) / "provider-jobs" / request_id
        require(Path(active["source_path"]).parent == job_root, "Input provenance escaped its owner request")
        prepared = active["prepared_assets"]
        manifest_path = safe(prepared["manifest_path"])
        require(manifest_path.is_relative_to(safe(job_root)), "Prepared input manifest escaped its owner request")
        manifest_raw = bytes_at(manifest_path)
        require(sha(manifest_raw) == prepared["manifest_sha256"], "Prepared input manifest changed")
        exclusive(output / "native-input-manifests" / (request_id + ".json"), manifest_raw)
        item = dict(manifest_path=str(manifest_path), manifest_sha256=sha(manifest_raw),
                    manifest_bytes=len(manifest_raw), archive_sha256=prepared["archive_sha256"], upload_journal=None)
        journal = job_root / "asset-upload-journal.json"
        if journal.exists():
            raw = bytes_at(journal)
            exclusive(output / "native-upload-journals" / (request_id + ".json"), raw)
            item["upload_journal"] = dict(path=str(journal), bytes=len(raw), sha256=sha(raw))
        elif active.get("asset_upload_receipt") is not None:
            raise ClosureError("Verified asset transaction lacks its original upload journal")
        input_inventory[request_id] = item
    result = dict(native_ledger_event_inventory=event_pins, native_adapter_call_inventory=call_pins,
                  native_asset_input_and_upload_inventory=input_inventory,
                  scope="Every observed native call including failed/unknown submissions; no provider effect or cost inferred from exit zero",
                  full_physical_energy_joules=None, monetary_cost=None, complete_total_cost=False)
    exclusive(output / "native-history-inventory.json", result)
    return result


def finalize(binding, owner, capsule, config, plan, output, initial_owner):
    source_root, state_root = Path(binding["source_root"]), Path(config["state_root"])
    launch_role = recheck_binding_inputs(binding, config, owner)
    snapshot = ledger_snapshot(owner, config, state_root, binding.get("authorized_owner_recovery_event_sha256", []))
    require(initial_owner["state"] == "TERMINAL_VERIFIED" and initial_owner["terminal"]["exit_code"] == 0
            and not initial_owner["terminal"].get("timed_out") and not initial_owner["terminal"].get("cancelled"), "Successful stopped native owner required")
    handoff_path = state_root / "final-handoff.json"
    handoff = read(handoff_path)
    validate_closure(config, snapshot, handoff, handoff_path, source_root)
    chains, cost = capsule_chains(owner, capsule, config, snapshot)
    cost["native_history"] = retain_native_history(config, snapshot, output)
    exclusive(output / "actual-native-launch.json", bytes_at(binding["native_launch"]["receipt_path"]))
    exclusive(output / "actual-native-admission.json", bytes_at(binding["native_launch"]["admission_path"]))
    exclusive(output / "native-launch-role-binding.json", launch_role)
    metadata_path = Path(binding["bundle"]).with_suffix(".json")
    metadata = bytes_at(metadata_path)
    require(sha(metadata) == config["identity"]["bundle_metadata_sha256"], "Precompute metadata changed")
    exclusive(output / "bundle-metadata.json", metadata)
    cost["bundle_precompute_counting"] = dict(instances=1, metadata_sha256=sha(metadata), scope="One bundle construction; not multiplied by arm, fit, group, or provider job")
    union = assemble(owner, capsule, config, plan, snapshot, handoff, chains, output / "full-study", output / "groups")
    exclusive(output / "union.json", union)
    exclusive(output / "cost-provenance.json", cost)
    exclusive(output / "owner-handoff.json", bytes_at(handoff_path))
    owner.verify_local_pins(config, source_root, Path(binding["control_root"]))
    require(sha(bytes_at(__file__)) == binding["continuation_source_sha256"], "Continuation source changed")
    require(same_stopped(initial_owner, owner_observation(binding)), "Owner changed while reading its closed evidence")
    result, measurement = run_analysis(config, source_root, Path(binding["bundle"]), output / "full-study", output, binding["cpu_analysis_environment"])
    analysis_result_gate(result, config, snapshot)
    owner.verify_local_pins(config, source_root, Path(binding["control_root"]))
    require(recheck_binding_inputs(binding, config, owner) == launch_role, "Native launch/config/publication binding changed during analysis")
    current = ledger_snapshot(owner, config, state_root, binding.get("authorized_owner_recovery_event_sha256", []))
    require(current["head"] == snapshot["head"] and same_stopped(initial_owner, owner_observation(binding)), "Owner/ledger changed during analysis")
    require(sha(bytes_at(__file__)) == binding["continuation_source_sha256"], "Continuation source changed during analysis")
    actual_files, _, actual_dirs = capsule._inventory(output / "full-study")
    require(actual_files == union["files"] and actual_dirs == union["directories"], "Analysis changed its input study")
    return dict(status="FROZEN_ANALYSIS_COMPLETED", scientific_status=result["scientific_status"],
                analysis_sha256=sha(bytes_at(output / "analysis.json")), progress=progress(snapshot),
                analysis_cost=measurement, registered_fit_count=160, successful_fit_count=union["successful_fit_count"],
                expansion_decision="HOLD", full_physical_energy_joules=None, complete_cost=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    binding = read(args.binding, args.binding_sha256)
    require(binding.get("schema") == "hcsn-s81-colab-analysis-owner-binding-v3" and isinstance(binding.get("plan_sha256"), str) and len(binding["plan_sha256"]) == 64,
            "Explicit final native owner binding required")
    require(sha(bytes_at(__file__)) == binding["continuation_source_sha256"], "Continuation source differs from bound version")
    output = safe(args.output)
    require(str(output) == binding["output"] and not output.exists(), "Output is not the exclusive bound path")
    deadline = datetime.fromisoformat(binding["observer_deadline_utc"]).timestamp()
    began = datetime.fromisoformat(binding["binding_created_at_utc"]).timestamp()
    require(0 < deadline-began <= 72*3600 and began <= time.time() < deadline, "Finite original observation window missing/expired")
    config = read(binding["config_path"], binding["config_sha256"])
    require(config["control_pins"] == binding["control_pins"] and config["plan_sha256"] == binding["plan_sha256"], "Final owner config identity differs")
    owner, capsule = dependencies(binding["control_root"], config["control_pins"])
    source_root = Path(binding["source_root"])
    protected = [safe(source_root), safe(binding["control_root"]), safe(config["state_root"])]
    require(all(not output.is_relative_to(root) and not root.is_relative_to(output) for root in protected), "Analysis output overlaps frozen source or owner state")
    require(isinstance(binding.get("native_host"), str) and binding["owner"]["job_directory"] ==
            str(Path(binding["native_job_root"]) / binding["owner"]["job_id"]), "Native analysis/owner host or job-directory binding differs")
    plan = owner.validate_config(config, source_root, source_root / config["plan_relative_path"], binding["control_root"],
                                 config["published_plan_commit"], config["published_plan_ref"])
    verify_launch_role(binding, config, owner)
    require(sha(bytes_at(binding["bundle"])) == config["identity"]["bundle_sha256"]
            and sha(bytes_at(Path(binding["bundle"]).with_suffix(".json"))) == config["identity"]["bundle_metadata_sha256"], "Qualified bundle bytes differ")
    output.mkdir(parents=True, exist_ok=False)
    exclusive(output / "claim.json", dict(binding_sha256=args.binding_sha256, binding=binding, pid=os.getpid(),
              at=datetime.now(timezone.utc).isoformat(), uniqueness="Exclusive output path only; no training-owner lock or provider action"))
    started = time.monotonic()
    receipt = dict(status="BLOCKED", analysis_started=False, full_physical_energy_joules=None, original_campaign_completion_credit=0,
                   training_operations=0, episode_evaluation_operations=0, provider_submissions=0, observer_deadline_stops_training=False)
    try:
        count = 0
        while True:
            observation = owner_observation(binding)
            count += 1
            exclusive(output / "observations" / f"{count:06d}.json", dict(at=datetime.now(timezone.utc).isoformat(), **observation))
            if observation["state"] == "TERMINAL_VERIFIED":
                if observation["terminal"]["exit_code"] != 0 or observation["terminal"].get("cancelled") or observation["terminal"].get("timed_out"):
                    snapshot = ledger_snapshot(owner, config, config["state_root"], binding.get("authorized_owner_recovery_event_sha256", []))
                    retain_native_history(config, snapshot, output)
                    receipt.update(status="OWNER_FAILED_OR_TIMED_OUT_PARTIAL_RETAINED", progress=progress(snapshot),
                                   reason="No complete handoff is invented; no training/episode replay")
                    break
                receipt.update(finalize(binding, owner, capsule, config, plan, output, observation), analysis_started=True)
                break
            if not args.watch or time.time() >= deadline:
                snapshot = ledger_snapshot(owner, config, config["state_root"], binding.get("authorized_owner_recovery_event_sha256", []))
                retain_native_history(config, snapshot, output)
                receipt.update(status="OBSERVATION_ONLY_PARTIAL_HOLD", progress=progress(snapshot),
                               reason="Owner termination is not verified; observation ended without stopping or replaying it")
                break
            time.sleep(min(30., max(0., deadline-time.time())))
    except Exception as error:
        receipt.update(status="BLOCKED", error_type=type(error).__name__, reason=str(error),
                       analysis_started=(output / "analysis-started.json").exists())
    receipt.update(wall_seconds=time.monotonic()-started, finished_at=datetime.now(timezone.utc).isoformat(),
                   scientific_admission="HOLD", complete_total_cost=False, monetary_cost=None)
    exclusive(output / "continuation-terminal.json", receipt)
    print(json.dumps(receipt, sort_keys=True, allow_nan=False), flush=True)
    return 0 if receipt["status"] == "FROZEN_ANALYSIS_COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
