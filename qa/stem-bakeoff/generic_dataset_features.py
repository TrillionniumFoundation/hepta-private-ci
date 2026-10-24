"""Encode complete explicit dataset text with frozen native-window pooling.

Only the exact UTF8 value of each row's text is a model input. Labels, outcome
receipts and source versions are never formatted into that value. This additive
exporter shares the complete-source policy without changing earlier experiments.
"""

import argparse
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch

from full_source_features import file_sha, write_json
from long_document_chunks import ChunkPolicy, tokenize_documents
from long_document_encoder import LongDocumentEncoder, POOLING
from long_document_sources import canonical, sha
from real_encoder import CANDIDATES, FrozenRealEncoder
from shared_feature_contract import SourceEvent

SOURCE_FILES = ("generic_dataset_features.py", "full_source_features.py",
    "long_document_encoder.py", "long_document_chunks.py", "long_document_sources.py",
    "shared_feature_extract.py", "shared_feature_contract.py", "real_encoder.py",
    "feature_bundle.py", "teacher_snapshot.py")


def code_hashes():
    return {name: file_sha(Path(__file__).with_name(name)) for name in SOURCE_FILES}


def read_sources(dataset):
    path = Path(dataset)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024**2:
        raise ValueError("bounded ordinary dataset file required")
    raw = path.read_bytes()
    if len(raw) > 64 * 1024**2:
        raise ValueError("dataset grew beyond its byte budget")
    data = json.loads(raw)
    rows = data.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError("bounded nonempty source rows required")
    records, seen, total = [], set(), 0
    for row in rows:
        source, text, version = row["source_id"], row["text"], row["source_version"]
        if (type(source) is not str or not 1 <= len(source) <= 256 or source in seen
                or type(text) is not str or not text or type(version) not in (dict, str)):
            raise ValueError("unique source IDs, complete text and explicit versions required")
        encoded, version_bytes = text.encode("utf-8"), canonical(version)
        if (not 1 <= len(encoded) <= ChunkPolicy().max_source_bytes
                or not 1 <= len(version_bytes) <= 4096 or not version
                or type(row.get("text_utf8_bytes")) is not int
                or row["text_utf8_bytes"] != len(encoded)
                or row.get("text_utf8_sha256") != sha(encoded)):
            raise ValueError("complete text bytes, hash or source version differs from manifest")
        bound_version = "sha256:" + sha(version_bytes)
        SourceEvent(source, bound_version)
        seen.add(source)
        total += len(encoded)
        records.append({"source_id": source, "source_version": bound_version,
            "source_version_input": version, "text": text,
            "source_utf8_sha256": sha(encoded), "source_utf8_bytes": len(encoded)})
    if total > 64 * 1024**2:
        raise ValueError("complete predictor corpus exceeds byte budget")
    return tuple(records), sha(raw), len(raw)


def export_generic_features(dataset, snapshot, acquisition, output, *, candidate,
                            batch_size=16, threads=2):
    if (candidate not in ("granite97m", "embeddinggemma2_740m")
            or type(batch_size) is not int or not 1 <= batch_size <= 32
            or type(threads) is not int or not 1 <= threads <= 8):
        raise ValueError("bounded fixed complete-source extraction required")
    dataset, acquisition, root = Path(dataset), Path(acquisition), Path(output)
    if root.exists():
        raise ValueError("complete-source evidence requires a new output directory")
    records, dataset_sha256, dataset_bytes = read_sources(dataset)
    acquired, spec = json.loads(acquisition.read_bytes()), CANDIDATES[candidate]
    if (acquired["candidate"] != candidate or acquired["revision"] != spec["revision"]
            or acquired["repository"] != spec["repository"]):
        raise ValueError("checkpoint acquisition differs from registered candidate")
    policy, implementation = ChunkPolicy(), code_hashes()
    observed_at_ns = time.time_ns()
    protocol = {"schema": "hepta.generic-complete-source-protocol.v1", "candidate": candidate,
        "dataset_sha256": dataset_sha256, "dataset_bytes": dataset_bytes,
        "checkpoint_acquisition_sha256": file_sha(acquisition), "policy": asdict(policy),
        "pooling": POOLING, "batch_size": batch_size, "threads": threads,
        "retention": "chunks", "predictor_fields": ["text"], "text_transform": "none",
        "source_version_policy": "sha256 of canonical JSON source_version; metadata only",
        "utf8_source_truncation": False, "label_fields_enter_encoder": False,
        "source_code_sha256": implementation, "observed_at_ns": observed_at_ns,
        "quality_qualified": False, "original_experiment_changed": False, "authority": "DENY_ALL"}
    root.mkdir(parents=True)
    write_json(root / "protocol.json", protocol)
    torch.set_num_threads(threads)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    owner = FrozenRealEncoder(candidate=candidate, snapshot=snapshot, revision=spec["revision"],
        expected_inventory_sha256=acquired["inventory_sha256"], operator_accepted_terms=True,
        profile="text", device="cpu", max_tokens=policy.max_tokens, task="classification",
        generation=1, scope_id="generic-complete-source-20261024")
    load = {"wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
            "loaded_model": owner.accounting}
    encoder = LongDocumentEncoder(owner, policy)
    began = time.perf_counter_ns()
    plans = tokenize_documents(owner._tokenizer, [row["text"] for row in records],
                               prefix=owner.prefix, policy=policy)
    planning_ns = time.perf_counter_ns() - began
    count = sum(len(p.chunks) for p in plans)
    plan = {**protocol, "schema": "hepta.generic-complete-source-export.v1",
        "feature_identity": encoder.feature_identity, "feature_definition": encoder.feature_definition,
        "profile": "text", "task": "classification", "max_tokens": policy.max_tokens,
        "source_ids": [row["source_id"] for row in records], "row_count": len(records),
        "chunks": count, "expected_physical_forward_calls": (count + batch_size - 1) // batch_size,
        "native_content_tokens": sum(p.content_tokens for p in plans),
        "original_complete_predictor_utf8_bytes": sum(r["source_utf8_bytes"] for r in records),
        "maximum_chunks_per_source": max(len(p.chunks) for p in plans),
        "planning_wall_ns": planning_ns, "retained_chunk_global_bytes": count * spec["width"] * 4,
        "document_plan_sha256": [p.seal_sha256 for p in plans]}
    write_json(root / "plan.json", plan)
    with (root / "documents.jsonl.gz").open("xb") as raw, \
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        for row, document in zip(records, plans, strict=True):
            zipped.write(canonical({key: row[key] for key in
                ("source_id", "source_version", "source_version_input")}
                | {"document_plan_sha256": document.seal_sha256, **document.manifest()}) + b"\n")
    print(json.dumps({"candidate": candidate, "planned_documents": len(plans),
                      "planned_chunks": count, "planned_forwards": plan["expected_physical_forward_calls"]}), flush=True)
    events = [SourceEvent(r["source_id"], r["source_version"], observed_at_ns) for r in records]
    with (root / "forwards.jsonl").open("xb") as log:
        def progress(receipt):
            log.write(canonical(receipt) + b"\n")
            log.flush()
            if receipt["model_forward_calls_total"] % 25 == 0:
                print(json.dumps({"candidate": candidate, "forward_calls": receipt["model_forward_calls_total"],
                    "completed_chunks": receipt["first_chunk"] + receipt["batch_size"]}), flush=True)
        batch, local = encoder.encode(plans, events=events, expected_identity=owner.identity,
            batch_size=batch_size, retention="chunks", on_batch=progress)
    if local:
        raise ValueError("unexpected retained native-token data")
    values, chunks = batch.read_global().numpy(), batch.read_chunks().numpy()
    if values.shape != (len(records), spec["width"]) or chunks.shape != (count, spec["width"]):
        raise ValueError("complete-source output shape changed")
    if (file_sha(dataset) != dataset_sha256 or code_hashes() != implementation
            or file_sha(acquisition) != protocol["checkpoint_acquisition_sha256"]):
        raise ValueError("source, implementation or acquisition changed during encoding")
    with (root / "features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=values)
    with (root / "chunk-features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=chunks,
            document_indices=np.repeat(np.arange(len(plans), dtype=np.int32), [len(p.chunks) for p in plans]),
            chunk_indices=np.concatenate([np.arange(len(p.chunks), dtype=np.int32) for p in plans]))
    report = {"plan": plan, "load": load, "encoding": encoder.last_receipt,
        "feature_identity": batch.feature_identity_digest, "encoder_identity": asdict(owner.identity),
        "checkpoint_inventory_sha256": acquired["inventory_sha256"],
        "source_record_digests": batch.source_record_digests, "feature_shape": list(values.shape),
        "retained_global_bytes": values.nbytes, "retained_chunk_global_bytes": chunks.nbytes,
        "retained_chunk_mapping_bytes": count * 8, "retained_native_token_bytes": 0,
        "retained_predictor_utf8_bytes": plan["original_complete_predictor_utf8_bytes"],
        "retained_input_dataset_bytes": dataset_bytes, "python_metadata_bytes_measured": False,
        "feature_archive_bytes": (root / "features.npz").stat().st_size,
        "feature_archive_sha256": file_sha(root / "features.npz"), "feature_tensor_sha256": sha(values.tobytes()),
        "chunk_archive_bytes": (root / "chunk-features.npz").stat().st_size,
        "chunk_archive_sha256": file_sha(root / "chunk-features.npz"), "chunk_tensor_sha256": sha(chunks.tobytes()),
        "source_span_receipt_sha256": file_sha(root / "documents.jsonl.gz"),
        "forward_log_sha256": file_sha(root / "forwards.jsonl"),
        "environment": {"python": platform.python_version(), "torch_threads": torch.get_num_threads(),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024},
        "quality_qualified": False, "condition": "complete_text_window192_overlap32_weighted_pool",
        "original_experiment_changed": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
    write_json(root / "report.json", report)
    write_json(root / "manifest.json", {p.name: {"sha256": file_sha(p), "bytes": p.stat().st_size}
                                       for p in sorted(root.iterdir()) if p.is_file()})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "snapshot", "acquisition", "output", "candidate"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=2)
    result = export_generic_features(**vars(parser.parse_args()))
    print(json.dumps({"feature_identity": result["feature_identity"], "shape": result["feature_shape"],
                      "chunks": result["encoding"]["chunks"], "forwards": result["encoding"]["physical_forward_calls"]}))
