"""Fixed numeric sources, charged source archives and source-free read process."""

import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

from .codec import (
    compress_bytes,
    decode_exact,
    decode_factor,
    encode_factor,
    exact_matrix_archives,
    source_digest,
)
from .factor_cell import FactorBank


def json_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()
            + b"\n"
        )


def write_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def datasets(source_dir, settings, seeds):
    root = Path(source_dir)
    for domain in settings["numeric_domains"]:
        path = root / (domain + ".json")
        source = json.loads(path.read_bytes())
        values = np.asarray(source["values"], dtype=np.int32)
        metadata = {k: v for k, v in source.items() if k != "values"}
        metadata["canonical_source_json_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        metadata["task"] = (
            "Previously written published numeric observations, addressed by source/year/month. No forecast claims."
        )
        groups = min(settings["cells"], len(values))
        routes = np.minimum(
            groups - 1, np.arange(len(values)) * groups // len(values)
        ).astype(np.uint8)
        yield domain, values, routes, metadata, float(source["scale"]), list(seeds)
    if settings["include_digits"]:
        path = (
            root.parents[2] / "memory-cell-v2" / "sources" / "external" / "digits.npz"
        )
        with np.load(path, allow_pickle=False) as source:
            values = source["X"].astype(np.int32)
            routes = source["y"].astype(np.uint8)
        metadata = {
            "domain": "digits-pixels",
            "record_axis": "original dataset row index",
            "field_axis": "row-major 8 by 8 pixel coordinate",
            "rows": len(values),
            "columns": 64,
            "scale": 1,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "task": "Numeric pixel recall on the existing Digits source; not a new independent domain",
            "predeclared_partition": "Original digit label is available only during write; its deployed row-to-cell assignment is serialized and charged.",
        }
        yield "digits-pixels", values, routes, metadata, 1.0, list(seeds)
    for seed in seeds:
        rng = np.random.default_rng(seed)
        n, d, groups = (
            settings["synthetic_rows"],
            settings["synthetic_columns"],
            settings["cells"],
        )
        routes = np.minimum(groups - 1, np.arange(n) * groups // n).astype(np.uint8)
        latents = rng.integers(-7, 8, size=(n, 2))
        decoders = rng.integers(-7, 8, size=(groups, 2, d))
        centers = rng.integers(-80, 81, size=(groups, d))
        structured = (
            np.einsum("nr,nrd->nd", latents, decoders[routes]) + centers[routes]
        )
        random = rng.integers(-200, 201, size=(n, d))
        selectors = rng.random((n, d))
        for mixture in settings["random_mix"]:
            values = np.where(selectors < mixture, random, structured).astype(np.int32)
            name = (
                "synthetic-mix-" + str(mixture).replace(".", "p") + "-seed-" + str(seed)
            )
            metadata = {
                "domain": name,
                "rows": n,
                "columns": d,
                "scale": 1,
                "generator": "Four integer rank-two local subspaces; independent bounded random replacement per coordinate",
                "seed": int(seed),
                "random_replacement_probability": mixture,
                "random_alphabet_size": 401,
                "random_source_entropy_bits_per_value_when_probability_one": float(
                    np.log2(401)
                ),
                "record_axis": "generated row index",
                "field_axis": "generated field index",
                "task": "Previously written numeric recall; random-source outcomes must not be generalized as universal compression.",
            }
            yield name, values, routes, metadata, 1.0, [seed]


def metrics(predictions, truth, scale, variance):
    errors = np.asarray(predictions, dtype=np.float64) - truth.astype(np.float64)
    mse = float(np.mean(errors**2))
    return {
        "queries": len(errors),
        "mse_scaled_integer": mse,
        "normalized_mse": mse / max(variance, 1e-30),
        "mae_original_units": float(np.mean(np.abs(errors)) / scale),
        "rmse_original_units": float(np.sqrt(mse) / scale),
        "max_error_original_units": float(np.max(np.abs(errors)) / scale),
        "exact_accuracy": float(np.mean(errors == 0)),
    }


def prepare_archives(directory, values, metadata):
    common = compress_bytes(json_bytes(metadata), "best")
    write_bytes(directory / "address-provenance.bin", common)
    started = time.perf_counter()
    baselines = exact_matrix_archives(values)
    baseline_seconds = time.perf_counter() - started
    records = []
    for name, archive in baselines.items():
        path = directory / "exact-baselines" / (name.replace("/", "-") + ".bin")
        write_bytes(path, archive)
        started = time.perf_counter()
        restored, mask = decode_exact(archive, hashlib.sha256(archive).hexdigest())
        if not np.array_equal(restored, values) or not mask.all():
            raise RuntimeError("strong exact baseline failed source reconstruction")
        records.append(
            {
                "name": name,
                "archive_bytes": len(archive),
                "complete_stored_bytes": len(archive) + len(common),
                "sha256": hashlib.sha256(archive).hexdigest(),
                "decode_seconds": time.perf_counter() - started,
                "exact_reconstruction": True,
                "path": str(path),
            }
        )
    best = min(records, key=lambda r: r["archive_bytes"])
    result = {
        "address_provenance_bytes": len(common),
        "address_provenance_sha256": hashlib.sha256(common).hexdigest(),
        "source_values": values.size,
        "canonical_int32_value_bytes": values.nbytes,
        "source_sha256": source_digest(values, np.ones(values.shape, dtype=bool)),
        "raw_official_provenance_file_bytes": metadata.get("raw_source", {}).get(
            "bytes", 0
        ),
        "source_json_evidence_retention": "Repository source files remain research evidence; not required by an isolated read or archived replay. Complete research retention is reported separately.",
        "codec_search_encode_seconds": baseline_seconds,
        "codec_candidates": records,
        "strongest_exact_baseline": best,
        "decoded_exact_cache_array_bytes": values.nbytes + values.size,
    }
    write_json(directory / "archive-accounting.json", result)
    return result


def source_codec_curve(directory, values, fitted, common_bytes, exact_bytes):
    curve, best = [], None
    for choice in fitted["candidates"][0]:
        bank = FactorBank(fitted["routes"], fitted["mask"], (choice["block"],))
        archive, receipt = encode_factor(bank, values)
        restored, mask = decode_factor(
            archive,
            model=FactorBank.from_bytes(bank.to_bytes(), bank.digest),
            expected_sha256=receipt["archive_sha256"],
        )
        if not np.array_equal(restored, values) or not mask.all():
            raise RuntimeError("factor residual did not reconstruct written source")
        predictions = bank.reconstruct()
        error = predictions.astype(np.float64) - values
        record = receipt | {
            "rank": choice["rank"],
            "pure_parameter_mse": float(np.mean(error**2)),
            "pure_parameter_exact_accuracy": float(np.mean(error == 0)),
            "complete_stored_bytes": receipt["complete_standalone_bytes"]
            + common_bytes,
            "exact_source_ratio": receipt["complete_standalone_bytes"] / exact_bytes,
            "explicit_residual_exact_reconstruction": True,
        }
        curve.append(record)
        if best is None or receipt["complete_standalone_bytes"] < best[0]:
            best = (receipt["complete_standalone_bytes"], bank, archive, record)
    best[1].save(directory / "best-source-codec-model.bin")
    write_bytes(directory / "best-source-residual.bin", best[2])
    write_json(
        directory / "source-codec-curve.json",
        {
            "candidates": curve,
            "best": best[3],
            "selection": "Minimum complete model plus residual archive bytes over all written-source global-rank candidates; no hidden-query evaluation enters this choice.",
            "all_candidate_encode_seconds": sum(r["encode_seconds"] for r in curve),
            "deployed_model_counted_once": True,
        },
    )
    return best[3] | {
        "selection_search_encode_seconds": sum(r["encode_seconds"] for r in curve)
    }


def read_requests(request_path, output_path):
    requests = json.loads(Path(request_path).read_bytes())
    results = []
    for request in requests:
        if set(request) != {"id", "artifact", "sha256", "rows", "columns"}:
            raise ValueError(
                "isolated read accepts only model identities and value-free coordinates"
            )
        bank = FactorBank.load(request["artifact"], request["sha256"])
        started = time.perf_counter()
        answers = bank.read(request["rows"], request["columns"])
        results.append(
            {
                "id": request["id"],
                "answers": answers,
                "read_seconds": time.perf_counter() - started,
                "artifact_sha256": bank.digest,
                "resident_model_array_bytes": bank.parameter_bytes
                + bank.routes.nbytes
                + bank.mask.nbytes,
            }
        )
    write_json(
        Path(output_path),
        {
            "input_contract": "Only saved FactorBank artifacts and value-free row/column addresses. No source values, exact archive, residual, training closure or answer catalog supplied.",
            "process_id": os.getpid(),
            "results": results,
        },
    )
