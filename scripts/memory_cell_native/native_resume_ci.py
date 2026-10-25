"""Explicit one-attempt continuation of the retained pre-decoder native failure.

Never trains, acquires weights, builds Rust, or edits the failed run. A new owner
and new receipt namespace consume a byte-identical copy of the frozen training
artifacts. This is a continuation, not an independent fresh-training replication.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_backend import file_sha, inspect
from native_ci import summarize
from native_ci_support import command, identity, model_environment, SOURCE_PATHS
from native_resume_support import admit, inventory, MUTABLE_PINS
from native_trial import retain


def execute(args):
    started = time.monotonic()
    repo = Path(args.repo).resolve(strict=True)
    binary = Path(args.binary).resolve(strict=True)
    failed = Path(args.failed_native_run).resolve(strict=True)
    output = Path(args.out).resolve()
    before = identity(repo)
    if before["head"] != args.expected_head:
        raise ValueError("explicit continuation source commit differs")
    admission = admit(failed, output, repo)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    run = output / "trial"
    failure = None
    report = None
    copied = None
    binary_sha256 = file_sha(binary)
    retain(output / "source-before.json", before)
    retain(output / "frozen-before.json", admission["frozen"])
    retain(output / "invocation.json", {
        "argv": sys.argv, "python": sys.executable, "binary_sha256": binary_sha256,
        "expected_head": args.expected_head, "failed_native_run": str(failed),
        "training_updates_added": 0, "model_acquisition_bytes_added": 0,
    })
    original = admission["original"]
    try:
        command(output, "source-archive", ["git", "archive", "--format=tar.gz",
                f"--output={output / 'executed-source.tar.gz'}", "HEAD", *SOURCE_PATHS],
                cwd=repo, timeout=120)
        run.mkdir(mode=0o700)
        excluded = {"native_config.json", "native_inspection.json", "native-process-receipts"}
        for path in (failed / "trial").iterdir():
            if path.name in excluded:
                continue
            if path.is_dir():
                shutil.copytree(path, run / path.name)
            else:
                shutil.copy2(path, run / path.name)
        copied = inventory(run)
        expected_copy = {name: row for name, row in inventory(failed / "trial").items()
                         if name == "." or Path(name).parts[0] not in excluded}
        if copied != expected_copy:
            raise ValueError("copied source, recipe, training or checkpoint bytes differ")
        receipts = run / "native-process-receipts"
        receipts.mkdir(mode=0o700)
        checkpoint = run / "checkpoint"
        pins, inspection = inspect(repo, original["model"], checkpoint)
        if pins != admission["pins"]:
            raise ValueError("copied checkpoint registration differs")
        config = {**original, "repo": str(repo), "checkpoint": str(checkpoint),
                  "receipt_directory": str(receipts), "pins": pins}
        retain(run / "native_config.json", config)
        retain(run / "native_inspection.json", inspection)
        retain(output / "checkpoint-before.json", {
            p.name: file_sha(p) for p in checkpoint.iterdir() if p.is_file()})
        retain(output / "registration.json", {
            "schema": "hepta.memory-cell.explicit-resume-registration.v1",
            "original_config": original, "resumed_config": config,
            "config_changes": {key: {"before": original[key], "after": config[key]}
                               for key in original if original[key] != config[key]},
            "pin_changes": {key: {"before": original["pins"][key], "after": pins[key]}
                            for key in pins if original["pins"][key] != pins[key]},
            "allowed_reregistration_pins": sorted(MUTABLE_PINS),
            "original_config_sha256": admission["original_sha256s"]["trial/native_config.json"],
            "original_failure_sha256": admission["original_sha256s"]["failure.json"],
            "original_failed_source_head": admission["source"]["head"],
            "training_updates_added": 0, "training_updates_reused": 96,
            "model_acquisition_bytes_added": 0, "original_native_decoder_queries": 0,
            "original_native_feature_forwards": 0, "original_control_queries": 0,
            "copied_inputs_before": copied, "inspection": inspection,
            "production_qualified": False,
        })
        owner = output / "native-owner"
        environment = model_environment()
        command(output, "prepare-owner", [binary, "prepare", owner], cwd=repo,
                timeout=120, environment=environment)
        anchor = json.loads((owner / "prepare.json").read_text())["anchor_sha256"]
        if anchor != file_sha(owner / "anchor.json"):
            raise ValueError("independently retained new owner anchor differs")
        command(output, "daemon-probe", [binary, "run", owner, run / "native_config.json",
                run / "source_document.json", anchor], cwd=repo,
                timeout=420, environment=environment)
        for control in ("base", "shuffled"):
            command(output, f"control-{control}", [sys.executable, "-I", "-B",
                    repo / "scripts/memory_cell_network/model_child.py", "--parent-pid",
                    os.getpid(), repo / "scripts/memory_cell_native/native_controls.py",
                    run, control], cwd=repo, timeout=600, environment=environment)
        report = summarize(output, started)
        process_paths = list(receipts.glob("*/process.json"))
        if len(process_paths) != 1 or report["engineering"]["backend_dispatch_attempts"] != 1:
            raise ValueError("exactly one actual native worker process is required")
        processes = {}
        for kind, path in [("native", process_paths[0]), *[
                (control, output / "commands" / f"control-{control}" / "receipt.json")
                for control in ("base", "shuffled")]]:
            process = json.loads(path.read_text())
            bootstrap = json.loads((path.parent / "stderr.log").read_text().splitlines()[0])
            if (process["exit_code"] != 0 or process["timed_out"]
                    or bootstrap["schema"] != "hepta.memory-process.started.v1"
                    or process["pid"] != bootstrap["pid"]):
                raise ValueError("actual model-child completion and bootstrap differ")
            processes[kind] = {"process": process, "bootstrap": bootstrap}
        if len({row["process"]["pid"] for row in processes.values()}) != 3:
            raise ValueError("native/base/shuffled must execute in three fresh processes")
        report.update(actual_model_child_processes_added=len(processes), model_processes=processes)
    except BaseException as error:
        failure = {"error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()}
    try:
        after = {"failed_run": inventory(failed), "model": inventory(admission["model"])}
        retain(output / "frozen-after.json", after)
        if after != admission["frozen"]:
            raise ValueError("original failed run or base changed during continuation")
        if copied is not None:
            copied_after = {name: row for name, row in inventory(run).items()
                            if name == "." or Path(name).parts[0] not in excluded}
            retain(output / "copied-inputs-after.json", copied_after)
            if copied_after != copied:
                raise ValueError("copied immutable inputs changed during continuation")
        after_source = identity(repo)
        retain(output / "source-after.json", after_source)
        if (before != after_source or file_sha(binary) != binary_sha256
                or inspect(repo, original["model"], admission["checkpoint"])[0] != admission["pins"]):
            raise ValueError("source, runtime registration or original checkpoint changed")
    except BaseException as error:
        failure = {**(failure or {}), "frozen_verification_error": f"{type(error).__name__}: {error}",
                   "frozen_verification_traceback": traceback.format_exc()}
    provenance = {
        "schema": "hepta.memory-cell.explicit-native-continuation.v1",
        "failed_native_run": str(failed), "original_failed_source_head": admission["source"]["head"],
        "original_failure_sha256": admission["original_sha256s"]["failure.json"],
        "original_training_sha256": admission["original_sha256s"]["trial/training.json"],
        "training_source_head": admission["source"]["head"],
        "training_updates_added": 0, "training_updates_reused": 96,
        "training_model_forwards_added": 0, "training_model_forwards_reused": 96,
        "model_acquisition_bytes_added": 0, "model_acquisition_attempts_added": 0,
        "original_failure": admission["failure"], "original_commands": admission["commands"],
        "original_acquisition": admission["acquisition"],
        "original_training_receipt": admission["training"],
        "original_decoder_queries": 0, "original_native_feature_forwards": 0,
        "cost_scope": "new commands are continuation-only; original failure wall already includes original acquisition and training",
        "wall_seconds": time.monotonic() - started,
        "automatic_retry": False, "independent_training_replication": False,
        "production_qualified": False, "confirmation": False,
    }
    retain(output / "continuation.json", provenance)
    if failure is not None:
        retain(output / "failure.json", {
            **failure, **provenance, "actual_completed_decoder_queries": None,
            "actual_completed_native_feature_forwards": None,
            "partial_process_receipts_retained": True,
            "partial_execution_locations": [str(run / "native-process-receipts"),
                                             str(output / "commands"), str(output / "native-owner")],
        })
        raise RuntimeError(f"explicit continuation failed; retained evidence: {output}")
    report.update({
        "schema": "hepta.memory-cell.native-explicit-resume-development.v1",
        "continuation": provenance, "training_updates_added": 0, "training_updates_reused": 96,
        "training_source_head": admission["source"]["head"],
        "model_acquisition_bytes_added": 0, "automatic_retry": False,
        "wall_seconds": time.monotonic() - started,
        "original_failed_run_wall_seconds": admission["failure"]["wall_seconds"],
        "combined_original_and_resume_wall_seconds": admission["failure"]["wall_seconds"] + time.monotonic() - started,
    })
    retain(output / "report.json", report)
    print(json.dumps(report, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("failed-native-run", "out", "repo", "binary", "expected-head"):
        parser.add_argument(f"--{name}", required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
