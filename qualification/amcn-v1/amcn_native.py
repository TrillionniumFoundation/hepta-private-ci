"""Real HF LocalEncoder -> Shared FeatureMatrix -> SemanticMemoryCell candidate.

No synthetic fallback. Caller supplies a complete pinned LOCAL HuggingFace safetensors
snapshot, original public question/evidence bytes, TRAIN-only labels and exact scope.
The upstream LocalEncoder owns model loading and full tensor parity. This runner
never downloads, uses remote model code, reads future targets or serves weights.
"""
from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import os

from experiments.shared_stem_cell.execution import (
    Case, LocalEncoder, encode_cases, parameters, tensor_digest,
)
from amcn_core import Evidence, canonical, digest, is_sha, require, shadow_disposition
from amcn_learning import FeatureMatrix, Row, train_semantic


def build_inputs(records, *, scope, generation, maximum=16384):
    """Source-first, complete question/evidence association. No target accepted."""
    require(isinstance(records, list) and 2 <= len(records) <= maximum, "input size")
    prepared, cases, ids = [], [], set()
    needed = {"row_id", "question", "evidence", "family", "split"}
    for record in records:
        require(isinstance(record, dict) and set(record) == needed, "source record fields")
        require(isinstance(record["evidence"], Evidence), "source reference required")
        ev = record["evidence"]
        require(ev.current(scope, generation), "stale evidence reference")
        require(isinstance(record["question"], str)
                and 1 <= len(record["question"].encode("utf-8")) <= 8192,
                "bounded question")
        rid, family, split = record["row_id"], record["family"], record["split"]
        require(isinstance(rid, str) and rid and rid not in ids
                and isinstance(family, str) and family
                and split in ("train", "select", "future_a", "future_b", "retention"),
                "source split identity")
        ids.add(rid)
        # Exact full input is canonical JSON rather than a template with collisions;
        # model still treats evidence as untrusted text, not executable commands.
        text = canonical({"question": record["question"],
                          "source_id": ev.evidence_id,
                          "source_revision": ev.revision,
                          "source_content_sha256": ev.content_sha256,
                          "evidence": ev.text}).decode("utf-8")
        cases.append(Case(case_id=rid, group=family, split=split,
                          observed_at=None, cell=0, scope=scope, text=text))
        prepared.append(Row(rid, ev.source_root, family, split, scope,
                            generation, cases[-1].input_digest))
    return prepared, cases


def encode_native(root: Path, model_manifest, records, *, scope, generation,
                  maximum_tokens=512, batch_size=8, cache_bytes=0):
    """Execute real pinned pretrained Transformer, not a trained-test fixture."""
    prepared, cases = build_inputs(records, scope=scope, generation=generation)
    backend = LocalEncoder(root, model_manifest, maximum_tokens=maximum_tokens)
    try:
        tensor, metrics = encode_cases(backend, cases, batch_size=batch_size,
                                       cache_bytes=cache_bytes)
        backend.close()  # materialized source inventory unchanged
    finally:
        # Resident object is local and non-authorizing; no new product model owner.
        backend.loaded.cpu()
    require(metrics["requests"] == len(records) and not metrics["simulated_encoder"]
            and metrics["encoder_forward_calls"] >= 1, "no real shared Encoder call")
    encoder_identity = backend.identity
    require(is_sha(encoder_identity), "exact physical Encoder snapshot digest")
    observed = {"profile": "hepta.amcn.real-local-hf-encoder.v1",
                "encoder_identity": encoder_identity,
                "tensor_digest": tensor_digest(tensor),
                "case_ids": [c.case_id for c in cases],
                "input_sha256": [c.input_digest for c in cases],
                "backend_metrics": metrics}
    receipt_digest = digest(observed)
    matrix = FeatureMatrix(prepared, tensor, encoder_sha256=encoder_identity,
                           scope=scope, generation=generation,
                           backend_profile="local_hf_snapshot_checked_unreviewed",
                           encoder_execution_receipt=receipt_digest)
    return matrix, observed


def run_train_once(root, model_manifest, records, train_labels, *, scope,
                   generation, steps=48, output_dir):
    """Seal real Head tensor bytes before any independent held-out judgments."""
    output_dir = Path(output_dir)
    require(not output_dir.exists(), "immutable output directory must not exist")
    matrix, encoder_receipt = encode_native(Path(root), model_manifest, records,
                                            scope=scope, generation=generation)
    trial = train_semantic(matrix, train_labels, steps=steps)
    from safetensors.torch import save_file
    output_dir.mkdir(parents=True, exist_ok=False)
    state = {k: v.detach().cpu().contiguous() for k, v
             in trial["trained"].state_dict().items()}
    try:
        model_path = output_dir / "semantic-head.safetensors"
        save_file(state, str(model_path))
        with model_path.open("rb") as f:
            os.fsync(f.fileno())
        bytes_sha = sha256(model_path.read_bytes()).hexdigest()
        payload = {
            "schema": "hepta.amcn.real-head-candidate.v1",
            "source_scope": scope, "generation": generation,
            "source_manifest_sha256": digest([(r["row_id"], r["evidence"].content_sha256,
                                                r["evidence"].source_root) for r in records]),
            "encoder_execution": encoder_receipt,
            "prediction_digest": digest(trial["predictions"]),
            "head_tensor_sha256": bytes_sha,
            "head_geometry": parameters(trial["trained"]),
            "head_training": trial["receipt"],
            "independent_evaluator": None,
            "selection": "RESEARCH_ONLY_NOT_ADMITTED",
            "production_accepted": False
        }
        # Only identifiers, digests, costs and tensor weights are serialized.
        # Raw source, query, TRAIN labels, future labels and historical KV are not.
        for name, data in (("sealed-predictions.json", trial["predictions"]),
                           ("candidate-receipt.json", payload)):
            with (output_dir / name).open("xb") as f:
                f.write(canonical(data) + b"\n")
                f.flush()
                os.fsync(f.fileno())
        dirfd = os.open(str(output_dir), os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        # Fail visibly; keep partial source+artifact for investigation.
        raise
    return shadow_disposition(
        candidate_output=str(output_dir), head_tensor_sha256=bytes_sha,
        physical_encoder_forward_calls=encoder_receipt["backend_metrics"]["encoder_forward_calls"],
        training=trial["receipt"]["metrics"]["work"],
        independent_holdout_unscored=True)
