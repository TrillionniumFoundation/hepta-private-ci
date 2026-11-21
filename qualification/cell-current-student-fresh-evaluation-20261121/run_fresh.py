"""New manifest-policy single-call evaluation; never imports old raw policy.

Run only after separately published selection and panel receipts. This entry
does not acquire source content, prepare tasks, train, retry, or resume an arm.
"""

import argparse
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import fresh_contract as c

NATIVE_SHA = "023caf96622e555a670215a2dc2373e635b74dfa3bf01c1f656c94d224398ddd"
GATE_SHA = "49cced4d3eb61ee86b1f55a11ca097be7618a0fc9b59e515f1b1d7676bec671c"
CODEC_SHA = "e1147a8d02624ca87b4a1f2f3345b034664b11b074f29787cb4b34085d4058c3"
TRAINING_FILES = {
    "corrections.py": "da699c0b25cf36432cff8952b9c4ec64b7cbae083ade08b9552ccabf48c8a59c",
    "learner.py": "f391f073b906c4e02481e49d1195941e8ba66c0c4f9d50acd7c6b2433aa1947a",
    "comparison.py": "5918e4a67c8e2ffb71969885bcde569ed8ebf215dfed91473102546dd67570bb",
}
ENVIRONMENT_SCOPE = "complete venv tree plus explicitly hashed external symlink file targets; host /usr,/lib,/lib64 dependency closure is not fully inventoried"


def module(name, path, expected):
    path = Path(path).resolve()
    c.require(c.sha(path) == expected, "admitted executable bytes changed: " + str(path))
    c.require(name not in sys.modules or Path(sys.modules[name].__file__).resolve() == path,
              "another module already owns the import name")
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def native_adapter(deployment):
    native = module("fresh_original_native", deployment["native_source"], NATIVE_SHA)
    for key, expected in (("ANCESTOR", GATE_SHA), ("CODEC", CODEC_SHA)):
        path = Path(deployment[key.casefold()])
        c.require(c.sha(path) == expected, "original gate/codec changed")
        setattr(native, key, path)
    environment = c.read_bound(deployment["native_environment"])
    c.require(environment["schema"] == "hepta.readonly-native-environment.v1"
              and environment["inventory_scope"] == ENVIRONMENT_SCOPE
              and environment["host_mount_closure_complete"] is False, "explicit verifier inventory boundary required")
    root, observed = Path(environment["root"]), set()
    for row in environment["files"]:
        relative = Path(row["path"])
        c.require(not relative.is_absolute() and ".." not in relative.parts, "unsafe verifier environment path")
        path = root / relative
        if row.get("symlink_target") is not None:
            c.require(path.is_symlink() and path.readlink().as_posix() == row["symlink_target"], "verifier symlink changed")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root.resolve()):
                target = row["external_target"]
                c.require(resolved.is_file() and str(resolved) == target["path"]
                          and resolved.stat().st_size == target["bytes"] and c.sha(resolved) == target["sha256"],
                          "external symlink target bytes changed or directory was not inventoried")
        else:
            c.require(path.is_file() and not path.is_symlink() and path.stat().st_size == row["bytes"]
                      and c.sha(path) == row["sha256"], "verifier environment bytes changed")
        observed.add(relative.as_posix())
    c.require(observed == {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()},
              "verifier environment inventory changed")
    c.require(c.sha(root / "bin/python") == environment["python_binary_sha256"], "verifier interpreter changed")
    native.VENV, native.HOST_CANARY = root, Path(deployment["host_canary"])
    c.require(native.HOST_CANARY.is_file(), "owner canary missing")
    native.environment_scope_receipt = {"inventory_binding": deployment["native_environment"],
        "scope": ENVIRONMENT_SCOPE, "host_mount_closure_complete": False}
    return native


def model_manifests(weights, bundle, engine, artifact_root):
    manifests = {}
    for mode in c.MODES:
        child = c.read_bound(weights["models"][mode]["manifest"])
        fit = c.read_bound(weights["models"][mode]["training_result"])
        parent = bundle["parents"][mode]["manifest"]
        c.require(child["schema"] == "hepta.current-student-correction-model.v1"
                  and child["candidate_digest"] == c.TRAINING_CANDIDATE
                  and child["parent_manifest"] == parent
                  and child["parent_model_digest"] == c.digest(parent)
                  and child["parameter_before"] == parent["parameter_after"]
                  and child["parameter_after"] != child["parameter_before"]
                  and child["runtime"] == parent["runtime"] and child["base_manifest"] == parent["base_manifest"],
                  "new child must continue this exact frozen parent")
        c.require(fit["status"] == "COMPLETE" and fit["model_digest"] == c.digest(child)
                  and fit["steps"] == fit["durably_completed_updates"] == fit["possible_actual_update_upper_bound"] == 8
                  and fit["journal_complete"] is True and fit["update_completion_uncertain"] is False,
                  "both bounded child fits must be complete and unambiguous")
        for value in (parent, child):
            directory = engine.probe._base(artifact_root, value["adapter_directory"])
            c.require(engine.probe._inventory(directory) == value["adapter_files"], "actual adapter bytes changed")
        manifests[mode] = {"frozen": parent, "retrieval": parent, "final_only": child}
    return manifests


def policy_guard(predictor, manifest):
    runtime, generation = manifest["runtime"], predictor.generation.to_dict()
    c.require(runtime["max_input_tokens"] == 4096 and runtime["max_new_tokens"] == 384
              and runtime["message_protocol"] == "native_chat_v2" and runtime["attn_implementation"] == "eager",
              "new single-call manifest policy differs")
    c.require(runtime["generation"]["do_sample"] is False
              and runtime["generation"]["num_beams"] == runtime["generation"]["num_return_sequences"] == 1
              and runtime["generation"]["max_new_tokens"] == 384
              and all(generation[key] == value for key, value in runtime["generation"].items())
              and c.digest(generation) == predictor.generation_digest,
              "actual generation differs from frozen manifest; defaults are not substitutes")
    c.require(predictor.model_digest == c.digest(manifest)
              and predictor.model.config._attn_implementation == "eager"
              and all(not parameter.requires_grad for parameter in predictor.model.parameters()),
              "fresh eager frozen model load required")
    return {"request_policy": c.POLICY, "runtime_digest": c.digest(runtime),
            "actual_generation_config_sha256": predictor.generation_digest,
            "old_raw_8192_2048_policy_comparable": False}


def run_task(record, request, capacity, predictor, native, slots, slot, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, native_pending = time.perf_counter(), False
    try:
        c.write_new(output / "REQUEST.json", request)
        slots.claim("generation", slot, {"record_id": record["record_id"], "request_digest": c.digest(request)})
        c.write_new(output / "GENERATION_DISPATCH.json", {"started_at_ns": str(time.time_ns()),
                    "monotonic_started_ns": str(time.monotonic_ns()), "slot": list(slot)})
        produced = predictor.predict(request)
        c.write_new(output / "OUTPUT.json", produced)
        c.require(produced["loaded_model_digest"] == predictor.model_digest
                  and produced["generation_config_sha256"] == predictor.generation_digest
                  and produced["input_tokens"] == capacity["input_tokens"]
                  and produced["rendered_input_sha256"] == capacity["rendered_input_sha256"]
                  and produced["output_tokens"] == len(produced["output_token_ids"]) <= 384
                  and type(produced["hit_output_limit"]) is bool, "actual generation receipt differs")
        c.write_new(output / "GENERATION_RETURN.json", {"completed_at_ns": str(time.time_ns()),
                    "monotonic_completed_ns": str(time.monotonic_ns()), "output_digest": c.digest(produced)})
        if produced["hit_output_limit"]:
            verification = {"success": False, "stage": "output_cap_refusal", "actual_native_child": False}
        else:
            slots.claim("evaluation_native", slot, {"raw_output_sha256": c.sha(output / "OUTPUT.json")})
            native_pending = True
            verification = native.verify(record["task_spec_path"], record["task_spec_sha256"],
                                         produced["answer"], output / "verify", record["expected_cases"])
            native_pending = False
        c.write_new(output / "VERIFICATION.json", verification)
        row = {"record_id": record["record_id"], "slot": list(slot), "success": verification["success"],
               "actual_native_child": verification["actual_native_child"], "output_cap_hit": produced["hit_output_limit"],
               "request_digest": c.digest(request), "output_digest": c.digest(produced),
               "verification_digest": c.digest(verification), "input_tokens": produced["input_tokens"],
               "output_tokens": produced["output_tokens"], "wall_seconds": time.perf_counter() - started}
        c.write_new(output / "RESULT.json", row)
        return row
    except BaseException as error:
        if native_pending:
            c.write_new(slots.root.parent / "EXECUTION_UNCERTAIN.json", {"slot": list(slot),
                        "reason": "original native verifier did not return its waited receipt", "automatic_retry": False})
        c.write_new(output / "FAILED.json", {"error_type": type(error).__name__, "error": str(error),
                    "generation_or_native_dispatch_may_have_occurred": True, "automatic_retry": False,
                    "cost_complete": False, "wall_seconds": time.perf_counter() - started})
        raise


def evaluate(deployment, mode, arm, supervision):
    c.require(supervision["parent_pid"] == os.getppid() and supervision["mode"] == mode
              and supervision["arm"] == arm and supervision["deployment_digest"] == c.digest(deployment),
              "bounded fresh supervisor required")
    selection = c.read_bound(deployment["selection"])
    c.validate_selection(selection, c.read_bound(deployment["weights"]), c.read_bound(deployment["excluded"]),
                         c.read_bound(deployment["selection_publication"]))
    root = Path(selection["owner_root"])
    root.mkdir(parents=True, exist_ok=True)
    c.require(not (root / "EXECUTION_UNCERTAIN.json").exists(), "previous worker cleanup remains uncertain")
    with (root / "EVALUATION.lock").open("a+b") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _evaluate(deployment, mode, arm)


def _evaluate(deployment, mode, arm):
    c.require(deployment["schema"] == "hepta.current-student-fresh-deployment.v1"
              and mode in c.MODES and arm in c.ARMS, "new deployed arm required")
    for name in ("fresh_contract.py", "run_fresh.py"):
        c.require(c.sha(Path(__file__).parent / name) == deployment["source_files"][name], "fresh executable changed")
    selection, weights, excluded, publication, panel = [c.read_bound(deployment[key]) for key in
        ("selection", "weights", "excluded", "selection_publication", "panel")]
    c.validate_selection(selection, weights, excluded, publication)
    c.panel_guard(panel, selection, excluded, publication)
    seal = c.read_bound(deployment["panel_seal"])
    c.require(Path(deployment["panel_seal"]["path"]).resolve() == Path(selection["owner_root"]) / "PANEL_FROZEN.json"
              and seal["status"] == "PANEL_FROZEN" and seal["panel_digest"] == c.digest(panel)
              and seal["selection_digest"] == c.digest(selection) and seal["panel"] == deployment["panel"],
              "source acquisition must be sealed before evaluation")
    publication_panel = c.read_bound(deployment["panel_publication"])
    c.require(publication_panel["panel_digest"] == c.digest(panel)
              and re.fullmatch(r"[0-9a-f]{40}", publication_panel["commit"])
              and max(int(publication["published_at_ns"]), int(seal["created_at_ns"]), *(int(row["source_preparation_completed_at_ns"]) for row in panel["tasks"]))
              < int(publication_panel["published_at_ns"]) <= time.time_ns(),
              "frozen panel publication required")
    output = Path(selection["owner_root"]) / "evaluation" / mode / arm
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "OWNER_STARTED.json", {"mode": mode, "arm": arm, "policy": c.POLICY, "automatic_retry": False})
    predictor, rows = None, []
    try:
        learner, comparison, bundle, engine, manifests = assets(deployment, weights)
        manifest = manifests[mode][arm]
        native = native_adapter(deployment)
        for record in panel["tasks"]:
            spec = native.bound(record["task_spec_path"], record["task_spec_sha256"])
            before, after = native.before_oracle(spec)
            c.require(spec["project_id"] == record["project_id"] and spec["source_path"] == record["source_path"]
                      and spec["function"] == record["allowed_function"] and native.sha(before) == record["original_source_sha256"]
                      and native.sha(after) == record["original_after_sha256"], "actual source inventory differs before model load")
        torch, _ = engine.probe._libraries()
        device = torch.device(manifest["runtime"]["device"])
        torch.cuda.set_per_process_memory_fraction(0.70, device)
        predictor = learner.load_model(manifest, c.digest(manifest), deployment["artifact_root"], engine)
        c.write_new(output / "POLICY.json", {**policy_guard(predictor, manifest),
                    "native_environment": native.environment_scope_receipt})
        slots = c.Slots(selection, excluded)
        requests = []
        for record in panel["tasks"]:
            request = {"record_id": record["record_id"], "task": copy.deepcopy(record["task"])}
            prepared, retrieval = comparison.prepare_request("retrieval" if arm == "retrieval" else "frozen",
                request, bundle, mode, predictor.tokenizer, engine.chat_protocol)
            reference = Path(record["reference"]["path"])
            c.require(reference.is_file() and reference.stat().st_size <= 65536
                      and c.sha(reference) == record["reference"]["sha256"], "bound complete reference changed")
            measured = c.complete_capacity(prepared, reference.read_bytes().decode("utf-8"), predictor.tokenizer, engine.chat_protocol)
            capacity = record["capacity"][mode][arm]
            c.require(capacity == measured,
                      "published full-context/reference capacity differs")
            requests.append((record, prepared, measured, retrieval))
        for index, (record, request, capacity, retrieval) in enumerate(requests):
            c.require(c.read_bound(deployment["panel"]) == panel and c.read_bound(deployment["selection"]) == selection,
                      "published evaluation inputs changed before dispatch")
            row = run_task(record, request, capacity, predictor, native, slots, (mode, arm, index), output / str(index))
            row["retrieval"] = retrieval
            rows.append(row)
        result = {"schema": "hepta.current-student-fresh-arm.v1", "status": "COMPLETE", "mode": mode, "arm": arm,
                  "policy": c.POLICY, "rows": rows, "completed_model_calls": len(rows),
                  "actual_native_children": sum(row["actual_native_child"] for row in rows),
                  "full_system_cost_known": False, "scientific_confirmation_qualified": False,
                  "old_raw_policy_comparable": False, "native_adoption": False}
        c.write_new(output / "RESULT.json", result)
        return result
    except BaseException as error:
        c.write_new(output / "FAILED.json", {"error_type": type(error).__name__, "error": str(error),
                    "completed_rows": len(rows), "automatic_retry": False, "cost_complete": False})
        raise
    finally:
        if predictor is not None:
            predictor.close()


def assets(deployment, weights):
    """Verify actual new child/parent files without constructing a predictor."""
    training = Path(deployment["training_directory"])
    modules = {name: module(name, training / (name + ".py"), TRAINING_FILES[name + ".py"])
               for name in ("corrections", "learner", "comparison")}
    learner, comparison = modules["learner"], modules["comparison"]
    bundle, protocol = learner.inputs(deployment["prepared_directory"])
    c.require(protocol["candidate_digest"] == c.TRAINING_CANDIDATE, "other training candidate rejected")
    engine = learner.load_engine(bundle, deployment["framework_root"], deployment["engine_directory"])
    manifests = model_manifests(weights, bundle, engine, deployment["artifact_root"])
    return learner, comparison, bundle, engine, manifests


def supervise(binding, mode, arm):
    """Own a finite worker process group; uncertain cleanup blocks later arms."""
    deployment = c.read_bound(binding)
    selection = c.read_bound(deployment["selection"])
    c.validate_selection(selection, c.read_bound(deployment["weights"]), c.read_bound(deployment["excluded"]),
                         c.read_bound(deployment["selection_publication"]))
    root = Path(selection["owner_root"])
    c.require(not (root / "EXECUTION_UNCERTAIN.json").exists(), "previous cleanup is unresolved")
    c.require(mode in c.MODES and arm in c.ARMS, "undeclared supervised arm")
    output = root / "supervision" / mode / arm
    output.mkdir(parents=True, exist_ok=False)
    identity = {"parent_pid": os.getpid(), "mode": mode, "arm": arm, "deployment_digest": c.digest(deployment)}
    c.write_new(output / "OWNER.json", identity)
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--deployment", binding["path"],
            "--deployment-sha256", binding["sha256"], "--mode", mode, "--arm", arm,
            "--worker-owner", str(output / "OWNER.json"), "--worker-owner-sha256", c.sha(output / "OWNER.json")]
    started, error, code, returned_slots = time.monotonic(), None, None, set()
    with (output / "STDOUT.txt").open("xb") as stdout, (output / "STDERR.txt").open("xb") as stderr:
        worker = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True)
        c.write_new(output / "WORKER_STARTED.json", {"pid": worker.pid, "process_group_id": worker.pid, "argv": argv})
        def interrupted(signum, frame):
            raise InterruptedError("supervisor received signal " + str(signum))

        handlers = {signum: signal.signal(signum, interrupted) for signum in (signal.SIGTERM, signal.SIGINT)}
        try:
            while worker.poll() is None:
                c.require(time.monotonic() - started < 2400, "evaluation arm wall deadline exceeded")
                for index in range(4):
                    call = root / "evaluation" / mode / arm / str(index)
                    dispatch, returned = call / "GENERATION_DISPATCH.json", call / "GENERATION_RETURN.json"
                    if index not in returned_slots and returned.exists():
                        try:
                            receipt = json.loads(returned.read_bytes())
                            if int(receipt["monotonic_completed_ns"]) > 0 and re.fullmatch(r"[0-9a-f]{64}", receipt["output_digest"]):
                                returned_slots.add(index)
                        except (ValueError, KeyError):
                            pass
                    if dispatch.exists() and index not in returned_slots:
                        try:
                            timestamp = int(json.loads(dispatch.read_bytes())["monotonic_started_ns"])
                        except (ValueError, KeyError):
                            continue
                        c.require(time.monotonic_ns() - timestamp < 300 * 10**9, "generation wall deadline exceeded")
                time.sleep(0.25)
            code = worker.wait(timeout=10)
        except BaseException as caught:
            error = repr(caught)
            try:
                os.killpg(worker.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                code = worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    code = worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    code = None
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
        if (error is not None or code is None or code < 0) and not (root / "EXECUTION_UNCERTAIN.json").exists():
            c.write_new(root / "EXECUTION_UNCERTAIN.json", {"worker_pid": worker.pid, "mode": mode, "arm": arm,
                        "worker_exit_confirmed": code is not None, "owned_native_cleanup_confirmed": False,
                        "reason": "forced worker stop does not establish native process-group cleanup",
                        "read_only_owner_scope_cleanup_evidence_required": True, "automatic_retry": False})
    receipt = {"schema": "hepta.current-student-fresh-supervision.v1", "returncode": code, "error": error,
               "worker_exit_confirmed": code is not None, "wall_seconds": time.monotonic() - started,
               "generation_deadline_seconds": 300, "arm_deadline_seconds": 2400, "automatic_retry": False,
               "native_cleanup_policy": "original bwrap die-with-parent and original native 120s/TERM/KILL bounds retained",
               "stdout_sha256": c.sha(output / "STDOUT.txt"), "stderr_sha256": c.sha(output / "STDERR.txt"),
               "all_namespace_descendant_reaping_observed": False}
    c.write_new(output / "RESULT.json", receipt)
    c.require(error is None and code == 0, "bounded worker failed; claims and full owner logs retained")
    return receipt


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--deployment-sha256", required=True)
    parser.add_argument("--mode", choices=c.MODES, required=True)
    parser.add_argument("--arm", choices=c.ARMS, required=True)
    parser.add_argument("--worker-owner")
    parser.add_argument("--worker-owner-sha256")
    args = parser.parse_args()
    binding = {"path": args.deployment, "sha256": args.deployment_sha256}
    if args.worker_owner:
        result = evaluate(c.read_bound(binding), args.mode, args.arm,
                          c.read_bound({"path": args.worker_owner, "sha256": args.worker_owner_sha256}))
        print(json.dumps({"status": result["status"], "completed_model_calls": result["completed_model_calls"]}))
    else:
        print(json.dumps(supervise(binding, args.mode, args.arm)))
