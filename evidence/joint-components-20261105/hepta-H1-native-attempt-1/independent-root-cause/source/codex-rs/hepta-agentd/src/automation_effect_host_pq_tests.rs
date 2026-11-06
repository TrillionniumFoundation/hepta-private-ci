//! Native composition controls use actual ML-DSA, Unix peer credentials, an
//! independent in-test CAS service and loopback HTTP. They do not qualify key
//! custody, real-provider crash windows, WANs or a complete Agentd installation.
use super::*;
use codex_hepta_fleet::AgentLifecycle;
use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
use codex_model_provider::PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER;
use ed25519_dalek::Signer;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;

#[path = "automation_effect_host_pq_test_support.rs"]
mod support;
use support::*;

#[path = "automation_effect_host_pq_lost_ack.rs"]
mod lost_ack;
use lost_ack::LostAckProvider;

fn namespace(fixture: &PqFixture) -> PathBuf {
    fixture
        .owner
        .identity
        .layout
        .automation_root()
        .join("final-use-authority-pq-v2")
}

fn archive_policy(fixture: &PqFixture, name: &str) -> anyhow::Result<Value> {
    let bytes = fs::read(&fixture.host_path)?;
    let path = fixture.owner.identity.layout.automation_root().join(name);
    fs::write(&path, &bytes)?;
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    Ok(serde_json::json!({"path":path,"sha256":Sha256Digest::for_bytes(&bytes)}))
}

fn current_head(
    host: &AgentdAutomationEffectHost,
    revision: u64,
) -> anyhow::Result<FinalUseRevocations> {
    let mut head = host.authority.revocation_head()?;
    head.revision = revision;
    Ok(head)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_loader_denies_classical_schema_and_contract_or_policy_substitution()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let fixture = PqFixture::new(&server.uri()).await?;
    for schema in [1, 3] {
        write_private(
            &fixture.host_path,
            &serde_json::json!({"schema_version":schema}),
        )?;
        let error = fixture.open().unwrap_err();
        assert!(error.to_string().contains("explicit PQ host schema 4"));
        assert!(!namespace(&fixture).exists());
    }
    let mut changes = Vec::new();
    let mut config = fixture.config.clone();
    config["provider"]["dispatch_url"] = serde_json::json!(format!("{}/other", server.uri()));
    changes.push(config);
    let mut config = fixture.config.clone();
    config["provider"]["headers"] = serde_json::json!({"authorization":"another-credential"});
    changes.push(config);
    let mut config = fixture.config.clone();
    config["spawn_generation"] = serde_json::json!(2);
    changes.push(config);
    let mut config = fixture.config.clone();
    config["contract_signature"] = serde_json::json!(vec![0; 64]);
    changes.push(config);
    let mut config = fixture.config.clone();
    config["authority"]["issuer_keys"] = config["authority"]["revocation_keys"].clone();
    changes.push(config);
    let mut config = fixture.config.clone();
    config["authority"]["external_clock"] = config["authority"]["external_frontier"].clone();
    changes.push(config);
    for changed in changes {
        write_private(&fixture.host_path, &changed)?;
        assert!(fixture.open().is_err());
        assert!(!namespace(&fixture).exists());
    }
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn initial_feed_is_authenticated_before_any_local_authority_or_frontier_write()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let fixture = PqFixture::new(&server.uri()).await?;
    let original = fs::read(&fixture.feed_path)?;
    let mut signed: SignedFinalUseRevocationUpdate = serde_json::from_slice(&original)?;
    signed.signature[0] ^= 1;
    write_private(&fixture.feed_path, &signed)?;
    assert!(fixture.open().is_err());
    assert!(!namespace(&fixture).exists());
    let head =
        serde_json::from_value::<FinalUseRevocations>(fixture.config["authority"]["head"].clone())?;
    fixture.write_feed(head.clone(), fixture.now)?;
    assert!(fixture.open().is_err());
    assert!(!namespace(&fixture).exists());
    let mut changed = head;
    changed.revision += 1;
    fixture.write_feed(changed, fixture.now + 60_000)?;
    assert!(fixture.open().is_err());
    assert!(!namespace(&fixture).exists());
    assert_eq!(fixture.frontier.cas_count.load(Ordering::SeqCst), 0);
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn current_clock_frontier_and_pq_grant_are_mandatory_before_contact() -> anyhow::Result<()> {
    let server = MockServer::start().await;
    let fixture = PqFixture::new(&server.uri()).await?;
    let host = fixture.open()?;
    let (state, _) = fixture.state(&host).await?;
    let intent = effect_intent(&fixture.scope()?);
    prepare_effect(&fixture.owner, fixture.now, &intent).await?;
    let valid = fixture.grant(&intent)?;
    let mut invalid_grants = Vec::new();
    let mut classic = valid.clone();
    classic.grant.schema_version = 1;
    classic.signature = ed25519_dalek::SigningKey::from_bytes(&[91; 32])
        .sign(&classic.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    invalid_grants.push(classic);
    let mut corrupt = valid.clone();
    corrupt.signature[0] ^= 1;
    invalid_grants.push(corrupt);
    let mut stale = valid.clone();
    stale.grant.authority_epoch = 8;
    stale.signature = fixture
        .issuer
        .sign_exact_message(&stale.grant.signing_bytes()?)?
        .to_vec();
    invalid_grants.push(stale);
    let mut over_lease = valid.clone();
    over_lease.grant.expires_at_unix_ms = fixture.now + 60_001;
    over_lease.signature = fixture
        .issuer
        .sign_exact_message(&over_lease.grant.signing_bytes()?)?
        .to_vec();
    invalid_grants.push(over_lease);
    for signed in invalid_grants {
        assert!(
            host.execute_ordinary(
                &state,
                &fixture.owner.store,
                &intent,
                WIRE,
                &signed,
                "denied-grant"
            )
            .await
            .is_err()
        );
    }
    fixture.clock.available.store(false, Ordering::SeqCst);
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &valid,
            "denied-clock"
        )
        .await
        .is_err()
    );
    fixture.clock.available.store(true, Ordering::SeqCst);
    let before = *fixture.frontier.frontier.lock().unwrap();
    fixture.frontier.frontier.lock().unwrap().state_sha256[0] ^= 1;
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &valid,
            "denied-frontier"
        )
        .await
        .is_err()
    );
    *fixture.frontier.frontier.lock().unwrap() = before;
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn revoked_equal_number_drift_expired_feed_and_new_epoch_do_not_contact_provider()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let fixture = PqFixture::new(&server.uri()).await?;
    let host = fixture.open()?;
    let (state, _) = fixture.state(&host).await?;
    let intent = effect_intent(&fixture.scope()?);
    prepare_effect(&fixture.owner, fixture.now, &intent).await?;
    let grant = fixture.grant(&intent)?;
    let mut revoked = current_head(&host, 2)?;
    revoked
        .revoked_grant_ids
        .insert(grant.grant.grant_id.clone());
    fixture.write_feed(revoked.clone(), fixture.now + 60_000)?;
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &grant,
            "revoked"
        )
        .await
        .is_err()
    );
    let mut removed = revoked.clone();
    removed.revoked_grant_ids.clear();
    fixture.write_feed(removed, fixture.now + 60_000)?;
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &grant,
            "same-numbers"
        )
        .await
        .is_err()
    );
    assert_eq!(host.authority.revocation_head()?, revoked);
    fixture.write_feed(revoked, fixture.now)?;
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &grant,
            "expired"
        )
        .await
        .is_err()
    );
    let mut next = current_head(&host, 3)?;
    next.authority_epoch = 10;
    fixture.write_feed(next.clone(), fixture.now + 60_000)?;
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &grant,
            "old-contract-epoch"
        )
        .await
        .is_err()
    );
    assert_eq!(host.authority.revocation_head()?, next);
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn generation_change_after_store_await_refuses_contact_and_keeps_consumed_nonce()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let fixture = PqFixture::new(&server.uri()).await?;
    let host = fixture.open()?;
    let (state, registry) = fixture.state(&host).await?;
    let intent = effect_intent(&fixture.scope()?);
    prepare_effect(&fixture.owner, fixture.now, &intent).await?;
    let grant = fixture.grant(&intent)?;
    let calls = AtomicUsize::new(0);
    let boundary = || {
        if calls.fetch_add(1, Ordering::SeqCst) == 1 {
            registry
                .compare_and_transition(
                    &fixture.owner.identity.agent_id,
                    2,
                    AgentLifecycle::Draining,
                )
                .map_err(invalid)?;
        }
        if !state.automation_admission_ready()? {
            return Err(invalid("test observed superseded generation"));
        }
        host.pq
            .as_ref()
            .unwrap()
            .validate_grant(&host.authority, &host.revocations_file, &grant)
    };
    let outcome = host
        .execute_at_boundary(
            EffectHostInput {
                store: &fixture.owner.store,
                intent: &intent,
                wire_payload: WIRE,
                signed_grant: &grant,
                command_id: "generation-window",
                now_ms: fixture.now + 5,
            },
            &boundary,
        )
        .await;
    assert!(outcome.is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    assert!(matches!(
        host.reconcile_at_boundary(
            &fixture.owner.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fixture.now + 6,
            &|| Err(invalid("no external authority"))
        )
        .await?,
        AgentdAutomationEffectReconcileOutcome::ProvenAbsent
    ));
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_revocation_after_store_await_obeys_active_effect_fence_and_never_sends()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let fixture = PqFixture::new(&server.uri()).await?;
    let host = fixture.open()?;
    let intent = effect_intent(&fixture.scope()?);
    prepare_effect(&fixture.owner, fixture.now, &intent).await?;
    let grant = fixture.grant(&intent)?;
    let calls = AtomicUsize::new(0);
    let mut revoked = current_head(&host, 2)?;
    revoked
        .revoked_grant_ids
        .insert(grant.grant.grant_id.clone());
    let boundary = || {
        if calls.fetch_add(1, Ordering::SeqCst) == 1 {
            fixture
                .write_feed(revoked.clone(), fixture.now + 60_000)
                .map_err(invalid)?;
        }
        host.pq
            .as_ref()
            .unwrap()
            .validate_grant(&host.authority, &host.revocations_file, &grant)
    };
    assert!(
        host.execute_at_boundary(
            EffectHostInput {
                store: &fixture.owner.store,
                intent: &intent,
                wire_payload: WIRE,
                signed_grant: &grant,
                command_id: "revocation-window",
                now_ms: fixture.now + 5
            },
            &boundary
        )
        .await
        .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    assert_eq!(host.authority.revocation_head()?.revision, 1);
    assert!(matches!(
        host.reconcile_at_boundary(
            &fixture.owner.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fixture.now + 6,
            &|| Err(invalid("no external authority"))
        )
        .await?,
        AgentdAutomationEffectReconcileOutcome::ProvenAbsent
    ));
    host.pq
        .as_ref()
        .unwrap()
        .refresh(&host.authority, &host.revocations_file)?;
    assert_eq!(host.authority.revocation_head()?, revoked);
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_dispatch_and_new_generation_recovery_keep_one_stable_operation()
-> anyhow::Result<()> {
    let provider = LostAckProvider::start()?;
    let mut fixture = PqFixture::new(&provider.uri).await?;
    let host = fixture.open()?;
    let (state, registry) = fixture.state(&host).await?;
    let intent = effect_intent(&fixture.scope()?);
    prepare_effect(&fixture.owner, fixture.now, &intent).await?;
    let grant = fixture.grant(&intent)?;
    let key = ProviderEffectKey::for_taskflow_v2(
        "provider/fixture-v1",
        &fixture.owner.identity.agent_id,
        &intent.run_id,
        &intent.step_id,
    )
    .map_err(|error| anyhow::anyhow!("provider key: {error:?}"))?;
    provider.expect(ProviderEffectIntent::new(
        key.clone(),
        intent.payload_digest.clone(),
    ))?;
    let response = state
        .response(
            1,
            1,
            crate::AgentdMethod::AutomationExecuteEffect {
                intent: intent.clone(),
                wire_payload_hex: WIRE.iter().map(|b| format!("{b:02x}")).collect(),
                signed_grant: Box::new(grant.clone()),
                command_id: "pq-ordinary-unknown".into(),
            },
        )
        .await?;
    assert!(matches!(
        response.payload,
        crate::AgentdPayload::AutomationEffect(_)
    ));
    let pending = fixture
        .owner
        .store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .unwrap();
    assert_eq!(pending.provider_effect_key, Some(key.clone()));
    assert!(pending.provider_ack.is_none());
    assert_eq!(provider.posts.load(Ordering::SeqCst), 1);
    assert_eq!(provider.applies.load(Ordering::SeqCst), 1);
    let applied: Value = serde_json::from_slice(&fs::read(&provider.record_path)?)?;
    assert_eq!(applied["effect_key"], serde_json::json!(key.as_str()));
    assert_eq!(
        applied["payload_sha256"],
        serde_json::json!(intent.payload_digest.as_str())
    );
    let reference = archive_policy(&fixture, "generation-one.json")?;
    drop(state);
    drop(host);
    fixture.owner.store.close().await;
    fixture.owner.store = AutomationStore::open(&fixture.owner.identity.layout).await?;
    registry.compare_and_transition(
        &fixture.owner.identity.agent_id,
        2,
        AgentLifecycle::Draining,
    )?;
    registry.compare_and_transition(
        &fixture.owner.identity.agent_id,
        3,
        AgentLifecycle::Stopped,
    )?;
    fixture.owner.identity.spawn_generation = 5;
    fixture.config["spawn_generation"] = serde_json::json!(5);
    fixture.sign_config()?;
    let without_history = fixture.open()?;
    assert!(without_history.provider_intent(&pending).is_err());
    drop(without_history);
    fixture.config["recovery_provider_policies"] = serde_json::json!([reference]);
    fixture.sign_config()?;
    let host = fixture.open()?;
    let (state, registry) = fixture.state(&host).await?;
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &grant,
            "old-generation-replay"
        )
        .await
        .is_err()
    );
    assert_eq!(host.provider_intent(&pending)?.key, key);
    fixture.write_feed(host.authority.revocation_head()?, fixture.now)?;
    assert!(
        host.reconcile_ordinary(
            &state,
            &fixture.owner.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fixture.now + 8
        )
        .await
        .is_err()
    );
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 0);
    fixture.write_feed(host.authority.revocation_head()?, fixture.now + 60_000)?;
    assert!(matches!(
        host.reconcile_ordinary(
            &state,
            &fixture.owner.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fixture.now + 9
        )
        .await?,
        AgentdAutomationEffectReconcileOutcome::Indeterminate
    ));
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 1);
    assert!(matches!(
        host.reconcile_ordinary(
            &state,
            &fixture.owner.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fixture.now + 10
        )
        .await?,
        AgentdAutomationEffectReconcileOutcome::Observed { .. }
    ));
    let settled = fixture
        .owner
        .store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .unwrap();
    let ack = settled
        .provider_ack
        .expect("provider operation persisted after lookup");
    assert_eq!(
        serde_json::json!(ack.provider_operation_id_sha256.as_str()),
        applied["provider_operation_id_sha256"]
    );
    assert_eq!(ack.key, key);
    let terminal = fixture
        .owner
        .store
        .read_terminal_authorized_taskflow_effect(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .unwrap();
    fixture.write_feed(host.authority.revocation_head()?, fixture.now)?;
    let local = host
        .reconcile_ordinary(
            &state,
            &fixture.owner.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fixture.now + 11,
        )
        .await?;
    let AgentdAutomationEffectReconcileOutcome::Observed { receipt, chain } = local else {
        panic!("local terminal receipt")
    };
    assert_eq!(*receipt, terminal);
    assert!(chain.is_none());
    registry.compare_and_transition(
        &fixture.owner.identity.agent_id,
        6,
        AgentLifecycle::Draining,
    )?;
    assert!(
        host.execute_ordinary(
            &state,
            &fixture.owner.store,
            &effect_intent(&fixture.scope()?),
            WIRE,
            &grant,
            "drained-owner"
        )
        .await
        .is_err()
    );
    assert_eq!(provider.posts.load(Ordering::SeqCst), 1);
    assert_eq!(provider.applies.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 2);
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn recovery_requires_current_signed_exact_historical_policy_and_same_provider()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let mut fixture = PqFixture::new(&server.uri()).await?;
    let reference = archive_policy(&fixture, "original-provider.json")?;
    fixture.config["recovery_provider_policies"] = serde_json::json!([reference.clone()]);
    fixture.sign_config()?;
    let valid = fixture.config.clone();
    fixture.config["recovery_provider_policies"][0]["sha256"] =
        serde_json::json!(Sha256Digest::for_bytes(b"other bytes"));
    fixture.sign_config()?;
    assert!(fixture.open().is_err());
    fixture.config = valid.clone();
    fixture.config["provider"]["dispatch_url"] =
        serde_json::json!(format!("{}/other", server.uri()));
    fixture.sign_config()?;
    assert!(fixture.open().is_err());
    fixture.config = valid.clone();
    fixture.config["destination_id"] = serde_json::json!("provider:other");
    fixture.sign_config()?;
    assert!(fixture.open().is_err());
    fixture.config = valid.clone();
    fixture.config["recovery_provider_policies"] = serde_json::json!(vec![reference.clone(); 9]);
    fixture.sign_config()?;
    assert!(fixture.open().is_err());
    let old_path = PathBuf::from(reference["path"].as_str().unwrap());
    let original: Value = serde_json::from_slice(&fs::read(&old_path)?)?;
    fixture.config = original.clone();
    fixture.config["agent_id"] = serde_json::json!("00000000-0000-4000-8000-000000000999");
    fixture.sign_config()?;
    fs::copy(&fixture.host_path, &old_path)?;
    fixture.config = valid.clone();
    fixture.config["recovery_provider_policies"][0]["sha256"] =
        serde_json::json!(Sha256Digest::for_bytes(&fs::read(&old_path)?));
    fixture.sign_config()?;
    assert!(fixture.open().is_err());
    for (field, replacement) in [
        ("contract_signature", serde_json::json!(vec![0; 3309])),
        (
            "final_use_scope_sha256",
            serde_json::json!(Sha256Digest::for_bytes(b"wrong scope").as_str()),
        ),
    ] {
        let mut old = original.clone();
        old[field] = replacement;
        write_private(&old_path, &old)?;
        fixture.config = valid.clone();
        fixture.config["recovery_provider_policies"][0]["sha256"] =
            serde_json::json!(Sha256Digest::for_bytes(&fs::read(&old_path)?));
        fixture.sign_config()?;
        assert!(fixture.open().is_err());
    }
    fixture.config = valid;
    fixture.config["recovery_provider_policies"][0]["sha256"] =
        serde_json::json!(Sha256Digest::for_bytes(b"not signed by current root"));
    write_private(&fixture.host_path, &fixture.config)?;
    assert!(fixture.open().is_err());
    assert!(!namespace(&fixture).exists());
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn historical_policy_does_not_connect_old_trust_services_or_follow_its_references()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let mut fixture = PqFixture::new(&server.uri()).await?;
    let current = fixture.config.clone();
    let absent = fixture
        .owner
        .identity
        .layout
        .automation_root()
        .join("deliberately-absent-policy.json");
    fixture.config["authority"]["signed_revocations_file"] = serde_json::json!(absent);
    fixture.config["authority"]["external_clock"]["socket_path"] = serde_json::json!(absent);
    fixture.config["authority"]["external_frontier"]["socket_path"] = serde_json::json!(absent);
    fixture.config["recovery_provider_policies"] = serde_json::json!([{"path":absent,"sha256":Sha256Digest::for_bytes(b"never-follow-this-reference")}]);
    fixture.sign_config()?;
    let old_scope = fixture.scope()?;
    let reference = archive_policy(&fixture, "old-services-unavailable.json")?;
    fixture.config = current;
    fixture.config["recovery_provider_policies"] = serde_json::json!([reference]);
    fixture.sign_config()?;
    let host = fixture.open()?;
    assert_eq!(host.pq.as_ref().unwrap().recovery_scopes, vec![old_scope]);
    assert!(!absent.exists());
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reconcile_rechecks_generation_after_store_await_without_reclassifying_unknown()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let fixture = PqFixture::new(&server.uri()).await?;
    let host = fixture.open()?;
    let (state, registry) = fixture.state(&host).await?;
    let intent = effect_intent(&fixture.scope()?);
    prepare_effect(&fixture.owner, fixture.now, &intent).await?;
    let grant = fixture.grant(&intent)?;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(500))
        .expect(1)
        .mount(&server)
        .await;
    let receipt = host
        .execute_ordinary(
            &state,
            &fixture.owner.store,
            &intent,
            WIRE,
            &grant,
            "already-sent",
        )
        .await?;
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let calls = AtomicUsize::new(0);
    let boundary = || {
        calls.fetch_add(1, Ordering::SeqCst);
        registry
            .compare_and_transition(
                &fixture.owner.identity.agent_id,
                2,
                AgentLifecycle::Draining,
            )
            .map_err(invalid)?;
        if !state.automation_admission_ready()? {
            return Err(invalid("reconciliation owner was superseded"));
        }
        host.pq
            .as_ref()
            .unwrap()
            .refresh(&host.authority, &host.revocations_file)
            .map(|_| ())
    };
    assert!(
        host.reconcile_at_boundary(
            &fixture.owner.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fixture.now + 10,
            &boundary
        )
        .await
        .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        fixture
            .owner
            .store
            .read_terminal_authorized_taskflow_effect(
                &intent.run_id,
                &intent.step_id,
                intent.attempt
            )
            .await?
            .is_none()
    );
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    assert_eq!(server.received_requests().await.unwrap().len(), 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pon_schema4_binds_native_binary_and_original_limits_without_running_a_node()
-> anyhow::Result<()> {
    let server = MockServer::start().await;
    let mut fixture = PqFixture::new(&server.uri()).await?;
    let root = fixture.owner.identity.layout.automation_root();
    let binary = root.join("pinned-inert-native-control");
    fs::copy("/usr/bin/true", &binary)?;
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&binary, fs::Permissions::from_mode(0o700))?;
    let store = root.join("controlled-pon-store");
    fs::create_dir(&store)?;
    fs::write(store.join("native.sqlite"), b"")?;
    fixture.config["provider"] = serde_json::json!({
        "kind":"pon","chain_binary":binary,"chain_binary_sha256":Sha256Digest::for_bytes(&fs::read(&binary)?),"chain_store":store,
        "chain_state_backend":"authenticated-v1","chain_genesis_time":1,"chain_evaluation_policy":"bounded-v1","chain_task_profile":"task-v1","chain_model_profile":"model-v1","chain_workers":1,
        "chain_min_confirmation_depth":1,"chain_min_confirmation_work_depth_hex":format!("{}01","00".repeat(63)),"timeout_ms":2000
    });
    fixture.sign_config()?;
    let valid = fixture.config.clone();
    fixture.config["provider"]["chain_workers"] = serde_json::json!(65);
    fixture.sign_config()?;
    assert!(fixture.open().is_err());
    fixture.config = valid.clone();
    fixture.config["contract_signature"] = serde_json::json!(vec![0; 64]);
    write_private(&fixture.host_path, &fixture.config)?;
    assert!(fixture.open().is_err());
    assert!(!namespace(&fixture).exists());
    fixture.config = valid;
    fixture.sign_config()?;
    let host = fixture.open()?;
    assert!(matches!(host.adapter, AgentdProviderEffectAdapter::Pon(_)));
    assert_eq!(
        host.authority.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    let denied = AtomicUsize::new(0);
    let intent = effect_intent(&fixture.scope()?);
    let pending = AuthorizedEffectPending {
        owner_agent_id: fixture.owner.identity.agent_id.clone(),
        run_id: intent.run_id.clone(),
        step_id: intent.step_id.clone(),
        attempt: 1,
        intent_digest: intent.digest()?,
        payload_digest: intent.payload_digest.clone(),
        provider_effect_key: Some(
            ProviderEffectKey::for_taskflow_v2(
                "provider/fixture-v1",
                &fixture.owner.identity.agent_id,
                &intent.run_id,
                &intent.step_id,
            )
            .map_err(|error| anyhow::anyhow!("provider key: {error:?}"))?,
        ),
        wire_payload: Some(WIRE.to_vec()),
        provider_ack: None,
        binding_digest: Sha256Digest::for_bytes(&serde_json::to_vec(&intent.final_use_binding()?)?),
        destination_id: intent.destination_id.clone(),
        authority_epoch: 9,
        grant_id: "not-an-execution-grant".into(),
        started_at_ms: fixture.now,
    };
    assert!(
        host.observe_chain_at_boundary(&pending, &|| {
            denied.fetch_add(1, Ordering::SeqCst);
            Err(invalid("optional observation is not authorized"))
        })
        .await
        .is_none()
    );
    assert_eq!(denied.load(Ordering::SeqCst), 1);
    drop(host);
    fs::write(&binary, b"changed after pin")?;
    assert!(fixture.open().is_err());
    assert_eq!(fixture.frontier.cas_count.load(Ordering::SeqCst), 0);
    assert!(server.received_requests().await.unwrap().is_empty());
    Ok(())
}
