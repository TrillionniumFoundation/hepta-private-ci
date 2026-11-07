use super::*;
use crate::control_packet::AdmittedEffectPacketV1;
use tokio::sync::Semaphore;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn packet_v1_refuses_http_even_with_valid_pq_grant_before_consumption() -> anyhow::Result<()>
{
    let fixture = Fixture::new().await?;
    let server = MockServer::start().await;
    let scope = Sha256Digest::for_bytes(b"packet-http-refusal");
    let setup = PqFixture::http(&server.uri(), &scope)?;
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, NOW, &intent).await?;
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert!(!host.supports_packet_v1());
    let before = setup.trust_requests();
    let mut reader = WIRE;
    let packet = AdmittedEffectPacketV1::read(
        &mut reader,
        u32::try_from(WIRE.len())?,
        &intent.payload_digest,
        Arc::new(Semaphore::new(/*permits*/ 2)),
        &crate::NeuralCognitiveExecutionV1::bounded_read(),
    )
    .await?;
    assert!(
        host.execute_packet_v1(
            &fixture.store,
            &intent,
            &packet,
            &grant,
            "packet-http",
            NOW + 5,
        )
        .await
        .is_err()
    );
    assert_eq!(setup.trust_requests(), before);
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert!(
        fixture
            .store
            .pending_authorized_taskflow_effects(8)
            .await?
            .is_empty()
    );
    assert!(
        server
            .received_requests()
            .await
            .expect("HTTP observations")
            .is_empty()
    );
    fixture.store.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn packet_v1_keeps_full_intent_binding_and_refuses_missing_or_classical_owner()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"packet-owner-refusal");
    let mut setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
    setup.config["provider"] = legacy_fixture::pon_provider(setup.root.path())?;
    let provider: ProviderConfig = serde_json::from_value(setup.config["provider"].clone())?;
    let mut statement = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
    statement.extend(serde_json::to_vec(&serde_json::json!({
        "provider_scope": setup.config["provider_scope"],
        "destination_id": setup.config["destination_id"],
        "final_use_scope_sha256": setup.config["final_use_scope_sha256"],
        "provider": provider,
    }))?);
    setup.sign_contract(&Sha256Digest::for_bytes(&statement))?;
    let mut host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert!(host.supports_packet_v1());
    let wire = vec![0x51; 49_508];
    let mut intent = effect_intent(&scope);
    intent.payload_digest = Sha256Digest::for_bytes(&wire);
    prepare_effect(&fixture, NOW, &intent).await?;
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let before = setup.trust_requests();
    let packet = AdmittedEffectPacketV1::read(
        &mut wire.as_slice(),
        u32::try_from(wire.len())?,
        &intent.payload_digest,
        Arc::new(Semaphore::new(/*permits*/ 2)),
        &crate::NeuralCognitiveExecutionV1::bounded_read(),
    )
    .await?;
    let mut changed = vec![intent.clone(); 4];
    changed[0].subject_id = "foreign-agent".to_string();
    changed[1].destination_id = "foreign-provider".to_string();
    changed[2].final_use_scope_digest = Sha256Digest::for_bytes(b"foreign-scope");
    changed[3].payload_digest = Sha256Digest::for_bytes(b"foreign-payload");
    for wrong in changed {
        assert!(
            host.execute_packet_v1(
                &fixture.store,
                &wrong,
                &packet,
                &grant,
                "packet-binding",
                NOW + 5,
            )
            .await
            .is_err()
        );
    }
    // Cancellation after framing must still refuse before authority or provider
    // entry; a successfully admitted body is not an execution lease.
    let cancellation = tokio_util::sync::CancellationToken::new();
    let execution = crate::NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(2),
        cancellation.clone(),
    );
    let cancelled = AdmittedEffectPacketV1::read(
        &mut wire.as_slice(),
        u32::try_from(wire.len())?,
        &intent.payload_digest,
        Arc::new(Semaphore::new(/*permits*/ 2)),
        &execution,
    )
    .await?;
    cancellation.cancel();
    assert!(matches!(host.execute_packet_v1(
        &fixture.store, &intent, &cancelled, &grant, "packet-binding", NOW + 5,
    ).await, Err(AgentdError::Protocol(message)) if message.contains("cancelled")));
    let pq = host.pq.take();
    assert!(!host.supports_packet_v1());
    assert!(
        host.execute_packet_v1(
            &fixture.store,
            &intent,
            &packet,
            &grant,
            "packet-binding",
            NOW + 5,
        )
        .await
        .is_err()
    );
    host.pq = pq;
    let current = host.authority.clone();
    host.authority = FinalUseAuthority::open_state_dir(
        &setup.root.path().join("classical-fixture-owner"),
        "classical-fixture".to_string(),
        SigningKey::from_bytes(&[17; 32]).verifying_key().to_bytes(),
        setup.head.clone(),
    )?;
    assert!(!host.supports_packet_v1());
    assert!(
        host.execute_packet_v1(
            &fixture.store,
            &intent,
            &packet,
            &grant,
            "packet-binding",
            NOW + 5,
        )
        .await
        .is_err()
    );
    assert_eq!(current.capacity()?.used_nonces, 0);
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert_eq!(setup.trust_requests(), before);
    assert!(
        fixture
            .store
            .pending_authorized_taskflow_effects(8)
            .await?
            .is_empty()
    );
    fixture.store.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn packet_v1_rejects_above_recovery_ledger_limit_before_consuming_valid_grant()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"packet-recovery-ledger-bound");
    let mut setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
    setup.config["provider"] = legacy_fixture::pon_provider(setup.root.path())?;
    let provider: ProviderConfig = serde_json::from_value(setup.config["provider"].clone())?;
    let mut statement = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
    statement.extend(serde_json::to_vec(&serde_json::json!({
        "provider_scope": setup.config["provider_scope"],
        "destination_id": setup.config["destination_id"],
        "final_use_scope_sha256": setup.config["final_use_scope_sha256"],
        "provider": provider,
    }))?);
    setup.sign_contract(&Sha256Digest::for_bytes(&statement))?;
    let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert!(host.supports_packet_v1());

    // The original ledger accepts at most 65,536 bytes. At the former 1-MiB
    // transport bound this valid signed intent reached authority.claim(), then
    // failed at begin_effect_dispatch_attempt() after consuming its nonce.
    let wire = vec![0x51; 65_537];
    let mut intent = effect_intent(&scope);
    intent.payload_digest = Sha256Digest::for_bytes(&wire);
    prepare_effect(&fixture, NOW, &intent).await?;
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let trust_before = setup.trust_requests();
    let permits = Arc::new(Semaphore::new(/*permits*/ 2));
    let execution = crate::NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(/*secs*/ 30),
        tokio_util::sync::CancellationToken::new(),
    );
    let mut reader = wire.as_slice();
    let result = async {
        let packet = AdmittedEffectPacketV1::read(
            &mut reader,
            u32::try_from(wire.len()).expect("bounded regression length"),
            &intent.payload_digest,
            Arc::clone(&permits),
            &execution,
        )
        .await?;
        host.execute_packet_v1(
            &fixture.store,
            &intent,
            &packet,
            &grant,
            "packet-recovery-ledger-bound",
            NOW + 5,
        )
        .await
    }
    .await;
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert!(
        fixture
            .store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
            .is_none()
    );
    assert_eq!(setup.trust_requests(), trust_before);
    assert_eq!(reader, wire.as_slice());
    assert_eq!(permits.available_permits(), 2);
    assert!(matches!(
        result,
        Err(AgentdError::Invalid(message))
            if message == "automation effect packet length is invalid"
    ));
    // Even an internal caller bypassing framing cannot start a provider for a
    // packet that the unchanged durable recovery owner cannot retain.
    let key = ProviderEffectKey::for_taskflow_v2(
        "provider/fixture-v1",
        &fixture.identity.agent_id,
        &intent.run_id,
        &intent.step_id,
    )
    .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    let provider_intent = ProviderEffectIntent::new(key, intent.payload_digest.clone());
    let AgentdProviderEffectAdapter::Pon(adapter) = &host.adapter else {
        anyhow::bail!("PQ PoN fixture required");
    };
    assert!(matches!(
        adapter.dispatch_packet(provider_intent, wire, execution).await,
        ProviderEffectDispatch::NotDispatched { reason_code }
            if reason_code == "pon_packet_v1_length_invalid"
    ));
    fixture.store.close().await;
    Ok(())
}
