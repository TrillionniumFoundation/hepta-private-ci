"""Prepare and audit one default-build current-owner decoder qualification.

The workflow runs Rust through `just test` between these two phases. This
driver never trains, launches Rust, retries a decoder, or supplies an answer.
"""

import argparse
import json
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_backend import file_set, file_sha, inspect
from native_ci_support import identity
from native_tick_contract import validate_tick_binding
from native_trial import retain


def source_identity(repo):
    source = identity(repo)
    source["current_ndu_owner_files"] = file_set(
        repo, (repo / "codex-rs/hepta-ndu").rglob("*.rs")
    )
    return source


def frozen_inputs(native, shadow, checkpoint):
    return {
        "native": file_set(native, (p for p in native.rglob("*") if p.is_file())),
        "controlled_shadow": file_set(
            shadow, (p for p in shadow.rglob("*") if p.is_file())
        ),
        "checkpoint": file_set(
            checkpoint, (p for p in checkpoint.rglob("*") if p.is_file())
        ),
    }


def prepare(args):
    repo = args.repo.resolve(strict=True)
    native, shadow = (
        args.native_run.resolve(strict=True),
        args.shadow_run.resolve(strict=True),
    )
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = source_identity(repo)
    if source["head"] != args.expected_head:
        raise ValueError(
            "current-owner qualification requires its exact committed source"
        )
    retain(args.out / "source-before.json", source)
    original = json.loads((native / "report.json").read_text())
    controlled = json.loads((shadow / "report.json").read_text())
    config = json.loads((shadow / "shadow_config.json").read_text())
    protocol = json.loads((native / "trial/protocol.json").read_text())
    training = json.loads((native / "trial/training.json").read_text())
    if (
        not original["engineering_pass"]
        or not controlled["engineering_pass"]
        or original["source_head"] != args.expected_head
        or controlled["source_head"] != args.expected_head
        or protocol["steps"] != 96
        or protocol["rank"] != 8
        or protocol["seed"] != 24031
        or protocol["learning_rate"] != 0.01
        or protocol["objective"] != "completion_ce"
        or training["receipt"]["steps"] != 96
        or len(training["receipt"]["schedule_indices"]) != 96
        or controlled["actual_total_decoder_queries_including_original_v1"] != 4
        or controlled["actual_total_native_feature_forwards_including_original_v1"] != 2
        or config["output_width"] != 5
        or Path(config["python"]).resolve() != Path(sys.executable).resolve()
        or Path(config["repo"]).resolve() != repo
    ):
        raise ValueError(
            "completed fixed v1 and controlled v2 qualifications are required"
        )
    checkpoint = Path(config["checkpoint"]).resolve(strict=True)
    pins, inspected = inspect(repo, config["model"], checkpoint)
    if pins != config["pins"]:
        raise ValueError("pretrained shadow pins differ from the current runtime")
    document = native / "trial/source_document.json"
    if inspected["lineage"]["roots"] != [file_sha(document)]:
        raise ValueError("current source must preserve the trained single-root bytes")
    current = {
        **config,
        "config_id": "memory-cell:current-owner-pretrained-v1",
        "receipt_directory": str(args.out.resolve() / "execution"),
    }
    retain(args.out / "model_config.json", current)
    retain(
        args.out / "registration.json",
        {
            "schema": "hepta.memory-cell.current-factory-registration.v1",
            "expected_head": args.expected_head,
            "original_shadow_config": config,
            "current_config": current,
            "source_document": str(document),
            "frozen_inputs": frozen_inputs(native, shadow, checkpoint),
            "extra_training_updates": 0,
            "new_decoder_queries_planned": 1,
            "default_daemon_process_exercised": False,
            "production_qualified": False,
        },
    )


def finish(args):
    repo = args.repo.resolve(strict=True)
    native, shadow = (
        args.native_run.resolve(strict=True),
        args.shadow_run.resolve(strict=True),
    )
    registered = json.loads((args.out / "registration.json").read_text())
    config = registered["current_config"]
    if json.loads((args.out / "model_config.json").read_text()) != config:
        raise ValueError("current factory configuration changed")
    checkpoint = Path(config["checkpoint"]).resolve(strict=True)
    before = json.loads((args.out / "source-before.json").read_text())
    after = source_identity(repo)
    if before != after or after["head"] != args.expected_head:
        raise ValueError("qualified source changed")
    frozen = frozen_inputs(native, shadow, checkpoint)
    if (
        frozen != registered["frozen_inputs"]
        or inspect(repo, config["model"], checkpoint)[0] != config["pins"]
    ):
        raise ValueError("original controls, weights or registered runtime changed")
    execution_root = Path(config["receipt_directory"])
    result = json.loads((execution_root / "current-factory-report.json").read_text())
    worker = execution_root / result["execution"]["request_sha256"]
    if sorted(path for path in execution_root.iterdir() if path.is_dir()) != [worker]:
        raise ValueError(
            "exactly one independently retained worker directory is required"
        )
    raw_execution = json.loads((worker / "stdout.json").read_text())
    request = json.loads((worker / "request.json").read_text())
    process = json.loads((worker / "process.json").read_text())
    validate_tick_binding(request)
    if (
        raw_execution != result["execution"]
        or file_sha(worker / "request.json") != raw_execution["request_sha256"]
        or request["schema"] != "hepta.memory-cell.native-request.v2"
        or request["pins"] != config["pins"]
        or request["source_root"] != result["source_document_sha256"]
        or request["query_digest"] != raw_execution["query_digest"]
        or request["source_binding_digest"] != raw_execution["source_binding_digest"]
        or raw_execution["decoder_queries"] != 1
        or raw_execution["feature_forward_calls"] != 1
        or process["exit_code"] != 0
        or process["timed_out"] is not False
        or process["owner_cancelled"] is not False
        or process["stdin_completed"] is not True
        or process["stdout_bytes"] != (worker / "stdout.json").stat().st_size
        or process["stderr_bytes"] != (worker / "stderr.log").stat().st_size
    ):
        raise ValueError("raw worker request, execution or process evidence differs")
    if (
        not result["engineering_pass"]
        or not result["actual_current_owner_factory"]
        or not result["exact_query_substitution_refused"]
        or not result["cancelled_runtime_delivery_refused"]
        or result["actual_decoder_queries"] != 1
        or result["actual_feature_forward_calls"] != 1
        or result["completed_worker_processes"] != 1
        or result["extra_training_updates"] != 0
        or result["production_qualified"]
        or result["default_daemon_process_exercised"]
        or result["source_document_sha256"]
        != file_sha(Path(registered["source_document"]))
        or result["configuration_sha256"] != file_sha(args.out / "model_config.json")
    ):
        raise ValueError(
            "actual default factory execution or evidence boundary differs"
        )
    retain(args.out / "source-after.json", after)
    retain(args.out / "frozen-after.json", frozen)
    retain(
        args.out / "report.json",
        {
            "schema": "hepta.memory-cell.current-factory-driver.v1",
            "engineering_pass": True,
            "source_head": after["head"],
            "execution": result,
            "training_updates_reused": 96,
            "training_updates_added": 0,
            "new_decoder_queries": 1,
            "new_feature_forwards": 1,
            "total_decoder_queries_including_prior_v1_v2": 5,
            "total_feature_forwards_including_prior_v1_v2": 3,
            "independent_future_tasks": 0,
            "future_accuracy": None,
            "production_qualified": False,
            "default_daemon_process_exercised": False,
            "authority_and_clock": "explicit test-controlled real durable owners",
            "automatic_retry": False,
            "retained_execution_files": file_set(
                execution_root, (p for p in execution_root.rglob("*") if p.is_file())
            ),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "finish"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--native-run", type=Path, required=True)
    parser.add_argument("--shadow-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    arguments = parser.parse_args()
    try:
        globals()[arguments.phase](arguments)
    except BaseException as error:
        if arguments.out.is_dir():
            retain(
                arguments.out / (arguments.phase + "-failure.json"),
                {
                    "error": f"{type(error).__name__}: {error}",
                    "traceback": traceback.format_exc(),
                    "engineering_pass": False,
                    "production_qualified": False,
                },
            )
        raise
