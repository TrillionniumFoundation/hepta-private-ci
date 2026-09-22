"""Durable integration-queue reconciliation for the Engineering Control Plane.

The controller turns an orchestration merge-queue proposal into a durable,
revisioned observation state. It has no merge authority: candidate, review and CI
observations only move an item to ready_external_merge; an external merge system
must perform any merge. Base drift invalidates the whole queue generation and
requires an explicit new generation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .orchestration import EngineeringPlan

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_TERMINAL_STATES = frozenset({"terminal_merged", "terminal_failed"})
_STAGE_ISSUERS = {
    "candidate": "engineering_evidence_binder",
    "review": "github_review_observer",
    "ci": "ci_executor",
}
_MUTABLE_STATES = frozenset(
    {
        "awaiting_candidate_evidence",
        "awaiting_review",
        "awaiting_ci",
        "ready_external_merge",
    }
)


@dataclass(frozen=True)
class IntegrationStageReceipt:
    queue_generation_id: str
    package_id: str
    stage: str
    evidence_digest: str
    satisfied: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class IntegrationTerminalReceipt:
    queue_generation_id: str
    package_id: str
    candidate_digest: str
    review_digest: str
    ci_digest: str
    outcome: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class IntegrationQueueGeneration:
    queue_generation_id: str
    orchestration_generation_id: str
    base_commit: str
    base_tree: str
    semantic_digest: str
    state: str
    revision: int
    created_unix_ns: int
    updated_unix_ns: int


@dataclass(frozen=True)
class IntegrationQueueItem:
    queue_generation_id: str
    package_id: str
    position: int
    candidate_digest: str | None
    review_digest: str | None
    ci_digest: str | None
    state: str
    terminal_outcome: str | None
    reason: str | None
    revision: int
    updated_unix_ns: int


def _git_sha1(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA1.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise EngineeringError("invalid_" + label)
    return value


def _observation_digest(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    checked_sha256(value, label)
    if value == "0" * 64:
        raise EngineeringError("invalid_" + label)
    return value


def _generation(row) -> IntegrationQueueGeneration:
    return IntegrationQueueGeneration(
        str(row["queue_generation_id"]),
        str(row["orchestration_generation_id"]),
        str(row["base_commit"]),
        str(row["base_tree"]),
        str(row["semantic_digest"]),
        str(row["state"]),
        int(row["revision"]),
        int(row["created_unix_ns"]),
        int(row["updated_unix_ns"]),
    )


def _item(row) -> IntegrationQueueItem:
    return IntegrationQueueItem(
        str(row["queue_generation_id"]),
        str(row["package_id"]),
        int(row["position"]),
        None if row["candidate_digest"] is None else str(row["candidate_digest"]),
        None if row["review_digest"] is None else str(row["review_digest"]),
        None if row["ci_digest"] is None else str(row["ci_digest"]),
        str(row["state"]),
        None if row["terminal_outcome"] is None else str(row["terminal_outcome"]),
        None if row["reason"] is None else str(row["reason"]),
        int(row["revision"]),
        int(row["updated_unix_ns"]),
    )


def integration_queue_generation(
    store: EngineeringStore, queue_generation_id: str
) -> IntegrationQueueGeneration:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("invalid_engineering_store")
    checked_id(queue_generation_id, "queue_generation_id")
    row = store.connection.execute(
        "SELECT * FROM integration_queue_generations WHERE queue_generation_id=?",
        (queue_generation_id,),
    ).fetchone()
    if row is None:
        raise EngineeringError("integration_generation_unknown")
    return _generation(row)


def integration_queue_item(
    store: EngineeringStore,
    queue_generation_id: str,
    package_id: str,
) -> IntegrationQueueItem:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("invalid_engineering_store")
    checked_id(queue_generation_id, "queue_generation_id")
    checked_id(package_id, "package_id")
    row = store.connection.execute(
        "SELECT * FROM integration_queue_items "
        "WHERE queue_generation_id=? AND package_id=?",
        (queue_generation_id, package_id),
    ).fetchone()
    if row is None:
        raise EngineeringError("integration_item_unknown")
    return _item(row)


def publish_integration_queue(
    store: EngineeringStore,
    plan: EngineeringPlan,
    *,
    queue_generation_id: str,
    base_commit: str,
    base_tree: str,
    now_ns: int | None = None,
) -> IntegrationQueueGeneration:
    """Publish one immutable queue ordering from a persisted orchestration plan."""
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("invalid_engineering_store")
    if not isinstance(plan, EngineeringPlan):
        raise EngineeringError("invalid_engineering_plan")
    checked_id(queue_generation_id, "queue_generation_id")
    base_commit = _git_sha1(base_commit, "integration_base_commit")
    base_tree = _git_sha1(base_tree, "integration_base_tree")
    now = store._now(now_ns)

    persisted = store.connection.execute(
        "SELECT semantic_digest FROM orchestration_generations WHERE generation_id=?",
        (plan.generation_id,),
    ).fetchone()
    if persisted is None:
        raise EngineeringError("orchestration_generation_unknown")
    if str(persisted["semantic_digest"]) != plan.base_schedule_digest:
        raise EngineeringError("orchestration_generation_mismatch")

    assignment_ids = tuple(row.package_id for row in plan.assignments)
    queue_ids = tuple(row.package_id for row in plan.merge_queue)
    positions = tuple(row.position for row in plan.merge_queue)
    if (
        assignment_ids != plan.integration_order
        or queue_ids != plan.integration_order
        or positions != tuple(range(1, len(queue_ids) + 1))
        or any(
            row.state != "awaiting_candidate_evidence"
            or row.merge_authority
            or row.release_authority
            for row in plan.merge_queue
        )
    ):
        raise EngineeringError("integration_plan_invalid")

    record = {
        "queueGenerationId": queue_generation_id,
        "orchestrationGenerationId": plan.generation_id,
        "baseCommit": base_commit,
        "baseTree": base_tree,
        "items": [
            {"position": row.position, "packageId": row.package_id}
            for row in plan.merge_queue
        ],
    }
    digest = semantic_digest(record)

    with store._transaction():
        existing = store.connection.execute(
            "SELECT * FROM integration_queue_generations WHERE queue_generation_id=?",
            (queue_generation_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["semantic_digest"]) != digest:
                raise EngineeringError("integration_generation_identity_conflict")
            return _generation(existing)

        store.connection.execute(
            "INSERT INTO integration_queue_generations VALUES(?,?,?,?,?,?,?,?,?)",
            (
                queue_generation_id,
                plan.generation_id,
                base_commit,
                base_tree,
                digest,
                "active",
                1,
                now,
                now,
            ),
        )
        for row in plan.merge_queue:
            store.connection.execute(
                "INSERT INTO integration_queue_items VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    queue_generation_id,
                    row.package_id,
                    row.position,
                    None,
                    None,
                    None,
                    "awaiting_candidate_evidence",
                    None,
                    None,
                    1,
                    now,
                ),
            )
        store._append_audit(
            "integration_queue_published",
            {
                "queueGenerationId": queue_generation_id,
                "orchestrationGenerationId": plan.generation_id,
                "semanticDigest": digest,
                "baseCommit": base_commit,
                "baseTree": base_tree,
            },
            now,
        )
        current = store.connection.execute(
            "SELECT * FROM integration_queue_generations WHERE queue_generation_id=?",
            (queue_generation_id,),
        ).fetchone()
    return _generation(current)


def _invalidate_generation_for_base_drift(
    store: EngineeringStore,
    generation,
    current_base_commit: str,
    current_base_tree: str,
    now: int,
) -> None:
    if str(generation["state"]) == "requires_replan":
        return
    if str(generation["state"]) == "terminal":
        raise EngineeringError("integration_generation_terminal")
    store.connection.execute(
        "UPDATE integration_queue_items SET state='invalidated',"
        "reason='base_drift',revision=revision+1,updated_unix_ns=? "
        "WHERE queue_generation_id=? AND state NOT IN ('terminal_merged','terminal_failed')",
        (now, generation["queue_generation_id"]),
    )
    store.connection.execute(
        "UPDATE integration_queue_generations SET state='requires_replan',"
        "revision=revision+1,updated_unix_ns=? WHERE queue_generation_id=?",
        (now, generation["queue_generation_id"]),
    )
    store._append_audit(
        "integration_queue_invalidated",
        {
            "queueGenerationId": str(generation["queue_generation_id"]),
            "reason": "base_drift",
            "expectedBaseCommit": str(generation["base_commit"]),
            "expectedBaseTree": str(generation["base_tree"]),
            "currentBaseCommit": current_base_commit,
            "currentBaseTree": current_base_tree,
        },
        now,
    )


def observe_integration_stage(
    store: EngineeringStore,
    queue_generation_id: str,
    package_id: str,
    *,
    current_base_commit: str,
    current_base_tree: str,
    receipt: IntegrationStageReceipt,
    trust_store: SignatureTrustStore,
    now_ns: int | None = None,
) -> IntegrationQueueItem:
    """Verify one typed stage observation before mutating integration readiness."""
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("invalid_engineering_store")
    if not isinstance(receipt, IntegrationStageReceipt):
        raise EngineeringError("integration_stage_receipt_required")
    checked_id(queue_generation_id, "queue_generation_id")
    checked_id(package_id, "package_id")
    now = store._now(now_ns)
    if (
        receipt.queue_generation_id != queue_generation_id
        or receipt.package_id != package_id
        or receipt.stage not in _STAGE_ISSUERS
        or receipt.issuer != _STAGE_ISSUERS.get(receipt.stage)
        or receipt.satisfied is not True
    ):
        raise EngineeringError("integration_stage_receipt_binding")
    checked_sha256(receipt.evidence_digest, "integration_stage_evidence_digest")
    if receipt.evidence_digest == "0" * 64:
        raise EngineeringError("integration_stage_receipt_binding")
    if (
        not receipt.signing_identity
        or type(receipt.observed_unix_ns) is not int
        or type(receipt.expires_unix_ns) is not int
        or receipt.observed_unix_ns > now
        or receipt.expires_unix_ns <= receipt.observed_unix_ns
        or now >= receipt.expires_unix_ns
        or not trust_store.verify(
            receipt,
            receipt.issuer,
            receipt.signing_identity,
            receipt.signature,
        )
    ):
        raise EngineeringError("integration_stage_receipt_binding")
    observation_digest = semantic_digest(asdict(receipt))
    supplied = {
        "candidate": {"candidate_digest": observation_digest},
        "review": {"review_digest": observation_digest},
        "ci": {"ci_digest": observation_digest},
    }[receipt.stage]
    return reconcile_integration_item(
        store,
        queue_generation_id,
        package_id,
        current_base_commit=current_base_commit,
        current_base_tree=current_base_tree,
        trust_store=trust_store,
        now_ns=now,
        **supplied,
    )


def reconcile_integration_item(
    store: EngineeringStore,
    queue_generation_id: str,
    package_id: str,
    *,
    current_base_commit: str,
    current_base_tree: str,
    candidate_digest: str | None = None,
    review_digest: str | None = None,
    ci_digest: str | None = None,
    terminal_outcome: str | None = None,
    terminal_receipt: IntegrationTerminalReceipt | None = None,
    trust_store: SignatureTrustStore | None = None,
    now_ns: int | None = None,
) -> IntegrationQueueItem:
    """Advance one item from observed evidence without acquiring merge authority."""
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("invalid_engineering_store")
    checked_id(queue_generation_id, "queue_generation_id")
    checked_id(package_id, "package_id")
    current_base_commit = _git_sha1(current_base_commit, "integration_base_commit")
    current_base_tree = _git_sha1(current_base_tree, "integration_base_tree")
    candidate_digest = _observation_digest(candidate_digest, "candidate_digest")
    review_digest = _observation_digest(review_digest, "review_digest")
    ci_digest = _observation_digest(ci_digest, "ci_digest")
    if terminal_outcome not in {None, "merged_observed", "terminal_failure"}:
        raise EngineeringError("invalid_integration_terminal_outcome")
    if terminal_outcome is not None and terminal_receipt is None:
        raise EngineeringError("authenticated_terminal_receipt_required")
    if terminal_receipt is not None and not isinstance(terminal_receipt, IntegrationTerminalReceipt):
        raise EngineeringError("integration_terminal_receipt_required")
    if terminal_receipt is not None and terminal_receipt.outcome not in {"merged_observed", "terminal_failure"}:
        raise EngineeringError("invalid_integration_terminal_outcome")
    if (
        terminal_outcome is not None
        and terminal_receipt is not None
        and terminal_outcome != terminal_receipt.outcome
    ):
        raise EngineeringError("integration_terminal_receipt_binding")
    now = store._now(now_ns)

    with store._transaction():
        generation = store.connection.execute(
            "SELECT * FROM integration_queue_generations WHERE queue_generation_id=?",
            (queue_generation_id,),
        ).fetchone()
        if generation is None:
            raise EngineeringError("integration_generation_unknown")
        row = store.connection.execute(
            "SELECT * FROM integration_queue_items "
            "WHERE queue_generation_id=? AND package_id=?",
            (queue_generation_id, package_id),
        ).fetchone()
        if row is None:
            raise EngineeringError("integration_item_unknown")

        row_state = str(row["state"])
        if row_state in _TERMINAL_STATES:
            if terminal_receipt is None or trust_store is None:
                raise EngineeringError("authenticated_terminal_receipt_required")
            stored_terminal = None if row["terminal_outcome"] is None else str(row["terminal_outcome"])
            expected = {
                "candidate": None if row["candidate_digest"] is None else str(row["candidate_digest"]),
                "review": None if row["review_digest"] is None else str(row["review_digest"]),
                "ci": None if row["ci_digest"] is None else str(row["ci_digest"]),
            }
            if (
                terminal_receipt.queue_generation_id != queue_generation_id
                or terminal_receipt.package_id != package_id
                or terminal_receipt.outcome != stored_terminal
                or terminal_receipt.candidate_digest != expected["candidate"]
                or terminal_receipt.review_digest != expected["review"]
                or terminal_receipt.ci_digest != expected["ci"]
                or terminal_receipt.issuer != "integration_terminal_observer"
                or type(terminal_receipt.observed_unix_ns) is not int
                or type(terminal_receipt.expires_unix_ns) is not int
                or terminal_receipt.observed_unix_ns > now
                or now >= terminal_receipt.expires_unix_ns
                or not trust_store.verify(
                    terminal_receipt,
                    terminal_receipt.issuer,
                    terminal_receipt.signing_identity,
                    terminal_receipt.signature,
                )
            ):
                raise EngineeringError("integration_terminal_receipt_binding")
            return _item(row)

        if (
            str(generation["base_commit"]) != current_base_commit
            or str(generation["base_tree"]) != current_base_tree
        ):
            _invalidate_generation_for_base_drift(
                store, generation, current_base_commit, current_base_tree, now
            )
            current = store.connection.execute(
                "SELECT * FROM integration_queue_items "
                "WHERE queue_generation_id=? AND package_id=?",
                (queue_generation_id, package_id),
            ).fetchone()
            return _item(current)
        if str(generation["state"]) == "requires_replan":
            raise EngineeringError("integration_generation_requires_replan")
        if str(generation["state"]) == "terminal":
            raise EngineeringError("integration_generation_terminal")
        if row_state not in _MUTABLE_STATES:
            raise EngineeringError("integration_item_terminal")

        observed = {
            "candidate": None if row["candidate_digest"] is None else str(row["candidate_digest"]),
            "review": None if row["review_digest"] is None else str(row["review_digest"]),
            "ci": None if row["ci_digest"] is None else str(row["ci_digest"]),
        }
        supplied = {
            "candidate": candidate_digest,
            "review": review_digest,
            "ci": ci_digest,
        }
        effective_candidate = observed["candidate"] or supplied["candidate"]
        effective_review = observed["review"] or supplied["review"]
        if supplied["review"] is not None and effective_candidate is None:
            raise EngineeringError("integration_review_before_candidate")
        if supplied["ci"] is not None and (
            effective_candidate is None or effective_review is None
        ):
            raise EngineeringError("integration_ci_before_review")

        changed = False
        for kind in ("candidate", "review", "ci"):
            if (
                observed[kind] is not None
                and supplied[kind] is not None
                and observed[kind] != supplied[kind]
            ):
                revision = int(row["revision"]) + 1
                store.connection.execute(
                    "UPDATE integration_queue_items SET state='invalidated',"
                    "reason=?,revision=?,updated_unix_ns=? "
                    "WHERE queue_generation_id=? AND package_id=?",
                    (
                        kind + "_drift",
                        revision,
                        now,
                        queue_generation_id,
                        package_id,
                    ),
                )
                store.connection.execute(
                    "UPDATE integration_queue_generations SET state='requires_replan',"
                    "revision=revision+1,updated_unix_ns=? WHERE queue_generation_id=?",
                    (now, queue_generation_id),
                )
                store._append_audit(
                    "integration_item_invalidated",
                    {
                        "queueGenerationId": queue_generation_id,
                        "packageId": package_id,
                        "reason": kind + "_drift",
                    },
                    now,
                )
                invalid = store.connection.execute(
                    "SELECT * FROM integration_queue_items "
                    "WHERE queue_generation_id=? AND package_id=?",
                    (queue_generation_id, package_id),
                ).fetchone()
                return _item(invalid)
            if observed[kind] is None and supplied[kind] is not None:
                observed[kind] = supplied[kind]
                changed = True

        if not changed and terminal_receipt is None:
            return _item(row)

        if observed["candidate"] is None:
            state = "awaiting_candidate_evidence"
        elif observed["review"] is None:
            state = "awaiting_review"
        elif observed["ci"] is None:
            state = "awaiting_ci"
        else:
            state = "ready_external_merge"

        terminal_value = None
        terminal_receipt_digest = None
        reason = None
        if terminal_receipt is not None:
            if state != "ready_external_merge":
                raise EngineeringError("integration_terminal_before_ready")
            if trust_store is None:
                raise EngineeringError("authenticated_terminal_receipt_required")
            for value, label in (
                (terminal_receipt.candidate_digest, "terminal_candidate_digest"),
                (terminal_receipt.review_digest, "terminal_review_digest"),
                (terminal_receipt.ci_digest, "terminal_ci_digest"),
            ):
                checked_sha256(value, label)
                if value == "0" * 64:
                    raise EngineeringError("integration_terminal_receipt_binding")
            if (
                terminal_receipt.queue_generation_id != queue_generation_id
                or terminal_receipt.package_id != package_id
                or terminal_receipt.candidate_digest != observed["candidate"]
                or terminal_receipt.review_digest != observed["review"]
                or terminal_receipt.ci_digest != observed["ci"]
                or terminal_receipt.issuer != "integration_terminal_observer"
                or type(terminal_receipt.observed_unix_ns) is not int
                or type(terminal_receipt.expires_unix_ns) is not int
                or terminal_receipt.observed_unix_ns < int(row["updated_unix_ns"])
                or terminal_receipt.observed_unix_ns > now
                or now >= terminal_receipt.expires_unix_ns
                or not trust_store.verify(
                    terminal_receipt,
                    terminal_receipt.issuer,
                    terminal_receipt.signing_identity,
                    terminal_receipt.signature,
                )
            ):
                raise EngineeringError("integration_terminal_receipt_binding")
            terminal_value = terminal_receipt.outcome
            terminal_receipt_digest = semantic_digest(asdict(terminal_receipt))
            if terminal_value == "merged_observed":
                state = "terminal_merged"
            else:
                state = "terminal_failed"
                reason = "external_terminal_failure"

        revision = int(row["revision"]) + 1
        store.connection.execute(
            "UPDATE integration_queue_items SET candidate_digest=?,review_digest=?,"
            "ci_digest=?,state=?,terminal_outcome=?,reason=?,revision=?,updated_unix_ns=? "
            "WHERE queue_generation_id=? AND package_id=? AND revision=?",
            (
                observed["candidate"],
                observed["review"],
                observed["ci"],
                state,
                terminal_value,
                reason,
                revision,
                now,
                queue_generation_id,
                package_id,
                row["revision"],
            ),
        )
        remaining = int(
            store.connection.execute(
                "SELECT COUNT(*) FROM integration_queue_items "
                "WHERE queue_generation_id=? "
                "AND state NOT IN ('terminal_merged','terminal_failed')",
                (queue_generation_id,),
            ).fetchone()[0]
        )
        generation_state = "terminal" if remaining == 0 else "active"
        store.connection.execute(
            "UPDATE integration_queue_generations SET state=?,"
            "revision=revision+1,updated_unix_ns=? WHERE queue_generation_id=?",
            (generation_state, now, queue_generation_id),
        )
        store._append_audit(
            "integration_item_reconciled",
            {
                "queueGenerationId": queue_generation_id,
                "packageId": package_id,
                "state": state,
                "revision": revision,
                "candidateDigest": observed["candidate"],
                "reviewDigest": observed["review"],
                "ciDigest": observed["ci"],
                "terminalOutcome": terminal_value,
                "terminalReceiptDigest": terminal_receipt_digest,
                "terminalObserver": (
                    None if terminal_receipt is None else terminal_receipt.signing_identity
                ),
            },
            now,
        )
        updated = store.connection.execute(
            "SELECT * FROM integration_queue_items "
            "WHERE queue_generation_id=? AND package_id=?",
            (queue_generation_id, package_id),
        ).fetchone()
    return _item(updated)
