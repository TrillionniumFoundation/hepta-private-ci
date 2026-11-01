use super::*;
use codex_hepta_evidence::AuthBusAdmissionError;
use codex_hepta_evidence::AuthBusOutboxError;
use codex_hepta_types::Generation;

#[tokio::test]
async fn pq_bound_policy_refuses_renewal_without_policy_snapshot() {
    let fixture = Fixture::with_algorithm(AuthBusAlgorithm::MlDsa65V2).await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let delivery = fixture.claim(&host, id).await;
    let issuer = host.trust(&fixture.state).await.unwrap().issuer().unwrap();
    let before = host.evidence.authbus_delivery_status(id).await.unwrap();
    assert!(matches!(
        host.evidence
            .renew_authbus_delivery(&issuer, &delivery.lease, /*lease_ms*/ 30_000)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::OwnerPolicyMismatch
        ))
    ));
    assert_eq!(
        host.evidence.authbus_delivery_status(id).await.unwrap(),
        before
    );

    // The real dispatcher must select the policy-bound entry, so refusing the
    // old API cannot turn a legitimate PQ delivery into an unavailable service.
    let queue = ReplyLostQueue::default();
    queue.lose_reply.store(false, Ordering::SeqCst);
    deliver(&fixture.state, &host, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 1);
    assert_eq!(
        host.evidence
            .authbus_delivery_status(id)
            .await
            .unwrap()
            .state,
        AuthBusDeliveryState::Acked
    );
}

#[tokio::test]
async fn pq_policy_change_fences_stale_renewal_and_current_policy_restores_dispatch() {
    let fixture = Fixture::with_algorithm(AuthBusAlgorithm::MlDsa65V2).await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let delivery = fixture.claim(&host, id).await;
    let selected = host.trust(&fixture.state).await.unwrap();
    let issuer = selected.issuer().unwrap();
    let (selected_revision, selected_digest) = selected.owner_policy().unwrap();

    // A second legitimate owner refresh changes only thread permission, leaving
    // issuer, key and epoch identical. A previously selected snapshot must not
    // become usable merely because renewal acquired its SQLite lock later.
    let mut config: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&fixture.trust_file).unwrap()).unwrap();
    config["policy_revision"] = serde_json::json!(selected_revision.get() + 1);
    config["thread_ids"] = serde_json::json!([]);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&config).unwrap()).unwrap();
    let current = host.trust(&fixture.state).await.unwrap();
    let current_issuer = current.issuer().unwrap();
    assert_eq!(
        (
            &current_issuer.issuer_id,
            current_issuer.key_epoch,
            current_issuer.verifying_key.as_bytes(),
            current_issuer.revoked,
        ),
        (
            &issuer.issuer_id,
            issuer.key_epoch,
            issuer.verifying_key.as_bytes(),
            issuer.revoked,
        )
    );
    let (current_revision, current_digest) = current.owner_policy().unwrap();
    let before = host.evidence.authbus_delivery_status(id).await.unwrap();
    for (revision, digest) in [
        (selected_revision, selected_digest),
        (current_revision, selected_digest),
        (
            Generation::new(current_revision.get() + 1).unwrap(),
            current_digest,
        ),
    ] {
        assert!(matches!(
            host.evidence
                .renew_authbus_delivery_with_owner_policy(
                    &issuer,
                    &delivery.lease,
                    revision,
                    digest,
                    /*lease_ms*/ 30_000,
                )
                .await,
            Err(AuthBusOutboxError::Admission(
                AuthBusAdmissionError::OwnerPolicyMismatch
            ))
        ));
        assert_eq!(
            host.evidence.authbus_delivery_status(id).await.unwrap(),
            before
        );
    }
    assert!(matches!(
        host.evidence
            .renew_authbus_delivery(&issuer, &delivery.lease, /*lease_ms*/ 30_000)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::OwnerPolicyMismatch
        ))
    ));
    let queue = ReplyLostQueue::default();
    queue.lose_reply.store(false, Ordering::SeqCst);
    deliver(&fixture.state, &host, &queue, delivery)
        .await
        .unwrap();
    assert!(queue.modes.lock().unwrap().is_empty());
    assert_eq!(
        host.evidence
            .authbus_delivery_status(id)
            .await
            .unwrap()
            .state,
        AuthBusDeliveryState::Quarantined
    );

    config["policy_revision"] = serde_json::json!(current_revision.get() + 1);
    config["thread_ids"] = serde_json::json!(["thread:test"]);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&config).unwrap()).unwrap();
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 2))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let mut delivery = fixture.claim(&host, id).await;
    let restored = host.trust(&fixture.state).await.unwrap();
    let (revision, digest) = restored.owner_policy().unwrap();
    delivery.lease = host
        .evidence
        .renew_authbus_delivery_with_owner_policy(
            &restored.issuer().unwrap(),
            &delivery.lease,
            revision,
            digest,
            /*lease_ms*/ 30_000,
        )
        .await
        .unwrap();
    deliver(&fixture.state, &host, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 1);
    assert_eq!(
        host.evidence
            .authbus_delivery_status(id)
            .await
            .unwrap()
            .state,
        AuthBusDeliveryState::Acked
    );
}

#[tokio::test]
async fn pq_removed_thread_cannot_return_through_owner_file_rollback_after_reopen() {
    let mut fixture = Fixture::with_algorithm(AuthBusAlgorithm::MlDsa65V2).await;
    let allowed = std::fs::read(&fixture.trust_file).unwrap();
    let request = fixture.request(/*sequence*/ 1);
    let mut removed: serde_json::Value = serde_json::from_slice(&allowed).unwrap();
    removed["policy_revision"] = serde_json::json!(2);
    removed["thread_ids"] = serde_json::json!([]);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&removed).unwrap()).unwrap();
    assert!(submit(&fixture.state, request.clone()).await.is_err());

    // Retain the real SQLite owner and independently retained checkpoint while
    // reopening against the owner file that no longer permits this thread.
    let recovered = Arc::new(
        TextIngress::open(
            fixture.state.identity(),
            fixture.trust_file.clone(),
            fixture.checkpoint_file.clone(),
        )
        .await
        .unwrap(),
    );
    let identity = fixture.state.identity().clone();
    // Release the original state's exclusive durable prompt owners before
    // opening a replacement state and submitting through its new ingress.
    drop(fixture.state);
    let state = Arc::new(
        AgentdState::new(
            identity,
            fixture.registry.clone(),
            /*event_capacity*/ 16,
        )
        .unwrap(),
    );
    state.refresh_generation().unwrap();
    fixture.state = Arc::clone(&state);
    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&state.identity().layout)
            .await
            .unwrap();
    state.attach_cognitive_store(Arc::new(cognitive)).unwrap();
    state.mark_runtime_prerequisites_ready().unwrap();
    state.mark_app_server_ready().unwrap();
    assert!(state.authbus.set(Arc::clone(&recovered)).is_ok());
    std::fs::write(&fixture.trust_file, &allowed).unwrap();
    let admitted_after_rollback = submit(&fixture.state, request.clone()).await;
    assert!(
        admitted_after_rollback.is_err(),
        "restoring an older owner file restored removed thread authority: {admitted_after_rollback:?}"
    );
    assert!(recovered.trust(&fixture.state).await.is_err());

    // Equal revisions cannot change authority. A strictly newer revision may
    // intentionally add a thread again without rotating its signing key.
    let mut restored = removed.clone();
    restored["thread_ids"] = serde_json::json!(["thread:test"]);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&restored).unwrap()).unwrap();
    assert!(submit(&fixture.state, request.clone()).await.is_err());
    restored["policy_revision"] = serde_json::json!(3);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&restored).unwrap()).unwrap();
    let id = submit(&fixture.state, request)
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let queue = ReplyLostQueue::default();
    queue.lose_reply.store(false, Ordering::SeqCst);
    let delivery = fixture.claim(&recovered, id).await;
    deliver(&fixture.state, &recovered, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 1);

    // The policy floor is domain-wide. Switching the current issuer cannot
    // make an older issuer's owner file current again.
    let old_issuer_request = fixture.request(/*sequence*/ 2);
    fixture.key = FixtureSigner::new(/*seed*/ 59, AuthBusAlgorithm::MlDsa65V2);
    let mut successor = restored.clone();
    successor["policy_revision"] = serde_json::json!(4);
    successor["issuer_id"] = serde_json::json!("issuer:successor");
    successor["public_key_hex"] = serde_json::json!(
        fixture
            .key
            .verifying_key()
            .as_bytes()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    );
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&successor).unwrap()).unwrap();
    let mut next = fixture.request(/*sequence*/ 1);
    next.issuer_id = "issuer:successor".into();
    next.message_id = "message:successor:1".into();
    fixture
        .key
        .sign(&fixture.state.identity().agent_id, &mut next);
    let id = submit(&fixture.state, next)
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let delivery = fixture.claim(&recovered, id).await;
    deliver(&fixture.state, &recovered, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 2);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&restored).unwrap()).unwrap();
    assert!(submit(&fixture.state, old_issuer_request).await.is_err());
    assert!(recovered.trust(&fixture.state).await.is_err());
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&successor).unwrap()).unwrap();
    let mut last = fixture.request(/*sequence*/ 2);
    last.issuer_id = "issuer:successor".into();
    last.message_id = "message:successor:2".into();
    fixture
        .key
        .sign(&fixture.state.identity().agent_id, &mut last);
    let id = submit(&fixture.state, last)
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let delivery = fixture.claim(&recovered, id).await;
    deliver(&fixture.state, &recovered, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 3);
}

#[tokio::test]
async fn pq_owner_requires_explicit_nonzero_policy_revision_and_accepts_set_ordering() {
    let fixture = Fixture::with_algorithm(AuthBusAlgorithm::MlDsa65V2).await;
    let mut config: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&fixture.trust_file).unwrap()).unwrap();
    config.as_object_mut().unwrap().remove("policy_revision");
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&config).unwrap()).unwrap();
    assert!(submit(&fixture.state, fixture.request(1)).await.is_err());
    config["policy_revision"] = serde_json::json!(0);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&config).unwrap()).unwrap();
    assert!(submit(&fixture.state, fixture.request(1)).await.is_err());
    config["policy_revision"] = serde_json::json!(2);
    config["thread_ids"] = serde_json::json!(["thread:other", "thread:test"]);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&config).unwrap()).unwrap();
    let request = fixture.request(1);
    let first = submit(&fixture.state, request.clone()).await.unwrap();
    config["thread_ids"] = serde_json::json!(["thread:test", "thread:other", "thread:test"]);
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&config).unwrap()).unwrap();
    assert_eq!(submit(&fixture.state, request).await.unwrap(), first);
}
