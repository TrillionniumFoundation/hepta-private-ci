//! Exercise the read-only receipt entry used by Agentd before dispatch replay.
use super::*;
use codex_hepta_automation::TaskFlowError;

#[tokio::test]
async fn terminal_receipts_reopen_with_complete_original_identity() {
    for outcome in [AuthorizedEffectOutcome::Succeeded, AuthorizedEffectOutcome::Failed] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let (authority, signed, _authority_dir) = final_use(expected.clone(), "receipt-reopen");
        let mut driver = RecordingDriver::receipt(outcome, b"original-terminal-evidence");
        let original = store.execute_authorized_taskflow_effect(
            &authority, &mut driver, &effect, EFFECT_PAYLOAD, &owner, &signed,
            &expected, "authorized-effect-dispatch", 30,
        ).await.expect("terminal dispatch");
        assert_eq!(driver.calls, 1);
        store.close().await;
        drop(store);
        drop(authority);
        drop(signed);
        let reopened = AutomationStore::open(&fixture.layout).await.expect("cold store open");
        for _ in 0..2 {
            let retained = reopened.read_authorized_taskflow_effect_receipt(
                &effect, "authorized-effect-dispatch",
            ).await.expect("read terminal receipt");
            assert_eq!(retained, Some(original.clone()));
        }
        assert_eq!(driver.calls, 1, "readback never calls the provider driver");
        reopened.close().await;
    }
}

#[tokio::test]
async fn reopened_terminal_receipt_rejects_changed_intent_and_command() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "receipt-binding");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"bound-receipt");
    let original = store.execute_authorized_taskflow_effect(
        &authority, &mut driver, &effect, EFFECT_PAYLOAD, &owner, &signed,
        &expected, "authorized-effect-dispatch", 30,
    ).await.expect("terminal dispatch");
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open(&fixture.layout).await.expect("cold store open");
    let mut changed = Vec::new();
    let mut intent = effect.clone();
    intent.operation_id.push_str("-changed");
    changed.push(intent);
    let mut intent = effect.clone();
    intent.payload_digest = Sha256Digest::for_bytes(b"changed payload");
    changed.push(intent);
    let mut intent = effect.clone();
    intent.destination_id.push_str("-changed");
    changed.push(intent);
    let mut intent = effect.clone();
    intent.subject_id.push_str("-changed");
    changed.push(intent);
    let mut intent = effect.clone();
    intent.final_use_scope_digest = Sha256Digest::for_bytes(b"changed scope");
    changed.push(intent);
    let mut intent = effect.clone();
    intent.policy_generation += 1;
    changed.push(intent);
    for intent in changed {
        assert!(matches!(
            reopened.read_authorized_taskflow_effect_receipt(
                &intent, "authorized-effect-dispatch",
            ).await,
            Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Conflict(_)))
        ));
    }
    assert!(matches!(
        reopened.read_authorized_taskflow_effect_receipt(&effect, "changed-command").await,
        Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Conflict(_)))
    ));
    assert_eq!(reopened.read_authorized_taskflow_effect_receipt(
        &effect, "authorized-effect-dispatch",
    ).await.expect("original still readable"), Some(original));
    assert_eq!(driver.calls, 1);
    reopened.close().await;
}

#[tokio::test]
async fn absent_and_indeterminate_receipts_do_not_claim_terminal_output() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    assert_eq!(store.read_authorized_taskflow_effect_receipt(
        &effect, "authorized-effect-dispatch",
    ).await.expect("no provider attempt yet"), None);
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "receipt-unknown");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"unknown");
    store.execute_authorized_taskflow_effect(
        &authority, &mut driver, &effect, EFFECT_PAYLOAD, &owner, &signed,
        &expected, "authorized-effect-dispatch", 30,
    ).await.expect("retain unresolved observation");
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open(&fixture.layout).await.expect("cold store open");
    assert_eq!(reopened.read_authorized_taskflow_effect_receipt(
        &effect, "authorized-effect-dispatch",
    ).await.expect("unknown remains unresolved"), None);
    assert_eq!(driver.calls, 1);
    assert_eq!(reopened.pending_authorized_taskflow_effects(8).await.expect("pending").len(), 1);
    reopened.close().await;
}
