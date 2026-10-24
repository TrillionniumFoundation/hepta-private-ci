"""Verify a pinned complete-source export before any document-level reuse."""

from dataclasses import asdict, dataclass
import gzip
import json
from pathlib import Path
import re

import numpy as np

from generic_dataset_features import code_hashes, read_sources
from full_source_features import file_sha
from long_document_sources import canonical, sha
from real_cell_features import load_features
from shared_feature_contract import SourceEvent, digest

FILES = {"protocol.json", "plan.json", "documents.jsonl.gz", "forwards.jsonl",
         "features.npz", "chunk-features.npz", "report.json"}
META = {"source_id", "source_version", "source_version_input", "document_plan_sha256"}


def core_document(document):
    return {key: value for key, value in document.items() if key not in META}


@dataclass(frozen=True)
class VerifiedDocumentCache:
    _metadata: bytes
    _features: bytes
    _chunks: bytes
    feature_shape: tuple
    chunk_shape: tuple
    file_pins: tuple

    def metadata(self):
        return json.loads(self._metadata)

    def features(self):
        return np.frombuffer(self._features, dtype=np.float32).reshape(self.feature_shape)

    def chunks(self):
        return np.frombuffer(self._chunks, dtype=np.float32).reshape(self.chunk_shape)

    def verify_files(self):
        for name, expected in self.file_pins:
            path = Path(name)
            if path.is_symlink() or not path.is_file() or file_sha(path) != expected:
                raise ValueError("previous source or sealed feature artifact changed")


def verify_prior(directory, dataset, expected_report_sha256):
    root = Path(directory)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_report_sha256):
        raise ValueError("independently pinned previous report hash required")
    if (root.is_symlink() or not root.is_dir()
            or {p.name for p in root.iterdir()} != FILES | {"manifest.json"}
            or any(p.is_symlink() or not p.is_file() or p.stat().st_size > 128 * 1024**2
                   for p in root.iterdir()) or file_sha(root / "report.json") != expected_report_sha256):
        raise ValueError("previous report or ordinary complete file inventory differs")
    manifest_bytes = (root / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if set(manifest) != FILES or manifest["report.json"]["sha256"] != expected_report_sha256:
        raise ValueError("previous manifest inventory differs")
    for name, record in manifest.items():
        if record != {"sha256": file_sha(root / name), "bytes": (root / name).stat().st_size}:
            raise ValueError("previous sealed artifact changed")
    records, dataset_sha256, _ = read_sources(dataset)
    values, report = load_features(root, dataset)
    plan = report["plan"]
    protocol = json.loads((root / "protocol.json").read_bytes())
    if (plan["schema"] != "hepta.generic-complete-source-export.v1"
            or json.loads((root / "plan.json").read_bytes()) != plan
            or any(plan.get(key) != value for key, value in protocol.items() if key != "schema")
            or plan["dataset_sha256"] != dataset_sha256
            or plan["source_ids"] != [r["source_id"] for r in records]
            or plan["source_code_sha256"] != code_hashes()
            or protocol["predictor_fields"] != ["text"] or protocol["text_transform"] != "none"
            or protocol["label_fields_enter_encoder"] is not False):
        raise ValueError("previous exact text-only predictor implementation or source binding differs")
    for key, name in (("chunk_archive_sha256", "chunk-features.npz"),
                      ("source_span_receipt_sha256", "documents.jsonl.gz"),
                      ("forward_log_sha256", "forwards.jsonl")):
        if file_sha(root / name) != report[key]:
            raise ValueError("previous report does not bind retained chunk/source artifacts")
    with gzip.open(root / "documents.jsonl.gz", "rb") as stream:
        raw = stream.read(128 * 1024**2 + 1)
    if len(raw) > 128 * 1024**2:
        raise ValueError("expanded source span manifest exceeds budget")
    documents = [json.loads(line) for line in raw.splitlines()]
    if len(documents) != len(records) or values.shape != (len(records), report["feature_shape"][1]):
        raise ValueError("previous document/global row counts differ")
    with np.load(root / "chunk-features.npz", allow_pickle=False) as archive:
        if archive.files != ["features", "document_indices", "chunk_indices"]:
            raise ValueError("unexpected previous chunk archive fields")
        chunks, rows, indices = (archive[k] for k in archive.files)
    counts = [len(d["chunks"]) for d in documents]
    if (chunks.shape != (sum(counts), values.shape[1]) or chunks.dtype != np.float32
            or not np.isfinite(chunks).all() or sha(chunks.tobytes()) != report["chunk_tensor_sha256"]
            or rows.dtype != np.int32 or indices.dtype != np.int32
            or not np.array_equal(rows, np.repeat(np.arange(len(records), dtype=np.int32), counts))
            or not np.array_equal(indices, np.concatenate([np.arange(n, dtype=np.int32) for n in counts]))):
        raise ValueError("previous chunk tensors or document mapping differ")
    offsets, cursor = [], 0
    for index, (row, document) in enumerate(zip(records, documents, strict=True)):
        core = core_document(document)
        if (document["source_id"] != row["source_id"] or document["source_version"] != row["source_version"]
                or document["source_version_input"] != row["source_version_input"]
                or sha(canonical(core)) != document["document_plan_sha256"]
                or document["document_plan_sha256"] != plan["document_plan_sha256"][index]
                or document["source_utf8_sha256"] != row["source_utf8_sha256"]
                or document["source_utf8_bytes"] != row["source_utf8_bytes"]
                or document["source_characters"] != len(row["text"])):
            raise ValueError("previous document/source/version seal differs")
        end_token = end_char = end_byte = 0
        pooled = np.zeros(values.shape[1], dtype=np.float64)
        for offset, chunk in enumerate(document["chunks"]):
            a, b = chunk["content_token_span"]
            c, d = chunk["char_span"]
            e, f = chunk["utf8_span"]
            if (not 0 <= a <= end_token < b <= document["content_tokens"]
                    or not 0 <= c <= end_char <= d <= len(row["text"])
                    or not 0 <= e <= end_byte <= f <= row["source_utf8_bytes"]
                    or e != len(row["text"][:c].encode()) or f != len(row["text"][:d].encode())
                    or not np.isfinite(chunk["aggregation_weight"]) or chunk["aggregation_weight"] <= 0):
                raise ValueError("previous native token/character/UTF8 coverage has gaps")
            end_token, end_char, end_byte = b, d, f
            pooled += chunks[cursor + offset].astype(np.float64) * chunk["aggregation_weight"]
        if (end_token != document["content_tokens"] or end_char != len(row["text"])
                or end_byte != row["source_utf8_bytes"]
                or abs(sum(c["aggregation_weight"] for c in document["chunks"]) - end_token) > 1e-8):
            raise ValueError("previous full-source tail or pooling weights are incomplete")
        pooled /= document["content_tokens"]
        pooled = (pooled / np.linalg.norm(pooled)).astype(np.float32)
        if not np.array_equal(pooled, values[index]):
            raise ValueError("previous retained chunk pooling differs from global feature")
        event = SourceEvent(row["source_id"], row["source_version"], plan["observed_at_ns"])
        source_digest = digest({"event": asdict(event), "source_utf8_sha256": row["source_utf8_sha256"],
                                "document_plan_sha256": document["document_plan_sha256"]})
        if source_digest != report["source_record_digests"][index]:
            raise ValueError("previous source event digest differs")
        offsets.append([cursor, cursor + counts[index]])
        cursor += counts[index]
    forwards = [json.loads(line) for line in (root / "forwards.jsonl").read_bytes().splitlines()]
    if (forwards != report["encoding"]["forwards"]
            or len(forwards) != report["encoding"]["physical_forward_calls"]
            or sum(r["batch_size"] for r in forwards) != len(chunks)):
        raise ValueError("previous actual forward inventory differs")
    metadata = canonical({"records": records, "documents": documents, "report": report,
                          "chunk_ranges": offsets, "report_sha256": expected_report_sha256})
    pins = tuple((str(root / name), record["sha256"]) for name, record in sorted(manifest.items())) + (
        (str(root / "manifest.json"), sha(manifest_bytes)), (str(Path(dataset)), dataset_sha256))
    result = VerifiedDocumentCache(metadata, values.tobytes(), chunks.tobytes(), values.shape, chunks.shape, pins)
    result.verify_files()
    return result
