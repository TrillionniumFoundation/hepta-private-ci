#![allow(clippy::expect_used)]
#![cfg(unix)]

use std::collections::BTreeSet;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::final_use_authorizer::FinalUseAuthorizerConfig;
use codex_hepta_infer_worker_host::final_use_authorizer::UnixFinalUseAuthorizer;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeBoundaryStatus;
use codex_hepta_infer_worker_host::native_app_server::NativeRunStatus;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use core_test_support::responses;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;
use tokio_util::sync::CancellationToken;
use wiremock::Mock;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;

mod support;

use support::fleet::FleetHarness;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const MODEL: &str = "gpt-5.2";
const REQUEST_ID: &str = "runtime-codex-product-e2e";
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
async fn runtime_codex_product_caller_commits_one_authorized_terminal_turn() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "runtime-codex-workspace")?;

    let provider = responses::start_mock_server().await;
    MockResponsesConfig::new(&provider.uri()).write(agent.layout.home_root())?;
    mount_terminal_response(&provider).await;

    fleet.start(&agent)?;
    let (_, health) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    ensure!(health.ready && !health.fenced);

    let authority_root = tempfile::tempdir()?;
    std::fs::set_permissions(
        authority_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let authority_socket = authority_root.path().join("final-use.sock");
    let listener = UnixListener::bind(&authority_socket)?;
    std::fs::set_permissions(&authority_socket, std::fs::Permissions::from_mode(0o660))?;
    let issuer_uid = std::fs::metadata(&authority_socket)?.uid();

    let signer = SigningKey::from_bytes(&[73; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(FinalUseAuthorizerConfig {
        issuer_socket: authority_socket,
        issuer_uid,
        signer_id: "authority-owner".to_string(),
        verifying_key: signer.verifying_key().to_bytes(),
        authority_state_dir: authority_root.path().join("authority-state"),
        authority_epoch: 9,
        revocation_revision: 1,
        revoked_grant_ids: BTreeSet::new(),
        issuer_timeout_ms: 2_000,
    })
    .map_err(|error| anyhow::anyhow!(error.to_string()))?;

    let issuer = tokio::spawn(async move { serve_one_grant(listener, signer).await });

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
    let journal = journal_root.path().join("runtime-codex.journal");
    let mut control = DurableInferenceControl::open(&journal, /*capacity*/ 32)?;
    let cancellation = CancellationToken::new();
    let output = driver
        .run(
            &mut control,
            NativeAdmission {
                request_id: REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            "Return the exact phrase runtime codex e2e.".to_string(),
            None,
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
    ensure!(
        output
            .codex_terminal_correlation_digest
            .as_deref()
            .is_some_and(|digest| digest.len() == 64),
        "terminal success omitted its exact Codex correlation digest"
    );

    let record = control
        .native_record(REQUEST_ID)
        .context("durable runtime.codex record disappeared")?;
    ensure!(
        record
            .dispatch
            .as_ref()
            .and_then(|dispatch| dispatch.codex_authority_witness_sha256.as_deref())
            .is_some_and(|digest| digest.len() == 64),
        "durable dispatch omitted the final-use authority witness"
    );
    let dispatch = record
        .dispatch
        .as_ref()
        .context("durable runtime.codex dispatch disappeared")?;
    ensure!(
        dispatch.codex_authority_epoch == Some(9),
        "durable dispatch omitted or changed the final-use authority epoch"
    );
    ensure!(
        dispatch.codex_revocation_revision == Some(1),
        "durable dispatch omitted or changed the final-use revocation revision"
    );
    ensure!(
        dispatch
            .codex_revocation_head_sha256
            .as_deref()
            .is_some_and(|digest| digest.len() == 64),
        "durable dispatch omitted the exact final-use revocation-head digest"
    );
    ensure!(
        record
            .observation
            .as_ref()
            .is_some_and(|observed| observed.terminal_observed),
        "durable owner did not persist the terminal observation"
    );

    let physical_sends = provider
        .received_requests()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|request| request.url.path().ends_with("/responses"))
        .count();
    ensure!(
        physical_sends == 1,
        "runtime.codex product caller sent {physical_sends} physical provider requests instead of exactly one"
    );

    drop(fleet);
    Ok(())
}

async fn mount_terminal_response(server: &wiremock::MockServer) {
    let body = responses::sse(vec![
        responses::ev_assistant_message("runtime-codex-message", "runtime codex e2e"),
        responses::ev_completed("runtime-codex-response"),
    ]);
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "text/event-stream")
                .set_body_string(body),
        )
        .expect(1)
        .mount(server)
        .await;
}

async fn serve_one_grant(listener: UnixListener, signer: SigningKey) -> Result<()> {
    let (mut stream, _) = listener.accept().await?;
    let mut length = [0_u8; 4];
    stream.read_exact(&mut length).await?;
    let request_len = usize::try_from(u32::from_be_bytes(length))?;
    ensure!(
        (1..=16 * 1024).contains(&request_len),
        "invalid final-use authority request length"
    );
    let mut request_bytes = vec![0_u8; request_len];
    stream.read_exact(&mut request_bytes).await?;
    let request: IssuerRequest = serde_json::from_slice(&request_bytes)?;
    ensure!(request.schema_version == AUTHORITY_SCHEMA);
    ensure!(request.operation == AUTHORITY_OPERATION);

    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority-owner".to_string(),
        authority_epoch: head.authority_epoch,
        grant_id: "runtime-codex-product-e2e-grant".to_string(),
        nonce: [91; 32],
        binding: request.binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now
            .checked_add(60_000)
            .context("test grant expiry overflow")?,
    };
    let signature = signer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    let response = IssuerResponse {
        schema_version: AUTHORITY_SCHEMA,
        revocations: head,
        grant: Some(SignedFinalUseGrant { grant, signature }),
        denial_reason: None,
    };
    let bytes = serde_json::to_vec(&response)?;
    let response_len = u32::try_from(bytes.len())?;
    stream.write_all(&response_len.to_be_bytes()).await?;
    stream.write_all(&bytes).await?;
    stream.flush().await?;
    Ok(())
}
