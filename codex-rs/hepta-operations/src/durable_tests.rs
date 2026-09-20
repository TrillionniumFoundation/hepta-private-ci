use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::DurableOperationLedger;
use crate::OperationError;
use crate::OperationKey;
use crate::OperationState;
use crate::ReconciliationOutcome;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn digest(label: &[u8]) -> Digest32 {
    Digest32::of_bytes(label)
}

fn key(payload: &[u8]) -> OperationKey {
    OperationKey {
        id: stable_id("operation:ui:1"),
        payload_digest: digest(payload),
    }
}

#[tokio::test]
async fn reopen_preserves_indeterminate_and_terminal_history() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let owner_generation = generation(7);

    let ledger = DurableOperationLedger::open(&path).await.expect("open");
    let begun = ledger
        .begin(key(b"payload-v1"), owner_generation)
        .await
        .expect("begin");
    assert_eq!(begun.operation.revision.get(), 1);
    assert!(matches!(begun.operation.state, OperationState::Pending));

    let repeated = ledger
        .begin(key(b"payload-v1"), owner_generation)
        .await
        .expect("idempotent begin");
    assert_eq!(repeated.operation.revision.get(), 1);

    let conflict = ledger
        .begin(key(b"payload-v2"), owner_generation)
        .await
        .expect_err("changed semantics must conflict");
    assert!(matches!(conflict, OperationError::Conflict(_)));

    let authority = digest(b"authority-admission");
    let authorized = ledger
        .record_authority_evidence(
            &stable_id("operation:ui:1"),
            authority,
            generation(11),
        )
        .await
        .expect("record authority evidence");
    assert_eq!(authorized.operation.revision.get(), 2);
    assert_eq!(authorized.authority_evidence_digest, Some(authority));

    let dispatch = digest(b"dispatch");
    let dispatched = ledger
        .record_dispatch(&stable_id("operation:ui:1"), dispatch)
        .await
        .expect("dispatch");
    assert_eq!(dispatched.operation.revision.get(), 3);
    assert!(!dispatched.operation.state.is_terminal());
    assert_eq!(dispatched.dispatch_digest, Some(dispatch));

    ledger.close().await;

    let reopened = DurableOperationLedger::open(&path).await.expect("reopen");
    let after_reopen = reopened
        .get(&stable_id("operation:ui:1"))
        .await
        .expect("read")
        .expect("record");
    assert!(matches!(
        after_reopen.operation.state,
        OperationState::Dispatched { .. }
    ));
    assert_eq!(after_reopen.authority_evidence_digest, Some(authority));
    assert_eq!(after_reopen.dispatch_digest, Some(dispatch));

    let reason = digest(b"response-lost-after-dispatch");
    let indeterminate = reopened
        .mark_indeterminate(&stable_id("operation:ui:1"), reason)
        .await
        .expect("indeterminate");
    assert_eq!(indeterminate.operation.revision.get(), 4);
    assert!(!indeterminate.operation.state.is_terminal());

    reopened.close().await;

    let recovered = DurableOperationLedger::open(&path).await.expect("reopen indeterminate");
    let retained = recovered
        .get(&stable_id("operation:ui:1"))
        .await
        .expect("read retained")
        .expect("retained record");
    assert!(matches!(
        retained.operation.state,
        OperationState::Indeterminate { .. }
    ));
    assert_eq!(retained.indeterminate_reason_digest, Some(reason));

    let stale = recovered
        .observe_terminal(
            &stable_id("operation:ui:1"),
            ReconciliationOutcome::Applied,
            digest(b"terminal-applied"),
            generation(8),
        )
        .await
        .expect_err("stale observer must reject");
    assert_eq!(stale, OperationError::StaleGeneration);

    let terminal_digest = digest(b"terminal-applied");
    let terminal = recovered
        .observe_terminal(
            &stable_id("operation:ui:1"),
            ReconciliationOutcome::Applied,
            terminal_digest,
            owner_generation,
        )
        .await
        .expect("terminal observation");
    assert_eq!(terminal.operation.revision.get(), 5);
    assert!(terminal.operation.state.is_terminal());
    assert_eq!(terminal.terminal_evidence_digest, Some(terminal_digest));

    recovered.close().await;

    let final_reopen = DurableOperationLedger::open(&path).await.expect("final reopen");
    let final_record = final_reopen
        .get(&stable_id("operation:ui:1"))
        .await
        .expect("read terminal")
        .expect("terminal record");
    assert!(matches!(
        final_record.operation.state,
        OperationState::Applied { .. }
    ));
    assert_eq!(final_record.terminal_evidence_digest, Some(terminal_digest));

    let idempotent_terminal = final_reopen
        .observe_terminal(
            &stable_id("operation:ui:1"),
            ReconciliationOutcome::Applied,
            terminal_digest,
            owner_generation,
        )
        .await
        .expect("same terminal evidence is idempotent");
    assert_eq!(idempotent_terminal.operation.revision.get(), 5);

    let conflicting_terminal = final_reopen
        .observe_terminal(
            &stable_id("operation:ui:1"),
            ReconciliationOutcome::NotApplied,
            digest(b"different-terminal"),
            owner_generation,
        )
        .await
        .expect_err("terminal state cannot be rewritten");
    assert_eq!(conflicting_terminal, OperationError::Terminal);
}

#[tokio::test]
async fn dispatch_acknowledgement_never_becomes_terminal_by_itself() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let ledger = DurableOperationLedger::open(&path).await.expect("open");
    let operation_id = stable_id("operation:ui:1");

    ledger
        .begin(key(b"payload-v1"), generation(2))
        .await
        .expect("begin");
    ledger
        .record_authority_evidence(&operation_id, digest(b"authority"), generation(4))
        .await
        .expect("authority evidence");
    let dispatched = ledger
        .record_dispatch(&operation_id, digest(b"queue-ack"))
        .await
        .expect("dispatch acknowledgement");

    assert!(matches!(
        dispatched.operation.state,
        OperationState::Dispatched { .. }
    ));
    assert!(!dispatched.operation.state.is_terminal());

    ledger.close().await;
    let reopened = DurableOperationLedger::open(&path).await.expect("reopen");
    let record = reopened
        .get(&operation_id)
        .await
        .expect("query")
        .expect("record");
    assert!(matches!(
        record.operation.state,
        OperationState::Dispatched { .. }
    ));
    assert!(!record.operation.state.is_terminal());
}
