"""Freeze actual full-length calibration before either fresh training process."""

import time

import layout_context as ctx


def collect():
    protocol_path = ctx.HERE / "prepared/PROTOCOL.json"
    protocol = ctx.read(protocol_path)
    for name, expected in protocol["candidate_files"].items():
        if ctx.sha(ctx.HERE / name) != expected:
            raise ValueError("full gate source/data changed: " + name)
    folder = ctx.WORK / "retained/calibration"
    owned = ctx.WORK / "owned-calibration_only-1"
    result = ctx.read(folder / "RESULT.json")
    actual_exit = ctx.read(owned / "calibration/EXIT.json")
    started = ctx.read(folder / "STARTED.json")
    engine = ctx.read(folder / "TRAINING_ENGINE.json")
    if (
        result["status"] != "PASS"
        or result["optimizer_updates"] != 0
        or result["model_generation_calls"] != 0
        or result["parameter_before"] != protocol["parent_parameter_digest"]
        or result["parameter_after"] != protocol["parent_parameter_digest"]
        or actual_exit["wait_returncode"] != 0
        or actual_exit["timed_out"]
        or started["freeze_digest"] != ctx.data.digest(protocol)
        or engine["engine"] != "eager_checkpointed_softmax"
    ):
        raise ValueError("actual complete full-length gate required")
    modes = ("document_evidence", "native_feedback")
    if [row["mode"] for row in result["rows"]] != list(modes):
        raise ValueError("both actual layout calibrations required")
    for row in result["rows"]:
        if (
            row["model_forwards"] != 5
            or row["model_backwards"] != 5
            or row["supervised_positions"] != 1196
            or row["padded_positions"] != 5 * 3584
        ):
            raise ValueError("maximum full group shape differs")
        counts = row["inner_checkpoint_counts"]
        if (
            counts["forward:attention_function_started"] != 5 * 28
            or counts["forward:attention_function_completed"] != 5 * 28
            or counts["forward:softmax_original_entered"] != 5 * 28 * 28
            or counts["backward:softmax_recompute_entered"] <= 0
        ):
            raise ValueError("real inner checkpoint mechanism not observed")
    if (
        result["rows"][0]["inner_checkpoint_counts"]
        != result["rows"][1]["inner_checkpoint_counts"]
    ):
        raise ValueError("full calibration recomputation shapes differ")
    paths = [
        folder / name
        for name in (
            "RESULT.json",
            "STARTED.json",
            "MODEL_LOADED.json",
            "ALLOCATOR.json",
            "TRAINING_ENGINE.json",
            "COMPUTE.jsonl",
        )
    ] + [
        owned / "calibration/EXIT.json",
        owned / "calibration/STDERR.txt",
        owned / "calibration/STDOUT.txt",
        owned / "INTENT.json",
        ctx.WORK / "DEPLOYMENT.json",
    ]
    return {
        "schema": "hepta.upstream-layout-real-training-admission.v1",
        "status": "ACTUAL_FULL_GATE_PASSED",
        "protocol_sha256": ctx.sha(protocol_path),
        "calibration_source_commit": ctx.read(ctx.WORK / "DEPLOYMENT.json")[
            "source_commit"
        ],
        "parent_parameter_digest": protocol["parent_parameter_digest"],
        "actual_files": {str(path): ctx.sha(path) for path in paths},
        "full_gate_result": result,
        "next_fit_updates_per_arm": 32,
        "fit_initialization": "separate child processes, cold same P, fresh empty AdamW",
        "physical_cost_equal_to_old_eager": False,
        "B3_materials_read": False,
    }


def verify_admission():
    path = ctx.WORK / "TRAINING_ADMISSION.json"
    admission = ctx.read(path)
    created = admission.pop("created_at_ns")
    if not isinstance(created, int) or created <= 0 or admission != collect():
        raise ValueError("prospectively published actual training admission differs")
    return ctx.sha(path)


if __name__ == "__main__":
    value = {"created_at_ns": time.time_ns(), **collect()}
    ctx.write(ctx.WORK / "TRAINING_ADMISSION.json", value)
    print(ctx.data.canonical(value).decode(), flush=True)
