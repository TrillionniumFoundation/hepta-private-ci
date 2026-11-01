use super::*;

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
