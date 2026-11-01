//! Test-only SQLite contention control; no IPC or external effect transport.
use super::*;
use codex_hepta_authbus::AuthBusAlgorithm;
use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;

// A fixture witness outside the SQLite file, not independent deployment evidence.
async fn acknowledge(
    store: &HeptaEvidenceStore,
    external: &mut ReplayCheckpoint,
    path: &std::path::Path,
) {
    let pending = store
        .reconcile_authbus_restore_checkpoint(*external)
        .await
        .unwrap()
        .expect("pending fixture checkpoint");
    let bytes = format!("{}:{}\n", pending.generation, pending.digest);
    let file = std::fs::File::create(path).unwrap();
    std::io::Write::write_all(&mut &file, bytes.as_bytes()).unwrap();
    file.sync_all().unwrap();
    assert_eq!(std::fs::read(path).unwrap(), bytes.as_bytes());
    store
        .advance_authbus_restore_checkpoint(external.generation, pending)
        .await
        .unwrap();
    *external = pending;
}

#[tokio::test]
async fn policy_writer_contention_fails_closed_until_checkpoint_then_fences_old_snapshot() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let algorithm = AuthBusAlgorithm::MlDsa65V2;
    store.bind_authbus_profile(algorithm).await.unwrap();
    let spki = PqNativeSigningKey::public_spki_from_seed(&[91; 32].into());
    let key = PqNativeSigningKey::from_owned_seed(
        [91; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki).unwrap(),
    )
    .unwrap();
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:policy-contention").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: AuthBusVerifyingKey::from_pq_spki(&spki).unwrap(),
        revoked: false,
    };
    let mut external = ReplayCheckpoint {
        generation: 1,
        digest: store.authbus_replay_frontier_digest().await.unwrap(),
    };
    store
        .initialize_authbus_restore_checkpoint(external)
        .await
        .unwrap();
    let witness = temp.path().join("fixture-external-witness.txt");
    let old_revision = Generation::new(1).unwrap();
    let old_digest = Digest32::of_bytes(b"fixture-policy-old");
    store
        .pin_authbus_issuer_with_owner_policy(&issuer, old_revision, old_digest)
        .await
        .unwrap();
    acknowledge(&store, &mut external, &witness).await;
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new("message:policy-contention").unwrap(),
        subject_id: StableId::new("subject:policy-contention").unwrap(),
        scope_digest: Digest32::of_bytes(b"route"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence: 1,
        expires_at_ms: now_millis().unwrap() as u64 + 60_000,
    };
    let signature = key
        .sign_exact_message(&claims.signing_bytes_for(algorithm))
        .unwrap()
        .into();
    let message = SignedMessage { claims, signature };
    let queued = store
        .enqueue_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"payload",
        )
        .await
        .unwrap();
    acknowledge(&store, &mut external, &witness).await;
    let worker = StableId::new("worker:policy-contention").unwrap();
    let delivery = store
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: queued.delivery_id,
                subject_id: &message.claims.subject_id,
                scope_digest: message.claims.scope_digest,
                worker_id: &worker,
                lease_ms: 30_000,
            },
        )
        .await
        .unwrap();
    let before = store
        .authbus_delivery_status(queued.delivery_id)
        .await
        .unwrap();
    // The production pool allows five connections. This transaction holds one;
    // the public renewal must obtain a distinct connection and contend for its lock.
    let mut writer = store.pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
    let new_revision = Generation::new(2).unwrap();
    let new_digest = Digest32::of_bytes(b"fixture-policy-new");
    assert!(
        crate::authbus_owner_policy::update_required(&mut writer, new_revision, new_digest)
            .await
            .unwrap()
    );
    crate::authbus_owner_policy::store(&mut writer, new_revision, new_digest)
        .await
        .unwrap();
    crate::authbus_recovery::stage_replay_checkpoint_after_mutation(&mut writer)
        .await
        .unwrap();
    {
        let renewal = store.renew_authbus_delivery_with_owner_policy(
            &issuer,
            &delivery.lease,
            old_revision,
            old_digest,
            /*lease_ms*/ 30_000,
        );
        tokio::pin!(renewal);
        // A completed future here is a failure. Pending is only an observation
        // of non-completion, not instrumentation of SQLite's busy-handler entry.
        tokio::select! {
            biased;
            result = &mut renewal => {
                writer.rollback().await.unwrap();
                panic!("renewal completed while writer held lock: {result:?}");
            }
            () = tokio::time::sleep(Duration::from_millis(100)) => {}
        }
        writer.commit().await.unwrap();
        // Resume the SAME future; the observation window never cancels it.
        // On deadline failure the test aborts before any later assertion or ACK;
        // no task was spawned and all handles belong only to this temporary DB.
        let result = tokio::time::timeout(Duration::from_secs(10), &mut renewal)
            .await
            .expect("renewal must settle after writer commits");
        assert!(matches!(result, Err(AuthBusOutboxError::Unavailable)));
    }
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        before
    );
    assert!(
        store
            .pending_authbus_restore_checkpoint()
            .await
            .unwrap()
            .is_some()
    );
    acknowledge(&store, &mut external, &witness).await;
    assert!(matches!(
        store
            .renew_authbus_delivery_with_owner_policy(
                &issuer,
                &delivery.lease,
                old_revision,
                old_digest,
                /*lease_ms*/ 30_000,
            )
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::OwnerPolicyMismatch
        ))
    ));
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        before
    );
    let renewed = store
        .renew_authbus_delivery_with_owner_policy(
            &issuer,
            &delivery.lease,
            new_revision,
            new_digest,
            /*lease_ms*/ 30_000,
        )
        .await
        .unwrap();
    let after = store
        .authbus_delivery_status(queued.delivery_id)
        .await
        .unwrap();
    assert_eq!(after.fence, before.fence + 1);
    assert_eq!(after.state, AuthBusDeliveryState::Leased);
    assert_eq!(after.attempts, before.attempts);
    assert_eq!(after.lease_until_ms, Some(renewed.expires_at_ms()));
    assert_eq!(
        store.pending_authbus_restore_checkpoint().await.unwrap(),
        None
    );
    store.pool.close().await;
}
