use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_agentd::test_support::CognitiveTestHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use core_test_support::responses;
use serde::Deserialize;
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use super::super::NativeAdmission;
use super::super::NativeWorkerConfig;
use super::AppServerModelDriver;
use super::Instant;
use super::NativeBoundaryStatus;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::Result;

const CHILD_CASE_ENV: &str = "HEPTA_NATIVE_RECOVERY_TEST_CASE";
const PROMPT: &str = "return the recovery marker";
const REQUEST_ID: &str = "native-recovery-observation";
const MODEL: &str = "mock-model";

#[derive(Deserialize, Serialize)]
struct RecoveryChildCase {
    socket: PathBuf,
    agent: String,
    journal: PathBuf,
    output: PathBuf,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_agentd_reconciles_reopened_worker_without_replaying_provider() -> Result<()> {
    if let Some(path) = std::env::var_os(CHILD_CASE_ENV) {
        let case: RecoveryChildCase = serde_json::from_slice(&std::fs::read(path)?)?;
        // A genuinely new worker process opens the old journal. Recovery has no
        // final-use issuer and must never attempt another physical turn/start.
        let driver = AppServerModelDriver::new(NativeWorkerConfig {
            agentd_socket: case.socket,
            agent_id: AgentId::parse(&case.agent)?,
            generation: 1,
            model: MODEL.to_string(),
            timeout: Duration::from_secs(20),
        })?;
        let mut control = DurableInferenceControl::open(&case.journal, 8)?;
        let output = driver
            .run(
                &mut control,
                NativeAdmission {
                    request_id: REQUEST_ID.to_string(),
                    maximum_in_flight: 1,
                },
                PROMPT.to_string(),
                None,
                &CancellationToken::new(),
            )
            .await?;
        let record = control
            .native_record(REQUEST_ID)
            .ok_or("recovered native record missing")?;
        assert_eq!(record.state, NativeReservationState::Released);
        assert_eq!(record.observation.as_ref(), Some(&output));
        std::fs::write(case.output, serde_json::to_vec(&output)?)?;
        return Ok(());
    }

    let server = responses::start_mock_server().await;
    let mut completed = responses::ev_completed("recovery-response");
    completed["response"]["usage"]["output_tokens"] = serde_json::json!(17);
    completed["response"]["usage"]["total_tokens"] = serde_json::json!(17);
    let response_mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_response_created("recovery-response"),
            responses::ev_assistant_message("recovery-message", "recovery marker"),
            completed,
        ]),
    )
    .await;
    // Keep Unix socket paths bounded even when the platform's default temp
    // directory includes a long per-user prefix.
    let directory = tempfile::Builder::new().prefix("hnr-").tempdir_in("/tmp")?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?;
    let host = CognitiveTestHost::start(
        directory.path().join("host"),
        agent_id,
        MODEL,
        &format!("{}/v1", server.uri()),
    )
    .await?;
    let authority_directory = tempfile::tempdir()?;
    let (authorizer, issuer) = crate::final_use_authorizer::tests::independent_test_authorizer(
        authority_directory.path(),
        1,
    )
    .await?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: host.control_socket().to_path_buf(),
        agent_id: host.agent_id().clone(),
        generation: 1,
        model: MODEL.to_string(),
        timeout: Duration::from_secs(20),
    })?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let mut original = DurableInferenceControl::open(directory.path().join("original"), 8)?;
    let accepted = driver
        .run(
            &mut original,
            NativeAdmission {
                request_id: REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            PROMPT.to_string(),
            None,
            &CancellationToken::new(),
        )
        .await?;
    assert!(accepted.succeeded());
    assert_eq!(accepted.observed_output_tokens, Some(17));
    let accepted_record = original
        .native_record(REQUEST_ID)
        .cloned()
        .ok_or("missing original dispatch")?;
    drop(original);
    issuer.await??;

    // These journals represent different durable prefixes of that same exact
    // dispatch. The provider has already completed and the original worker has
    // unsubscribed, so each child must recover through retained thread/read.
    for (index, boundary) in [
        None,
        Some(NativeBoundaryStatus::TimedOut),
        Some(NativeBoundaryStatus::Quarantined),
        Some(NativeBoundaryStatus::Cancelled),
    ]
    .into_iter()
    .enumerate()
    {
        let journal = directory.path().join(format!("recovery-{index}"));
        let mut prefix = DurableInferenceControl::open(&journal, 8)?;
        prefix.reserve_native(accepted_record.request.clone(), 1)?;
        prefix.dispatch_native(
            REQUEST_ID,
            accepted_record
                .dispatch
                .clone()
                .ok_or("original dispatch binding missing")?,
        )?;
        if let Some(boundary_status) = boundary {
            prefix.native_started(REQUEST_ID, accepted.turn_id.clone())?;
            prefix.cancel_native(REQUEST_ID)?;
            if boundary_status != NativeBoundaryStatus::Cancelled {
                let mut partial = accepted.clone();
                partial.terminal_observed = false;
                partial.status = NativeRunStatus::Indeterminate;
                partial.boundary_status = boundary_status;
                partial.output.clear();
                partial.codex_terminal_correlation_digest = None;
                partial.stop_reason = Some("recorded before worker loss".to_string());
                if boundary_status == NativeBoundaryStatus::Quarantined {
                    partial.owner_authority = NativeOwnerAuthority::Lost {
                        reason: "recorded owner loss".to_string(),
                    };
                }
                prefix.settle_native(REQUEST_ID, partial)?;
            }
        }
        drop(prefix);
        let output_path = directory.path().join(format!("output-{index}.json"));
        let case_path = directory.path().join(format!("case-{index}.json"));
        std::fs::write(
            &case_path,
            serde_json::to_vec(&RecoveryChildCase {
                socket: host.control_socket().to_path_buf(),
                agent: host.agent_id().to_string(),
                journal: journal.clone(),
                output: output_path.clone(),
            })?,
        )?;
        let log_path = directory.path().join(format!("child-{index}.log"));
        let log = std::fs::File::create(&log_path)?;
        let mut child = Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                "native_app_server::recovery::tests::real_agentd_reconciles_reopened_worker_without_replaying_provider",
                "--nocapture",
            ])
            .env(CHILD_CASE_ENV, &case_path)
            .stdout(Stdio::from(log.try_clone()?))
            .stderr(Stdio::from(log))
            .spawn()?;
        let deadline = Instant::now() + Duration::from_secs(30);
        let status = loop {
            if let Some(status) = child.try_wait()? {
                break status;
            }
            if Instant::now() >= deadline {
                child.kill()?;
                child.wait()?;
                return Err("recovery child exceeded its bounded deadline".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        };
        assert!(status.success(), "{}", std::fs::read_to_string(log_path)?);
        let recovered: NativeRunOutput = serde_json::from_slice(&std::fs::read(output_path)?)?;
        assert!(recovered.terminal_observed);
        assert_eq!(recovered.status, NativeRunStatus::Completed);
        assert_eq!(recovered.thread_id, accepted.thread_id);
        assert_eq!(recovered.turn_id, accepted.turn_id);
        assert_eq!(recovered.output, accepted.output);
        assert!(recovered.codex_terminal_correlation_digest.is_some());
        assert_eq!(
            recovered.boundary_status,
            match boundary {
                // This prefix records only cancel_native, whose boolean does
                // not prove whether cancellation, timeout or observation loss
                // triggered interruption before the worker disappeared.
                Some(NativeBoundaryStatus::Cancelled) => NativeBoundaryStatus::Quarantined,
                Some(boundary) => boundary,
                None => NativeBoundaryStatus::Succeeded,
            },
        );
        assert_eq!(recovered.succeeded(), boundary.is_none());
        assert_eq!(
            recovered.observed_output_tokens,
            match boundary {
                Some(NativeBoundaryStatus::TimedOut | NativeBoundaryStatus::Quarantined) => Some(17),
                _ => None,
            },
        );
        if boundary == Some(NativeBoundaryStatus::Quarantined) {
            assert_eq!(
                recovered.owner_authority,
                NativeOwnerAuthority::Lost {
                    reason: "recorded owner loss".to_string(),
                },
            );
        }
        let reopened = DurableInferenceControl::open(&journal, 8)?;
        assert_eq!(
            reopened
                .native_record(REQUEST_ID)
                .and_then(|record| record.observation.as_ref()),
            Some(&recovered),
        );
    }
    assert_eq!(response_mock.requests().len(), 1);
    host.shutdown().await;
    Ok(())
}
