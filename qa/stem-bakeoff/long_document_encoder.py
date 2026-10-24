"""One frozen owner encodes complete native-token windows and pools documents."""

from dataclasses import asdict, dataclass
from pathlib import Path
import time

import numpy as np
import torch

from long_document_chunks import ChunkPolicy, DocumentPlan, tokenizer_fingerprint
from long_document_sources import canonical, sha
from shared_feature_contract import SCHEMA as SHARED_SCHEMA, SourceEvent, digest
from shared_feature_extract import SharedFeatureEncoder

SCHEMA = "hepta.full-source-document-features.v1"
POOLING = "sum(chunk_global * sum_inverse_native_token_overlap)/content_tokens; document_l2"
MAX_LOCAL_BYTES = 64 * 1024**2


@dataclass(frozen=True)
class DocumentFeatureBatch:
    identity: object
    feature_identity_digest: str
    source_record_digests: tuple
    global_shape: tuple
    _global: bytes
    chunk_shape: tuple | None
    _chunks: bytes | None
    _manifest: bytes
    _seal: str

    def verify_integrity(self):
        bound = canonical([asdict(self.identity), self.feature_identity_digest,
                           self.source_record_digests, self.global_shape, self.chunk_shape])
        if sha(bound + self._global + (self._chunks or b"") + self._manifest) != self._seal:
            raise ValueError("pooled document snapshot changed")

    def read_global(self):
        self.verify_integrity()
        return torch.from_numpy(np.frombuffer(self._global, dtype=np.float32).reshape(self.global_shape).copy())

    def read_chunks(self):
        self.verify_integrity()
        if self._chunks is None:
            raise ValueError("chunk features were not retained")
        return torch.from_numpy(np.frombuffer(self._chunks, dtype=np.float32).reshape(self.chunk_shape).copy())

    def manifest(self):
        import json
        return json.loads(self._manifest)


class LongDocumentEncoder:
    """Research-only full-source pooling with one owner and an explicit new identity.

    Optional native local views are returned as independent batch snapshots. They
    are bounded before the first forward; this API never silently drops detail.
    """

    def __init__(self, owner, policy=ChunkPolicy()):
        self.shared = SharedFeatureEncoder(owner)
        self.owner, self.policy = owner, policy
        if owner.profile != "text" or owner.max_tokens != policy.max_tokens:
            raise ValueError("text owner and exact chunk-window budget required")
        self.tokenizer_sha256 = tokenizer_fingerprint(owner._tokenizer)
        base = digest({"schema": SHARED_SCHEMA, "encoder": asdict(owner.identity),
                       "extractor_sha256": self.shared.extractor_sha256})
        paths = [Path(__file__).with_name(name) for name in
                 ("long_document_encoder.py", "long_document_chunks.py", "long_document_sources.py")]
        self.feature_definition = {"schema": SCHEMA, "base_shared_feature_identity": base,
            "tokenizer_sha256": self.tokenizer_sha256, "policy": asdict(policy), "pooling": POOLING,
            "chunk_input": "slice complete native encoding; repeat native prefix and special template",
            "code_sha256": {p.name: sha(p.read_bytes()) for p in paths}}
        self.feature_identity = digest(self.feature_definition)
        self.last_receipt = None

    def encode(self, plans, *, events, expected_identity, batch_size=16, retention="chunks", on_batch=None):
        owner = self.owner
        if (type(batch_size) is not int or not 1 <= batch_size <= 32
                or retention not in ("global", "chunks", "tokens")
                or not isinstance(plans, (tuple, list)) or not 1 <= len(plans) <= 4096
                or len(events) != len(plans)):
            raise ValueError("bounded full-document plan and retention required")
        # Validate every document before any model computation.
        self.shared._preflight(events, "global", expected_identity)
        if tokenizer_fingerprint(owner._tokenizer) != self.tokenizer_sha256:
            raise ValueError("native tokenizer changed before document encoding")
        if digest(self.feature_definition) != self.feature_identity or self.feature_definition["policy"] != asdict(self.policy):
            raise ValueError("document feature definition changed")
        flat = []
        for document, plan in enumerate(plans):
            if (type(plan) is not DocumentPlan or plan.policy != self.policy or plan.prefix != owner.prefix
                    or plan.tokenizer_sha256 != self.tokenizer_sha256):
                raise ValueError("document plan belongs to a different tokenizer, prefix or window policy")
            plan.verify()
            flat.extend((document, index, chunk) for index, chunk in enumerate(plan.chunks))
        if not 1 <= len(flat) <= self.policy.max_total_chunks:
            raise ValueError("full document window budget exceeded")
        width = owner.spec["width"]
        local_estimate = sum(len(flat[begin:begin + batch_size]) * (
            max(len(chunk.input_ids) for _, _, chunk in flat[begin:begin + batch_size]) * (width * 4 + 26)
            + width * 4 + 5) for begin in range(0, len(flat), batch_size))
        if retention == "tokens" and local_estimate > MAX_LOCAL_BYTES:
            raise ValueError("requested native local detail exceeds byte budget before forward")
        source_digests = tuple(digest({"event": asdict(event),
            "source_utf8_sha256": sha(plan.source_text.encode()), "document_plan_sha256": plan.seal_sha256})
            for event, plan in zip(events, plans, strict=True))
        pooled = np.zeros((len(plans), width), dtype=np.float64)
        chunks = None if retention == "global" else np.empty((len(flat), width), dtype=np.float32)
        local, forwards = [], []
        began, cpu, calls_before = time.perf_counter_ns(), time.process_time_ns(), owner._calls
        local_retained = 0
        for begin in range(0, len(flat), batch_size):
            selected = flat[begin:begin + batch_size]
            sequence = max(len(chunk.input_ids) for _, _, chunk in selected)
            ids = torch.full((len(selected), sequence), owner._tokenizer.pad_token_id, dtype=torch.int64)
            mask = torch.zeros_like(ids)
            spans = torch.zeros((*ids.shape, 2), dtype=torch.int64)
            valid = torch.zeros_like(ids, dtype=torch.bool)
            sources, batch_events = [], []
            for row, (document, index, chunk) in enumerate(selected):
                count = len(chunk.input_ids)
                ids[row, :count] = torch.tensor(chunk.input_ids)
                mask[row, :count] = 1
                spans[row, :count] = torch.tensor(chunk.char_spans)
                valid[row, :count] = torch.tensor(chunk.char_valid)
                batch_events.append(events[document])
                sources.append(digest({"document_source": source_digests[document], "chunk_index": index,
                                       "chunk": chunk.manifest()}))
            with owner._lock:
                self.shared._preflight(batch_events, "tokens" if retention == "tokens" else "global", expected_identity)
                batch = self.shared._forward({"input_ids": ids, "attention_mask": mask}, tuple(sources),
                    [("text",)] * len(selected), tuple(batch_events),
                    "tokens" if retention == "tokens" else "global", time.perf_counter(),
                    spans if retention == "tokens" else None, valid if retention == "tokens" else None)
            values = batch.read_global().numpy()
            for offset, (document, _, chunk) in enumerate(selected):
                pooled[document] += values[offset].astype(np.float64) * chunk.weight
            if chunks is not None:
                chunks[begin:begin + len(selected)] = values
            if retention == "tokens":
                views = batch.snapshot()
                local_retained += sum(value.numel() * value.element_size() for value in views.values())
                if local_retained > MAX_LOCAL_BYTES:
                    raise ValueError("native local detail exceeded predeclared byte budget")
                local.append(views)
            receipt = {**self.shared.last_receipt, "first_chunk": begin,
                "source_row_indices": [document for document, _, _ in selected],
                "chunk_indices": [index for _, index, _ in selected],
                "input_tensor_bytes": ids.numel() * ids.element_size() + mask.numel() * mask.element_size(),
                "padded_input_tokens": ids.numel()}
            forwards.append(receipt)
            if on_batch is not None:
                on_batch(receipt)
        counts = np.array([plan.content_tokens for plan in plans], dtype=np.float64)[:, None]
        pooled /= counts
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        if not np.isfinite(pooled).all() or np.any(norms <= 1e-12):
            raise ValueError("nonfinite or zero full-document pooled feature")
        global_features = (pooled / norms).astype(np.float32)
        calls = owner._calls - calls_before
        if calls != len(forwards) or calls != (len(flat) + batch_size - 1) // batch_size:
            raise ValueError("actual forward count differs from complete chunk execution")
        self.last_receipt = {"schema": SCHEMA, "feature_identity": self.feature_identity,
            "feature_definition": self.feature_definition, "documents": len(plans), "chunks": len(flat),
            "native_content_tokens": sum(plan.content_tokens for plan in plans),
            "processed_native_input_tokens": sum(len(chunk.input_ids) for _, _, chunk in flat),
            "padded_input_tokens": sum(r["padded_input_tokens"] for r in forwards),
            "physical_forward_calls": calls, "encoder_instances": 1,
            "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
            "cache": {"enabled": False, "chunk_requests": len(flat), "hits": 0,
                      "misses": len(flat), "retained_tensor_bytes": 0},
            "retained_global_bytes": global_features.nbytes,
            "retained_chunk_global_bytes": 0 if chunks is None else chunks.nbytes,
            "retained_local_view_bytes": local_retained, "retention": retention,
            "forwards": forwards, "native_content_tokens_dropped": 0,
            "source_spans_cover_complete_input": True, "encoder_updates": 0, "authority": "DENY_ALL"}
        metadata = canonical({"feature_definition": self.feature_definition,
            "source_record_digests": source_digests,
            "documents": [{"event": asdict(event), "document_plan_sha256": plan.seal_sha256,
                            **plan.manifest()} for event, plan in zip(events, plans, strict=True)]})
        self.last_receipt["retained_manifest_bytes"] = len(metadata)
        self.last_receipt["retained_source_utf8_bytes"] = sum(len(p.source_text.encode()) for p in plans)
        self.last_receipt["python_metadata_bytes_measured"] = False
        global_bytes = global_features.tobytes()
        chunk_bytes = None if chunks is None else chunks.tobytes()
        shape = None if chunks is None else chunks.shape
        bound = canonical([asdict(owner.identity), self.feature_identity, source_digests, global_features.shape, shape])
        result = DocumentFeatureBatch(owner.identity, self.feature_identity, source_digests,
            global_features.shape, global_bytes, shape, chunk_bytes, metadata,
            sha(bound + global_bytes + (chunk_bytes or b"") + metadata))
        return result, tuple(local)
