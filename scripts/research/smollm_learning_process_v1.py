#!/usr/bin/env python3
"""Explicit research backend for the native learning-owner integration test.

Runs the original pinned trainer and weight worker. It has no production grant,
CURRENT writer, signing key or Chain writer. Every operation has fresh storage;
native admission and the complete absolute deadline are supplied on stdin.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HELPER_SHA = "185e747bb90e4c793ea9c2bc0ce8606f88780d7154873e153a902f4da4e2ee4e"
WORKER_SHA = "10c09efcb24d65ce850ccbee61f3034262fa026ee5d19adab90bc9eda67049c0"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    raw = canonical(value) + b"\n"
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    assert sha(args.config) == args.config_sha256
    config = json.loads(args.config.read_bytes())
    request_raw = sys.stdin.buffer.read(16385)
    assert 0 < len(request_raw) <= 16384
    request = json.loads(request_raw)
    assert request["schema"] == "hepta.research.smollm.process.v1"
    assert request["operation"] == config["operation"]
    assert time.time() < request["deadline_unix_seconds"]
    root = Path(config["output"])
    research = Path(config["research_root"])
    previous = Path(config["previous_run"])
    helper_path = Path(config["worker_helper"])
    assert sha(helper_path) == HELPER_SHA
    helper_spec = importlib.util.spec_from_file_location("actual_readback", helper_path)
    helper = importlib.util.module_from_spec(helper_spec)
    exec(compile(helper_path.read_bytes(), str(helper_path), "exec"), helper.__dict__)
    worker = research / "worktree/workers/weight/worker.py"
    assert sha(worker) == WORKER_SHA
    source = research / "inputs/source/chain"
    action = request["action"]
    before = {str(p): sha(p) for directory in (source, worker.parent)
              for p in sorted(directory.rglob("*"))
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    if action == "prepare":
        root.mkdir(mode=0o700, exist_ok=False)
        previous_result = json.loads((previous / "training-result.json").read_bytes())
        previous_plan = json.loads((previous / "frozen-plan.json").read_bytes())
        parent_ref = previous_result["stages"][0]["parent_material"]
        assert sha(parent_ref["path"]) == parent_ref["sha256"]
        parent = json.loads(Path(parent_ref["path"]).read_bytes())
        data = previous_plan["inputs"][1]
        assert sha(data["path"]) == data["sha256"]
        raw_data = Path(data["path"]).read_bytes()
        rows = json.loads(raw_data)["records"]
        base_config = json.loads((previous / "model-generation-1.json").read_bytes())
        evaluation = [dict(row, request_id=config["operation"] + f"-eval-{i}")
                      for i, row in enumerate(previous_plan["evaluation"])]
        frozen = dict(schema="hepta.research.smollm.frozen.v1", operation=config["operation"],
                      created_unix_ns=time.time_ns(), deadline_unix_seconds=request["deadline_unix_seconds"],
                      dataset=data, dataset_rows=len(rows), dataset_bytes=len(raw_data),
                      parent=parent, parent_ref=parent_ref, model_config=base_config,
                      evaluation=evaluation, evaluation_profile=previous_plan["evaluation_profile"],
                      decision_rule="candidate-correct-strictly-greater-else-NoUpdate",
                      next_prompt=previous_plan["next_task"]["prompt"], steps=10, cpu_threads=4,
                      maximum_training_seconds=90, source_before=before,
                      prior_tasks_and_outcomes_exposed=True, independent_evaluation=False,
                      qualification="HOLD_NO_GO")
        frozen_ref = save(root / "frozen.json", frozen)
        assert sha(Path(parent["directory"]) / "artifact.safetensors") == parent["file_sha256"]
        result = dict(frozen=frozen_ref, parent=parent, dataset=data, dataset_rows=len(rows),
                      dataset_bytes=len(raw_data), model_config=base_config,
                      worker_sha256=WORKER_SHA, helper_sha256=HELPER_SHA,
                      evaluation_profile_sha256=hashlib.sha256(canonical(dict(
                          evaluation=evaluation, rule=frozen["decision_rule"], profile=frozen["evaluation_profile"]))).hexdigest(),
                      source_digest=hashlib.sha256(canonical(before)).hexdigest(),
                      next_prompt=frozen["next_prompt"], device_sha256=sha("/proc/sys/kernel/osrelease"))
    else:
        frozen = json.loads((root / "frozen.json").read_bytes())
        assert frozen["operation"] == config["operation"] and frozen["source_before"] == before
        assert request["frozen_sha256"] == sha(root / "frozen.json")
        assert request["deadline_unix_seconds"] == frozen["deadline_unix_seconds"]
        parent = frozen["parent"]
        assert sha(Path(parent["directory"]) / "artifact.safetensors") == parent["file_sha256"]
        if action == "train":
            assert len(request["initial_learning_head"]) == len(request["dataset_learning_head"]) == 64
            save(root / "native-training-admission.json", request)
            data = frozen["dataset"]
            assert sha(data["path"]) == data["sha256"]
            command = [sys.executable, str(source / "scripts/llm_inherited_runtime.py"), "train",
                       "--materials", str(research / "pinned-base"), "--output", str(root / "training"),
                       "--operation-id", config["operation"] + "-train", "--input", data["path"],
                       "--input-sha256", data["sha256"], "--threads", "4", "--steps", "10",
                       "--parent", frozen["parent_ref"]["path"], "--parent-sha256", frozen["parent_ref"]["sha256"]]
            start = time.monotonic_ns()
            remaining = min(90, request["deadline_unix_seconds"] - time.time())
            assert remaining > 0
            with (root / "training.log").open("xb") as log:
                run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=remaining,
                                     env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
            milliseconds = (time.monotonic_ns() - start + 999999) // 1000000
            save(root / "training-command.json", dict(command=command, returncode=run.returncode, milliseconds=milliseconds))
            assert run.returncode == 0
            receipt_path = root / "training/worker/actual-receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            candidate = json.loads((root / "training/worker/parent-material.json").read_bytes())
            assert receipt["outcome"] == "success" and receipt["parameter_change"] is True
            assert receipt["training"]["steps"] == 10 and receipt["actual_loaded_parent"] == parent["adapter"]
            artifact = Path(candidate["directory"]) / "artifact.safetensors"
            assert sha(artifact) == candidate["file_sha256"] and receipt["artifact"] == candidate["adapter"]
            assert candidate["generation"] == parent["generation"] + 1
            result = dict(candidate=candidate, steps=10, milliseconds=milliseconds,
                          artifact_bytes=artifact.stat().st_size, actual_loaded_parent=parent["adapter"],
                          receipt=dict(path=str(receipt_path), sha256=sha(receipt_path)),
                          dataset_sha256=data["sha256"], source_digest=hashlib.sha256(canonical(before)).hexdigest())
        elif action == "evaluate":
            candidate = json.loads((root / "training/worker/parent-material.json").read_bytes())
            evaluations = []
            for label, material in (("parent", parent), ("candidate", candidate)):
                rows = []
                owner, opened = open_worker(helper, worker, root, config, frozen, material, label + "-eval", 4)
                try:
                    for index, row in enumerate(frozen["evaluation"], 1):
                        inputs = dict(mode="conditional_binary", request_id=row["request_id"], prompt=row["prompt"])
                        response = owner.call(f"evaluation-{index}", "probe", dict(inputs=inputs))
                        observed = helper.output_record(response, inputs, index)
                        observed.update(expected_output=row["expected_output"], correct=observed["predicted_output"] == row["expected_output"])
                        rows.append(observed)
                    close = owner.call("close", "close", {})
                    assert close["ok"] and close["result"]["forward_examples"] == 4
                finally:
                    save(root / (label + "-eval-exit.json"), owner.finish())
                evaluations.append(dict(role=label, adapter=material["adapter"], correct=sum(x["correct"] for x in rows), rows=rows))
            disposition = "Qualified" if evaluations[1]["correct"] > evaluations[0]["correct"] else "NoUpdate"
            result = dict(disposition=disposition, evaluations=evaluations, candidate=candidate,
                          selected_adapter=parent["adapter"] if disposition == "NoUpdate" else candidate["adapter"],
                          frozen_sha256=sha(root / "frozen.json"))
        elif action in ("probe", "probe_recover"):
            inputs = request["inputs"]
            assert inputs["mode"] == "conditional_binary" and inputs["prompt"] == frozen["next_prompt"]
            assert request["selected_adapter"] == parent["adapter"]
            token = hashlib.sha256(inputs["request_id"].encode()).hexdigest()[:20]
            name = "probe-" + token
            original = root / (name + "-response.json")
            if action == "probe":
                assert not original.exists()
            else:
                assert original.is_file()
            owner, opened = open_worker(helper, worker, root, config, frozen, parent, name, 1,
                                        transcript=name + ("-cold" if action == "probe_recover" else "-hot"))
            try:
                response = owner.call("native-step", "probe", dict(inputs=inputs))
                observed = helper.output_record(response, inputs, 1)
                if action == "probe":
                    save(original, response)
                else:
                    assert response == json.loads(original.read_bytes())
                    wrong = dict(inputs, prompt=inputs["prompt"] + " changed")
                    conflict = owner.call("native-step", "probe", dict(inputs=wrong))
                    assert not conflict["ok"] and conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
                    exhausted = owner.call("extra", "probe", dict(inputs=dict(inputs, request_id=inputs["request_id"] + "-extra")))
                    assert not exhausted["ok"] and exhausted["error"]["code"] == "FORWARD_BUDGET"
                    save(root / (name + "-recovery-controls.json"), dict(conflict=conflict, exhausted=exhausted))
                # EOF preserves the same session ledger; close would terminate it.
            finally:
                exit_record = owner.finish()
                save(root / (name + ("-cold-exit.json" if action == "probe_recover" else "-hot-exit.json")), exit_record)
            result = dict(schema="hepta.research.smollm.actual-proposal.v1", selected_adapter=parent["adapter"],
                          selected_file_sha256=parent["file_sha256"], native_request_digest=request["native_request_digest"],
                          observation=observed, original_response_sha256=sha(original), worker_pid=exit_record["pid"],
                          cold_recovery=action == "probe_recover", new_forward_calls=0 if action == "probe_recover" else 1)
        else:
            raise ValueError("unsupported explicit research action")
    assert {path: sha(path) for path in before} == before
    assert time.time() < request["deadline_unix_seconds"]
    evidence_name = action if action not in ("probe", "probe_recover") else action + "-" + hashlib.sha256(request["inputs"]["request_id"].encode()).hexdigest()[:20]
    evidence = save(root / (evidence_name + "-result.json"), result)
    print(json.dumps(dict(schema="hepta.research.smollm.process-result.v1", operation=config["operation"], action=action,
                          request_sha256=hashlib.sha256(request_raw).hexdigest(), result=result, evidence=evidence,
                          authority="DENY_ALL", production_qualification="HOLD_NO_GO"), sort_keys=True), flush=True)


def open_worker(helper, worker, root, config, frozen, material, session_suffix, maximum, transcript=None):
    model = dict(frozen["model_config"], parent_dir=material["directory"], parent_contract=material["contract"],
                 parent_adapter=material["adapter"], parent_file_sha256=material["file_sha256"], generation=material["generation"])
    assert sha(Path(material["directory"]) / "artifact.safetensors") == material["file_sha256"]
    params = dict(provider="smollm2_cell", model=model, cpu_threads=4,
                  input_roots=[model["source_dir"], model["materials_dir"], str(Path(model["plan_path"]).parent), model["parent_dir"]],
                  output_root=str(root / (session_suffix + "-store")), limits=dict(max_forward_examples=maximum, max_patch_candidates=1))
    owner = helper.Worker(worker, config["operation"] + "-" + session_suffix, root, transcript or session_suffix)
    opened = owner.call("open", "open", params)
    assert opened["ok"] and opened["result"]["model"]["parent_adapter"] == material["adapter"]
    assert opened["result"]["model"]["identity"]["parent"]["file_sha256"] == material["file_sha256"]
    return owner, opened


if __name__ == "__main__":
    main()
