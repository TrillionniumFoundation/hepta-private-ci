#!/usr/bin/env python3
"""Dependency-free multimodal Cell contract and shadow experiment.

The experiment keeps one deterministic, frozen shared-encoder feature cache and
trains one small modality adapter plus one per-Cell gate/head for each of
``text``, ``image``, ``audio`` and ``video``.  Every modality receives the same
estimated adapter/gate/head FLOP budget.  The result is a qualification
artifact only:

    mode = SHADOW_ONLY
    authority = DENY_ALL

No model provider, external effect, selected artifact or live runtime weight is
invoked or mutated.  Unsupported modalities, parent digest drift and wrong
modality calls fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import math
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


SUPPORTED_MODALITIES = ("text", "image", "audio", "video")
PROTOCOL_MODE = "SHADOW_ONLY"
# ``MODE`` is retained as a short compatibility alias for the first draft of
# the contract API.  New callers should use ``PROTOCOL_MODE``.
MODE = PROTOCOL_MODE
AUTHORITY = "DENY_ALL"
# Short alias kept for small callers and older shadow test fixtures.
MODE = PROTOCOL_MODE


class ContractError(ValueError):
    """A contract, digest, budget or lineage invariant failed."""


class UnsupportedModality(ContractError):
    """The requested modality is outside the registered capability set."""


class WrongModality(ContractError):
    """A Cell was asked to consume a row from another modality."""


class LineageError(ContractError):
    """A rollback target is not in the immutable candidate lineage."""


def _digest_bytes(*parts: object) -> bytes:
    return "|".join(str(part) for part in parts).encode("utf-8")


def digest_text(*parts: object) -> str:
    return hashlib.sha256(_digest_bytes(*parts)).hexdigest()


def _unit_float(*parts: object) -> float:
    raw = int.from_bytes(hashlib.sha256(_digest_bytes(*parts)).digest()[:8], "big")
    return (raw / float(1 << 64)) * 2.0 - 1.0


def _sigmoid(value: float) -> float:
    value = max(-40.0, min(40.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def _bounded_utility(error: float) -> float:
    return max(0.0, min(1.0, 1.0 - abs(error)))


def _mse(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ContractError("alignment vectors have different dimensions")
    return sum((a - b) ** 2 for a, b in zip(left, right)) / max(1, len(left))


@dataclass(frozen=True)
class CachedSample:
    sample_id: str
    split: str
    features: Tuple[float, ...]
    latent_target: Tuple[float, ...]
    task_target: float


@dataclass(frozen=True)
class FeatureCache:
    """A single immutable encoder cache shared by all modalities and Cells."""

    seed: int
    feature_dim: int
    latent_dim: int
    samples: Tuple[CachedSample, ...]
    encoder_digest: str
    frozen: bool = True

    @property
    def digest(self) -> str:
        """Compatibility alias for the frozen shared encoder digest."""
        return self.encoder_digest

    def rows_for(self, modality: str) -> Tuple["FeatureRow", ...]:
        require_modality(modality)
        return tuple(FeatureRow(sample, modality) for sample in self.samples)


@dataclass(frozen=True)
class FeatureRow:
    sample: CachedSample
    modality: str

    @property
    def sample_id(self) -> str:
        return self.sample.sample_id

    @property
    def split(self) -> str:
        return self.sample.split

    @property
    def features(self) -> Tuple[float, ...]:
        return self.sample.features

    @property
    def latent_target(self) -> Tuple[float, ...]:
        return self.sample.latent_target

    @property
    def task_target(self) -> float:
        return self.sample.task_target


def require_modality(modality: str) -> None:
    if modality not in SUPPORTED_MODALITIES:
        raise UnsupportedModality(f"unsupported modality: {modality!r}")


def build_feature_cache(
    seed: int = 17,
    *,
    feature_dim: int = 6,
    latent_dim: int = 4,
    train_rows: int = 32,
    future_rows: int = 16,
) -> FeatureCache:
    """Build deterministic shared features and cross-modal target latents."""
    if feature_dim < 1 or latent_dim < 1 or train_rows < 1 or future_rows < 1:
        raise ValueError("dimensions and row counts must be positive")
    samples: List[CachedSample] = []
    for split, count in (("train", train_rows), ("future", future_rows)):
        for index in range(count):
            sample_id = digest_text("sample", seed, split, index)
            features = tuple(_unit_float("shared-encoder", seed, split, index, i)
                             for i in range(feature_dim))
            latent_target = tuple(_unit_float("shared-latent-target", seed, index, i)
                                  for i in range(latent_dim))
            task_target = _sigmoid(
                0.35 * _unit_float("task-bias", seed, index)
                + sum(
                    0.22 * _unit_float("task-weight", seed, i) * features[i]
                    for i in range(feature_dim)
                )
            )
            samples.append(CachedSample(sample_id, split, features, latent_target, task_target))
    payload = [
        {
            "sample_id": sample.sample_id,
            "split": sample.split,
            "features": sample.features,
            "latent_target": sample.latent_target,
            "task_target": sample.task_target,
        }
        for sample in samples
    ]
    encoder_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return FeatureCache(seed, feature_dim, latent_dim, tuple(samples), encoder_digest)


@dataclass
class ModalityAdapter:
    modality: str
    feature_dim: int
    latent_dim: int
    weights: Tuple[Tuple[float, ...], ...]
    bias: Tuple[float, ...]

    @classmethod
    def initialize(cls, modality: str, feature_dim: int, latent_dim: int, seed: int) -> "ModalityAdapter":
        require_modality(modality)
        weights = tuple(
            tuple(0.05 * _unit_float("adapter", seed, modality, out, inp)
                  for inp in range(feature_dim))
            for out in range(latent_dim)
        )
        bias = tuple(0.01 * _unit_float("adapter-bias", seed, modality, out)
                     for out in range(latent_dim))
        return cls(modality, feature_dim, latent_dim, weights, bias)

    @property
    def parameter_count(self) -> int:
        return self.latent_dim * self.feature_dim + self.latent_dim

    @property
    def digest(self) -> str:
        return digest_text(self.modality, self.feature_dim, self.latent_dim, self.weights, self.bias)

    def encode(self, features: Sequence[float], modality: str | None = None) -> Tuple[float, ...]:
        requested = self.modality if modality is None else modality
        require_modality(requested)
        if requested != self.modality:
            raise WrongModality(f"adapter {self.modality!r} cannot consume {requested!r}")
        if len(features) != self.feature_dim:
            raise ContractError("feature dimension mismatch")
        return tuple(
            math.tanh(self.bias[out] + sum(self.weights[out][inp] * features[inp]
                                           for inp in range(self.feature_dim)))
            for out in range(self.latent_dim)
        )


@dataclass(frozen=True)
class CellContract:
    """Unified modality/lineage/budget/capability/authority contract."""

    cell_id: str
    modality: str
    parent_digest: str
    adapter_digest: str
    budget_flops: int
    capability: Tuple[str, ...]
    authority: str = AUTHORITY
    mode: str = PROTOCOL_MODE
    predecessor_digest: str = ""
    revision: int = 1

    def validate(self, expected_parent_digest: str | None = None) -> None:
        require_modality(self.modality)
        if not self.cell_id or len(self.cell_id) > 128:
            raise ContractError("invalid cell_id")
        for label, value in (("parent_digest", self.parent_digest), ("adapter_digest", self.adapter_digest)):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ContractError(f"invalid {label}")
        if expected_parent_digest is not None:
            # Accepting a FeatureCache here keeps the early registry API
            # source-compatible while the contract itself stores only the
            # immutable digest.
            expected = getattr(expected_parent_digest, "encoder_digest", expected_parent_digest)
            if self.parent_digest != expected:
                raise ContractError("parent digest drift")
        if self.budget_flops <= 0:
            raise ContractError("budget must be positive")
        if not self.capability or len(set(self.capability)) != len(self.capability):
            raise ContractError("capability must be non-empty and unique")
        if self.authority != AUTHORITY or self.mode != PROTOCOL_MODE:
            raise ContractError("runtime authority is not permitted")
        if self.revision < 1:
            raise ContractError("revision must be positive")
        if self.predecessor_digest and (
            len(self.predecessor_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.predecessor_digest)
        ):
            raise ContractError("invalid predecessor digest")

    @property
    def digest(self) -> str:
        self.validate()
        payload = {
            "cell_id": self.cell_id,
            "modality": self.modality,
            "parent_digest": self.parent_digest,
            "adapter_digest": self.adapter_digest,
            "budget_flops": self.budget_flops,
            "capability": self.capability,
            "authority": self.authority,
            "mode": self.mode,
            "predecessor_digest": self.predecessor_digest,
            "revision": self.revision,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def as_dict(self) -> Dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "modality": self.modality,
            "parent_digest": self.parent_digest,
            "adapter_digest": self.adapter_digest,
            "budget_flops": self.budget_flops,
            "capability": list(self.capability),
            "authority": self.authority,
            "mode": self.mode,
            "predecessor_digest": self.predecessor_digest,
            "revision": self.revision,
            "contract_digest": self.digest,
        }


@dataclass
class CellModel:
    """A small modality adapter plus per-Cell gate and prediction head."""

    cell_id: str
    modality: str
    parent_digest: str
    adapter: ModalityAdapter
    gate_weights: List[float]
    gate_bias: float
    head_weights: List[float]
    head_bias: float

    @property
    def parameter_count(self) -> int:
        return self.adapter.parameter_count + len(self.gate_weights) + 1 + len(self.head_weights) + 1

    @property
    def weights_digest(self) -> str:
        return digest_text(
            self.cell_id,
            self.modality,
            self.adapter.digest,
            tuple(self.gate_weights),
            self.gate_bias,
            tuple(self.head_weights),
            self.head_bias,
        )

    def _forward(self, row: FeatureRow) -> Tuple[Tuple[float, ...], float, float]:
        if row.modality != self.modality:
            raise WrongModality(f"Cell {self.cell_id} expects {self.modality}, received {row.modality}")
        latent = self.adapter.encode(row.features, row.modality)
        gate = _sigmoid(self.gate_bias + sum(w * value for w, value in zip(self.gate_weights, latent)))
        gated = tuple(gate * value for value in latent)
        prediction = _sigmoid(self.head_bias + sum(w * value for w, value in zip(self.head_weights, gated)))
        return latent, gate, prediction

    def predict(self, row: FeatureRow) -> float:
        return self._forward(row)[2]

    def train_step(self, row: FeatureRow, learning_rate: float, alignment_weight: float = 0.35) -> None:
        latent, gate, prediction = self._forward(row)
        task_error = prediction - row.task_target
        task_derivative = task_error * prediction * (1.0 - prediction)
        gated = tuple(gate * value for value in latent)
        old_head = tuple(self.head_weights)
        for index, value in enumerate(gated):
            self.head_weights[index] -= learning_rate * task_derivative * value
        self.head_bias -= learning_rate * task_derivative
        gate_signal = sum(weight * value for weight, value in zip(old_head, latent))
        gate_derivative = task_derivative * gate_signal * gate * (1.0 - gate)
        for index, value in enumerate(latent):
            self.gate_weights[index] -= learning_rate * gate_derivative * value
        self.gate_bias -= learning_rate * gate_derivative
        # A bounded alignment gradient keeps every modality in the same latent
        # coordinate system while the gate/head learns task utility.
        latent_gradient = [
            alignment_weight * (latent[index] - row.latent_target[index])
            + task_derivative * old_head[index] * gate
            + gate_derivative * self.gate_weights[index]
            for index in range(len(latent))
        ]
        for out in range(self.adapter.latent_dim):
            tanh_derivative = 1.0 - latent[out] * latent[out]
            scaled = learning_rate * latent_gradient[out] * tanh_derivative
            updated_weights = list(self.adapter.weights)
            for inp in range(self.adapter.feature_dim):
                updated_weights[out] = tuple(
                    value - scaled * row.features[inp] if index == inp else value
                    for index, value in enumerate(updated_weights[out])
                )
            self.adapter.weights = tuple(updated_weights)
            self.adapter.bias = tuple(
                value - scaled if index == out else value
                for index, value in enumerate(self.adapter.bias)
            )


@dataclass(frozen=True)
class CellSnapshot:
    artifact_digest: str
    contract_digest: str
    weights_digest: str
    predecessor_digest: str
    revision: int
    modality: str
    mode: str = PROTOCOL_MODE
    authority: str = AUTHORITY

    def as_dict(self) -> Dict[str, object]:
        return {
            "artifact_digest": self.artifact_digest,
            "contract_digest": self.contract_digest,
            "weights_digest": self.weights_digest,
            "predecessor_digest": self.predecessor_digest,
            "revision": self.revision,
            "modality": self.modality,
            "mode": self.mode,
            "authority": self.authority,
        }


@dataclass
class CellBundle:
    model: CellModel
    contract: CellContract
    initial_snapshot: CellSnapshot
    candidate_snapshot: CellSnapshot
    budget_flops: int
    update_count: int

    @property
    def cell_id(self) -> str:
        return self.model.cell_id

    @property
    def lineage(self) -> Tuple[CellSnapshot, ...]:
        return (self.initial_snapshot, self.candidate_snapshot)

    def rollback(self, artifact_digest: str) -> CellSnapshot:
        for snapshot in self.lineage:
            if snapshot.artifact_digest == artifact_digest:
                return snapshot
        raise LineageError("rollback target is not in immutable Cell lineage")


def _snapshot(
    model: CellModel,
    contract: CellContract,
    predecessor_digest: str,
    revision: int,
) -> CellSnapshot:
    contract.validate(model.parent_digest)
    weights_digest = model.weights_digest
    artifact_digest = digest_text(
        "cell-artifact-v1", contract.digest, weights_digest, predecessor_digest, revision
    )
    return CellSnapshot(
        artifact_digest=artifact_digest,
        contract_digest=contract.digest,
        weights_digest=weights_digest,
        predecessor_digest=predecessor_digest,
        revision=revision,
        modality=model.modality,
    )


def build_cell_bundle(
    cache: FeatureCache,
    modality: str,
    *,
    cell_index: int = 0,
    budget_updates: int = 32,
    learning_rate: float = 0.06,
) -> CellBundle:
    """Train one Cell candidate with exact, modality-independent update count."""
    require_modality(modality)
    if budget_updates < 1:
        raise ValueError("budget_updates must be positive")
    rows = cache.rows_for(modality)
    train_rows = tuple(row for row in rows if row.split == "train")
    if not train_rows:
        raise ContractError("feature cache has no training rows")
    adapter = ModalityAdapter.initialize(modality, cache.feature_dim, cache.latent_dim, cache.seed)
    model = CellModel(
        cell_id=f"{modality}-cell-{cell_index}",
        modality=modality,
        parent_digest=cache.encoder_digest,
        adapter=adapter,
        gate_weights=[0.02 * _unit_float("gate", cache.seed, modality, i) for i in range(cache.latent_dim)],
        gate_bias=0.0,
        head_weights=[0.02 * _unit_float("head", cache.seed, modality, i) for i in range(cache.latent_dim)],
        head_bias=0.0,
    )
    parameter_count = model.parameter_count
    per_update_flops = 2 * parameter_count
    budget_flops = budget_updates * per_update_flops
    capabilities = ("encode", "cross_modal_align", "predict", "rollback")
    initial_contract = CellContract(
        cell_id=model.cell_id,
        modality=modality,
        parent_digest=cache.encoder_digest,
        adapter_digest=adapter.digest,
        budget_flops=budget_flops,
        capability=capabilities,
        predecessor_digest="",
        revision=1,
    )
    initial_contract.validate(cache.encoder_digest)
    initial_snapshot = _snapshot(model, initial_contract, predecessor_digest="0" * 64, revision=1)
    for update in range(budget_updates):
        model.train_step(train_rows[update % len(train_rows)], learning_rate)
    candidate_contract = CellContract(
        cell_id=model.cell_id,
        modality=modality,
        parent_digest=cache.encoder_digest,
        adapter_digest=model.adapter.digest,
        budget_flops=budget_flops,
        capability=capabilities,
        predecessor_digest=initial_snapshot.artifact_digest,
        revision=2,
    )
    candidate_contract.validate(cache.encoder_digest)
    candidate_snapshot = _snapshot(
        model,
        candidate_contract,
        predecessor_digest=initial_snapshot.artifact_digest,
        revision=2,
    )
    return CellBundle(model, candidate_contract, initial_snapshot, candidate_snapshot, budget_flops, budget_updates)


def _bundle_metrics(bundle: CellBundle, cache: FeatureCache) -> Dict[str, object]:
    rows = cache.rows_for(bundle.model.modality)
    future_rows = tuple(row for row in rows if row.split == "future")
    predictions = [bundle.model.predict(row) for row in future_rows]
    task_utility = sum(_bounded_utility(pred - row.task_target) for pred, row in zip(predictions, future_rows)) / max(1, len(future_rows))
    alignment_losses = []
    for row in future_rows:
        latent, _, _ = bundle.model._forward(row)
        alignment_losses.append(_mse(latent, row.latent_target))
    alignment_loss = sum(alignment_losses) / max(1, len(alignment_losses))
    return {
        "cell_id": bundle.model.cell_id,
        "modality": bundle.model.modality,
        "parameter_count": bundle.model.parameter_count,
        "train_flops": bundle.budget_flops,
        "budget_flops": bundle.budget_flops,
        "future_task_utility": task_utility,
        "cross_modal_alignment_loss": alignment_loss,
        "cross_modal_alignment_utility": 1.0 / (1.0 + alignment_loss),
        "contract": bundle.contract.as_dict(),
        "candidate_snapshot": bundle.candidate_snapshot.as_dict(),
        "initial_snapshot": bundle.initial_snapshot.as_dict(),
        "mode": PROTOCOL_MODE,
        "authority": AUTHORITY,
    }


def _global_alignment(cache: FeatureCache, bundles: Sequence[CellBundle]) -> Tuple[float, float]:
    grouped: Dict[str, List[Tuple[float, ...]]] = {}
    for bundle in bundles:
        for row in cache.rows_for(bundle.model.modality):
            if row.split != "future":
                continue
            latent, _, _ = bundle.model._forward(row)
            grouped.setdefault(row.sample_id, []).append(latent)
    losses: List[float] = []
    for vectors in grouped.values():
        for left_index in range(len(vectors)):
            for right_index in range(left_index + 1, len(vectors)):
                losses.append(_mse(vectors[left_index], vectors[right_index]))
    loss = sum(losses) / max(1, len(losses))
    return loss, 1.0 / (1.0 + loss)


def run_experiment(
    seed: int = 17,
    *,
    feature_dim: int = 6,
    latent_dim: int = 4,
    train_rows: int = 32,
    future_rows: int = 16,
    budget_updates: int = 32,
) -> Dict[str, object]:
    cache = build_feature_cache(
        seed,
        feature_dim=feature_dim,
        latent_dim=latent_dim,
        train_rows=train_rows,
        future_rows=future_rows,
    )
    bundles = [
        build_cell_bundle(cache, modality, cell_index=index, budget_updates=budget_updates)
        for index, modality in enumerate(SUPPORTED_MODALITIES)
    ]
    metrics = [_bundle_metrics(bundle, cache) for bundle in bundles]
    alignment_loss, alignment_utility = _global_alignment(cache, bundles)
    budget_values = [bundle.budget_flops for bundle in bundles]
    return {
        "seed": seed,
        "encoder": {
            "frozen": cache.frozen,
            "feature_dim": feature_dim,
            "latent_dim": latent_dim,
            "shared_cache": True,
            "parent_digest": cache.encoder_digest,
        },
        "budget": {
            "updates_per_cell": budget_updates,
            "train_flops": budget_values[0],
            "all_modalities_equal": len(set(budget_values)) == 1,
            "cost_model": "2 * (adapter + gate + head parameters) per cached sample update",
        },
        "modalities": list(SUPPORTED_MODALITIES),
        "cells": metrics,
        "cross_modal": {
            "alignment_loss": alignment_loss,
            "alignment_utility": alignment_utility,
        },
        "lineage": {
            "rollback_targets": [bundle.initial_snapshot.artifact_digest for bundle in bundles],
            "candidate_predecessors_match": all(
                bundle.candidate_snapshot.predecessor_digest == bundle.initial_snapshot.artifact_digest
                for bundle in bundles
            ),
        },
        "protocol": {
            "mode": PROTOCOL_MODE,
            "authority": AUTHORITY,
            "unsupported_modality_fail_closed": True,
            "wrong_modality_fail_closed": True,
            "production_caller": False,
            "model_invocation": False,
            "provider_dispatch": False,
            "artifact_selection": False,
            "note": "synthetic held-out shadow comparison; no causal efficacy claim",
        },
    }


class CellRegistry:
    """Small in-memory registry used by the compatibility smoke path.

    Registration is validation only: it never selects a candidate for
    production and never mutates the shared encoder cache.  A duplicate Cell,
    parent-digest drift, unsupported modality, or non-positive budget is
    rejected before insertion.
    """

    def __init__(self, cache: FeatureCache):
        self.cache = cache
        self._cells: Dict[str, object] = {}

    def register(self, cell: object) -> object:
        cell_id = getattr(cell, "cell_id", None)
        contract = getattr(cell, "contract", None)
        if contract is None or cell_id is None:
            raise ContractError("registry requires a CellBundle-like object")
        if cell_id in self._cells:
            raise LineageError(f"duplicate cell id: {cell_id}")
        if contract.parent_digest != self.cache.encoder_digest:
            raise LineageError("parent digest drift")
        try:
            contract.validate(self.cache)
        except ContractError as exc:
            raise LineageError(str(exc)) from exc
        self._cells[cell_id] = cell
        return cell

    def rollback(self, cell_id: str) -> object:
        if cell_id not in self._cells:
            raise LineageError(f"unknown Cell: {cell_id}")
        return self._cells[cell_id]

    @property
    def cells(self) -> Tuple[object, ...]:
        return tuple(self._cells.values())


def split_cells(cache: FeatureCache, budget_flops: int) -> Tuple[CellBundle, ...]:
    """Build one candidate per registered modality under a common budget.

    ``build_cell_bundle`` exposes an exact update budget.  This compatibility
    helper accepts a FLOP budget and rounds down to a whole number of equal
    update units; the returned contract reports the realized budget.  The
    authoritative experiment path is ``run_experiment`` where equality is
    explicit in the result ledger.
    """
    if budget_flops <= 0:
        raise ContractError("budget must be positive")
    # For the default dimensions each update costs 76 FLOPs.  Derive the same
    # number from a zero-update model rather than relying on a magic constant.
    adapter = ModalityAdapter.initialize("text", cache.feature_dim, cache.latent_dim, cache.seed)
    per_update = 2 * (adapter.parameter_count + 2 * cache.latent_dim + 2)
    updates = max(1, budget_flops // per_update)
    return tuple(
        build_cell_bundle(cache, modality, cell_index=index, budget_updates=updates)
        for index, modality in enumerate(SUPPORTED_MODALITIES)
    )


def run(seed: int = 17, budget_flops: int | None = None) -> Dict[str, object]:
    """Compatibility view over :func:`run_experiment`.

    The richer result is available under the same return object; ``metrics``
    and flattened ``cells`` are included for consumers of the earlier draft
    API.  A requested budget is recorded as an input contract while the
    nested experiment continues to report its exact realized update budget.
    """
    result = run_experiment(seed=seed)
    requested = result["budget"]["train_flops"] if budget_flops is None else budget_flops
    if requested <= 0:
        raise ContractError("budget must be positive")
    result["encoder"]["digest"] = result["encoder"]["parent_digest"]
    result["metrics"] = {
        "budget_flops": requested,
        "alignment_loss": result["cross_modal"]["alignment_loss"],
        "alignment_utility": result["cross_modal"]["alignment_utility"],
    }
    result["cells"] = [
        {
            "cell_id": cell["cell_id"],
            "modality": cell["modality"],
            "parent_digest": cell["contract"]["parent_digest"],
            "adapter_digest": cell["contract"]["adapter_digest"],
            "budget_flops": requested,
            "capability": cell["contract"]["capability"],
            "mode": cell["mode"],
            "authority": cell["authority"],
            "contract_digest": cell["contract"]["contract_digest"],
        }
        for cell in result["cells"]
    ]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--budget-updates", type=int, default=32)
    args = parser.parse_args()
    print(json.dumps(run_experiment(seed=args.seed, budget_updates=args.budget_updates), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
