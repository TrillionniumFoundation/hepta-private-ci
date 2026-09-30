#![cfg(unix)]

use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::bail;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AutomationEffectObservation;
use codex_hepta_agentd::AutomationEffectReconcileState;
use codex_hepta_agentd::HEPTA_AGENT_GENERATION_ENV;
use codex_hepta_agentd::HEPTA_AGENT_HOME_ENV;
use codex_hepta_agentd::HEPTA_AGENT_ID_ENV;
use codex_hepta_agentd::HEPTA_AGENT_RUN_ROOT_ENV;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HEPTA_FLEET_ROOT_ENV;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_model_provider::HttpProviderEffectConfig;
use codex_model_provider::HttpProviderEffectContractAttestation;
use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
use core_test_support::responses;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use http::HeaderMap;
use serde::Serialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;
use tokio::time::Instant;
use tokio::time::sleep;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_bytes;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52";
const RUN_ID: &str = "agentd-process-effect-run";
const STEP_ID: &str = "effect";
const COMMAND_ID: &str = "agentd-process-effect-dispatch";
const WIRE: &[u8] = b"{\"effect\":\"deliver-after-restart\"}";
const PROVIDER_SCOPE: &str = "provider/process-fixture-v1";
const DESTINATION_ID: &str = "provider:process-fixture";
const AUTHORITY_EPOCH: u64 = 9;
const PROCESS_TIMEOUT: Duration = Duration::from_secs(90);
const TRUST_WINDOW_MS: u64 = 600_000;

struct AgentProcess {
    child: Child,
    log_path: PathBuf,
}

impl AgentProcess {
    fn kill_and_wait(&mut self) -> Result<()> {
        if self.child.try_wait()?.is_none() {
            self.child.kill().context("kill Agentd process")?;
        }
        self.child.wait().context("wait for Agentd process")?;
        Ok(())
    }

    fn exited(&mut self) -> Result<Option<std::process::ExitStatus>> {
        self.child.try_wait().context("inspect Agentd process")
    }

    fn log(&self) -> String {
        fs::read_to_string(&self.log_path).unwrap_or_else(|_| "<log unavailable>".to_string())
    }
}

impl Drop for AgentProcess {
    fn drop(&mut self) {
        let _ = self.kill_and_wait();
    }
}

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time after epoch")
            .as_millis(),
    )
    .expect("time fits u64")
}

fn test_signing_key(label: &[u8]) -> SigningKey {
    let mut digest = Sha256::new();
    digest.update(b"hepta.kernel-authority.process-recovery-signing-key.v1\0");
    digest.update(label);
    let seed: [u8; 32] = digest.finalize().into();
    SigningKey::from_bytes(&seed)
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

fn write_private_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let parent = path.parent().context("private JSON has no parent")?;
    fs::create_dir_all(parent)?;
    let next = path.with_extension("next");
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .mode(0o600)
        .open(&next)
        .with_context(|| format!("open {}", next.display()))?;
    let bytes = serde_json::to_vec(value)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    fs::rename(&next, path)?;
    File::open(parent)?.sync_all()?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn definition() -> TaskFlowDefinition {
    TaskFlowDefinition::new(
        "agentd-process-effect",
        1,
        STEP_ID,
        vec![
            TaskFlowNodeSpec::effect(STEP_ID, "provider.deliver", "provider-key-v1"),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new(STEP_ID, "success"),
            TaskFlowEdgeSpec::new(STEP_ID, "failure"),
        ],
        vec!["provider.deliver".to_string()],
        Sha256Digest::for_bytes(b"agentd-process-effect-policy"),
    )
    .expect("valid process definition")
}

fn effect_intent(scope: &Sha256Digest) -> AuthorizedEffectIntent {
    AuthorizedEffectIntent {
        run_id: RUN_ID.to_string(),
        step_id: STEP_ID.to_string(),
        attempt: 1,
        operation_id: "provider.deliver".to_string(),
        subject_id: AGENT_ID.to_string(),
        destination_id: DESTINATION_ID.to_string(),
        payload_digest: Sha256Digest::for_bytes(WIRE),
        final_use_scope_digest: scope.clone(),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    }
}

async fn prepare_effect(
    store: &AutomationStore,
    agent_id: &AgentId,
    intent: &AuthorizedEffectIntent,
    now: u64,
) -> Result<()> {
    let definition = definition();
    let fence = TaskFlowFence::new(
        agent_id.clone(),
        "agentd-process-effect-owner",
        1,
        1,
        "agentd-process-effect-fence",
    )?;
    store
        .register_taskflow_definition(&definition, &fence, now)
        .await?;
    store
        .create_taskflow_run(
            &intent.run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-process-effect",
            now,
        )
        .await?;
    let claimed = store
        .claim_taskflow_run(&intent.run_id, &fence, now + 1, TRUST_WINDOW_MS)
        .await?;
    store
        .apply_taskflow_command(&TaskFlowCommand::new(
            &intent.run_id,
            "agentd-process-effect-start",
            fence.clone(),
            claimed.revision,
            TaskFlowTransition::Start,
            now + 2,
        )?)
        .await?;
    let digest = intent.digest()?;
    store
        .prepare_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            &fence,
            &digest,
            &intent.payload_digest,
            "agentd-process-effect-prepare",
            now + 3,
        )
        .await?;
    store
        .claim_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            &fence,
            &digest,
            &intent.payload_digest,
            "agentd-process-effect-claim",
            now + 4,
        )
        .await?;
    Ok(())
}

fn signed_final_use(
    intent: &AuthorizedEffectIntent,
    now: u64,
    signer: &SigningKey,
) -> SignedFinalUseGrant {
    let nonce: [u8; 32] = Sha256::digest(b"agentd-process-effect-nonce").into();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "automation-security-owner".to_string(),
        authority_epoch: AUTHORITY_EPOCH,
        grant_id: "agentd-process-effect-grant".to_string(),
        nonce,
        binding: intent.final_use_binding().expect("final-use binding"),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + TRUST_WINDOW_MS,
    };
    SignedFinalUseGrant {
        signature: signer
            .sign(&grant.signing_bytes().expect("grant signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    }
}

fn signed_revocation_update(
    signer: &SigningKey,
    head: FinalUseRevocations,
    now: u64,
) -> SignedFinalUseRevocationUpdate {
    let issued_at_unix_ms = now.saturating_sub(1_000);
    let update = FinalUseRevocationUpdate::new(
        "automation-revocation-distributor".to_string(),
        head,
        issued_at_unix_ms,
        issued_at_unix_ms.saturating_add(
            codex_hepta_contracts::MAX_REVOCATION_FEED_LIFETIME_MS,
        ),
    );
    SignedFinalUseRevocationUpdate {
        signature: signer
            .sign(&update.signing_bytes().expect("revocation signing bytes"))
            .to_bytes()
            .to_vec(),
        update,
    }
}

fn spawn_agentd(
    fleet_root: &HeptaFleetRoot,
    layout: &HeptaAgentLayout,
    workspace: &Path,
    agent_id: &AgentId,
    spawn_generation: u64,
    host_file: &Path,
    log_path: PathBuf,
) -> Result<AgentProcess> {
    let stdout = File::create(&log_path)
        .with_context(|| format!("create {}", log_path.display()))?;
    let stderr = stdout.try_clone()?;
    let child = Command::new(env!("CARGO_BIN_EXE_codex-hepta-agentd"))
        .current_dir(workspace)
        .env(HEPTA_FLEET_ROOT_ENV, fleet_root.as_path())
        .env(HEPTA_AGENT_ID_ENV, agent_id.as_str())
        .env(HEPTA_AGENT_GENERATION_ENV, spawn_generation.to_string())
        .env(HEPTA_AGENT_HOME_ENV, layout.home_root())
        .env(HEPTA_AGENT_RUN_ROOT_ENV, layout.run_root())
        .env("CODEX_HOME", layout.home_root())
        .arg("--automation-effect-host-file")
        .arg(host_file)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .context("spawn normal Agentd product process")?;
    Ok(AgentProcess { child, log_path })
}

async fn wait_for_health(
    process: &mut AgentProcess,
    client: &AgentdClient,
    label: &str,
    condition: impl Fn(&codex_hepta_agentd::HealthSnapshot) -> bool,
) -> Result<codex_hepta_agentd::HealthSnapshot> {
    let deadline = Instant::now() + PROCESS_TIMEOUT;
    loop {
        if let Some(status) = process.exited()? {
            bail!(
                "Agentd exited before {label}: {status}; log:\n{}",
                process.log()
            );
        }
        if let Ok(health) = client.health().await
            && condition(&health)
        {
            return Ok(health);
        }
        if Instant::now() >= deadline {
            bail!("Agentd did not reach {label}; log:\n{}", process.log());
        }
        sleep(Duration::from_millis(50)).await;
    }
}

async fn wait_for_provider_method(server: &MockServer, expected: &str) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let requests = server
            .received_requests()
            .await
            .context("provider request recording disabled")?;
        if requests
            .iter()
            .any(|request| request.method.as_str() == expected)
        {
            return Ok(());
        }
        if Instant::now() >= deadline {
            bail!("provider never observed {expected}");
        }
        sleep(Duration::from_millis(25)).await;
    }
}

async fn wait_for_pending_snapshot(path: &Path) -> Result<Value> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Ok(bytes) = fs::read(path)
            && let Ok(value) = serde_json::from_slice::<Value>(&bytes)
            && !value["pending_revocations"].is_null()
        {
            return Ok(value);
        }
        if Instant::now() >= deadline {
            bail!("durable pending revocation was not observed at {}", path.display());
        }
        sleep(Duration::from_millis(25)).await;
    }
}

fn assert_single_nonce_frame(path: &Path, grant: &SignedFinalUseGrant) -> Result<Vec<u8>> {
    let bytes = fs::read(path).with_context(|| format!("read {}", path.display()))?;
    ensure!(bytes.len() == 40, "expected one 40-byte nonce frame");
    let mut epoch = [0_u8; 8];
    epoch.copy_from_slice(&bytes[..8]);
    ensure!(
        u64::from_be_bytes(epoch) == grant.grant.authority_epoch,
        "nonce epoch drifted"
    );
    ensure!(
        bytes[8..] == grant.grant.nonce[..],
        "nonce identity was not preserved"
    );
    Ok(bytes)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn two_agentd_processes_preserve_pending_nonce_attempt_witness_and_terminal_receipt() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let agent_id = AgentId::parse(AGENT_ID)?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let layout = registry.register(manifest)?.layout;

    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(layout.home_root())?;

    let now = now_ms();
    let scope = Sha256Digest::for_bytes(b"provider-process-fixture-scope");
    let intent = effect_intent(&scope);
    let store = AutomationStore::open(&layout).await?;
    prepare_effect(&store, &agent_id, &intent, now).await?;
    store.close().await;

    let provider = MockServer::start().await;
    let provider_key = ProviderEffectKey::for_operation(
        PROVIDER_SCOPE,
        &intent.run_id,
        &intent.step_id,
    )
    .map_err(|error| anyhow!("derive provider effect key: {error:?}"))?;
    let provider_receipt = Sha256Digest::for_bytes(b"provider-process-operation");
    let ack = serde_json::json!({
        "effect_key": provider_key.as_str(),
        "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": provider_receipt.as_str(),
        "status": "completed"
    });
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(
            PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER,
            provider_key.as_str(),
        ))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(
            ResponseTemplate::new(200)
                .set_delay(Duration::from_secs(30))
                .set_body_json(ack.clone()),
        )
        .expect(1)
        .mount(&provider)
        .await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(200).set_body_json(ack))
        .expect(1)
        .mount(&provider)
        .await;

    let contract_signer = test_signing_key(b"provider-contract");
    let final_use_signer = test_signing_key(b"final-use-issuer");
    let revocation_signer = test_signing_key(b"revocation-distributor");
    let provider_config = HttpProviderEffectConfig {
        dispatch_url: format!("{}/dispatch", provider.uri()),
        lookup_url_template: format!("{}/status/{{key}}", provider.uri()),
        headers: HeaderMap::new(),
        timeout: Duration::from_secs(30),
        contract_id: "agentd-process-effect-contract".to_string(),
        attestation: None,
    };
    let contract_digest = provider_config
        .contract_sha256()
        .map_err(|error| anyhow!("derive provider contract digest: {error}"))?;
    let contract_statement = HttpProviderEffectContractAttestation::statement_for(
        "agentd-process-effect-contract",
        &contract_digest,
        1,
    );
    let contract_signature = contract_signer.sign(&contract_statement).to_bytes();

    let initial_head = FinalUseRevocations {
        authority_epoch: AUTHORITY_EPOCH,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let initial_update = signed_revocation_update(&revocation_signer, initial_head, now);
    let feed_file = layout.automation_root().join("effect-revocation-feed.json");
    write_private_json(&feed_file, &initial_update)?;
    let trust_root = root.join("external-authority-trust");
    fs::create_dir(&trust_root)?;
    fs::set_permissions(&trust_root, fs::Permissions::from_mode(0o700))?;
    let trust_root = trust_root.canonicalize()?;
    let host_file = layout.automation_root().join("effect-host.json");
    let host_config = serde_json::json!({
        "schema_version": 2,
        "provider_scope": PROVIDER_SCOPE,
        "destination_id": DESTINATION_ID,
        "final_use_scope_sha256": scope.as_str(),
        "dispatch_url": format!("{}/dispatch", provider.uri()),
        "lookup_url_template": format!("{}/status/{{key}}", provider.uri()),
        "headers": {},
        "timeout_ms": 30000,
        "contract_id": "agentd-process-effect-contract",
        "contract_sha256": contract_digest.as_str(),
        "contract_authority_epoch": 1,
        "contract_signature_hex": hex(&contract_signature),
        "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
        "final_use_signer_id": "automation-security-owner",
        "final_use_issuer_keys": [{
            "key_id": "issuer-2026-a",
            "verifying_key_hex": hex(&final_use_signer.verifying_key().to_bytes()),
            "not_before_authority_epoch": 1,
            "not_after_authority_epoch": u64::MAX
        }],
        "final_use_revocation_distributor_id": "automation-revocation-distributor",
        "final_use_revocation_keys": [{
            "key_id": "revocation-2026-a",
            "verifying_key_hex": hex(&revocation_signer.verifying_key().to_bytes()),
            "not_before_authority_epoch": 1,
            "not_after_authority_epoch": u64::MAX
        }],
        "final_use_revocation_feed_file": feed_file,
        "final_use_trust_root": trust_root,
        "max_inflight_effects": 2,
        "claim_reserve": 8
    });
    write_private_json(&host_file, &host_config)?;
    let grant = signed_final_use(&intent, now, &final_use_signer);

    let starting_one =
        registry.compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)?;
    ensure!(starting_one.generation == 1);
    let mut first = spawn_agentd(
        &fleet_root,
        &layout,
        &workspace,
        &agent_id,
        starting_one.generation,
        &host_file,
        root.join("agentd-first.log"),
    )?;
    let first_client = AgentdClient::new(
        layout.agentd_control_socket().to_path_buf(),
        agent_id.clone(),
        starting_one.generation,
    )?;
    wait_for_health(&mut first, &first_client, "promotion readiness", |health| {
        health.promotion_ready
    })
    .await?;
    let running_one = registry.compare_and_transition(
        &agent_id,
        starting_one.generation,
        AgentLifecycle::Running,
    )?;
    ensure!(running_one.generation == 2);
    wait_for_health(&mut first, &first_client, "running readiness", |health| {
        health.ready
    })
    .await?;

    let first_result = first_client
        .automation_execute_effect(
            intent.clone(),
            WIRE,
            grant.clone(),
            COMMAND_ID.to_string(),
        )
        .await;
    ensure!(
        first_result.is_err(),
        "the first control waiter must time out while owner work continues"
    );
    wait_for_provider_method(&provider, "POST").await?;

    let mut revoked = BTreeSet::new();
    revoked.insert(grant.grant.grant_id.clone());
    let newer_update = signed_revocation_update(
        &revocation_signer,
        FinalUseRevocations {
            authority_epoch: AUTHORITY_EPOCH,
            revision: 2,
            revoked_grant_ids: revoked,
        },
        now_ms(),
    );
    write_private_json(&feed_file, &newer_update)?;
    let pending_result = first_client
        .automation_execute_effect(
            intent.clone(),
            WIRE,
            grant.clone(),
            COMMAND_ID.to_string(),
        )
        .await;
    ensure!(
        pending_result.is_err(),
        "new admission must be denied while the exact newer head is pending"
    );

    let authority_root = layout.automation_root().join("final-use-authority");
    let authority_snapshot = authority_root.join("authority.json");
    let pending_snapshot = wait_for_pending_snapshot(&authority_snapshot).await?;
    ensure!(pending_snapshot["head"]["revision"].as_u64() == Some(1));
    ensure!(
        pending_snapshot["pending_revocations"]["revision"].as_u64() == Some(2)
    );
    let claims_path = authority_root.join("authority.claims");
    let first_claims = assert_single_nonce_frame(&claims_path, &grant)?;

    first.kill_and_wait()?;
    let interrupted_store = AutomationStore::open(&layout).await?;
    let first_witness = interrupted_store
        .authorized_taskflow_effect_authority_witness(RUN_ID, STEP_ID, 1)
        .await?
        .context("first process did not durably retain the authority witness")?;
    let first_attempt = interrupted_store
        .authorized_taskflow_effect_attempt(RUN_ID, STEP_ID, 1)
        .await?
        .context("first process did not durably retain the provider attempt")?;
    ensure!(first_attempt.grant_id == grant.grant.grant_id);
    ensure!(first_attempt.payload_digest == intent.payload_digest);
    interrupted_store.close().await;

    let failed = registry.compare_and_transition(
        &agent_id,
        running_one.generation,
        AgentLifecycle::Failed,
    )?;
    let starting_two = registry.compare_and_transition(
        &agent_id,
        failed.generation,
        AgentLifecycle::Starting,
    )?;
    ensure!(starting_two.generation == 4);
    let mut second = spawn_agentd(
        &fleet_root,
        &layout,
        &workspace,
        &agent_id,
        starting_two.generation,
        &host_file,
        root.join("agentd-second.log"),
    )?;
    let second_client = AgentdClient::new(
        layout.agentd_control_socket().to_path_buf(),
        agent_id.clone(),
        starting_two.generation,
    )?;
    wait_for_health(&mut second, &second_client, "second promotion readiness", |health| {
        health.promotion_ready
    })
    .await?;
    let running_two = registry.compare_and_transition(
        &agent_id,
        starting_two.generation,
        AgentLifecycle::Running,
    )?;
    ensure!(running_two.generation == 5);
    wait_for_health(&mut second, &second_client, "second running readiness", |health| {
        health.ready
    })
    .await?;

    let reconciled = second_client
        .automation_reconcile_effect(RUN_ID.to_string(), STEP_ID.to_string(), 1)
        .await?;
    ensure!(reconciled.state == AutomationEffectReconcileState::Terminal);
    let recovered_effect = reconciled
        .effect
        .context("terminal reconciliation omitted the effect receipt")?;
    ensure!(recovered_effect.observation == AutomationEffectObservation::Succeeded);
    ensure!(recovered_effect.receipt_digest.is_some());
    wait_for_provider_method(&provider, "GET").await?;

    let terminal_replay = second_client
        .automation_execute_effect(
            intent.clone(),
            WIRE,
            grant.clone(),
            COMMAND_ID.to_string(),
        )
        .await?;
    ensure!(
        terminal_replay.receipt_digest == recovered_effect.receipt_digest,
        "terminal replay changed the durable receipt"
    );
    ensure!(
        terminal_replay.observation == AutomationEffectObservation::Succeeded,
        "terminal replay changed the durable observation"
    );

    second.kill_and_wait()?;
    let committed_snapshot: Value = serde_json::from_slice(&fs::read(&authority_snapshot)?)?;
    ensure!(committed_snapshot["pending_revocations"].is_null());
    ensure!(committed_snapshot["head"]["revision"].as_u64() == Some(2));
    ensure!(
        committed_snapshot["head"]["revoked_grant_ids"]
            .as_array()
            .is_some_and(|ids| ids.iter().any(|id| {
                id.as_str() == Some(grant.grant.grant_id.as_str())
            }))
    );
    let second_claims = assert_single_nonce_frame(&claims_path, &grant)?;
    ensure!(
        first_claims == second_claims,
        "cold recovery reset or duplicated nonce history"
    );

    let recovered_store = AutomationStore::open(&layout).await?;
    let second_witness = recovered_store
        .authorized_taskflow_effect_authority_witness(RUN_ID, STEP_ID, 1)
        .await?
        .context("second process lost the durable authority witness")?;
    ensure!(first_witness == second_witness);
    let durable_receipt = recovered_store
        .read_authorized_taskflow_effect_receipt(&intent, COMMAND_ID)
        .await?
        .context("second process did not retain the terminal provider receipt")?;
    ensure!(durable_receipt.observation == Some(TaskFlowStepObservation::Succeeded));
    ensure!(durable_receipt.receipt_digest == recovered_effect.receipt_digest);
    recovered_store.close().await;

    let requests = provider
        .received_requests()
        .await
        .context("provider request recording disabled")?;
    let posts = requests
        .iter()
        .filter(|request| request.method.as_str() == "POST")
        .count();
    let gets = requests
        .iter()
        .filter(|request| request.method.as_str() == "GET")
        .count();
    ensure!(posts == 1, "cold recovery redispatched the provider effect");
    ensure!(gets == 1, "cold recovery did not reconcile by exact provider lookup");
    provider.verify().await;
    Ok(())
}
