"""Run the fixed native development probe from a clean committed checkout.

Build the existing Agentd example separately, after scoped `just test`. This
driver never compiles Rust, formats code, retries a model call, or assumes an
accuracy gate. It retains fresh training, raw controls, and actual daemon data.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_backend import file_sha
from native_ci_support import (
    acquire,
    command,
    identity,
    model_environment,
    validate_inputs,
    SOURCE_PATHS,
)
from native_trial import retain


def execute(args):
    repo = Path(args.repo).resolve(strict=True)
    binary = Path(args.binary).resolve(strict=True)
    output = Path(args.out).absolute()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    started = time.monotonic()
    try:
        original = identity(repo)
        if original["head"] != args.expected_head:
            raise ValueError(
                "executed source does not match explicitly expected commit"
            )
        retain(output / "source-before.json", original)
        retain(
            output / "invocation.json",
            {
                "argv": sys.argv,
                "python": sys.executable,
                "binary_sha256": file_sha(binary),
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
        fixtures = repo / "scripts/memory_cell_native/fixtures"
        inputs, archive = validate_inputs(fixtures)
        retain(output / "source-inputs.json", inputs)
        model = acquire(fixtures, Path(args.model_out).absolute(), output)
        python = Path(sys.executable).absolute()
        trial = repo / "scripts/memory_cell_native/native_trial.py"
        launcher = repo / "scripts/memory_cell_network/model_child.py"
        run = output / "trial"
        environment = model_environment()
        command(
            output,
            "prepare-source",
            [
                python,
                "-I",
                "-B",
                trial,
                "prepare",
                "--archive",
                archive,
                "--dataset-sha256",
                inputs["dataset_sha256"],
                "--case-id",
                inputs["case_id"],
                "--out",
                run,
            ],
            cwd=repo,
            environment=environment,
        )
        before_protocol = file_sha(run / "protocol.json")
        # Preparation is a separate process: the durable SQLite cut is closed
        # before the actual daemon reacquires its writer lease.
        owner = output / "native-owner"
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
            raise ValueError("independently retained source anchor differs")
        command(
            output,
            "train-96",
            [
                python,
                "-I",
                "-B",
                launcher,
                "--parent-pid",
                os.getpid(),
                trial,
                "train",
                "--run",
                run,
                "--repo",
                repo,
                "--model",
                model,
            ],
            cwd=repo,
            timeout=1200,
            environment=environment,
        )
        command(
            output,
            "configure",
            [
                python,
                "-I",
                "-B",
                trial,
                "configure",
                "--run",
                run,
                "--repo",
                repo,
                "--model",
                model,
            ],
            cwd=repo,
            environment=environment,
        )
        checkpoint_before = {
            p.name: file_sha(p) for p in (run / "checkpoint").iterdir() if p.is_file()
        }
        retain(output / "checkpoint-before.json", checkpoint_before)
        command(
            output,
            "daemon-probe",
            [
                binary,
                "run",
                owner,
                run / "native_config.json",
                run / "source_document.json",
                anchor,
            ],
            cwd=repo,
            timeout=420,
            environment=environment,
        )
        for control in ("base", "shuffled"):
            command(
                output,
                f"control-{control}",
                [
                    python,
                    "-I",
                    "-B",
                    launcher,
                    "--parent-pid",
                    os.getpid(),
                    repo / "scripts/memory_cell_native/native_controls.py",
                    run,
                    control,
                ],
                cwd=repo,
                timeout=600,
                environment=environment,
            )
        if (
            identity(repo) != original
            or file_sha(run / "protocol.json") != before_protocol
        ):
            raise ValueError("source or fixed protocol changed during execution")
        if checkpoint_before != {
            p.name: file_sha(p) for p in (run / "checkpoint").iterdir() if p.is_file()
        }:
            raise ValueError("decoder checkpoint bytes changed during read controls")
        retain(output / "source-after.json", identity(repo))
        report = summarize(output, started)
        retain(output / "report.json", report)
        print(json.dumps(report, sort_keys=True), flush=True)
    except BaseException as error:
        retain(
            output / "failure.json",
            {
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
                "wall_seconds": time.monotonic() - started,
                "automatic_retry": False,
                "production_qualified": False,
            },
        )
        raise


def summarize(output, started):
    run = output / "trial"
    owner = output / "native-owner"
    document = json.loads((run / "source_document.json").read_text())
    engineering = json.loads((owner / "report.json").read_text())
    native = json.loads((owner / "raw-result.json").read_text())
    execution = json.loads(native["execution_json"])
    controls = {}
    for control in ("base", "shuffled"):
        row = json.loads(
            (output / "commands" / f"control-{control}" / "stdout.log").read_text()
        )
        if (
            row["control"] != control
            or len(row["rows"]) != 1
            or row["fact_input"]
            or row["retrieval_input"]
            or row["answer_lexicon_input"]
        ):
            raise ValueError("raw research control receipt differs")
        controls[control] = row
    questions = [row["rows"][0]["question"] for row in controls.values()]
    expected_question = json.loads((run / "read_query.json").read_text())["question"]
    if (
        any(value != expected_question for value in questions)
        or execution["question"] != expected_question
    ):
        raise ValueError("control/native actual query bytes differ")
    if (
        execution["decoder_queries"] != 1
        or execution["feature_forward_calls"] != 1
        or not engineering["engineering_pass"]
    ):
        raise ValueError("actual execution counts or engineering gate differ")
    training = json.loads((run / "training.json").read_text())
    receipts = {
        p.parent.name: json.loads(p.read_text())
        for p in sorted((output / "commands").glob("*/receipt.json"))
    }
    values = {
        "native-fixed-adapter": native["text"],
        **{name: row["rows"][0]["text"] for name, row in controls.items()},
    }
    return {
        "schema": "hepta.memory-cell.native-hosted-development.v1",
        "engineering_pass": True,
        "engineering": engineering,
        "source_head": json.loads((output / "source-before.json").read_text())["head"],
        "parameter_observations": {
            name: {
                "raw_text": value,
                "exact_correct": value.strip() == document["value"],
                "denominator": 1,
            }
            for name, value in values.items()
        },
        "actual_decoder_queries": 3,
        "actual_native_feature_forwards": 1,
        "training_receipt": training,
        "commands": receipts,
        "execution_cost": {
            "native_process_peak_rss_bytes": execution["process_peak_rss_bytes"],
            "native_parameter_bytes": execution["resident_bytes"],
            "native_latency_micros": execution["latency_micros"],
            "decoder_prompt_tokens": len(execution["prompt_token_ids"])
            + sum(v["rows"][0]["input_tokens"] for v in controls.values()),
            "native_feature_input_tokens": len(execution["prompt_token_ids"]),
            "generated_tokens": len(execution["generated_token_ids"])
            + sum(v["rows"][0]["generated_tokens"] for v in controls.values()),
            "training_forwards_and_tokens": training["receipt"],
        },
        "wall_seconds": time.monotonic() - started,
        "previously_exposed_case": True,
        "confirmation": False,
        "parameter_success_gate": None,
        "production_qualified": False,
        "external_github_acl_authenticated": False,
        "neuron_runtime_calibrated_tick": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model-out", required=True)
    parser.add_argument("--expected-head", required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
