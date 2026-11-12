"""Real FUNSD train-image -> source CLI -> original wire -> native owner check.

This is one engineering input, not a task-benefit evaluation. The first eight
lexically sorted TRAIN images supply four annotation-free 16x16 crops each for
PCA; the ninth is acquired through the ordinary source owner. No annotation or
evaluation files are read. Raw retained outputs must not be published to git.
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path

from perc1_process_meter import run as measured_run

from .capture_entry import decode_native_wire
from .producer import FrozenMobileNet
from .projection import fit_projection
from .schema import canonical, require, sha
from .source_capture import verify_source_evidence
from .source_entry import make_config


def write_json(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def regions_for(raw):
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
    require(width >= 32 and height >= 32, "source too small for fixed crops")
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


def file_manifest(root):
    return {
        str(path.relative_to(root)): {
            "sha256": sha(path.read_bytes()),
            "bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "FILE_MANIFEST.json"
    }


def qualify(args):
    import numpy as np
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
        "source_qualification",
    )
    code = [Path(__file__).with_name(name + ".py") for name in names]
    code += [
        repo / "scripts" / name
        for name in (
            "perc1_process_meter.py",
            "perc1_native_owner_qualification.py",
            "perc1_native_owner_probe.rs",
        )
    ]
    pins = {str(path.relative_to(repo)): sha(path.read_bytes()) for path in code}
    write_json(root / "CODE_PINS.json", pins)
    training_dir = args.training_images.resolve(strict=True)
    require(
        training_dir.name == "images" and training_dir.parent.name == "training_data",
        "only the FUNSD training_data/images directory is accepted",
    )
    images = sorted(training_dir.glob("*.png"))[:9]
    require(
        len(images) == 9 and all(p.is_file() and not p.is_symlink() for p in images),
        "nine regular original TRAIN image files required",
    )
    acquisition = json.loads(args.acquisition_manifest.read_bytes())
    require(
        acquisition["schema"] == "perc1.funsd-source-acquisition.v1",
        "FUNSD acquisition record required",
    )
    write_json(
        root / "ACQUISITION.json",
        {
            "record": acquisition,
            "record_sha256": sha(args.acquisition_manifest.read_bytes()),
            "authentication": "prior acquisition record, not independent origin attestation",
        },
    )
    weights_raw = args.weights.read_bytes()
    require(sha(weights_raw) == args.weights_sha256, "weight input pin mismatch")
    weights_copy = inputs / "weights.pth"
    with weights_copy.open("xb") as stream:
        stream.write(weights_raw)
    worker = FrozenMobileNet(weights_copy, args.weights_sha256, device="cpu")
    training, features, captures, groups = [], [], [], []
    for path in images[:8]:
        raw = path.read_bytes()
        regions = regions_for(raw)
        _, values, transform = worker.features(raw, regions)
        features.extend(values)
        group = "funsd-train:" + path.stem
        captures.extend({"sha256": sha(raw), "split": "train"} for _ in regions)
        groups.extend(group for _ in regions)
        training.append(
            {
                "relative_source": "training_data/images/" + path.name,
                "source_sha256": sha(raw),
                "source_bytes": len(raw),
                "source_group": group,
                "transform": transform,
            }
        )
    require(worker.calls == 8, "each training frame must actually execute the backbone")
    projection = fit_projection(
        np.asarray(features),
        captures=captures,
        groups=groups,
        backbone_sha256=args.weights_sha256,
        dimension=16,
    )
    projection_path = root / "projection.json"
    write_json(projection_path, projection)
    write_json(
        root / "TRAINING.json",
        {
            "images": training,
            "rows": len(features),
            "actual_backbone_batches": worker.calls,
            "backbone_cold_load_ns": worker.cold_load_ns,
            "versions": worker.versions,
            "projection_training": projection["training"],
            "annotations_read": False,
            "evaluation_split_read": False,
            "roi_policy": "four 16x16 crops at quarter-grid centers",
            "selection": "first eight lexical TRAIN image filenames; ninth reserved for engineering input",
        },
    )
    training_load_ns = worker.cold_load_ns
    del worker, weights_raw, features

    source_path = images[8]
    source_raw = source_path.read_bytes()
    source_sha = sha(source_raw)
    require(
        source_sha not in {item["source_sha256"] for item in training},
        "engineering input duplicates a PCA training image",
    )
    image_copy = inputs / "source.png"
    with image_copy.open("xb") as stream:
        stream.write(source_raw)
    scope = {
        "agent_id": "perc-source-qualification",
        "cell_id": "perc-source-cell",
        "run_id": "funsd-source-native-001",
        "principal_digest": list(
            bytes.fromhex(sha(b"local-engineering-principal-no-daemon-grant"))
        ),
    }
    scope_bytes = b"hepta.cell.scope.v1"
    for key in ("agent_id", "cell_id", "run_id"):
        value = scope[key].encode()
        scope_bytes += len(value).to_bytes(4, "big") + value
    scope_digest = sha(scope_bytes + bytes(scope["principal_digest"]))
    source_id = "funsd-train-" + source_path.stem
    sources = {
        source_id: {
            "schema": "perc1.source-capture.v1",
            "kind": "document_page",
            "source_uri": acquisition["url"]
            + "#dataset/training_data/images/"
            + source_path.name,
            "source_group": "funsd-train:" + source_path.stem,
            "image": {"path": str(image_copy), "sha256": source_sha},
            "document": None,
            "text": None,
            "ocr": {
                "executable": str(args.tesseract.resolve(strict=True)),
                "sha256": sha(args.tesseract.read_bytes()),
                "language": "eng",
                "psm": 6,
            },
        }
    }
    config = make_config(
        root / "owner",
        "real-source-qualification",
        1,
        1,
        sources,
        {
            "weights": str(weights_copy),
            "weights_sha256": args.weights_sha256,
            "projection": str(projection_path),
            "projection_sha256": sha(projection_path.read_bytes()),
            "device": "cpu",
        },
        scope_digest,
    )
    request = {
        "source_id": source_id,
        "representation": "global",
        "regions": regions_for(source_raw),
    }
    config_path, request_path = root / "config.json", root / "request.json"
    write_json(config_path, config)
    write_json(request_path, request)
    write_json(root / "scope.json", scope)
    steps = []

    def invoke(name, command):
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
            envelope["returncode"] == 0 and envelope["measurement_valid"],
            "command failed or cost/source evidence invalid: " + name,
        )
        return json.loads((destination / "stdout.bin").read_bytes())

    base = [sys.executable, "-m", "perc1"]
    options = ["--config", str(config_path), "--operation", "real-source-001"]
    capture = base + ["source-capture"] + options + ["--request", str(request_path)]
    first = invoke("01-first", capture)
    replay = invoke("02-replay", capture)
    require(
        first["status"] == "executed"
        and first["this_entry"]
        == {
            "source_callback_invocations": 1,
            "encoder_loaded": True,
            "encoder_completed_calls": 1,
        },
        "first CLI did not perform exactly one acquisition/backbone batch",
    )
    deleted = []
    for path in (image_copy, weights_copy):
        deleted.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
        )
        path.unlink()
    write_json(root / "DELETED_RUN_OWNED_INPUTS.json", deleted)
    cold = invoke("03-cold-read", base + ["source-read"] + options)
    require(
        not image_copy.exists() and not weights_copy.exists(),
        "run inputs unexpectedly restored",
    )
    for result in (replay, cold):
        require(
            result["status"] == "executed"
            and result["this_entry"]
            == {
                "source_callback_invocations": 0,
                "encoder_loaded": False,
                "encoder_completed_calls": 0,
            },
            "replay/read performed new acquisition or encoding",
        )
        require(
            result["receipt"] == first["receipt"]
            and result["owner_status"] == first["owner_status"],
            "replay/read changed retained receipt or acquisition budget",
        )
    require(
        first["owner_status"]["reserved_units"] == 1
        and first["owner_status"]["remaining_units"] == 0,
        "one acquisition budget not retained",
    )

    result = cold["receipt"]["result"]
    require(result["schema"] == "perc1.owned-encoding.v2", "v2 source evidence missing")
    metadata, producer = result["source_evidence"], result["producer"]
    restored = verify_source_evidence(metadata, root / "owner")
    wire = decode_native_wire(result, source_root=root / "owner")
    observation = json.loads(wire)
    require(
        sha(restored["image"]) == source_sha, "retained source does not match original"
    )
    require(
        metadata["ocr"] is not None and metadata["ocr"]["words"],
        "actual OCR spans missing",
    )
    require(
        all(first[key] == cold[key] for key in ("verified_source_artifacts",)),
        "cold read did not verify original sidecar artifacts",
    )
    with Image.open(io.BytesIO(restored["image"])) as image:
        rgb = image.convert("RGB").tobytes()
    require(
        sha(rgb) == producer["transform"]["raster_rgb_sha256"],
        "retained raster mismatch",
    )
    expected = {
        "scope": scope,
        "source_frontier": observation["source_frontier"],
        "encoder_digest": observation["encoder_digest"],
        "latent_model_digest": observation["latent_model_digest"],
        "representation": observation["representation"],
        "feature_dimension": 16,
        "source_pin": observation["evidence"][0]["source"],
    }
    wire_path, raster_path, expected_path = (
        root / "native-wire.json",
        root / "native-raster.rgb",
        root / "native-expected.json",
    )
    for path, raw in ((wire_path, wire), (raster_path, rgb)):
        with path.open("xb") as stream:
            stream.write(raw)
    write_json(expected_path, expected)
    native = invoke(
        "04-native-qualification",
        [
            sys.executable,
            str(repo / "scripts/perc1_native_owner_qualification.py"),
            "--binary",
            str(args.native_binary.resolve(strict=True)),
            "--wire",
            str(wire_path),
            "--raster",
            str(raster_path),
            "--expected",
            str(expected_path),
            "--output",
            str(root / "native-owner"),
            "--input-classification",
            "captured_source",
        ],
    )
    require(
        native["status"] == "PASS_LOCAL_MECHANISM_ONLY" and native["invocations"] == 13,
        "native original-wire owner qualification incomplete",
    )
    require(
        pins == {str(path.relative_to(repo)): sha(path.read_bytes()) for path in code},
        "source changed during qualification",
    )
    report = {
        "schema": "perc1.real-source-native-qualification.v1",
        "status": "PASS_LOCAL_MECHANISM_ONLY",
        "scientific_status": "HOLD",
        "adoption": "NoUpdate",
        "source_code_sha256": pins,
        "source": {
            "relative_source": "training_data/images/" + source_path.name,
            "sha256": source_sha,
            "bytes": len(source_raw),
            "uri": metadata["source_uri"],
            "source_group": metadata["source_group"],
            "archive_sha256": acquisition["archive_sha256"],
            "origin_authenticated": False,
            "source_group_independence_verified": False,
        },
        "training": {
            "distinct_train_images": 8,
            "actual_backbone_batches": 8,
            "crop_features": 32,
            "pca_fits": 1,
            "dimension": 16,
            "neural_gradient_updates": 0,
            "pca_sha256": sha(projection_path.read_bytes()),
            "annotations_read": False,
            "evaluation_split_read": False,
        },
        "execution_counts": {
            "distinct_engineering_source_images": 1,
            "independent_real_tasks": 0,
            "source_cli_processes": 3,
            "source_callbacks": 1,
            "ocr_processes": 1,
            "online_backbone_batches": 1,
            "online_crops": 4,
            "total_backbone_batches_including_pca": 9,
            "native_processes": 13,
            "native_diagnostic_head_executions": 2,
        },
        "source_evidence": {
            "verified_artifact_count": len(restored),
            "evidence_sha256": metadata["evidence_sha256"],
            "artifacts": metadata["artifacts"],
            "ocr_span_count": len(metadata["ocr"]["words"]),
            "ocr_accuracy_verified": False,
            "native_text": metadata["native_text"],
            "full_document_text_consumed_by_native_head": False,
        },
        "continuity": {
            "original_wire_sha256": sha(wire),
            "original_wire_bytes": len(wire),
            "retained_rgb_sha256": sha(rgb),
            "owner_receipt_sha256": cold["receipt"]["receipt_sha256"],
            "scope_digest": scope_digest,
            "replay_receipt_identical": True,
            "cold_read_after_input_and_weight_copy_deleted": True,
            "replay_and_cold_read_new_capture_or_model_calls": 0,
            "sidecar_exact_artifacts_verified_after_deletion": True,
        },
        "native": native,
        "cost": {
            "source_stage": metadata["measurements"],
            "producer_stage": producer["measurements"],
            "pca_training": {
                "backbone_cold_load_ns": training_load_ns,
                "frame_stages": [
                    {
                        key: item["transform"][key]
                        for key in ("decode_ns", "preprocessing_ns", "inference_ns")
                    }
                    for item in training
                ],
                "projection_wall_ns": projection["training"]["wall_ns"],
                "projection_cpu_ns": projection["training"]["cpu_ns"],
            },
            "transform_stage": {
                key: producer["transform"][key]
                for key in ("decode_ns", "preprocessing_ns", "inference_ns")
            },
            "encoder_cold_load_ns": producer["worker"]["cold_load_ns"],
            "command_envelopes": steps,
            "driver_wall_ns": time.perf_counter_ns() - started,
            "driver_process_cpu_ns": time.process_time_ns() - cpu,
            "energy_joules": None,
            "provider_billing": None,
            "scope": "training, CLI startup/OCR/encoding/persistence/replay and native test commands measured; nested times overlap; prior scan/render and acquisition download unmeasured",
        },
        "limits": [
            "one fixed TRAIN page, neutral tiny crops and hand-authored native head",
            "PCA compression and native arithmetic do not establish semantic or terminal-task quality",
            "13 native calls exercise durability/recovery/negative controls, not 13 independent tasks",
            "OCR spans preserve engine output without proving transcription accuracy",
            "production daemon enrollment and task-benefit adoption remain unqualified",
        ],
        "production_daemon_integrated": False,
        "trained_semantic_head_executed": False,
        "raw_outputs_publication": "retain privately; publish only this summary, file manifest and reproduction source",
    }
    write_json(root / "REPORT.json", report)
    write_json(root / "FILE_MANIFEST.json", file_manifest(root))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "training-images",
        "acquisition-manifest",
        "weights",
        "native-binary",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--tesseract", type=Path, default=Path("/usr/bin/tesseract"))
    args = parser.parse_args()
    existing = args.output.exists()
    try:
        print(json.dumps(qualify(args), indent=2))
    except Exception as error:
        if not existing and args.output.is_dir():
            write_json(
                args.output / "FAILURE.json",
                {
                    "status": "FAILED",
                    "scientific_status": "HOLD",
                    "adoption": "NoUpdate",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
            )
            write_json(args.output / "FILE_MANIFEST.json", file_manifest(args.output))
        raise


if __name__ == "__main__":
    main()
