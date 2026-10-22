"""Measure actual private Head storage and serving on one real feature bundle.

Replicas contain trained task weights but are not independently learned Cells.
The model is already resident. Timings include Python validation and copies,
and are descriptive samples, never a production latency or energy guarantee.
"""

import copy
import gc
import resource
import statistics
import time

import torch

from native_latent import CellRequest, SharedStemServer
from real_encoder import physical_model_accounting

SCALES = (1, 8, 64, 256, 1024, 4096)


def validate_fanout_plan(scales, repeats):
    if (type(scales) is not tuple or not scales
            or any(type(n) is not int or n not in SCALES for n in scales)
            or list(scales) != sorted(set(scales))
            or type(repeats) is not int or not 1 <= repeats <= 20):
        raise ValueError("bounded fanout plan required")


def measure_fanout(owner, bundle, trained, *, scales=SCALES, repeats=3):
    validate_fanout_plan(scales, repeats)
    if len(bundle.source_record_digests) != 1:
        raise ValueError("single-event fanout bundle required")
    bundle.require_identity(owner.identity)
    if trained.identity != owner.identity:
        raise ValueError("trained Head does not belong to this Encoder")
    if (any(m.training for m in owner._model.modules())
            or any(p.requires_grad or p.grad is not None for p in owner._model.parameters())
            or any(m.training for m in trained._head.modules())
            or any(p.requires_grad for p in trained._head.parameters())):
        raise ValueError("Encoder and trained Head must remain frozen for fanout")
    if (not isinstance(owner.last_receipt, dict)
            or owner.last_receipt.get("feature_bundle_sha256") != bundle.bundle_digest
            or owner.last_receipt.get("model_forward_calls") != 1):
        raise ValueError("source encoding receipt does not bind this feature bundle")
    # The public predictor verifies the trained artifact's immutable weights.
    trained.predict_task(bundle)
    server = SharedStemServer(owner._model, generation=owner.identity.generation,
                              width=trained._head.width,
                              encoder_sha256=owner.identity.encoder_sha256)
    calls = [0]
    handle = owner._model.register_forward_hook(lambda *_: calls.__setitem__(0, calls[0] + 1))
    rows = []
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        for count in scales:
            heads = [copy.deepcopy(trained._head) for _ in range(count)]
            storage = [physical_model_accounting(head) for head in heads]
            # Ensure this is N actual private allocations, not N Python aliases.
            pointers = [p.untyped_storage().data_ptr() for h in heads for p in h.parameters()]
            original = {p.untyped_storage().data_ptr() for p in trained._head.parameters()}
            if len(pointers) != len(set(pointers)) or original.intersection(pointers):
                raise ValueError("Cell Head replicas alias weight storage")
            requests = [CellRequest(f"news.{i}", owner.identity.generation, head,
                         torch.zeros(1, head.state_width), "0" * 64)
                        for i, head in enumerate(heads)]
            latencies = []
            for _ in range(repeats):
                start = time.perf_counter()
                result = server.evaluate_bundle(bundle, requests, expected_identity=owner.identity)
                latencies.append(1000 * (time.perf_counter() - start))
                if (result["owner_forward_calls_for_this_batch"] != 0
                        or len(result["cell_results"]) != count):
                    raise ValueError("precomputed fanout unexpectedly invoked Encoder")
            rows.append({"cells": count, "active_input_events": 1,
                "private_head_instances": count,
                "private_head_parameters_each": storage[0]["loaded_parameter_count"],
                "actual_private_head_tensor_bytes": sum(s["resident_tensor_storage_bytes"] for s in storage),
                "actual_shared_encoder_tensor_bytes": owner.accounting["resident_tensor_storage_bytes"],
                "head_fanout_ms_samples": latencies,
                "head_fanout_ms_median": statistics.median(latencies),
                "additional_encoder_forward_calls": calls[0],
                "copy_accounting": result["copy_accounting"],
                "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024})
            del heads, requests, result, pointers
            gc.collect()
    finally:
        handle.remove()
        torch.set_num_threads(threads)
    if calls[0]:
        raise ValueError("model was called while serving preencoded features")
    return {"schema": "hepta.real-feature-head-fanout.v1", "measurements": rows,
            "feature_bundle_sha256": bundle.bundle_digest,
            "replica_semantics": "private copies of one trained Head; not independent learning",
            "source_encode_ms": owner.last_receipt["encode_ms"],
            "source_encode_forward_calls": owner.last_receipt["model_forward_calls"],
            "weights_physically_allocated": True, "encoder_instances": 1,
            "independent_input_event_scaling_measured": False,
            "latency_slo_qualified": False, "energy_measured": False,
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
