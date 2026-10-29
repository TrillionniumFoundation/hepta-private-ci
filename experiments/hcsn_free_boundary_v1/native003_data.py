"""Generate an independently identified fresh MNIST extension without inference.

Reuse the original reader, episode construction and train-fitted transforms.
An exact original-test prefix replay is required before new episodes are saved.
The parent records complete child CPU, including imports and artifact writes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


DATA_SEED = 912201
OLD_TEST_COUNT = 512
FRESH_COUNT = 128


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(cache, original, output):
    import numpy as np
    from ..continuous_spiking_network import data as reader

    cache, original, output = map(Path, (cache, original, output))
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "fresh_mnist.npz"
    manifest_path = destination.with_suffix(".json")
    if destination.exists() or manifest_path.exists():
        raise FileExistsError("Refusing to replace existing fresh-test artifacts")

    old_json = original / "mnist.json"
    old_npz = original / "mnist.npz"
    sources_path = original / "SOURCES.json"
    manifest = json.loads(old_json.read_text())
    sources = json.loads(sources_path.read_text())
    if manifest["task"] != "mnist" or manifest["seed"] != DATA_SEED:
        raise ValueError("Original MNIST task or pinned data seed differs")
    if file_hash(old_npz) != manifest["sha256"]:
        raise ValueError("Original dataset differs from its frozen manifest")
    identity = hashlib.sha256(json.dumps(sources["files"], sort_keys=True).encode()).hexdigest()
    if not identity == sources["sha256"] == manifest["source_manifest_sha256"]:
        raise ValueError("Original raw-source manifest identity differs")

    raw_receipts = []
    for item in sources["files"]:
        if not item["path"].startswith("mnist/"):
            continue
        raw = cache / item["path"]
        digest = file_hash(raw)
        if raw.stat().st_size != item["bytes"] or digest != item["sha256"]:
            raise ValueError(f"Raw MNIST source differs: {item['path']}")
        raw_receipts.append({"path": item["path"], "bytes": raw.stat().st_size,
                             "sha256": digest})
    if len(raw_receipts) != 4:
        raise ValueError("Expected all four pinned MNIST IDX archives")

    reader_path = Path(reader.__file__).resolve()
    wrapper_path = Path(__file__).with_name("datasets.py")
    code_hashes = {"native003_data.py": file_hash(__file__),
                   "continuous_spiking_network/data.py": file_hash(reader_path),
                   "hcsn_free_boundary_v1/datasets.py": file_hash(wrapper_path)}
    images = reader._mnist(cache)
    data = reader._real_split("mnist", OLD_TEST_COUNT + FRESH_COUNT, "test",
                              DATA_SEED, 32, images, None)
    data.validate()
    for transform in manifest["transforms"]:
        if transform["fit_split"] != "train":
            raise ValueError("Only original train-fitted transforms are permitted")
        start, stop = transform["columns"]
        presence = transform["presence_column"]
        mean = np.asarray(transform["mean"], dtype=np.float32)
        std = np.asarray(transform["std"], dtype=np.float32)
        if mean.shape != (stop - start,) or std.shape != mean.shape or np.any(std <= 0):
            raise ValueError("Invalid pinned transform statistics")
        present = data.x[..., presence:presence + 1] > 0
        data.x[..., start:stop] = np.where(present,
                                          (data.x[..., start:stop] - mean) / std, 0)
    target = np.full(data.dt.shape, -100, dtype=np.int64)
    target[:, -1] = data.y
    prefix_arrays = {"test_x": data.x[:OLD_TEST_COUNT],
                     "test_dt": data.dt[:OLD_TEST_COUNT],
                     "test_y": target[:OLD_TEST_COUNT]}
    prefix_checks = {}
    with np.load(old_npz, allow_pickle=False) as old:
        for name, generated in prefix_arrays.items():
            expected = old[name]
            matched = (generated.dtype == expected.dtype
                       and np.array_equal(generated, expected))
            prefix_checks[name] = {"exact_equal": bool(matched),
                                   "shape": list(generated.shape), "dtype": str(generated.dtype)}
            if not matched:
                raise ValueError(f"Original 512-example prefix does not reproduce {name}")
    old_metadata = manifest["splits"]["test"]
    for name, expected in old_metadata.items():
        if isinstance(expected, list):
            generated = (data.sample_ids.tolist() if name == "episode_ids"
                         else data.metadata[name])[:OLD_TEST_COUNT]
            if generated != expected:
                raise ValueError(f"Original test metadata does not reproduce {name}")
            prefix_checks[name] = {"exact_equal": True, "count": len(generated)}
    if len(old_metadata["image_source_ids"]) != OLD_TEST_COUNT:
        raise ValueError("Unexpected original test length")

    fresh_metadata = {
        name: value[OLD_TEST_COUNT:]
        for name, value in data.metadata.items() if isinstance(value, list)
    }
    fresh_metadata["episode_ids"] = data.sample_ids[OLD_TEST_COUNT:].tolist()
    fresh_metadata["episodes"] = FRESH_COUNT
    fresh_metadata["unique_images"] = len(set(fresh_metadata["image_source_ids"]) - {""})
    fresh_metadata["unique_recordings"] = 0
    fresh_ids = set(fresh_metadata["image_source_ids"])
    if len(fresh_ids) != FRESH_COUNT or "" in fresh_ids:
        raise ValueError("Fresh episodes must contain 128 distinct source images")
    disjoint = {}
    for split in ("train", "val", "test"):
        overlap = fresh_ids.intersection(manifest["splits"][split]["image_source_ids"])
        episode_overlap = set(fresh_metadata["episode_ids"]).intersection(
            manifest["splits"][split]["episode_ids"])
        if overlap or episode_overlap:
            raise ValueError(f"Fresh source/episode leakage into original {split}")
        disjoint[split] = {"image_source_overlap": 0, "episode_id_overlap": 0,
                           "original_episodes": len(manifest["splits"][split]["episode_ids"])}

    fresh = {"test_x": data.x[OLD_TEST_COUNT:], "test_dt": data.dt[OLD_TEST_COUNT:],
             "test_y": target[OLD_TEST_COUNT:]}
    if not all(np.isfinite(value).all() for value in fresh.values()):
        raise ValueError("Nonfinite fresh data")
    if not np.all(fresh["test_y"][:, :-1] == -100):
        raise ValueError("Only final-step labels may be supervised")
    # No fitting, model import, training, logits or prediction occurs in this script.
    np.savez_compressed(destination, **fresh)
    output_manifest = {
        "schema": "hcsn-native003-fresh-mnist.v1", "task": "mnist", "seed": DATA_SEED,
        "sha256": file_hash(destination), "input_dim": 64, "output_dim": 10,
        "selection": {"reader": "_real_split('mnist',640,'test',912201,32,images,None)",
                      "slice_start_inclusive": OLD_TEST_COUNT,
                      "slice_stop_exclusive": OLD_TEST_COUNT + FRESH_COUNT},
        "splits": {"test": fresh_metadata}, "transforms": manifest["transforms"],
        "transform_fit": "Copied original training statistics; no fitting in this extension",
        "original": {"directory": str(original.resolve()),
                     "mnist_npz_sha256": manifest["sha256"],
                     "mnist_json_sha256": file_hash(old_json),
                     "source_manifest_file_sha256": file_hash(sources_path),
                     "source_manifest_identity_sha256": identity},
        "raw_mnist": raw_receipts, "code_sha256": code_hashes,
        "prefix_reproduction": prefix_checks, "disjoint_from_original": disjoint,
        "model_inference_performed": False, "new_statistics_fitted": False,
        "array_shapes": {name: list(value.shape) for name, value in fresh.items()},
        "array_dtypes": {name: str(value.dtype) for name, value in fresh.items()},
    }
    # Bind the receipt to unchanged reader, wrapper, original manifest and sources.
    if (code_hashes["native003_data.py"] != file_hash(__file__)
            or code_hashes["continuous_spiking_network/data.py"] != file_hash(reader_path)
            or code_hashes["hcsn_free_boundary_v1/datasets.py"] != file_hash(wrapper_path)
            or manifest["sha256"] != file_hash(old_npz)):
        raise RuntimeError("Source or original dataset changed during generation")
    manifest_path.write_text(json.dumps(output_manifest, indent=2) + "\n")
    print(json.dumps({"path": str(destination), "sha256": output_manifest["sha256"],
                      "episodes": FRESH_COUNT, "prefix_exact": True, "all_disjoint": True}))


def measured_build(cache, original, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / "generation_receipt.json"
    if receipt_path.exists():
        raise FileExistsError("Refusing to replace an existing complete-generation receipt")
    command = [sys.executable, "-m", "experiments.hcsn_free_boundary_v1.native003_data",
               "--cache", str(cache), "--original", str(original),
               "--output", str(output), "--worker"]
    environment = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        environment[name] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.perf_counter()
    with (output / "generation_stdout.txt").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=environment)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = {"schema": "hcsn-native003-data-generation-receipt.v1",
               "measurement": "os.wait4 child rusage; includes imports, raw reads, checks and writes",
               "command": command, "returncode": process.returncode,
               "child_user_cpu_seconds": usage.ru_utime,
               "child_system_cpu_seconds": usage.ru_stime,
               "child_total_cpu_seconds": usage.ru_utime + usage.ru_stime,
               "wall_seconds": time.perf_counter() - started,
               "child_peak_rss_kib_linux": usage.ru_maxrss,
               "thread_environment": {name: environment[name] for name in (
                   "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                   "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
               "source_sha256": file_hash(__file__), "python": sys.version,
               "model_inference_performed": False}
    for filename in ("fresh_mnist.npz", "fresh_mnist.json", "generation_stdout.txt"):
        path = output / filename
        if path.exists():
            receipt[f"{filename}_sha256"] = file_hash(path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    if process.returncode:
        raise RuntimeError(f"Data generation failed; retained receipt and log in {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        build(args.cache, args.original, args.output)
    else:
        measured_build(args.cache, args.original, args.output)


if __name__ == "__main__":
    main()
