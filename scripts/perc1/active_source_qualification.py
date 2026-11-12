"""Real source CLI ACQUIRE/STOP/replay qualification with a diagnostic controller.

The head is fitted to hand-specified synthetic branch markers. Its predictions
are not estimates of real task value. One TRAIN document supplies two nested
neutral crops; annotations and evaluation splits are never read. Preserve all
run artifacts locally; no source bytes or model weights belong in the git PR.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from perc1_process_meter import run as measured_run

from .acquisition import train_head
from .active_capture import observed_prefix
from .owner import Owner
from .schema import Cost, canonical, require, sha
from .source_entry import make_config, operator_source_config


def write_json(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def diagnostic_pair(group, split, marker, dimension):
    receipt = {
        "source_id": "initial",
        "receipt_sha256": sha([group, "receipt"]),
        "capture_sha256": sha([group, "capture"]),
    }
    prefix = sha([group, "synthetic-prefix"])
    before = {
        "prefix_sha256": prefix,
        "solver_sha256": sha("hand-diagnostic-solver"),
        "inference_seed": 0,
        "evidence": [receipt],
        "score": 1.0 if marker < 0 else 0.0,
        "cost": asdict(Cost(acquisition=2, encoding=2, inference=2)),
    }
    after = {
        **before,
        "evidence": [
            receipt,
            {
                "source_id": "additional",
                "receipt_sha256": sha([group, "extra-receipt"]),
                "capture_sha256": sha([group, "extra-capture"]),
            },
        ],
        "score": 1.0 if marker > 0 else 0.0,
        "cost": asdict(Cost(acquisition=3, encoding=3, inference=3, communication=1)),
    }
    return {
        "schema": "perc1.acquisition-pair.v1",
        "source_group": group,
        "split": split,
        "candidate_id": "additional",
        "features": {
            "schema": "perc1.acquisition-features.v1",
            "prefix_sha256": prefix,
            "task_goal": [marker],
            "coverage": 0.25,
            "source_repeat": 0.0,
            "remaining_budget": 100,
            "uncertainty": 0.95,
            "acquired_latent": [0.0] * dimension,
            "acquired_receipt_sha256s": [receipt["receipt_sha256"]],
        },
        "without": before,
        "with": after,
    }


def image_regions(width, height):
    return [
        {
            "evidence_id": f"neutral-{x}-{y}",
            "x": width * x // 4 - 8,
            "y": height * y // 4 - 8,
            "width": 16,
            "height": 16,
        }
        for y in (1, 3)
        for x in (1, 3)
    ]


def qualify(args):
    from PIL import Image

    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    inputs = root / "run-owned-inputs"
    inputs.mkdir(mode=0o700)
    repo = Path(__file__).resolve().parents[2]
    names = (
        "__main__",
        "entry",
        "source_entry",
        "source_capture",
        "browser_capture",
        "owner",
        "capture_entry",
        "producer",
        "projection",
        "raster",
        "native",
        "schema",
        "active_capture",
        "acquisition",
        "mlp_head",
        "active_source_qualification",
    )
    code = [Path(__file__).with_name(name + ".py") for name in names]
    code.append(repo / "scripts" / "perc1_process_meter.py")
    pins = {str(path.relative_to(repo)): sha(path.read_bytes()) for path in code}
    write_json(root / "CODE_PINS.json", pins)
    prior = args.prior_run.resolve(strict=True)
    prior_config = json.loads((prior / "config.json").read_bytes())
    acquisition = json.loads((prior / "ACQUISITION.json").read_bytes())
    projection_bytes = (prior / "projection.json").read_bytes()
    require(
        sha(projection_bytes) == prior_config["model"]["projection_sha256"],
        "reused PCA pin changed",
    )
    projection = json.loads(projection_bytes)
    weights_bytes = args.weights.read_bytes()
    weights_sha = prior_config["model"]["weights_sha256"]
    require(
        sha(weights_bytes) == weights_sha == projection["backbone_sha256"],
        "backbone pin mismatch",
    )
    (inputs / "weights.pth").write_bytes(weights_bytes)
    (root / "projection.json").write_bytes(projection_bytes)
    del weights_bytes
    training = args.training_images.resolve(strict=True)
    require(
        training.name == "images" and training.parent.name == "training_data",
        "TRAIN image directory required",
    )
    paths = sorted(training.glob("*.png"))
    require(len(paths) >= 10, "ten original TRAIN images required")
    original_path = paths[9]
    require(not original_path.is_symlink(), "regular TRAIN image required")
    original_bytes = original_path.read_bytes()
    original_sha = sha(original_bytes)
    (inputs / "full-page.png").write_bytes(original_bytes)
    source_group = "funsd-train:" + original_path.stem
    require(
        source_group not in projection["training"]["source_groups"],
        "crop document was in PCA training",
    )
    source_uri = (
        acquisition["record"]["url"]
        + "#dataset/training_data/images/"
        + original_path.name
    )
    source_template = next(iter(prior_config["sources"].values()))
    sources, mapping, requests = {}, [], {}
    with Image.open(original_path) as original:
        image = original.convert("RGB")
        width, height = image.size
        cx, cy = width // 4, height // 4
        require(
            cx >= 64 and cy >= 64 and cx + 64 <= width and cy + 64 <= height,
            "neutral nested crop bounds",
        )
        for name, half in (("initial", 32), ("expanded", 64)):
            box = [cx - half, cy - half, cx + half, cy + half]
            path = inputs / (name + ".png")
            cropped = image.crop(box)
            cropped.save(path)
            raw = path.read_bytes()
            with Image.open(path) as check:
                require(
                    check.convert("RGB").tobytes() == image.crop(box).tobytes(),
                    "lossless crop mapping failed",
                )
            source_id = "funsd-" + name
            sources[source_id] = {
                "schema": "perc1.source-capture.v1",
                "kind": "document_page",
                "source_uri": source_uri,
                "source_group": source_group,
                "image": {"path": str(path), "sha256": sha(raw)},
                "document": {
                    "path": str(inputs / "full-page.png"),
                    "sha256": original_sha,
                    "page_index": 0,
                },
                "text": None,
                "ocr": source_template["ocr"],
            }
            requests[name] = {
                "source_id": source_id,
                "representation": "global",
                "regions": image_regions(cropped.width, cropped.height),
            }
            mapping.append(
                {
                    "source_id": source_id,
                    "source_group": source_group,
                    "original_sha256": original_sha,
                    "original_dimensions": [width, height],
                    "original_box_xyxy": box,
                    "crop_sha256": sha(raw),
                    "crop_dimensions": [cropped.width, cropped.height],
                    "pixel_mapping_verified_locally": True,
                    "origin_authenticated": False,
                }
            )
    write_json(
        root / "SOURCE_MAPPING.json",
        {
            "source_uri": source_uri,
            "original_sha256": original_sha,
            "crops": mapping,
            "selection": "tenth lexical TRAIN image; fixed quarter-page point; no labels",
            "annotations_read": False,
            "evaluation_split_read": False,
            "independent_real_tasks": 0,
            "distinct_original_documents": 1,
        },
    )
    model = {
        **prior_config["model"],
        "weights": str(inputs / "weights.pth"),
        "projection": str(root / "projection.json"),
    }
    config = make_config(
        root / "owner",
        "active-source-diagnostic",
        1,
        2,
        sources,
        model,
        sha([root.name, "scope"]),
    )
    config_path = root / "config.json"
    write_json(config_path, config)
    _, _, binding = operator_source_config(config_path)
    for name, request in requests.items():
        write_json(root / (name + "-request.json"), request)
    dimension = projection["dimension"]
    pairs = {
        split: [
            diagnostic_pair(f"diagnostic-{split}-{i}", split, marker, dimension)
            for i, marker in enumerate((-1.0, 0.0, 1.0))
        ]
        for split in ("train", "dev")
    }
    split_groups = {
        split: [p["source_group"] for p in rows] for split, rows in pairs.items()
    }
    split_groups["confirmation"] = ["diagnostic-placeholder-not-a-real-source"]
    head = train_head(
        pairs["train"],
        pairs["dev"],
        split_groups,
        feature_extractor_sha256=pins["scripts/perc1/active_source_qualification.py"],
        ridge=0.01,
        cost_value=0.1,
    )
    require(
        all(v == 0 for row in head["coefficients"] for v in row[6:]),
        "diagnostic head unexpectedly uses visual values",
    )
    write_json(root / "diagnostic-head.json", head)
    write_json(
        root / "DIAGNOSTIC_CONTROLLER.json",
        {
            "head_sha256": sha(head),
            "pairs": pairs,
            "split_groups": split_groups,
            "hand_controlled_diagnostic": True,
            "real_value_training_pairs": 0,
            "diagnostic_fixture_fits": 1,
            "real_training_or_utility_claim": False,
            "rule": "+1 marker before extra observation; -1 after; latent weights deliberately zero",
            "quoted_microcredits_are_advisory": True,
            "adoption": "NoUpdate",
        },
    )
    steps = []
    base = [sys.executable, "-m", "perc1"]

    def invoke(name, command, expected=0, reason=None):
        destination = root / name
        envelope = measured_run(
            command,
            destination,
            cwd=repo / "scripts",
            source_paths=code,
            timeout_seconds=180,
        )
        steps.append({"name": name, "receipt": envelope})
        require(
            envelope["returncode"] == expected and envelope["measurement_valid"],
            "CLI outcome/source mismatch: " + name,
        )
        result = json.loads(
            (
                destination / ("stdout.bin" if expected == 0 else "stderr.bin")
            ).read_bytes()
        )
        if reason is not None:
            require(reason in result["reason"], "negative-control cause mismatch")
        print(json.dumps({"stage": name, "returncode": expected}), flush=True)
        return result

    def command(action, operation, request_path=None):
        value = base + [action, "--config", str(config_path), "--operation", operation]
        return (
            value if request_path is None else value + ["--request", str(request_path)]
        )

    def active_request(operation_ids, marker):
        with Owner(config["state_dir"], binding, config["budget_units"]) as owner:
            prefix = observed_prefix(
                owner, sha("active-diagnostic-task"), operation_ids
            )
        features = diagnostic_pair("runtime", "confirmation", marker, dimension)[
            "features"
        ]
        features.update(
            prefix_sha256=sha(prefix),
            acquired_receipt_sha256s=prefix["receipt_sha256s"],
            acquired_latent=prefix["latent_summary"],
        )
        return {
            "head": head,
            "head_sha256": sha(head),
            "task_sha256": prefix["task_sha256"],
            "observed_operations": operation_ids,
            "candidates": [
                {
                    "id": "additional",
                    "kind": "expand_roi" if marker > 0 else "reobserve",
                    "upper_cost": 4,
                    "features": features,
                    "request": requests["expanded"],
                }
            ],
        }

    initial = invoke(
        "01-initial",
        command("source-capture", "initial-001", root / "initial-request.json"),
    )
    acquire_path = root / "acquire-request.json"
    write_json(acquire_path, active_request(["initial-001"], 1.0))
    acquired = invoke("02-acquire", command("source-active", "extra-001", acquire_path))
    stop_path = root / "stop-request.json"
    write_json(stop_path, active_request(["initial-001", "extra-001"], -1.0))
    stopped = invoke("03-stop", command("source-active", "stop-001", stop_path))
    execution = {
        "source_callback_invocations": 1,
        "encoder_loaded": True,
        "encoder_completed_calls": 1,
    }
    inactive = {
        "source_callback_invocations": 0,
        "encoder_loaded": False,
        "encoder_completed_calls": 0,
    }
    require(
        initial["this_entry"] == acquired["this_entry"] == execution,
        "two real captures/backbone batches were not executed",
    )
    require(
        initial["status"] == acquired["status"] == "executed", "source execution failed"
    )
    require(
        acquired["active"]["decision"]["kind"] == "expand_roi"
        and acquired["active"]["decision"]["selection"]["action"] == "ACQUIRE",
        "diagnostic ACQUIRE did not execute",
    )
    require(
        stopped["status"] == "stopped" and stopped["this_entry"] == inactive,
        "STOP performed work",
    )
    require(
        stopped["active"]["owner_receipt"] is None,
        "STOP invented an acquisition receipt",
    )
    state = stopped["owner_status"]
    require(
        state["reserved_units"] == 2 and state["remaining_units"] == 0,
        "attempt reservations incorrect",
    )
    preserved = root / "preserved-run-owned-inputs"
    inputs.rename(preserved)
    write_json(
        root / "MOVED_RUN_OWNED_INPUTS.json",
        {
            "old_directory": str(inputs),
            "preserved_directory": str(preserved),
            "deleted_files": [],
            "original_user_sources_modified": False,
            "reason": "cold reads/replays must succeed with configured acquisition/weight paths absent",
        },
    )
    require(
        not inputs.exists() and args.weights.is_file() and original_path.is_file(),
        "original sources changed",
    )
    for name, operation, original in (
        ("04-acquire-decision-read", "extra-001", acquired),
        ("05-stop-decision-read", "stop-001", stopped),
    ):
        result = invoke(name, command("source-decision-read", operation))
        require(
            result["decision"] == original["active"]["decision"]
            and result["this_entry"] == inactive
            and result["owner_status"] == state,
            "cold decision read changed evidence or performed work",
        )
    for name, operation, path, original in (
        ("06-acquire-replay", "extra-001", acquire_path, acquired),
        ("07-stop-replay", "stop-001", stop_path, stopped),
    ):
        result = invoke(name, command("source-active", operation, path))
        require(
            result["receipt"] == original["receipt"]
            and result["active"]["decision"] == original["active"]["decision"],
            "replay changed receipt/decision",
        )
        require(
            result["this_entry"] == inactive and result["owner_status"] == state,
            "replay spent another attempt or ran work",
        )
    invoke(
        "08-stop-token-refused",
        command("source-capture", "stop-001", root / "expanded-request.json"),
        2,
        "capture conflicts with retained active decision",
    )
    invoke(
        "09-budget-refused",
        command("source-capture", "over-budget", root / "expanded-request.json"),
        2,
        "acquisition reservation denied",
    )
    final = invoke("10-final-cold-read", command("source-read", "extra-001"))
    require(
        final["receipt"] == acquired["receipt"]
        and final["owner_status"] == state
        and final["this_entry"] == inactive,
        "final effect receipt/budget changed",
    )
    require(
        pins == {str(path.relative_to(repo)): sha(path.read_bytes()) for path in code},
        "source changed during qualification",
    )
    report = {
        "schema": "perc1.active-source-qualification.v1",
        "status": "PASS_LOCAL_ACTIVE_PIPELINE",
        "head_sha256": sha(head),
        "code_pins_sha256": sha(pins),
        "config_sha256": sha(config),
        "projection_file_sha256": sha(projection_bytes),
        "reused_projection_from": str(prior),
        "projection_backbone_batches_this_run": 0,
        "actual_online_backbone_batches": 2,
        "actual_source_callbacks": 2,
        "distinct_original_documents": 1,
        "nested_crop_observations": 2,
        "independent_real_tasks": 0,
        "real_value_training_pairs": 0,
        "diagnostic_fixture_fits": 1,
        "hand_controlled_diagnostic": True,
        "attempts_reserved": 2,
        "attempt_budget": 2,
        "stop_effects": 0,
        "replay_new_effects": 0,
        "decision_cold_reads": 2,
        "source_cold_reads": 1,
        "expected_negative_controls": [
            "STOP token cannot capture",
            "attempt budget exhausted",
        ],
        "parent_wall_ns": time.perf_counter_ns() - started,
        "parent_process_cpu_ns": time.process_time_ns() - cpu,
        "cost_scope": "parent wall includes input preparation, diagnostic fit, prefix reads and every child command; child receipts include imports/startup/capture/OCR/encoder/readback. Nested times are not additive.",
        "steps": steps,
        "energy_joules": None,
        "provider_billing": None,
        "terminal_task_quality": None,
        "measured_net_benefit": None,
        "scientific_qualified": False,
        "production_daemon_integrated": False,
        "adoption": "NoUpdate",
        "real_power_loss_tested": False,
    }
    write_json(root / "REPORT.json", report)
    write_json(
        root / "FILE_MANIFEST.json",
        {
            str(path.relative_to(root)): {
                "sha256": sha(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "FILE_MANIFEST.json"
        },
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prior-run", "training-images", "weights", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report = qualify(args)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "actual_online_backbone_batches",
                    "attempts_reserved",
                    "independent_real_tasks",
                    "adoption",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
