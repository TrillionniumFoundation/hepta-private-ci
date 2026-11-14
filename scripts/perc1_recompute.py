"""Recompute retained neural outputs in a fresh process from frozen artifacts.

Exact tensor, feature and Q24 comparisons establish reproducible output values.
This does not independently attest the original worker, hardware or historical cost.
OCR is retained evidence and is not rerun by this command.
"""

import argparse
import json
import os
import time
from pathlib import Path

from perc1.producer import FrozenMobileNet, PREPROCESS, _regions
from perc1.projection import project
from perc1.schema import Dataset, load, require, sha


def _child(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "artifact escapes collector root")
    return path


def run(
    dataset_path,
    weights,
    projection_path,
    pins_path,
    collector_root,
    output,
    device="cpu",
):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output, root = Path(output), Path(collector_root).resolve()
    require(not output.exists(), "retain earlier recomputation attempts")
    output.mkdir(parents=True)
    report = {
        "schema": "perc1.recomputation.v1",
        "status": "FAIL",
        "scientific_status": "HOLD",
        "scope": "fresh-process exact recomputation of actual image tensors, backbone features and projected native Q24 values",
        "independent_hardware_attestation": False,
        "original_execution_attestation": False,
        "recompute_pid": os.getpid(),
        "results": [],
    }
    cache, seen, original_pids, groups, source_representations = (
        {},
        set(),
        set(),
        set(),
        set(),
    )
    worker = None
    try:
        dataset = Dataset(load(dataset_path), Path(dataset_path).parent)
        projection, pins = load(projection_path), load(pins_path)
        require(
            pins["schema"] == "perc1.document-execution-pins.v1"
            and pins["dataset_sha256"] == sha(dataset.value),
            "frozen dataset mismatch",
        )
        require(
            pins["projection_sha256"] == sha(projection)
            and pins["backbone_sha256"] == projection["backbone_sha256"],
            "frozen projection mismatch",
        )
        require(
            pins["preprocess_sha256"] == sha(PREPROCESS),
            "frozen preprocessing mismatch",
        )
        worker = FrozenMobileNet(weights, pins["backbone_sha256"], device)
        expected_code = {
            name: pins["code"][name + ".py"]
            for name in ("producer", "projection", "raster", "native", "schema")
        }
        require(
            worker.code == expected_code,
            "restore the exact frozen producer source before recomputation",
        )
        index = load(root / "index.json")
        require(
            index["schema"] == "perc1.document-receipt-index.v1"
            and index["dataset_sha256"] == pins["dataset_sha256"],
            "collector index identity mismatch",
        )
        require(
            type(index["records"]) is list and index["records"], "empty collector index"
        )
        report.update(
            execution_pins_sha256=sha(pins),
            dataset_sha256=sha(dataset.value),
            backbone_sha256=worker.weights_sha256,
            projection_sha256=sha(projection),
            producer_code=worker.code,
            versions=worker.versions,
            device=worker.device,
            device_name=worker.device_name,
            cold_load_ns=worker.cold_load_ns,
        )
        for entry in index["records"]:
            result = {
                "path": entry["path"],
                "source_id": entry["source_id"],
                "status": "FAIL",
            }
            try:
                path = _child(root, entry["path"])
                require(
                    path not in seen and path.stat().st_size <= 8 * 1024 * 1024,
                    "duplicate/excessive receipt",
                )
                seen.add(path)
                payload = path.read_bytes()
                require(
                    sha(payload) == entry["file_sha256"]
                    and len(payload) == entry["byte_length"],
                    "indexed file changed",
                )
                record = load(path)
                require(
                    record["receipt_sha256"]
                    == entry["receipt_sha256"]
                    == sha(
                        {
                            key: value
                            for key, value in record.items()
                            if key != "receipt_sha256"
                        }
                    ),
                    "collector receipt digest mismatch",
                )
                require(
                    record["source_id"] == entry["source_id"]
                    and record["status"] == entry["status"] == "observed"
                    and record["representation"] == entry["representation"],
                    "failed/mismatched collected observation",
                )
                if record["producer"] is None:
                    require(
                        record["encoded"] is False and record["native_wire"] is None,
                        "invalid OCR-only receipt",
                    )
                    result["status"] = "SKIPPED_OCR_ONLY"
                else:
                    producer, request = record["producer"], record["producer_request"]
                    require(
                        record["encoded"] is True and record["native_wire"] is not None,
                        "unencoded neural receipt",
                    )
                    source = dataset.sources[record["source_id"]]
                    representation = record["representation"]
                    require(
                        representation in ("global", "dense")
                        and representation == request["representation"],
                        "representation mismatch",
                    )
                    require(
                        request["source_id"] == source["id"]
                        and request["capture_sha256"] == source["sha256"],
                        "original capture mismatch",
                    )
                    require(
                        producer["receipt_sha256"]
                        == sha(
                            {
                                key: value
                                for key, value in producer.items()
                                if key != "receipt_sha256"
                            }
                        )
                        and producer["request_sha256"] == sha(request),
                        "producer receipt/request changed",
                    )
                    require(
                        producer["worker"]["code"] == expected_code
                        and producer["worker"]["versions"] == worker.versions
                        and producer["worker"]["device"] == worker.device,
                        "exact recomputation runtime differs from original",
                    )
                    expected_model = {
                        "architecture": "torchvision.mobilenet_v3_small.features",
                        "backbone_sha256": worker.weights_sha256,
                        "projection_sha256": sha(projection),
                        "producer_code_sha256": sha(expected_code),
                    }
                    require(
                        producer["model"] == expected_model,
                        "frozen model binding mismatch",
                    )
                    original_pids.add(producer["worker"]["pid"])
                    # PID values can repeat across time or process namespaces.
                    # Separate CLI invocation is a caller obligation; a numeric
                    # PID comparison is diagnostic, never process attestation.
                    groups.add(source["group"])
                    source_representations.add((source["id"], representation))
                    raw = dataset.read(source["id"])
                    _regions(request["regions"], 2**32 - 1, 2**32 - 1, 8192)
                    key = sha(
                        {
                            "capture_sha256": sha(raw),
                            "regions": request["regions"],
                            "representation": representation,
                        }
                    )
                    cached = key in cache
                    if not cached:
                        recompute_start = time.perf_counter_ns()
                        _, features, transform = worker.features(
                            raw, request["regions"]
                        )
                        selected = (
                            features.mean(axis=0, keepdims=True)
                            if representation == "global"
                            else features
                        )
                        projected = project(selected, projection, worker.weights_sha256)
                        quantized = [
                            [round(float(value) * 2**24) for value in row]
                            for row in projected.tolist()
                        ]
                        cache[key] = {
                            "transform": transform,
                            "q24": quantized,
                            "recompute_wall_ns": time.perf_counter_ns()
                            - recompute_start,
                        }
                        (output / (key + ".json")).write_text(
                            json.dumps(
                                {
                                    "schema": "perc1.recomputed-values.v1",
                                    "key": key,
                                    "first_source_id": source["id"],
                                    "representation": representation,
                                    "transform": transform,
                                    "q24": quantized,
                                    "q24_sha256": sha(quantized),
                                    "recompute_wall_ns": cache[key][
                                        "recompute_wall_ns"
                                    ],
                                },
                                indent=2,
                            )
                            + "\n"
                        )
                    actual, original = cache[key]["transform"], producer["transform"]
                    for field in (
                        "capture_sha256",
                        "capture_bytes",
                        "raster_rgb_sha256",
                        "raster_shape",
                        "preprocess",
                        "crops",
                        "features_shape",
                        "features_f32le_sha256",
                        "backbone_sha256",
                        "producer_code_sha256",
                    ):
                        require(
                            actual[field] == original[field],
                            "recomputed transform/feature mismatch: " + field,
                        )
                    require(
                        cache[key]["q24"]
                        == [
                            item["values_q24"]
                            for item in producer["observation"]["latents"]
                        ],
                        "recomputed Q24 values differ",
                    )
                    result.update(
                        status="PASS",
                        representation=representation,
                        input_key=key,
                        cache_reused=cached,
                        receipt_sha256=record["receipt_sha256"],
                        features_sha256=actual["features_f32le_sha256"],
                        q24_sha256=sha(cache[key]["q24"]),
                    )
            except Exception as error:
                result["error"] = {"type": type(error).__name__, "message": str(error)}
            report["results"].append(result)
        inventory = {
            path.resolve()
            for path in (root / "records").glob("*.json")
            if not path.name.endswith(".native.json")
        }
        require(inventory == seen, "collector index omits receipt files")
    except Exception as error:
        report["setup_or_inventory_error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    counts = {
        status: sum(row["status"] == status for row in report["results"])
        for status in ("PASS", "FAIL", "SKIPPED_OCR_ONLY")
    }
    report.update(
        counts=counts,
        actual_model_executions=worker.calls if worker else 0,
        completed_value_sets=len(cache),
        covered_neural_receipts=counts["PASS"],
        unique_source_representations=len(source_representations),
        source_groups=len(groups),
        original_worker_pids=sorted(original_pids),
        distinct_recompute_pid=os.getpid() not in original_pids,
        process_identity_scope="PID comparison is diagnostic only; invoke this CLI separately. No process or hardware attestation.",
        wall_ns=time.perf_counter_ns() - started,
        cpu_ns=time.process_time_ns() - cpu,
        command_code_sha256=sha(Path(__file__).read_bytes()),
    )
    if (
        counts["PASS"] > 0
        and counts["FAIL"] == 0
        and "setup_or_inventory_error" not in report
    ):
        report["status"] = "PASS"
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "dataset",
        "weights",
        "projection",
        "execution-pins",
        "collector-root",
        "output",
    ):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    report = run(
        args.dataset,
        args.weights,
        args.projection,
        args.execution_pins,
        args.collector_root,
        args.output,
        args.device,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "counts": report["counts"],
                "actual_model_executions": report["actual_model_executions"],
            }
        )
    )
    raise SystemExit(0 if report["status"] == "PASS" else 1)
