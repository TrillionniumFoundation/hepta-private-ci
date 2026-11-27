"""Collect a small source-separated SROIE diagnostic through the actual actor.

The five-source smoke run validates real OCR/actions/scoring and frozen-law
plumbing. It is not a semantic-generation benchmark, a policy-return comparison,
or an independent NDU gain claim. Every failed attempt is retained.
"""

import argparse
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from PIL import Image

from ndu_real_materials.common import binding, write_json
from ndu_real_materials.groups import connect_sources, normalized
from .controllers import ControlPlan
from .episode import EpisodeHost
from .metering import file_sha
from .stopped_calibration_run import parse_args as diagnostic_args, run as diagnose
from .stopped_diagnostics import REGISTRATION_SCHEMA
from .stopped_observed_inputs import load_inputs, save_inputs
from .stopped_torch import source_identity

DATASET = {
    "repository": "jsdnrs/ICDAR2019-SROIE",
    "revision": "bffe40c26759f3376ec2b3ae9031dbba54cd587c",
    "file": "data/test-00000-of-00001.parquet",
    "bytes": 191045976,
    "sha256": "04f8f31b45944cc6e6459a7a95c851a721fc93ffec0a5c29ece9ded734a684c2",
    "license": "CC-BY-4.0 as declared by distributor",
}
SCHEDULES = (
    ("WRITE_TEXT", "STOP"),
    ("WRITE_TEXT", "RENDER_IMAGE", "STOP"),
    ("PREPARE_ROI", "READ_ROI", "WRITE_TEXT", "RENDER_IMAGE", "STOP"),
)


def prepare(parquet, root):
    import pyarrow.parquet as pq
    from ndu_real_materials.register import make_case, target_boxes

    parquet = Path(parquet)
    if (
        parquet.stat().st_size != DATASET["bytes"]
        or file_sha(parquet) != DATASET["sha256"]
    ):
        raise ValueError("Public SROIE parquet differs from the fixed upstream LFS pin")
    records = []
    # This fixed prefix and source-group ordering are chosen before any model
    # execution. Eligibility uses annotation validity, never observed success.
    for row in next(pq.ParquetFile(parquet).iter_batches(batch_size=32)).to_pylist():
        raw = row["image"]["bytes"]
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
        if image.width * image.height > 16_000_000:
            continue
        boxes = target_boxes(row, "total", image.width, image.height)
        pixels = list(image.resize((9, 8)).convert("L").getdata())
        records.append(
            {
                **{k: row[k] for k in ("key", "entities", "words", "bboxes")},
                "field": "total",
                "target_boxes": boxes,
                "eligible": bool(boxes),
                "raw": raw,
                "image_sha256": hashlib.sha256(raw).hexdigest(),
                "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "transcript_sha256": hashlib.sha256(
                    "\n".join(row["words"]).encode()
                ).hexdigest(),
                "word_tokens": set(normalized(word) for word in row["words"]),
                "dhash": sum(
                    int(pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
                    for y in range(8)
                    for x in range(8)
                ),
                "aspect": image.width / image.height,
                "width": image.width,
                "height": image.height,
            }
        )
    groups, edges = connect_sources(records)
    selected = [g for g in groups if any(r["eligible"] for r in g["members"])][:5]
    if len(selected) != 5:
        raise ValueError("Fixed prefix lacks five distinct eligible merchant groups")
    materials = root / "materials"
    rubric = {
        "schema": "ndu.real.receipt.rubric.v1",
        "text": "exact canonical source-annotated total",
        "image": "source-pixel-equal crop and annotation IoU",
        "weights": {"text": 0.5, "image": 0.5},
        "scope": "real observation plumbing smoke; not a semantic-generation benchmark",
    }
    write_json(materials / "rubric.json", rubric)
    cases, roster = [], []
    for role, group in zip(
        ("fit", "calibration", "calibration", "diagnostic", "diagnostic"), selected
    ):
        row = sorted(
            (r for r in group["members"] if r["eligible"]), key=lambda r: r["key"]
        )[0]
        path = materials / "private" / "images" / (row["key"] + ".jpg")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(row["raw"])
        row["source_image"] = binding(path, materials)
        case = make_case(
            materials,
            row,
            group,
            "train",
            "text_image_complementary",
            file_sha(materials / "rubric.json"),
        )
        cases.append(case)
        roster.append(
            {
                "diagnostic_role": role,
                "source_group": group["source_group"],
                "episode_key": row["key"],
                "source_image": row["source_image"],
                "case_id": case["id"],
            }
        )
    write_json(
        materials / "private" / "reference-index.v2.json",
        {
            "schema": "ndu.real.reference-index.v2",
            "case_roles": {c["id"]: "train" for c in cases},
            "cases": {c["id"]: c["reference"] for c in cases},
            "rubric": binding(materials / "rubric.json", materials),
        },
    )
    registration = {
        "schema": REGISTRATION_SCHEMA,
        **{
            role + "_source_groups": [
                r["source_group"] for r in roster if r["diagnostic_role"] == role
            ]
            for role in ("fit", "calibration", "diagnostic")
        },
        "core": "ordinary",
        "memory_mode": "reset",
        "seed": 730001,
        "neighbor_groups": 2,
        "particles": 2,
        "risk_settings": [0.0, 2.0],
        "feature_scales": [1.0] * 40,
        "behavior_was_unfitted_collector": False,
    }
    write_json(root / "registration.json", registration)
    write_json(
        root / "prospective-selection.json",
        {
            "dataset": DATASET,
            "roster": roster,
            "source_edges": edges,
            "selection": "first 32 parquet rows, eligible groups sorted by fixed existing group ID, first five",
            "schedules": SCHEDULES,
            "collector_seed": 730001,
            "content_epochs": 3,
            "fit_calibration_diagnostic_partition_frozen_before_any_actor": True,
            "raw_record_split": "train; separately frozen diagnostic roles; no historical records relabeled",
            "public_dataset_pretraining_exposure": "unknown; collector is newly initialized",
            "registration_sha256": file_sha(root / "registration.json"),
        },
    )
    return materials, cases


def command(root, label, argv, repository, *, timeout=180):
    folder = root / "commands" / label
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    env = dict(
        os.environ,
        PYTHONPATH=str(repository / "scripts") + os.pathsep + str(repository),
    )
    env.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    receipt = {"command": argv, "status": "started", "exit_code": None}
    write_json(folder / "started.json", receipt)
    try:
        with (
            (folder / "stdout.log").open("xb") as stdout,
            (folder / "stderr.log").open("xb") as stderr,
        ):
            result = subprocess.run(
                argv,
                cwd=repository,
                env=env,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
            )
        receipt.update(
            status="completed" if result.returncode == 0 else "failed",
            exit_code=result.returncode,
        )
        if result.returncode:
            raise RuntimeError("Observed collector command failed: " + label)
    except subprocess.TimeoutExpired:
        receipt["status"] = "timed_out"
        raise
    finally:
        receipt.update(
            wall_seconds=time.perf_counter() - started,
            stdout_sha256=file_sha(folder / "stdout.log"),
            stderr_sha256=file_sha(folder / "stderr.log"),
        )
        write_json(folder / "receipt.json", receipt)


def run(args):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    started, results = time.perf_counter(), []
    report = {
        "schema": "ndu.stopped.observed-smoke.v1",
        "status": "started",
        "scientific_admission": "HOLD",
        "net_benefit_established": False,
        "policy_return_comparison": False,
        "native_owner_authenticated": False,
    }
    write_json(root / "started.json", report)
    try:
        repository = Path(__file__).resolve().parents[2]
        if args.prepared_input:
            if not args.expected_input_manifest_sha256:
                raise ValueError(
                    "A transferred subset requires its explicit manifest SHA256"
                )
            materials, cases = load_inputs(
                args.prepared_input, root, args.expected_input_manifest_sha256, DATASET
            )
            report["upstream_parquet_verified_in_this_process"] = False
        else:
            materials, cases = prepare(args.parquet, root)
            save_inputs(root, cases, DATASET)
            report["upstream_parquet_verified_in_this_process"] = True
        report["input_manifest_sha256"] = file_sha(root / "input-manifest.json")
        plan = ControlPlan(horizon=1, particles=2, memory_mode="reset")
        control = root / "control.json"
        write_json(
            control,
            {
                "control": asdict(plan),
                "episode_wall_seconds": 60.0,
                "fixed_schedule": [],
                "seed": 730001,
            },
        )
        config = {
            "material_root": str(materials),
            "python": sys.executable,
            "scripts_root": str(repository / "scripts"),
            "repository_root": str(repository),
            "pillow_path": str(Path(Image.__file__).parent.parent),
            "latency_weight": plan.latency_weight,
            "episode_wall_seconds": 60.0,
            "rubric_sha256": file_sha(materials / "rubric.json"),
            "reference_index_sha256": file_sha(
                materials / "private/reference-index.v2.json"
            ),
            "evaluator_sha256": file_sha(
                repository / "scripts/ndu_real_materials/evaluator.py"
            ),
            "tesseract": str(Path(args.tesseract).resolve(strict=True)),
            "tessdata_dir": str(Path(args.tessdata_dir).resolve(strict=True)),
            "ocr_library_dir": str(Path(args.ocr_library_dir).resolve(strict=True)),
            "runtime_roots": [
                str(repository),
                sys.prefix,
                sys.base_prefix,
                "/usr",
                "/etc/ld.so.cache",
                "/dev/null",
                "/dev/urandom",
                "/proc/cpuinfo",
            ],
        }
        write_json(root / "execution-config.json", config)
        common = [
            sys.executable,
            "-m",
            "ndu_real_runtime.training",
            "--core",
            "ordinary",
            "--seed",
            "730001",
            "--replicate-role",
            "collector",
            "--control-plan",
            str(control),
            "--content-epochs",
            "3",
            "--fit-epochs",
            "1",
            "--max-wall-seconds",
            "60",
        ]
        command(
            root,
            "bootstrap",
            [*common, "--bootstrap", "--output", str(root / "bootstrap")],
            repository,
        )

        def collect(case, model_dir, label, schedules):
            weights = model_dir / "weights.pt"
            paths = []
            for index, schedule in enumerate(schedules):
                folder = root / "episodes" / (label + f"-{index:02d}")
                profile = {
                    "original_operation_id": label + f"-{index:02d}",
                    "weights": str(weights),
                    "model_sha256": file_sha(weights),
                    "core": "ordinary",
                    "controller": "initial",
                    "control_plan": str(control),
                    "training_receipt_sha256": file_sha(model_dir / "receipt.json"),
                }
                host = EpisodeHost(
                    config, case, profile, folder, training=True, exploration=schedule
                )
                result = host.run()
                results.append(
                    {
                        "path": str(folder),
                        "status": result["terminal_status"],
                        "source_group": case["source_id"],
                        "actions": result["actions"],
                        "gross_score": result.get("gross_score"),
                        "wall_seconds": result["deployment_meter"]["wall_seconds"],
                    }
                )
                write_json(
                    root / "episode-events" / (label + f"-{index:02d}.json"),
                    results[-1],
                )
                if result["terminal_status"] != "Completed":
                    raise RuntimeError(
                        "Real actor episode failed; original result retained: "
                        + str(folder)
                    )
                paths.append(folder / "training-rows.jsonl")
            return paths

        fit = collect(cases[0], root / "bootstrap", "fit-source", (SCHEDULES[-1],))[0]
        command(
            root,
            "fit-collector",
            [
                *common,
                "--content-only",
                "--records",
                str(fit),
                "--expected-records-sha256",
                file_sha(fit),
                "--output",
                str(root / "collector"),
            ],
            repository,
        )
        collector = root / "collector"
        freeze = {
            "weights_sha256": file_sha(collector / "weights.pt"),
            "receipt_sha256": file_sha(collector / "receipt.json"),
            "registration_sha256": file_sha(root / "registration.json"),
            "source_sha256": source_identity(),
            "stage": "before_calibration_or_diagnostic_collection",
        }
        write_json(root / "collector-freeze.json", freeze)
        paths = []
        for index, case in enumerate(cases[1:]):
            paths.extend(
                collect(case, collector, f"held-source-{index:02d}", SCHEDULES)
            )
        records = root / "observed-records.jsonl"
        with records.open("xb") as stream:
            for path in paths:
                stream.write(path.read_bytes())
        argv = [
            "--output",
            str(root / "diagnostic"),
            "--device",
            "cpu",
            "--expected-source-sha256",
            freeze["source_sha256"],
            "--max-wall-seconds",
            "180",
        ]
        for name, path in (
            ("records", records),
            ("weights", collector / "weights.pt"),
            ("behavior-metadata", collector / "receipt.json"),
            ("registration", root / "registration.json"),
        ):
            argv.extend(
                [
                    "--" + name,
                    str(path),
                    "--expected-" + name + "-sha256",
                    file_sha(path),
                ]
            )
        code = diagnose(diagnostic_args(argv))
        report.update(
            status="completed" if code == 0 else "diagnostic_not_completed",
            diagnostic_exit_code=code,
            collector_weights_unchanged=file_sha(collector / "weights.pt")
            == freeze["weights_sha256"],
            real_source_groups=5,
            collector_content_fit_runs=1,
            raw_record_sha256=file_sha(records),
            diagnostic_receipt_sha256=file_sha(root / "diagnostic/receipt.json"),
        )
    except Exception as error:
        report.update(
            status="failed", error={"type": type(error).__name__, "message": str(error)}
        )
        (root / "traceback.txt").write_text(traceback.format_exc())
    report.update(
        episodes=results,
        wall_seconds=time.perf_counter() - started,
        cost_scope="outer elapsed envelope; nested stages retained, not summed; energy and money unknown",
    )
    write_json(root / "receipt.json", report)
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--parquet", type=Path)
    inputs.add_argument("--prepared-input", type=Path)
    parser.add_argument("--expected-input-manifest-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tesseract", default="/usr/bin/tesseract")
    parser.add_argument("--tessdata-dir", default="/usr/share/tesseract-ocr/5/tessdata")
    parser.add_argument("--ocr-library-dir", default="/usr/lib/x86_64-linux-gnu")
    raise SystemExit(run(parser.parse_args()))
