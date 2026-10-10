use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use crate::COMPACT_PERSISTENCE_EXTERNAL_EFFECTS;
use crate::COMPACT_PERSISTENCE_KG_WRITE_AUTHORITY;
use crate::COMPACT_PERSISTENCE_NAMESPACE;
use crate::CompactCheckpoint;
use crate::CompactFence;
use crate::CompactLease;
use crate::CompactLossReport;
use crate::CompactParentSnapshot;
use crate::CompactPersistenceAppend;
use crate::CompactPersistenceError;
use crate::CompactPersistenceJournal;
use crate::CompactPersistenceState;
use crate::CompactProtectedRef;
use crate::CompactReconcileOutcome;
use crate::CompactSummaryReceipt;
use crate::checkpoint_digest;

fn fence() -> CompactFence {
    CompactFence::new(3, 8, 19, "fence:19").expect("fence")
}

fn snapshot() -> CompactParentSnapshot {
    CompactParentSnapshot::new(
        "ctx:local-development",
        20,
        30,
        7,
        Sha256Digest::for_bytes(b"parent-state"),
        fence(),
    )
    .expect("snapshot")
}

fn checkpoint() -> CompactCheckpoint {
    CompactCheckpoint::new(
        "ctxcp:local-development",
        CompactLease::from_snapshot(snapshot()),
        vec![CompactProtectedRef::new("approval:1", "approval", true).expect("ref")],
        CompactSummaryReceipt::new(
            Sha256Digest::for_bytes(b"summary"),
            Sha256Digest::for_bytes(b"model"),
            Sha256Digest::for_bytes(b"policy"),
        ),
        CompactLossReport::new(vec!["event:29".to_string()], 1, Vec::new(), 0).expect("loss"),
        0,
    )
    .expect("checkpoint")
}

#[test]
fn append_only_intent_is_cas_bound_and_idempotent() {
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    let cp = checkpoint();
    assert_eq!(
        journal.append_intent("op:1", &cp, &snapshot()),
        Ok(CompactPersistenceAppend::Appended { sequence: 1 })
    );
    assert_eq!(
        journal.append_intent("op:1", &cp, &snapshot()),
        Ok(CompactPersistenceAppend::Replay { sequence: 1 })
    );
    assert_eq!(journal.entries().len(), 1);
    assert_eq!(
        journal.commit_checkpoint("op:1", &checkpoint_digest(&cp).expect("digest")),
        Ok(CompactPersistenceAppend::Appended { sequence: 2 })
    );
    assert_eq!(
        journal.state("op:1"),
        Some(CompactPersistenceState::Committed)
    );
}

#[test]
fn rehydration_witness_is_append_only_idempotent_and_replayable() {
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    let cp = checkpoint();
    journal
        .append_intent("op:rehydrate", &cp, &snapshot())
        .expect("intent");
    let digest = checkpoint_digest(&cp).expect("digest");
    journal
        .commit_checkpoint("op:rehydrate", &digest)
        .expect("commit");
    assert_eq!(
        journal.record_rehydration("op:rehydrate", &digest, 0),
        Ok(CompactPersistenceAppend::Appended { sequence: 3 })
    );
    assert_eq!(
        journal.record_rehydration("op:rehydrate", &digest, 0),
        Ok(CompactPersistenceAppend::Replay { sequence: 3 })
    );
    assert_eq!(
        journal
            .rehydration("op:rehydrate")
            .expect("rehydration witness")
            .expected_revision,
        0
    );

    let mut reopened = CompactPersistenceJournal::reopen(journal.snapshot()).expect("reopen");
    assert_eq!(
        reopened.record_rehydration("op:rehydrate", &digest, 0),
        Ok(CompactPersistenceAppend::Replay { sequence: 3 })
    );
    assert!(matches!(
        reopened.record_rehydration("op:rehydrate", &Sha256Digest::for_bytes(b"changed"), 0),
        Err(CompactPersistenceError::CasConflict(_))
    ));
}

#[test]
fn rehydration_requires_committed_intent_and_exact_revision() {
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    let cp = checkpoint();
    let digest = checkpoint_digest(&cp).expect("digest");
    journal
        .append_intent("op:pending", &cp, &snapshot())
        .expect("intent");
    assert!(matches!(
        journal.record_rehydration("op:pending", &digest, 0),
        Err(CompactPersistenceError::IllegalTransition { .. })
    ));
    journal
        .commit_checkpoint("op:pending", &digest)
        .expect("commit");
    assert!(matches!(
        journal.record_rehydration("op:pending", &digest, 1),
        Err(CompactPersistenceError::CasConflict(_))
    ));
}

#[test]
fn stale_parent_and_fence_are_rejected_before_append() {
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    let cp = checkpoint();
    let mut changed = snapshot();
    changed.expected_parent_revision = 8;
    assert!(matches!(
        journal.append_intent("op:stale", &cp, &changed),
        Err(CompactPersistenceError::CasConflict(_))
    ));
    let mut next = snapshot();
    next.fence = CompactFence::new(3, 8, 20, "fence:20").expect("next fence");
    assert_eq!(
        journal.append_intent("op:fenced", &cp, &next),
        Err(CompactPersistenceError::StaleFence)
    );
    assert!(journal.entries().is_empty());
}

#[test]
fn indeterminate_reconcile_and_reopen_preserve_quarantine() {
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    let cp = checkpoint();
    journal
        .append_intent("op:unknown", &cp, &snapshot())
        .expect("intent");
    journal
        .mark_indeterminate("op:unknown", "lost-ack")
        .expect("quarantine");
    assert_eq!(
        journal.state("op:unknown"),
        Some(CompactPersistenceState::Indeterminate)
    );
    assert!(
        journal
            .commit_checkpoint("op:unknown", &checkpoint_digest(&cp).expect("digest"))
            .is_err()
    );
    let reopened = CompactPersistenceJournal::reopen(journal.snapshot()).expect("reopen");
    assert_eq!(
        reopened.state("op:unknown"),
        Some(CompactPersistenceState::Indeterminate)
    );
    let mut reconciled = reopened;
    reconciled
        .reconcile("op:unknown", CompactReconcileOutcome::Committed)
        .expect("reconcile");
    assert_eq!(
        reconciled.state("op:unknown"),
        Some(CompactPersistenceState::Committed)
    );
}

#[test]
fn reopen_rejects_tampered_hash_chain() {
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    journal
        .append_intent("op:tamper", &checkpoint(), &snapshot())
        .expect("intent");
    let mut snapshot = journal.snapshot();
    snapshot.entries[0].operation_id = "op:changed".to_string();
    assert!(matches!(
        CompactPersistenceJournal::reopen(snapshot),
        Err(CompactPersistenceError::Corrupt(_))
    ));
}

#[test]
fn contract_carries_negative_authority_flags() {
    assert_eq!(COMPACT_PERSISTENCE_NAMESPACE, "local_development_only");
    const {
        assert!(!COMPACT_PERSISTENCE_EXTERNAL_EFFECTS);
        assert!(!COMPACT_PERSISTENCE_KG_WRITE_AUTHORITY);
    }
}
