use super::*;
use codex_hepta_automation::TaskFlowError;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn stale_recovery_cannot_poison_original_attempt_after_reopen() {
    for recovery in [
        AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Succeeded,
            receipt_digest: Sha256Digest::for_bytes(b"stale-owner-success"),
            provider_ack: None,
        }),
        AuthorizedEffectRecovery::ProvenAbsent {
            proof_digest: Sha256Digest::for_bytes(b"stale-owner-absence"),
        },
    ] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let (authority, signed, _authority_dir) = final_use(expected.clone(), "owner-recovery");
        let mut driver =
            RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"original-unknown");
        let original = store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                AuthorizedEffectExecutionInput {
                    intent: &effect,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed,
                    expected_binding: &expected,
                    command_id: "authorized-effect-dispatch",
                    now_ms: 30,
                },
            )
            .await
            .expect("original unknown effect");
        assert_eq!(driver.calls, 1);
        let pending = store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("pending original attempt");
        let mut stale_owner = owner.clone();
        stale_owner.generation += 1;
        stale_owner.fencing_token = "different-owner-fence".to_string();

        assert!(matches!(
            store
                .recover_authorized_taskflow_effect(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &stale_owner,
                    recovery,
                    31,
                )
                .await,
            Err(AuthorizedEffectError::TaskFlow(TaskFlowError::StaleFence))
        ));
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen after rejected owner");
        assert_eq!(
            reopened
                .pending_authorized_taskflow_effects(8)
                .await
                .expect("original remains pending"),
            pending
        );
        assert_eq!(
            reopened
                .read_taskflow_step(&effect.run_id, &effect.step_id, effect.attempt, &owner)
                .await
                .expect("read original step"),
            Some(original)
        );

        // The original owner may observe a late provider ACK after lease expiry;
        // this repairs the old attempt and grants no authority to dispatch again.
        let recovered = reopened
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                    outcome: AuthorizedEffectOutcome::Succeeded,
                    receipt_digest: Sha256Digest::for_bytes(b"original-owner-success"),
                    provider_ack: None,
                }),
                2_000,
            )
            .await
            .expect("original owner terminal reconciliation");
        let AuthorizedEffectRecoveryResult::Observed(receipt) = recovered else {
            panic!("original provider observation must settle the original step");
        };
        assert_eq!(receipt.state, TaskFlowStepState::Reconciled);
        assert_eq!(
            receipt.final_outcome,
            Some(TaskFlowReconcileOutcome::Succeeded)
        );
        assert_eq!(driver.calls, 1);
        reopened.close().await;
    }
}
