//! Real Agentd AF_UNIX ingress, original SQLite/FinalUse and generation reopen.
//! Only the HTTP provider is mocked; this is not a native Chain/Supervisor run.
#[cfg(target_os = "linux")]
#[path = "automation_effect_packet_file_tests.rs"]
mod packet_file_tests;

use super::tests::Fixture;
use super::tests::WIRE;
use super::tests::effect_intent;
use super::tests::hex;
use super::tests::signed_final_use;
use super::*;
use anyhow::Context;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::io::AsyncWriteExt;
use tokio_util::sync::CancellationToken;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_bytes;
use wiremock::matchers::method;
use wiremock::matchers::path;

struct EffectFixture {
    base: Fixture,
    provider: MockServer,
    host_file: PathBuf,
    intent: AuthorizedEffectIntent,
    grant: SignedFinalUseGrant,
    now_ms: u64,
}

struct RunningOwner {
    client: crate::AgentdClient,
    state: Arc<crate::AgentdState>,
    host: Arc<AgentdAutomationEffectHost>,
    stop: CancellationToken,
    server: tokio::task::JoinHandle<Result<(), AgentdError>>,
    _writer: fs::File,
}

impl EffectFixture {
    async fn new() -> anyhow::Result<Self> {
        let base = Fixture::new().await?;
        let provider = MockServer::start().await;
        let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let scope = Sha256Digest::for_bytes(b"ordinary-effect-resume-scope");
        let intent = effect_intent(&scope);
        let contract_signer = SigningKey::from_bytes(&[23; 32]);
        let signer = SigningKey::from_bytes(&[29; 32]);
        let grant = signed_final_use(&intent, now_ms, &signer)?;
        let config = HttpProviderEffectConfig {
            dispatch_url: format!("{}/dispatch", provider.uri()),
            lookup_url_template: format!("{}/status/{{key}}", provider.uri()),
            headers: HeaderMap::new(),
            timeout: Duration::from_secs(5),
            contract_id: "ordinary-effect-resume-contract".to_owned(),
            attestation: None,
        };
        let digest = config.contract_sha256().map_err(anyhow::Error::msg)?;
        let signature = contract_signer
            .sign(&HttpProviderEffectContractAttestation::statement_for(
                &config.contract_id,
                &digest,
                1,
            ))
            .to_bytes();
        let revocations = base
            .identity
            .layout
            .automation_root()
            .join("resume-revocations.json");
        fs::write(
            &revocations,
            serde_json::to_vec(&FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            })?,
        )?;
        fs::set_permissions(&revocations, fs::Permissions::from_mode(0o600))?;
        let host_file = base
            .identity
            .layout
            .automation_root()
            .join("resume-host.json");
        fs::write(
            &host_file,
            serde_json::to_vec(&serde_json::json!({
                "schema_version": 1, "provider_scope": "provider/fixture-v1", "destination_id": "provider:fixture",
                "final_use_scope_sha256": scope.as_str(), "dispatch_url": config.dispatch_url,
                "lookup_url_template": config.lookup_url_template, "headers": {}, "timeout_ms": 5000,
                "contract_id": config.contract_id, "contract_sha256": digest.as_str(), "contract_authority_epoch": 1,
                "contract_signature_hex": hex(&signature), "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
                "final_use_signer_id": "automation-security-owner", "final_use_verifying_key_hex": hex(&signer.verifying_key().to_bytes()),
                "final_use_revocations_file": revocations,
            }))?,
        )?;
        fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600))?;
        Ok(Self {
            base,
            provider,
            host_file,
            intent,
            grant,
            now_ms,
        })
    }

    fn fleet(&self) -> anyhow::Result<FleetRegistry> {
        Ok(FleetRegistry::open_existing(HeptaFleetRoot::parse(
            self.base.identity.fleet_root.clone(),
        )?)?)
    }

    async fn start(&self, generation: u64) -> anyhow::Result<RunningOwner> {
        let original = &self.base.identity;
        let config = crate::AgentdConfig::load(
            original.fleet_root.clone(),
            original.agent_id.clone(),
            generation,
            original.home_root.clone(),
            original.run_root.clone(),
            original.home_root.clone(),
            original.workspace.clone(),
        )?;
        let (identity, registry, writer) = config.into_parts();
        let store = AutomationStore::open(&identity.layout).await?;
        let cognitive = Arc::new(codex_hepta_memory::CognitiveStore::open(&identity.layout).await?);
        let host = Arc::new(AgentdAutomationEffectHost::open(
            &identity,
            &self.host_file,
        )?);
        let client = crate::AgentdClient::new(
            identity.control_socket.clone(),
            identity.agent_id.clone(),
            generation,
        )?;
        let state = Arc::new(crate::AgentdState::new(identity.clone(), registry, 16)?);
        state.attach_cognitive_store(cognitive)?;
        state.attach_automation_store(store)?;
        state.attach_automation_effect_host(Arc::clone(&host))?;
        state.mark_runtime_prerequisites_ready()?;
        self.fleet()?.compare_and_transition(
            &identity.agent_id,
            generation,
            AgentLifecycle::Running,
        )?;
        state.mark_app_server_ready()?;
        let stop = CancellationToken::new();
        let server = crate::AgentdControlServer::bind(
            identity.control_socket,
            Arc::clone(&state),
            stop.clone(),
        )
        .await?;
        Ok(RunningOwner {
            client,
            state,
            host,
            stop,
            server: tokio::spawn(server.run()),
            _writer: writer,
        })
    }

    async fn acknowledge(&self) -> anyhow::Result<()> {
        let key = ProviderEffectKey::for_operation(
            "provider/fixture-v1",
            &self.intent.run_id,
            &self.intent.step_id,
        )
        .map_err(|error| anyhow::anyhow!("provider key: {error:?}"))?;
        Mock::given(method("GET")).respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "effect_key": key.as_str(), "payload_sha256": self.intent.payload_digest.as_str(),
            "provider_operation_id_sha256": Sha256Digest::for_bytes(b"provider-operation").as_str(), "status": "completed",
        }))).mount(&self.provider).await;
        Ok(())
    }
}

impl RunningOwner {
    async fn stop(self) -> anyhow::Result<()> {
        self.stop.cancel();
        self.server.await??;
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ordinary_effect_legacy_plan_keeps_absent_length_and_inline_resume() -> anyhow::Result<()> {
    let fixture = EffectFixture::new().await?;
    let key = ProviderEffectKey::for_operation("provider/fixture-v1", &fixture.intent.run_id, "effect")
        .map_err(|error| anyhow::anyhow!("provider key: {error:?}"))?;
    let original = serde_json::json!({"intent":fixture.intent,"provider_effect_key":key,
        "packet_path":"/host/legacy.packet","final_use_grant":fixture.grant,"command_id":"dispatch"});
    let legacy: crate::CognitiveUpgradeEffectV1 = serde_json::from_value(original.clone())?;
    assert_eq!(legacy.packet_byte_length, None);
    assert_eq!(serde_json::to_value(&legacy)?, original);
    Mock::given(method("POST")).and(path("/dispatch")).and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(503)).expect(1).mount(&fixture.provider).await;
    fixture.fleet()?.compare_and_transition(&fixture.base.identity.agent_id, 0, AgentLifecycle::Starting)?;
    let owner = fixture.start(1).await?;
    assert!(!owner.client.capabilities().await?.capabilities.iter().any(|cap| cap.id == crate::AUTOMATION_PON_PACKET_FILE_CAPABILITY));
    let result = owner.client.automation_resume_effect(legacy.intent, WIRE, legacy.final_use_grant, legacy.command_id).await?;
    assert_eq!(result.state, crate::AutomationEffectReconcileState::Indeterminate);
    assert_eq!(owner.host.authority.capacity()?.used_nonces, 1);
    owner.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ordinary_effect_queue_budget_refuses_before_prepare_and_can_retry() -> anyhow::Result<()> {
    let fixture = EffectFixture::new().await?;
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(503))
        .expect(1)
        .mount(&fixture.provider)
        .await;
    fixture.fleet()?.compare_and_transition(
        &fixture.base.identity.agent_id,
        0,
        AgentLifecycle::Starting,
    )?;
    let owner = fixture.start(1).await?;
    let serial = owner.host.resume_serial.lock().await;
    // The original provider is bounded at five seconds. The server-private
    // budget initially covers it and the one-second cleanup reserve; queueing
    // then removes that reserve before any preparation, nonce or contact.
    let deadline = Instant::now() + Duration::from_millis(6_050);
    let resume = owner.host.resume_effect(
        &fixture.base.store,
        &owner.state,
        AgentdEffectResumeInput {
            intent: &fixture.intent,
            material: AgentdEffectMaterial::Inline(WIRE),
            signed_grant: &fixture.grant,
            command_id: "dispatch",
            deadline,
        },
    );
    let release = async {
        tokio::time::sleep(Duration::from_millis(100)).await;
        drop(serial);
    };
    let (result, ()) = tokio::join!(resume, release);
    assert!(result.is_err());
    assert!(
        fixture
            .base
            .store
            .taskflow_run(&fixture.intent.run_id)
            .await?
            .is_none()
    );
    assert!(
        fixture
            .base
            .store
            .authorized_taskflow_effect_attempt(&fixture.intent.run_id, "effect", 1)
            .await?
            .is_none()
    );
    assert_eq!(owner.host.authority.capacity()?.used_nonces, 0);
    assert!(
        fixture
            .provider
            .received_requests()
            .await
            .context("provider observations")?
            .is_empty()
    );
    let result = owner
        .client
        .automation_resume_effect(
            fixture.intent.clone(),
            WIRE,
            fixture.grant.clone(),
            "dispatch".to_owned(),
        )
        .await?;
    assert_eq!(
        result,
        crate::AutomationEffectReconcileSnapshot {
            state: crate::AutomationEffectReconcileState::Indeterminate,
            effect: None,
            chain: None,
        }
    );
    assert_eq!(owner.host.authority.capacity()?.used_nonces, 1);
    owner.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ordinary_effect_rpc_prepares_once_and_recovers_unknown_after_reopen() -> anyhow::Result<()>
{
    let fixture = EffectFixture::new().await?;
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(503))
        .expect(1)
        .mount(&fixture.provider)
        .await;
    fixture.fleet()?.compare_and_transition(
        &fixture.base.identity.agent_id,
        0,
        AgentLifecycle::Starting,
    )?;
    let first = fixture.start(1).await?;
    let pending = crate::AutomationEffectReconcileSnapshot {
        state: crate::AutomationEffectReconcileState::Indeterminate,
        effect: None,
        chain: None,
    };
    assert_eq!(
        first
            .client
            .automation_resume_effect(
                fixture.intent.clone(),
                WIRE,
                fixture.grant.clone(),
                "dispatch".to_owned()
            )
            .await?,
        pending
    );
    assert_eq!(
        first
            .client
            .automation_resume_effect(
                fixture.intent.clone(),
                WIRE,
                fixture.grant.clone(),
                "dispatch".to_owned()
            )
            .await?,
        pending
    );
    assert!(
        first
            .client
            .automation_resume_effect(
                fixture.intent.clone(),
                WIRE,
                fixture.grant.clone(),
                "wrong-command".to_owned()
            )
            .await
            .is_err()
    );
    assert!(
        first
            .client
            .automation_resume_effect(
                fixture.intent.clone(),
                b"wrong-wire",
                fixture.grant.clone(),
                "dispatch".to_owned()
            )
            .await
            .is_err()
    );
    let before = fixture
        .base
        .store
        .authorized_taskflow_effect_attempt(&fixture.intent.run_id, "effect", 1)
        .await?
        .context("durable attempt")?;
    assert_eq!(first.host.authority.capacity()?.used_nonces, 1);
    let run = fixture
        .base
        .store
        .taskflow_run(&fixture.intent.run_id)
        .await?
        .context("original run")?;
    let historical_fence = first.host.current_fence(&run, fixture.now_ms)?;
    first.stop().await?;
    for (generation, lifecycle) in [
        (2, AgentLifecycle::Draining),
        (3, AgentLifecycle::Stopped),
        (4, AgentLifecycle::Starting),
    ] {
        fixture.fleet()?.compare_and_transition(
            &fixture.base.identity.agent_id,
            generation,
            lifecycle,
        )?;
    }
    fixture.acknowledge().await?;
    let reopened = fixture.start(5).await?;
    reopened.state.require_effect_ready()?;
    // Explicit owner timestamp exercises receipt-bound recovery after the old
    // lease, without sleeping or changing a database row or clock environment.
    let recovered = reopened
        .host
        .reconcile_pending(
            &fixture.base.store,
            &before,
            &historical_fence,
            fixture.now_ms + 120_000,
        )
        .await?;
    let AgentdAutomationEffectReconcileOutcome::Observed { receipt, chain } = recovered else {
        anyhow::bail!("registered provider Ack was not recovered");
    };
    assert!(chain.is_none());
    let expected = crate::AutomationEffectReconcileSnapshot {
        state: crate::AutomationEffectReconcileState::Terminal,
        effect: Some(crate::AutomationEffectSnapshot {
            run_id: fixture.intent.run_id.clone(),
            step_id: "effect".to_owned(),
            attempt: 1,
            event_seq: receipt.event_seq,
            receipt_digest: receipt.receipt_digest.clone(),
            observation: crate::AutomationEffectObservation::Succeeded,
        }),
        chain: None,
    };
    assert_eq!(
        reopened
            .client
            .automation_resume_effect(
                fixture.intent.clone(),
                WIRE,
                fixture.grant.clone(),
                "dispatch".to_owned()
            )
            .await?,
        expected
    );
    assert_eq!(
        reopened
            .client
            .automation_observe_effect(fixture.intent.clone(), "dispatch".to_owned())
            .await?,
        expected
    );
    assert_eq!(
        fixture
            .base
            .store
            .authorized_taskflow_effect_attempt(&fixture.intent.run_id, "effect", 1)
            .await?,
        Some(before)
    );
    assert_eq!(reopened.host.authority.capacity()?.used_nonces, 1);
    reopened.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ordinary_effect_disconnected_reply_resumes_without_second_dispatch() -> anyhow::Result<()>
{
    let fixture = EffectFixture::new().await?;
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(503).set_delay(Duration::from_secs(3)))
        .expect(1)
        .mount(&fixture.provider)
        .await;
    fixture.fleet()?.compare_and_transition(
        &fixture.base.identity.agent_id,
        0,
        AgentLifecycle::Starting,
    )?;
    let owner = fixture.start(1).await?;
    let mut transport =
        codex_uds::UnixStream::connect(&fixture.base.identity.control_socket).await?;
    let request = crate::AgentdRequest::automation_resume_effect(
        1,
        1,
        fixture.intent.clone(),
        hex(WIRE),
        fixture.grant.clone(),
        "dispatch".to_owned(),
    );
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    transport.write_all(&bytes).await?;
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if fixture
                .base
                .store
                .authorized_taskflow_effect_attempt(&fixture.intent.run_id, "effect", 1)
                .await?
                .is_some()
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    drop(transport);
    fixture.acknowledge().await?;
    let result = owner
        .client
        .automation_resume_effect(
            fixture.intent.clone(),
            WIRE,
            fixture.grant.clone(),
            "dispatch".to_owned(),
        )
        .await?;
    assert_eq!(
        result.state,
        crate::AutomationEffectReconcileState::Terminal
    );
    assert_eq!(
        result.effect.context("terminal effect")?.observation,
        crate::AutomationEffectObservation::Succeeded
    );
    assert_eq!(owner.host.authority.capacity()?.used_nonces, 1);
    owner.stop().await?;
    Ok(())
}
