"""Bounded, qualification-only decision-head fitting in learning.operator.

This numerical leaf has no ledger writer, model executor, artifact selector or
production authority. The existing learning owner must resolve/authenticate the
frozen rows and revalidate their support before admitting the returned bytes.
Digests here bind data; they do not certify source permission or independence.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import re
import time
from typing import Callable

import torch
from torch import nn
from safetensors.torch import load as load_tensors, save as save_tensors

MAX_ROWS = 256
MAX_WIDTH = 2048
MAX_HEAD_BYTES = 32 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class HeadRejected(ValueError):
    pass


class TrainingExpired(RuntimeError):
    """Any candidate copy is discarded; already consumed work is not refunded."""
    def __init__(self, steps: int):
        super().__init__("training deadline exhausted or regressed")
        self.steps = steps


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def checked_digest(value: str) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value) or value == "0" * 64:
        raise HeadRejected("invalid digest")
    return value


def tensor_bytes(value: torch.Tensor) -> bytes:
    if (type(value) is not torch.Tensor or value.device.type != "cpu"
            or value.dtype != torch.float32 or value.layout != torch.strided
            or not value.is_contiguous()):
        raise HeadRejected("only contiguous CPU float32 tensors are admitted")
    if not bool(torch.isfinite(value).all()):
        raise HeadRejected("non-finite tensor")
    return value.detach().numpy().tobytes(order="C")


def _check_execution_profile(head: nn.Sequential) -> None:
    # Tensor digests cannot bind Python hooks, compiled callables, method
    # overrides or gradient transformations. Reject them before serialization,
    # deepcopy or forward/backward can invoke unregistered behavior. This is a
    # trusted in-process compatibility check, not a Python security sandbox.
    hooks = ("_forward_pre_hooks", "_forward_hooks", "_backward_pre_hooks",
             "_backward_hooks", "_state_dict_pre_hooks", "_state_dict_hooks",
             "_load_state_dict_pre_hooks", "_load_state_dict_post_hooks")
    methods = ("forward", "_call_impl", "_wrapped_call_impl", "state_dict",
               "load_state_dict", "_save_to_state_dict", "_load_from_state_dict",
               "__deepcopy__", "__reduce__", "__reduce_ex__", "__getstate__",
               "__setstate__", "named_modules", "modules", "parameters",
               "named_parameters", "_apply", "train", "eval", "requires_grad_")
    module_runtime = vars(nn.modules.module)
    if any(value for name, value in module_runtime.items()
           if name.startswith("_global_") and name.endswith("_hooks")):
        raise HeadRejected("global module callbacks are outside the scorer profile")
    for module in (head, *head):
        attributes = vars(module)
        if (any(attributes.get(name) for name in hooks)
                or any(name in attributes for name in methods)
                or getattr(module, "_compiled_call_impl", None) is not None):
            raise HeadRejected("scorer callbacks or executable overrides are not admitted")
        for parameter in module._parameters.values():
            if parameter is not None and (type(parameter) is not nn.Parameter
                    or getattr(parameter, "_backward_hooks", None)
                    or getattr(parameter, "_post_accumulate_grad_hooks", None)):
                raise HeadRejected("parameter gradient callbacks are not admitted")


def head_schema(head: nn.Module) -> dict:
    # Match the pinned Laya scorer, not arbitrary executable modules/dropout.
    if type(head) is not nn.Sequential or [type(m) for m in head] != [nn.LayerNorm, nn.Linear, nn.GELU, nn.Linear]:
        raise HeadRejected("unsupported head architecture")
    _check_execution_profile(head)
    width = head[1].in_features
    if (not 1 <= width <= MAX_WIDTH or head[0].normalized_shape != (width,)
            or head[1].out_features != width or head[3].in_features != width
            or head[3].out_features != 1 or not head[0].elementwise_affine
            or head[0].bias is None or head[1].bias is None or head[3].bias is None
            or head[2].approximate not in ("none", "tanh")
            or not math.isfinite(head[0].eps) or not 1e-8 <= head[0].eps <= 1):
        raise HeadRejected("head dimensions or normalization")
    if any(module.training for module in head.modules()):
        raise HeadRejected("selected head must be frozen in evaluation mode")
    state = head.state_dict()
    if set(state) != {"0.weight", "0.bias", "1.weight", "1.bias", "3.weight", "3.bias"}:
        raise HeadRejected("unexpected parameter or buffer inventory")
    if sum(t.numel() * t.element_size() for t in state.values()) > MAX_HEAD_BYTES:
        raise HeadRejected("head byte bound")
    expected_shapes = {"0.weight": (width,), "0.bias": (width,),
                       "1.weight": (width, width), "1.bias": (width,),
                       "3.weight": (1, width), "3.bias": (1,)}
    storages = set()
    for name, tensor in state.items():
        tensor_bytes(tensor)
        storage = tensor.untyped_storage().data_ptr()
        if tuple(tensor.shape) != expected_shapes[name] or storage in storages:
            raise HeadRejected("scorer shape or independent-storage contract")
        storages.add(storage)
    return {"schema": "hepta.cell-scorer.f32.v1", "width": width,
            "eps": head[0].eps, "gelu": head[2].approximate,
            "tensors": {k: list(v.shape) for k, v in sorted(state.items())}}


def state_digest(head: nn.Module) -> str:
    schema = head_schema(head)
    state = head.state_dict()
    h = hashlib.sha256(canonical(schema))
    for name, value in sorted(state.items()):
        h.update(canonical(name)); h.update(tensor_bytes(value))
    return h.hexdigest()


@dataclass(frozen=True)
class HeadRow:
    row_id: str
    group_id: str
    observed_at_ms: int
    scope_id: str
    objective_digest: str
    bundle_digest: str
    source_digest: str
    outcome_digest: str
    option_ids: tuple[str, ...]
    features: torch.Tensor
    target: torch.Tensor


def validate_rows(rows: tuple[HeadRow, ...], width: int, scope: str,
                  objective: str, bundle: str) -> str:
    if type(rows) is not tuple or len(rows) > MAX_ROWS:
        raise HeadRejected("bounded immutable row sequence required")
    if not isinstance(scope, str) or not ID.fullmatch(scope):
        raise HeadRejected("scope identity")
    checked_digest(objective); checked_digest(bundle)
    if any(type(row) is not HeadRow for row in rows):
        raise HeadRejected("invalid row")
    ids, outcomes = set(), set()
    h = hashlib.sha256(b"hepta.cell-head.dataset.v1\0")
    for row in rows:
        for value in (row.row_id, row.group_id):
            if not isinstance(value, str) or not ID.fullmatch(value):
                raise HeadRejected("row/group identity")
    for row in sorted(rows, key=lambda r: r.row_id):
        checked_digest(row.source_digest); checked_digest(row.outcome_digest)
        if row.row_id in ids or row.outcome_digest in outcomes:
            raise HeadRejected("duplicate row or outcome cannot increase support")
        ids.add(row.row_id); outcomes.add(row.outcome_digest)
        if (row.scope_id, row.objective_digest, row.bundle_digest) != (scope, objective, bundle):
            raise HeadRejected("scope/objective/model substitution")
        if type(row.observed_at_ms) is not int or not 0 < row.observed_at_ms < 2**63:
            raise HeadRejected("event time")
        keys = row.option_ids
        if (type(keys) is not tuple or not 2 <= len(keys) <= 9 or keys[0] != "abstain"
                or any(not isinstance(key, str) or not ID.fullmatch(key) for key in keys)
                or len(set(keys)) != len(keys) or tuple(sorted(keys[1:])) != keys[1:]):
            raise HeadRejected("complete canonical option set required")
        if (type(row.features) is not torch.Tensor or type(row.target) is not torch.Tensor
                or tuple(row.features.shape) != (len(keys), width)
                or tuple(row.target.shape) != (len(keys),)
                or row.features.requires_grad or row.target.requires_grad):
            raise HeadRejected("frozen feature/target shape")
        feature_bytes, target_bytes = tensor_bytes(row.features), tensor_bytes(row.target)
        if bool((row.target < 0).any()) or abs(float(row.target.sum()) - 1) > 1e-6:
            raise HeadRejected("invalid target distribution")
        h.update(canonical([row.row_id, row.group_id, row.observed_at_ms, scope,
                            objective, bundle, row.source_digest, row.outcome_digest, keys]))
        h.update(feature_bytes); h.update(target_bytes)
    return h.hexdigest()


@dataclass(frozen=True)
class HeadBudget:
    epochs: int = 2
    maximum_steps: int = 512
    minimum_groups: int = 2
    learning_rate: float = 0.01
    gradient_norm: float = 1.0
    maximum_delta_norm: float = 1.0
    owned_tensor_bytes: int = 128 * 1024 * 1024

    def validate(self) -> None:
        for value, low, high in ((self.epochs, 1, 16), (self.maximum_steps, 1, 4096),
                                 (self.minimum_groups, 2, MAX_ROWS),
                                 (self.owned_tensor_bytes, 1, 256 * 1024 * 1024)):
            if type(value) is not int or not low <= value <= high:
                raise HeadRejected("integer training budget")
        for value, low, high in ((self.learning_rate, 1e-6, 0.1),
                                 (self.gradient_norm, 1e-6, 4),
                                 (self.maximum_delta_norm, 1e-6, 4)):
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise HeadRejected("numeric training budget")


@dataclass(frozen=True)
class HeadFit:
    disposition: str
    base_bundle_digest: str
    baseline_head_digest: str
    candidate_head_digest: str
    objective_digest: str
    scope_id: str
    dataset_digest: str
    training_profile_digest: str
    temperature: float
    payload: bytes | None
    payload_sha256: str | None
    steps: int
    groups: int
    owned_tensor_accounting_bytes: int
    elapsed_seconds: float
    delta_norm: float


def fit_head(selected: nn.Module, rows: tuple[HeadRow, ...], *, scope: str,
             objective: str, bundle: str, temperature: float, budget: HeadBudget,
             deadline: float, clock: Callable[[], float] = time.monotonic) -> HeadFit:
    """Train a private scorer copy, never the selected model or evaluation rows.

    SGD without momentum, canonical row order and eval-mode deterministic scorer.
    A global L2 projection bounds changes; it does not establish utility gain.
    Owned-tensor accounting is conservative, not an OS resident-memory attestation.
    Loading/encoding/evaluation costs belong to the caller's same conserved budget.
    """
    if type(budget) is not HeadBudget:
        raise HeadRejected("training budget type")
    budget.validate()
    started = clock(); last = started; steps = 0
    def check_time() -> None:
        nonlocal last
        now = clock()
        if (type(now) not in (int, float) or not math.isfinite(now)
                or type(started) not in (int, float) or not math.isfinite(started)
                or type(deadline) not in (int, float)
                or not math.isfinite(deadline) or now < last or now >= deadline
                or deadline - started > 300):
            raise TrainingExpired(steps)
        last = now
    check_time()
    if (type(temperature) not in (int, float) or not math.isfinite(temperature)
            or not 0.01 <= temperature <= 100):
        raise HeadRejected("temperature must be a fixed positive base parameter")
    schema = head_schema(selected); width = schema["width"]
    baseline_digest = state_digest(selected)
    dataset = validate_rows(rows, width, scope, objective, bundle)
    profile_digest = digest({"algorithm": "canonical-sgd-soft-ce-projected.v1",
                             "budget": asdict(budget), "temperature": temperature,
                             "head_schema": schema})
    groups = len({row.group_id for row in rows})
    accounting = 0
    def result(candidate=None, delta=0.0):
        check_time()
        if state_digest(selected) != baseline_digest:
            raise HeadRejected("selected parameters changed during training")
        candidate_digest = baseline_digest if candidate is None else state_digest(candidate)
        payload = None if candidate is None else save_tensors(candidate.state_dict())
        payload_digest = None if payload is None else hashlib.sha256(payload).hexdigest()
        check_time()
        return HeadFit("no_change" if payload is None else "candidate", bundle,
                       baseline_digest, candidate_digest,
                       objective, scope, dataset, profile_digest, temperature, payload,
                       payload_digest, steps, groups, accounting, last - started, delta)
    if groups < budget.minimum_groups:
        return result()
    if len(rows) * budget.epochs > budget.maximum_steps:
        raise HeadRejected("requested epochs exceed step budget")
    head_bytes = sum(t.numel() * t.element_size() for t in selected.state_dict().values())
    feature_bytes = sum((r.features.numel() + r.target.numel()) * 4 for r in rows)
    # Candidate, reference, gradients, projection/serialization temporaries and
    # immutable feature copies. Encoder resident/activation allocation is separate.
    accounting = 8 * head_bytes + 2 * feature_bytes + 16 * 9 * width * 4
    if accounting > budget.owned_tensor_bytes:
        raise HeadRejected("tensor-copy budget exceeded before candidate allocation")
    check_time()
    # Borrowed Tensor storage is mutable even inside a frozen dataclass. Bind
    # the actual private copies before optimization: checking the caller again
    # at the end misses a change/copy/restore (ABA) of targets, features or base.
    frozen = tuple(replace(r, features=r.features.clone(), target=r.target.clone())
                   for r in sorted(rows, key=lambda r: r.row_id))
    candidate = copy.deepcopy(selected).eval().requires_grad_(True)
    check_time()
    if validate_rows(frozen, width, scope, objective, bundle) != dataset:
        raise HeadRejected("copied dataset snapshot differs from admitted rows")
    if state_digest(candidate) != baseline_digest:
        raise HeadRejected("copied base snapshot differs from selected head")
    reference = [p.detach().clone() for p in candidate.parameters()]
    optimizer = torch.optim.SGD(candidate.parameters(), lr=budget.learning_rate, momentum=0, foreach=False)
    for _ in range(budget.epochs):
        for row in frozen:
            features, target = row.features, row.target
            check_time(); _check_execution_profile(candidate)
            optimizer.zero_grad(set_to_none=True)
            logits = candidate(features).squeeze(-1) / temperature
            loss = -(target * torch.log_softmax(logits, dim=-1)).sum()
            if not bool(torch.isfinite(loss)):
                raise HeadRejected("non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(candidate.parameters(), budget.gradient_norm,
                                           error_if_nonfinite=True, foreach=False)
            check_time(); optimizer.step(); steps += 1
            with torch.no_grad():
                delta = math.sqrt(sum(float(((p - r).double() ** 2).sum())
                                      for p, r in zip(candidate.parameters(), reference)))
                if not math.isfinite(delta):
                    raise HeadRejected("non-finite parameter delta")
                if delta > budget.maximum_delta_norm:
                    scale = budget.maximum_delta_norm / delta
                    for p, r in zip(candidate.parameters(), reference):
                        p.copy_(r + scale * (p - r))
            check_time()
    # Targets/features are immutable by contract, and identity drift still rejects.
    if validate_rows(rows, width, scope, objective, bundle) != dataset:
        raise HeadRejected("training dataset changed during fitting")
    delta = math.sqrt(sum(float(((p.detach() - r).double() ** 2).sum())
                          for p, r in zip(candidate.parameters(), reference)))
    if delta > budget.maximum_delta_norm * (1 + 1e-4):
        raise HeadRejected("delta projection exceeded its bound")
    return result(None if state_digest(candidate) == baseline_digest else candidate, delta)


def restore_candidate(selected: nn.Module, fit: HeadFit, *, bundle: str,
                      scope: str, objective: str) -> nn.Module:
    """Decode candidate bytes into a NEW head; this is not artifact selection.

    An existing artifact owner must separately authenticate the manifest,
    compatibility, generation, dataset withdrawal and current-use permission.
    """
    baseline = state_digest(selected)
    if (fit.base_bundle_digest, fit.scope_id, fit.objective_digest, fit.baseline_head_digest) != (
            bundle, scope, objective, baseline):
        raise HeadRejected("candidate base/scope/objective mismatch")
    if fit.disposition != "candidate" or not isinstance(fit.payload, bytes) or not 1 <= len(fit.payload) <= MAX_HEAD_BYTES + 8192:
        raise HeadRejected("candidate payload is absent or oversized")
    if hashlib.sha256(fit.payload).hexdigest() != fit.payload_sha256:
        raise HeadRejected("candidate bytes changed")
    try:
        decoded = load_tensors(fit.payload)
    except Exception as error:
        raise HeadRejected("invalid candidate tensor encoding") from error
    state = selected.state_dict()
    if set(decoded) != set(state):
        raise HeadRejected("candidate tensor inventory changed")
    for name, tensor in decoded.items():
        if tensor.shape != state[name].shape:
            raise HeadRejected("candidate tensor shape changed")
        tensor_bytes(tensor)
    restored = copy.deepcopy(selected).eval()
    head_schema(restored)
    restored.load_state_dict(decoded, strict=True)
    if state_digest(restored) != fit.candidate_head_digest:
        raise HeadRejected("candidate tensor identity changed")
    return restored
