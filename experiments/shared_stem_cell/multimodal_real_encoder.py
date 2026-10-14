"""Pinned offline text stem ingress for the existing cross-modal Bridge experiment.

The *only* production of real embeddings is through the repository's strict
``execution.LocalEncoder`` loader. No implicit network access, fallback model,
model selection, metric grading or authority is implemented here.

TRAIN input includes raw text targets; FUTURE_TARGETS is an independently held
input and MUST NOT be given to the train/predict producer. This module produces
no future targets unless the operator explicitly starts that separate command.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import time

import torch

from multimodal_bridge import ContractError, ModalityFeature, _digest
from multimodal_alignment_contract import (
    SCHEMA, MAX_ROWS, _text, canonical, load_pinned_document,
    load_pinned_jsonl, parse_feature, sha, write_new,
)

PROFILE_SCHEMA = "hepta.multimodal-pinned-text-encoder.v1"
RECEIPT_SCHEMA = "hepta.multimodal-text-ingress-receipt.v1"
PHASES = frozenset({"train", "future_targets"})


@dataclass(frozen=True)
class EncoderProfile:
    candidate: str
    snapshot: dict
    snapshot_digest: str
    profile_digest: str
    expected_width: int
    maximum_tokens: int
    batch_size: int
    normalization: str


def validated_profile(raw: dict, digest: str) -> EncoderProfile:
    _digest(digest)
    if (type(raw) is not dict or set(raw) != {
            "schema", "candidate", "snapshot", "expected_width", "maximum_tokens",
            "batch_size", "pooling", "normalization"} or raw["schema"] != PROFILE_SCHEMA):
        raise ContractError("exact pinned encoder profile required")
    candidate = _text(raw["candidate"], "candidate", 96)
    if not all(33 <= ord(c) <= 126 for c in candidate):
        raise ContractError("ASCII stable candidate label required")
    snapshot = raw["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != {"revision", "kind", "files"}
            or snapshot["kind"] not in ("encoder", "masked_lm")
            or type(snapshot["files"]) is not dict or not snapshot["files"]
            or type(snapshot["revision"]) is not str or len(snapshot["revision"]) != 40
            or any(c not in "0123456789abcdef" for c in snapshot["revision"])):
        raise ContractError("exact revision and snapshot manifest required")
    for key, value in snapshot["files"].items():
        if type(key) is not str or not key or type(value) is not str:
            raise ContractError("invalid snapshot inventory")
        _digest(value)
    width, tokens, batch = raw["expected_width"], raw["maximum_tokens"], raw["batch_size"]
    if (type(width) is not int or not 1 <= width <= 512
            or type(tokens) is not int or not 8 <= tokens <= 8192
            or type(batch) is not int or not 1 <= batch <= 32
            or raw["pooling"] != "attention-mask-mean"
            or raw["normalization"] not in ("none", "unit_l2")):
        raise ContractError("explicit supported width, pooling, normalization and budget required")
    return EncoderProfile(candidate, snapshot, sha(canonical(snapshot)), digest,
                          width, tokens, batch, raw["normalization"])


def _input_digest(text: str) -> str:
    return sha(canonical(["hepta.multimodal-raw-text-input.v1", text]))


def _validate_raw(rows: list[dict], phase: str) -> tuple[list[dict], str]:
    if phase not in PHASES or not 1 <= len(rows) <= MAX_ROWS:
        raise ContractError("invalid dataset phase or cardinality")
    if phase == "train" and len(rows) < 8:
        raise ContractError("train phase requires at least eight examples")
    expected = ({"case_id", "group_id", "scope", "observed_at", "split", "source", "target_text"}
                if phase == "train" else
                {"case_id", "group_id", "scope", "observed_at", "split", "source_input_sha256", "target_text"})
    prepared = []
    cases = set()
    scopes = set()
    groups = set()
    modality = set()
    encoder_ids = set()
    text_digests = set()
    for raw in rows:
        if type(raw) is not dict or set(raw) != expected or raw["split"] != (
                "train" if phase == "train" else "future"):
            raise ContractError("phase-specific exact row schema required")
        for field in ("case_id", "group_id", "scope"):
            _text(raw[field], field)
        observed_at = raw["observed_at"]
        if type(observed_at) is not int or not 0 <= observed_at < 2**63:
            raise ContractError("invalid observation time")
        text = raw["target_text"]
        if type(text) is not str or not 1 <= len(text.encode("utf-8")) <= 8192:
            raise ContractError("bounded nonempty text is required; no silent truncation")
        if raw["case_id"] in cases:
            raise ContractError("duplicate case identity")
        cases.add(raw["case_id"])
        scopes.add(raw["scope"])
        groups.add(raw["group_id"])
        td = _input_digest(text)
        text_digests.add(td)
        source = None
        if phase == "train":
            source = parse_feature(raw["source"])
            if source.modality == "text":
                raise ContractError("source must be a non-text modality")
            modality.add(source.modality)
            encoder_ids.add(source.encoder_sha256)
        else:
            _digest(raw["source_input_sha256"])
        prepared.append({"row": raw, "text_digest": td, "source": source})
    if len(scopes) != 1 or (phase == "train" and (
            len(groups) < 2 or len(modality) != 1 or len(encoder_ids) != 1)):
        raise ContractError("cross-scope or mixed modality/encoder cohort")
    return prepared, next(iter(scopes))


def feature_rows(rows: list[dict], phase: str, backend,
                 profile: EncoderProfile) -> tuple[list[dict], dict]:
    """Physical .encode is mandatory; injected test backends remain unverified."""
    prepared, scope = _validate_raw(rows, phase)
    identity = _digest(getattr(backend, "identity", None))
    if profile.snapshot_digest != sha(canonical(profile.snapshot)):
        raise ContractError("profile snapshot mutated after admission")
    full_identity = sha(canonical([PROFILE_SCHEMA, profile.profile_digest,
                                   profile.snapshot_digest, identity,
                                   "attention-mask-mean", profile.normalization]))
    produced = []
    start_calls = getattr(backend, "forward_calls", None)
    if type(start_calls) is not int or start_calls < 0:
        raise ContractError("backend lacks physical forward counter")
    started = time.perf_counter_ns()
    forward_batches = 0
    for i in range(0, len(prepared), profile.batch_size):
        selection = prepared[i:i + profile.batch_size]
        vectors = backend.encode([x["row"]["target_text"] for x in selection])
        if (not isinstance(vectors, torch.Tensor) or vectors.device.type != "cpu"
                or vectors.dtype != torch.float32 or vectors.ndim != 2
                or tuple(vectors.shape) != (len(selection), profile.expected_width)
                or not bool(torch.isfinite(vectors).all())):
            raise ContractError("actual encoder output identity, width or type mismatch")
        if profile.normalization == "unit_l2":
            norms = torch.linalg.vector_norm(vectors, dim=1, keepdim=True)
            if not bool(torch.isfinite(norms).all()) or bool((norms <= 0).any()):
                raise ContractError("zero or nonfinite vector cannot be unit normalized")
            vectors = vectors / norms
        for item, vec in zip(selection, vectors.tolist()):
            source_row = item["row"]
            feature = ModalityFeature.from_vector("text", item["text_digest"], full_identity,
                                                 tuple(vec))
            target = {"modality": feature.modality, "input_sha256": feature.input_sha256,
                      "encoder_sha256": feature.encoder_sha256, "values": list(feature.values)}
            base = {name: source_row[name] for name in
                    ("case_id", "group_id", "scope", "observed_at", "split")}
            if phase == "train":
                source = item["source"]
                produced.append({**base, "source": {
                    "modality": source.modality, "input_sha256": source.input_sha256,
                    "encoder_sha256": source.encoder_sha256, "values": list(source.values)},
                    "target": target})
            else:
                produced.append({**base, "source_input_sha256": source_row["source_input_sha256"],
                                 "target": target})
        forward_batches += 1
        current = getattr(backend, "forward_calls", None)
        if current != start_calls + forward_batches:
            raise ContractError("backend did not execute exactly one forward per batch")
    duration = time.perf_counter_ns() - started
    receipt = {"schema": RECEIPT_SCHEMA, "phase": phase, "candidate": profile.candidate,
               "model_kind": profile.snapshot["kind"], "model_revision": profile.snapshot["revision"],
               "snapshot_digest": profile.snapshot_digest,
               "profile_digest": profile.profile_digest, "backend_identity": identity,
               "feature_encoder_identity": full_identity,
               "pooling": "attention-mask-mean", "normalization": profile.normalization,
               "output_width": profile.expected_width, "examples": len(produced),
               "batches": forward_batches, "backend_forward_calls_observed": forward_batches, "physical_forwards": None,
               "measured_wall_ns": duration, "process_rss_bytes": None,
               "model_checkpoint_locally_verified": False,
               "actual_pretrained_model_proven": False,
               "independent_learning_efficacy": False,
               "production_accepted": False, "scope": scope,
               "target_input_digests": sorted({r["text_digest"] for r in prepared})}
    return produced, receipt


def write_jsonl_new(path: Path, rows: list[dict]) -> str:
    blob = b"".join(canonical(row) for row in rows)
    with path.open("xb") as stream:
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(blob)


def run_offline(profile_path: Path, profile_sha256: str, snapshot_root: Path,
                dataset_path: Path, dataset_sha256: str, output_dir: Path, phase: str) -> dict:
    """No test backend allowed on this entrypoint: strict HF material only."""
    raw = load_pinned_document(profile_path, profile_sha256)
    profile = validated_profile(raw, profile_sha256)
    dataset, src_digest = load_pinned_jsonl(dataset_path, dataset_sha256)
    # Validate raw data completely before allocating actual model weights.
    _validate_raw(dataset, phase)
    # A profile's per-file hashes are rechecked by LocalEncoder before/after all forwards.
    from execution import LocalEncoder, measured  # optional HF dependency loads here only
    try:
        with measured() as cost:
            backend = LocalEncoder(snapshot_root, profile.snapshot, profile.maximum_tokens)
            if backend.identity != profile.snapshot_digest:
                raise ContractError("actual model snapshot identity drift")
            try:
                emitted, receipt = feature_rows(dataset, phase, backend, profile)
            finally:
                backend.close()  # rechecks model bytes after execution
            receipt["parameter_count"] = sum(p.numel() for p in backend.loaded.parameters())
            receipt["parameter_bytes_f32"] = sum(p.numel() * p.element_size()
                                                  for p in backend.loaded.parameters())
    except Exception:
        # Never write any output (or run synthetic fallback) after a loader failure.
        raise
    receipt["model_load_and_forward_cost"] = cost
    receipt["input_file_sha256"] = src_digest
    receipt["model_checkpoint_locally_verified"] = True
    receipt["physical_forwards"] = backend.forward_calls
    receipt["model_publisher_authenticated"] = False
    # An authenticated published model identity / independent external outcome
    # is not implied by a pinned local checkpoint and an operator label.
    output_dir.mkdir(parents=False, exist_ok=False)
    encoded_sha = write_jsonl_new(output_dir / "encoded.jsonl", emitted)
    receipt["encoded_sha256"] = encoded_sha
    write_new(output_dir / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description="Verified offline text Encoder → multimodal features")
    parser.add_argument("phase", choices=["train"])
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_offline(args.profile, args.profile_sha256, args.model_snapshot,
                args.input, args.input_sha256, args.output_dir, "train")


if __name__ == "__main__":
    main()
