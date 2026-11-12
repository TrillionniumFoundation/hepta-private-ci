"""One create-only registered development campaign; never resume old actors."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def read(path):
    return json.loads(Path(path).read_bytes())


def pin(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--prior-freeze", type=Path, required=True)
    parser.add_argument("--prior-freeze-sha256", required=True)
    args = parser.parse_args()
    code, root = args.repository.resolve(), args.output.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(code), "rev-parse", "HEAD"], text=True
    ).strip()
    if (
        head != args.expected_source
        or pin(args.prior_freeze) != args.prior_freeze_sha256
    ):
        raise ValueError("Source checkout or retained prior input changed")
    old = read(args.prior_freeze)["collection_plan"]
    root.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "ctrl.real-development-campaign.v1",
        "source_sha": head,
        "wrapper_sha256": pin(__file__),
        "prior_freeze_sha256": args.prior_freeze_sha256,
        "prior_incomplete_collection_retained": True,
        "study_id": "ctrl-real-policy-20261112-1333",
        "fit_per_field": 12,
        "calibration_per_field": 9,
        "evaluation_per_field": 8,
        "action_budget_seconds": 40.0,
        "read_seconds_bound": 30.0,
        "finalizer_seconds_reserve": 5.0,
        "latency_weight": old["config"]["latency_weight"],
        "content_seed": 314159,
        "content_epochs": 12,
        "content_lr": 0.0003,
        "cost_scope": "actual elapsed time at common frozen tariff; energy/provider/oneoff incomplete",
        "scope": "exposed development, source-equal descriptive comparison; no confirmation or adoption",
    }
    save(root / "CAMPAIGN_PLAN.json", plan)
    save(root / "BASE_PLAN.json", old)
    stages = []

    def run(name, script, flags):
        command = [sys.executable, str(code / "scripts" / script), *map(str, flags)]
        save(
            root / (name + "_START.json"),
            {"command": command, "time_ns": time.time_ns()},
        )
        print(json.dumps({"stage": name, "status": "STARTED"}), flush=True)
        began = time.perf_counter()
        with (root / (name + ".log")).open("x") as log:
            process = subprocess.run(
                command, cwd=code, stdout=log, stderr=subprocess.STDOUT, timeout=3600
            )
        record = {
            "stage": name,
            "exit_code": process.returncode,
            "elapsed_seconds": time.perf_counter() - began,
            "log_sha256": pin(root / (name + ".log")),
            "time_ns": time.time_ns(),
        }
        save(root / (name + "_TERMINAL.json"), record)
        stages.append(record)
        print(json.dumps(record), flush=True)
        if process.returncode:
            raise RuntimeError("Original stage failed: " + name)

    try:
        run(
            "prepare",
            "ctrl_macro_prepare.py",
            [
                "--material-root",
                old["config"]["material_root"],
                "--old-plan",
                root / "BASE_PLAN.json",
                "--new-code",
                code,
                "--output",
                root / "preparation",
                "--study-id",
                plan["study_id"],
                "--fit-per-field",
                12,
                "--calibration-per-field",
                9,
                "--evaluation-per-field",
                8,
            ],
        )
        prepared = read(root / "preparation/INPUT_PREPARED.json")
        prepared["collection_plan"]["action_budget_seconds"] = plan[
            "action_budget_seconds"
        ]
        prepared["read_seconds_bound"] = plan["read_seconds_bound"]
        prepared["finalizer_seconds_reserve"] = plan["finalizer_seconds_reserve"]
        save(root / "FROZEN_INPUT.json", prepared)
        registrations = {}
        for mode in ("frozen", "adapted"):
            source = root / (mode.upper() + "_INPUT.json")
            if mode == "adapted":
                adapted = deepcopy(prepared)
                receipt = read(root / "content/receipt.json")
                adapted["collection_plan"]["profile"].update(
                    weights=str(root / "content/weights.pt"),
                    model_sha256=receipt["weights_sha256"],
                    training_receipt_sha256=pin(root / "content/receipt.json"),
                )
                save(source, adapted)
            directory = root / mode
            run(
                mode + "_freeze",
                "ctrl_macro_study.py",
                [
                    "freeze",
                    "--repository",
                    code,
                    "--run-dir",
                    directory,
                    "--prepared-plan",
                    source,
                    "--expected-input-sha256",
                    pin(source),
                ],
            )
            freeze_pin = pin(directory / "FROZEN.json")
            registrations[mode] = {
                "directory": str(directory),
                "freeze_sha256": freeze_pin,
            }
            save(root / (mode.upper() + "_FREEZE_PIN.json"), registrations[mode])
            for stage in ("collect", "export", "fit"):
                run(
                    mode + "_" + stage,
                    "ctrl_macro_study.py",
                    [
                        stage,
                        "--repository",
                        code,
                        "--run-dir",
                        directory,
                        "--freeze-sha256",
                        freeze_pin,
                    ],
                )
            if mode == "frozen":
                run(
                    "content_adapt",
                    "ctrl_macro_content.py",
                    [
                        "--repository",
                        code,
                        "--run-dir",
                        directory,
                        "--freeze-sha256",
                        freeze_pin,
                        "--output",
                        root / "content",
                        "--seed",
                        plan["content_seed"],
                        "--epochs",
                        plan["content_epochs"],
                        "--learning-rate",
                        plan["content_lr"],
                    ],
                )
        run(
            "factorial_freeze",
            "ctrl_macro_factorial.py",
            [
                "freeze",
                "--repository",
                code,
                "--output",
                root / "factorial",
                "--frozen-dir",
                root / "frozen",
                "--frozen-freeze",
                registrations["frozen"]["freeze_sha256"],
                "--adapted-dir",
                root / "adapted",
                "--adapted-freeze",
                registrations["adapted"]["freeze_sha256"],
                "--adaptation-receipt",
                root / "content/receipt.json",
                "--adaptation-sha256",
                pin(root / "content/receipt.json"),
            ],
        )
        factorial_pin = pin(root / "factorial/FROZEN.json")
        save(root / "FACTORIAL_PIN.json", {"sha256": factorial_pin})
        run(
            "factorial_evaluate",
            "ctrl_macro_factorial.py",
            [
                "evaluate",
                "--repository",
                code,
                "--output",
                root / "factorial",
                "--factorial-sha256",
                factorial_pin,
            ],
        )
        save(
            root / "COMPLETED.json",
            {
                "source_sha": head,
                "stages": stages,
                "report_sha256": pin(root / "factorial/REPORT.json"),
                "production_admission": False,
            },
        )
    except Exception as error:
        save(
            root / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "stages": stages,
                "source_sha": head,
                "time_ns": time.time_ns(),
                "original_outputs_preserved": True,
            },
        )
        raise


if __name__ == "__main__":
    main()
