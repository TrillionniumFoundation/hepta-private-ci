"""One controlled pretrained v2 shadow qualification using completed v1 weights.

No training, model acquisition, Rust build, retry, or evaluation-driven tuning.
The original v1 config/protocol/controls remain unchanged. A separate profile
registers the current v2 runtime and width-five uncalibrated observations.
"""

import argparse
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_backend import file_set, file_sha, inspect
from native_ci_support import command, identity, model_environment, SOURCE_PATHS
from native_trial import retain


def execute(args):
    repo = Path(args.repo).resolve(strict=True)
    binary = Path(args.binary).resolve(strict=True)
    native = Path(args.native_run).resolve(strict=True)
    trial = native / "trial"
    output = Path(args.out).absolute()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        before = identity(repo)
        if before["head"] != args.expected_head:
            raise ValueError("explicit shadow source commit differs")
        retain(output / "source-before.json", before)
        retain(
            output / "invocation.json",
            {
                "argv": sys.argv,
                "binary_sha256": file_sha(binary),
                "python": sys.executable,
                "expected_head": args.expected_head,
            },
        )
        command(
            output,
            "source-archive",
            [
                "git",
                "archive",
                "--format=tar.gz",
                f"--output={output / 'executed-source.tar.gz'}",
                "HEAD",
                *SOURCE_PATHS,
            ],
            cwd=repo,
            timeout=120,
        )
        protocol = json.loads((trial / "protocol.json").read_text())
        training = json.loads((trial / "training.json").read_text())
        previous = json.loads((native / "report.json").read_text())
        original = json.loads((trial / "native_config.json").read_text())
        if (
            protocol["steps"] != 96
            or protocol["rank"] != 8
            or protocol["seed"] != 24031
            or protocol["learning_rate"] != 0.01
            or protocol["objective"] != "completion_ce"
            or training["receipt"]["steps"] != 96
            or len(training["receipt"]["schedule_indices"]) != 96
            or not previous["engineering_pass"]
            or previous["actual_decoder_queries"] != 3
            or previous["actual_native_feature_forwards"] != 1
        ):
            raise ValueError(
                "completed fixed v1 training and all original controls required"
            )
        if (
            original["output_width"] != 4
            or original["rank"] != 8
            or original["seed"] != 24031
            or Path(original["python"]).resolve() != Path(sys.executable).resolve()
        ):
            raise ValueError("original v1 profile or Python executable differs")
        frozen = file_set(native, (p for p in native.rglob("*") if p.is_file()))
        checkpoint = Path(original["checkpoint"]).resolve(strict=True)
        checkpoint_before = file_set(
            checkpoint, (p for p in checkpoint.rglob("*") if p.is_file())
        )
        pins, inspected = inspect(repo, original["model"], checkpoint)
        immutable = set(pins) - {"runtime_digest", "worker_sha256"}
        if any(pins[key] != original["pins"][key] for key in immutable):
            raise ValueError(
                "weights, lineage, tokenizer, device or decoder identity changed"
            )
        receipts = output / "native-process-receipts"
        receipts.mkdir(mode=0o700)
        shadow = {
            **original,
            "repo": str(repo),
            "pins": pins,
            "output_width": 5,
            "config_id": "memory-cell:controlled-shadow-qualification-v2",
            "receipt_directory": str(receipts),
        }
        config_path = output / "shadow_config.json"
        retain(config_path, shadow)
        retain(
            output / "registration.json",
            {
                "schema": "hepta.memory-cell.controlled-shadow-registration.v1",
                "original_config_path": str(trial / "native_config.json"),
                "original_config_sha256": file_sha(trial / "native_config.json"),
                "original_config": original,
                "shadow_config": shadow,
                "config_changes": {
                    key: {"before": original[key], "after": shadow[key]}
                    for key in original
                    if original[key] != shadow[key]
                },
                "immutable_pin_names": sorted(immutable),
                "training_updates_added": 0,
                "original_v1_report_sha256": file_sha(native / "report.json"),
                "original_v1_source_head": previous["source_head"],
                "checkpoint_before": checkpoint_before,
                "frozen_before": frozen,
                "inspection": inspected,
                "production_qualified": False,
            },
        )
        owner = output / "shadow-owner"
        environment = model_environment()
        command(
            output,
            "prepare-owner",
            [binary, "prepare", owner],
            cwd=repo,
            timeout=120,
            environment=environment,
        )
        anchor = json.loads((owner / "prepare.json").read_text())["anchor_sha256"]
        if anchor != file_sha(owner / "anchor.json"):
            raise ValueError("independently retained source owner cut differs")
        command(
            output,
            "pretrained-shadow",
            [binary, "run", owner, config_path, trial / "source_document.json", anchor],
            cwd=repo,
            timeout=420,
            environment=environment,
        )
        engineering = json.loads((owner / "report.json").read_text())
        execution = json.loads((owner / "raw-execution.json").read_text())
        if (
            not engineering["engineering_pass"]
            or engineering["actual_backend_dispatches"] != 1
            or execution["decoder_queries"] != 1
            or execution["feature_forward_calls"] != 1
            or engineering["production_qualified"]
            or engineering["authority_grants_any"]
        ):
            raise ValueError("actual shadow execution or authority boundary differs")
        after = identity(repo)
        checkpoint_after = file_set(
            checkpoint, (p for p in checkpoint.rglob("*") if p.is_file())
        )
        frozen_after = file_set(native, (p for p in native.rglob("*") if p.is_file()))
        after_pins, _ = inspect(repo, original["model"], checkpoint)
        if (
            before != after
            or checkpoint_before != checkpoint_after
            or frozen != frozen_after
            or pins != after_pins
        ):
            raise ValueError(
                "source, original v1 artifacts, model or checkpoint changed"
            )
        retain(output / "source-after.json", after)
        retain(
            output / "frozen-after.json",
            {"files": frozen_after, "checkpoint": checkpoint_after},
        )
        report = {
            "schema": "hepta.memory-cell.pretrained-shadow-driver.v1",
            "engineering_pass": True,
            "engineering": engineering,
            "source_head": before["head"],
            "original_v1_source_head": previous["source_head"],
            "actual_shadow_decoder_queries": execution["decoder_queries"],
            "actual_shadow_feature_forwards": execution["feature_forward_calls"],
            "actual_total_decoder_queries_including_original_v1": previous[
                "actual_decoder_queries"
            ]
            + execution["decoder_queries"],
            "actual_total_native_feature_forwards_including_original_v1": previous[
                "actual_native_feature_forwards"
            ]
            + execution["feature_forward_calls"],
            "training_updates_reused": training["receipt"]["steps"],
            "training_updates_added": 0,
            "cost": {
                "latency_micros": execution["latency_micros"],
                "model_parameter_bytes": execution["resident_bytes"],
                "process_peak_rss_bytes": execution["process_peak_rss_bytes"],
                "prompt_tokens": len(execution["prompt_token_ids"]),
                "generated_tokens": len(execution["generated_token_ids"]),
            },
            "wall_seconds": time.monotonic() - started,
            "automatic_retry": False,
            "controlled_context_provider": True,
            "production_qualified": False,
            "future_tasks": 0,
            "confirmation": False,
        }
        retain(output / "report.json", report)
        print(json.dumps(report, sort_keys=True), flush=True)
    except BaseException as error:
        retain(
            output / "failure.json",
            {
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
                "wall_seconds": time.monotonic() - started,
                "training_updates_added": 0,
                "actual_completed_model_calls": None,
                "partial_process_receipts_retained": True,
                "automatic_retry": False,
                "production_qualified": False,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "binary", "native-run", "out", "expected-head"):
        parser.add_argument(f"--{name}", required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
