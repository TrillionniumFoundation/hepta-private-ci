"""Prepare and audit one actual default-daemon current-owner qualification.

No training, Rust execution, decoder invocation, retry or answer substitution
occurs in this driver. Execute the named Rust test through `just test` between
the phases. A development inventory is explicitly distinct from committed CI.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_backend import file_set, file_sha, inspect
from native_tick_contract import validate_tick_binding
from native_trial import retain


TEST = "pretrained_default_daemon_current_process_delivers_once_then_refuses_revocation"
CRATES = (
    "hepta-agentd",
    "hepta-memory",
    "hepta-ndu",
    "hepta-objective",
    "hepta-contracts",
    "hepta-neuron",
    "hepta-agent-protocol",
    "hepta-cognitive-store",
    "hepta-cognitive-types",
    "hepta-types",
)


def read(path):
    return json.loads(Path(path).read_text())


def source_identity(args):
    repo = args.repo.resolve(strict=True)
    head = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()
    )
    if head != args.expected_head:
        raise ValueError("repository HEAD differs from the declared identity")
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo
        )
    )
    if args.source_profile == "committed" and dirty:
        raise ValueError("committed qualification requires a clean checkout")
    files = [
        repo / "justfile",
        repo / "codex-rs/Cargo.toml",
        repo / "codex-rs/Cargo.lock",
        repo / "codex-rs/rust-toolchain.toml",
        repo / ".github/workflows/hepta-memory-native-process.yml",
        repo / "scripts/memory_cell_native/fixtures/base-acquisition.json",
    ]
    for crate in CRATES:
        root = repo / "codex-rs" / crate
        files.extend(root.rglob("*.rs"))
        files.append(root / "Cargo.toml")
    for package in ("memory_cell", "memory_cell_native"):
        files.extend((repo / "scripts" / package).glob("*.py"))
    files.extend((repo / "scripts/memory_cell_native/current").glob("*.py"))
    files.append(repo / "scripts/memory_cell_network/model_child.py")
    return {
        "head": head,
        "source_profile": args.source_profile,
        "dirty": dirty,
        "files": file_set(repo, files),
        "committed_source_qualified": not dirty,
    }


def frozen_inputs(args, config):
    checkpoint = Path(config["checkpoint"]).resolve(strict=True)
    return {
        "prior_config": file_sha(args.prior_config),
        "source_document": file_sha(args.source_document),
        "protocol": file_sha(args.training_run / "protocol.json"),
        "training": file_sha(args.training_run / "training.json"),
        "checkpoint": file_set(
            checkpoint, (p for p in checkpoint.rglob("*") if p.is_file())
        ),
    }


def prepare(args):
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = source_identity(args)
    retain(args.out / "source-before.json", source)
    prior = read(args.prior_config)
    protocol = read(args.training_run / "protocol.json")
    training = read(args.training_run / "training.json")
    if (
        protocol["steps"],
        protocol["rank"],
        protocol["seed"],
        protocol["learning_rate"],
        protocol["objective"],
    ) != (96, 8, 24031, 0.01, "completion_ce"):
        raise ValueError(
            "only the existing fixed completion-CE checkpoint is registered"
        )
    if (
        training["receipt"]["steps"] != 96
        or len(training["receipt"]["schedule_indices"]) != 96
    ):
        raise ValueError("retained training schedule differs")
    if (
        Path(prior["python"]).resolve() != Path(sys.executable).resolve()
        or Path(prior["repo"]).resolve() != args.repo.resolve()
    ):
        raise ValueError("explicit runtime or repository differs")
    pins, inspection = inspect(args.repo, prior["model"], prior["checkpoint"])
    receipt = training["receipt"]
    if (
        training["manifest_sha256"] != pins["manifest_sha256"]
        or receipt != inspection["lineage"]["training"]
    ):
        raise ValueError("training cost receipt is not joined to the actual checkpoint")
    if (
        receipt["objective"],
        receipt["learning_rate"],
        receipt["writer_seed"],
        receipt["actual_model_forwards"],
    ) != ("completion_ce", 0.01, 24031, 96):
        raise ValueError("actual retained training method or cost differs")
    changed = sorted(key for key in pins if pins[key] != prior["pins"].get(key))
    if changed and (not args.allow_runtime_refresh or changed != ["runtime_digest"]):
        raise ValueError("immutable model/profile pins changed")
    if inspection["lineage"]["roots"] != [file_sha(args.source_document)]:
        raise ValueError("source is not the trained exact single-root document")
    if (prior["rank"], prior["seed"], prior["output_width"]) != (8, 24031, 5):
        raise ValueError("existing decoder profile differs")
    if args.fixture_root.exists():
        raise ValueError("a new actual-process fixture directory is required")
    config = {
        **prior,
        "config_id": "memory-cell:current-default-process-v1",
        "receipt_directory": str(args.out.resolve() / "execution"),
        "pins": pins,
    }
    retain(args.out / "model_config.json", config)
    retain(args.out / "inspection.json", inspection)
    retain(
        args.out / "registration.json",
        {
            "schema": "hepta.memory-cell.default-process-registration.v1",
            "fixture_root": str(args.fixture_root.resolve()),
            "test": TEST,
            "source_document": str(args.source_document.resolve(strict=True)),
            "prior_config": prior,
            "current_config": config,
            "refreshed_pin_fields": changed,
            "frozen_inputs": frozen_inputs(args, prior),
            "training_updates_added": 0,
            "maximum_new_decoder_queries": 1,
            "automatic_retry": False,
            "authority_and_clock": "separate controlled issuer process; local files and Linux system clock",
            "production_qualified": False,
        },
    )


def finish(args):
    registration = read(args.out / "registration.json")
    config = registration["current_config"]
    if read(args.out / "model_config.json") != config or source_identity(args) != read(
        args.out / "source-before.json"
    ):
        raise ValueError("configured source changed during qualification")
    if (
        frozen_inputs(args, registration["prior_config"])
        != registration["frozen_inputs"]
    ):
        raise ValueError("previous training, source or checkpoint changed")
    if inspect(args.repo, config["model"], config["checkpoint"])[0] != config["pins"]:
        raise ValueError("runtime/base/adapter pins changed")
    test = read(args.test_receipt)
    if (
        test["exit_code"] != 0
        or test["source_changed_during_execution"]
        or test["command"][:2] != ["just", "test"]
        or not any(TEST in item for item in test["command"])
    ):
        raise ValueError("actual named just-test execution did not qualify")
    fixture = Path(registration["fixture_root"])
    report = read(fixture / "process-report.json")
    restart = read(fixture / "restart-old-cut.report.json")
    command = read(fixture / "daemon.command.json")
    if (
        not report["engineering_pass"]
        or report["result"]["decoder_queries"] != 1
        or report["result"]["new_training_updates"] != 0
    ):
        raise ValueError("actual process exercise did not qualify")
    result = report["result"]
    if (
        not all(
            result[key] is True
            for key in (
                "actual_default_daemon_process",
                "actual_objective_start",
                "separate_issuer_process",
                "positive_delivery",
                "revocation_refused",
            )
        )
        or result["daemon_pid"] == result["issuer_pid"]
        or result["production_qualified"]
    ):
        raise ValueError("actual process/authority boundary differs")
    if (
        not report["shutdown"]["drain_acknowledged"]
        or report["shutdown"]["exit_code"] != 0
        or report["shutdown"]["sigkill_used"]
    ):
        raise ValueError("owned daemon was not gracefully drained and joined")
    if (
        restart["exit_code"] == 0
        or restart["new_spawn_generation"] != 5
        or not restart["old_authority_cut_rebound_to_current_generation"]
        or "pinned file drift" not in restart["error"]
    ):
        raise ValueError(
            "restart did not independently reject its retained stale authority cut"
        )
    if (
        file_sha(command["program"]) != command["binary_sha256"]
        or not command["default_build"]
    ):
        raise ValueError("actual default daemon binary changed")
    responses = {
        number: read(fixture / f"control-{number:03}.response.json")
        for number in (1, 7, 8, 9, 10, 11)
    }
    if (
        responses[1]["payload"]["daemon_pid"] != result["daemon_pid"]
        or "execution" in responses[7]["payload"]
        or "text" in responses[7]["payload"]
    ):
        raise ValueError("execution answered outside the delivery boundary")
    delivered = responses[8]["payload"]
    execution = delivered["execution"]
    if (
        not delivered["abstain"]
        or delivered["authority_grants_any"]
        or delivered["production_qualified"]
    ):
        raise ValueError("shadow result gained action authority")
    if (
        not responses[9]["ok"]
        or responses[10]["ok"]
        or responses[11]["ok"]
        or "Revoked" not in responses[10]["error"]
    ):
        raise ValueError("post-execution revocation or replay was not refused")
    root = Path(config["receipt_directory"])
    worker = root / execution["request_sha256"]
    if sorted(p for p in root.iterdir() if p.is_dir()) != [worker]:
        raise ValueError("exactly one decoder child is required")
    request, raw, process = (
        read(worker / name) for name in ("request.json", "stdout.json", "process.json")
    )
    validate_tick_binding(request)
    document = read(args.source_document)
    if (
        raw != execution
        or file_sha(worker / "request.json") != execution["request_sha256"]
    ):
        raise ValueError("raw worker response/request identity differs")
    if (
        request["schema"] != "hepta.memory-cell.native-request.v2"
        or request["pins"] != config["pins"]
        or request["source_root"] != file_sha(args.source_document)
    ):
        raise ValueError("actual worker did not use the registered source/runtime")
    if (
        execution["text"].strip() != document["value"]
        or execution["decoder_queries"] != 1
        or execution["feature_forward_calls"] != 1
    ):
        raise ValueError("raw decoder did not satisfy the fixed existing-case check")
    if (
        process["exit_code"] != 0
        or process["timed_out"]
        or process["owner_cancelled"]
        or not process["stdin_completed"]
        or process["stdout_bytes"] != (worker / "stdout.json").stat().st_size
        or process["stderr_bytes"] != (worker / "stderr.log").stat().st_size
    ):
        raise ValueError("retained worker process failed or has inconsistent counters")
    started = json.loads((worker / "stderr.log").read_text().splitlines()[0])
    if (
        process["parent_pid"] != result["daemon_pid"]
        or started["schema"] != "hepta.memory-process.started.v1"
        or started["pid"] != process["pid"]
        or started["parent_pid"] != result["daemon_pid"]
        or started["expected_parent_pid"] != result["daemon_pid"]
    ):
        raise ValueError(
            "raw decoder process is not joined to the actual daemon parent"
        )
    retain(args.out / "source-after.json", source_identity(args))
    retain(
        args.out / "report.json",
        {
            "schema": "hepta.memory-cell.default-process-qualification.v1",
            "engineering_pass": True,
            "source_profile": args.source_profile,
            "source_head": args.expected_head,
            "actual_default_daemon_process_exercised": True,
            "process": report,
            "restart": restart,
            "training_updates_reused": 96,
            "training_updates_added": 0,
            "new_decoder_queries": 1,
            "new_feature_forwards": 1,
            "independent_future_tasks": 0,
            "future_accuracy": None,
            "production_qualified": False,
            "protected_clock_or_frontier_qualified": False,
            "automatic_retry": False,
            "test_receipt_sha256": file_sha(args.test_receipt),
            "binary_sha256": command["binary_sha256"],
            "worker_process": process,
            "fixture_files": file_set(
                fixture, (p for p in fixture.rglob("*") if p.is_file())
            ),
            "execution_files": file_set(
                root, (p for p in root.rglob("*") if p.is_file())
            ),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "finish"))
    for name in (
        "repo",
        "prior-config",
        "training-run",
        "source-document",
        "out",
        "fixture-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--source-profile",
        choices=("committed", "development-inventory"),
        required=True,
    )
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--allow-runtime-refresh", action="store_true")
    parser.add_argument("--test-receipt", type=Path)
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
