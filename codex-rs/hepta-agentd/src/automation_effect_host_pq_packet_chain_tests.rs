//! Real control socket -> PQ effect owner -> exact native Chain packet.
//! Fleet, storage, control and effect owners are real. App Server readiness is
//! an explicit component fixture; this does not execute Agentd startup Evidence
//! recovery, launch an App Server, or qualify independent trust deployment.

use super::super::super::pon_process::chain_tests::Chain;
use super::*;
use anyhow::Context;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio_util::sync::CancellationToken;

#[path = "automation_effect_host_pq_packet_rollback_tests.rs"]
mod rollback_tests;

struct ControlFixture {
    client: crate::AgentdClient,
    cancellation: CancellationToken,
    task: Option<tokio::task::JoinHandle<Result<(), crate::AgentdError>>>,
}

impl ControlFixture {
    async fn start(
        fixture: &Fixture,
        store: AutomationStore,
        host: Arc<AgentdAutomationEffectHost>,
    ) -> anyhow::Result<Self> {
        let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(
            fixture.identity.fleet_root.clone(),
        )?)?;
        let current = registry.load_agent(&fixture.identity.agent_id)?;
        if current.lifecycle.generation == 0 {
            registry.compare_and_transition(
                &fixture.identity.agent_id,
                0,
                AgentLifecycle::Starting,
            )?;
            registry.compare_and_transition(
                &fixture.identity.agent_id,
                1,
                AgentLifecycle::Running,
            )?;
        } else {
            anyhow::ensure!(current.lifecycle.lifecycle == AgentLifecycle::Running);
        }
        let state = Arc::new(crate::AgentdState::new(
            fixture.identity.clone(),
            registry,
            16,
        )?);
        state.attach_automation_store(store)?;
        state.attach_automation_effect_host(host)?;
        let cognitive =
            codex_hepta_cognitive_store::DurableCognitiveStore::open(&fixture.identity.layout)
                .await?;
        state.attach_cognitive_store(Arc::new(cognitive))?;
        state.refresh_generation()?;
        state.mark_runtime_prerequisites_ready()?;
        // Component readiness fixture only. No fabricated Evidence admission.
        state.mark_app_server_ready()?;
        let cancellation = CancellationToken::new();
        let server = crate::AgentdControlServer::bind(
            fixture.identity.control_socket.clone(),
            state,
            cancellation.clone(),
        )
        .await?;
        Ok(Self {
            client: crate::AgentdClient::new(
                fixture.identity.control_socket.clone(),
                fixture.identity.agent_id.clone(),
                fixture.identity.spawn_generation,
            )?,
            cancellation,
            task: Some(tokio::spawn(server.run())),
        })
    }

    async fn packet(
        &self,
        intent: &AuthorizedEffectIntent,
        wire: &[u8],
        grant: &SignedFinalUseGrant,
        command: &str,
    ) -> Result<crate::AutomationEffectSnapshot, crate::AgentdError> {
        self.client
            .automation_execute_effect_packet_v1(
                intent.clone(),
                wire,
                grant.clone(),
                command.to_string(),
            )
            .await
    }

    async fn stop(mut self) -> anyhow::Result<()> {
        self.cancellation.cancel();
        tokio::time::timeout(
            Duration::from_secs(2),
            self.task.take().expect("owned server"),
        )
        .await???;
        Ok(())
    }
}

impl Drop for ControlFixture {
    fn drop(&mut self) {
        self.cancellation.cancel();
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact Chain release binary; selected by paired native CI"]
async fn real_chain_pq_packet_v1_control_socket_preserves_full_packet_and_offline_receipt()
-> anyhow::Result<()> {
    let source = std::env::var("HEPTA_PON_CHAIN_SOURCE")?;
    anyhow::ensure!(
        source.len() == 40
            && source
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "missing exact Chain source identity"
    );
    let binary = PathBuf::from(std::env::var("HEPTA_PON_CHAIN_BINARY")?).canonicalize()?;
    let digest = Sha256Digest::parse(std::env::var("HEPTA_PON_CHAIN_SHA256")?)
        .map_err(anyhow::Error::msg)?;
    assert_eq!(Sha256Digest::for_bytes(&fs::read(&binary)?), digest);
    let genesis_time = SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_secs()
        .checked_sub(3600)
        .context("native Chain fixture clock")?;
    for backend in ["legacy-v2", "authenticated-v1"] {
        let fixture = Fixture::new().await?;
        let chain_root = tempfile::tempdir()?;
        let root = chain_root.path().canonicalize()?;
        let namespace = root.join("receiver");
        let chain = Chain {
            binary: binary.clone(),
            digest: digest.clone(),
            genesis_time,
            backend,
        };
        chain.call("status", &namespace, &[]).await?;
        let wire = chain
            .packet(
                "make",
                &namespace,
                &root.join("first.packet"),
                genesis_time + 10,
            )
            .await?;
        anyhow::ensure!(
            wire.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES
                && wire.len() <= crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES,
            "native packet must exercise the separate packet-v1 range: {} bytes",
            wire.len()
        );
        let scope = Sha256Digest::for_bytes(b"pq-packet-control-real-chain");
        let mut setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
        setup.config["contract_id"] = serde_json::json!("pq-packet-control-chain");
        setup.config["provider"] = serde_json::json!({
            "provider_kind": "trillionnium-pon-local-v1",
            "chain_binary": binary, "chain_binary_sha256": digest.as_str(),
            "chain_store": namespace, "chain_state_backend": backend,
            "chain_genesis_time": genesis_time, "chain_evaluation_policy": "legacy-first-two-v3",
            "chain_task_profile": "legacy-task-v1", "chain_model_profile": "linear-expert-dev-v1",
            "chain_workers": 1, "chain_min_confirmation_depth": 1,
            "chain_min_confirmation_work_depth_hex": format!("{}02", "00".repeat(63)),
            "timeout_ms": 30_000,
        });
        let provider: ProviderConfig = serde_json::from_value(setup.config["provider"].clone())?;
        let mut contract = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
        contract.extend(serde_json::to_vec(&serde_json::json!({
            "provider_scope": setup.config["provider_scope"], "destination_id": setup.config["destination_id"],
            "final_use_scope_sha256": setup.config["final_use_scope_sha256"], "provider": provider,
        }))?);
        setup.sign_contract(&Sha256Digest::for_bytes(&contract))?;
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        setup.now.store(now, Ordering::SeqCst);
        setup.publish_feed(&setup.feed(setup.head.clone(), now - 1000, now + 60_000)?)?;
        let mut intent = effect_intent(&scope);
        intent.payload_digest = Sha256Digest::for_bytes(&wire);
        prepare_effect(&fixture, now.saturating_sub(10), &intent).await?;
        let grant = setup.grant_at(&intent, now - 1000, now + 30_000)?;
        let host = Arc::new(AgentdAutomationEffectHost::open(
            &fixture.identity,
            &setup.config_path,
        )?);
        assert_eq!(
            host.authority.authentication_profile(),
            FinalUseAuthenticationProfile::MlDsa65V2
        );
        let control =
            ControlFixture::start(&fixture, fixture.store.clone(), Arc::clone(&host)).await?;
        let command = "pq-packet-control-dispatch";
        // Original inline host/client limits still refuse these exact bytes.
        let inline = host
            .execute(&fixture.store, &intent, &wire, &grant, command, now)
            .await
            .unwrap_err();
        assert!(inline.to_string().contains("too large"), "{inline}");
        let inline = control
            .client
            .automation_execute_effect(intent.clone(), &wire, grant.clone(), command.into())
            .await
            .unwrap_err();
        assert!(inline.to_string().contains("too large"), "{inline}");
        // A complete packet through the real socket cannot skip PQ signing.
        let mut invalid = grant.clone();
        invalid.signature[0] ^= 1;
        let refused = control
            .packet(&intent, &wire, &invalid, command)
            .await
            .unwrap_err();
        assert!(
            refused.to_string().contains("InvalidSignature"),
            "{refused}"
        );
        assert_eq!(host.authority.capacity()?.used_nonces, 0);
        assert!(fixture.store.authorized_taskflow_effect_attempt(
            &intent.run_id, &intent.step_id, intent.attempt,
        ).await?.is_none());
        let key = ProviderEffectKey::for_taskflow_v2(
            "provider/fixture-v1",
            &fixture.identity.agent_id,
            &intent.run_id,
            &intent.step_id,
        )
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
        let provider_intent = ProviderEffectIntent::new(key.clone(), intent.payload_digest.clone());
        let before = host
            .adapter
            .current_chain_observation(&provider_intent, Some(&wire))
            .await
            .context("native pre-dispatch observation")?;
        assert!(!before.stored_exact);
        let receipt = control.packet(&intent, &wire, &grant, command).await?;
        assert_eq!(
            receipt.observation,
            crate::AutomationEffectObservation::Succeeded
        );
        let durable = fixture
            .store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
            .context("durable packet attempt")?;
        assert_eq!(durable.owner_agent_id, fixture.identity.agent_id);
        assert_eq!(durable.intent_digest, intent.digest()?);
        assert_eq!(durable.payload_digest, intent.payload_digest);
        assert_eq!(durable.provider_effect_key.as_ref(), Some(&key));
        assert_eq!(durable.wire_payload.as_deref(), Some(wire.as_slice()));
        let original = fixture
            .store
            .read_authorized_taskflow_effect_receipt(&intent, command)
            .await?
            .context("original terminal receipt")?;
        assert_eq!(receipt.run_id, original.run_id);
        assert_eq!(receipt.step_id, original.step_id);
        assert_eq!(receipt.attempt, original.attempt);
        assert_eq!(receipt.event_seq, original.event_seq);
        assert_eq!(receipt.receipt_digest, original.receipt_digest);
        let included = host
            .adapter
            .current_chain_observation(&provider_intent, Some(&wire))
            .await
            .context("native post-dispatch observation")?;
        assert!(included.stored_exact && included.active_chain_member);
        assert_eq!(included.block_id, before.block_id);
        assert_eq!(included.active_depth, Some(0));
        assert_eq!(included.provider_effect_key.as_deref(), Some(key.as_str()));
        assert_eq!(
            included.payload_sha256.as_deref(),
            Some(intent.payload_digest.as_str())
        );
        assert!(!included.confirmation_policy_satisfied);
        assert!(!included.finality_authority && !included.execution_authority);
        let mut block_binding = b"trillionnium.pon.block.v1\0".to_vec();
        block_binding.extend_from_slice(before.block_id.as_bytes());
        let expected = AuthorizedEffectProviderReceipt::from_provider_ack(
            ProviderEffectAck::new(
                key,
                intent.payload_digest.clone(),
                Sha256Digest::for_bytes(&block_binding),
                ProviderEffectAckStatus::Completed,
            ),
            ProviderEffectAckSource::DispatchResponse,
        );
        assert_eq!(
            receipt.receipt_digest.as_ref(),
            Some(&expected.receipt_digest)
        );
        let consumed = host.authority.frontier()?;
        assert_eq!(host.authority.capacity()?.used_nonces, 1);
        assert_eq!(
            serde_json::from_slice::<FinalUseFrontier>(&fs::read(
                setup.root.path().join("frontier.json")
            )?,)?,
            consumed
        );
        control.stop().await?;
        // Response delivery does not prove a detached connection released its
        // owner. Require that release before reopening the original storage.
        tokio::time::timeout(Duration::from_secs(2), async {
            while Arc::strong_count(&host) != 1 {
                tokio::task::yield_now().await;
            }
        })
        .await?;
        fixture.store.close().await;
        drop(host);
        let store = AutomationStore::open(&fixture.identity.layout).await?;
        let reopened = Arc::new(AgentdAutomationEffectHost::open(
            &fixture.identity,
            &setup.config_path,
        )?);
        assert_eq!(reopened.authority.frontier()?, consumed);
        let control = ControlFixture::start(&fixture, store.clone(), Arc::clone(&reopened)).await?;
        // Move only this test's disposable provider namespace after ordinary
        // loader validation. Stop trust services; retain the original binary.
        fs::rename(&namespace, root.join("retained-receiver"))?;
        setup.now.store(now + 90_000, Ordering::SeqCst);
        drop(setup);
        let replay = control.packet(&intent, &wire, &grant, command).await?;
        assert_eq!(replay, receipt);
        assert_eq!(
            store
                .read_authorized_taskflow_effect_receipt(&intent, command,)
                .await?,
            Some(original)
        );
        assert_eq!(reopened.authority.capacity()?.used_nonces, 1);
        assert!(
            !namespace.exists(),
            "offline readback must not recreate the provider store"
        );
        assert!(
            control
                .packet(&intent, &wire, &grant, "changed-command")
                .await
                .is_err()
        );
        control.stop().await?;
        store.close().await;
        println!(
            "{}",
            serde_json::json!({
                "case":"pq-packet-v1-control-socket-real-chain", "backend":backend,
                "chain_source":source, "chain_binary_sha256":digest.as_str(), "wire_bytes":wire.len(),
                "inline_limit_unchanged":true, "server_io_timeout_configuration_ms":2000,
                "provider_timeout_configuration_ms":30000, "provider_elapsed_time_measured":false,
                "receipt":receipt, "used_nonces":1, "restart_offline_exact_receipt":true,
                "readiness_fixture_only":true, "app_server_launched":false, "evidence_startup_executed":false,
                "chain_task_profile_is_pq":false, "independent_trust_deployment_qualified":false,
                "process_start_count_measured":false, "energy_measured":false, "production_activation":false,
            })
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_pq_http_does_not_advertise_or_accept_packet_v1() -> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"pq-http-no-packet-v1");
    let setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
    let host = Arc::new(AgentdAutomationEffectHost::open(
        &fixture.identity,
        &setup.config_path,
    )?);
    let control = ControlFixture::start(&fixture, fixture.store.clone(), Arc::clone(&host)).await?;
    let capabilities = control.client.capabilities().await?;
    assert!(
        capabilities
            .capabilities
            .iter()
            .any(|capability| capability.id == crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT)
    );
    assert!(
        !capabilities
            .capabilities
            .iter()
            .any(|capability| capability.id
                == crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1)
    );
    let intent = effect_intent(&scope);
    let grant = setup.grant(&intent, NOW + 30_000)?;
    let error = control
        .packet(&intent, WIRE, &grant, "http-cannot-gain-packet")
        .await
        .unwrap_err();
    assert!(error.to_string().contains("does not advertise"), "{error}");
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert!(
        fixture
            .store
            .pending_authorized_taskflow_effects(8)
            .await?
            .is_empty()
    );
    control.stop().await?;
    fixture.store.close().await;
    Ok(())
}

#[path = "automation_effect_host_pq_npq6_chain_tests.rs"]
mod npq6_chain_tests;
