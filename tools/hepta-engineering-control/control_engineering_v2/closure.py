"""Final repository-owned closure for Lane G authority-adjacent composition.

This layer is installed after :mod:`hardening`.  It closes the remaining
persistence and freshness gaps without adding acceptance, merge, activation,
promotion, release, deployment, peer-enrollment, credential-propagation, or
runtime authority.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict
import json
import time
from pathlib import Path
from typing import Any

from . import assimilation as _assimilation
from . import control_plane as _control
from . import facade as _facade
from . import hardening as _hardening
from .candidate import Candidate, SandboxReceipt
from .evidence import EvidenceDecision, ExecutionReceipt, HmacTrustStore

_FINAL_SCHEMA_VERSION = 4

# The hardened initializer reads this module global at call time.  Bumping it
# before capturing the installed initializer makes schema-v4 stores reopenable;
# the final table creation below remains idempotent if a process died between
# the metadata update and the DDL statement.
_hardening._STORE_SCHEMA_VERSION = _FINAL_SCHEMA_VERSION
_BASE_STORE_INIT = _control.EngineeringStore.__init__
_BASE_BIND_CANDIDATE_EVIDENCE = _hardening.bind_candidate_evidence
_BASE_PREPARE_ASSIMILATION = _hardening.hardened_prepare_assimilation_candidate
_BASE_RECORD_DECISION = _hardening._ORIGINAL_RECORD_DECISION


def _decode_paths_json(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value
    elif isinstance(value, (bytes, bytearray, memoryview)):
        try:
            text = bytes(value).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise _control.EngineeringError("invalid_lease_paths_encoding") from None
    else:
        raise _control.EngineeringError("invalid_lease_paths_encoding")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        raise _control.EngineeringError("invalid_lease_paths_encoding") from None
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise _control.EngineeringError("invalid_lease_paths_encoding")
    return tuple(decoded)


def _final_lease_frontier(
    store: _control.EngineeringStore,
    envelope: Any,
    now_ns: int,
) -> str:
    rows = store.connection.execute(
        "SELECT lease_id,envelope_id,holder,paths_json,state,authority_epoch,"
        "fencing_token,revision,issued_unix_ns,expires_unix_ns,semantic_digest "
        "FROM path_leases WHERE state='active' AND expires_unix_ns>? "
        "ORDER BY fencing_token,lease_id",
        (now_ns,),
    ).fetchall()
    leases: list[dict[str, object]] = []
    for row in rows:
        leases.append(
            {
                "leaseId": str(row["lease_id"]),
                "envelopeId": str(row["envelope_id"]),
                "holder": str(row["holder"]),
                "paths": _decode_paths_json(row["paths_json"]),
                "state": str(row["state"]),
                "authorityEpoch": int(row["authority_epoch"]),
                "fencingToken": int(row["fencing_token"]),
                "revision": int(row["revision"]),
                "issuedUnixNs": int(row["issued_unix_ns"]),
                "expiresUnixNs": int(row["expires_unix_ns"]),
                "semanticDigest": str(row["semantic_digest"]),
            }
        )
    return _control.semantic_digest(
        {
            "envelopeId": str(envelope["envelope_id"]),
            "envelopeSemanticDigest": str(envelope["semantic_digest"]),
            "envelopeRevision": int(envelope["revision"]),
            "sourceCommit": str(envelope["source_commit"]),
            "sourceTree": str(envelope["source_tree"]),
            "activeLeases": leases,
        }
    )


def _install_final_schema(store: _control.EngineeringStore) -> None:
    row = store.connection.execute(
        "SELECT schema_version FROM engineering_schema_meta WHERE singleton=1"
    ).fetchone()
    if row is not None and int(row[0]) > _FINAL_SCHEMA_VERSION:
        raise _control.EngineeringError("unsupported_future_store_schema")
    store.connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS integration_decision_bindings(
          decision_id TEXT PRIMARY KEY,
          candidate_id TEXT NOT NULL,
          candidate_digest TEXT NOT NULL,
          sandbox_receipt_digest TEXT NOT NULL,
          binding_receipt_digest TEXT NOT NULL,
          bound_evidence_digest TEXT NOT NULL,
          recorded_unix_ns INTEGER NOT NULL,
          semantic_digest TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_integration_decision_bindings_candidate
          ON integration_decision_bindings(candidate_id);
        """
    )
    now = time.time_ns()
    store.connection.execute(
        "UPDATE engineering_schema_meta SET schema_version=?,updated_unix_ns=? "
        "WHERE singleton=1",
        (_FINAL_SCHEMA_VERSION, now),
    )
    store.connection.execute(f"PRAGMA user_version={_FINAL_SCHEMA_VERSION}")
    store.connection.commit()


def _final_store_init(
    self: _control.EngineeringStore,
    database: str | Path,
    *args: Any,
    **kwargs: Any,
) -> None:
    _BASE_STORE_INIT(self, database, *args, **kwargs)
    try:
        _install_final_schema(self)
    except BaseException:
        self.connection.close()
        raise


def bind_candidate_evidence(
    candidate: Candidate,
    sandbox: SandboxReceipt,
    evidence: EvidenceDecision,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    binding: _hardening.CandidateEvidenceBindingReceipt,
    trust_store: HmacTrustStore,
    *,
    now_ns: int | None = None,
) -> _hardening.BoundEvidenceDecision:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    if (
        source_execution.tree != sandbox.source_tree_before
        or source_execution.tree != sandbox.source_tree_after
    ):
        raise _control.EngineeringError("source_execution_tree_mismatch")
    lower_bound = max(source_execution.observed_unix_ns, merge_execution.observed_unix_ns)
    upper_bound = min(source_execution.expires_unix_ns, merge_execution.expires_unix_ns)
    if binding.observed_unix_ns < lower_bound or binding.expires_unix_ns > upper_bound:
        raise _control.EngineeringError("candidate_binding_window_escape")
    return _BASE_BIND_CANDIDATE_EVIDENCE(
        candidate,
        sandbox,
        evidence,
        source_execution,
        merge_execution,
        binding,
        trust_store,
        now_ns=now,
    )


def prepare_assimilation_candidate(
    consent: _assimilation.OwnerConsentReceipt,
    observations: Mapping[str, str],
    omissions: Iterable[str],
    sandbox_factory: Any,
    *,
    trust_store: HmacTrustStore,
    consent_attestation: _hardening.OwnerConsentAttestation,
    now_ns: int | None = None,
) -> _assimilation.AssimilationProposal:
    if (
        consent_attestation.observed_unix_ns < consent.observed_unix_ns
        or consent_attestation.expires_unix_ns > consent.expires_unix_ns
    ):
        raise _control.EngineeringError("consent_attestation_window_escape")
    return _BASE_PREPARE_ASSIMILATION(
        consent,
        observations,
        omissions,
        sandbox_factory,
        trust_store=trust_store,
        consent_attestation=consent_attestation,
        now_ns=now_ns,
    )


def record_integration_decision(
    store: _control.EngineeringStore,
    decision_id: str,
    evidence: EvidenceDecision | _hardening.BoundEvidenceDecision,
    *,
    now_ns: int | None = None,
) -> None:
    now = store._now(now_ns)
    if evidence.eligible_for_independent_review is not True:
        _hardening._run_immediate(
            store,
            lambda: _BASE_RECORD_DECISION(
                store,
                decision_id,
                evidence.evidence_digest,
                False,
                evidence.reasons,
                now_ns=now,
            ),
        )
        return
    if not isinstance(evidence, _hardening.BoundEvidenceDecision):
        raise _control.EngineeringError("candidate_binding_required")
    if evidence.candidate_bound is not True or evidence.reasons:
        raise _control.EngineeringError("candidate_binding_required")

    binding_payload = {
        "decisionId": decision_id,
        "candidateId": evidence.candidate_id,
        "candidateDigest": evidence.candidate_digest,
        "sandboxReceiptDigest": evidence.sandbox_receipt_digest,
        "bindingReceiptDigest": evidence.binding_receipt_digest,
        "boundEvidenceDigest": evidence.evidence_digest,
        "recordedUnixNs": now,
    }
    binding_semantic_digest = _control.semantic_digest(binding_payload)

    def operation() -> None:
        existing = store.connection.execute(
            "SELECT candidate_id,candidate_digest,sandbox_receipt_digest,"
            "binding_receipt_digest,bound_evidence_digest,semantic_digest "
            "FROM integration_decision_bindings WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        expected = (
            evidence.candidate_id,
            evidence.candidate_digest,
            evidence.sandbox_receipt_digest,
            evidence.binding_receipt_digest,
            evidence.evidence_digest,
            binding_semantic_digest,
        )
        if existing is None:
            store.connection.execute(
                "INSERT INTO integration_decision_bindings("
                "decision_id,candidate_id,candidate_digest,sandbox_receipt_digest,"
                "binding_receipt_digest,bound_evidence_digest,recorded_unix_ns,"
                "semantic_digest) VALUES(?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    evidence.candidate_id,
                    evidence.candidate_digest,
                    evidence.sandbox_receipt_digest,
                    evidence.binding_receipt_digest,
                    evidence.evidence_digest,
                    now,
                    binding_semantic_digest,
                ),
            )
        else:
            actual = tuple(str(existing[index]) for index in range(6))
            if actual != expected:
                raise _control.EngineeringError("decision_binding_conflict")
        _BASE_RECORD_DECISION(
            store,
            decision_id,
            evidence.evidence_digest,
            True,
            evidence.reasons,
            now_ns=now,
        )

    _hardening._run_immediate(store, operation)


def integration_decision_binding(
    store: _control.EngineeringStore,
    decision_id: str,
) -> Mapping[str, object]:
    _control.checked_id(decision_id, "decision_id")
    row = store.connection.execute(
        "SELECT * FROM integration_decision_bindings WHERE decision_id=?",
        (decision_id,),
    ).fetchone()
    if row is None:
        raise _control.EngineeringError("unknown_integration_decision_binding")
    return {
        "decisionId": str(row["decision_id"]),
        "candidateId": str(row["candidate_id"]),
        "candidateDigest": str(row["candidate_digest"]),
        "sandboxReceiptDigest": str(row["sandbox_receipt_digest"]),
        "bindingReceiptDigest": str(row["binding_receipt_digest"]),
        "boundEvidenceDigest": str(row["bound_evidence_digest"]),
        "recordedUnixNs": int(row["recorded_unix_ns"]),
        "semanticDigest": str(row["semantic_digest"]),
    }


def install_closure() -> None:
    if getattr(_control.EngineeringStore, "_lane_g_closure_installed", False):
        return
    _control.EngineeringStore.__init__ = _final_store_init  # type: ignore[method-assign]
    _control.EngineeringStore.integration_decision_binding = integration_decision_binding  # type: ignore[attr-defined]
    _hardening._lease_frontier = _final_lease_frontier
    _hardening.bind_candidate_evidence = bind_candidate_evidence
    _hardening.hardened_record_integration_decision = record_integration_decision
    _hardening.hardened_prepare_assimilation_candidate = prepare_assimilation_candidate
    _facade.record_integration_decision = record_integration_decision
    _facade.prepare_assimilation_candidate = prepare_assimilation_candidate
    _control.EngineeringStore._lane_g_closure_installed = True  # type: ignore[attr-defined]
