"""Bridge the shared-encoder qualification harness to Stem/Cell contracts.

The bridge is deliberately an adapter, not an evaluator or selector. It
converts a qualified receipt into content-addressed Stem/Cell artifacts and
resource ledgers. Synthetic smoke and historical replay are retained as
diagnostic evidence and can never satisfy a split or promotion gate.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any, Iterable


def _load_contracts():
    try:
        from stem_transfer_cell_artifact import (  # type: ignore
            CellArtifactV1,
            ContractError,
            ParameterLedgerV1,
            SplitGateV1,
            StemManifestV1,
            TransferCaseV1,
            TransferMatrixV1,
        )
        return CellArtifactV1, ContractError, ParameterLedgerV1, SplitGateV1, StemManifestV1, TransferCaseV1, TransferMatrixV1
    except ModuleNotFoundError:
        contract_path = Path(__file__).resolve().parents[2] / "stem-transfer-cell-artifact-p0" / "stem_transfer_cell_artifact.py"
        spec = importlib.util.spec_from_file_location("stem_transfer_cell_artifact", contract_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load Stem contract: {contract_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.CellArtifactV1, module.ContractError, module.ParameterLedgerV1, module.SplitGateV1, module.StemManifestV1, module.TransferCaseV1, module.TransferMatrixV1


CellArtifactV1, ContractError, ParameterLedgerV1, SplitGateV1, StemManifestV1, TransferCaseV1, TransferMatrixV1 = _load_contracts()

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


def _digest(name: str, value: str) -> None:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ContractError(f"{name} must be a lowercase sha256")


def _identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise ContractError(f"{name} is not a stable identifier")


def _bounded(name: str, value: str, limit: int = 256) -> None:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ContractError(f"{name} has an invalid length")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArtifactIdentityV1:
    stem_digest: str
    stem_generation: int
    cell_generation: int
    run_generation: int
    authority_epoch: str
    principal: str
    purpose: str
    source_digest: str
    input_digest: str
    preprocessor_digest: str

    def __post_init__(self) -> None:
        _digest("stem_digest", self.stem_digest)
        for name, value in (("source_digest", self.source_digest), ("input_digest", self.input_digest), ("preprocessor_digest", self.preprocessor_digest)):
            _digest(name, value)
        if self.stem_generation < 0 or self.cell_generation < 0 or self.run_generation < 1:
            raise ContractError("run and artifact generations must be positive where required")
        _bounded("authority_epoch", self.authority_epoch)
        _bounded("principal", self.principal)
        _bounded("purpose", self.purpose)


@dataclass(frozen=True)
class FeatureKeyV1:
    stem_digest: str
    stem_generation: int
    cell_generation: int
    run_generation: int
    authority_epoch: str
    principal: str
    purpose: str
    source_digest: str
    input_digest: str
    preprocessor_digest: str
    readonly: bool = True

    def __post_init__(self) -> None:
        _digest("stem_digest", self.stem_digest)
        for name, value in (("source_digest", self.source_digest), ("input_digest", self.input_digest), ("preprocessor_digest", self.preprocessor_digest)):
            _digest(name, value)
        if self.run_generation < 1 or self.stem_generation < 0 or self.cell_generation < 0:
            raise ContractError("FeatureKey generation is stale")
        _bounded("authority_epoch", self.authority_epoch)
        _bounded("principal", self.principal)
        _bounded("purpose", self.purpose)
        if not self.readonly:
            raise ContractError("FeatureKey must be readonly")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": "hepta.feature-key.bridge.v1"}


def feature_key_for_artifact(artifact: Any, identity: ArtifactIdentityV1) -> FeatureKeyV1:
    """Bind a feature key to a Cell artifact without granting admission authority."""

    if artifact.stem_digest != identity.stem_digest:
        raise ContractError("feature key Stem digest does not match Cell artifact")
    if artifact.generation != identity.cell_generation:
        raise ContractError("feature key Cell generation does not match artifact")
    return FeatureKeyV1(
        stem_digest=identity.stem_digest,
        stem_generation=identity.stem_generation,
        cell_generation=identity.cell_generation,
        run_generation=identity.run_generation,
        authority_epoch=identity.authority_epoch,
        principal=identity.principal,
        purpose=identity.purpose,
        source_digest=identity.source_digest,
        input_digest=identity.input_digest,
        preprocessor_digest=identity.preprocessor_digest,
    )


@dataclass(frozen=True)
class QualificationReceiptV1:
    task_id: str
    modality: str
    stem_digest: str
    source_digest: str
    budget_digest: str
    quality: float
    flops: float
    memory_bytes: float
    latency_ms: float
    risk: float
    stem_params: int
    projector_params: int
    resident_cell_params: int
    active_cell_params: int
    state_params: int
    cache_params: int
    logical_cells: int
    active_cells: int
    evidence_class: str
    independent_new_source: bool
    reader_citations: int
    model_input_gold_visible: bool = False
    feature_key: FeatureKeyV1 | None = None

    def __post_init__(self) -> None:
        _identifier("task_id", self.task_id)
        _bounded("modality", self.modality, 64)
        for name, value in (("stem_digest", self.stem_digest), ("source_digest", self.source_digest), ("budget_digest", self.budget_digest)):
            _digest(name, value)
        for name, value in (("quality", self.quality), ("flops", self.flops), ("memory_bytes", self.memory_bytes), ("latency_ms", self.latency_ms), ("risk", self.risk)):
            if value < 0:
                raise ContractError(f"{name} must be non-negative")
        for name in ("stem_params", "projector_params", "resident_cell_params", "active_cell_params", "state_params", "cache_params", "logical_cells", "active_cells", "reader_citations"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise ContractError(f"{name} must be a non-negative integer")
        if self.active_cell_params > self.resident_cell_params or self.active_cells > self.logical_cells:
            raise ContractError("active resource counts exceed resident/logical counts")
        if self.evidence_class not in {"REAL_SHADOW", "SYNTHETIC_SMOKE", "HISTORICAL_REPLAY"}:
            raise ContractError("unknown evidence class")
        if not self.independent_new_source:
            raise ContractError("transfer evidence requires an independent new source")
        if self.model_input_gold_visible:
            raise ContractError("gold cannot be visible to the model")
        if self.feature_key is not None:
            if self.feature_key.stem_digest != self.stem_digest or self.feature_key.source_digest != self.source_digest:
                raise ContractError("feature key does not match receipt identity")

    def to_transfer_case(self) -> Any:
        return TransferCaseV1(self.task_id, self.modality, self.stem_digest, self.source_digest, self.quality, self.flops, self.memory_bytes, self.latency_ms, self.risk)

    def to_ledger(self) -> Any:
        return ParameterLedgerV1(self.stem_params, self.projector_params, self.resident_cell_params, self.active_cell_params, self.state_params, self.cache_params, self.logical_cells, self.active_cells)


def transfer_matrix_from_receipts(stem: Any, receipts: Iterable[QualificationReceiptV1], matched_budget_digest: str) -> Any:
    items = tuple(receipts)
    if not items:
        raise ContractError("at least one qualification receipt is required")
    _digest("matched_budget_digest", matched_budget_digest)
    for receipt in items:
        if receipt.stem_digest != stem.stem_digest:
            raise ContractError("receipt Stem digest mismatch")
        if receipt.budget_digest != matched_budget_digest:
            raise ContractError("resource budget digest mismatch")
    return TransferMatrixV1(
        matrix_id=f"bridge.{matched_budget_digest[:16]}",
        stem=stem,
        cases=tuple(receipt.to_transfer_case() for receipt in items),
        matched_budget_digest=matched_budget_digest,
    )


@dataclass(frozen=True)
class ReaderGateReceiptV1:
    evidence_class: str
    independent_new_source: bool
    reader_sufficient: bool
    citation_coverage: float
    future_lcb: float
    baseline_ucb: float
    old_task_degradation: float
    ece: float
    ood_false_acceptance: float
    fallback_coverage: float
    rollback_recovery: float
    deleted_replay: int
    model_input_gold_visible: bool = False

    def __post_init__(self) -> None:
        if self.evidence_class not in {"REAL_SHADOW", "SYNTHETIC_SMOKE", "HISTORICAL_REPLAY"}:
            raise ContractError("unknown Reader evidence class")
        if not self.independent_new_source or self.model_input_gold_visible:
            raise ContractError("Reader evidence identity is not admissible")
        for name, value in (("citation_coverage", self.citation_coverage), ("future_lcb", self.future_lcb), ("baseline_ucb", self.baseline_ucb), ("old_task_degradation", self.old_task_degradation), ("ece", self.ece), ("ood_false_acceptance", self.ood_false_acceptance), ("fallback_coverage", self.fallback_coverage), ("rollback_recovery", self.rollback_recovery)):
            if value < 0:
                raise ContractError(f"{name} must be non-negative")
        if self.deleted_replay < 0:
            raise ContractError("deleted_replay must be non-negative")

    def to_split_gate(self) -> Any:
        sufficient = self.reader_sufficient and self.citation_coverage == 1.0 and self.evidence_class == "REAL_SHADOW"
        return SplitGateV1(
            future_lcb=self.future_lcb,
            baseline_ucb=self.baseline_ucb,
            old_task_degradation=self.old_task_degradation,
            ece=self.ece,
            ood_false_acceptance=self.ood_false_acceptance,
            fallback_coverage=self.fallback_coverage,
            rollback_recovery=self.rollback_recovery,
            deleted_replay=self.deleted_replay,
            reader_sufficient=sufficient,
        )


__all__ = [
    "ArtifactIdentityV1",
    "FeatureKeyV1",
    "QualificationReceiptV1",
    "ReaderGateReceiptV1",
    "feature_key_for_artifact",
    "sha256_text",
    "transfer_matrix_from_receipts",
]
