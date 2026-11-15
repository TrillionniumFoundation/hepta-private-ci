"""Validate collected neural wires against frozen pins and original captures.

The unchanged native probe checks each observation. This is observation-contract
readback; execution attestation, Cell admission and task qualification stay separate.
"""

import argparse
import io
import json
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

from perc1.producer import PREPROCESS
from perc1.schema import ActorObservation, Dataset, exact, integer, load, require, sha


def _child(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "receipt path escapes collector root")
    return path


def _regions(image, requested):
    """Independent full-view quadrant coverage, retaining declared stable IDs."""
    width, height = image.size
    require(
        width >= 2 and height >= 2 and width * height * 3 <= 8192,
        "native crop size mismatch",
    )
    xs, ys = (0, width // 2, width), (0, height // 2, height)
    boxes = [
        {
            "x": xs[x],
            "y": ys[y],
            "width": xs[x + 1] - xs[x],
            "height": ys[y + 1] - ys[y],
        }
        for y in range(2)
        for x in range(2)
    ]
    require(
        type(requested) is list and len(requested) == 4, "expected four crop quadrants"
    )
    for index, (item, box) in enumerate(zip(requested, boxes)):
        exact(item, "evidence_id x y width height")
        for key in box:
            integer(item[key], 1 if key in ("width", "height") else 0)
        require(
            {key: item[key] for key in box} == box
            and item["evidence_id"] == f"tile-{index // 2}-{index % 2}",
            "capture quadrant mismatch",
        )
    return requested


def validate_one(
    record, dataset, projection, pins, root, probe, output, scratch, number
):
    source = dataset.sources[record["source_id"]]
    require(record["status"] == "observed", "collector retained a failed observation")
    producer, native = record["producer"], record["native_wire"]
    require(
        record["receipt_sha256"]
        == sha({k: v for k, v in record.items() if k != "receipt_sha256"}),
        "collector receipt digest mismatch",
    )
    if producer is None:
        require(
            native is None and record["encoded"] is False,
            "OCR-only receipt exposes a native wire",
        )
        return {"status": "SKIPPED_OCR_ONLY", "source_id": source["id"]}
    require(
        record["encoded"] is True and type(native) is dict,
        "neural receipt lacks native wire",
    )
    request = exact(
        record["producer_request"],
        "schema operation_id capture_path capture_sha256 source_id observed_at_micros regions representation scope_digest source_frontier exact_text",
    )
    require(
        request["schema"] == "perc1.producer-request.v1"
        and producer["schema"] == "perc1.producer-receipt.v1"
        and producer["status"] == "executed",
        "producer schema/status mismatch",
    )
    require(producer["request_sha256"] == sha(request), "producer request changed")
    require(
        producer["receipt_sha256"]
        == sha({k: v for k, v in producer.items() if k != "receipt_sha256"}),
        "producer receipt changed",
    )
    require(
        request["source_id"] == source["id"]
        and request["capture_sha256"] == source["sha256"],
        "registered capture mismatch",
    )
    representation = record["representation"]
    require(
        representation in ("global", "dense")
        and request["representation"] == representation,
        "representation mismatch",
    )
    scope = sha(
        {"dataset_sha256": sha(dataset.value), "episode_id": source["episode_id"]}
    )
    frontier = sha(source)
    require(
        request["scope_digest"] == scope and request["source_frontier"] == frontier,
        "dataset scope/frontier mismatch",
    )
    raw = dataset.read(source["id"])
    with Image.open(io.BytesIO(raw)) as encoded:
        require(
            encoded.format in ("PNG", "JPEG")
            and getattr(encoded, "n_frames", 1) == 1
            and encoded.getexif().get(274, 1) == 1,
            "unsupported capture decode",
        )
        image = encoded.convert("RGB")
    locator = source["locator"]
    require(
        image.size == (locator["x1"] - locator["x0"], locator["y1"] - locator["y0"]),
        "registered document/capture dimensions mismatch",
    )
    regions = _regions(image, request["regions"])
    rgb = image.tobytes()
    timestamp = integer(request["observed_at_micros"], 1)
    require(
        timestamp * 1000 >= source["available_ns"],
        "capture precedes registered availability",
    )
    source_pin = {
        "source_id": source["id"],
        "origin_digest": list(bytes.fromhex(source["sha256"])),
        "content_digest": list(bytes.fromhex(sha(rgb))),
        "byte_length": len(rgb),
        "observed_at_micros": timestamp,
        "layout": {
            "kind": "raster",
            "width": image.width,
            "height": image.height,
            "channels": 3,
        },
    }
    code = {
        name: pins["code"][name + ".py"]
        for name in ("producer", "projection", "raster", "native", "schema")
    }
    require(
        producer["worker"]["code"] == code, "worker differs from frozen producer code"
    )
    model = {
        "architecture": "torchvision.mobilenet_v3_small.features",
        "backbone_sha256": pins["backbone_sha256"],
        "projection_sha256": pins["projection_sha256"],
        "producer_code_sha256": sha(code),
    }
    encoder = {
        "model": model,
        "preprocess": PREPROCESS,
        "representation": representation,
        "dimension": projection["dimension"],
        "global_pool": "mean crop features before projection",
    }
    require(
        producer["model"] == model and producer["encoder"] == encoder,
        "frozen model/encoder mismatch",
    )
    transform = producer["transform"]
    require(
        transform["capture_sha256"] == source["sha256"]
        and transform["raster_rgb_sha256"] == sha(rgb)
        and transform["raster_shape"] == [image.height, image.width, 3]
        and transform["backbone_sha256"] == pins["backbone_sha256"]
        and transform["producer_code_sha256"] == sha(code)
        and transform["preprocess"] == PREPROCESS,
        "capture/worker transform mismatch",
    )
    require(len(transform["crops"]) == len(regions), "transform crop count mismatch")
    for crop, region in zip(transform["crops"], regions):
        x, y, width, height = (region[key] for key in ("x", "y", "width", "height"))
        require(
            crop["region"] == region
            and crop["crop_rgb_sha256"]
            == sha(image.crop((x, y, x + width, y + height)).tobytes())
            and crop["crop_rgb_bytes"] == width * height * 3,
            "original crop coordinates/bytes mismatch",
        )
    wire_path = _child(root, native["path"])
    require(wire_path.stat().st_size <= 65536, "native wire exceeds capacity")
    wire = wire_path.read_bytes()
    require(
        len(wire) == native["byte_length"]
        and sha(wire) == native["sha256"] == producer["observation_sha256"],
        "native wire digest mismatch",
    )
    observation = load(wire_path)
    require(
        observation == producer["observation"],
        "native wire/producer observation mismatch",
    )
    require(
        len(observation["evidence"]) == len(regions), "native evidence count mismatch"
    )
    for item, region in zip(observation["evidence"], regions):
        coordinates = {
            "kind": "image_region",
            **{key: region[key] for key in ("x", "y", "width", "height")},
        }
        require(
            item["source"] == source_pin
            and item["coordinates"] == coordinates
            and item["evidence_id"] == region["evidence_id"],
            "native evidence source/coordinates mismatch",
        )
    checkpoint = sha(
        {
            "backbone_sha256": pins["backbone_sha256"],
            "projection_sha256": pins["projection_sha256"],
        }
    )
    actor = ActorObservation.parse(
        record["observation"],
        source,
        raw,
        {"checkpoint_sha256": checkpoint, "dimension": projection["dimension"]},
        representation + "_fixed",
    ).to_dict()
    require(
        len(actor["tokens"]) == len(observation["latents"]),
        "actor/native token count mismatch",
    )
    for index, (token, latent) in enumerate(
        zip(actor["tokens"], observation["latents"])
    ):
        loc = dict(source["locator"])
        if representation == "dense":
            region = regions[index]
            loc.update(x0=loc["x0"] + region["x"], y0=loc["y0"] + region["y"])
            loc.update(x1=loc["x0"] + region["width"], y1=loc["y0"] + region["height"])
        require(
            token["locator"] == loc
            and token["values"] == [v / 2**24 for v in latent["values_q24"]],
            "actor/native coordinates or latent values mismatch",
        )
    expected = {
        "scope_digest": list(bytes.fromhex(scope)),
        "source_frontier": list(bytes.fromhex(frontier)),
        "encoder_digest": list(bytes.fromhex(sha(encoder))),
        "latent_model_digest": list(bytes.fromhex(sha(model))),
        "representation": representation,
        "feature_dimension": projection["dimension"]
        * (1 if representation == "global" else 4),
        "source_pin": source_pin,
    }
    binding_path, result_path = (
        output / f"{number:06d}.expected.json",
        output / f"{number:06d}.result.json",
    )
    binding_path.write_text(json.dumps(expected, indent=2) + "\n")
    raster_path = scratch / "actor.rgb"
    raster_path.write_bytes(rgb)
    completed = subprocess.run(
        [
            str(probe),
            str(wire_path),
            str(raster_path),
            str(binding_path),
            str(result_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    require(
        completed.returncode == 0,
        "native validator rejected: " + completed.stderr[:1000],
    )
    result = load(result_path)
    require(
        result["status"] == "PASS" and result["wire_sha256"] == sha(wire),
        "native result mismatch",
    )
    return {
        "status": "PASS",
        "source_id": source["id"],
        "representation": representation,
        "collector_receipt_sha256": record["receipt_sha256"],
        "result": result,
    }


def run(
    dataset_path,
    projection_path,
    pins_path,
    collector_root,
    probe,
    build_record,
    output,
):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    dataset = Dataset(load(dataset_path), Path(dataset_path).parent)
    projection, pins, build = load(projection_path), load(pins_path), load(build_record)
    require(
        pins["schema"] == "perc1.document-execution-pins.v1"
        and pins["dataset_sha256"] == sha(dataset.value),
        "frozen dataset mismatch",
    )
    require(
        pins["projection_sha256"] == sha(projection)
        and projection["backbone_sha256"] == pins["backbone_sha256"],
        "frozen projection mismatch",
    )
    require(
        pins["preprocess_sha256"] == sha(PREPROCESS), "frozen preprocessing mismatch"
    )
    require(
        build["returncode"] == 0
        and build["sources_unchanged"]
        and build["binary_sha256"] == sha(Path(probe).read_bytes()),
        "native executable/build identity mismatch",
    )
    root, output, probe = (
        Path(collector_root).resolve(),
        Path(output),
        Path(probe).resolve(),
    )
    require(not output.exists(), "retain previous native batch attempts")
    output.mkdir(parents=True)
    index = load(root / "index.json")
    require(
        index["schema"] == "perc1.document-receipt-index.v1"
        and index["dataset_sha256"] == sha(dataset.value),
        "collector index identity mismatch",
    )
    entries = index["records"]
    require(type(entries) is list and entries, "empty collector index")
    results, seen = [], set()
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        for number, entry in enumerate(entries):
            try:
                path = _child(root, entry["path"])
                require(
                    path not in seen and path.stat().st_size <= 8 * 1024 * 1024,
                    "duplicate/excessive collector record",
                )
                seen.add(path)
                record = load(path)
                require(
                    record["source_id"] == entry["source_id"], "indexed source mismatch"
                )
                payload = path.read_bytes()
                require(
                    sha(payload) == entry["file_sha256"]
                    and len(payload) == entry["byte_length"],
                    "indexed record file changed",
                )
                require(
                    record["receipt_sha256"] == entry["receipt_sha256"]
                    and record["representation"] == entry["representation"]
                    and record["status"] == entry["status"],
                    "indexed receipt changed",
                )
                results.append(
                    validate_one(
                        record,
                        dataset,
                        projection,
                        pins,
                        root,
                        probe,
                        output,
                        Path(temporary),
                        number,
                    )
                )
            except Exception as error:
                results.append(
                    {
                        "status": "FAIL",
                        "entry": entry,
                        "error": type(error).__name__ + ": " + str(error),
                    }
                )
    inventory = {
        p.resolve()
        for p in (root / "records").glob("*.json")
        if not p.name.endswith(".native.json")
    }
    if seen != inventory:
        results.append(
            {
                "status": "FAIL",
                "error": "collector index does not cover every record file",
            }
        )
    counts = {
        key: sum(row["status"] == key for row in results)
        for key in ("PASS", "FAIL", "SKIPPED_OCR_ONLY")
    }
    report = {
        "schema": "perc1.native-batch.v1",
        "status": "PASS" if counts["FAIL"] == 0 and counts["PASS"] > 0 else "FAIL",
        "scope": "original capture bytes, frozen model binding and unchanged native observation validator",
        "scientific_status": "HOLD",
        "counts": counts,
        "results": results,
        "execution_pins_sha256": sha(pins),
        "dataset_sha256": sha(dataset.value),
        "native_build_sha256": sha(build),
        "wall_ns": time.perf_counter_ns() - started,
        "cpu_ns": time.process_time_ns() - cpu,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "dataset",
        "projection",
        "execution-pins",
        "collector-root",
        "probe",
        "build-record",
        "output",
    ):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    report = run(
        args.dataset,
        args.projection,
        args.execution_pins,
        args.collector_root,
        args.probe,
        args.build_record,
        args.output,
    )
    print(json.dumps({"status": report["status"], "counts": report["counts"]}))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
