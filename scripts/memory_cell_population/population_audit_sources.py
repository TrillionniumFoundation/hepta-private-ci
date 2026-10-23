"""Independent source/protocol identity and lossless typed-baseline audit."""

import json
import lzma
from pathlib import Path
import sqlite3
import struct
import zlib

from population_audit_artifacts import (
    SEEDS,
    _bytes,
    _digest,
    _hash,
    _json,
    _read,
    _require,
    _same,
)


def _exact(sources, operation):
    kind = operation["kind"]
    if kind == "semantic":
        rows = [
            r
            for r in sources
            if r["kind"] == kind
            and (r["entity"], r["relation"])
            == (operation["entity"], operation["relation"])
        ]
        return (
            (rows[0]["value"], [rows[0]["source_digest"]]) if rows else ("unknown", [])
        )
    if kind in ("event_at", "event_asof"):
        rows = [
            r
            for r in sources
            if r["kind"] == "episode" and r["entity"] == operation["entity"]
        ]
        selected = (
            [r for r in rows if r["day"] == operation["day"]]
            if kind == "event_at"
            else [r for r in rows if r["day"] <= operation["day"]]
        )
        roots = sorted(
            r["source_digest"] for r in (selected if kind == "event_at" else rows)
        )
        return (
            max(selected, key=lambda r: r["day"])["location"] if selected else "unknown"
        ), roots
    rows = [
        r
        for r in sources
        if r["kind"] == "procedure" and r["rule"] == operation["rule"]
    ]
    if not rows:
        return "unknown", []
    rule = rows[0]
    return str(
        (rule["multiplier"] * operation["input"] + rule["offset"]) % rule["modulus"]
    ), [rule["source_digest"]]


def _inputs(directory, result):
    from population_fixtures import dataset

    data, protocol = (
        _json(directory / "dataset.json"),
        _json(directory / "protocol.json"),
    )
    seed = result["seed"]
    _require(type(seed) is int and seed in SEEDS, "registered seed")
    _same(data, dataset(seed), "unchanged public seed and retained fixture generator")
    _require(result["protocol_sha256"] == _digest(protocol), "trial protocol pin")
    commitments = {
        "seeds": list(SEEDS),
        "parent": {"rank": 4, "source_examples": 16, "updates": 512},
        "single": {"rank": 8, "source_examples": 64, "updates": 1024},
        "split": {
            "rank_per_cell": 4,
            "cells": 2,
            "source_examples_per_cell": 32,
            "updates_per_cell": 512,
        },
        "model": "HuggingFaceTB/SmolLM2-135M-Instruct",
        "model_revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac",
        "identical_source_and_runtime_identity_across_seeds": True,
        "general_memory_proven": False,
        "production_accepted": False,
    }
    for key, value in commitments.items():
        _same(protocol[key], value, "registered protocol")
    _require(
        protocol["codec"]["primary_bits"] == 8
        and protocol["codec"]["secondary_bits"] == 4
        and protocol["codec"]["posthoc_bitwidth_selection"] is False,
        "fixed quantization protocol",
    )
    for section, fixed in {
        "split_gate": {
            "mean_retention_gain": 0.05,
            "each_seed_gain_minimum": 0.0,
            "parent_final_semantic_minimum": 0.75,
        },
        "router_gate": {
            "supported_coverage_minimum": 0.75,
            "eligible_oracle_recall_minimum": 0.75,
            "eligible_oracle_regret_maximum": 0.05,
            "gain_over_expected_uniform_random_minimum": 0.05,
            "gain_over_metadata_capability_minimum": 0.05,
            "raw_ood_reject_minimum": 0.9,
        },
        "heterogeneous_gate": {
            "minimum_each_retention_family_each_seed": 0.75,
            "minimum_each_transfer_family_each_seed": 0.75,
        },
        "codec": {
            "fixed_candidate": "single",
            "packed_complete_ratio_maximum": 0.35,
            "retention_loss_maximum": 0.02,
            "transfer_loss_maximum": 0.02,
            "quantized_execution": False,
        },
    }.items():
        for key, value in fixed.items():
            _same(protocol[section][key], value, "unchanged preregistered threshold")
    identity = _json(directory / "source-identity.json")
    _same(
        identity,
        _json(directory / "source-identity-after.json"),
        "source unchanged throughout experiment",
    )
    _same(identity, result["source_identity"], "trial source identity")
    _require(
        identity["source_manifest_sha256"] == _digest(identity["files_sha256"]),
        "source inventory digest",
    )
    scripts = Path(__file__).resolve().parents[1]
    for relative, expected in identity["files_sha256"].items():
        _require(
            _hash(_read(scripts / relative)) == expected,
            "retained implementation source pin: " + relative,
        )
    sets, all_ids = [], []
    for name in (
        "router_training",
        "router_reject_training",
        "source_selection",
        "retention_final",
        "transfer_final",
        "ood_final",
    ):
        questions = {" ".join(p["question"].casefold().split()) for p in data[name]}
        _require(
            len(questions) == len(data[name])
            and not any(questions & earlier for earlier in sets),
            "disjoint router/selection/final/OOD questions",
        )
        sets.append(questions)
        for probe in data[name]:
            answer, roots = _exact(data["sources"], probe["operation"])
            _require(
                answer == probe["value"] and roots == probe["source_roots"],
                "source-derived probe answer and complete dependencies",
            )
            all_ids.append(probe["probe_id"])
    _require(len(all_ids) == len(set(all_ids)), "unique probe identity")
    return data


def _baselines(directory, data, report):
    root = directory / "exact-baselines"
    _same(_json(root / "population-baseline.json"), report, "raw exact baseline report")
    source = _bytes(data["sources"])
    expected_names = {
        "complete_records.json",
        "complete_records.zlib9",
        "complete_records.lzma6",
        "complete_records.sqlite3",
        "seed-and-generator.bin",
        "seed-and-generator.zlib9",
    }
    _require(
        set(report["measurements"]) == expected_names,
        "all complete lossless competitors retained",
    )
    for name, measurement in report["measurements"].items():
        raw = _read(root / name)
        _require(
            measurement["bytes"] == len(raw)
            and measurement["sha256"] == _hash(raw)
            and measurement["lossless"] is True,
            "actual baseline artifact bytes",
        )
    _require(
        _read(root / "complete_records.json") == source
        and zlib.decompress(_read(root / "complete_records.zlib9")) == source
        and lzma.decompress(_read(root / "complete_records.lzma6")) == source,
        "complete-source lossless decompression",
    )
    with sqlite3.connect(
        f"file:{root / 'complete_records.sqlite3'}?mode=ro", uri=True
    ) as database:
        rows = [
            json.loads(row[0])
            for row in database.execute("SELECT payload FROM memory ORDER BY ordinal")
        ]
    _same(rows, data["sources"], "SQLite exact source round trip")
    bundle = _read(root / "seed-and-generator.bin")
    length = struct.unpack("<I", bundle[:4])[0]
    metadata, generator = json.loads(bundle[4 : 4 + length]), bundle[4 + length :]
    _require(
        metadata == {"seed": data["seed"], "source_sha256": _hash(generator)}
        and generator == _read(Path(__file__).with_name("population_fixtures.py"))
        and zlib.decompress(_read(root / "seed-and-generator.zlib9")) == bundle,
        "retained seed plus complete generator exact baseline",
    )
    probes = data["retention_final"] + data["transfer_final"] + data["ood_final"]
    expected = []
    for probe in probes:
        answer, roots = _exact(data["sources"], probe["operation"])
        expected.append(
            {
                "probe_id": probe["probe_id"],
                "answer": answer,
                "roots": roots,
                "exact": answer == probe["value"],
            }
        )
    _same(
        report["typed_operation_rows"],
        expected,
        "independently executed factual temporal and program baselines",
    )
    best = min(
        report["measurements"], key=lambda key: report["measurements"][key]["bytes"]
    )
    _same(
        report["smallest_complete_exact_representation"],
        {"name": best, **report["measurements"][best]},
        "best lossless full-source baseline",
    )
    _require(
        report["typed_operation_exact"] == 1.0
        and report["irreducible_entropy_bound_claimed"] is False,
        "exact known-seed fixture is not an entropy lower bound",
    )
