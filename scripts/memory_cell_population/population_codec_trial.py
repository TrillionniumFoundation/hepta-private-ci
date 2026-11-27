"""Fixed int8 primary and int4 secondary evaluation of the full-source single cell."""

import hashlib
from pathlib import Path
import time

from checkpoint_codec import encode_checkpoint, decode_checkpoint
from parametric_owner import Frontier, ParametricOwner
from population_reads import fresh_read, score_single, source_capabilities


def evaluate_codecs(model, data, training, original, output, write_json):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    version = training["versions"]["single"][0]
    source = Path(version["directory"])
    original_inventory = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source.iterdir()
        if p.is_file()
    }
    original_bytes = sum(p.stat().st_size for p in source.iterdir() if p.is_file())
    owner = ParametricOwner(output / "owners.sqlite3")
    frontier = Frontier(data["scope"], 1, ())
    probes = data["retention_final"] + data["transfer_final"] + data["ood_final"]
    capabilities = source_capabilities(data["sources"])
    variants = {}
    for bits in (8, 4):
        packed, materialized = (
            output / f"int{bits}-packed",
            output / f"int{bits}-materialized",
        )
        started = time.perf_counter()
        encoded = encode_checkpoint(
            source,
            packed,
            expected_manifest_sha256=version["manifest_sha256"],
            allowed_roots=version["roots"],
            revoked_roots=(),
            bits=bits,
        )
        encode_seconds = time.perf_counter() - started
        started = time.perf_counter()
        decoded = decode_checkpoint(
            packed,
            materialized,
            expected_codec_sha256=encoded["codec_manifest_sha256"],
            allowed_roots=version["roots"],
            revoked_roots=(),
        )
        decode_seconds = time.perf_counter() - started
        derived = {
            **version,
            "directory": str(materialized),
            "manifest_sha256": decoded["manifest_sha256"],
            "roots": decoded["roots"],
        }
        write_json(
            output / f"int{bits}-derivation.json",
            {
                "encoding": encoded,
                "decoding": decoded,
                "version": derived,
                "encode_seconds": encode_seconds,
                "decode_seconds": decode_seconds,
            },
        )
        journal = fresh_read(
            model,
            derived,
            [p["question"] for p in probes],
            output,
            f"codec-{bits}",
            owner,
            frontier,
            write_json,
        )
        scored = score_single(probes, journal, derived, capabilities)
        losses = {
            name: original[name]["accuracy"] - scored["metrics"][name]["accuracy"]
            for name in ("retention", "transfer")
        }
        ratio = encoded["packed_artifact_bytes"] / original_bytes
        variants[str(bits)] = {
            "bits": bits,
            "primary": bits == 8,
            "encoding": encoded,
            "decoding": decoded,
            "version": derived,
            "metrics": scored["metrics"],
            "quality_loss": losses,
            "packed_complete_ratio": ratio,
            "storage_ratio_gate": ratio <= 0.35,
            "retention_loss_gate": losses["retention"] <= 0.02 + 1e-12,
            "transfer_loss_gate": losses["transfer"] <= 0.02 + 1e-12,
            "owner_admitted_before_and_after": journal[
                "owner_admitted_before_and_after"
            ],
            "costs": {
                "encode_seconds": encode_seconds,
                "decode_seconds": decode_seconds,
                "fresh_process_wall_seconds": journal["fresh_process_wall_seconds"],
                "generation_seconds": sum(r["seconds"] for r in journal["rows"]),
                "input_tokens": sum(r["input_tokens"] for r in journal["rows"]),
                "generated_tokens": sum(r["generated_tokens"] for r in journal["rows"]),
                "actual_queries": len(journal["rows"]),
                "packed_artifact_bytes": encoded["packed_artifact_bytes"],
                "materialized_checkpoint_bytes": decoded[
                    "materialized_checkpoint_bytes"
                ],
                "loaded_adapter_tensor_bytes": decoded["decoded_tensor_bytes"],
            },
            "quantized_execution": False,
            "posthoc_selection": False,
            "production_accepted": False,
        }
        write_json(output / f"int{bits}-assessments.json", scored)
    after = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source.iterdir()
        if p.is_file()
    }
    if after != original_inventory:
        raise ValueError("codec derivation changed the retained original candidate")
    primary = variants["8"]
    report = {
        "schema": "hepta.memory-population.codec-result.v1",
        "fixed_candidate": "single",
        "primary_bits": 8,
        "secondary_bits": 4,
        "original_complete_checkpoint_bytes": original_bytes,
        "original_inventory_before_and_after": original_inventory,
        "variants": variants,
        "primary_gate_passed": all(
            primary[k]
            for k in (
                "storage_ratio_gate",
                "retention_loss_gate",
                "transfer_loss_gate",
                "owner_admitted_before_and_after",
            )
        ),
        "owner_database_bytes": (output / "owners.sqlite3").stat().st_size,
        "original_plus_packed_plus_materialized_all_retained": True,
        "quantized_execution": False,
        "net_compression_advantage_proven": False,
        "production_accepted": False,
    }
    write_json(output / "result.json", report)
    return report
