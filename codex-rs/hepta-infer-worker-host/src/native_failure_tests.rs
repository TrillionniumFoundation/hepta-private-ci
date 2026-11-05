use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;

use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::test_support::CognitiveTestHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
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
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::NativeWorkerConfig;
use super::Result;

const CHILD_CASE_ENV: &str = "HEPTA_NATIVE_FAILURE_TEST_CASE";
const TEST_NAME: &str = "native_app_server::failure_tests::worker_loss_before_cleanup_preserves_timeout_usage_and_owner_loss";
const REQUEST_ID: &str = "native-failure-cutoff";
const PROMPT: &str = "exercise the bounded recovery observation";
const MODEL: &str = "mock-model";
const REQUEST_TIMEOUT: Duration = Duration::from_millis(5_250);

#[derive(Default)]
struct FailureHooks {
    usage: Option<oneshot::Sender<()>>,
    journal: Option<oneshot::Sender<()>>,
}

static JOURNAL_HOOK: OnceLock<Mutex<FailureHooks>> = OnceLock::new();

/// Notify only after the real, correlated usage event has updated the output.
pub(super) fn notify_observed_usage(observed_tokens: u64) {
    if observed_tokens != 17 {
        return;
    }
    if let Some(hooks) = JOURNAL_HOOK.get()
        && let Some(hook) = hooks
            .lock()
            .expect("native failure usage hook")
            .usage
            .take()
    {
        let _ = hook.send(());
    }
}

/// The isolated child pauses after both synchronous journal appends.
pub(super) async fn pause_after_observation_journal(request_id: &str) {
    if request_id != REQUEST_ID {
        return;
    }
    let hook = JOURNAL_HOOK
        .get_or_init(|| Mutex::new(FailureHooks::default()))
        .lock()
        .expect("native failure journal hook")
        .journal
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
    usage_observed: PathBuf,
    ready: PathBuf,
    output: PathBuf,
    recover: bool,
}

#[derive(Clone, Copy)]
enum FailureKind {
    TimedOut,
    OwnerLost,
}

async fn wait_for_child_marker(child: &mut Child, marker: &Path, log: &Path) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(15);
    while !marker.exists() {
        if let Some(status) = child.try_wait()? {
            return Err(format!(
                "worker exited before {} ({status}): {}",
                marker.display(),
                std::fs::read_to_string(log)?,
            )
            .into());
        }
        if Instant::now() >= deadline {
            child.kill()?;
            child.wait()?;
            return Err(
                format!("worker did not reach {} before deadline", marker.display()).into(),
            );
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn worker_loss_before_cleanup_preserves_timeout_usage_and_owner_loss() -> Result<()> {
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
            // The replacement has no authorizer and may only observe the old dispatch.
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
        let (usage_seen, usage) = oneshot::channel();
        let (reached, journaled) = oneshot::channel();
        *JOURNAL_HOOK
            .get_or_init(|| Mutex::new(FailureHooks::default()))
            .lock()
            .expect("native failure journal hook") = FailureHooks {
            usage: Some(usage_seen),
            journal: Some(reached),
        };
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
                return Err(format!("worker returned before observing usage: {result:?}").into());
            }
            usage = usage => {
                usage?;
                std::fs::write(case.usage_observed, b"correlated-usage-observed")?;
            }
        }
        tokio::select! {
            result = &mut run => {
                return Err(format!("worker returned before the cleanup cutoff: {result:?}").into());
            }
            journaled = journaled => {
                journaled?;
                std::fs::write(case.ready, b"observation-journaled-before-cleanup")?;
                // The parent kills this real worker. No graceful return can settle it.
                std::future::pending::<()>().await;
            }
        }
        return Err("unreachable failure child return".into());
    }

    let Some(host_completion) = super::test_process::isolate_host(TEST_NAME).await? else {
        return Ok(());
    };
    // core_test_support registers the production arg0 helper dispatch.
    let server = responses::start_mock_server().await;
    let mut sequence = Vec::new();
    for index in 0..2 {
        let first_response = format!("usage-before-loss-{index}");
        let mut completed = responses::ev_completed(&first_response);
        completed["response"]["usage"]["output_tokens"] = serde_json::json!(17);
        completed["response"]["usage"]["total_tokens"] = serde_json::json!(17);
        sequence.push(responses::sse_response(responses::sse(vec![
            responses::ev_response_created(&first_response),
            // An unknown tool causes another response in the same turn without an OS effect.
            responses::ev_function_call(
                &format!("recovery-tool-{index}"),
                "missing_recovery_test_tool",
                "{}",
            ),
            completed,
        ])));
        sequence.push(
            responses::sse_response(responses::sse(vec![
                responses::ev_response_created(&format!("after-worker-loss-{index}")),
                responses::ev_assistant_message(
                    &format!("recovery-message-{index}"),
                    "late recovery marker",
                ),
                responses::ev_completed(&format!("after-worker-loss-{index}")),
            ]))
            .set_delay(Duration::from_secs(8)),
        );
    }
    let response_mock = responses::mount_response_sequence(&server, sequence).await;
    let directory = tempfile::Builder::new().prefix("hnf-").tempdir_in("/tmp")?;
    // One parent host serves both cases; its immutable process home is never reset.
    let host = CognitiveTestHost::start(
        directory.path().join("host"),
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c14")?,
        MODEL,
        &format!("{}/v1", server.uri()),
        crate::native_app_server::tests::app_server_test_runtime_paths()?,
    )
    .await?;

    for (index, failure) in [FailureKind::TimedOut, FailureKind::OwnerLost]
        .into_iter()
        .enumerate()
    {
        let case_root = directory.path().join(format!("case-{index}"));
        std::fs::create_dir_all(&case_root)?;
        let mut case = FailureChildCase {
            socket: host.control_socket().to_path_buf(),
            agent: host.agent_id().to_string(),
            journal: case_root.join("worker.journal"),
            usage_observed: case_root.join("usage-observed"),
            ready: case_root.join("ready"),
            output: case_root.join("recovered.json"),
            recover: false,
        };
        let case_path = case_root.join("case.json");
        std::fs::write(&case_path, serde_json::to_vec(&case)?)?;
        let crash_log_path = case_root.join("crash-child.log");
        let crash_log = std::fs::File::create(&crash_log_path)?;
        let mut child = Command::new(std::env::current_exe()?)
            .args(["--exact", TEST_NAME, "--nocapture"])
            .env(CHILD_CASE_ENV, &case_path)
            .stdout(Stdio::from(crash_log.try_clone()?))
            .stderr(Stdio::from(crash_log))
            .spawn()?;
        wait_for_child_marker(&mut child, &case.usage_observed, &crash_log_path).await?;

        let suspended_socket = host.control_socket().with_extension("suspended");
        if matches!(failure, FailureKind::OwnerLost) {
            // AgentdClient opens a fresh connection for each health request.
            // Remove only the real socket's name after the worker observed usage.
            std::fs::rename(host.control_socket(), &suspended_socket)?;
        }
        wait_for_child_marker(&mut child, &case.ready, &crash_log_path).await?;
        child.kill()?;
        child.wait()?;
        if matches!(failure, FailureKind::OwnerLost) {
            std::fs::rename(&suspended_socket, host.control_socket())?;
        }

        let mut reopened = DurableInferenceControl::open(&case.journal, 8)?;
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
        assert_eq!(partial.status, NativeRunStatus::Indeterminate);
        assert!(!partial.terminal_observed);
        assert_eq!(partial.observed_output_tokens, Some(17));
        match failure {
            FailureKind::TimedOut => {
                assert_eq!(partial.boundary_status, NativeBoundaryStatus::TimedOut);
                assert_eq!(
                    partial.stop_reason.as_deref(),
                    Some(super::LOCAL_DEADLINE_ELAPSED)
                );
            }
            FailureKind::OwnerLost => {
                assert_eq!(partial.boundary_status, NativeBoundaryStatus::Quarantined);
                assert!(matches!(
                    partial.owner_authority,
                    NativeOwnerAuthority::Lost { .. }
                ));
            }
        }
        let mut competing = record.request.clone();
        competing.request_id = format!("{REQUEST_ID}-competing-{index}");
        assert!(matches!(
            reopened.reserve_native(competing, 1),
            Err(ControlError::CapacityExceeded)
        ));
        drop(reopened);

        // Recovery has a genuinely healthy current owner. Prior Lost must still be final.
        let health = AgentdClient::new(
            host.control_socket().to_path_buf(),
            host.agent_id().clone(),
            1,
        )?
        .health()
        .await?;
        assert!(health.ready && !health.fenced);
        case.recover = true;
        std::fs::write(&case_path, serde_json::to_vec(&case)?)?;
        let recovery_log_path = case_root.join("recovery-child.log");
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
        assert_eq!(recovered.boundary_status, partial.boundary_status);
        assert_eq!(recovered.owner_authority, partial.owner_authority);
        assert_eq!(recovered.stop_reason, partial.stop_reason);
        assert_eq!(recovered.observed_output_tokens, Some(17));
        assert_eq!(recovered.thread_id, partial.thread_id);
        assert_eq!(recovered.turn_id, partial.turn_id);
        assert!(!recovered.succeeded());
        assert_eq!(response_mock.requests().len(), (index + 1) * 2);
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
    }
    host.shutdown().await;
    host_completion.complete()?;
    Ok(())
}
