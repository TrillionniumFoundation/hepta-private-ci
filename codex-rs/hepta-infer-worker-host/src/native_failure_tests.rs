use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;

use codex_hepta_agentd::test_support::CognitiveTestHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use core_test_support::responses;
use serde::Deserialize;
use serde::Serialize;
use tokio::sync::oneshot;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::AppServerModelDriver;
use super::NativeAdmission;
use super::NativeBoundaryStatus;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::NativeWorkerConfig;
use super::Result;

const CHILD_CASE_ENV: &str = "HEPTA_NATIVE_FAILURE_TEST_CASE";
const TEST_NAME: &str = "native_app_server::failure_tests::worker_loss_before_cleanup_retains_observed_timeout_and_usage";
const REQUEST_ID: &str = "native-failure-cutoff";
const PROMPT: &str = "exercise the bounded recovery observation";
const MODEL: &str = "mock-model";
const REQUEST_TIMEOUT: Duration = Duration::from_millis(5_250);

static JOURNAL_HOOK: OnceLock<Mutex<Option<oneshot::Sender<()>>>> = OnceLock::new();

/// Only the isolated child installs this hook. The production call site has
/// already synchronously appended observation and cancellation before it runs.
pub(super) async fn pause_after_observation_journal(request_id: &str) {
    if request_id != REQUEST_ID {
        return;
    }
    let hook = JOURNAL_HOOK
        .get_or_init(|| Mutex::new(None))
        .lock()
        .expect("native failure journal hook")
        .take();
    if let Some(hook) = hook {
        let _ = hook.send(());
        std::future::pending::<()>().await;
    }
}

#[derive(Deserialize, Serialize)]
struct FailureChildCase {
    socket: PathBuf,
    agent: String,
    journal: PathBuf,
    ready: PathBuf,
    output: PathBuf,
    recover: bool,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn worker_loss_before_cleanup_retains_observed_timeout_and_usage() -> Result<()> {
    if let Some(path) = std::env::var_os(CHILD_CASE_ENV) {
        let case: FailureChildCase = serde_json::from_slice(&std::fs::read(path)?)?;
        let driver = AppServerModelDriver::new(NativeWorkerConfig {
            agentd_socket: case.socket,
            agent_id: AgentId::parse(&case.agent)?,
            generation: 1,
            model: MODEL.to_string(),
            timeout: REQUEST_TIMEOUT,
        })?;
        let mut control = DurableInferenceControl::open(&case.journal, 8)?;
        if case.recover {
            // No authorizer exists in the replacement process. It may only
            // observe the exact old dispatch, never start another model turn.
            let deadline = Instant::now() + Duration::from_secs(15);
            loop {
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
                if output.terminal_observed {
                    std::fs::write(case.output, serde_json::to_vec(&output)?)?;
                    return Ok(());
                }
                if Instant::now() >= deadline {
                    return Err(
                        "retained turn did not become terminal before recovery deadline".into(),
                    );
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        }

        let authority_directory = case
            .journal
            .parent()
            .ok_or("child journal directory missing")?
            .join("authority");
        std::fs::create_dir_all(&authority_directory)?;
        let (authorizer, _issuer) =
            crate::final_use_authorizer::tests::independent_test_authorizer(
                &authority_directory,
                1,
            )
            .await?;
        let driver = driver.with_turn_start_authorizer(Arc::new(authorizer));
        let (reached, journaled) = oneshot::channel();
        *JOURNAL_HOOK
            .get_or_init(|| Mutex::new(None))
            .lock()
            .expect("native failure journal hook") = Some(reached);
        let cancellation = CancellationToken::new();
        let run = driver.run(
            &mut control,
            NativeAdmission {
                request_id: REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            PROMPT.to_string(),
            None,
            &cancellation,
        );
        tokio::pin!(run);
        tokio::select! {
            result = &mut run => {
                return Err(format!("worker returned before the cleanup cutoff: {result:?}").into());
            }
            journaled = journaled => {
                journaled?;
                std::fs::write(case.ready, b"observation-journaled-before-cleanup")?;
                // The parent now kills this actual worker process. No return,
                // graceful shutdown, or final settlement can fill the gap.
                std::future::pending::<()>().await;
            }
        }
        return Err("unreachable failure child return".into());
    }

    let server = responses::start_mock_server().await;
    let mut first_completed = responses::ev_completed("usage-before-timeout");
    first_completed["response"]["usage"]["output_tokens"] = serde_json::json!(17);
    first_completed["response"]["usage"]["total_tokens"] = serde_json::json!(17);
    let response_mock = responses::mount_response_sequence(
        &server,
        vec![
            responses::sse_response(responses::sse(vec![
                responses::ev_response_created("usage-before-timeout"),
                // An unknown tool produces a model-visible error and another
                // response request within the same turn, without an OS effect.
                responses::ev_function_call("recovery-tool", "missing_recovery_test_tool", "{}"),
                first_completed,
            ])),
            responses::sse_response(responses::sse(vec![
                responses::ev_response_created("after-worker-loss"),
                responses::ev_assistant_message("recovery-message", "late recovery marker"),
                responses::ev_completed("after-worker-loss"),
            ]))
            .set_delay(Duration::from_secs(8)),
        ],
    )
    .await;
    let directory = tempfile::Builder::new().prefix("hnf-").tempdir_in("/tmp")?;
    let host = CognitiveTestHost::start(
        directory.path().join("host"),
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c14")?,
        MODEL,
        &format!("{}/v1", server.uri()),
    )
    .await?;
    let mut case = FailureChildCase {
        socket: host.control_socket().to_path_buf(),
        agent: host.agent_id().to_string(),
        journal: directory.path().join("worker.journal"),
        ready: directory.path().join("ready"),
        output: directory.path().join("recovered.json"),
        recover: false,
    };
    let case_path = directory.path().join("case.json");
    std::fs::write(&case_path, serde_json::to_vec(&case)?)?;
    let crash_log_path = directory.path().join("crash-child.log");
    let crash_log = std::fs::File::create(&crash_log_path)?;
    let mut child = Command::new(std::env::current_exe()?)
        .args(["--exact", TEST_NAME, "--nocapture"])
        .env(CHILD_CASE_ENV, &case_path)
        .stdout(Stdio::from(crash_log.try_clone()?))
        .stderr(Stdio::from(crash_log))
        .spawn()?;
    let cutoff_deadline = Instant::now() + Duration::from_secs(15);
    while !case.ready.exists() {
        if let Some(status) = child.try_wait()? {
            return Err(format!(
                "worker exited before cleanup cutoff ({status}): {}",
                std::fs::read_to_string(&crash_log_path)?,
            )
            .into());
        }
        if Instant::now() >= cutoff_deadline {
            child.kill()?;
            child.wait()?;
            return Err("worker did not reach cleanup cutoff before its deadline".into());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    child.kill()?;
    child.wait()?;

    let reopened = DurableInferenceControl::open(&case.journal, 8)?;
    let record = reopened
        .native_record(REQUEST_ID)
        .cloned()
        .ok_or("worker lost its actual durable dispatch")?;
    let partial = record
        .observation
        .as_ref()
        .ok_or("pre-cleanup observation missing")?;
    assert_eq!(record.state, NativeReservationState::Cancelling);
    assert!(record.cancel_requested);
    assert_eq!(partial.boundary_status, NativeBoundaryStatus::TimedOut);
    assert_eq!(partial.status, NativeRunStatus::Indeterminate);
    assert!(!partial.terminal_observed);
    assert_eq!(partial.observed_output_tokens, Some(17));
    assert_eq!(
        partial.stop_reason.as_deref(),
        Some(super::LOCAL_DEADLINE_ELAPSED)
    );
    drop(reopened);

    case.recover = true;
    std::fs::write(&case_path, serde_json::to_vec(&case)?)?;
    let recovery_log_path = directory.path().join("recovery-child.log");
    let recovery_log = std::fs::File::create(&recovery_log_path)?;
    let mut replacement = Command::new(std::env::current_exe()?)
        .args(["--exact", TEST_NAME, "--nocapture"])
        .env(CHILD_CASE_ENV, &case_path)
        .stdout(Stdio::from(recovery_log.try_clone()?))
        .stderr(Stdio::from(recovery_log))
        .spawn()?;
    let recovery_deadline = Instant::now() + Duration::from_secs(20);
    let status = loop {
        if let Some(status) = replacement.try_wait()? {
            break status;
        }
        if Instant::now() >= recovery_deadline {
            replacement.kill()?;
            replacement.wait()?;
            return Err("replacement worker exceeded its recovery deadline".into());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    assert!(
        status.success(),
        "{}",
        std::fs::read_to_string(recovery_log_path)?
    );
    let recovered: NativeRunOutput = serde_json::from_slice(&std::fs::read(case.output)?)?;
    assert!(recovered.terminal_observed);
    assert!(matches!(
        recovered.status,
        NativeRunStatus::Completed | NativeRunStatus::Interrupted
    ));
    assert_eq!(recovered.boundary_status, NativeBoundaryStatus::TimedOut);
    assert_eq!(recovered.observed_output_tokens, Some(17));
    assert_eq!(recovered.thread_id, partial.thread_id);
    assert_eq!(recovered.turn_id, partial.turn_id);
    assert!(!recovered.succeeded());
    assert_eq!(response_mock.requests().len(), 2);
    let reopened = DurableInferenceControl::open(&case.journal, 8)?;
    assert_eq!(
        reopened
            .native_record(REQUEST_ID)
            .map(|record| record.state),
        Some(NativeReservationState::Released)
    );
    assert_eq!(
        reopened
            .native_record(REQUEST_ID)
            .and_then(|record| record.observation.as_ref()),
        Some(&recovered)
    );
    host.shutdown().await;
    Ok(())
}
