"""Export fixed complete-source windows as a separate, repeated-holdout diagnostic.

No labels or gold patches enter tokenization, pooling or extraction. The original
192-prefix experiment is immutable. New feature identities bind full-source
chunking and aggregation; they cannot silently reuse original private heads.
"""

import argparse
from dataclasses import asdict
import gzip
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch

from long_document_chunks import ChunkPolicy, tokenize_documents
from long_document_encoder import LongDocumentEncoder, POOLING
from long_document_sources import FullSourceBank, canonical, sha
from real_encoder import CANDIDATES, FrozenRealEncoder
from shared_feature_contract import SourceEvent

SOURCE_FILES = ("full_source_features.py", "long_document_encoder.py", "long_document_chunks.py",
                "long_document_sources.py", "shared_feature_extract.py", "shared_feature_contract.py",
                "real_encoder.py", "feature_bundle.py", "teacher_snapshot.py")


def file_sha(path):
    return sha(Path(path).read_bytes())


def code_hashes():
    return {name: file_sha(Path(__file__).with_name(name)) for name in SOURCE_FILES}


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def exact_tail_reads(bank, records, plans):
    """Known ID/revision/range lookup baseline; choosing relevant ranges is unmeasured."""
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipts = []
    for row, plan in zip(records, plans, strict=True):
        tail = plan.chunks[-1]
        raw, receipt = bank.read_slice(row["source_id"], row["source_version"], tail.char_start,
                                      tail.char_end, row["source_utf8_sha256"])
        if raw != row["text"][tail.char_start:tail.char_end].encode():
            raise ValueError("exact tail source slice changed")
        receipts.append(receipt)
    row = records[0]
    failures = 0
    for source, version, digest in (("missing:source", row["source_version"], row["source_utf8_sha256"]),
            (row["source_id"], "stale:revision", row["source_utf8_sha256"]),
            (row["source_id"], row["source_version"], "0" * 64)):
        try:
            bank.read_slice(source, version, 0, 1, digest)
        except ValueError:
            failures += 1
    if failures != 3:
        raise ValueError("missing/stale source reads were accepted")
    return {"schema": "hepta.full-source-range-read.v1", "byte_exact_tail_reads": len(receipts),
        "missing_stale_rejections": failures, "wall_ns": time.perf_counter_ns() - began,
        "cpu_ns": time.process_time_ns() - cpu, "source_bank": bank.accounting(), "reads": receipts,
        "encoder_calls": 0, "head_updates": 0, "semantic_chunk_selection_measured": False,
        "scope": "last declared chunk by known address; source bank load is measured separately"}


def export_full_features(dataset, source_archive, source_report, snapshot, acquisition, output, *,
                         candidate, batch_size=16, threads=4):
    if (candidate not in ("granite97m", "embeddinggemma2_740m")
            or type(batch_size) is not int or not 1 <= batch_size <= 32
            or type(threads) is not int or not 1 <= threads <= 8):
        raise ValueError("bounded fixed full-source extraction plan required")
    root, acquisition = Path(output), Path(acquisition)
    if root.exists():
        raise ValueError("full-source evidence requires a new output directory")
    bank = FullSourceBank(dataset, source_archive, source_report)
    records = bank.records()
    acquired, spec = json.loads(acquisition.read_bytes()), CANDIDATES[candidate]
    if (acquired["candidate"] != candidate or acquired["revision"] != spec["revision"]
            or acquired["repository"] != spec["repository"]):
        raise ValueError("checkpoint acquisition differs from the registered candidate")
    root.mkdir(parents=True)
    observed_at_ns = time.time_ns()
    policy, implementation = ChunkPolicy(), code_hashes()
    protocol = {"schema": "hepta.full-source-extraction-protocol.v1", "candidate": candidate,
        "dataset_sha256": file_sha(dataset), "source_files_sha256": bank.file_hashes,
        "checkpoint_acquisition_sha256": file_sha(acquisition), "policy": asdict(policy),
        "pooling": POOLING, "batch_size": batch_size, "threads": threads,
        "retention": "chunks", "predictor_fields": ["repo", "problem_statement"],
        "reconstruction": "Repository: {repo}\\n\\nIssue:\\n{complete problem_statement}",
        "utf8_source_truncation": False, "label_fields_enter_encoder": False,
        "source_code_sha256": implementation, "observed_at_ns": observed_at_ns,
        "scientific_status": "new full-input-coverage diagnostic; legacy holdout reused, not confirmatory",
        "original_experiment_changed": False, "authority": "DENY_ALL"}
    write_json(root / "protocol.json", protocol)
    torch.set_num_threads(threads)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    owner = FrozenRealEncoder(candidate=candidate, snapshot=snapshot, revision=spec["revision"],
        expected_inventory_sha256=acquired["inventory_sha256"], operator_accepted_terms=True,
        profile="text", device="cpu", max_tokens=policy.max_tokens, task="classification",
        generation=1, scope_id="full-source-coverage-20261024")
    load = {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "loaded_model": owner.accounting}
    encoder = LongDocumentEncoder(owner, policy)
    started = time.perf_counter_ns()
    plans = tokenize_documents(owner._tokenizer, [row["text"] for row in records], prefix=owner.prefix, policy=policy)
    planning_ns = time.perf_counter_ns() - started
    chunk_count = sum(len(plan.chunks) for plan in plans)
    plan = {**protocol,
        "schema": "hepta.real-cell-full-source-feature-export.v1", "feature_identity": encoder.feature_identity,
        "feature_definition": encoder.feature_definition, "profile": "text", "task": "classification",
        "max_tokens": policy.max_tokens, "source_ids": [row["source_id"] for row in records],
        "row_count": len(records), "chunks": chunk_count,
        "expected_physical_forward_calls": (chunk_count + batch_size - 1) // batch_size,
        "native_content_tokens": sum(p.content_tokens for p in plans),
        "original_complete_predictor_utf8_bytes": sum(row["source_utf8_bytes"] for row in records),
        "original_issue_utf8_bytes": sum(row["original_issue_utf8_bytes"] for row in records),
        "maximum_chunks_per_source": max(len(p.chunks) for p in plans),
        "planning_wall_ns": planning_ns, "retained_chunk_global_bytes": chunk_count * spec["width"] * 4,
        "document_plan_sha256": [p.seal_sha256 for p in plans]}
    write_json(root / "plan.json", plan)
    with (root / "documents.jsonl.gz").open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        for row, document in zip(records, plans, strict=True):
            zipped.write(canonical({key: row[key] for key in ("source_id", "source_version", "created_at")}
                | {"document_plan_sha256": document.seal_sha256, **document.manifest()}) + b"\n")
    print(json.dumps({"candidate": candidate, "planned_documents": len(plans), "planned_chunks": chunk_count,
                      "planned_forwards": plan["expected_physical_forward_calls"]}), flush=True)
    events = [SourceEvent(row["source_id"], row["source_version"], observed_at_ns) for row in records]
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
        raise ValueError("unexpected retained local-token tensors")
    features, chunks = batch.read_global().numpy(), batch.read_chunks().numpy()
    if features.shape != (len(records), spec["width"]) or chunks.shape != (chunk_count, spec["width"]):
        raise ValueError("complete-source feature shapes differ from declared corpus")
    with (root / "features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=features)
    with (root / "chunk-features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=chunks,
            document_indices=np.repeat(np.arange(len(plans), dtype=np.int32), [len(p.chunks) for p in plans]),
            chunk_indices=np.concatenate([np.arange(len(p.chunks), dtype=np.int32) for p in plans]))
    reads = exact_tail_reads(bank, records, plans)
    write_json(root / "exact-tail-reads.json", reads)
    bank.verify_files()
    if code_hashes() != implementation or file_sha(acquisition) != protocol["checkpoint_acquisition_sha256"]:
        raise ValueError("full-source implementation or checkpoint receipt changed during extraction")
    report = {"plan": plan, "load": load, "encoding": encoder.last_receipt,
        "feature_identity": batch.feature_identity_digest, "encoder_identity": asdict(owner.identity),
        "checkpoint_inventory_sha256": acquired["inventory_sha256"],
        "source_record_digests": batch.source_record_digests, "feature_shape": list(features.shape),
        "retained_global_bytes": features.nbytes, "retained_chunk_global_bytes": chunks.nbytes,
        "retained_chunk_mapping_bytes": chunk_count * 8,
        "retained_native_token_bytes": 0,
        "feature_archive_bytes": (root / "features.npz").stat().st_size,
        "feature_archive_sha256": file_sha(root / "features.npz"), "feature_tensor_sha256": sha(features.tobytes()),
        "chunk_archive_bytes": (root / "chunk-features.npz").stat().st_size,
        "chunk_archive_sha256": file_sha(root / "chunk-features.npz"), "chunk_tensor_sha256": sha(chunks.tobytes()),
        "source_span_receipt_sha256": file_sha(root / "documents.jsonl.gz"),
        "forward_log_sha256": file_sha(root / "forwards.jsonl"),
        "exact_tail_reads_sha256": file_sha(root / "exact-tail-reads.json"),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
            "torch_threads": torch.get_num_threads(), "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "packages": {name: importlib.metadata.version(name) for name in ("numpy", "torch", "transformers", "tokenizers")}},
        "quality_qualified": False, "condition": "full_source_window192_overlap32_weighted_pool",
        "original_experiment_changed": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
    write_json(root / "report.json", report)
    write_json(root / "manifest.json", {path.name: {"sha256": file_sha(path), "bytes": path.stat().st_size}
                                        for path in sorted(root.iterdir()) if path.is_file()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "source-archive", "source-report", "snapshot", "acquisition", "output", "candidate"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=4)
    report = export_full_features(**vars(parser.parse_args()))
    print(json.dumps({"feature_identity": report["feature_identity"], "shape": report["feature_shape"],
                      "chunks": report["encoding"]["chunks"], "forwards": report["encoding"]["physical_forward_calls"]}))


if __name__ == "__main__":
    main()
