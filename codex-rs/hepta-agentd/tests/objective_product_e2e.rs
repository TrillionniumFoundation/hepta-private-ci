#![recursion_limit = "256"]
#![cfg(unix)]

use std::collections::BTreeSet;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_hepta_agentd::AgentContextAttachment;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AuthBusObjectiveBody;
use codex_hepta_agentd::AuthBusObjectiveIngress;
use codex_hepta_agentd::ObjectiveStartOutcome;
use codex_hepta_agentd::authbus_objective_claims;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::final_use_authorizer::FinalUseAuthorizerConfig;
use codex_hepta_infer_worker_host::final_use_authorizer::UnixFinalUseAuthorizer;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeBoundaryStatus;
use codex_hepta_infer_worker_host::native_app_server::NativeIntelligenceRunBinding;
use codex_hepta_infer_worker_host::native_app_server::NativeRunStatus;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_objective::decode_source_envelope_json_v1;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use core_test_support::responses;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;
use tokio_util::sync::CancellationToken;
use wiremock::Mock;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;

mod support;

#[path = "objective_product_e2e/replay.rs"]
mod replay;

use support::fleet::AgentFixture;
use support::fleet::FleetHarness;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c31";
const MISSING_CHECKPOINT_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c32";
const COMPILED_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c34";
const ISSUER_ID: &str = "issuer.objective.product";
const MODEL: &str = "gpt-5.2";
const AUTHORITY_SCHEMA: u32 = 1;
const AUTHORITY_OPERATION: &str = "runtime.codex.turn_start";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IssuerRequest {
    schema_version: u32,
    operation: String,
    binding: FinalUseBinding,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct IssuerResponse {
    schema_version: u32,
    revocations: FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<String>,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn signed_objective_abstain_is_durable_idempotent_and_restart_safe() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "objective-product-workspace")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri())
        .with_model(MODEL)
        .disable_feature(codex_features::Feature::Plugins)
        .write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    // Provisioners commonly create the owner directory before Agentd starts.
    // A pristine layout must initialize its external checkpoint rather than be
    // mistaken for rolled-back durable history.
    let precreated_store = agent.layout.home_root().join("objective-run-start-v1");
    let precreated_segments = precreated_store.join("segments");
    std::fs::create_dir_all(&precreated_segments)?;
    std::fs::set_permissions(&precreated_store, std::fs::Permissions::from_mode(0o700))?;
    std::fs::set_permissions(&precreated_segments, std::fs::Permissions::from_mode(0o700))?;

    let key = SigningKey::from_bytes(&[113; 32]);
    let files = configure_objective_files(&agent, &key).await?;
    fleet.start_with_objective_files(
        &agent,
        &files.trust_file,
        &files.authbus_checkpoint_file,
        &files.profile_file,
        &files.objective_checkpoint_file,
    )?;
    let (control, first_health) = fleet.wait_ready(&agent, 1).await?;

    let first = signed_objective(&agent.agent_id, &key, 1, 1, "run.objective.product.1")?;
    let first_receipt = admitted(control.objective_start(first.clone()).await?)?;
    ensure!(first_receipt.disposition == "explicit_abstain");
    ensure!(!first_receipt.idempotent);

    let duplicate = admitted(control.objective_start(first.clone()).await?)?;
    ensure!(duplicate.idempotent);
    ensure!(duplicate.run_id == first_receipt.run_id);
    ensure!(duplicate.publication_digest == first_receipt.publication_digest);
    ensure!(duplicate.chain_digest == first_receipt.chain_digest);
    assert_checkpoint(&files.objective_checkpoint_file, &agent.agent_id, 1)?;

    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let (restarted, second_health) = fleet.wait_new_spawn(&agent, 1).await?;
    ensure!(second_health.process_id != first_health.process_id);
    let second_generation = fleet
        .supervisor
        .snapshot(&agent.agent_id)
        .and_then(|snapshot| snapshot.spawn_generation)
        .context("restarted Agent has no spawn generation")?;
    ensure!(second_generation > 1);
    let stale = restarted
        .objective_start(first)
        .await
        .expect_err("old spawn-bound objective must not re-enter after restart");
    ensure!(stale.to_string().contains("agentd rejected request"));

    let second = signed_objective(
        &agent.agent_id,
        &key,
        second_generation,
        2,
        "run.objective.product.2",
    )?;
    let second_receipt = admitted(restarted.objective_start(second.clone()).await?)?;
    ensure!(second_receipt.disposition == "explicit_abstain");
    ensure!(!second_receipt.idempotent);
    ensure!(admitted(restarted.objective_start(second).await?)?.idempotent);
    assert_checkpoint(&files.objective_checkpoint_file, &agent.agent_id, 2)?;

    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let (_, third_health) = fleet.wait_new_spawn(&agent, second_generation).await?;
    ensure!(third_health.process_id != second_health.process_id);
    assert_checkpoint(&files.objective_checkpoint_file, &agent.agent_id, 2)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn signed_compiled_objective_executes_once_reaches_terminal_and_does_not_resurrect()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(COMPILED_AGENT_ID, "objective-compiled-workspace")?;
    let provider = responses::start_mock_server().await;
    MockResponsesConfig::new(&provider.uri())
        .with_model(MODEL)
        .disable_feature(codex_features::Feature::Plugins)
        .write(agent.layout.home_root())?;
    mount_terminal_response(&provider).await;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;

    let key = SigningKey::from_bytes(&[116; 32]);
    let files = configure_objective_files(&agent, &key).await?;
    fleet.start_with_objective_files(
        &agent,
        &files.trust_file,
        &files.authbus_checkpoint_file,
        &files.profile_file,
        &files.objective_checkpoint_file,
    )?;
    let (control, first_health) = fleet.wait_ready(&agent, 1).await?;
    let request =
        signed_compiled_objective(&agent.agent_id, &key, 1, 1, "run.objective.compiled.1")?;
    let receipt = admitted(control.objective_start(request.clone()).await?)?;
    ensure!(receipt.disposition == "compiled");
    let execution = receipt
        .execution
        .clone()
        .context("compiled objective omitted its exact execution binding")?;
    ensure!(execution.objective_digest == receipt.objective_digest);
    let admitted_run = control
        .run_status(receipt.run_id.clone())
        .await?
        .context("compiled objective did not enter the daemon run coordinator")?;
    ensure!(admitted_run.phase == AgentRunPhase::Admitted);

    let context_digest = digest_hex('a');
    let envelope_digest = digest_hex('b');
    let attached = control
        .run_attach_context(
            admitted_run.revision,
            AgentContextAttachment {
                run_id: receipt.run_id.clone(),
                request_digest: execution.request_digest.clone(),
                objective_digest: execution.objective_digest.clone(),
                body_digest: execution.body_digest.clone(),
                artifact_set_digest: execution.artifact_set_digest.clone(),
                authority_epoch: execution.authority_epoch,
                generation: execution.generation,
                fence_digest: execution.fence_digest.clone(),
                deadline_ms: execution.deadline_ms,
                context_digest: context_digest.clone(),
                compilation_receipt_digest: envelope_digest.clone(),
            },
        )
        .await?;
    ensure!(attached.phase == AgentRunPhase::ContextAttached);

    let authority_root = tempfile::tempdir()?;
    std::fs::set_permissions(
        authority_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let authority_socket = authority_root.path().join("final-use.sock");
    let listener = UnixListener::bind(&authority_socket)?;
    std::fs::set_permissions(&authority_socket, std::fs::Permissions::from_mode(0o660))?;
    let issuer_uid = std::fs::metadata(&authority_socket)?.uid();
    let authority_signer = SigningKey::from_bytes(&[117; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(FinalUseAuthorizerConfig {
        issuer_socket: authority_socket,
        issuer_uid,
        signer_id: "objective-product-authority".to_string(),
        verifying_key: authority_signer.verifying_key().to_bytes(),
        authority_state_dir: authority_root.path().join("authority-state"),
        authority_epoch: 11,
        revocation_revision: 1,
        revoked_grant_ids: BTreeSet::new(),
        issuer_timeout_ms: 2_000,
    })
    .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    let issuer = tokio::spawn(async move { serve_one_grant(listener, authority_signer).await });

    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: agent.layout.agentd_control_socket().to_path_buf(),
        agent_id: agent.agent_id.clone(),
        generation: 1,
        model: MODEL.to_string(),
        timeout: Duration::from_secs(20),
    })
    .map_err(|error| anyhow::anyhow!(error.to_string()))?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal_root = tempfile::tempdir()?;
    let journal = journal_root
        .path()
        .join("objective-product-execution.journal");
    let mut durable = DurableInferenceControl::open(&journal, 8)?;
    let cancellation = CancellationToken::new();
    let binding = NativeIntelligenceRunBinding {
        run_id: receipt.run_id.clone(),
        expected_revision: attached.revision,
        context_digest,
        envelope_digest,
    };
    let output = driver
        .run_intelligence(
            &mut durable,
            NativeAdmission {
                request_id: "objective-product-physical-turn-1".to_string(),
                maximum_in_flight: 1,
            },
            "Return the exact phrase objective product e2e.".to_string(),
            None,
            binding.clone(),
            &cancellation,
        )
        .await
        .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    issuer
        .await
        .context("final-use issuer task failed to join")??;
    ensure!(output.status == NativeRunStatus::Completed);
    ensure!(output.boundary_status == NativeBoundaryStatus::Succeeded);
    ensure!(output.terminal_observed);
    let terminal = control
        .run_status(receipt.run_id.clone())
        .await?
        .context("objective run disappeared before terminal verification")?;
    ensure!(terminal.phase == AgentRunPhase::Succeeded);
    ensure!(terminal.terminal_observed);

    // Lost response followed by a full inference-journal reopen returns the
    // durable observation and cannot acquire another grant or send another
    // physical provider request.
    drop(durable);
    let mut durable = DurableInferenceControl::open(&journal, 8)?;
    let replay = driver
        .run_intelligence(
            &mut durable,
            NativeAdmission {
                request_id: "objective-product-physical-turn-1".to_string(),
                maximum_in_flight: 1,
            },
            "Return the exact phrase objective product e2e.".to_string(),
            None,
            binding,
            &cancellation,
        )
        .await
        .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    ensure!(replay == output);
    let physical_sends = provider
        .received_requests()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|observed| observed.url.path().ends_with("/responses"))
        .count();
    ensure!(
        physical_sends == 1,
        "objective product sent {physical_sends} physical turns"
    );
    assert_checkpoint(&files.objective_checkpoint_file, &agent.agent_id, 1)?;

    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let (restarted, second_health) = fleet.wait_new_spawn(&agent, 1).await?;
    ensure!(second_health.process_id != first_health.process_id);
    ensure!(restarted.run_status(receipt.run_id).await?.is_none());
    let stale = restarted
        .objective_start(request)
        .await
        .expect_err("old generation objective unexpectedly resurrected after restart");
    ensure!(stale.to_string().contains("agentd rejected request"));
    assert_checkpoint(&files.objective_checkpoint_file, &agent.agent_id, 1)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn existing_local_objective_run_start_history_without_external_checkpoint_fails_daemon_start()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(
        MISSING_CHECKPOINT_AGENT_ID,
        "objective-missing-checkpoint-workspace",
    )?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri())
        .with_model(MODEL)
        .disable_feature(codex_features::Feature::Plugins)
        .write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let key = SigningKey::from_bytes(&[114; 32]);
    let files = configure_objective_files(&agent, &key).await?;

    fleet.start_with_objective_files(
        &agent,
        &files.trust_file,
        &files.authbus_checkpoint_file,
        &files.profile_file,
        &files.objective_checkpoint_file,
    )?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let request = signed_objective(
        &agent.agent_id,
        &key,
        1,
        1,
        "run.objective.missing-checkpoint",
    )?;
    let receipt = admitted(control.objective_start(request).await?)?;
    ensure!(receipt.disposition == "explicit_abstain");
    ensure!(files.objective_checkpoint_file.is_file());
    ensure!(
        agent
            .layout
            .home_root()
            .join("objective-run-start-v1/active.bin")
            .is_file()
    );

    fleet.supervisor.kill(&agent.agent_id)?;
    wait_until_stopped(&mut fleet, &agent).await?;
    std::fs::remove_file(&files.objective_checkpoint_file)?;
    std::fs::File::open(
        files
            .objective_checkpoint_file
            .parent()
            .context("objective checkpoint parent")?,
    )?
    .sync_all()?;

    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let error = match fleet.wait_new_spawn(&agent, 1).await {
        Ok(_) => anyhow::bail!("missing external checkpoint unexpectedly reached readiness"),
        Err(error) => error,
    };
    let rendered = format!("{error:#}");
    ensure!(
        rendered.contains("RollbackDetected") || rendered.contains("run-start checkpoint"),
        "daemon failed for an unrelated reason: {rendered}"
    );
    ensure!(!files.objective_checkpoint_file.exists());
    Ok(())
}

async fn mount_terminal_response(server: &wiremock::MockServer) {
    mount_terminal_responses(server, 1).await;
}

async fn mount_terminal_responses(server: &wiremock::MockServer, expected: u64) {
    let body = responses::sse(vec![
        responses::ev_assistant_message("objective-product-message", "objective product e2e"),
        responses::ev_completed("objective-product-response"),
    ]);
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "text/event-stream")
                .set_body_string(body),
        )
        // Exact counts are asserted on the successful execution path below.
        // Only enforce the upper bound on drop so an earlier admission error
        // remains visible instead of being masked by a mock destructor panic.
        .expect(0..=expected)
        .mount(server)
        .await;
}

async fn serve_one_grant(listener: UnixListener, signer: SigningKey) -> Result<()> {
    serve_grants(listener, signer, 1).await
}

async fn serve_grants(listener: UnixListener, signer: SigningKey, count: usize) -> Result<()> {
    for index in 0..count {
        let (mut stream, _) = listener.accept().await?;
        let mut length = [0_u8; 4];
        stream.read_exact(&mut length).await?;
        let request_len = usize::try_from(u32::from_be_bytes(length))?;
        ensure!((1..=16 * 1024).contains(&request_len));
        let mut request_bytes = vec![0_u8; request_len];
        stream.read_exact(&mut request_bytes).await?;
        let request: IssuerRequest = serde_json::from_slice(&request_bytes)?;
        ensure!(request.schema_version == AUTHORITY_SCHEMA);
        ensure!(request.operation == AUTHORITY_OPERATION);

        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let revocations = FinalUseRevocations {
            authority_epoch: 11,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let nonce_byte = u8::try_from(index % 251 + 1)?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "objective-product-authority".to_string(),
            authority_epoch: revocations.authority_epoch,
            grant_id: format!("objective-product-final-use-grant-{index}"),
            nonce: [nonce_byte; 32],
            binding: request.binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now.checked_add(60_000).context("grant expiry overflow")?,
        };
        let signature = signer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        let bytes = serde_json::to_vec(&IssuerResponse {
            schema_version: AUTHORITY_SCHEMA,
            revocations,
            grant: Some(SignedFinalUseGrant { grant, signature }),
            denial_reason: None,
        })?;
        stream
            .write_all(&u32::try_from(bytes.len())?.to_be_bytes())
            .await?;
        stream.write_all(&bytes).await?;
        stream.flush().await?;
    }
    Ok(())
}

async fn wait_until_stopped(fleet: &mut FleetHarness, agent: &AgentFixture) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let report = fleet.supervisor.tick(Instant::now());
        ensure!(
            report.faults.is_empty(),
            "supervisor faults while stopping objective Agent: {:?}",
            report.faults
        );
        if fleet
            .supervisor
            .snapshot(&agent.agent_id)
            .is_none_or(|snapshot| !snapshot.active)
        {
            return Ok(());
        }
        ensure!(
            Instant::now() < deadline,
            "objective Agent did not stop before checkpoint removal"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

struct ObjectiveFiles {
    trust_file: std::path::PathBuf,
    authbus_checkpoint_file: std::path::PathBuf,
    profile_file: std::path::PathBuf,
    objective_checkpoint_file: std::path::PathBuf,
    _authbus_root: tempfile::TempDir,
    _objective_root: tempfile::TempDir,
}

async fn configure_objective_files(
    agent: &AgentFixture,
    key: &SigningKey,
) -> Result<ObjectiveFiles> {
    let trust_file = agent.layout.home_root().join("authbus-trust.json");
    write_private_json(
        &trust_file,
        &json!({
            "schema_version": 1,
            "agent_id": agent.agent_id.to_string(),
            "issuer_id": ISSUER_ID,
            "key_epoch": 1,
            "public_key_hex": hex(key.verifying_key().as_bytes()),
            "revoked": false,
            "thread_ids": []
        }),
    )?;

    let profile_file = agent.layout.home_root().join("objective-profile.json");
    write_private_json(&profile_file, &objective_profile())?;

    let authbus_root = tempfile::tempdir()?;
    std::fs::set_permissions(authbus_root.path(), std::fs::Permissions::from_mode(0o700))?;
    let authbus_checkpoint_file = authbus_root.path().join("authbus-checkpoint.json");
    let home = AbsolutePathBuf::from_absolute_path(agent.layout.home_root())?;
    let evidence = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(home)).await?;
    let frontier = evidence.authbus_replay_frontier_digest().await?;
    drop(evidence);
    write_authbus_checkpoint(
        &authbus_checkpoint_file,
        &agent.agent_id,
        frontier.to_string(),
    )?;

    let objective_root = tempfile::tempdir()?;
    std::fs::set_permissions(
        objective_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let objective_checkpoint_file = objective_root
        .path()
        .canonicalize()?
        .join("objective-run-start-checkpoint.json");

    Ok(ObjectiveFiles {
        trust_file,
        authbus_checkpoint_file,
        profile_file,
        objective_checkpoint_file,
        _authbus_root: authbus_root,
        _objective_root: objective_root,
    })
}

fn objective_profile() -> Value {
    fn resource(name: &str, class: &str, suffix: usize) -> Value {
        json!({
            "constraintId": format!("resource.{name}.{suffix}"),
            "axis": format!("resource.{name}"),
            "class": class,
            "q32PerSourceUnit": 1,
            "evidenceSource": "profile.resource"
        })
    }
    json!({
        "profileId": "objective.profile.product.e2e",
        "profileRevision": 1,
        "expectedInputSchemaDigest": digest_hex('1'),
        "expectedNormalizationProfileDigest": digest_hex('2'),
        "principalScopeDigest": digest_hex('3'),
        "principalScope": "principal.product.e2e",
        "allowedLocales": ["en-US"],
        "maximumSourceAgeMicros": 10000000000000000_u64,
        "maximumFutureSkewMicros": 1000000,
        "deadlineRequired": true,
        "allowedTrustedSourceIdentities": [ISSUER_ID],
        "constraints": [{
            "sourceConstraintId": "latency.ceiling",
            "expectedUnit": "micros",
            "class": "task",
            "axis": "latency.micros"
        }],
        "predicates": [{
            "sourcePredicateId": "task.success",
            "expectedUnit": "ratio",
            "axis": "task.success.ratio"
        }, {
            "sourcePredicateId": "task.terminal",
            "expectedUnit": "boolean",
            "axis": "task.terminal.boolean"
        }],
        "actions": [{
            "sourceActionClass": "read",
            "actionId": "action.read"
        }],
        "softDimensions": [],
        "evidenceRequirements": [{
            "sourceRequirementId": "evidence.quality",
            "axis": "evidence.confidence"
        }],
        "resources": {
            "timeMicros": resource("time", "task", 1),
            "tokenCount": resource("tokens", "task", 2),
            "computeMicros": resource("compute", "environment", 3),
            "memoryBytes": resource("memory", "environment", 4),
            "networkBytes": resource("network", "principal", 5),
            "externalEffectCount": resource("effects", "principal", 6)
        },
        "risk": {
            "evidenceSource": "profile.risk",
            "class": "principal",
            "riskConstraintId": "risk.class",
            "riskAxis": "risk.value",
            "lowValueQ32": 0,
            "mediumValueQ32": 1,
            "highValueQ32": 2,
            "criticalValueQ32": 3,
            "rollbackConstraintId": "risk.rollback",
            "rollbackAxis": "risk.rollback.value",
            "rollbackNoneValueQ32": 0,
            "rollbackReversibleValueQ32": 1,
            "rollbackCompensatableValueQ32": 2,
            "rollbackIrreversibleValueQ32": 3,
            "compensationConstraintId": "risk.compensation",
            "compensationAxis": "risk.compensation.value",
            "compensationFalseValueQ32": 0,
            "compensationTrueValueQ32": 1,
            "abstentionConstraintId": "risk.abstention",
            "abstentionAxis": "risk.abstention.value",
            "abstentionRules": [{"sourceRule": "ask", "valueQ32": 1}]
        }
    })
}

fn source_envelope_json() -> Result<String> {
    source_envelope_json_with_legal_actions(json!([]))
}

fn compiled_source_envelope_json() -> Result<String> {
    source_envelope_json_with_legal_actions(json!(["read"]))
}

fn source_envelope_json_with_legal_actions(legal_action_classes: Value) -> Result<String> {
    let mut source = json!({
        "requestId": "objective.request.product.e2e",
        "principalScopeDigest": digest_hex('3'),
        "intentDigest": digest_hex('f'),
        "structuredIntent": {
            "successPredicates": [{
                "predicateId": "task.success",
                "unit": "ratio",
                "comparator": "gte",
                "boundQ32": 2147483648_i64,
                "evidenceSourceId": "observer.task",
                "terminal": false
            }],
            "terminalConditions": [{
                "predicateId": "task.terminal",
                "unit": "boolean",
                "comparator": "eq",
                "boundQ32": 4294967296_i64,
                "evidenceSourceId": "observer.task",
                "terminal": true
            }],
            "legalActionClasses": legal_action_classes,
            "forbiddenActionClasses": [],
            "confirmationActionClasses": [],
            "constraints": [{
                "constraintId": "latency.ceiling",
                "unit": "micros",
                "comparator": "lte",
                "boundQ32": 5000,
                "evidenceSourceId": "observer.clock",
                "terminal": false
            }],
            "softDimensions": [],
            "evidenceRequirements": [{
                "requirementId": "evidence.quality",
                "evidenceSourceId": "observer.evidence",
                "minimumConfidencePpm": 900000,
                "terminal": true
            }],
            "resources": {
                "timeMicros": 1000000,
                "tokenCount": 256,
                "computeMicros": 1000000,
                "memoryBytes": 1048576,
                "networkBytes": 0,
                "externalEffectCount": 0
            },
            "risk": {
                "riskClass": "low",
                "abstentionRule": "ask",
                "rollbackClass": "reversible",
                "compensationRequired": false
            },
            "provenance": {
                "sourceDigest": digest_hex('4'),
                "normalizationProfileDigest": digest_hex('2')
            }
        },
        "sourceTrustClass": "authorized_adapter",
        "locale": "en-US",
        "observedAt": "2026-01-01T00:00:00Z",
        "deadline": "2099-01-01T00:00:00.000001Z",
        "inputSchemaDigest": digest_hex('1')
    });
    let draft_bytes = serde_json::to_vec(&source)?;
    let draft = decode_source_envelope_json_v1(&draft_bytes)
        .map_err(|error| anyhow::anyhow!("source decode: {error}"))?;
    let intent = canonical_objective_intent_digest_v1(&draft)
        .map_err(|error| anyhow::anyhow!("intent digest: {error}"))?;
    source["intentDigest"] = json!(intent.to_string());
    Ok(serde_json::to_string(&source)?)
}

fn signed_objective(
    agent_id: &AgentId,
    key: &SigningKey,
    spawn_generation: u64,
    sequence: u64,
    run_id: &str,
) -> Result<AuthBusObjectiveIngress> {
    signed_objective_with_source(
        agent_id,
        key,
        spawn_generation,
        sequence,
        run_id,
        source_envelope_json()?,
    )
}

fn signed_compiled_objective(
    agent_id: &AgentId,
    key: &SigningKey,
    spawn_generation: u64,
    sequence: u64,
    run_id: &str,
) -> Result<AuthBusObjectiveIngress> {
    signed_objective_with_source(
        agent_id,
        key,
        spawn_generation,
        sequence,
        run_id,
        compiled_source_envelope_json()?,
    )
}

fn signed_objective_with_source(
    agent_id: &AgentId,
    key: &SigningKey,
    spawn_generation: u64,
    sequence: u64,
    run_id: &str,
    source_envelope_json: String,
) -> Result<AuthBusObjectiveIngress> {
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let mut request = AuthBusObjectiveIngress {
        issuer_id: ISSUER_ID.to_string(),
        key_epoch: 1,
        message_id: format!("message.objective.product.{sequence}"),
        sequence,
        expires_at_ms: now_ms + 300_000,
        signature_hex: String::new(),
        body: AuthBusObjectiveBody {
            spawn_generation,
            run_id: run_id.to_string(),
            objective_revision: sequence,
            source_envelope_json,
            runtime_body_digest: digest_hex('5'),
            preference_state_digest: digest_hex('6'),
            model_tuple_digest: digest_hex('7'),
            prompt_registry_digest: digest_hex('8'),
            artifact_set_digest: digest_hex('9'),
            authority_epoch: 1,
        },
    };
    let claims = authbus_objective_claims(agent_id, &request)?;
    request.signature_hex = hex(&key.sign(&claims.signing_bytes()).to_bytes());
    Ok(request)
}

fn admitted(outcome: ObjectiveStartOutcome) -> Result<codex_hepta_agentd::ObjectiveRunAdmission> {
    match outcome {
        ObjectiveStartOutcome::Admitted { receipt } => Ok(receipt),
        ObjectiveStartOutcome::Conflict {
            run_id,
            conflict_digest,
        } => anyhow::bail!("unexpected conflict for {run_id}: {conflict_digest}"),
    }
}

fn write_private_json(path: &Path, value: &Value) -> Result<()> {
    let parent = path.parent().context("private file parent missing")?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    temporary
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    serde_json::to_writer(temporary.as_file_mut(), value)?;
    temporary.as_file_mut().flush()?;
    temporary.as_file().sync_all()?;
    temporary.persist(path)?;
    std::fs::File::open(parent)?.sync_all()?;
    Ok(())
}

fn write_authbus_checkpoint(path: &Path, agent_id: &AgentId, digest: String) -> Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer(
        &mut file,
        &json!({
            "schema_version": 1,
            "agent_id": agent_id.to_string(),
            "generation": 1,
            "digest": digest
        }),
    )?;
    file.flush()?;
    file.sync_all()?;
    Ok(())
}

fn assert_checkpoint(path: &Path, agent_id: &AgentId, sequence: u64) -> Result<()> {
    let value: Value = serde_json::from_slice(&std::fs::read(path)?)?;
    ensure!(value["schema_version"] == json!(1));
    ensure!(value["agent_id"] == json!(agent_id.to_string()));
    ensure!(value["anchor_sequence"] == json!(sequence));
    ensure!(value["compacted_prefix_sequence"] == json!(0));
    Ok(())
}

fn digest_hex(value: char) -> String {
    value.to_string().repeat(64)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "run only on a named target host through hepta-objective-target-measure.py"]
async fn measurement_signed_objective_daemon_round_trip() -> Result<()> {
    let samples = product_measurement_sample_count(32, 1_000)?;
    let execution_samples = product_execution_measurement_sample_count(4, 64)?;
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c33",
        "objective-product-measurement-workspace",
    )?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri())
        .with_model(MODEL)
        .disable_feature(codex_features::Feature::Plugins)
        .write(agent.layout.home_root())?;
    mount_terminal_responses(&model, u64::try_from(execution_samples)?).await;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;

    let key = SigningKey::from_bytes(&[115; 32]);
    let files = configure_objective_files(&agent, &key).await?;
    fleet.start_with_objective_files(
        &agent,
        &files.trust_file,
        &files.authbus_checkpoint_file,
        &files.profile_file,
        &files.objective_checkpoint_file,
    )?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let mut timings = Vec::with_capacity(samples);
    let mut last_request = None;
    for sample in 1..=samples {
        let sequence = u64::try_from(sample)?;
        let request = signed_objective(
            &agent.agent_id,
            &key,
            1,
            sequence,
            &format!("run.objective.measure.{sequence}"),
        )?;
        let started = Instant::now();
        let receipt = admitted(control.objective_start(request.clone()).await?)?;
        timings.push(started.elapsed().as_nanos());
        ensure!(!receipt.idempotent);
        ensure!(receipt.disposition == "explicit_abstain");
        ensure!(receipt.execution.is_none());
        last_request = Some(request);
    }

    let replay_started = Instant::now();
    let replay = admitted(
        control
            .objective_start(last_request.context("measurement produced no request")?)
            .await?,
    )?;
    let replay_ns = replay_started.elapsed().as_nanos();
    ensure!(replay.idempotent);

    let authority_root = tempfile::tempdir()?;
    std::fs::set_permissions(
        authority_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let authority_socket = authority_root.path().join("final-use.sock");
    let listener = UnixListener::bind(&authority_socket)?;
    std::fs::set_permissions(&authority_socket, std::fs::Permissions::from_mode(0o660))?;
    let issuer_uid = std::fs::metadata(&authority_socket)?.uid();
    let authority_signer = SigningKey::from_bytes(&[119; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(FinalUseAuthorizerConfig {
        issuer_socket: authority_socket,
        issuer_uid,
        signer_id: "objective-product-authority".to_string(),
        verifying_key: authority_signer.verifying_key().to_bytes(),
        authority_state_dir: authority_root.path().join("authority-state"),
        authority_epoch: 11,
        revocation_revision: 1,
        revoked_grant_ids: BTreeSet::new(),
        issuer_timeout_ms: 2_000,
    })
    .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    let issuer =
        tokio::spawn(
            async move { serve_grants(listener, authority_signer, execution_samples).await },
        );
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: agent.layout.agentd_control_socket().to_path_buf(),
        agent_id: agent.agent_id.clone(),
        generation: 1,
        model: MODEL.to_string(),
        timeout: Duration::from_secs(20),
    })
    .map_err(|error| anyhow::anyhow!(error.to_string()))?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let execution_root = tempfile::tempdir()?;
    let execution_journal = execution_root
        .path()
        .join("objective-product-measurement.journal");
    let mut durable = DurableInferenceControl::open(
        &execution_journal,
        execution_samples
            .checked_add(1)
            .context("execution measurement capacity overflow")?,
    )?;
    let cancellation = CancellationToken::new();
    let mut execution_timings = Vec::with_capacity(execution_samples);
    let mut last_execution = None;
    for sample in 1..=execution_samples {
        let sequence = u64::try_from(samples.checked_add(sample).context("sequence overflow")?)?;
        let run_id = format!("run.objective.measure.compiled.{sequence}");
        let request = signed_compiled_objective(&agent.agent_id, &key, 1, sequence, &run_id)?;
        let native_request_id = format!("objective-product-measure-turn-{sequence}");
        let prompt = "Return the exact phrase objective product e2e.".to_string();
        let started = Instant::now();
        let receipt = admitted(control.objective_start(request).await?)?;
        ensure!(receipt.disposition == "compiled");
        let execution = receipt
            .execution
            .context("compiled measurement omitted execution binding")?;
        let admitted_run = control
            .run_status(receipt.run_id.clone())
            .await?
            .context("compiled measurement run disappeared")?;
        let context_digest = format!("{sequence:064x}");
        let envelope_digest = format!(
            "{:064x}",
            sequence.checked_add(1_000_000).context("digest overflow")?
        );
        let attached = control
            .run_attach_context(
                admitted_run.revision,
                AgentContextAttachment {
                    run_id: receipt.run_id.clone(),
                    request_digest: execution.request_digest,
                    objective_digest: execution.objective_digest,
                    body_digest: execution.body_digest,
                    artifact_set_digest: execution.artifact_set_digest,
                    authority_epoch: execution.authority_epoch,
                    generation: execution.generation,
                    fence_digest: execution.fence_digest,
                    deadline_ms: execution.deadline_ms,
                    context_digest: context_digest.clone(),
                    compilation_receipt_digest: envelope_digest.clone(),
                },
            )
            .await?;
        let binding = NativeIntelligenceRunBinding {
            run_id: receipt.run_id.clone(),
            expected_revision: attached.revision,
            context_digest,
            envelope_digest,
        };
        let output = driver
            .run_intelligence(
                &mut durable,
                NativeAdmission {
                    request_id: native_request_id.clone(),
                    maximum_in_flight: 1,
                },
                prompt.clone(),
                None,
                binding.clone(),
                &cancellation,
            )
            .await
            .map_err(|error| anyhow::anyhow!(error.to_string()))?;
        ensure!(output.status == NativeRunStatus::Completed);
        ensure!(output.boundary_status == NativeBoundaryStatus::Succeeded);
        ensure!(output.terminal_observed);
        let terminal = control
            .run_status(receipt.run_id)
            .await?
            .context("compiled measurement terminal disappeared")?;
        ensure!(terminal.phase == AgentRunPhase::Succeeded && terminal.terminal_observed);
        execution_timings.push(started.elapsed().as_nanos());
        last_execution = Some((native_request_id, prompt, binding, output));
    }
    issuer
        .await
        .context("measurement final-use issuer task failed to join")??;

    let (native_request_id, prompt, binding, output) =
        last_execution.context("execution measurement produced no request")?;
    drop(durable);
    let mut durable = DurableInferenceControl::open(
        &execution_journal,
        execution_samples
            .checked_add(1)
            .context("execution measurement capacity overflow")?,
    )?;
    let execution_replay_started = Instant::now();
    let execution_replay = driver
        .run_intelligence(
            &mut durable,
            NativeAdmission {
                request_id: native_request_id,
                maximum_in_flight: 1,
            },
            prompt,
            None,
            binding,
            &cancellation,
        )
        .await
        .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    let execution_replay_ns = execution_replay_started.elapsed().as_nanos();
    ensure!(execution_replay == output);
    let physical_sends = model
        .received_requests()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|observed| observed.url.path().ends_with("/responses"))
        .count();
    ensure!(physical_sends == execution_samples);

    let durable_sequence = samples
        .checked_add(execution_samples)
        .context("checkpoint sequence overflow")?;
    assert_checkpoint(
        &files.objective_checkpoint_file,
        &agent.agent_id,
        u64::try_from(durable_sequence)?,
    )?;
    let restart_started = Instant::now();
    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let _ = fleet.wait_new_spawn(&agent, 1).await?;
    let restart_ns = restart_started.elapsed().as_nanos();
    assert_checkpoint(
        &files.objective_checkpoint_file,
        &agent.agent_id,
        u64::try_from(durable_sequence)?,
    )?;
    let (p50, p95, p99) = measured_percentiles(timings)?;
    let (execution_p50, execution_p95, execution_p99) = measured_percentiles(execution_timings)?;
    println!(
        "OBJECTIVE_PRODUCT_MEASUREMENT={}",
        json!({
            "schema": "hepta.objective-product-target-measurement.v1",
            "path": "signed_objective_daemon_round_trip",
            "samples": samples,
            "latencyNanoseconds": {"p50": p50, "p95": p95, "p99": p99},
            "exactReplayNanoseconds": replay_ns,
            "executionSamples": execution_samples,
            "executionLatencyNanoseconds": {
                "p50": execution_p50,
                "p95": execution_p95,
                "p99": execution_p99
            },
            "executionExactReplayNanoseconds": execution_replay_ns,
            "physicalProviderSends": physical_sends,
            "terminalObservations": execution_samples,
            "restartReadyNanoseconds": restart_ns,
            "durableCheckpointSequence": durable_sequence
        })
    );
    Ok(())
}

fn product_execution_measurement_sample_count(default: usize, maximum: usize) -> Result<usize> {
    match std::env::var("HEPTA_OBJECTIVE_PRODUCT_EXECUTION_SAMPLES") {
        Ok(raw) => {
            let value = raw
                .parse::<usize>()
                .context("HEPTA_OBJECTIVE_PRODUCT_EXECUTION_SAMPLES must be an integer")?;
            ensure!(
                (1..=maximum).contains(&value),
                "HEPTA_OBJECTIVE_PRODUCT_EXECUTION_SAMPLES must be in 1..={maximum}"
            );
            Ok(value)
        }
        Err(std::env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error.into()),
    }
}

fn product_measurement_sample_count(default: usize, maximum: usize) -> Result<usize> {
    match std::env::var("HEPTA_OBJECTIVE_PRODUCT_MEASUREMENT_SAMPLES") {
        Ok(raw) => {
            let value = raw
                .parse::<usize>()
                .context("HEPTA_OBJECTIVE_PRODUCT_MEASUREMENT_SAMPLES must be an integer")?;
            ensure!(
                (1..=maximum).contains(&value),
                "HEPTA_OBJECTIVE_PRODUCT_MEASUREMENT_SAMPLES must be in 1..={maximum}"
            );
            Ok(value)
        }
        Err(std::env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error.into()),
    }
}

fn measured_percentiles(mut samples_ns: Vec<u128>) -> Result<(u128, u128, u128)> {
    ensure!(!samples_ns.is_empty(), "measurement sample set is empty");
    samples_ns.sort_unstable();
    let pick = |percent: usize| {
        let index = (samples_ns.len() - 1) * percent / 100;
        samples_ns[index]
    };
    Ok((pick(50), pick(95), pick(99)))
}
