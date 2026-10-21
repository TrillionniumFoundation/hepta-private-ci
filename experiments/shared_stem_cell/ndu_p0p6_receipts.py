"""P0-P6 research-only physical/source and capability receipt completeness audit.

No self-asserted signature, model byte SHA, or numeric observation authenticates
an external source. Consequently completeness NEVER implies production acceptance.
Unknown resource measurements are kept NULL, never estimated from parameters.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math


ARMS = ("laya421", "granite97", "mmbert_small", "embeddinggemma2")
SCALES = (64, 256, 1024, 4096)
SEARCH = ("no_search", "fixed_depth", "vanilla_tree", "learned_critic", "finite_bsde", "coupled_ndu")
PHASES = tuple(f"P{k}" for k in range(7))


class ReceiptError(ValueError):
    pass


def _sha(s):
    return type(s) is str and len(s) == 64 and s != "0"*64 and all(c in "0123456789abcdef" for c in s)


def freeze_models(manifest):
    """Checks same Reader, task and frozen resources on all proposed model arms.

    File SHA claims are not independent file-byte or model execution receipts.
    """
    if type(manifest) is not dict or set(manifest) != set(ARMS):
        raise ReceiptError("all four reference models are required")
    identity = set()
    common = None
    for name in ARMS:
        m = manifest[name]
        required = {"weights_sha256", "tokenizer_sha256", "preprocessor_sha256",
                    "checkpoint_revision", "dataset_sha256", "reader_sha256",
                    "objective_sha256", "head_initial_sha256", "train_budget", "license_review_id",
                    "feature_width", "pooling_sha256", "normalization_sha256",
                    "quantization_sha256", "runtime_sha256", "bridge_sha256"}
        if type(m) is not dict or set(m) != required:
            raise ReceiptError("complete model/readout/Reader freeze required")
        if any(not _sha(m[k]) for k in ("weights_sha256", "tokenizer_sha256",
                                           "preprocessor_sha256", "dataset_sha256",
                                           "reader_sha256", "objective_sha256",
                                           "head_initial_sha256", "pooling_sha256",
                                           "normalization_sha256", "quantization_sha256",
                                           "runtime_sha256", "bridge_sha256")):
            raise ReceiptError("invalid model/source identity")
        if (type(m["checkpoint_revision"]) is not str or len(m["checkpoint_revision"]) != 40
                or not all(c in "0123456789abcdef" for c in m["checkpoint_revision"])):
            raise ReceiptError("immutable checkpoint revision required")
        if type(m["feature_width"]) is not int or not 1 <= m["feature_width"] <= 512:
            raise ReceiptError("invalid explicit native Neuron feature width")
        if type(m["train_budget"]) is not int or not 0 < m["train_budget"] <= 10**15:
            raise ReceiptError("registered identical train budget required")
        if type(m["license_review_id"]) is not str or not m["license_review_id"]:
            raise ReceiptError("license review provenance required")
        pinned = tuple(m[k] for k in ("dataset_sha256", "reader_sha256", "objective_sha256", "head_initial_sha256", "train_budget", "feature_width"))
        if common is not None and pinned != common:
            raise ReceiptError("changed Reader/task/initial Head/budget invalidates comparison")
        common = pinned
        key = (m["weights_sha256"], m["tokenizer_sha256"])
        if key in identity:
            raise ReceiptError("model weight aliases cannot masquerade as distinct arms")
        identity.add(key)
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"schema": "hepta.stem.frozen-p0-panel.v1", "panel_sha256": hashlib.sha256(data).hexdigest(),
            "declared_models": list(ARMS), "physical_weights_verified": False,
            "real_reader_quality_proven": False, "production_accepted": False}


def _positive_int(v):
    return type(v) is int and v > 0


def _quantile(xs, numerator):
    """Conservative observed nearest-rank, never from one aggregate time."""
    ordered = sorted(xs)
    idx = (len(xs) * numerator + 99) // 100 - 1
    return ordered[idx]


def meter_scale(records, *, arm):
    """Summarize complete observed request samples and actual encoder calls.

    This only audits numbers that were supplied. The host must independently
    witness actual execution, worker identity, RSS and physical forward count.
    """
    if arm not in ARMS or type(records) not in (list, tuple) or len(records) != 4:
        raise ReceiptError("one four-scale arm required")
    by_scale = {}
    frozen_binding = None
    for r in records:
        expected = {"arm", "cells", "concurrency", "scope_sha256", "source_sha256",
                    "model_sha256", "head_sha256", "physical_encoder_forwards",
                    "cpu_ns", "wall_ns", "peak_rss_bytes", "latencies_ns", "energy_joules"}
        if type(r) is not dict or set(r) != expected or r["arm"] != arm:
            raise ReceiptError("physical run schema/arm mismatch")
        n = r["cells"]
        if n not in SCALES or n in by_scale or not _positive_int(r["concurrency"]) or r["concurrency"] > n:
            raise ReceiptError("missing/duplicate scale or concurrency")
        if any(not _sha(r[k]) for k in ("scope_sha256", "source_sha256", "model_sha256", "head_sha256")):
            raise ReceiptError("unbound physical source/head")
        binding = (r["scope_sha256"], r["model_sha256"], r["head_sha256"])
        if frozen_binding is not None and binding != frozen_binding:
            raise ReceiptError("model/head/scope changed between physical scales")
        frozen_binding = binding
        if any(not _positive_int(r[k]) for k in ("physical_encoder_forwards", "cpu_ns", "wall_ns", "peak_rss_bytes")):
            raise ReceiptError("missing physical work/cost")
        samples = r["latencies_ns"]
        if (type(samples) not in (list, tuple) or len(samples) != n
                or any(not _positive_int(s) for s in samples)):
            raise ReceiptError("no complete request latency census")
        joules = r["energy_joules"]
        if joules is not None and (type(joules) not in (int, float) or not math.isfinite(joules) or joules < 0):
            raise ReceiptError("unknown energy must stay null")
        by_scale[n] = {"logical_cells": n, "concurrency": r["concurrency"],
                       "physical_encoder_forwards": r["physical_encoder_forwards"],
                       "cpu_ns": r["cpu_ns"], "wall_ns": r["wall_ns"],
                       "peak_rss_bytes": r["peak_rss_bytes"],
                       "p50_ns": _quantile(samples, 50),
                       "p95_ns": _quantile(samples, 95),
                       "p99_ns": _quantile(samples, 99),
                       "energy_joules": joules}
    if set(by_scale) != set(SCALES):
        raise ReceiptError("64/256/1024/4096 all required")
    return {"schema": "hepta.stem.selfreported-physical-scale.v1", "model_arm": arm,
            "observations": [by_scale[n] for n in SCALES],
            "host_attestation_verified": False, "production_accepted": False}


def phase_blockers(evidence: dict) -> dict:
    """No inferred successes: absent independent checks remain explicit blockers."""
    if type(evidence) is not dict:
        raise ReceiptError("typed evidence inventory required")
    requirements = {
        "P0": ("pinned_real_weights", "paired_reader_outcomes", "identical_task_cost"),
        "P1": ("real_worker_producer", "real_64_256_1024_4096", "resource_quality_frontier"),
        "P2": ("pretrained_modality_towers", "source_disjoint_interventions", "external_task_gain"),
        "P3": ("actual_search_controls", "frozen_shared_critic", "independent_cost_adjusted_gain"),
        "P4": ("finite_tree_exact_oracle", "obstruction_regression", "global_interface_admission"),
        "P5": ("admitted_coupled_coefficients", "same_task_cheap_controls", "new_outcome_gain"),
        "P6": ("sealed_distilled_candidate", "external_future_retention", "physical_cost_quality"),
    }
    unknown = set(evidence) - {v for req in requirements.values() for v in req}
    if unknown:
        raise ReceiptError("unknown evidence flags cannot mint an approval")
    # Even every self-reported flag cannot grant independent qualification.
    for key, value in evidence.items():
        if type(value) is not bool:
            raise ReceiptError("only explicit boolean mechanism flags allowed")
    phases = {}
    for phase, fields in requirements.items():
        missing = [field for field in fields if evidence.get(field) is not True]
        phases[phase] = {"mechanism_reported_complete": not missing,
                         "missing_or_unverified_fields": missing,
                         "independent_acceptance": False}
    return {"schema": "hepta.stem.p0-p6-research-readiness.v1", "phases": phases,
            "all_stages_independently_passed": False, "production_accepted": False,
            "requires_external_signer_and_target_host": True}
