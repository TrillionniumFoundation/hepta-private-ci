"""Exact Git and role-separated evidence verification for Lane G."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
from pathlib import Path
import re
import subprocess
import time
from collections.abc import Mapping

from .control_plane import (
    EngineeringError,
    canonical_json,
    checked_id,
    checked_sha256,
    semantic_digest,
)

SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CanonicalSourceReceipt:
    repository_full_name: str
    source_commit: str
    source_tree: str
    document_set_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class ExecutionReceipt:
    receipt_id: str
    class_name: str
    commit: str
    tree: str
    ordered_parents: tuple[str, ...]
    checks_digest: str
    passed: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class EvaluatorIndependenceReceipt:
    generator_principal: str
    generator_signing_identity: str
    evaluator_principal: str
    evaluator_signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkCompletionReceipt:
    package_id: str
    generation_id: str
    source_commit: str
    source_tree: str
    checks_digest: str
    status: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""
    authority_delta: bool = False


@dataclass(frozen=True)
class EvidenceDecision:
    eligible_for_independent_review: bool
    reasons: tuple[str, ...]
    evidence_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


class HmacTrustStore:
    """Reference verifier; production composition injects an HSM-backed port."""

    def __init__(self, keys: Mapping[tuple[str, str], bytes]):
        self._keys = dict(keys)

    @staticmethod
    def payload(value: object) -> bytes:
        row = asdict(value) if hasattr(value, "__dataclass_fields__") else value
        if isinstance(row, dict):
            row = dict(row)
            row.pop("signature", None)
        return canonical_json(row)

    def sign(self, value: object, issuer: str, signing_identity: str) -> str:
        key = self._keys[(issuer, signing_identity)]
        return hmac.new(key, self.payload(value), hashlib.sha256).hexdigest()

    def verify(
        self,
        value: object,
        issuer: str,
        signing_identity: str,
        signature: str,
    ) -> bool:
        key = self._keys.get((issuer, signing_identity))
        if (
            key is None
            or not isinstance(signature, str)
            or SHA256.fullmatch(signature) is None
        ):
            return False
        expected = hmac.new(key, self.payload(value), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def _run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EngineeringError("git_read_failed") from None
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 1_048_576:
        raise EngineeringError("git_read_failed")
    return result.stdout.strip()


def _git_identity(root: Path, commit: str) -> tuple[str, tuple[str, ...]]:
    if (
        not isinstance(commit, str)
        or SHA1.fullmatch(commit) is None
        or commit == "0" * 40
    ):
        raise EngineeringError("invalid_git_identity")
    if _run_git(root, "rev-parse", "--verify", f"{commit}^{{commit}}") != commit:
        raise EngineeringError("invalid_git_identity")
    tree = _run_git(root, "rev-parse", f"{commit}^{{tree}}")
    parents = tuple(_run_git(root, "show", "-s", "--format=%P", commit).split())
    return tree, parents


def _normal_remote(value: str) -> str:
    value = value.strip().removesuffix(".git").removesuffix("/")
    if value.startswith("git@github.com:"):
        return value.removeprefix("git@github.com:")
    for prefix in ("https://github.com/", "http://github.com/"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return value


def _valid_window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and observed <= now < expires
        and expires > observed
    )


def verify_canonical_source_receipt(
    root: str | Path,
    expected_repository: str,
    source: CanonicalSourceReceipt,
    trust_store: HmacTrustStore,
    *,
    expected_document_set_digest: str,
    now_ns: int | None = None,
) -> CanonicalSourceReceipt:
    """Authenticate the exact source identity before a work envelope is issued."""
    now = time.time_ns() if now_ns is None else now_ns
    if not isinstance(source, CanonicalSourceReceipt):
        raise EngineeringError("invalid_source_receipt")
    if source.repository_full_name != expected_repository:
        raise EngineeringError("repository_mismatch")
    if source.issuer != "source_authority":
        raise EngineeringError("source_issuer_role")
    checked_sha256(source.document_set_digest, "document_set_digest")
    checked_sha256(expected_document_set_digest, "document_set_digest")
    if source.document_set_digest != expected_document_set_digest:
        raise EngineeringError("document_set_drift")
    if not _valid_window(source.observed_unix_ns, source.expires_unix_ns, now):
        raise EngineeringError("source_receipt_stale")
    if not trust_store.verify(
        source, source.issuer, source.signing_identity, source.signature
    ):
        raise EngineeringError("source_receipt_signature")
    repository = Path(root).resolve()
    remote = _normal_remote(_run_git(repository, "config", "--get", "remote.origin.url"))
    if remote != expected_repository:
        raise EngineeringError("repository_remote_mismatch")
    tree, _parents = _git_identity(repository, source.source_commit)
    if tree != source.source_tree:
        raise EngineeringError("source_tree_mismatch")
    return source


def verify_work_completion_receipts(
    receipts: tuple[WorkCompletionReceipt, ...] | list[WorkCompletionReceipt],
    trust_store: HmacTrustStore,
    *,
    generation_id: str | None,
    source_commit: str,
    source_tree: str,
    now_ns: int | None = None,
) -> frozenset[str]:
    """Return authenticated completed package ids for one exact source generation."""
    now = time.time_ns() if now_ns is None else now_ns
    if generation_id is not None:
        checked_id(generation_id, "generation_id")
    if SHA1.fullmatch(source_commit) is None or SHA1.fullmatch(source_tree) is None:
        raise EngineeringError("invalid_git_identity")
    if len(receipts) > 4096:
        raise EngineeringError("completed_limit_exceeded")
    completed: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, WorkCompletionReceipt):
            raise EngineeringError("invalid_completion_receipt")
        checked_id(receipt.package_id, "package_id")
        checked_id(receipt.generation_id, "generation_id")
        checked_sha256(receipt.checks_digest, "checks_digest")
        if receipt.status != "completed":
            raise EngineeringError("completion_not_terminal")
        if generation_id is not None and receipt.generation_id != generation_id:
            raise EngineeringError("completion_generation_mismatch")
        if receipt.source_commit != source_commit or receipt.source_tree != source_tree:
            raise EngineeringError("completion_source_mismatch")
        if receipt.authority_delta is not False:
            raise EngineeringError("completion_authority_delta")
        if receipt.issuer not in {"ci_executor", "independent_evaluator"}:
            raise EngineeringError("completion_issuer_role")
        if not _valid_window(
            receipt.observed_unix_ns, receipt.expires_unix_ns, now
        ):
            raise EngineeringError("completion_receipt_stale")
        if not trust_store.verify(
            receipt, receipt.issuer, receipt.signing_identity, receipt.signature
        ):
            raise EngineeringError("completion_receipt_signature")
        if receipt.package_id in completed:
            raise EngineeringError("duplicate_completion_receipt")
        completed.add(receipt.package_id)
    return frozenset(completed)


def verify_integration_evidence(
    root: str | Path,
    expected_repository: str,
    source: CanonicalSourceReceipt,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    independence: EvaluatorIndependenceReceipt,
    trust_store: HmacTrustStore,
    *,
    expected_document_set_digest: str,
    now_ns: int | None = None,
) -> EvidenceDecision:
    """Verify real Git objects and authenticated receipts.

    Success means only that the candidate may be handed to an independent
    reviewer. It is never acceptance, selection, merge, activation, promotion,
    release, or runtime authority.
    """
    now = time.time_ns() if now_ns is None else now_ns
    reasons: list[str] = []
    repository = Path(root).resolve()
    if source.repository_full_name != expected_repository:
        reasons.append("repository_mismatch")
    try:
        remote = _normal_remote(
            _run_git(repository, "config", "--get", "remote.origin.url")
        )
        if remote and remote != expected_repository:
            reasons.append("repository_remote_mismatch")
    except EngineeringError:
        reasons.append("repository_remote_unavailable")
    try:
        checked_sha256(source.document_set_digest, "invalid_document_set_digest")
        checked_sha256(expected_document_set_digest, "invalid_document_set_digest")
        checked_sha256(source_execution.checks_digest, "invalid_source_checks_digest")
        checked_sha256(merge_execution.checks_digest, "invalid_merge_checks_digest")
    except EngineeringError as error:
        reasons.append(error.code)
    if source.document_set_digest != expected_document_set_digest:
        reasons.append("document_set_drift")
    if source.issuer != "source_authority":
        reasons.append("source_issuer_role")
    if source_execution.issuer != "ci_executor":
        reasons.append("source_execution_issuer_role")
    if merge_execution.issuer != "ci_executor":
        reasons.append("merge_execution_issuer_role")
    signed_values = (
        (source, source.issuer, source.signing_identity, "source_receipt_signature"),
        (
            source_execution,
            source_execution.issuer,
            source_execution.signing_identity,
            "source_execution_signature",
        ),
        (
            merge_execution,
            merge_execution.issuer,
            merge_execution.signing_identity,
            "merge_execution_signature",
        ),
        (
            independence,
            independence.evaluator_principal,
            independence.evaluator_signing_identity,
            "independence_signature",
        ),
    )
    for value, issuer, signing_identity, label in signed_values:
        if not trust_store.verify(value, issuer, signing_identity, value.signature):
            reasons.append(label)
    for value, label in (
        (source, "source_receipt_stale"),
        (source_execution, "source_execution_stale"),
        (merge_execution, "merge_execution_stale"),
        (independence, "independence_receipt_stale"),
    ):
        if not _valid_window(value.observed_unix_ns, value.expires_unix_ns, now):
            reasons.append(label)
    if (
        independence.generator_principal == independence.evaluator_principal
        or independence.generator_signing_identity
        == independence.evaluator_signing_identity
    ):
        reasons.append("evaluator_identity_collision")
    try:
        source_tree, _source_parents = _git_identity(repository, source.source_commit)
        exact_tree, exact_parents = _git_identity(repository, source_execution.commit)
        merge_tree, merge_parents = _git_identity(repository, merge_execution.commit)
    except EngineeringError as error:
        reasons.append(error.code)
        source_tree = exact_tree = merge_tree = ""
        exact_parents = merge_parents = ()
    if source_tree != source.source_tree:
        reasons.append("source_tree_mismatch")
    if source_execution.class_name != "exact_source":
        reasons.append("source_execution_class")
    if merge_execution.class_name != "synthetic_merge":
        reasons.append("merge_execution_class")
    if (
        source_execution.commit != source.source_commit
        or exact_tree != source.source_tree
    ):
        reasons.append("exact_source_mismatch")
    if (
        source_execution.tree != exact_tree
        or source_execution.ordered_parents != exact_parents
    ):
        reasons.append("source_execution_identity_mismatch")
    if (
        merge_execution.tree != merge_tree
        or merge_execution.ordered_parents != merge_parents
    ):
        reasons.append("merge_execution_identity_mismatch")
    if len(merge_parents) != 2 or merge_parents[1] != source.source_commit:
        reasons.append("merge_parent_order_mismatch")
    if merge_execution.commit in {source.source_commit, *merge_parents}:
        reasons.append("synthetic_merge_not_distinct")
    if source_execution.passed is not True:
        reasons.append("source_execution_failed")
    if merge_execution.passed is not True:
        reasons.append("merge_execution_failed")
    evidence = {
        "source": asdict(source),
        "sourceExecution": asdict(source_execution),
        "mergeExecution": asdict(merge_execution),
        "independence": asdict(independence),
        "expectedDocumentSetDigest": expected_document_set_digest,
    }
    unique = tuple(sorted(set(reasons)))
    return EvidenceDecision(not unique, unique, semantic_digest(evidence))
