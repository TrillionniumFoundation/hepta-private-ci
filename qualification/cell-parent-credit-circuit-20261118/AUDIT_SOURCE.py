"""Audit retained E4 receipts and messages without model or verifier executions."""

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(
    "/home/qian-qi/work/hepta-e4-parent-credit-20261118-2e9b/candidate-18de3463"
)
SOURCE = ROOT / "source"
RUN = ROOT / "run-1"
DEST = ROOT.parent / "export-complete-3"
MODELS = {
    "P": "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786",
    "C": "785bc1cea2996e33cfe02c9c51a5a3802c931b010060369fc659b47fde4440a1",
}
PARAMETERS = {
    "P": "e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f",
    "C": "549ac578447c41d1ddc975f14468c54eeae12ba431f47bcd1a3da46fbc17ce8f",
}
GENERATION = "e31715a80c7c2d6fb35843583b19931ec955723cba8366472ed48b461514e3eb"
VERIFIER = "64fcc25e4ccf82f31c2549f5d4c1a5c4af1831c5bed4219c0aac2283b213a020"
ARMS = [
    ("PP", ("P", "P")),
    ("CC", ("C", "C")),
    ("PC", ("P", "C")),
    ("CP", ("C", "P")),
    ("PC_no_answer", ("P", "C")),
    ("PC_no_feedback", ("P", "C")),
    ("PP_retrieval", ("P", "P")),
    ("CC_retrieval", ("C", "C")),
    ("PC_retrieval", ("P", "C")),
]
INDEX = {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return sha(canonical(value))


def raw_read(path):
    raw = path.read_bytes()
    INDEX[str(path)] = {"bytes": len(raw), "sha256": sha(raw)}
    return raw


def read(path):
    return json.loads(raw_read(path))


def write(name, value):
    with (DEST / name).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def visible(record):
    return {
        "record_id": record["record_id"],
        "task": {
            "input": record["task"]["input"],
            "messages": record["task"].get(
                "messages", [{"role": "user", "content": record["task"]["input"]}]
            ),
        },
    }


def business(record, answer, receipt, controls=None, verifier_source=VERIFIER):
    assert receipt["record_id"] == record["record_id"]
    assert receipt["answer_sha256"] == sha(answer.encode())
    assert receipt["input_sha256"] == sha(record["task"]["input"].encode())
    assert receipt["parameters_sha256"] == digest(
        record["task"]["verifier"]["parameters"]
    )
    assert receipt["verifier"] == ["repo_patch", "1"]
    assert receipt["verifier_source_sha256"] == verifier_source
    assert receipt["production_eligible"] is False
    core = {
        key: value
        for key, value in receipt.items()
        if key not in ("success", "receipt_sha256")
    }
    assert digest(core) == receipt["receipt_sha256"]
    result = receipt["result"]
    assert receipt["success"] == result["success"]
    if result.get("executed", False):
        observed = result["result"]
        original = [
            row for row in observed["observations"] if row["control"] == "original"
        ]
        mutants = [
            row for row in observed["observations"] if row["control"] != "original"
        ]
        assert len(original) == 1 and len(mutants) == observed["control_count"] > 0
        if controls is not None:
            assert len(mutants) == controls
        rejected = sum(not row["passed"] for row in mutants)
        assert observed["original_passed"] == original[0]["passed"]
        assert observed["controls_rejected"] == rejected
        success = original[0]["passed"] and rejected == len(mutants)
    else:
        success = False
    assert receipt["success"] == success
    return success


def cost():
    return {
        "model_calls": 0,
        "verifier_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "business_executions": 0,
        "format_rejections": 0,
        "output_limit_hits": 0,
        "generation_wall_seconds": 0.0,
        "verifier_wall_seconds": 0.0,
        "observed_subject_calls": 0,
    }


def add(target, output, receipt):
    target["model_calls"] += 1
    target["verifier_calls"] += 1
    target["input_tokens"] += output["input_tokens"]
    target["output_tokens"] += len(output["output_token_ids"])
    target["business_executions"] += int(receipt["result"].get("executed", False))
    target["format_rejections"] += int(not receipt["result"].get("executed", False))
    target["output_limit_hits"] += int(output["hit_output_limit"])
    target["generation_wall_seconds"] += output["wall_seconds"]
    target["verifier_wall_seconds"] += receipt["result"].get("wall_ns", 0) / 1e9
    target["observed_subject_calls"] += sum(
        len(row["calls"])
        for row in receipt["result"].get("result", {}).get("observations", [])
    )


def output_identity(output, cell, request, frozen_ns):
    assert output["loaded_model_digest"] == MODELS[cell]
    assert output["generation_config_sha256"] == GENERATION
    assert output["message_protocol"] == "native_chat_v2"
    assert output["max_new_tokens"] == 384
    assert 0 < output["input_tokens"] <= 4096
    assert output["output_tokens"] == len(output["output_token_ids"]) <= 384
    assert output["messages_sha256"] == digest(request["task"]["messages"])
    assert output["input_sha256"] == sha(request["task"]["input"].encode())
    assert output["rendered_input_sha256"] == output["rendered_prompt_sha256"]
    assert frozen_ns < output["started_at_ns"] < output["completed_at_ns"]
    assert output["external_effect_executed"] is False


def main():
    source_freeze = read(ROOT / "SOURCE_FREEZE.json")
    assert source_freeze["source_commit"] == "18de34630fe4b81efaf875c073272b062aeea211"
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True
        ).strip()
        == source_freeze["source_commit"]
    )
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=SOURCE)
    for name, expected in source_freeze["files"].items():
        assert sha((SOURCE / name).read_bytes()) == expected, name
    frozen_ns = source_freeze["created_at_ns"]
    b2_raw = raw_read(
        SOURCE / "qualification/cell-blind-panel-b2-20261118/prepared/records.jsonl"
    )
    assert (
        sha(b2_raw)
        == "26b2e625c649a73a991c681bb1949cdaf91b995d8e4bc3402b924495797d42cb"
    )
    records = [json.loads(line) for line in b2_raw.splitlines() if line]
    assert len(records) == 6 and len({row["record_id"] for row in records}) == 6
    assert all(row["authorization"]["training_allowed"] is False for row in records)
    freeze = read(RUN / "FREEZE.json")
    report = read(RUN / "RESULT.json")
    assert report["freeze_digest"] == digest(freeze)
    assert freeze["record_digests"]["B2_exposed_followup"] == [
        digest(row) for row in records
    ]
    assert [
        (row["name"], tuple(row["graph"]["path"])) for row in freeze["arms"]
    ] == ARMS
    assert freeze["within_run_posthoc_arm_selection"] is False
    assert freeze["budget"] == {
        "max_input_tokens_per_call": 4096,
        "max_output_tokens_per_call": 384,
        "max_relay_bytes": 2048,
        "model_calls": 2,
    }
    for cell, reference in freeze["provider"]["manifest_files"].items():
        manifest = read(Path(reference["path"]))
        assert INDEX[reference["path"]]["sha256"] == reference["sha256"]
        assert digest(manifest) == MODELS[cell]
        assert manifest["parameter_after"] == PARAMETERS[cell]
    memory_raw = raw_read(
        SOURCE
        / "qualification/cell-experiments-v3-20261116/development-old-open.records.jsonl"
    )
    memory = [json.loads(line) for line in memory_raw.splitlines() if line]
    memory = [row for row in memory if row["split"] == "train"]
    assert len(memory) == 6 and all(
        row["authorization"]["training_allowed"] for row in memory
    )
    retrieval = read(RUN / "RETRIEVAL.json")
    assert retrieval["memory_record_digests"] == [digest(row) for row in memory]
    assert (
        retrieval["reference_verifier_calls"]
        == len(retrieval["reference_verifications"])
        == 6
    )
    reference_cost = {
        "verifier_calls": 6,
        "model_calls": 0,
        "business_executions": 0,
        "verifier_wall_seconds": 0.0,
    }
    for record, receipt in zip(
        memory, retrieval["reference_verifications"], strict=True
    ):
        assert business(record, record["final_answer"], receipt)
        reference_cost["business_executions"] += int(receipt["result"]["executed"])
        reference_cost["verifier_wall_seconds"] += (
            receipt["result"].get("wall_ns", 0) / 1e9
        )
    augmented = {}
    retrieval_selection = {}
    for record, selection in zip(records, retrieval["selections"], strict=True):
        words = set(re.findall(r"[a-z_][a-z_0-9]*", record["task"]["input"].lower()))
        ranked = []
        for row in memory:
            other = set(re.findall(r"[a-z_][a-z_0-9]*", row["task"]["input"].lower()))
            score = len(words & other) * 1_000_000 // max(1, len(words | other))
            ranked.append((-score, digest(row), row))
        negative, identity, row = min(ranked, key=lambda item: item[:2])
        message = {
            "role": "tool",
            "content": canonical(
                {
                    "schema": "hepta.training-reference.v1",
                    "instruction": "This is a different previously verified training task. Solve the current task; do not copy its expected values.",
                    "task": row["task"]["input"],
                    "answer": row["final_answer"],
                }
            ).decode(),
        }
        assert len(message["content"].encode()) <= 4096
        current = copy.deepcopy(record)
        current["task"].setdefault(
            "messages", [{"role": "user", "content": record["task"]["input"]}]
        ).append(message)
        assert selection == {
            "query_record_digest": digest(record),
            "memory_record_digest": identity,
            "message_sha256": digest(message),
            "augmented_record_digest": digest(current),
            "lexical_score_millionths": -negative,
        }
        augmented[record["record_id"]] = current
        retrieval_selection[record["record_id"]] = {
            "memory_record_id": row["record_id"],
            "memory_record_digest": identity,
            "reference_answer": row["final_answer"],
        }
    expected_order = [
        (record["task_id"], name) for record in records for name, _ in ARMS
    ]
    assert [
        (row["task_id"], row["arm"]) for row in report["outcomes"]
    ] == expected_order
    summaries = {
        name: {
            "tasks": 0,
            "first": 0,
            "last": 0,
            "selected": 0,
            "recoveries": 0,
            "regressions": 0,
            "cost": cost(),
        }
        for name, _ in ARMS
    }
    calls, tasks, total = [], [], cost()
    previous_completed = frozen_ns
    for record in records:
        for arm, route in ARMS:
            original = (
                augmented[record["record_id"]] if arm.endswith("_retrieval") else record
            )
            folder = RUN / "B2_exposed_followup" / record["record_id"] / arm
            contract, result = (
                read(folder / "CONTRACT.json"),
                read(folder / "RESULT.json"),
            )
            assert (
                contract["graph"]["path"] == list(route)
                and contract["graph"]["graph_id"] == arm
            )
            assert (
                contract["budget"] == freeze["budget"]
                and contract["cells"] == freeze["provider"]["cells"]
            )
            assert result["record_digest"] == digest(original) and result[
                "contract_digest"
            ] == digest(contract)
            assert result["status"] == "COMPLETE" and len(result["nodes"]) == 2
            outputs, receipts = [], []
            task_cost = cost()
            for slot, cell in enumerate(route):
                node_dir = folder / f"node-{slot}"
                request, output, receipt, step = [
                    read(node_dir / name)
                    for name in [
                        "REQUEST.json",
                        "OUTPUT.json",
                        "VERIFICATION.json",
                        "STEP.json",
                    ]
                ]
                assert result["nodes"][slot] == step
                assert (
                    step["slot"] == slot
                    and step["cell_id"] == cell
                    and step["status"] == "COMPLETE"
                )
                assert step["request_digest"] == digest(request) and step[
                    "output_digest"
                ] == digest(output)
                assert (
                    step["verification_digest"] == digest(receipt)
                    and step["output"] == output
                    and step["verification"] == receipt
                )
                assert read(node_dir / "POOL_REQUEST.json") == request
                assert read(node_dir / "POOL_RESULT.json") == output
                raw = read(node_dir / "POOL_RAW_OUTPUT.json")
                assert all(output[key] == value for key, value in raw.items())
                intent = read(node_dir / "POOL_INTENT.json")
                assert (
                    intent["cell_id"] == cell and intent["model_digest"] == MODELS[cell]
                )
                assert (
                    intent["request_digest"] == digest(request)
                    and intent["automatic_retry"] is False
                )
                assert (
                    request["record_id"] == record["record_id"]
                    and request["task"]["input"] == record["task"]["input"]
                )
                output_identity(output, cell, request, frozen_ns)
                assert previous_completed < output["started_at_ns"]
                previous_completed = output["completed_at_ns"]
                assert output["active_adapter_sha256"] == PARAMETERS[cell]
                evidence = output["parameter_source_evidence"]
                assert evidence["actual_normalized_adapter_hash"] == PARAMETERS[cell]
                assert (
                    output["parameter_evidence_digest"]
                    == output["parameter_source_digest"]
                    == digest(evidence)
                )
                assert evidence["adapter_parameters"] == 544768
                assert (
                    output["active_parameters"]
                    == evidence["base_parameters"] + evidence["adapter_parameters"]
                )
                success = business(original, output["answer"], receipt, controls=2)
                assert step["business"]["business_success"] == success
                assert step["business"]["verifier_executed"] == receipt["result"].get(
                    "executed", False
                )
                if slot == 0:
                    assert request == visible(original)
                    assert step["incoming_edges"] == []
                else:
                    initial = visible(original)["task"]["messages"]
                    messages = request["task"]["messages"]
                    assert messages[: len(initial)] == initial
                    relayed = messages[len(initial) :]
                    has_answer = arm != "PC_no_answer"
                    has_feedback = arm != "PC_no_feedback"
                    assert len(relayed) == 1 + int(has_answer)
                    assert step["incoming_edges"] == (
                        ["answer", "feedback"]
                        if has_answer and has_feedback
                        else ["answer"]
                        if has_answer
                        else ["feedback"]
                    )
                    if has_answer:
                        assert relayed[0] == {
                            "role": "assistant",
                            "content": outputs[0]["answer"],
                        }
                    assert relayed[-1]["role"] == "tool"
                    message = json.loads(relayed[-1]["content"])
                    if has_feedback:
                        assert (
                            message["schema"] == "hepta.stable-repository-feedback.v1"
                        )
                        assert message["success"] == receipts[0]["success"]
                        assert message["reason"] == receipts[0]["result"]["reason"]
                        assert message["execution_performed"] == receipts[0][
                            "result"
                        ].get("executed", False)
                        assert message["next_attempt_resets_template"] is True
                    else:
                        assert message == {
                            "schema": "hepta.circuit-feedback-omitted.v1",
                            "instruction": "Continue the original task and return the required complete JSON edit.",
                        }
                    assert sum(len(row["content"].encode()) for row in relayed) <= 2048
                for key in ("input_tokens", "output_tokens"):
                    assert step["cost"][key] == output[key]
                for target in (task_cost, summaries[arm]["cost"], total):
                    add(target, output, receipt)
                calls.append(
                    {
                        "task": record["record_id"],
                        "arm": arm,
                        "slot": slot,
                        "cell": cell,
                        "success": success,
                        "request_sha256": INDEX[str(node_dir / "REQUEST.json")][
                            "sha256"
                        ],
                        "output_sha256": INDEX[str(node_dir / "OUTPUT.json")]["sha256"],
                        "verification_sha256": INDEX[
                            str(node_dir / "VERIFICATION.json")
                        ]["sha256"],
                        "input_tokens": output["input_tokens"],
                        "output_tokens": output["output_tokens"],
                        "generation_wall_seconds": output["wall_seconds"],
                        "verifier_wall_seconds": receipt["result"].get("wall_ns", 0)
                        / 1e9,
                        "business_executed": receipt["result"].get("executed", False),
                        "reason": receipt["result"]["reason"],
                        "started_at_ns": output["started_at_ns"],
                        "completed_at_ns": output["completed_at_ns"],
                        "active_parameter_sha256": output["active_adapter_sha256"],
                    }
                )
                outputs.append(output)
                receipts.append(receipt)
            first, last = [row["success"] for row in receipts]
            selected = first or last
            selected_slot = 0 if first else 1
            assert (
                result["first_success"] == first
                and result["success"] == selected
                and result["final_slot"] == selected_slot
            )
            assert result["last_executed_slot"] == 1
            assert result["final_answer_sha256"] == sha(
                outputs[selected_slot]["answer"].encode()
            )
            for key in report["cost"]:
                assert result["cost"][key] == task_cost[key]
            summary_row = next(
                row
                for row in report["outcomes"]
                if row["task_id"] == record["task_id"] and row["arm"] == arm
            )
            assert summary_row["result_digest"] == digest(result)
            assert (
                summary_row["first_success"] == first
                and summary_row["last_success"] == last
                and summary_row["success"] == selected
            )
            summary = summaries[arm]
            summary["tasks"] += 1
            summary["first"] += first
            summary["last"] += last
            summary["selected"] += selected
            summary["recoveries"] += not first and last
            summary["regressions"] += first and not last
            tasks.append(
                {
                    "record_id": record["record_id"],
                    "arm": arm,
                    "first": first,
                    "last": last,
                    "selected": selected,
                    "selected_slot": selected_slot,
                    "answers": [row["answer"] for row in outputs],
                    "reasons": [row["result"]["reason"] for row in receipts],
                    "original_call_observations": [
                        [
                            o
                            for o in row["result"]
                            .get("result", {})
                            .get("observations", [])
                            if o["control"] == "original"
                        ]
                        for row in receipts
                    ],
                }
            )
    assert len(calls) == 108 and len(tasks) == 54
    assert (
        len(list((RUN / "B2_exposed_followup").glob("*/*/node-*/OUTPUT.json"))) == 108
    )
    for key in report["cost"]:
        assert report["cost"][key] == total[key], key
    assert (
        report["provider_exit"]["complete_outputs_retained"]
        == report["provider_exit"]["generation_requests_dispatched"]
        == 108
    )
    assert (
        report["provider_exit"]["returncode"] == 0
        and report["provider_close"]["source_inventory_unchanged"]
    )
    original_verifier_path = Path(
        "/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/candidate-qwen-03/scripts/cell_experiments/repo_execution.py"
    )
    original_verifier = (
        "ee37e28567944ab542a21926f66957cf663c0ec7e7ceab62a4c30da5fce4282b"
    )
    assert sha(raw_read(original_verifier_path)) == original_verifier
    assert (
        source_freeze["files"]["scripts/cell_experiments/repo_execution.py"] == VERIFIER
    )
    calibration_dir = RUN / "A_SETUP_CALIBRATION"
    inputs_path = Path(
        "/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-sft-02/INPUTS.json"
    )
    inputs_raw = raw_read(inputs_path)
    assert (
        sha(inputs_raw)
        == "691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3"
    )
    calibration_record = json.loads(inputs_raw)["records"][0]
    calibration_request = visible(calibration_record)
    calibration = read(calibration_dir / "RESULT.json")
    assert calibration["calibration_verifier_source_sha256"] == original_verifier
    assert freeze["provider"]["matched_setup_calibration"] == calibration
    setup_cost = cost()
    setup_completed = []
    for cell in MODELS:
        cold, identity = (
            read(calibration_dir / f"{cell}_COLD_OUTPUT.json"),
            read(calibration_dir / f"{cell}_COLD_IDENTITY.json"),
        )
        pooled = read(calibration_dir / f"{cell}_POOL/POOL_RESULT.json")
        assert (
            identity["model_digest"] == MODELS[cell]
            and identity["actual_parameter_sha256"] == PARAMETERS[cell]
        )
        assert identity["adapter_parameters"] == 544768
        assert pooled["active_adapter_sha256"] == PARAMETERS[cell]
        for key in (
            "answer",
            "output_token_ids",
            "loaded_model_digest",
            "generation_config_sha256",
            "rendered_prompt_sha256",
            "messages_sha256",
        ):
            assert cold[key] == pooled[key]
        pair = calibration["pairs"][cell]
        assert pair["cold_output_digest"] == digest(cold) and pair[
            "pool_output_digest"
        ] == digest(pooled)
        assert pair["active_adapter_sha256"] == PARAMETERS[cell] and pair["equal"]
        for output, receipt_path in (
            (cold, calibration_dir / f"{cell}_COLD_VERIFICATION.json"),
            (pooled, calibration_dir / f"{cell}_POOL/VERIFICATION.json"),
        ):
            output_identity(output, cell, calibration_request, frozen_ns)
            receipt = read(receipt_path)
            business(
                calibration_record,
                output["answer"],
                receipt,
                controls=2,
                verifier_source=original_verifier,
            )
            add(setup_cost, output, receipt)
            setup_completed.append(output["completed_at_ns"])
    assert max(setup_completed) < calls[0]["started_at_ns"]
    assert setup_cost["model_calls"] == setup_cost["verifier_calls"] == 4
    assert setup_cost["input_tokens"] == calibration["input_tokens"]
    assert setup_cost["output_tokens"] == calibration["output_tokens"]
    owner = read(ROOT / "owned-run-1/EXIT.json")
    complete = read(ROOT / "owned-run-1/COMPLETE.json")
    assert (
        owner["wait_returncode"] == 0
        and not owner["timed_out"]
        and not owner["automatic_retry"]
    )
    assert (
        complete["actual_child_exit_sha256"]
        == INDEX[str(ROOT / "owned-run-1/EXIT.json")]["sha256"]
    )
    assert (
        complete["primary_result_sha256"] == INDEX[str(RUN / "RESULT.json")]["sha256"]
    )
    assert (
        complete["setup_result_sha256"]
        == INDEX[str(calibration_dir / "RESULT.json")]["sha256"]
    )
    assert (
        complete["model_calls"]
        == total["model_calls"] + setup_cost["model_calls"]
        == 112
    )
    assert (
        complete["verifier_calls"]
        == total["verifier_calls"]
        + setup_cost["verifier_calls"]
        + reference_cost["verifier_calls"]
        == 118
    )
    audit = {
        "schema": "hepta.parent-credit-circuit-readout.v1",
        "status": "AUDIT_PASS",
        "execution_source_commit": source_freeze["source_commit"],
        "execution_source_tree": source_freeze["source_tree"],
        "created_at_ns": time.time_ns(),
        "source_freeze_sha256": INDEX[str(ROOT / "SOURCE_FREEZE.json")]["sha256"],
        "models": MODELS,
        "actual_loaded_parameter_sha256": PARAMETERS,
        "main": summaries,
        "main_cost": total,
        "calibration_cost": setup_cost,
        "reference_preparation_cost": reference_cost,
        "actual_owner_exit": owner,
        "pool_initialization_cost": report["pool_initialization_cost"],
        "retained_retrieval_selections": retrieval_selection,
        "total_model_calls": 112,
        "total_verifier_calls": 118,
        "extra_audit_model_calls": 0,
        "extra_audit_verifier_calls": 0,
        "verifier_sources_by_scope": {
            "main_and_A_references": VERIFIER,
            "A_calibration": original_verifier,
        },
        "prior_audit_failure": "export-complete-1 checked retained-core A calibration with the newer main verifier hash; export-complete-2 checked the old hash against the training-source path instead of the actual retained provider core. Both source/error/log originals are retained. The corrected checker binds main and calibration to their exact predeclared provider paths and raw source hashes, with no result or call changes.",
        "input_tokens_audit_scope": "original measured per-call input counts checked against bound requests and caps; output counts independently equal retained token-ID lengths",
        "scientific_confirmation_qualified": False,
        "native_owner_adoption": False,
        "full_system_cost_known": False,
        "energy_joules": None,
        "monetary_cost": None,
        "limits": [
            "B2 is exposed development in this follow-up, not new confirmation.",
            "Fixed two-call and tool caps; actual input/output tokens differ.",
            "Parent and its A-trained credit continuation have different training histories, not independent teachers.",
            "Retrieval uses only six prior Hepta A records; all six B2 queries retrieve A-counter.",
            "first_true success uses the predeclared two controls; Python bool equals int, so this is not broad semantic coverage.",
            "No native HIA/Circuit execution, owner adoption, user growth or settlement eligibility follows from these receipts.",
            "Timing scopes are nested; owner wall and children CPU must not be added to their inner model/verifier timings.",
        ],
    }
    write("READOUT.json", audit)
    write("CALLS.json", calls)
    write("TASKS.json", tasks)
    write("INPUT_INDEX.json", INDEX)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "summary": summaries,
                "main_cost": total,
                "calibration_cost": setup_cost,
                "reference_cost": reference_cost,
                "readout_sha256": sha((DEST / "READOUT.json").read_bytes()),
                "input_count": len(INDEX),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        write(
            "AUDIT_FAILURE.json",
            {
                "type": type(error).__name__,
                "message": str(error),
                "at_ns": time.time_ns(),
                "original_run_unchanged": True,
            },
        )
        raise
