use super::super::tests::Fixture;
use super::super::tests::WIRE;
use super::super::tests::effect_intent;
use super::super::tests::prepare_effect;
use super::*;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
use codex_model_provider::PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::atomic::Ordering;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_bytes;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;

#[path = "automation_effect_host_pq_test_support.rs"]
mod support;
use support::write_private;

#[path = "automation_effect_host_pq_legacy_fixture.rs"]
mod legacy_fixture;

#[path = "automation_effect_host_pq_fixture.rs"]
mod fixture;
use fixture::PqFixture;

const NOW: u64 = 1_000_000;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_pq_http_dispatches_once_and_reads_exact_receipt_after_reopen()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let server = MockServer::start().await;
    let scope = Sha256Digest::for_bytes(b"ordinary-pq-effect");
    let setup = PqFixture::http(&server.uri(), &scope)?;
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, NOW, &intent).await?;
    let key = ProviderEffectKey::for_taskflow_v2(
        "provider/fixture-v1",
        &fixture.identity.agent_id,
        &intent.run_id,
        &intent.step_id,
    )
    .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    let ack = serde_json::json!({ "effect_key": key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": Sha256Digest::for_bytes(b"pq-provider-operation").as_str(), "status": "completed" });
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER, key.as_str()))
        .and(header(
            PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER,
            intent.payload_digest.as_str(),
        ))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(200).set_body_json(ack))
        .expect(1)
        .mount(&server)
        .await;
    let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert_eq!(
        host.authority.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let receipt = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "pq-dispatch",
            NOW + 5,
        )
        .await?;
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );
    let durable = fixture
        .store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .expect("durable provider attempt");
    assert_eq!(durable.provider_effect_key.as_ref(), Some(&key));
    assert_eq!(durable.wire_payload.as_deref(), Some(WIRE));
    let consumed = host.authority.frontier()?;
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    assert_eq!(
        serde_json::from_slice::<FinalUseFrontier>(&fs::read(
            setup.root.path().join("frontier.json")
        )?)?,
        consumed
    );
    fixture.store.close().await;
    drop(host);
    let store = AutomationStore::open(&fixture.identity.layout).await?;
    let reopened = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert_eq!(reopened.authority.frontier()?, consumed);
    let mut revoked = setup.head.clone();
    revoked.revision += 1;
    revoked
        .revoked_grant_ids
        .insert(grant.grant.grant_id.clone());
    setup.publish_feed(&setup.feed(revoked.clone(), NOW - 1000, NOW + 60_000)?)?;
    reopened.pq.as_ref().expect("PQ owner").authenticate(
        &reopened.authority,
        &setup.feed_path,
        &grant,
    )?;
    assert_eq!(reopened.authority.revocation_head()?, revoked);
    assert_eq!(reopened.authority.capacity()?.used_nonces, 1);
    setup.now.store(NOW + 90_000, Ordering::SeqCst);
    // Exact terminal evidence remains readable after expiry and revocation,
    // with both real trust services and their files gone. This grants no retry.
    drop(setup);
    let replay = reopened
        .execute(&store, &intent, WIRE, &grant, "pq-dispatch", NOW + 90_000)
        .await?;
    assert_eq!(replay, receipt);
    let mut substituted = intent.clone();
    substituted.operation_id.push_str("-changed");
    assert!(
        reopened
            .execute(
                &store,
                &substituted,
                WIRE,
                &grant,
                "pq-dispatch",
                NOW + 90_001
            )
            .await
            .is_err()
    );
    assert!(
        reopened
            .execute(
                &store,
                &intent,
                b"changed",
                &grant,
                "pq-dispatch",
                NOW + 90_001
            )
            .await
            .is_err()
    );
    assert!(
        reopened
            .execute(
                &store,
                &intent,
                WIRE,
                &grant,
                "changed-command",
                NOW + 90_001
            )
            .await
            .is_err()
    );
    assert_eq!(
        server
            .received_requests()
            .await
            .expect("HTTP observations")
            .len(),
        1
    );
    server.verify().await;
    store.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_loader_rejects_legacy_missing_or_classical_profile_before_trust()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let server = MockServer::start().await;
    let scope = Sha256Digest::for_bytes(b"ordinary-pq-effect");
    let mut setup = PqFixture::http(&server.uri(), &scope)?;
    let valid = setup.config.clone();
    let legacy =
        legacy_fixture::configurations(setup.root.path(), &server.uri(), &scope, &setup.head)?;
    for case in 0..4 {
        setup.config = valid.clone();
        match case {
            0 => setup.config = legacy[0].clone(),
            1 => setup.config = legacy[1].clone(),
            2 => {
                setup
                    .config
                    .as_object_mut()
                    .expect("config")
                    .remove("authentication_profile");
            }
            3 => setup.config["authentication_profile"] = serde_json::json!("classical_v1"),
            _ => unreachable!(),
        }
        setup.write_config()?;
        assert!(
            matches!(AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path),
            Err(AgentdError::Invalid(message)) if message.contains("schema 4 and explicit ml_dsa65_v2"))
        );
        assert!(
            !fixture
                .identity
                .layout
                .automation_root()
                .join("final-use-authority")
                .exists()
        );
        assert_eq!(setup.trust_requests(), 0);
        assert!(
            server
                .received_requests()
                .await
                .expect("HTTP observations")
                .is_empty()
        );
        if case < 2 {
            // The identical bytes must be accepted by the original explicit
            // test-only constructor. Ordinary refusal is not a malformed-file test.
            let old_fixture = Fixture::new().await?;
            let old = AgentdAutomationEffectHost::open_legacy_for_test(
                &old_fixture.identity,
                &setup.config_path,
            )?;
            assert_eq!(
                old.authority.authentication_profile(),
                FinalUseAuthenticationProfile::ClassicalV1
            );
            old_fixture.store.close().await;
        }
    }
    setup.config = valid;
    let classical = SigningKey::from_bytes(&[88; 32]);
    let digest = Sha256Digest::parse(
        setup.config["contract_sha256"]
            .as_str()
            .expect("digest")
            .to_string(),
    )
    .map_err(anyhow::Error::msg)?;
    let statement = HttpProviderEffectContractAttestation::statement_for(
        "pq-http-fixture",
        &digest,
        /*authority_epoch*/ 9,
    );
    let signature = classical.sign(&statement).to_bytes();
    assert!(
        HttpProviderEffectContractAttestation::verify_signed(
            "pq-http-fixture",
            digest,
            /*authority_epoch*/ 9,
            &signature,
            &classical.verifying_key().to_bytes()
        )
        .map_err(anyhow::Error::msg)?
        .is_verified()
    );
    setup.config["contract_signature"] = serde_json::json!(signature.to_vec());
    setup.write_config()?;
    assert!(AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path).is_err());
    assert!(
        !fixture
            .identity
            .layout
            .automation_root()
            .join("final-use-authority")
            .exists()
    );
    assert_eq!(setup.trust_requests(), 0);
    fixture.store.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_pq_refuses_invalid_feed_expiry_and_grant_outliving_feed_before_send()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let server = MockServer::start().await;
    let scope = Sha256Digest::for_bytes(b"ordinary-pq-effect");
    let setup = PqFixture::http(&server.uri(), &scope)?;
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, NOW, &intent).await?;
    let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let before = host.authority.frontier()?;
    write_private(&setup.feed_path, &serde_json::to_vec(&setup.head)?)?;
    assert!(
        host.execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "pq-unsigned-head",
            NOW + 5
        )
        .await
        .is_err()
    );
    let mut corrupt = setup.feed(setup.head.clone(), NOW - 1000, NOW + 60_000)?;
    corrupt.signature[100] ^= 1;
    let expired = setup.feed(setup.head.clone(), NOW - 1000, NOW)?;
    let short = setup.feed(setup.head.clone(), NOW - 1000, NOW + 10_000)?;
    for feed in [corrupt, expired, short] {
        setup.publish_feed(&feed)?;
        assert!(
            host.execute(&fixture.store, &intent, WIRE, &grant, "pq-refusal", NOW + 5)
                .await
                .is_err()
        );
        assert_eq!(host.authority.frontier()?, before);
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
    }
    setup.publish_feed(&setup.feed(setup.head.clone(), NOW - 1000, NOW + 60_000)?)?;
    setup.now.store(NOW + 30_000, Ordering::SeqCst);
    assert!(
        host.execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "pq-expired-grant",
            NOW + 30_000
        )
        .await
        .is_err()
    );
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
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
async fn ordinary_pq_signed_revocation_and_old_feed_never_reenter_provider() -> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let server = MockServer::start().await;
    let scope = Sha256Digest::for_bytes(b"ordinary-pq-effect");
    let setup = PqFixture::http(&server.uri(), &scope)?;
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, NOW, &intent).await?;
    let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let mut revoked = setup.head.clone();
    revoked.revision += 1;
    revoked
        .revoked_grant_ids
        .insert(grant.grant.grant_id.clone());
    setup.publish_feed(&setup.feed(revoked.clone(), NOW - 1000, NOW + 60_000)?)?;
    assert!(
        host.execute(&fixture.store, &intent, WIRE, &grant, "pq-revoked", NOW + 5)
            .await
            .is_err()
    );
    assert_eq!(host.authority.revocation_head()?, revoked);
    let retained = host.authority.frontier()?;
    setup.publish_feed(&setup.feed(setup.head.clone(), NOW - 1000, NOW + 60_000)?)?;
    assert!(
        host.execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "pq-old-feed",
            NOW + 6
        )
        .await
        .is_err()
    );
    assert_eq!(host.authority.frontier()?, retained);
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
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
async fn original_store_driver_refuses_authenticated_lease_after_exact_head_changes()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let server = MockServer::start().await;
    let scope = Sha256Digest::for_bytes(b"ordinary-pq-effect");
    let setup = PqFixture::http(&server.uri(), &scope)?;
    let intent = effect_intent(&scope);
    let fence = prepare_effect(&fixture, NOW, &intent).await?;
    let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let lease = host.pq.as_ref().expect("PQ owner").authenticate(
        &host.authority,
        &setup.feed_path,
        &grant,
    )?;
    assert!(lease.check().is_ok());
    let mut successor = setup.head.clone();
    successor.revision += 1;
    host.authority.update_revocations(successor.clone())?;
    let mut driver = AgentdAuthorizedEffectDriver {
        adapter: host.adapter.clone(),
        lease: Some(lease),
        provider_scope: host.provider_scope.clone(),
        destination_id: host.destination_id.clone(),
    };
    let binding = intent.final_use_binding()?;
    let result = fixture
        .store
        .execute_authorized_taskflow_effect(
            &host.authority,
            &mut driver,
            AuthorizedEffectExecutionInput {
                intent: &intent,
                wire_payload: WIRE,
                fence: &fence,
                signed_grant: &grant,
                expected_binding: &binding,
                command_id: "pq-head-race",
                now_ms: NOW + 5,
            },
        )
        .await;
    assert!(matches!(
        result,
        Err(AuthorizedEffectError::Driver(
            AuthorizedEffectDriverError::BeforeProviderContact
        ))
    ));
    assert_eq!(host.authority.revocation_head()?, successor);
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
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
async fn ordinary_pq_missing_external_frontier_cannot_bootstrap_or_dispatch() -> anyhow::Result<()>
{
    for lose_after_open in [false, true] {
        let fixture = Fixture::new().await?;
        let server = MockServer::start().await;
        let scope = Sha256Digest::for_bytes(b"ordinary-pq-effect");
        let mut setup = PqFixture::http(&server.uri(), &scope)?;
        let host = if lose_after_open {
            Some(AgentdAutomationEffectHost::open(
                &fixture.identity,
                &setup.config_path,
            )?)
        } else {
            None
        };
        drop(setup.frontier.take());
        if let Some(host) = host {
            let intent = effect_intent(&scope);
            prepare_effect(&fixture, NOW, &intent).await?;
            let grant = setup.grant(&intent, NOW + 30_000)?;
            assert!(
                host.execute(
                    &fixture.store,
                    &intent,
                    WIRE,
                    &grant,
                    "pq-frontier-loss",
                    NOW + 5
                )
                .await
                .is_err()
            );
            assert!(
                fixture
                    .store
                    .pending_authorized_taskflow_effects(8)
                    .await?
                    .is_empty()
            );
        } else {
            assert!(
                AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path).is_err()
            );
            assert!(
                !fixture
                    .identity
                    .layout
                    .automation_root()
                    .join("final-use-authority")
                    .exists()
            );
        }
        assert!(
            server
                .received_requests()
                .await
                .expect("HTTP observations")
                .is_empty()
        );
        fixture.store.close().await;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_pq_pon_loader_binds_actual_elf_and_contract_without_executing_chain()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"ordinary-pq-pon");
    let mut setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
    // Loader qualification only; no Chain process or business success occurs.
    setup.config["contract_id"] = serde_json::json!("pq-pon-fixture");
    setup.config["provider"] = legacy_fixture::pon_provider(setup.root.path())?;
    let typed: ProviderConfig = serde_json::from_value(setup.config["provider"].clone())?;
    let mut statement = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
    statement.extend(serde_json::to_vec(&serde_json::json!({
        "provider_scope": setup.config["provider_scope"], "destination_id": setup.config["destination_id"],
        "final_use_scope_sha256": setup.config["final_use_scope_sha256"], "provider": typed,
    }))?);
    setup.sign_contract(&Sha256Digest::for_bytes(&statement))?;
    setup.config["provider"]["chain_workers"] = serde_json::json!(2);
    setup.write_config()?;
    assert!(
        matches!(AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path),
        Err(AgentdError::Invalid(message)) if message.contains("PoN provider contract digest mismatch"))
    );
    assert_eq!(setup.trust_requests(), 0);
    assert!(
        !fixture
            .identity
            .layout
            .automation_root()
            .join("final-use-authority")
            .exists()
    );
    setup.config["provider"]["chain_workers"] = serde_json::json!(1);
    setup.write_config()?;
    let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert!(matches!(&host.adapter, AgentdProviderEffectAdapter::Pon(_)));
    assert_eq!(
        host.authority.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    fixture.store.close().await;
    Ok(())
}
