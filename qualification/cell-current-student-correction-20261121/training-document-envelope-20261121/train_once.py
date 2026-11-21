"""Bound one unchanged learner.train call; preserve all claims and partial journals."""

import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import time
import traceback
import types

HARD_DEADLINE = None


def load_code(name, path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("frozen execution source differs: " + str(path))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def arm(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("fixed training deadline is exhausted")
    signal.setitimer(signal.ITIMER_REAL, remaining)


def expired(signum, frame):
    if time.monotonic() >= HARD_DEADLINE:
        os._exit(124)
    signal.setitimer(signal.ITIMER_REAL, HARD_DEADLINE - time.monotonic())
    raise TimeoutError("predeclared finite training engineering scope expired")


def seal_outputs(helper, output):
    rows, directories = {}, [output]
    for path in sorted(output.rglob("*")):
        state = path.lstat()
        helper.require(not path.is_symlink(), "training output contains a symlink")
        if stat.S_ISDIR(state.st_mode):
            directories.append(path)
            continue
        helper.require(stat.S_ISREG(state.st_mode) and state.st_nlink == 1, "training output is not an owned regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before, checksum, count = os.fstat(fd), hashlib.sha256(), 0
            os.fsync(fd)
            while True:
                block = os.read(fd, 1024 * 1024)
                if not block:
                    break
                checksum.update(block)
                count += len(block)
            helper.require(helper.stamp(before) == helper.stamp(os.fstat(fd)) == helper.stamp(path.lstat())
                           and count == before.st_size, "training output changed while sealing")
            rows[path.relative_to(output).as_posix()] = {"bytes": count, "sha256": checksum.hexdigest()}
        finally:
            os.close(fd)
    for path in sorted(directories, key=lambda x: len(x.parts), reverse=True):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    # Persist the new mode, candidate and research-directory entries through
    # their existing artifact root; none of these ancestors is renamed.
    for path in output.parents[:3]:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return rows


def main(plan_path, plan_sha):
    global HARD_DEADLINE
    started, cpu_started = time.monotonic(), time.process_time()
    signal.signal(signal.SIGALRM, expired)
    work_deadline, hard_deadline = started + 900, started + 960
    HARD_DEADLINE = hard_deadline
    arm(work_deadline)
    plan_raw = Path(plan_path).read_bytes()
    if hashlib.sha256(plan_raw).hexdigest() != plan_sha:
        raise RuntimeError("training plan hash differs")
    plan = json.loads(plan_raw)
    helper = load_code("frozen_cpu_evidence_helpers", plan["cpu_helper"]["path"], plan["cpu_helper"]["sha256"])
    helper.require(plan["status"] == "FROZEN_AFTER_CPU_EVIDENCE_PUBLICATION"
                   and helper.canonical(plan) == plan_raw, "training plan is not canonically frozen")
    helper.require(plan["work_seconds"] == 900 and plan["hard_seconds"] == 960
                   and plan["outer_transport_timeout_seconds"] == 1020
                   and plan["mode"] in ("document_evidence", "native_feedback")
                   and plan["optimizer_updates_per_parent"] == 8 and plan["optimizer_updates_global_cap"] == 16,
                   "fixed engineering or scientific limits differ")
    helper.require(helper.digest(Path(__file__).read_bytes()) == plan["runner_sha256"], "training runner differs")
    evidence = load_code("frozen_training_evidence", plan["evidence_helper"]["path"], plan["evidence_helper"]["sha256"])
    root, prepared = Path(plan["owner"]), Path(plan["prepared"])
    helper.require(root.parent.resolve(strict=True) == root.parent and not root.exists(), "training owner already exists; no retry")
    root.mkdir(mode=0o700)
    fd = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    helper.require(helper.write_new(root / "PLAN.json", plan)["sha256"] == plan_sha, "plan writeback differs")
    helper.write_new(root / "CLAIM.json", {"plan_sha256": plan_sha, "mode": plan["mode"], "pid": os.getpid(),
                     "started_unix_ns": time.time_ns(), "reserved_optimizer_updates": 8,
                     "automatic_retry": False, "automatic_next_phase": False})
    result = {"schema": "hepta.original-student-training-scope.v1", "status": "FAILED", "mode": plan["mode"],
              "plan_sha256": plan_sha, "scientific_candidate": plan["scientific_candidate"],
              "automatic_retry": False, "automatic_next_phase": False, "generation_calls": 0,
              "native_task_executions": 0, "fresh_content_reads": 0, "original_learner_modified": False,
              "scientific_confirmation_qualified": False, "native_adoption": False,
              "frozen_inputs_unchanged": False, "installed_metadata_unchanged": False,
              "full_physical_cost_unknown": True, "python_guard_is_not_os_network_isolation": True}
    learner = bundle = protocol = before = distributions_before = None
    original_called, error = False, None
    output = Path(plan["artifact_root"]) / "research-current-student-correction-20261121" / plan["scientific_candidate"] / plan["mode"]
    try:
        helper.require(tuple(sys.version_info[:3]) == (3, 12, 3) and sys.flags.isolated and sys.dont_write_bytecode
                       and Path(sys.prefix).resolve() == Path(plan["venv"]).resolve()
                       and str(Path(sys.executable).resolve()) == plan["python_identity"]["path"], "qualified isolated runtime differs")
        result["running_interpreter"] = helper.running_interpreter(plan)
        helper.require(all(os.environ.get(k) == v for k, v in plan["required_environment"].items())
                       and "PYTORCH_ALLOC_CONF" not in os.environ, "frozen offline/allocator environment differs")
        desktop = helper.load_exact(plan["runtime_gate"]["desktop_result_path"], plan["runtime_gate"]["desktop_result_sha256"])
        result["runtime_evidence_sha256"] = helper.runtime_proof(plan, desktop)
        encoding_raw = (prepared / "ENCODING.json").read_bytes()
        helper.require(helper.digest(encoding_raw) == plan["prepared_sha256"]["ENCODING.json"], "CPU encoding bytes differ")
        result["admission_evidence"] = evidence.cpu_and_publication(helper, plan, encoding_raw)
        result["predecessor"] = evidence.predecessor(helper, plan)
        existing_claims = {p.name for p in prepared.glob("CLAIM-*.json")}
        helper.require(existing_claims == (set() if plan["mode"] == "document_evidence" else {"CLAIM-document_evidence.json"})
                       and not output.exists(), "original scientific claim or output already exists; no retry")
        bundle = helper.load_exact(prepared / "CORRECTIONS.json", plan["prepared_sha256"]["CORRECTIONS.json"])
        protocol = helper.load_exact(prepared / "PROTOCOL.json", plan["prepared_sha256"]["PROTOCOL.json"])
        helper.require(protocol["candidate_digest"] == plan["scientific_candidate"]
                       and protocol["training_settings"]["steps"] == 8
                       and protocol["optimizer_updates_global_cap"] == 16, "original training protocol differs")
        before = helper.input_inventory(plan, bundle, protocol)
        helper.require(len(before) == 172, "input closure must be original 171 plus published encoding")
        helper.write_new(root / "INPUTS_BEFORE.json", before)
        distributions_before = helper.installed_metadata(plan)
        helper.write_new(root / "DISTRIBUTIONS_BEFORE.json", distributions_before)
        for name in ("cache", "tmp"):
            (root / name).mkdir()
        sys.addaudithook(helper.audit)
        source = Path(plan["learner_directory"])
        sys.path.insert(0, str(source))
        load_code("corrections", source / "corrections.py", protocol["source_files"]["corrections.py"])
        learner = load_code("original_student_learner", source / "learner.py", protocol["source_files"]["learner.py"])
        helper.require(tuple(learner.contract.MODES) == ("document_evidence", "native_feedback")
                       and learner.inputs(prepared) == (bundle, protocol), "unchanged learner input gate differs")
        original_called = True
        fit = learner.train(prepared, plan["mode"], plan["artifact_root"], plan["framework_root"], plan["engine_directory"])
        helper.require(fit == json.loads((output / "TRAINING.json").read_bytes()) and fit["status"] == "COMPLETE"
                       and fit["steps"] == fit["durably_completed_updates"] == fit["possible_actual_update_upper_bound"] == 8
                       and fit["journal_complete"] is True and fit["update_completion_uncertain"] is False,
                       "original fit did not durably finish exactly eight updates")
        steps_raw = (output / "STEPS.jsonl").read_bytes()
        helper.require(steps_raw.endswith(b"\n"), "partial full-step journal")
        steps = [json.loads(line) for line in steps_raw.splitlines()]
        helper.require([row["step"] for row in steps] == list(range(1, 9)), "full-step journal differs")
        mapping = {"model_forwards": "outer_model_forwards", "model_backwards": "outer_model_backwards",
                   "supervised_positions": "supervised_target_positions", "padded_positions": "padded_positions",
                   "input_tokens": "unpadded_positions"}
        actual = {target: sum(row[source] for row in steps) for source, target in mapping.items()}
        helper.require(actual == {k: v for k, v in plan["planned_compute_per_parent"][plan["mode"]].items()
                                  if k != "optimizer_updates"}, "actual original compute differs from CPU schedule")
        manifest = json.loads((output / "manifest.json").read_bytes())
        helper.require(learner.contract.digest(manifest) == fit["model_digest"]
                       and manifest["parent_model_digest"] == bundle["parents"][plan["mode"]]["model_digest"]
                       and manifest["parameter_before"] == bundle["parents"][plan["mode"]]["manifest"]["parameter_after"]
                       and manifest["parameter_after"] != manifest["parameter_before"], "saved child does not continue its original parent")
        result.update(original_training=fit, actual_compute=actual, model_digest=fit["model_digest"],
                      output=str(output), original_artifacts=seal_outputs(helper, output))
        result["inner_checkpoint_counts"] = {key: sum(row["inner_checkpoint_counts"].get(key, 0) for row in steps)
                                               for key in sorted({key for row in steps for key in row["inner_checkpoint_counts"]})}
        helper.require(time.monotonic() < work_deadline, "training work exceeded its finite engineering boundary")
        result["status"] = "TRAINED_PENDING_OUTER_TERMINAL"
    except BaseException as failure:
        arm(hard_deadline)
        error = type(failure).__name__ + ": " + str(failure)
        with (root / "ERROR.txt").open("x") as stream:
            traceback.print_exc(file=stream)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        arm(hard_deadline)
        try:
            if learner is not None and original_called:
                result["update_bounds"] = learner.update_bounds(output / "UPDATES.jsonl", 8)
                if error is None:
                    helper.require(result["update_bounds"] == {key: result["original_training"][key]
                                   for key in result["update_bounds"]}, "final update journal differs from the completed fit")
            else:
                result["update_bounds"] = {"durably_completed_updates": 0, "possible_actual_update_upper_bound": 0,
                                           "update_completion_uncertain": False, "journal_complete": True}
            claim = prepared / ("CLAIM-" + plan["mode"] + ".json")
            result["original_claim_retained"] = claim.exists()
            if claim.exists():
                raw = claim.read_bytes()
                result["original_claim"] = {"path": str(claim), "bytes": len(raw), "sha256": helper.digest(raw)}
        except BaseException as sealing_failure:
            error = (error + "; " if error else "") + "journal readback: " + repr(sealing_failure)
            result.setdefault("update_bounds", {"durably_completed_updates": 0, "possible_actual_update_upper_bound": 8,
                                                 "update_completion_uncertain": True, "journal_complete": False})
        try:
            if before is not None:
                after = helper.input_inventory(plan, bundle, protocol)
                helper.write_new(root / "INPUTS_AFTER.json", after)
                helper.require(after == before, "base, retained parents, encoding, or frozen sources changed")
                result["frozen_inputs_unchanged"] = True
            if distributions_before is not None:
                after_distributions = helper.installed_metadata(plan)
                helper.write_new(root / "DISTRIBUTIONS_AFTER.json", after_distributions)
                helper.require(after_distributions == distributions_before, "installed METADATA changed")
                result["installed_metadata_unchanged"] = True
            for path, expected in ((Path(__file__), plan["runner_sha256"]),
                                   (Path(plan["cpu_helper"]["path"]), plan["cpu_helper"]["sha256"]),
                                   (Path(plan["evidence_helper"]["path"]), plan["evidence_helper"]["sha256"])):
                helper.require(helper.digest(path.read_bytes()) == expected, "execution source changed after admission")
            result["execution_sources_unchanged"] = True
            if output.exists() and "original_artifacts" not in result:
                result["partial_original_artifacts"] = seal_outputs(helper, output)
        except BaseException as sealing_failure:
            error = (error + "; " if error else "") + "finalization: " + repr(sealing_failure)
        arm(hard_deadline)
        if error is not None:
            result["status"] = "FAILED"
        result.update(error=error, original_train_called=original_called, refused_python_events=helper.REFUSED_EVENTS,
                      wall_seconds=time.monotonic() - started, self_cpu_seconds=time.process_time() - cpu_started,
                      cost_scopes_not_additive=True, claimed_update_cap=8,
                      completion_not_proven_if_outer_terminal_unknown=True)
        prior_lower = 8 if result.get("predecessor") is not None else 0
        prior_upper = 8 if plan["mode"] == "native_feedback" else 0
        result["global_update_bounds"] = {"durably_completed_updates": prior_lower + result["update_bounds"]["durably_completed_updates"],
                                          "possible_actual_update_upper_bound": prior_upper + result["update_bounds"]["possible_actual_update_upper_bound"],
                                          "reserved_global_cap": 16}
        receipt = helper.write_new(root / "RESULT.json", result)
        terminal = {"success_pending_outer": error is None, "result": receipt,
                    "after_result_fsync_unix_ns": time.time_ns(), "automatic_next_phase": False}
        helper.write_new(root / "POST_FSYNC.json", terminal)
        helper.require(time.monotonic() < hard_deadline, "training finalization exceeded fixed absolute deadline")
        print(json.dumps(terminal), flush=True)
        signal.setitimer(signal.ITIMER_REAL, 0)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
