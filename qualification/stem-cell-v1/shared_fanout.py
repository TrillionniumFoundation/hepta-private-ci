"""One physical shared Encoder view feeding many independently trained Cell banks.

Qualification-only CPU FP32 online experiment. A view is reusable ONLY for
exactly the same scope + complete state/question/ordered-options input. Different
questions, principals, time windows or Encoder versions cannot share it. This
module deliberately has no persistent or cross-request feature cache.

The 'separate' control re-executes the actual supplied Encoder for EACH bank;
there are no synthetic cost multipliers or divided-by-N latency claims. Both
paths pay their own Head/router work and retain their execution observations.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass

import torch

from execution_meter import WorkLedger
from head_surgery import tensor_inventory
from matrix_bank import state_digest
from matrix_materials import PUBLIC_FIELDS
from next_round_matrix import _digest
from paired_execution import PHASES


@dataclass(frozen=True)
class CellConsumer:
    """Task-specific trained bank for exactly one admitted representation."""
    task_id: str
    scope: str
    view_sha256: str
    bank: torch.nn.Module


def view_digest(row):
    """Bind the complete public request, not just the state or a pooled vector."""
    if (not isinstance(row, dict) or set(row) != PUBLIC_FIELDS
            or any(not isinstance(row[k], str) or not row[k] or len(row[k].encode()) > 65536
                   for k in ("scope", "sample_id", "source_group", "state", "question"))
            or type(row["available_at_ns"]) is not int or row["available_at_ns"] <= 0
            or not isinstance(row["options"], list) or not 2 <= len(row["options"]) <= 16
            or any(not isinstance(v, str) or not v or len(v.encode()) > 4096
                   for v in row["options"])):
        raise ValueError("complete bounded single-scope public input required")
    # The entire input (including ordered options) has one identity. Including
    # time and sample ID may forgo a cache hit, but never leaks cross-task state.
    return _digest(row)


def _require_consumers(row, consumers, *, max_total_cells=4096):
    digest = view_digest(row)
    if not isinstance(consumers, (list, tuple)) or not 1 <= len(consumers) <= 256:
        raise ValueError("bounded 1..256 consumer views required")
    if type(max_total_cells) is not int or not 1 <= max_total_cells <= 4096:
        raise ValueError("invalid total logical Cell limit")
    names, bank_objects, logical = set(), set(), 0
    for entry in consumers:
        if not isinstance(entry, CellConsumer):
            raise ValueError("typed CellConsumer required")
        if (not isinstance(entry.task_id, str) or not entry.task_id
                or len(entry.task_id) > 128 or entry.task_id in names):
            raise ValueError("distinct nonempty bounded task IDs required")
        names.add(entry.task_id)
        if entry.scope != row["scope"] or entry.view_sha256 != digest:
            raise ValueError("cross-scope or cross-query feature reuse forbidden")
        bank = entry.bank
        if not isinstance(bank, torch.nn.Module) or id(bank) in bank_objects:
            raise ValueError("independent typed bank object required for each task")
        bank_objects.add(id(bank))
        if bank.training or getattr(bank, "dimension", None) is None:
            raise ValueError("frozen eval-mode bank with explicit input dimension required")
        logical_cells = getattr(bank, "heads", None)
        if logical_cells is None or not 1 <= len(logical_cells) <= 4096:
            raise ValueError("qualified CellBank head inventory required")
        logical += len(logical_cells)
        for tensor in bank.parameters():
            if tensor.device.type != "cpu" or tensor.dtype != torch.float32:
                raise ValueError("CPU FP32 bank required")
    if logical > max_total_cells:
        raise ValueError("total logical Cell ceiling exceeded")
    return digest, logical


def _encode_and_validate(encoder, row, dimension, feature_limit):
    feature, n_tokens = encoder(dict(row))
    if (not isinstance(feature, torch.Tensor) or feature.shape != (dimension,)
            or feature.dtype != torch.float32 or feature.device.type != "cpu"
            or feature.requires_grad or not torch.isfinite(feature).all().item()
            or type(n_tokens) is not int or n_tokens < 1
            or feature.untyped_storage().nbytes() > feature_limit):
        raise ValueError("Encoder produced an unsafe or over-budget shared view")
    return feature, n_tokens


def _execute(encoder, row, consumers, *, shared, policy, caps,
             max_feature_bytes, expected_view_digest):
    """Measure actual dispatch; no replay-estimated Encoder math."""
    dimension = consumers[0].bank.dimension
    meter = WorkLedger(policy, caps)
    logits, encoder_calls, token_counts, call_ns = [], 0, [], []
    before = [state_digest(v.bank) for v in consumers]
    started = time.perf_counter_ns()
    feature = None
    try:
        with torch.inference_mode():
            for i, entry in enumerate(consumers):
                if not shared or feature is None:
                    begin = time.perf_counter_ns()
                    with meter.scope("inference", "encoder"):
                        encoder_calls += 1
                        feature, n_tokens = _encode_and_validate(
                            encoder, row, dimension, max_feature_bytes)
                    call_ns.append(time.perf_counter_ns() - begin)
                elif feature is not None:
                    # The cached value never outlives this one request and must
                    # be for the exact same input and principal.
                    n_tokens = token_counts[0]
                if entry.bank.dimension != dimension:
                    raise ValueError("consumer Encoder feature width mismatch")
                with meter.scope("inference", "bank"):
                    values = entry.bank(feature.unsqueeze(0))
                    if (values.ndim != 2 or values.shape[0] != 1
                            or not torch.isfinite(values).all().item()):
                        raise ValueError("invalid CellBank output")
                    logits.append(values[0].detach().clone().tolist())
                token_counts.append(n_tokens)
                if not shared:
                    del feature
                    feature = None
        if view_digest(row) != expected_view_digest:
            raise ValueError("request input changed during execution")
        if [state_digest(v.bank) for v in consumers] != before:
            raise ValueError("CellBank parameters changed during evaluation")
        if shared and encoder_calls != 1:
            raise ValueError("shared Encoder was redundantly invoked")
        if not shared and encoder_calls != len(consumers):
            raise ValueError("independent Encoder control omitted calls")
        observed = meter.report()
        return dict(status="completed", encoder_calls=encoder_calls,
                    token_counts=token_counts, per_encoder_call_wall_ns=call_ns,
                    elapsed_ns=time.perf_counter_ns()-started,
                    logits=logits, work_observation=observed,
                    formula_flops=observed["phase_flops"]["inference"])
    except BaseException:
        # Deliberately fail the experiment; no completed/partial logits are
        # emitted as an apparently successful quality comparison.
        raise
    finally:
        feature = None


def measure_fanout(encoder, row, consumers, *, policy, caps=None,
                   max_feature_bytes=4 * 1024 * 1024, max_total_cells=4096,
                   atol=1e-6, rtol=1e-6):
    """Execute shared first, then physically repeated Encoder control.

    Same-order single-pass timings include instrumentation/first-call effects;
    they are observations, NOT randomized hardware latency measurements. No
    pretraining/independent-task success, energy or full-system gain is issued.
    """
    from execution_meter import validate_policy
    validate_policy(policy)
    if caps is None:
        caps = dict.fromkeys(PHASES, 10**13)
    if not isinstance(caps, dict) or set(caps) != set(PHASES):
        raise ValueError("all phase caps must be explicit")
    for value in caps.values():
        if type(value) is not int or value < 0:
            raise ValueError("nonnegative integer formula caps required")
    if type(max_feature_bytes) is not int or not 4 <= max_feature_bytes <= 256 * 1024 * 1024:
        raise ValueError("bounded retained feature storage required")
    for tol in (atol, rtol):
        if type(tol) not in (float,int) or not math.isfinite(tol) or not 0 <= tol <= 1e-3:
            raise ValueError("preregister bounded numeric comparison tolerance")
    digest, total_cells = _require_consumers(row, consumers, max_total_cells=max_total_cells)
    before = [state_digest(c.bank) for c in consumers]
    shared = _execute(encoder, row, consumers, shared=True, policy=policy,
        caps=caps, max_feature_bytes=max_feature_bytes, expected_view_digest=digest)
    repeated = _execute(encoder, row, consumers, shared=False, policy=policy,
        caps=caps, max_feature_bytes=max_feature_bytes, expected_view_digest=digest)
    if [state_digest(c.bank) for c in consumers] != before:
        raise ValueError("CellBank changed across shared/repeated execution")
    if shared["token_counts"] != repeated["token_counts"]:
        raise ValueError("reused Encoder view changed tokenization")
    maximum_abs_diff = 0.
    for cached, single in zip(shared["logits"], repeated["logits"], strict=True):
        if len(cached) != len(single):
            raise ValueError("reused Encoder view changed output classes")
        for a, b in zip(cached, single, strict=True):
            maximum_abs_diff=max(maximum_abs_diff,abs(a-b))
            if abs(a-b)>atol+rtol*abs(b):
                raise ValueError("reused Encoder view changed task logits")
    unique_bank_bytes = tensor_inventory(torch.nn.ModuleList([c.bank for c in consumers]))["unique_weight_bytes"]
    a,b=shared["formula_flops"],repeated["formula_flops"]
    return dict(schema="hepta.shared-encoder-fanout-mechanism.v1",
        request_digest=digest, scope_digest=hashlib.sha256(row["scope"].encode()).hexdigest(),
        consumer_task_ids=[c.task_id for c in consumers],
        logical_cells=total_cells, actual_banks=len(consumers),
        standalone_encoder_calls=repeated["encoder_calls"],
        shared_encoder_calls=shared["encoder_calls"],
        encoder_reuse_validated_for_identical_request_only=True,
        per_request_cache_persisted=False, max_logit_abs_difference=maximum_abs_diff,
        bank_unique_weight_bytes=unique_bank_bytes,
        retained_view_payload_limit_bytes=max_feature_bytes,
        results=dict(shared=shared, repeated=repeated),
        formula_work_reduction=(b-a) if a is not None and b is not None else None,
        formula_work_reduction_fraction=(b-a)/b if a is not None and b not in (None,0) else None,
        confidence_intervals=False, throughput_benchmark_established=False,
        independent_task_learning_established=False,
        general_question_reuse_validated=False, system_energy_measured=False,
        production_authorized=False)
