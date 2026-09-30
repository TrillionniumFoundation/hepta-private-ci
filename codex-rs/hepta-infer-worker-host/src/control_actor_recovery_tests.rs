use super::*;

use codex_hepta_infer_core::control_contracts::ControlSignature;
use codex_hepta_infer_core::control_contracts::ReconciledTerminalStatus;
use codex_hepta_infer_core::control_contracts::TrustKey;
use codex_hepta_infer_core::control_contracts::TrustRole;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_infer_core::recovery_contracts::RecoveryReconciliationReceipt;
use codex_hepta_infer_core::recovery_contracts::SignedRecoveryReconciliationReceipt;
use codex_hepta_infer_core::recovery_contracts::verify_execution_plan_for_recovery;
use codex_hepta_infer_core::recovery_contracts::verify_recovery_reconciliation_receipt;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

use super::signed_fixture as signed;

#[tokio::test]
async fn writer_rejects_cached_terminal_capability_expired_after_verification() {
    let paths = tempfile::tempdir().unwrap();
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap();
    let (mut trust_keys, bundle) = signed::execution_authority("expired-proof", now);
    let key = SigningKey::from_bytes(&[5; 32]);
    trust_keys.push(TrustKey {
        key_id: "reconciliation-key".to_string(),
        signer_id: "provider-reconciler".to_string(),
        role: TrustRole::ReconciliationIssuer,
        verifying_key: key.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 9,
        revoked_at_authority_epoch: None,
    });
    let recovery_plan = Arc::new(verify_execution_plan_for_recovery(&trust_keys, &bundle).unwrap());
    let plan = Arc::new(signed::plan("expired-proof", now));
    let actor =
        NativeJournalWriterActor::spawn(paths.path().join("control.journal"), /*capacity*/ 8)
            .unwrap();
    let writer = actor.handle();
    writer
        .reserve(
            signed::request("expired-proof"),
            /*maximum_in_flight*/ 1,
        )
        .await
        .unwrap();
    writer
        .bind_execution("expired-proof".to_string(), Arc::clone(&plan), now)
        .await
        .unwrap();
    let dispatch = signed::dispatch("thread-1");
    let bytes = serde_json::to_vec(&dispatch).unwrap();
    let mut hash = Sha256::new();
    hash.update(b"hepta.inference-control.native-dispatch.v1\0");
    hash.update((bytes.len() as u64).to_be_bytes());
    hash.update(bytes);
    let dispatch_digest = format!("{:x}", hash.finalize());
    let prepared = writer
        .prepare_authorized_dispatch(
            "expired-proof".to_string(),
            dispatch,
            Arc::clone(&plan),
            now,
        )
        .await
        .unwrap();
    prepared
        .cross_effect_boundary()
        .started("turn-1".to_string())
        .await
        .unwrap();
    let mut unknown = signed::terminal_output("thread-1", "turn-1", "");
    unknown.status = NativeRunStatus::Indeterminate;
    unknown.boundary_status = NativeBoundaryStatus::Indeterminate;
    unknown.terminal_observed = false;
    let held = writer
        .settle_authorized(
            "expired-proof".to_string(),
            plan,
            now,
            unknown,
            /*protected_output*/ None,
        )
        .await
        .unwrap();
    assert_eq!(held.state, NativeReservationState::Indeterminate);

    // The real verifier accepted this capability while its signed window was
    // live. The writer must use its current clock when the cached proof arrives.
    let receipt = RecoveryReconciliationReceipt {
        schema_version: 1,
        issuer_id: "provider-reconciler".to_string(),
        issuer_authority_epoch: 3,
        execution_authority_epoch: 3,
        request_id: "expired-proof".to_string(),
        principal_id: "principal-1".to_string(),
        execution_binding_digest: recovery_plan.execution_binding_digest().to_string(),
        dispatch_digest,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        provider_id: "provider-1".to_string(),
        model_digest: "1".repeat(64),
        terminal_sequence: 1,
        terminal_status: ReconciledTerminalStatus::Completed,
        output_digest: Some("b".repeat(64)),
        encrypted_output_reference: None,
        observed_output_tokens: Some(7),
        usage_microunits: Some(11),
        issued_at_unix_ms: now - 10_000,
        expires_at_unix_ms: now - 5_000,
    };
    let envelope = SignedRecoveryReconciliationReceipt {
        signature: ControlSignature {
            key_id: "reconciliation-key".to_string(),
            signer_id: "provider-reconciler".to_string(),
            signature: key
                .sign(&receipt.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
        },
        receipt,
    };
    let verified = Arc::new(
        verify_recovery_reconciliation_receipt(now - 7_500, &trust_keys, &recovery_plan, &envelope)
            .unwrap(),
    );
    let reconciler = NativeReconcilerActor::new(writer.clone());
    assert_eq!(
        reconciler
            .reconcile("expired-proof".to_string(), recovery_plan, verified)
            .await,
        Err(NativeControlActorError::Control("InvalidTime".to_string()))
    );
    assert_eq!(
        writer.record("expired-proof".to_string()).await.unwrap(),
        Some(held)
    );
    actor.shutdown().await.unwrap();
}

#[tokio::test]
async fn queued_authorized_commands_recheck_owner_clock_after_expiry() {
    use codex_hepta_infer_core::control_contracts::ControlTrustStore;
    use codex_hepta_infer_core::control_contracts::verify_execution_plan;

    let paths = tempfile::tempdir().unwrap();
    let current_time = || {
        u64::try_from(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_millis(),
        )
        .unwrap()
    };
    let now = current_time();
    let valid_until = now + 5_000;
    let ids = ["queued-bind", "queued-dispatch", "queued-settle"];
    let plans: Vec<_> = ids
        .iter()
        .map(|id| {
            let (keys, bundle) = signed::execution_authority_until(id, now, valid_until);
            Arc::new(
                verify_execution_plan(now, &ControlTrustStore::new(keys).unwrap(), &bundle)
                    .unwrap(),
            )
        })
        .collect();
    let actor =
        NativeJournalWriterActor::spawn(paths.path().join("control.journal"), /*capacity*/ 8)
            .unwrap();
    let writer = actor.handle();
    for id in ids {
        writer
            .reserve(signed::request(id), /*maximum_in_flight*/ 3)
            .await
            .unwrap();
    }
    writer
        .bind_execution(ids[1].to_string(), Arc::clone(&plans[1]), now)
        .await
        .unwrap();
    writer
        .bind_execution(ids[2].to_string(), Arc::clone(&plans[2]), now)
        .await
        .unwrap();
    let prepared = writer
        .prepare_authorized_dispatch(
            ids[2].to_string(),
            signed::dispatch("thread-2"),
            Arc::clone(&plans[2]),
            now,
        )
        .await
        .unwrap();
    prepared
        .cross_effect_boundary()
        .started("turn-2".to_string())
        .await
        .unwrap();
    let mut before = Vec::new();
    for id in ids {
        before.push(writer.record(id.to_string()).await.unwrap().unwrap());
    }
    let (entered, entry) = std::sync::mpsc::sync_channel(1);
    let (release, blocked) = std::sync::mpsc::sync_channel(1);
    writer
        .send(Command::TestPause {
            entered,
            release: blocked,
        })
        .unwrap();
    entry.recv_timeout(Duration::from_secs(5)).unwrap();

    let (bind_reply, bind_response) = oneshot::channel();
    writer
        .send(Command::BindExecution {
            request_id: ids[0].to_string(),
            plan: Arc::clone(&plans[0]),
            now_unix_ms: now,
            reply: bind_reply,
        })
        .unwrap();
    let (dispatch_reply, dispatch_response) = oneshot::channel();
    writer
        .send(Command::PrepareAuthorizedDispatch {
            request_id: ids[1].to_string(),
            dispatch: signed::dispatch("thread-1"),
            plan: Arc::clone(&plans[1]),
            now_unix_ms: now,
            reply: dispatch_reply,
        })
        .unwrap();
    let (settle_reply, settle_response) = oneshot::channel();
    writer
        .send(Command::SettleAuthorized {
            request_id: ids[2].to_string(),
            plan: Arc::clone(&plans[2]),
            now_unix_ms: now,
            output: signed::terminal_output("thread-2", "turn-2", "private output"),
            protected_output: None,
            reply: settle_reply,
        })
        .unwrap();
    // All three were accepted with a live caller timestamp. Keep the unique
    // owner paused across the signed lease/data-policy deadline.
    tokio::time::sleep(Duration::from_millis(
        valid_until.saturating_sub(current_time()) + 1,
    ))
    .await;
    release.send(()).unwrap();
    assert_eq!(
        bind_response.await.unwrap(),
        Err(NativeControlActorError::Control("InvalidTime".to_string()))
    );
    assert_eq!(
        dispatch_response.await.unwrap().map(|_| ()),
        Err(NativeControlActorError::Control("InvalidTime".to_string()))
    );
    assert!(matches!(
        settle_response.await.unwrap(),
        Err(NativeControlActorError::Control(_))
    ));
    for (id, unchanged) in ids.into_iter().zip(before) {
        assert_eq!(
            writer.record(id.to_string()).await.unwrap(),
            Some(unchanged)
        );
    }
    actor.shutdown().await.unwrap();
}
