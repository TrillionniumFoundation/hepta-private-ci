"""Fail-closed future/OOD Reader matrix for the shared Stem research gate.

This is a receipt contract only. It does not run a model, train a Cell, or
select a production artifact.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib, json, math, re
from typing import Any, Mapping

SCHEMA = "hepta.prospective.future-ood-reader-matrix.v1"
ARM_ORDER = ("none", "distractor", "withheld", "full")
_SPLITS = {"future", "ood"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
REAL_SHADOW = "REAL_SHADOW"

class FutureOODMatrixError(ValueError):
    pass

def _req(ok: bool, msg: str):
    if not ok: raise FutureOODMatrixError(msg)
def _id(name: str, value: str): _req(isinstance(value,str) and _IDENT.fullmatch(value) is not None, f"{name} is not a stable identifier")
def _sha(name: str, value: str): _req(isinstance(value,str) and _HEX64.fullmatch(value) is not None, f"{name} must be sha256")
def _blob(name: str, value: str): _req(isinstance(value,str) and _HEX40.fullmatch(value) is not None, f"{name} must be Git blob sha1")
def _finite(name: str, value: Any): _req(type(value) in (int,float) and math.isfinite(float(value)) and float(value)>=0, f"{name} must be finite and non-negative")
def _canon(v: Any) -> str: return json.dumps(v, sort_keys=True, separators=(",",":"), ensure_ascii=True)
def digest(v: Any) -> str: return hashlib.sha256(_canon(v).encode()).hexdigest()

@dataclass(frozen=True)
class WindowSourceV1:
    window_id: str
    source_split: str
    source_digest: str
    source_blob_digest: str
    independent_new_source: bool = True
    model_input_gold_visible: bool = False
    def __post_init__(self):
        _id("window_id",self.window_id); _req(self.source_split in _SPLITS,"source_split must be future or ood")
        _sha("source_digest",self.source_digest); _blob("source_blob_digest",self.source_blob_digest)
        _req(type(self.independent_new_source) is bool and self.independent_new_source,"independent source is required")
        _req(type(self.model_input_gold_visible) is bool and not self.model_input_gold_visible,"gold cannot be model-visible")
    def to_dict(self): return {**asdict(self),"schema":"hepta.prospective.reader-window-source.v1"}

@dataclass(frozen=True)
class ReaderArmReceiptV1:
    candidate_id: str
    window_id: str
    arm: str
    checkpoint_receipt_digest: str
    calls: int
    input_tokens: int
    flops: float
    memory_bytes: float
    latency_ms: float
    evidence_class: str = REAL_SHADOW
    model_input_gold_visible: bool = False
    def __post_init__(self):
        _id("candidate_id",self.candidate_id); _id("window_id",self.window_id)
        _req(self.arm in ARM_ORDER,"unknown Reader arm"); _sha("checkpoint_receipt_digest",self.checkpoint_receipt_digest)
        _req(type(self.calls) is int and self.calls >= 1,"calls must be positive integer")
        _req(type(self.input_tokens) is int and self.input_tokens >= 0,"input_tokens must be non-negative integer")
        for n in ("flops","memory_bytes","latency_ms"): _finite(n,getattr(self,n))
        _req(self.evidence_class == REAL_SHADOW,"matrix requires raw REAL_SHADOW evidence")
        _req(type(self.model_input_gold_visible) is bool and not self.model_input_gold_visible,"gold cannot be model-visible")
    def to_dict(self): return {**asdict(self),"schema":"hepta.prospective.reader-arm-receipt.v1"}

@dataclass(frozen=True)
class GateOutcomeV1:
    retention_ok: bool
    calibration_ok: bool
    ood_ok: bool
    fallback_ok: bool
    rollback_ok: bool
    deletion_ok: bool
    def __post_init__(self):
        for n in asdict(self): _req(type(getattr(self,n)) is bool,f"{n} must be boolean")
    @property
    def all_ok(self): return all(asdict(self).values())

@dataclass(frozen=True)
class FutureOODReaderMatrixV1:
    matrix_id: str
    candidate_ids: tuple[str,...]
    windows: tuple[WindowSourceV1,...]
    receipts: tuple[ReaderArmReceiptV1,...]
    budget_digest: str
    checkpoint_receipt_digests: tuple[str,...]
    gates: GateOutcomeV1
    authority: str = "DENY_ALL"
    current_run_mutation: bool = False
    next_snapshot_only: bool = True
    status: str = "SHADOW_ONLY"
    def __post_init__(self):
        _id("matrix_id",self.matrix_id); _req(len(self.candidate_ids)>=2,"at least baseline and candidate are required")
        _req(tuple(sorted(set(self.candidate_ids))) == self.candidate_ids,"candidate_ids must be sorted and unique")
        for c in self.candidate_ids: _id("candidate_id",c)
        _sha("budget_digest",self.budget_digest)
        _req(tuple(sorted(set(self.checkpoint_receipt_digests))) == self.checkpoint_receipt_digests,"checkpoint digests must be sorted and unique")
        for d in self.checkpoint_receipt_digests: _sha("checkpoint_receipt_digest",d)
        _req(len(self.windows)>=3,"two future windows plus one OOD window are required")
        _req(sum(w.source_split=="future" for w in self.windows)>=2,"at least two independent future windows are required")
        _req(sum(w.source_split=="ood" for w in self.windows)>=1,"an independent OOD window is required")
        _req(len({w.window_id for w in self.windows})==len(self.windows),"window ids must be unique")
        _req(len({w.source_digest for w in self.windows})==len(self.windows),"source digests must be independent")
        _req(len({w.source_blob_digest for w in self.windows})==len(self.windows),"source blob digests must be independent")
        _req(type(self.current_run_mutation) is bool and not self.current_run_mutation,"current run is immutable")
        _req(type(self.next_snapshot_only) is bool and self.next_snapshot_only,"only next snapshot may change")
        _req(self.authority=="DENY_ALL" and self.status=="SHADOW_ONLY","matrix has no authority")
        expected={(c,w.window_id,a) for c in self.candidate_ids for w in self.windows for a in ARM_ORDER}
        actual={(r.candidate_id,r.window_id,r.arm) for r in self.receipts}
        _req(actual==expected,"matrix must contain exactly one receipt per candidate/window/arm")
        _req(len(actual)==len(self.receipts),"duplicate receipt key")
        _req(all(r.checkpoint_receipt_digest in self.checkpoint_receipt_digests for r in self.receipts),"unregistered checkpoint receipt")
        # Every candidate/window has the same exact budget dimensions; this
        # prevents hiding a cheaper arm behind fewer calls or tokens.
        for c in self.candidate_ids:
            for w in self.windows:
                rows=[r for r in self.receipts if r.candidate_id==c and r.window_id==w.window_id]
                first=(rows[0].calls,rows[0].input_tokens,rows[0].flops,rows[0].memory_bytes,rows[0].latency_ms)
                _req(all((r.calls,r.input_tokens,r.flops,r.memory_bytes,r.latency_ms)==first for r in rows),"arms do not share exact budget")
        all_budget={(r.calls,r.input_tokens,r.flops,r.memory_bytes,r.latency_ms) for r in self.receipts}
        _req(len(all_budget)==1,"candidate/window budgets are not equal")
    @property
    def eligible_for_next_snapshot(self): return self.gates.all_ok
    def to_dict(self): return {"schema":SCHEMA,**asdict(self),"windows":[w.to_dict() for w in self.windows],"receipts":[r.to_dict() for r in self.receipts],"gates":asdict(self.gates)}
    def require_next_snapshot_gate(self):
        _req(self.eligible_for_next_snapshot,"retention/calibration/OOD/fallback/rollback/deletion gate is not complete")
        return "ADVISORY_NEXT_SNAPSHOT_ONLY"

__all__=["ARM_ORDER","FutureOODMatrixError","FutureOODReaderMatrixV1","GateOutcomeV1","REAL_SHADOW","ReaderArmReceiptV1","WindowSourceV1","digest"]
