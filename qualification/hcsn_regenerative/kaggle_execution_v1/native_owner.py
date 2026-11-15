"""Draft unique native owner: fixed claims, verified whole capsules, no replay.

This control layer imports no training code. Root must pin all eight control
sources and the published plan before enabling this CLI. An unknown effect
halts the owner without cancelling, resubmitting, or declaring a fit unstarted.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time


STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-cpu-v1"
REF = "refs/heads/codex/hcsn-mechanisms-s81-cpu-v1-20261107"
TERMINAL = {"COMPLETED", "FAILED", "TIMEOUT"}
PROVIDER_TERMINAL = {"COMPLETE", "ERROR", "CANCEL_ACKNOWLEDGED"}
CONTROL_FILES = {"__init__.py", "native_owner.py", "cloud_batch.py", "capsule_contract.py", "finalize_mechanism.py", "test_kaggle_execution.py", "kaggle_provider.py", "test_kaggle_provider.py"}
CONTROL_RELATIVE = "qualification/hcsn_regenerative/kaggle_execution_v1"


class OwnerHalt(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise OwnerHalt(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(OwnerHalt("Nonfinite JSON")))
    try:
        canonical(value)  # Also reject exponent overflow, for example 1e999.
    except (ValueError, TypeError) as error:
        raise OwnerHalt("Nonfinite/invalid JSON") from error
    return value


def safe_path(path):
    path = Path(path).absolute()
    require(".." not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)), "Symlink/traversal in evidence path")
    return path


def version(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def file_bytes(path, limit=67108864):
    path = safe_path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= limit and before.st_nlink == 1, "Unsafe/oversized evidence file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(version(os.fstat(stream.fileno())) == version(before), "Evidence changed before read")
        data = stream.read(limit + 1)
    require(len(data) == before.st_size and version(path.lstat()) == version(before), "Evidence changed during read")
    return data


def read(path, expected=None):
    raw = file_bytes(path)
    require(expected is None or hashlib.sha256(raw).hexdigest() == expected, "Evidence SHA256 mismatch")
    return parse(raw)


def exclusive(path, value):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value if isinstance(value, bytes) else canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check_environment(expected, actual):
    for key, value in expected.items():
        if key in ("gpu_uuid_policy", "allowed_gpu_uuids"):
            continue
        if key == "gpu":
            require(all(actual.get("gpu", {}).get(k) == v for k, v in value.items()), "Execution GPU differs")
        else:
            require(actual.get(key) == value, "Execution environment differs: " + key)


def verify_local_pins(config, source_root, control_root):
    read(Path(source_root) / config["plan_relative_path"], config["plan_sha256"])
    for directory, pins in ((source_root, config["source_pins"]), (control_root, config["control_pins"])):
        for name, expected in pins.items():
            relative = Path(name)
            require(not relative.is_absolute() and ".." not in relative.parts and relative.as_posix() == name, "Unsafe source pin path")
            require(hashlib.sha256(file_bytes(Path(directory) / relative, 2 * 1024**2)).hexdigest() == expected, "Pinned source changed: " + name)


def load_control(name, root, expected):
    """Execute pinned source bytes directly, without trusting an old pyc cache."""
    path = Path(root) / (name + ".py")
    raw = file_bytes(path, 2 * 1024**2)
    require(hashlib.sha256(raw).hexdigest() == expected, "Control import source changed")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def validate_config(config, source_root, plan_path, control_root, commit, ref):
    require(config.get("schema") == "hcsn-kaggle-cpu-study-owner-config-v1" and config.get("formal_training_start_authorized") is True, "Formal training is not authorized")
    require(re.fullmatch(r"[0-9a-f]{40}", commit or "") and ref == REF, "Explicit published commit/ref required")
    require(config.get("published_plan_commit") == commit and config.get("published_plan_ref") == ref, "Publication arguments differ")
    plan_sha = config.get("plan_sha256")
    require(re.fullmatch(r"[0-9a-f]{64}", plan_sha or "") and Path(config["state_root"]).name == plan_sha, "Wrong global study owner root")
    require(Path(plan_path).absolute() == (Path(source_root) / config["plan_relative_path"]).absolute(), "Plan path is outside its pinned source location")
    plan = read(plan_path, plan_sha)
    require(plan.get("status") == "FROZEN" and plan.get("study_id") == STUDY_ID and plan.get("train_updates") == 400 and plan.get("max_fit_wall_seconds") == 480 and plan.get("state_count") == 81 and plan.get("expected_parameter_count") == 2890, "Frozen CPU scientific identity differs")
    proof = config.get("publication_receipt") or {}
    receipt = read(proof["receipt_path"], proof["receipt_sha256"])
    readback = read(proof["readback_path"], proof["readback_sha256"])
    require(receipt.get("status") == "published_and_verified" and receipt.get("repo") == "TrillionniumFoundation/hepta-private-ci" and receipt.get("branch") == ref.removeprefix("refs/heads/") and receipt.get("commit") == commit, "Native publication receipt is not the declared commit")
    require(readback.get("commit") == commit and readback["files"][config["plan_relative_path"]]["sha256"] == plan_sha, "Published plan bytes not verified")
    pins = config["source_pins"]
    require(pins == config["identity"]["source_pins"] and pins == plan["source_pins"], "Frozen source maps differ")
    require(all(readback["files"].get(name, {}).get("sha256") == sha for name, sha in pins.items()), "Published research-source bytes not all verified")
    controls = config.get("control_pins", {})
    require(set(controls) == CONTROL_FILES, "Complete pre-fit control source pins required")
    verify_local_pins(config, source_root, control_root)
    rows, groups = config["ordered_roster"], config["groups"]
    require(len(rows) == 160 and len({x["fit_id"] for x in rows}) == 160 and [x["index"] for x in rows] == list(range(160)), "Wrong exact 160-fit roster")
    require(len(groups) == 8 and [x for g in groups for x in g["fit_ids"]] == [r["fit_id"] for r in rows] and all(len(g["fit_ids"]) == 20 for g in groups), "Wrong 8 x 20 statistical groups")
    roster_sha = hashlib.sha256(canonical(rows)[:-1]).hexdigest()
    expected_identity = dict(study_id=plan["study_id"], plan_sha256=plan_sha, bundle_sha256=plan["bundle_sha256"],
        bundle_metadata_sha256=plan["bundle_metadata_sha256"], source_pins=pins, ordered_fit_roster_sha256=roster_sha,
        state_count=plan["state_count"], expected_parameter_count=plan["expected_parameter_count"], registered_fit_count=160,
        registered_training_updates=160 * plan["train_updates"], original_campaign_completion_credit=0)
    require(roster_sha == plan["ordered_fit_roster_sha256"] and config["identity"] == expected_identity, "Native roster/identity is not the frozen research identity")
    require(all(g["fit_ids"] == [r["fit_id"] for r in rows if r["group_id"] == g["group_id"]] for g in groups) and len({g["group_id"] for g in groups}) == 8, "Statistical group identities differ")
    require(config["runtime_policy"] == plan["runtime_feasibility_policy"] and config["execution_environment"] == plan["execution_environment"], "Frozen policy/environment differs")
    provider = config["provider"]
    policy = {k: provider[k] for k in ("account_selector", "expected_username", "expected_user_id", "accelerator", "internet", "is_private", "mode", "timeout_seconds")}
    require(policy["accelerator"] == "cpu" and policy["timeout_seconds"] == 3000 and policy["internet"] is False and policy["is_private"] is True and policy["mode"] == "batch", "CPU provider policy differs")
    require(plan["execution_environment"]["device"] == "cpu" and plan["execution_environment"]["gpu_uuid_policy"] == "not_applicable" and plan["execution_environment"]["cpu_threads"] == 1, "CPU environment policy differs")
    migration = plan["resource_migration"]
    require(hashlib.sha256(canonical(policy)[:-1]).hexdigest() == migration["cpu_provider_commitment"], "Private CPU provider identity is not bound to published plan")
    qualified = config["qualified_input"]
    require(hashlib.sha256(canonical(qualified)[:-1]).hexdigest() == migration["qualified_input_commitment"], "Qualified input producer/version/archive differs")
    require(qualified["notebook_ref"].split("/")[0] == policy["expected_username"] and qualified["notebook_version"] == 1 and type(qualified["kernel_id"]) is int and qualified["kernel_id"] > 0, "Qualified input ownership differs")
    require(qualified["archive_name"] == "suite-artifacts.zip" and qualified["bundle_member"] == "inputs/prior-qualified-bundle/operators-s81.npz" and qualified["metadata_member"] == "inputs/prior-qualified-bundle/operators-s81.json", "Qualified fixed input member differs")
    require(Path(provider["artifact_root"]).is_absolute() and Path(provider["native_python"]).is_absolute(), "Private transport paths must be absolute")
    for name, value in controls.items():
        require(pins.get(CONTROL_RELATIVE + "/" + name) == value, "Control pin absent from frozen source map")
    transport = load_control("kaggle_provider", control_root, controls["kaggle_provider.py"])
    transport.validate_installed(provider)
    return plan


def initial_state(config):
    return dict(config_sha256=digest(config), fits={r["fit_id"]: dict(state="UNSTARTED", ever_claimed=False) for r in config["ordered_roster"]},
                groups={g["group_id"]: dict(fit_ids=g["fit_ids"], phase="fit", prior_capsule=None, ever_claimed_fit_ids=[], ever_claimed_evaluation_ids=[], evaluations={}, selected_ids=[], verified_selection_lock_sha256=None) for g in config["groups"]},
                active=None, batch_count=0, halted=None, execution_finished=False)


def validate_state_transition(before, after, kind, evidence=None):
    require(before["config_sha256"] == after["config_sha256"] and before["fits"].keys() == after["fits"].keys() and before["groups"].keys() == after["groups"].keys(), "Global roster/config changed")
    for fit_id, old in before["fits"].items():
        new = after["fits"][fit_id]
        require(new["state"] in TERMINAL | {"UNKNOWN", "UNSTARTED", "RESERVED", "CLAIMED_PENDING"} and new["ever_claimed"] is (new["state"] not in {"UNSTARTED", "RESERVED"}), "Invalid native fit state/claim flag")
        require(not old["ever_claimed"] or new["ever_claimed"], "A native ever-claimed fit disappeared")
        if old["state"] in TERMINAL | {"UNKNOWN"}:
            require(new == old, "A terminal/unknown fit was changed or replayed")
        if old["state"] == "RESERVED" and new["state"] == "UNSTARTED":
            require(kind == "CAPSULE_ACCEPTED" and not new["ever_claimed"] and all((evidence or {}).get(k) is True for k in ("provider_terminal_verified", "full_capsule_verified", "final_state_attested")), "Reservation released without verified terminal capsule")
    for name, old in before["groups"].items():
        new = after["groups"][name]
        require(new["fit_ids"] == old["fit_ids"] and {"fit": 0, "selection": 1, "evaluation": 2, "done": 3}[new["phase"]] >= {"fit": 0, "selection": 1, "evaluation": 2, "done": 3}[old["phase"]], "Group identity/phase regressed")
        for key in ("ever_claimed_fit_ids", "ever_claimed_evaluation_ids"):
            require(set(old[key]) <= set(new[key]) <= set(new["fit_ids"]) and len(new[key]) == len(set(new[key])), "Native claim history contracted/escaped group")
        for fit_id, value in old["evaluations"].items():
            require(fit_id in new["evaluations"] and (value["state"] not in TERMINAL | {"UNKNOWN"} or new["evaluations"][fit_id] == value), "Evaluation disappeared or was replayed")
        require(set(new["evaluations"]) == set(new["ever_claimed_evaluation_ids"]), "Evaluation claim ledger is incomplete")
        if old["verified_selection_lock_sha256"] is not None:
            require(new["verified_selection_lock_sha256"] == old["verified_selection_lock_sha256"] and new["selected_ids"] == old["selected_ids"], "Verified selection was changed")
    if before["active"] and after["active"]:
        require(all(after["active"].get(k) == v for k, v in before["active"].items() if k not in ("producer", "terminal_observation")), "Active dispatch identity changed")
        for key in ("producer", "terminal_observation"):
            if before["active"].get(key) is not None:
                require(after["active"].get(key) == before["active"][key], "Provider producer/terminal identity changed")
    claims = {i for g in after["groups"].values() for i in g["ever_claimed_fit_ids"]}
    require(claims == {i for i, value in after["fits"].items() if value["ever_claimed"]}, "Global and group claim ledgers differ")


class Ledger:
    def __init__(self, root, config):
        self.root = safe_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        require(not self.root.is_symlink(), "Owner root is a symlink")
        self.lock = os.fdopen(os.open(self.root / "owner.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w")
        lock_stat = os.fstat(self.lock.fileno())
        require(stat.S_ISREG(lock_stat.st_mode) and lock_stat.st_nlink == 1, "Unsafe owner lock")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.lock.close()
            raise
        self.state, self.number, self.previous = initial_state(config), 0, None
        for path in sorted((self.root / "events").glob("*.json")):
            raw = file_bytes(path)
            event = parse(raw)
            require(event["sequence"] == self.number + 1 and event["previous_sha256"] == self.previous and path.name == f"{self.number + 1:06d}.json", "Broken immutable native ledger chain")
            validate_state_transition(self.state, event["state"], event["kind"], event.get("evidence"))
            self.state, self.number, self.previous = event["state"], event["sequence"], hashlib.sha256(raw).hexdigest()
        self.config = config

    def append(self, kind, state, evidence=None):
        validate_state_transition(self.state, state, kind, evidence)
        event = dict(sequence=self.number + 1, previous_sha256=self.previous, kind=kind, at_utc=datetime.now(timezone.utc).isoformat(), evidence=evidence, state=state)
        raw = canonical(event)
        exclusive(self.root / "events" / f"{self.number + 1:06d}.json", raw)
        self.state, self.number, self.previous = parse(raw)["state"], self.number + 1, hashlib.sha256(raw).hexdigest()

    def copy(self):
        return parse(canonical(self.state))



def validate_remote(remote, active, config):
    require(remote.get("schema") == "hepta-kaggle-job-v1" and remote.get("request_id") == active["request_id"] and remote.get("identity_verified") is True and remote.get("remote_effect_unknown") is False, "Provider identity/effect is unknown")
    require(remote.get("account", {}).get("username") == config["provider"]["expected_username"] and remote.get("account", {}).get("authenticated") is True and remote.get("account", {}).get("user_id") == config["provider"]["expected_user_id"] and type(remote.get("notebook_version")) is int and remote["notebook_version"] == 1, "Provider account/version differs")
    require(re.fullmatch(re.escape(config["provider"]["expected_username"]) + r"/[a-z0-9-]+", remote.get("notebook_ref", "")) and type(remote.get("kernel_id")) is int and remote["kernel_id"] > 0 and re.fullmatch(r"[0-9a-f]{64}", remote.get("input_digest", "")), "Missing authoritative producer identity")
    intent = remote.get("intent", {})
    require(intent.get("source_sha256") == active["code_sha256"] and intent.get("timeout_seconds") == 3000 and intent.get("accelerator") == "cpu" and intent.get("is_private") is True and intent.get("internet") is False, "Provider execution intent differs")
    require(intent.get("kernel_sources") == active["kernel_sources"], "Provider input kernel list differs")
    require(remote.get("remote_submission_state") == "ACKNOWLEDGED" and remote.get("submission_state") == "ACCEPTED", "Submission is not authoritatively acknowledged")
    producer = {key: remote[key] for key in ("request_id", "notebook_ref", "notebook_version", "kernel_id", "input_digest")}
    require(active.get("producer") in (None, producer), "Authoritative producer changed during observation")
    if active.get("terminal_observation") is not None:
        require(remote.get("remote_state") == active["terminal_observation"]["remote_state"], "Authoritative provider terminal regressed/changed")
    return producer


def verified_artifacts(result, remote, active):
    require(result.get("remote_manifest_verified") is True and result.get("remote_manifest_name") == "artifact-manifest.json" and result.get("verification_policy") == "manifest-and-http-v1", "Provider artifact manifest not verified")
    require(all(result.get(k) == remote.get(k) for k in ("request_id", "notebook_ref", "notebook_version", "input_digest")), "Artifact producer differs")
    root, records = Path(result["directory"]), result["files"]
    names = {x["path"] for x in records}
    require({"artifact-manifest.json", "execution.json", "capsule-manifest.json", "study-capsule.tar.gz"} <= names, "Required full capsule artifacts missing")
    require(root == Path(active["artifact_root"]) / active["request_id"] / "artifacts" / "v1" and len(names) == len(records) <= 4096 and sum(x["bytes"] for x in records) <= 67108864, "Artifact listing duplicates/invalid root/oversize")
    for row in records:
        name = Path(row["path"])
        require(not name.is_absolute() and ".." not in name.parts and name.as_posix() == row["path"], "Artifact path is unsafe")
        raw = file_bytes(root / name)
        require(len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"] and row.get("http_content_length_verified") is True, "Downloaded artifact bytes differ")
    manifest = read(root / "artifact-manifest.json")
    require(manifest.get("schema") == "hepta-artifact-manifest-v1" and manifest.get("request_id") == active["request_id"], "Artifact manifest identity differs")
    expected = {x["path"]: dict(bytes=x["bytes"], sha256=x["sha256"]) for x in records if x["path"] != "artifact-manifest.json"}
    require(len(manifest["files"]) == len(expected) and {x["path"]: dict(bytes=x["bytes"], sha256=x["sha256"]) for x in manifest["files"]} == expected, "Actual manifest inventory differs from downloaded bytes")
    return root


def verify_selection(study, group, plan, config):
    """Independent stdlib reproduction of the frozen validation-only selection."""
    block = study / "blocks" / group["group_id"]
    lock, receipt = read(block / "selection-lock.json"), read(block / "selection-receipt.json")
    lock_sha = hashlib.sha256(file_bytes(block / "selection-lock.json")).hexdigest()
    require(receipt.get("identity") == config["identity"] and receipt.get("group_id") == group["group_id"] and receipt.get("phase") == "selection" and receipt.get("selection_lock_sha256") == lock_sha, "Original selection receipt/lock binding differs")
    fits = [r for r in config["ordered_roster"] if r["fit_id"] in group["fit_ids"]]
    terminals = {r["fit_id"]: read(study / "attempts" / r["fit_id"] / "terminal.json") for r in fits}
    require(all(t.get("status") in TERMINAL for t in terminals.values()), "Selection lacks twenty non-UNKNOWN terminals")
    for field, name in (("fit_terminal_file_sha256", "terminal.json"), ("fit_process_completion_file_sha256", "process-completion.json")):
        require(lock.get(field) == {r["fit_id"]: hashlib.sha256(file_bytes(study / "attempts" / r["fit_id"] / name)).hexdigest() for r in fits}, "Selection training-evidence file hash differs")
    selected, missing = {}, {}
    for arm in plan["arms"]:
        pair = sorted((r for r in fits if r["arm"] == arm), key=lambda r: r["lr_index"])
        valid = [r for r in pair if terminals[r["fit_id"]].get("status") == "COMPLETED" and terminals[r["fit_id"]].get("optimizer_updates_completed") == plan["train_updates"] and (terminals[r["fit_id"]].get("validation") or {}).get("count") == plan["validation_count"] and math.isfinite(terminals[r["fit_id"]]["validation"].get("mse", math.nan))]
        if len(pair) != len(plan["learning_rates"]) or len(valid) != len(pair):
            missing[arm] = [dict(fit_id=r["fit_id"], status=terminals[r["fit_id"]]["status"]) for r in pair]
            continue
        best = min(valid, key=lambda r: (terminals[r["fit_id"]]["validation"]["mse"], r["lr_index"]))
        terminal = terminals[best["fit_id"]]
        selected[arm] = dict(fit_id=best["fit_id"], learning_rate=best["learning_rate"], validation_mse=terminal["validation"]["mse"], checkpoint_sha256=terminal["checkpoint_sha256"], terminal_sha256=hashlib.sha256(canonical(terminal)[:-1]).hexdigest())
    others = [a for a in plan["arms"] if a != "regenerative_dual" and a in selected]
    best_other = min(others, key=lambda a: (selected[a]["validation_mse"], plan["arms"].index(a))) if others else None
    complete = not missing and len(selected) == len(plan["arms"])
    expected = dict(schema="hcsn-mechanism-selection-lock-v1", identity=config["identity"], group_id=group["group_id"], task=fits[0]["task"], training_seed=fits[0]["training_seed"], selected=selected, incomplete_tuning_pairs=missing, strongest_registered_comparator=best_other if complete else None, best_available_comparator=best_other, strongest_full_registered_set_eligible=complete, all_registered_arms_selected=complete, selection_basis="validation MSE only; ties: registered arm order, then LR order", episode_seeds=plan["test_episode_seeds"], test_has_started=False)
    require(all(lock.get(k) == v for k, v in expected.items()), "Selection choices differ from frozen validation evidence")
    require(receipt.get("selected_fit_ids") == [v["fit_id"] for v in selected.values()] and receipt.get("all_registered_arms_selected") == complete and receipt.get("strongest_full_registered_set_eligible") == complete, "Selection receipt choices differ")
    # Dispatch uses full roster order; the selection receipt uses registered arm order.
    return [r["fit_id"] for r in fits if r["fit_id"] in {v["fit_id"] for v in selected.values()}], lock_sha


def inspect_claims(study, manifest, config, phase, selected_ids, selection_sha=None):
    fits = {row["fit_id"]: row for row in config["ordered_roster"]}
    outcomes, evaluations = {}, {}
    for category, ids, output, expected_phase in (("attempts", manifest["claimed_fit_ids"], outcomes, "fit"), ("evaluations", manifest["claimed_evaluation_ids"], evaluations, "selected_test")):
        for fit_id in ids:
            path = study / category / fit_id
            terminal, completion = path / "terminal.json", path / "process-completion.json"
            if not terminal.exists() or not completion.exists():
                output[fit_id] = dict(state="UNKNOWN", ever_claimed=True, reason="Claimed without complete stopped-worker evidence")
                continue
            t, stop = read(terminal), read(completion)
            require(t.get("identity") == config["identity"] and t.get("fit") == fits[fit_id] and t.get("phase") == expected_phase, "Claimed operation identity differs")
            require(type(stop.get("returncode")) is int and type(stop.get("timed_out")) is bool, "Worker stopped status missing")
            status = t.get("status")
            require(status in TERMINAL | {"UNKNOWN"}, "Unrecognized fit/evaluation outcome")
            if t.get("environment") is not None:
                check_environment(config["execution_environment"], t["environment"])
            if status in {"COMPLETED", "FAILED"}:
                require(t.get("frozen_environment_check", {}).get("matched") is True, "Claim did not establish the frozen execution environment")
            error = t.get("error") or {}
            require(not any(word in str(error.get("message", "")).lower() for word in ("environment", "gpu mismatch", "source drift", "source pin", "identity", "checkpoint", "selection", "bundle", "frozen", "plan mismatch", "roster")), "Integrity failure requires owner halt, not an ordinary training failure")
            if status == "FAILED":
                require(stop["returncode"] == 2 and not stop["timed_out"], "Failed outcome lacks a matching stopped worker")
            if status == "TIMEOUT":
                require(stop["timed_out"] or (stop["returncode"] == 2 and error.get("type") == "TimeoutError" and t.get("frozen_environment_check", {}).get("matched") is True), "Timeout lacks a stopped-worker timeout receipt")
            if status == "COMPLETED":
                require(stop["returncode"] == 0 and not stop["timed_out"] and t.get("source_and_input_pins_unchanged_at_completion") is True and t.get("frozen_environment_check", {}).get("matched") is True, "Completed operation lacks execution proof")
                if category == "attempts":
                    require(t.get("optimizer_updates_completed") == 400 and t.get("training_examples_completed") == 25600, "Completed fit has incomplete fixed budget")
                    require((t.get("validation") or {}).get("count") == 512 and math.isfinite(t["validation"].get("mse", math.nan)), "Completed fit lacks finite complete validation")
                    require(manifest["files"][f"attempts/{fit_id}/checkpoint.pt"]["sha256"] == t.get("checkpoint_sha256"), "Completed checkpoint binding differs")
                else:
                    require(fit_id in selected_ids and t.get("selection_lock_sha256") == selection_sha, "Evaluation was not selected under the verified lock")
                    require([r["episode_seed"] for r in t.get("test", [])] == [4703, 5801] and all(r["count"] == 1024 for r in t["test"]) and t.get("independent_training_replicates_represented") == 1 and t.get("evaluation_episode_seeds_are_training_replicates") is False, "Evaluation episode/training-seed accounting differs")
            count = t.get("optimizer_updates_completed")
            require(count is None or (type(count) is int and 0 <= count <= 400), "Invalid actual optimizer update counter")
            output[fit_id] = dict(state=status, ever_claimed=True, terminal_sha256=hashlib.sha256(file_bytes(terminal)).hexdigest(), process_completion_sha256=hashlib.sha256(file_bytes(completion)).hexdigest(), optimizer_updates_completed=count, counters_are_lower_bounds=t.get("counters_are_lower_bounds", False))
    return outcomes, evaluations


class Owner:
    def __init__(self, config, plan, source_root, control_root, ledger, builder, adapter=None):
        self.config, self.plan, self.source_root, self.control_root = config, plan, Path(source_root), Path(control_root)
        self.ledger, self.builder = ledger, builder
        self.adapter = adapter or load_control("kaggle_provider", self.control_root, config["control_pins"]["kaggle_provider.py"]).Adapter(config, ledger.root)

    def reserve(self, group):
        require(self.config.get("formal_training_start_authorized") is True, "Formal training is not authorized")
        verify_local_pins(self.config, self.source_root, self.control_root)
        s = self.ledger.copy()
        require(s["active"] is None and s["halted"] is None and s["batch_count"] < 248, "Existing/unknown job or fixed job-count bound")
        g, phase = s["groups"][group["group_id"]], s["groups"][group["group_id"]]["phase"]
        planned = [i for i in group["fit_ids"] if s["fits"][i]["state"] == "UNSTARTED"] if phase == "fit" else []
        planned_eval = [i for i in g["selected_ids"] if i not in g["ever_claimed_evaluation_ids"]] if phase == "evaluation" else []
        request = f"hcsn-s81-{self.config['plan_sha256'][:12]}-g{self.config['groups'].index(group):02d}-{phase}-b{s['batch_count']:03d}"
        require(phase == "selection" or planned or planned_eval, "No unclaimed registered operation remains in this phase")
        batch = dict(request_id=request, group_id=group["group_id"], phase=phase, planned_fit_ids=planned, planned_evaluation_ids=planned_eval,
                     formal_training_start_authorized=self.config["formal_training_start_authorized"], expected_group_fit_ids=group["fit_ids"],
                     plan_relative_path=self.config["plan_relative_path"], admission_epoch_unix=time.time(), verified_selection_lock_sha256=g["verified_selection_lock_sha256"],
                     prior_capsule=g["prior_capsule"], ever_claimed_fit_ids=g["ever_claimed_fit_ids"], ever_claimed_evaluation_ids=g["ever_claimed_evaluation_ids"],
                     artifact_root=self.config["provider"]["artifact_root"], identity=self.config["identity"], plan_sha256=self.config["plan_sha256"], source_pins=self.config["source_pins"], control_pins=self.config["control_pins"],
                     published_plan_commit=self.config["published_plan_commit"], published_plan_ref=REF, qualified_input=self.config["qualified_input"],
                     submission_not_before_utc=datetime.now(timezone.utc).isoformat())
        payload = self.builder(batch, self.source_root, self.source_root / self.config["plan_relative_path"], self.control_root)
        code = payload["source_text"].encode()
        sources = [self.config["qualified_input"]["notebook_ref"]] + ([g["prior_capsule"]["producer_ref"]] if g["prior_capsule"] else [])
        require(payload["request_id"] == request and payload["code_sha256"] == hashlib.sha256(code).hexdigest() and payload["code_bytes"] == len(code) <= 2 * 1024**2 and payload["kernel_sources"] == sources, "Cloud payload identity/size/input differs")
        directory = self.ledger.root / "provider-jobs" / request
        exclusive(directory / "source.py", code)
        exclusive(directory / "batch-config.json", batch)
        active = dict(batch, code_sha256=payload["code_sha256"], kernel_sources=sources, source_path=str(directory / "source.py"), reserved_unix=time.time(), producer=None, terminal_observation=None)
        for fit_id in planned:
            require(not s["fits"][fit_id]["ever_claimed"], "Cannot replay a claimed fit")
            s["fits"][fit_id] = dict(state="RESERVED", ever_claimed=False, request_id=request)
        s["active"], s["batch_count"] = active, s["batch_count"] + 1
        self.ledger.append("RESERVED_BEFORE_SUBMISSION", s, dict(request_id=request, code_sha256=payload["code_sha256"]))
        args = ["--request-id", request, "--source", active["source_path"], "--timeout", "3000", "--accelerator", "cpu"]
        for ref in sources:
            args += ["--kernel-source", ref]
        return self.adapter.call("submit", args, 180)

    def accept(self, remote, artifacts):
        from capsule_contract import restore_capsule, validate_transition
        verify_local_pins(self.config, self.source_root, self.control_root)
        s = self.ledger.copy()
        active, group_id = s["active"], s["active"]["group_id"]
        validate_remote(remote, active, self.config)
        require(active.get("producer") is not None and active.get("terminal_observation") is not None and remote.get("remote_state") in PROVIDER_TERMINAL, "Complete native producer/terminal binding missing")
        g = s["groups"][group_id]
        root = verified_artifacts(artifacts, remote, active)
        execution = read(root / "execution.json")
        require(execution.get("schema") == "hcsn-mechanism-provider-batch-v1", "Unsupported batch receipt")
        for key in ("request_id", "group_id", "phase", "identity", "source_pins", "control_pins", "plan_sha256", "published_plan_commit", "published_plan_ref", "planned_fit_ids", "planned_evaluation_ids"):
            require(execution.get(key) == active[key], "Batch receipt differs: " + key)
        require(execution.get("qualified_input") == active["qualified_input"] and execution.get("prior_capsule") == active["prior_capsule"], "Input producers differ from the native dispatch")
        cap = execution["capsule"]
        require(cap["archive_name"] == "study-capsule.tar.gz" and cap["manifest_name"] == "capsule-manifest.json", "Capsule artifact names differ")
        manifest = read(root / cap["manifest_name"], cap["manifest_sha256"])
        require(manifest["archive"] == dict(bytes=cap["archive_bytes"], sha256=cap["archive_sha256"]), "Capsule receipt/hash differs")
        prior = read(g["prior_capsule"]["native_manifest_path"], g["prior_capsule"]["manifest_sha256"]) if g["prior_capsule"] else None
        validate_transition(prior, manifest, g["ever_claimed_fit_ids"], g["ever_claimed_evaluation_ids"])
        group = next(x for x in self.config["groups"] if x["group_id"] == group_id)
        restored = self.ledger.root / "verified-capsules" / active["request_id"] / str(time.time_ns())
        restored.parent.mkdir(parents=True, exist_ok=True)
        restore_capsule(root / cap["archive_name"], manifest, restored, self.config["identity"], group_id, group["fit_ids"], g["ever_claimed_fit_ids"], g["ever_claimed_evaluation_ids"])
        fresh_fit = set(manifest["claimed_fit_ids"]) - set(active["ever_claimed_fit_ids"])
        fresh_eval = set(manifest["claimed_evaluation_ids"]) - set(active["ever_claimed_evaluation_ids"])
        require(fresh_fit <= set(active["planned_fit_ids"]) and fresh_eval <= set(active["planned_evaluation_ids"]), "Unregistered operation claimed by provider")
        for fit_id in fresh_fit:
            if not s["fits"][fit_id]["ever_claimed"]:
                s["fits"][fit_id] = dict(state="CLAIMED_PENDING", ever_claimed=True, request_id=active["request_id"])
        for fit_id in fresh_eval:
            g["evaluations"].setdefault(fit_id, dict(state="CLAIMED_PENDING", ever_claimed=True, request_id=active["request_id"]))
        g["ever_claimed_fit_ids"], g["ever_claimed_evaluation_ids"] = manifest["claimed_fit_ids"], manifest["claimed_evaluation_ids"]
        self.ledger.append("CLAIMS_OBSERVED", s, dict(manifest_sha256=cap["manifest_sha256"], producer=active["producer"], restored_path=str(restored), execution_path=str(root / "execution.json")))
        # This append precedes all terminal parsing and guard checks. A malformed
        # terminal can never erase the already authenticated physical claim.
        outcomes, evaluations = inspect_claims(restored, manifest, self.config, active["phase"], g["selected_ids"], g["verified_selection_lock_sha256"])
        s = self.ledger.copy()
        s["fits"].update(outcomes)
        s["groups"][group_id]["evaluations"] = evaluations
        self.ledger.append("OUTCOMES_OBSERVED", s)
        require(execution.get("status") == "EXPORTED" and execution.get("halt_owner") is False and remote["remote_state"] == "COMPLETE", "Provider did not export an accepted bounded batch")
        require(all(execution.get(k) is True for k in ("source_unchanged", "environment_verified", "worker_children_stopped", "final_state_attested", "capsule_verified")), "End-of-job evidence incomplete")
        check_environment(self.config["execution_environment"], execution["observed_environment"]["environment"])
        require(execution["observed_environment"].get("check", {}).get("matched") is True, "Global environment preflight did not match")
        require(all(x["state"] in TERMINAL for x in list(outcomes.values()) + list(evaluations.values())), "Unknown claimed operation; never replay")
        require(active["phase"] == "selection" or fresh_fit or fresh_eval, "No progress; do not allocate a replacement provider job")
        s = self.ledger.copy()
        g = s["groups"][group_id]
        for planned_name, claimed_name in (("fit", "claimed_fit_ids"), ("evaluation", "claimed_evaluation_ids")):
            require(execution.get("unclaimed_remaining_planned_" + planned_name + "_ids") == [i for i in active["planned_" + planned_name + "_ids"] if i not in manifest[claimed_name]], "Final unclaimed reservation evidence differs")
        for fit_id in active["planned_fit_ids"]:
            if fit_id not in manifest["claimed_fit_ids"]:
                require(not s["fits"][fit_id]["ever_claimed"], "Claim omission cannot release reservation")
                s["fits"][fit_id] = dict(state="UNSTARTED", ever_claimed=False)
        g["prior_capsule"] = dict(producer_ref=remote["notebook_ref"], version=1, kernel_id=remote["kernel_id"], input_digest=remote["input_digest"], archive_sha256=cap["archive_sha256"], archive_bytes=cap["archive_bytes"], manifest_sha256=cap["manifest_sha256"], native_manifest_path=str(root / cap["manifest_name"]), native_archive_path=str(root / cap["archive_name"]), native_restored_path=str(restored), request_id=active["request_id"], execution_path=str(root / "execution.json"), execution_sha256=hashlib.sha256(file_bytes(root / "execution.json")).hexdigest())
        if active["phase"] == "fit" and all(s["fits"][i]["state"] in TERMINAL for i in group["fit_ids"]):
            g["phase"] = "selection"
        elif active["phase"] == "selection":
            g["selected_ids"], g["verified_selection_lock_sha256"] = verify_selection(restored, group, self.plan, self.config)
            g["phase"] = "evaluation" if g["selected_ids"] else "done"
        elif active["phase"] == "evaluation" and set(g["selected_ids"]) <= set(evaluations):
            g["phase"] = "done"
        s["active"] = None
        self.ledger.append("CAPSULE_ACCEPTED", s, dict(provider_terminal_verified=True, full_capsule_verified=True, final_state_attested=True, producer=remote, artifact_verification=artifacts, execution_costs=execution.get("costs"), full_physical_energy_joules=None, nested_wall_not_added=True))

    def final_handoff(self):
        verify_local_pins(self.config, self.source_root, self.control_root)
        s, capsules, members, semantics = self.ledger.state, [], set(), set()
        require(s["active"] is None and all(v["state"] in TERMINAL for v in s["fits"].values()), "Final union requires all 160 non-UNKNOWN terminals")
        for group in self.config["groups"]:
            g = s["groups"][group["group_id"]]
            require(g["phase"] == "done" and set(g["ever_claimed_fit_ids"]) == set(group["fit_ids"]) and set(g["selected_ids"]) == set(g["evaluations"]) and all(v["state"] in TERMINAL for v in g["evaluations"].values()), "Group selection/evaluation closure missing")
            cap = g["prior_capsule"]
            manifest = read(cap["native_manifest_path"], cap["manifest_sha256"])
            require(manifest["identity"] == self.config["identity"] and manifest["group_id"] == group["group_id"] and manifest["expected_group_fit_ids"] == group["fit_ids"], "Final capsule identity differs")
            archive = file_bytes(cap["native_archive_path"])
            require(len(archive) == cap["archive_bytes"] and hashlib.sha256(archive).hexdigest() == cap["archive_sha256"] and not members.intersection(manifest["claimed_fit_ids"]), "Final capsule changed or groups overlap")
            for name, pin in manifest["files"].items():
                raw = file_bytes(Path(cap["native_restored_path"]) / name)
                require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"], "Final restored history changed")
            read(cap["execution_path"], cap["execution_sha256"])
            selected, lock_sha = verify_selection(Path(cap["native_restored_path"]), group, self.plan, self.config)
            require(selected == g["selected_ids"] and lock_sha == g["verified_selection_lock_sha256"], "Final selection binding differs")
            block = read(Path(cap["native_restored_path"]) / "blocks" / group["group_id"] / "terminal.json")
            require(block.get("identity") == self.config["identity"] and block.get("group_id") == group["group_id"] and block.get("selection_lock_sha256") == lock_sha and block.get("training_terminal_status") == {i: s["fits"][i]["state"] for i in group["fit_ids"]}, "Final group terminal differs from native ledger")
            members.update(manifest["claimed_fit_ids"])
            semantics.add(manifest["study_semantic_sha256"])
            capsules.append(dict(group_id=group["group_id"], fit_ids=group["fit_ids"], selected_ids=g["selected_ids"], selection_lock_sha256=g["verified_selection_lock_sha256"], capsule=cap))
        require(members == set(s["fits"]) and len(semantics) == 1, "Eight-group union does not represent the exact same full study")
        value = dict(schema="hcsn-mechanism-full-study-analysis-handoff-v1", status="EXECUTION_CLOSED_ANALYSIS_PENDING", identity=self.config["identity"],
            published_plan_commit=self.config["published_plan_commit"], published_plan_ref=REF, publication_receipt=self.config["publication_receipt"], control_pins=self.config["control_pins"],
            source_root=str(self.source_root), plan_path=str(self.source_root / self.config["plan_relative_path"]), qualified_input=self.config["qualified_input"], groups=capsules,
            ledger_head_before_closure=self.ledger.previous, ledger_events_directory=str(self.ledger.root / "events"), adapter_calls_directory=str(self.ledger.root / "adapter-calls"),
            progress=self.summary(), next_owner="root", next_action="Assemble all eight immutable group capsules into one fresh full-study tree; preserve all attempts, failures and losing LR checkpoints; then run the frozen mechanism_analysis.py in an independently recorded CPU analysis-only environment.",
            analysis_started=False, scientific_admission="HOLD", original_campaign_completion_credit=0, full_physical_energy_joules=None, monetary_cost=None,
            cost_rule="Retain every native adapter and provider receipt; payload, operation, worker and GPU intervals are nested scopes, never blindly added.")
        path = self.ledger.root / "final-handoff.json"
        raw = canonical(value)
        if path.exists():
            require(file_bytes(path) == raw, "Existing final handoff differs")
        else:
            exclusive(path, raw)
        return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())

    def run(self):
        require(self.ledger.state["halted"] is None, "Owner is halted; explicit review required")
        try:
            if self.ledger.state["execution_finished"]:
                return self.summary()
            while not all(g["phase"] == "done" for g in self.ledger.state["groups"].values()):
                active = self.ledger.state["active"]
                if active is None:
                    group = next(g for g in self.config["groups"] if self.ledger.state["groups"][g["group_id"]]["phase"] != "done")
                    self.reserve(group)  # Initial ACK is not yet a verified remote observation.
                active = self.ledger.state["active"]
                remote = self.adapter.call("resume", ["--request-id", active["request_id"]])
                require(remote.get("remote_submission_replayed") is False, "Resume must not replay submission")
                while True:
                    producer = validate_remote(remote, active, self.config)
                    if active["producer"] is None:
                        s = self.ledger.copy()
                        s["active"]["producer"] = producer
                        self.ledger.append("PROVIDER_ACKNOWLEDGED", s, remote)
                        active = self.ledger.state["active"]
                    if remote.get("remote_state") in PROVIDER_TERMINAL:
                        if active["terminal_observation"] is None:
                            s = self.ledger.copy()
                            s["active"]["terminal_observation"] = remote
                            self.ledger.append("PROVIDER_TERMINAL_OBSERVED", s, remote)
                        break
                    require(remote.get("remote_state") in {"QUEUED", "RUNNING"}, "Unknown provider state; halt without replay")
                    require(time.time() < active["reserved_unix"] + 3900, "Observation deadline only; no provider stop inferred")
                    remote = self.adapter.call("wait", ["--request-id", active["request_id"], "--wait-seconds", "30"])
                self.adapter.call("logs", ["--request-id", active["request_id"], "--limit", "16384"])
                artifacts = self.adapter.call("artifacts", ["--request-id", active["request_id"], "--manifest-name", "artifact-manifest.json", "--max-bytes", "67108864"], 600)
                self.accept(remote, artifacts)
                print(json.dumps(self.summary(), sort_keys=True, allow_nan=False), flush=True)
            handoff = self.final_handoff()
            s = self.ledger.copy()
            s["execution_finished"] = True
            s["final_handoff"] = handoff
            self.ledger.append("EXECUTION_CLOSED", s, self.summary())
            return self.summary()
        except BaseException as error:
            s = self.ledger.copy()
            s["halted"] = dict(type=type(error).__name__, reason=str(error), pending_provider_may_still_run=s["active"] is not None and s["active"].get("terminal_observation") is None, automatic_replay=False)
            self.ledger.append("HALTED", s)
            raise

    def summary(self):
        s = self.ledger.state
        known = [x.get("optimizer_updates_completed") for x in s["fits"].values() if x["ever_claimed"]]
        active = s["active"]
        unresolved = [dict(request_id=active["request_id"], phase=active["phase"], planned_fit_ids=active["planned_fit_ids"], planned_evaluation_ids=active["planned_evaluation_ids"], producer=active.get("producer"), native_terminal_observed=active.get("terminal_observation") is not None, complete_capsule_accepted=False)] if active else []
        return dict(schema="hcsn-global-160-owner-progress-v1", registered_fit_count=160, fit_counts=dict(Counter(x["state"] for x in s["fits"].values())),
                    ever_claimed_fit_count=sum(x["ever_claimed"] for x in s["fits"].values()), registered_optimizer_updates=64000,
                    known_optimizer_updates_lower_bound=sum(x for x in known if type(x) is int and x >= 0), missing_update_counter_count=sum(type(x) is not int for x in known),
                    statistical_groups=8, group_phases={k: v["phase"] for k, v in s["groups"].items()}, provider_jobs_reserved=s["batch_count"],
                    unresolved_provider_jobs=unresolved, unclaimed_reserved_fit_count=sum(v["state"] == "RESERVED" for v in s["fits"].values()), final_handoff=s.get("final_handoff"),
                    missing_cost_scope=["Full physical energy", "Provider monetary charges", "End-to-end external deployment cost"] + (["Unresolved provider effects and any unexported optimizer updates"] if unresolved else []),
                    original_campaign_completion_credit=0, scientific_admission="HOLD", full_physical_energy_joules=None, monetary_cost=None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "source-root", "plan", "control-root", "published-plan-commit", "published-plan-ref"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    config = read(args.config)
    require(Path(__file__).resolve() == (Path(args.control_root) / "native_owner.py").resolve(), "Running native owner is outside the declared control source root")
    plan = validate_config(config, args.source_root, args.plan, args.control_root, args.published_plan_commit, args.published_plan_ref)
    sys.path.insert(0, str(Path(args.control_root).resolve()))
    load_control("capsule_contract", args.control_root, config["control_pins"]["capsule_contract.py"])
    cloud = load_control("cloud_batch", args.control_root, config["control_pins"]["cloud_batch.py"])
    owner = Owner(config, plan, args.source_root, args.control_root, Ledger(config["state_root"], config), cloud.build_payload)
    print(json.dumps(owner.run(), sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
