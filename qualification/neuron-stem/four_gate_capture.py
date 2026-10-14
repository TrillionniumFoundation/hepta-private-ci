"""Actual CPU Torch Encoder-call capture for Gate 1, never a native Worker grant.

The caller supplies an already loaded, frozen Encoder, approved tokenizer input
preparation, pooling function and isolated Heads. No downloads, remote model code,
model replacement, training or production credentials are handled here.
"""
from collections import OrderedDict
import hashlib
import time

from four_gate_common import digest, integer, require, sha
from four_gate_compute import ARMS, encoding_key


def tensor_digest(tensor):
    """Actual tensor bytes; a digest is not a signed ArtifactLoadReceipt."""
    import torch

    value = tensor.detach().cpu().contiguous()
    h = hashlib.sha256()
    h.update(str((str(value.dtype), tuple(value.shape))).encode("ascii"))
    h.update(value.reshape(-1).view(torch.uint8).numpy().tobytes())
    return h.hexdigest()


def capture_cpu(model, prepare_batch, pool, heads, schedule, *, arm,
                pipeline_sha256, max_batch_size=32, cache_entries=256):
    """Execute one arm in an isolated CPU process and return observed raw traces.

    prepare_batch(rows, arm) returns a CPU tensor mapping with input_ids and an
    optional attention_mask. pool(model_output) returns a [batch, feature] tensor.
    The selected model must already be eval/frozen. Run each comparison arm in a
    fresh process: process peak RSS cannot be reset or subtracted reliably.
    """
    import psutil
    import torch

    require(arm in ARMS, "unknown capture arm")
    sha(pipeline_sha256)
    integer(max_batch_size, "native batch size", 1, 32)
    integer(cache_entries, "cache capacity", 1, 100_000)
    require(0 < len(schedule) <= 100_000, "bounded schedule required")
    require(not model.training and all(not p.requires_grad for p in model.parameters()),
            "Encoder must be explicitly frozen and in eval mode")
    require(all(p.device.type == "cpu" for p in model.parameters()) and
            all(p.device.type == "cpu" for head in heads.values() for p in head.parameters()),
            "CPU capture cannot certify GPU timing; use synchronized target-host telemetry")
    require(all(row["cell_id"] in heads for row in schedule), "missing isolated Cell Head")
    require(len({id(head) for head in heads.values()}) == len(heads), "Cell Heads alias one module")
    tensor_owners = {}
    for cell, head in heads.items():
        for parameter in head.parameters():
            pointer = parameter.untyped_storage().data_ptr()
            require(pointer not in tensor_owners or tensor_owners[pointer] == cell,
                    "Cell Head tensors alias another Cell")
            tensor_owners[pointer] = cell
    process = psutil.Process()
    cache = OrderedDict()
    events, requests = [], []
    peak_rss = process.memory_info().rss
    begin_wall, begin_cpu = time.perf_counter_ns(), time.process_time_ns()
    state = {"pending_keys": None, "tokens": None, "event": None, "observed_calls": 0}

    def before_forward(module, args, kwargs):
        require(state["pending_keys"] is not None and state["event"] is None,
                "unregistered or reentrant Encoder execution")
        ids = kwargs.get("input_ids")
        require(ids is not None and ids.ndim == 2 and
                ids.shape[0] == len(state["pending_keys"]), "batch identity/shape mismatch")
        mask = kwargs.get("attention_mask")
        tokens = ids.numel() if mask is None else int(mask.sum().item())
        require(tokens > 0, "empty Encoder input")
        state["event"] = {"id": f"encoder-{state['observed_calls']}",
                          "keys": list(state["pending_keys"]), "token_count": tokens,
                          "actual_input_tensor_sha256": tensor_digest(ids),
                          "start_ns": time.perf_counter_ns()}
        state["observed_calls"] += 1

    def after_forward(module, args, kwargs, output):
        require(state["event"] is not None, "unregistered Encoder completion")
        state["event"]["end_ns"] = time.perf_counter_ns()
        events.append(state["event"])
        state["event"] = None

    pre = model.register_forward_pre_hook(before_forward, with_kwargs=True)
    post = model.register_forward_hook(after_forward, with_kwargs=True)
    try:
        with torch.inference_mode():
            for start in range(0, len(schedule), max_batch_size):
                chunk = schedule[start:start + max_batch_size]
                # All schedule rows are already queued when capture begins.
                admitted = begin_wall
                keys = [encoding_key(row, arm, pipeline_sha256) for row in chunk]
                slots = {}
                missing, missing_keys = [], []
                for index, (row, key) in enumerate(zip(chunk, keys)):
                    marker = key if arm == "feature_reuse" else index
                    if arm == "feature_reuse" and key in cache:
                        slots[marker] = cache[key]
                        cache.move_to_end(key)
                    elif marker not in slots:
                        slots[marker] = None
                        missing.append(row)
                        missing_keys.append(key)
                if missing:
                    tokens = prepare_batch(missing, arm)
                    require(type(tokens) is dict and "input_ids" in tokens and
                            all(isinstance(t, torch.Tensor) and t.device.type == "cpu" for t in tokens.values()),
                            "approved preparation must return CPU tensors")
                    state["pending_keys"] = missing_keys
                    before_count = state["observed_calls"]
                    features = pool(model(**tokens))
                    state["pending_keys"] = None
                    require(state["observed_calls"] == before_count + 1,
                            "expected exactly one actual batched Encoder forward")
                    require(isinstance(features, torch.Tensor) and features.ndim == 2 and
                            features.shape[0] == len(missing) and torch.isfinite(features).all().item(),
                            "invalid Encoder pooled output")
                    event_id = events[-1]["id"]
                    pending_markers = [marker for marker, value in slots.items() if value is None]
                    for offset, marker in enumerate(pending_markers):
                        value = (features[offset].detach().clone(), event_id, offset)
                        slots[marker] = value
                        if arm == "feature_reuse":
                            cache[marker] = value
                            if len(cache) > cache_entries:
                                cache.popitem(last=False)
                for index, (row, key) in enumerate(zip(chunk, keys)):
                    marker = key if arm == "feature_reuse" else index
                    vector, event_id, slot = slots[marker]
                    output = heads[row["cell_id"]](vector)
                    require(torch.isfinite(output).all().item(), "non-finite Head output")
                    requests.append({"request_id": row["request_id"], "cell_id": row["cell_id"],
                                     "encoder_event_id": event_id, "encoder_slot": slot,
                                     "start_ns": admitted, "end_ns": time.perf_counter_ns(),
                                     "outcome": "succeeded", "prediction_sha256": tensor_digest(output)})
                peak_rss = max(peak_rss, process.memory_info().rss)
    finally:
        pre.remove()
        post.remove()
    elapsed_cpu = time.process_time_ns() - begin_cpu
    elapsed_wall = time.perf_counter_ns() - begin_wall
    return {"encoder_forwards": events, "requests": requests,
            "observed_inference_cost": {"cpu_ns": elapsed_cpu, "wall_ns": elapsed_wall,
                                        "gpu_ns": 0, "energy_uj": None},
            "sampled_peak_rss_bytes": peak_rss,
            "rss_is_continuously_sampled_high_watermark": False,
            "completed_schedule_sha256": digest(schedule),
            "arrival_policy": "all_rows_queued_at_capture_start",
            "native_worker_execution_authenticated": False,
            "production_promotion_permitted": False,
            "limitations": ["CPU research process only; no GPU or energy measurement",
                            "Caller must add separately measured lifecycle and true peak RSS receipts",
                            "Exceptions abort capture; no successful complete-run receipt is emitted",
                            "No-change arm requires its actual deployed decision model/Head, not a proxy"]}
