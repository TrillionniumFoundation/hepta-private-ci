"""Explicit source-version reconciliation over verified immutable document tensors.

Strict mode re-encodes changed source versions. Opt-in content_rebind creates a
new event/provenance record for identical model inputs, preserving the old tensor
origin. No old forward is attributed to a new source version.
"""

import argparse
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from document_feature_cache import core_document, verify_prior
from full_source_features import file_sha, write_json
from generic_dataset_features import code_hashes as generic_hashes, read_sources
from long_document_chunks import ChunkPolicy, tokenize_documents
from long_document_encoder import LongDocumentEncoder, POOLING
from long_document_sources import canonical, sha
from real_encoder import CANDIDATES, FrozenRealEncoder
from shared_feature_contract import SourceEvent, digest


def code_hashes():
    return generic_hashes() | {name: file_sha(Path(__file__).with_name(name)) for name in
        ("document_feature_cache.py", "reconcile_document_features.py")}


def reconcile_features(dataset, prior_dataset, prior_features, prior_report_sha256,
                       snapshot, acquisition, output, *, candidate, reuse_policy,
                       batch_size=16, threads=2):
    total_started, total_cpu = time.perf_counter_ns(), time.process_time_ns()
    if (reuse_policy not in ("strict", "content_rebind") or candidate not in ("granite97m", "embeddinggemma2_740m")
            or type(batch_size) is not int or not 1 <= batch_size <= 32
            or type(threads) is not int or not 1 <= threads <= 8):
        raise ValueError("explicit bounded reconciliation policy required")
    root, dataset, acquisition = Path(output), Path(dataset), Path(acquisition)
    if root.exists():
        raise ValueError("reconciliation requires a new output directory")
    validation_started, validation_cpu = time.perf_counter_ns(), time.process_time_ns()
    prior = verify_prior(prior_features, prior_dataset, prior_report_sha256)
    old = prior.metadata()
    validation = {"wall_ns": time.perf_counter_ns() - validation_started,
                  "cpu_ns": time.process_time_ns() - validation_cpu}
    records, dataset_hash, dataset_bytes = read_sources(dataset)
    acquired, spec = json.loads(acquisition.read_bytes()), CANDIDATES[candidate]
    if (acquired["candidate"] != candidate or acquired["revision"] != spec["revision"]
            or acquired["repository"] != spec["repository"]
            or old["report"]["plan"]["candidate"] != candidate):
        raise ValueError("registered candidate and previous checkpoint identity must agree")
    implementation, observed, policy = code_hashes(), time.time_ns(), ChunkPolicy()
    protocol = {"schema": "hepta.document-reconciliation-protocol.v1", "reuse_policy": reuse_policy,
        "dataset_sha256": dataset_hash, "dataset_bytes": dataset_bytes,
        "prior_dataset_sha256": old["report"]["plan"]["dataset_sha256"], "prior_report_sha256": prior_report_sha256,
        "checkpoint_acquisition_sha256": file_sha(acquisition), "source_code_sha256": implementation,
        "candidate": candidate, "policy": asdict(policy), "pooling": POOLING, "predictor_fields": ["text"],
        "label_fields_enter_encoder": False, "text_transform": "none", "batch_size": batch_size,
        "threads": threads, "observed_at_ns": observed, "authority": "DENY_ALL",
        "content_rebind_rule": "same source ID and exact text, native IDs/masks/windows/weights, owner/preprocess/pool; new source event with preserved tensor origin"}
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
    if (asdict(owner.identity) != old["report"]["encoder_identity"]
            or encoder.feature_identity != old["report"]["feature_identity"]
            or encoder.feature_definition != old["report"]["plan"]["feature_definition"]):
        raise ValueError("actual owner/preprocess/feature identity differs; cached tensors cannot be combined")
    planning_started, planning_cpu = time.perf_counter_ns(), time.process_time_ns()
    plans = tokenize_documents(owner._tokenizer, [r["text"] for r in records], prefix=owner.prefix, policy=policy)
    old_indices = {r["source_id"]: i for i, r in enumerate(old["records"])}
    decisions, fresh_indices = [], []
    for index, (row, document) in enumerate(zip(records, plans, strict=True)):
        old_index = old_indices.get(row["source_id"])
        previous = None if old_index is None else old["records"][old_index]
        reason = "new_source" if previous is None else "changed_text"
        status = "new_forward"
        if previous is not None and row["text"].encode() == previous["text"].encode():
            if document.manifest() != core_document(old["documents"][old_index]):
                raise ValueError("identical text has changed native windows, masks, spans or pooling")
            if row["source_version"] == previous["source_version"]:
                status, reason = "cache_hit", "exact_source_version_and_text"
            elif reuse_policy == "content_rebind":
                status, reason = "cache_rebind", "metadata_only_source_version_change"
            else:
                reason = "changed_source_version_strict_policy"
        if status == "new_forward":
            fresh_indices.append(index)
        decisions.append({"status": status, "reason": reason, "prior_row": old_index})
    planning = {"wall_ns": time.perf_counter_ns() - planning_started,
                "cpu_ns": time.process_time_ns() - planning_cpu}
    fresh_chunks = sum(len(plans[i].chunks) for i in fresh_indices)
    count = sum(len(p.chunks) for p in plans)
    plan = {**protocol, "schema": "hepta.reconciled-complete-source-export.v1",
        "feature_identity": encoder.feature_identity, "feature_definition": encoder.feature_definition,
        "source_ids": [r["source_id"] for r in records], "row_count": len(records), "chunks": count,
        "document_plan_sha256": [p.seal_sha256 for p in plans], "fresh_source_row_indices": fresh_indices,
        "new_chunks": fresh_chunks, "expected_new_physical_forward_calls": (fresh_chunks + batch_size - 1) // batch_size,
        "computed_uncached_full_cohort_forward_equivalent": (count + batch_size - 1) // batch_size,
        "full_cohort_equivalent_is_measured": False, "decisions": decisions}
    write_json(root / "plan.json", plan)
    events = [SourceEvent(r["source_id"], r["source_version"], observed) for r in records]
    fresh_batch, fresh_encoding = None, None
    with (root / "forwards.jsonl").open("xb") as log:
        if fresh_indices:
            def progress(receipt):
                log.write(canonical({**receipt, "new_dataset_row_indices":
                    [fresh_indices[i] for i in receipt["source_row_indices"]]}) + b"\n")
                log.flush()
            fresh_batch, _ = encoder.encode([plans[i] for i in fresh_indices],
                events=[events[i] for i in fresh_indices], expected_identity=owner.identity,
                batch_size=batch_size, retention="chunks", on_batch=progress)
            fresh_encoding = encoder.last_receipt
    assembly_started, assembly_cpu = time.perf_counter_ns(), time.process_time_ns()
    new_values = None if fresh_batch is None else fresh_batch.read_global().numpy()
    new_chunks = None if fresh_batch is None else fresh_batch.read_chunks().numpy()
    values, chunks = np.empty((len(records), spec["width"]), np.float32), np.empty((count, spec["width"]), np.float32)
    fresh_row = fresh_cursor = cursor = 0
    documents, sources = [], []
    for index, (row, document, decision) in enumerate(zip(records, plans, decisions, strict=True)):
        length = len(document.chunks)
        if decision["status"] == "new_forward":
            values[index] = new_values[fresh_row]
            chunks[cursor:cursor + length] = new_chunks[fresh_cursor:fresh_cursor + length]
            origin = {"kind": "new_forward", "fresh_subset_row": fresh_row,
                      "forward_source_record_digest": fresh_batch.source_record_digests[fresh_row]}
            fresh_row += 1
            fresh_cursor += length
        else:
            old_index = decision["prior_row"]
            a, b = old["chunk_ranges"][old_index]
            values[index], chunks[cursor:cursor + length] = prior.features()[old_index], prior.chunks()[a:b]
            origin = {"kind": decision["status"], "prior_report_sha256": prior_report_sha256,
                "prior_row": old_index, "prior_source_version": old["records"][old_index]["source_version"],
                "prior_source_record_digest": old["report"]["source_record_digests"][old_index],
                "prior_document_plan_sha256": old["documents"][old_index]["document_plan_sha256"],
                "prior_global_row_sha256": sha(prior.features()[old_index].tobytes()), "prior_chunk_range": [a, b]}
        binding = {"schema": "hepta.reconciled-source-event.v1", "event": asdict(events[index]),
            "source_utf8_sha256": row["source_utf8_sha256"], "document_plan_sha256": document.seal_sha256,
            "tensor_origin": origin}
        sources.append(digest(binding))
        documents.append({"source_id": row["source_id"], "source_version": row["source_version"],
            "source_version_input": row["source_version_input"], "document_plan_sha256": document.seal_sha256,
            **document.manifest(), "binding": binding, "source_record_digest": sources[-1]})
        cursor += length
    prior.verify_files()
    if (file_sha(dataset) != dataset_hash or code_hashes() != implementation
            or file_sha(acquisition) != protocol["checkpoint_acquisition_sha256"]):
        raise ValueError("current source, implementation or acquisition changed")
    with (root / "features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=values)
    with (root / "chunk-features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=chunks,
            document_indices=np.repeat(np.arange(len(plans), dtype=np.int32), [len(p.chunks) for p in plans]),
            chunk_indices=np.concatenate([np.arange(len(p.chunks), dtype=np.int32) for p in plans]))
    with (root / "documents.jsonl.gz").open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        for document in documents:
            zipped.write(canonical(document) + b"\n")
    assembly = {"wall_ns": time.perf_counter_ns() - assembly_started,
                "cpu_ns": time.process_time_ns() - assembly_cpu}
    new_calls = 0 if fresh_encoding is None else fresh_encoding["physical_forward_calls"]
    old_calls = old["report"]["encoding"]["physical_forward_calls"]
    cache = {"requests": len(records), "strict_hits": sum(d["status"] == "cache_hit" for d in decisions),
        "explicit_content_rebinds": sum(d["status"] == "cache_rebind" for d in decisions), "misses": len(fresh_indices),
        "previous_global_tensor_bytes": len(prior._features), "previous_chunk_tensor_bytes": len(prior._chunks)}
    encoding = {"physical_forward_calls": new_calls, "historical_prior_physical_forward_calls": old_calls,
        "total_historical_physical_forward_calls": old_calls + new_calls, "current_encoder_instances": 1,
        "historical_encoder_instances": old["report"]["encoding"]["encoder_instances"] + 1,
        "documents": len(records), "chunks": count, "cache": cache, "new_encoding_receipt": fresh_encoding,
        "prior_report_sha256": prior_report_sha256, "historical_encoding_wall_ns": old["report"]["encoding"]["wall_ns"] +
        (0 if fresh_encoding is None else fresh_encoding["wall_ns"]), "native_content_tokens_dropped": 0,
        "source_spans_cover_complete_input": True, "encoder_updates": 0}
    reconciliation = {"wall_ns": time.perf_counter_ns() - total_started,
        "cpu_ns": time.process_time_ns() - total_cpu, "cache_validation": validation,
        "native_planning_and_reuse_selection": planning, "assembly_revalidation_and_artifact_writes": assembly,
        "scope": "inclusive reconciliation through tensor/source artifact writes; includes model load, validation, planning, encoding and assembly; excludes final report/manifest writes; do not add nested phases to this total"}
    report = {"plan": plan, "load": load, "encoding": encoding, "reconciliation": reconciliation,
        "feature_identity": encoder.feature_identity,
        "encoder_identity": asdict(owner.identity), "checkpoint_inventory_sha256": acquired["inventory_sha256"],
        "source_record_digests": sources, "feature_shape": list(values.shape),
        "feature_archive_sha256": file_sha(root / "features.npz"), "feature_tensor_sha256": sha(values.tobytes()),
        "chunk_archive_sha256": file_sha(root / "chunk-features.npz"), "chunk_tensor_sha256": sha(chunks.tobytes()),
        "source_span_receipt_sha256": file_sha(root / "documents.jsonl.gz"), "forward_log_sha256": file_sha(root / "forwards.jsonl"),
        "retained_global_bytes": values.nbytes, "retained_chunk_global_bytes": chunks.nbytes,
        "retained_chunk_mapping_bytes": count * 8, "retained_native_token_bytes": 0,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "python_metadata_bytes_measured": False, "previous_artifacts_changed": False,
        "quality_qualified": False, "condition": "complete_text_window192_overlap32_weighted_pool",
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
    write_json(root / "report.json", report)
    write_json(root / "manifest.json", {p.name: {"sha256": file_sha(p), "bytes": p.stat().st_size}
                                       for p in sorted(root.iterdir()) if p.is_file()})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "prior-dataset", "prior-features", "prior-report-sha256", "snapshot",
                 "acquisition", "output", "candidate", "reuse-policy"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=2)
    result = reconcile_features(**vars(parser.parse_args()))
    print(json.dumps({"feature_identity": result["feature_identity"], "shape": result["feature_shape"],
                      "cache": result["encoding"]["cache"], "new_forwards": result["encoding"]["physical_forward_calls"]}))
