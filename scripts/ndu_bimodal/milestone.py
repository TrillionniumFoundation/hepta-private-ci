"""Execute one source-bound fixed-graph candidate and retain every outcome."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
import traceback

from . import run
from .candidate import seal_bundle, source_identity, verify_bundle


EXTRA_TESTS = (
    "scripts.ndu_bimodal.test_candidate",
    "scripts.ndu_bimodal.test_delivery",
    "scripts.ndu_bimodal.test_receipts",
    "scripts.test_ndu_bimodal_semantic_eval",
    "scripts.test_ndu_bimodal_frozen_generator",
    "scripts.ndu_real_runtime.test_conditional_particles",
    "scripts.ndu_real_runtime.test_stopped_control",
    "scripts.ndu_real_runtime.test_stopped_baseline",
    "scripts.ndu_real_runtime.test_stopped_torch",
    "scripts.ndu_real_runtime.test_stopped_diagnostics",
    "scripts.ndu_real_runtime.test_stopped_calibration_run",
    "scripts.ndu_real_runtime.test_stopped_observed_demo",
    "scripts.ndu_real_runtime.test_stopped_observed_inputs",
)


def execute(args, output, result):
    source = source_identity(run.REPO, args.source_commit)
    result["source_before"] = source
    version = run.subprocess.check_output(
        [args.rustc, "--version", "--verbose"], text=True, timeout=10
    )
    (output / "rustc-version.txt").write_text(version)
    if not re.match(r"rustc 1\.96\.\d+\b", version):
        raise ValueError("This qualification requires the declared Rust 1.96 toolchain")
    binary, test_binary = output / "hepta-joint-propose", output / "native-tests"
    for label, flags, target in (
        ("native-build", (), binary),
        ("native-test-build", ("--test",), test_binary),
    ):
        run._command(
            [args.rustc, "--edition=2024", "-O", *flags, run.RUST_SOURCE, "-o", target],
            output / label,
        )
    run._command([test_binary], output / "native-tests")
    native_log = (output / "native-tests.stdout.log").read_text()
    counts = re.search(
        r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", native_log
    )
    if not counts or int(counts[1]) == 0 or int(counts[2]) or int(counts[3]):
        raise AssertionError("Native tests are missing, failed, or skipped")
    result["native_test_count"] = int(counts[1])
    os.environ["JOINT_V4_NATIVE_BINARY"] = str(binary)
    result["tests"] = run._python_tests(output, (*run.TEST_MODULES, *EXTRA_TESTS))

    import numpy as np
    import PIL
    import torch
    from .delivery import read_delivery
    from .frozen_training import run_frozen_study
    from .semantic_eval import PROMPT, SEMANTIC_PROFILE, assess

    runtime = {
        "python": sys.version,
        "platform": platform.platform(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
    }
    result["runtime"] = runtime
    root = output / "frozen-content"
    study = run_frozen_study(
        root,
        seed=args.seed,
        base_steps=args.base_steps,
        adapter_steps=args.adapter_steps,
        future_sources=args.future_sources,
        max_training_seconds=args.max_training_seconds,
    )
    baseline = (root / "baseline.heptapk").read_bytes()
    candidate = (root / "candidate.heptapk").read_bytes()
    training = {
        "training_identity": study["candidate_freeze_sha256"],
        "training_sources": [
            row["source_sha256"]
            for stage in ("base_training", "adapter_training")
            for row in study[stage]["losses"]
        ],
        "original_report": "frozen-content/report.json",
    }
    result["checkpoint"] = run._checkpoint_check(output, baseline, candidate, training)
    native = run._native_demo(output, binary, candidate, training, prompt=PROMPT)
    delivery = native["delivery"]
    native_root = output / "native-demo"
    if (
        read_delivery(
            native_root / "delivery", expected_identity=delivery["delivery"]["identity"]
        )
        != delivery
    ):
        raise AssertionError("Original delivery cannot be reconstructed")
    semantic = assess(
        (native_root / "read.ppm").read_bytes(),
        (native_root / "delivery/generated.txt").read_text(encoding="utf-8"),
        (native_root / "delivery/generated.ppm").read_bytes(),
    )
    result["native_decoded_task"] = semantic
    run._json(output / "native-semantic.json", semantic)
    registration = study["registration"]
    contract = {
        "model": {
            "width": 32,
            "depth": 1,
            "kernel": registration["kernel"],
            "fixed_graph": registration["fixed_graph"],
            "shared_sha256": study["shared_before_sha256"],
        },
        "data": {
            "registration_sha256": study["registration_sha256"],
            "semantic_profile": SEMANTIC_PROFILE,
            "native_postfreeze_source_seeds": native["postfreeze_source_seeds"],
        },
        "codec": registration["codec"],
        "utility": {
            "task_score": "one iff decoded text and image are both correct",
            "ndu_independent_net_gain": None,
        },
        "budget": {
            "training_seconds": args.max_training_seconds,
            "base_steps": args.base_steps,
            "adapter_steps": args.adapter_steps,
            "native_seconds": 90,
            "native_calls": 32,
            "native_finalization_seconds": 4,
            "energy_joules": None,
            "provider_money": None,
        },
        "recovery": {
            "local_delivery": "original-identity atomic commit marker",
            "checkpoint": "NoUpdate preserves baseline",
            "ordinary_daemon": "NOT_EXECUTED_REAL_STAGE_OWNERS_REQUIRED",
        },
        "runtime": runtime,
    }
    manifest = seal_bundle(
        output,
        source,
        contract,
        {
            "baseline": "baseline.weights",
            "candidate": "candidate.weights",
            "native_binary": binary.name,
            "training": "frozen-content/report.json",
            "registration": "frozen-content/registration.json",
        },
    )
    run._json(output / "candidate.json", manifest)
    verify_bundle(
        output,
        json.loads((output / "candidate.json").read_text()),
        manifest["candidate_identity"],
    )
    result["candidate_identity"] = manifest["candidate_identity"]
    result["bounded_content_passed"] = (
        study["bounded_content_passed"] and semantic["both_correct"]
    )
    result["source_after"] = source_identity(run.REPO, args.source_commit)
    if result["source_after"] != source:
        raise AssertionError("Source changed during qualification")
    if not result["bounded_content_passed"]:
        raise AssertionError("Registered decoded text/image capability gate failed")
    result["execution_status"] = "passed_bounded_engineering_and_content"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--base-steps", type=int, default=1800)
    parser.add_argument("--adapter-steps", type=int, default=100)
    parser.add_argument("--future-sources", type=int, default=24)
    parser.add_argument("--max-training-seconds", type=float, default=600.0)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == run.REPO or run.REPO in output.parents:
        parser.error("Output must remain outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    result = {
        "schema": "hepta.bimodal.milestone.v1",
        "execution_status": "running",
        "scientific_acceptance": "HOLD_NO_GO",
        "production_update": "no-update",
        "general_multimodal_capability": False,
        "ndu_independent_net_gain": None,
        "actual_stage_owner_daemon_recovery": "NOT_EXECUTED",
    }
    failed = False
    try:
        execute(args, output, result)
    except BaseException as error:
        failed = True
        result.update(
            execution_status="failed", error_type=type(error).__name__, error=str(error)
        )
        (output / "failure.log").write_text(traceback.format_exc())
    if "source_before" in result:
        try:
            result["source_after"] = source_identity(run.REPO, args.source_commit)
            if result["source_after"] != result["source_before"]:
                raise AssertionError("Source changed during qualification")
        except BaseException as error:
            failed = True
            result.update(execution_status="failed", source_after_error=str(error))
    result["whole_run_wall_seconds"] = time.perf_counter() - started
    result["cost_scope"] = (
        "overlaps internal spans; energy, provider billing and historical cost remain unknown"
    )
    try:
        result["artifact_sha256_inventory"] = run._inventory(
            output,
            [
                p
                for p in output.rglob("*")
                if p.is_file() and p != output / "milestone.json"
            ],
        )
    except BaseException as error:
        failed = True
        result.update(execution_status="failed", artifact_inventory_error=str(error))
    run._json(output / "milestone.json", result)
    print(str(output / "milestone.json"), flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
