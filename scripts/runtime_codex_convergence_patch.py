"""Apply the bounded runtime.codex convergence patch; fail on source drift.

This materializer is deleted by its one-shot workflow after focused tests pass.
It does not change activation, deployment or release claims.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{path}: expected {count} matches, found {actual}")
    target.write_text(text.replace(old, new, count), encoding="utf-8")


# 1. Persist cancellation/timeout business-boundary decisions monotonically.
# 2. Separate effect certainty from retry policy for explicit App Server refusals.
replace(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    '''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatchRejection {
    pub status: NativeDispatchRejectionStatus,
    pub reason: String,
    pub response_digest: String,
    /// Only overload/pre-processing refusal may carry this bit.
    pub retry_safe_before_admission: bool,
}
''',
    '''#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDispatchEffectDisposition {
    /// The exact App Server response proves that no turn was admitted or started.
    DefinitelyNotStarted,
    /// The response does not establish whether the external effect crossed admission.
    AcceptedOrUnknown,
    /// Replay compatibility for records written before effect certainty was
    /// separated from retry policy. Only an old retry-safe refusal releases.
    #[default]
    LegacyRetryDerived,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatchRejection {
    pub status: NativeDispatchRejectionStatus,
    pub reason: String,
    pub response_digest: String,
    /// Whether an identical operation may be attempted again. This is not the
    /// resource-release decision: a definitive invalid request is non-retryable
    /// but still proves that the external effect never started.
    pub retry_safe_before_admission: bool,
    #[serde(default)]
    pub effect_disposition: NativeDispatchEffectDisposition,
}

impl NativeDispatchRejection {
    fn definitely_not_started(&self) -> bool {
        match self.effect_disposition {
            NativeDispatchEffectDisposition::DefinitelyNotStarted => true,
            NativeDispatchEffectDisposition::AcceptedOrUnknown => false,
            NativeDispatchEffectDisposition::LegacyRetryDerived => {
                self.retry_safe_before_admission
            }
        }
    }
}
''',
)
replace(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    '''                if rejection.retry_safe_before_admission
                    && !matches!(
                        rejection.status,
                        NativeDispatchRejectionStatus::Overloaded
                            | NativeDispatchRejectionStatus::Unavailable
                    )
                {
                    return Err(Error::InvalidTransition);
                }
                let safe_before_admission = rejection.retry_safe_before_admission;
                record.dispatch_rejection = Some(rejection);
                record.state = if safe_before_admission {
                    NativeReservationState::Released
                } else {
                    NativeReservationState::Indeterminate
                };
''',
    '''                if rejection.retry_safe_before_admission
                    && (!matches!(
                        rejection.status,
                        NativeDispatchRejectionStatus::Overloaded
                            | NativeDispatchRejectionStatus::Unavailable
                    ) || !rejection.definitely_not_started())
                {
                    return Err(Error::InvalidTransition);
                }
                let definitely_not_started = rejection.definitely_not_started();
                record.dispatch_rejection = Some(rejection);
                record.state = if definitely_not_started {
                    NativeReservationState::Released
                } else {
                    NativeReservationState::Indeterminate
                };
''',
)
replace(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    '''fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
) -> Result<(), Error> {
''',
    '''fn sticky_boundary_status(status: NativeBoundaryStatus) -> bool {
    matches!(
        status,
        NativeBoundaryStatus::Cancelled
            | NativeBoundaryStatus::TimedOut
            | NativeBoundaryStatus::Quarantined
    )
}

fn preserve_boundary_decision(record: &NativeRunRecord, output: &mut NativeRunOutput) {
    if let Some(previous) = record.observation.as_ref()
        && sticky_boundary_status(previous.boundary_status)
    {
        output.boundary_status = previous.boundary_status;
        if previous.stop_reason.is_some() {
            output.stop_reason = previous.stop_reason.clone();
        }
        return;
    }

    if record.cancel_requested && !sticky_boundary_status(output.boundary_status) {
        output.boundary_status = NativeBoundaryStatus::Cancelled;
        if output.stop_reason.is_none() {
            output.stop_reason =
                Some("cancellation requested before terminal observation".to_string());
        }
    }
}

fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
) -> Result<(), Error> {
''',
)
replace(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    '''    if output.terminal_observed == (output.status == NativeRunStatus::Indeterminate)
        || (output.turn_id.is_empty()
            && (output.terminal_observed
                || output.observed_output_tokens.is_some()
                || !output.output.is_empty()))
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let Some(previous) = &record.observation {
''',
    '''    if output.terminal_observed == (output.status == NativeRunStatus::Indeterminate)
        || (output.turn_id.is_empty()
            && (output.terminal_observed
                || output.observed_output_tokens.is_some()
                || !output.output.is_empty()))
    {
        return Err(Error::TerminalObservationMissing);
    }
    preserve_boundary_decision(record, &mut output);
    if let Some(previous) = &record.observation {
''',
)

# Bounded operational health surface: it exposes growth and unresolved work
# without deleting dedupe history or pretending compaction exists.
replace(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    '''#[derive(Clone, Debug, Default)]
pub(super) struct NativeJournal {
''',
    '''#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeJournalStatus {
    pub record_count: usize,
    pub released_records: usize,
    pub unresolved_records: usize,
    pub active_reservations: usize,
    pub maximum_in_flight: Option<usize>,
    pub record_capacity: usize,
    pub journal_bytes: u64,
    pub journal_limit_bytes: u64,
    pub near_capacity: bool,
    pub unresolved_request_ids: Vec<String>,
    pub unresolved_omitted: usize,
}

#[derive(Clone, Debug, Default)]
pub(super) struct NativeJournal {
''',
)
replace(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    '''    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    fn ensure_native_dispatch_space(&self) -> Result<(), Error> {
''',
    '''    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    /// Bounded operator view of append-only history and reconcile-only work.
    /// This is observation, not authority to release, delete, retry or compact.
    pub fn native_journal_status(
        &self,
        unresolved_limit: usize,
    ) -> Result<NativeJournalStatus, Error> {
        if unresolved_limit > 1024 {
            return Err(Error::CapacityExceeded);
        }
        let unresolved_records = self
            .native
            .records
            .values()
            .filter(|record| record.state != NativeReservationState::Released)
            .count();
        let unresolved_request_ids = self
            .native
            .records
            .iter()
            .filter(|(_, record)| record.state != NativeReservationState::Released)
            .take(unresolved_limit)
            .map(|(request_id, _)| request_id.clone())
            .collect::<Vec<_>>();
        let record_count = self.native.records.len();
        let released_records = record_count.saturating_sub(unresolved_records);
        let maximum_in_flight = self.native.maximum_in_flight;
        let near_record_capacity = record_count.saturating_mul(10)
            >= self.capacity.saturating_mul(9);
        let near_journal_capacity = self.journal_bytes.saturating_mul(10)
            >= super::MAX_JOURNAL_BYTES.saturating_mul(9);
        let near_in_flight_capacity = maximum_in_flight.is_some_and(|maximum| {
            self.native.active_reservations.saturating_mul(10)
                >= maximum.saturating_mul(9)
        });
        Ok(NativeJournalStatus {
            record_count,
            released_records,
            unresolved_records,
            active_reservations: self.native.active_reservations,
            maximum_in_flight,
            record_capacity: self.capacity,
            journal_bytes: self.journal_bytes,
            journal_limit_bytes: super::MAX_JOURNAL_BYTES,
            near_capacity: near_record_capacity
                || near_journal_capacity
                || near_in_flight_capacity,
            unresolved_omitted: unresolved_records.saturating_sub(unresolved_request_ids.len()),
            unresolved_request_ids,
        })
    }

    fn ensure_native_dispatch_space(&self) -> Result<(), Error> {
''',
)

# All definitely-unsent exits after write-ahead consume the one-shot local proof.
replace(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
''',
    '''use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeDispatchEffectDisposition;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
''',
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        verify_persisted_dispatch_binding(
            control,
            request_id,
            payload_digest,
            request_receipt.request_digest,
            source_admission_digest,
            codex_home_digest,
            connection_id,
            &started.thread.session_id,
            adapter_intent.deadline_ms,
            authority_epoch,
            revocation_revision,
            &revocation_head_digest,
            &authority_witness,
            &app_server_version,
        )?;
''',
    '''        if let Err(error) = verify_persisted_dispatch_binding(
            control,
            request_id,
            payload_digest,
            request_receipt.request_digest,
            source_admission_digest,
            codex_home_digest,
            connection_id,
            &started.thread.session_id,
            adapter_intent.deadline_ms,
            authority_epoch,
            revocation_revision,
            &revocation_head_digest,
            &authority_witness,
            &app_server_version,
        ) {
            let reason = format!("durable dispatch verification failed before effect: {error}");
            control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(reason.into());
        }
''',
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        if let Err(error) = validate_post_authority_fence(
            &post_health,
            &ingress_socket_path,
            &current_ingress.socket_path,
            cancellation.is_cancelled(),
            unix_time_ms()?,
            adapter_intent.deadline_ms,
        ) {
''',
    '''        let final_revalidation_now_ms = match unix_time_ms() {
            Ok(value) => value,
            Err(error) => {
                let reason = format!("trusted time unavailable before final-use entry: {error}");
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
        };
        if let Err(error) = validate_post_authority_fence(
            &post_health,
            &ingress_socket_path,
            &current_ingress.socket_path,
            cancellation.is_cancelled(),
            final_revalidation_now_ms,
            adapter_intent.deadline_ms,
        ) {
''',
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        let send_budget = remaining_before(adapter_intent.deadline_ms)?.min(RPC_TIMEOUT);
''',
    '''        let send_budget = match remaining_before(adapter_intent.deadline_ms) {
            Ok(value) => value.min(RPC_TIMEOUT),
            Err(error) => {
                let reason = error.to_string();
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
        };
''',
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                            },
''',
    '''                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                                effect_disposition:
                                    NativeDispatchEffectDisposition::DefinitelyNotStarted,
                            },
''',
)

# Unit regressions: exact reopen monotonicity, effect/retry separation and
# bounded operational status.
replace(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''        response_digest: "e".repeat(64),
        retry_safe_before_admission: true,
''',
    '''        response_digest: "e".repeat(64),
        retry_safe_before_admission: true,
        effect_disposition: NativeDispatchEffectDisposition::DefinitelyNotStarted,
''',
)
replace(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''        response_digest: "f".repeat(64),
        retry_safe_before_admission: false,
''',
    '''        response_digest: "f".repeat(64),
        retry_safe_before_admission: false,
        effect_disposition: NativeDispatchEffectDisposition::AcceptedOrUnknown,
''',
)
replace(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''    let terminal = output(NativeRunStatus::Interrupted, None);
    let interrupted = control.settle_native("r1", terminal.clone()).unwrap();
''',
    '''    let mut terminal = output(NativeRunStatus::Interrupted, None);
    terminal.boundary_status = NativeBoundaryStatus::Cancelled;
    terminal.stop_reason = Some("cancelled".to_string());
    let interrupted = control.settle_native("r1", terminal.clone()).unwrap();
''',
)
unit_tests = r'''
#[test]
fn reopened_cancelled_run_keeps_cancel_boundary_after_late_completion() {
    let path = path("cancel-reopen-monotonic");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    control.cancel_native("r1").unwrap();
    drop(control);

    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let mut completed = output(NativeRunStatus::Completed, Some(8));
    completed.owner_authority = NativeOwnerAuthority::ObservedReady;
    let settled = control.settle_native("r1", completed).unwrap();
    let observed = settled.observation.as_ref().unwrap();
    assert_eq!(observed.status, NativeRunStatus::Completed);
    assert_eq!(observed.boundary_status, NativeBoundaryStatus::Cancelled);
    assert!(observed.stop_reason.is_some());
    assert!(!observed.succeeded());
    assert_eq!(settled.state, NativeReservationState::Released);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn reopened_timed_out_run_keeps_timeout_boundary_after_late_completion() {
    let path = path("timeout-reopen-monotonic");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    control.cancel_native("r1").unwrap();
    let mut timed_out = output(NativeRunStatus::Indeterminate, None);
    timed_out.boundary_status = NativeBoundaryStatus::TimedOut;
    timed_out.stop_reason = Some("deadline elapsed".to_string());
    control.settle_native("r1", timed_out).unwrap();
    drop(control);

    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let mut completed = output(NativeRunStatus::Completed, Some(8));
    completed.owner_authority = NativeOwnerAuthority::ObservedReady;
    let settled = control.settle_native("r1", completed).unwrap();
    let observed = settled.observation.as_ref().unwrap();
    assert_eq!(observed.status, NativeRunStatus::Completed);
    assert_eq!(observed.boundary_status, NativeBoundaryStatus::TimedOut);
    assert_eq!(observed.stop_reason.as_deref(), Some("deadline elapsed"));
    assert!(!observed.succeeded());
    assert_eq!(settled.state, NativeReservationState::Released);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn definitive_nonretryable_rejection_releases_capacity_after_reopen() {
    let path = path("rejected-nonretryable-release");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    let rejection = NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Rejected,
        reason: "invalid params before admission".to_string(),
        response_digest: "c".repeat(64),
        retry_safe_before_admission: false,
        effect_disposition: NativeDispatchEffectDisposition::DefinitelyNotStarted,
    };
    let rejected = control
        .reject_native_before_start("r1", rejection.clone())
        .unwrap();
    assert_eq!(rejected.state, NativeReservationState::Released);
    assert_eq!(rejected.dispatch_rejection, Some(rejection));
    drop(control);

    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    reopened.reserve_native(request("r2"), 1).unwrap();
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn journal_status_reports_unresolved_work_and_growth_after_reopen() {
    let path = path("operator-status");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let mut unknown = output(NativeRunStatus::Indeterminate, None);
    unknown.output.clear();
    unknown.codex_terminal_correlation_digest = None;
    control.settle_native("r1", unknown).unwrap();
    let status = control.native_journal_status(1).unwrap();
    assert_eq!(status.record_count, 1);
    assert_eq!(status.active_reservations, 1);
    assert_eq!(status.unresolved_records, 1);
    assert_eq!(status.unresolved_request_ids, vec!["r1"]);
    assert!(status.near_capacity);
    assert_eq!(control.native_journal_status(1025), Err(Error::CapacityExceeded));
    drop(control);

    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_journal_status(1).unwrap(), status);
    let mut terminal = output(NativeRunStatus::Failed, Some(1));
    terminal.owner_authority = NativeOwnerAuthority::ObservedReady;
    control.settle_native("r1", terminal).unwrap();
    let settled = control.native_journal_status(1).unwrap();
    assert_eq!(settled.active_reservations, 0);
    assert_eq!(settled.unresolved_records, 0);
    assert_eq!(settled.released_records, 1);
    assert!(settled.unresolved_request_ids.is_empty());
    drop(control);
    std::fs::remove_file(path).unwrap();
}

'''
replace(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''#[test]
fn late_completed_releases_slot_without_erasing_authority_loss() {
''',
    unit_tests + '''#[test]
fn late_completed_releases_slot_without_erasing_authority_loss() {
''',
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs",
    '''    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;
''',
    '''    use codex_hepta_infer_core::durable_control::native::NativeDispatchEffectDisposition;
    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;
''',
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs",
    '''                response_digest: "c".repeat(64),
                retry_safe_before_admission: true,
            },
''',
    '''                response_digest: "c".repeat(64),
                retry_safe_before_admission: true,
                effect_disposition: NativeDispatchEffectDisposition::DefinitelyNotStarted,
            },
''',
)

# Extend the existing real Agentd + App Server product test with durable reopen,
# duplicate/no-replay, sticky cancellation/timeout, and process-loss coverage.
replace(
    "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs",
    '''use std::time::Duration;
use std::time::SystemTime;
''',
    '''use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
''',
)
replace(
    "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs",
    '''    let physical_sends = provider
        .received_requests()
''',
    '''    let persisted = record.clone();
    drop(control);
    let mut control = DurableInferenceControl::open(&journal, /*capacity*/ 32)?;
    let replay = driver
        .run(
            &mut control,
            NativeAdmission {
                request_id: REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            "Return the exact phrase runtime codex e2e.".to_string(),
            None,
            &CancellationToken::new(),
        )
        .await
        .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    ensure!(replay == output, "durable duplicate changed the terminal result");
    ensure!(
        control.native_record(REQUEST_ID) == Some(&persisted),
        "durable reopen changed the exact record"
    );

    let physical_sends = provider
        .received_requests()
''',
)
product_fault_tests = r'''
#[derive(Clone, Copy)]
enum StickyBoundaryCase {
    Cancelled,
    TimedOut,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn runtime_codex_product_cancel_timeout_and_reopen_keep_sticky_boundary() -> Result<()> {
    run_sticky_boundary_case(
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13",
        "runtime-codex-cancel-workspace",
        "runtime-codex-product-cancel",
        StickyBoundaryCase::Cancelled,
    )
    .await?;
    run_sticky_boundary_case(
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c14",
        "runtime-codex-timeout-workspace",
        "runtime-codex-product-timeout",
        StickyBoundaryCase::TimedOut,
    )
    .await
}

async fn run_sticky_boundary_case(
    agent_id: &str,
    workspace: &str,
    request_id: &str,
    case: StickyBoundaryCase,
) -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(agent_id, workspace)?;
    let provider = responses::start_mock_server().await;
    MockResponsesConfig::new(&provider.uri()).write(agent.layout.home_root())?;
    let (worker_timeout, response_delay) = match case {
        StickyBoundaryCase::Cancelled => {
            (Duration::from_secs(10), Duration::from_millis(1_000))
        }
        StickyBoundaryCase::TimedOut => {
            (Duration::from_millis(1_200), Duration::from_millis(2_200))
        }
    };
    mount_delayed_terminal_response(&provider, response_delay).await;

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
        timeout: worker_timeout,
    })
    .map_err(|error| anyhow::anyhow!(error.to_string()))?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal_root = tempfile::tempdir()?;
    let journal = journal_root.path().join("runtime-codex-boundary.journal");
    let mut control = DurableInferenceControl::open(&journal, 32)?;
    let cancellation = CancellationToken::new();
    let output = match case {
        StickyBoundaryCase::Cancelled => {
            let signal = cancellation.clone();
            let run = driver.run(
                &mut control,
                NativeAdmission {
                    request_id: request_id.to_string(),
                    maximum_in_flight: 1,
                },
                "Return a delayed runtime codex terminal.".to_string(),
                None,
                &cancellation,
            );
            let cancel = async move {
                tokio::time::sleep(Duration::from_millis(200)).await;
                signal.cancel();
            };
            let (result, ()) = tokio::join!(run, cancel);
            result.map_err(|error| anyhow::anyhow!(error.to_string()))?
        }
        StickyBoundaryCase::TimedOut => driver
            .run(
                &mut control,
                NativeAdmission {
                    request_id: request_id.to_string(),
                    maximum_in_flight: 1,
                },
                "Return a delayed runtime codex terminal.".to_string(),
                None,
                &cancellation,
            )
            .await
            .map_err(|error| anyhow::anyhow!(error.to_string()))?,
    };
    issuer.await.context("final-use issuer task failed to join")??;
    let expected = match case {
        StickyBoundaryCase::Cancelled => NativeBoundaryStatus::Cancelled,
        StickyBoundaryCase::TimedOut => NativeBoundaryStatus::TimedOut,
    };
    ensure!(output.boundary_status == expected);
    ensure!(!output.succeeded());
    let persisted = control
        .native_record(request_id)
        .context("sticky boundary record disappeared")?
        .clone();
    ensure!(
        persisted
            .observation
            .as_ref()
            .is_some_and(|value| value.boundary_status == expected && !value.succeeded())
    );
    drop(control);
    let reopened = DurableInferenceControl::open(&journal, 32)?;
    ensure!(reopened.native_record(request_id) == Some(&persisted));
    let physical_sends = provider
        .received_requests()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|request| request.url.path().ends_with("/responses"))
        .count();
    ensure!(physical_sends == 1, "sticky boundary case replayed a physical request");
    drop(fleet);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn runtime_codex_product_process_loss_after_dispatch_never_replays() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c15",
        "runtime-codex-process-loss-workspace",
    )?;
    let provider = responses::start_mock_server().await;
    MockResponsesConfig::new(&provider.uri()).write(agent.layout.home_root())?;
    mount_delayed_terminal_response(&provider, Duration::from_secs(5)).await;
    fleet.start(&agent)?;
    let (_, health) = fleet.wait_ready(&agent, 1).await?;
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
        timeout: Duration::from_secs(10),
    })
    .map_err(|error| anyhow::anyhow!(error.to_string()))?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal_root = tempfile::tempdir()?;
    let journal = journal_root.path().join("runtime-codex-process-loss.journal");
    let mut control = DurableInferenceControl::open(&journal, 32)?;
    let cancellation = CancellationToken::new();
    let run = driver.run(
        &mut control,
        NativeAdmission {
            request_id: "runtime-codex-product-process-loss".to_string(),
            maximum_in_flight: 1,
        },
        "Return after the process-loss fence.".to_string(),
        None,
        &cancellation,
    );
    let fault = async {
        let deadline = Instant::now() + Duration::from_secs(8);
        loop {
            let sends = provider
                .received_requests()
                .await
                .unwrap_or_default()
                .into_iter()
                .filter(|request| request.url.path().ends_with("/responses"))
                .count();
            if sends == 1 {
                break;
            }
            ensure!(Instant::now() < deadline, "provider dispatch was not observed");
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        fleet.supervisor.kill(&agent.agent_id)?;
        Ok::<_, anyhow::Error>(())
    };
    let coordinated = async {
        let (run_result, fault_result) = tokio::join!(run, fault);
        fault_result?;
        Ok::<_, anyhow::Error>(run_result)
    };
    let run_result = tokio::time::timeout(Duration::from_secs(20), coordinated)
        .await
        .context("process-loss product case timed out")??;
    issuer.await.context("final-use issuer task failed to join")??;
    if let Ok(output) = &run_result {
        ensure!(!output.succeeded());
    }
    let record = control
        .native_record("runtime-codex-product-process-loss")
        .context("process-loss durable record disappeared")?
        .clone();
    ensure!(record.dispatch.is_some());
    drop(control);
    let mut reopened = DurableInferenceControl::open(&journal, 32)?;
    let replay = driver
        .run(
            &mut reopened,
            NativeAdmission {
                request_id: "runtime-codex-product-process-loss".to_string(),
                maximum_in_flight: 1,
            },
            "Return after the process-loss fence.".to_string(),
            None,
            &CancellationToken::new(),
        )
        .await;
    ensure!(
        replay.is_err() || replay.as_ref().is_ok_and(|output| !output.succeeded()),
        "process loss was upgraded to success"
    );
    let physical_sends = provider
        .received_requests()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|request| request.url.path().ends_with("/responses"))
        .count();
    ensure!(physical_sends == 1, "process-loss recovery replayed turn/start");
    drop(fleet);
    Ok(())
}

async fn mount_delayed_terminal_response(server: &wiremock::MockServer, delay: Duration) {
    let body = responses::sse(vec![
        responses::ev_assistant_message("runtime-codex-delayed-message", "delayed terminal"),
        responses::ev_completed("runtime-codex-delayed-response"),
    ]);
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "text/event-stream")
                .set_delay(delay)
                .set_body_string(body),
        )
        .expect(1)
        .mount(server)
        .await;
}

'''
replace(
    "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs",
    '''async fn mount_terminal_response(server: &wiremock::MockServer) {
''',
    product_fault_tests + '''async fn mount_terminal_response(server: &wiremock::MockServer) {
''',
)

# Keep the implementation map and technical/fault docs aligned without
# promoting source, deployment, activation or release claims.
map_path = ROOT / "docs/modules/runtime.codex/IMPLEMENTATION_MAP.json"
implementation_map = json.loads(map_path.read_text(encoding="utf-8"))
product = next(
    entry
    for entry in implementation_map["compositionTests"]
    if entry["path"] == "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs"
)
for coverage in (
    "durable reopen and duplicate request do not add a physical provider dispatch",
    "cancelled and timed-out boundaries remain sticky after late terminal facts and reopen",
    "Agentd/App Server process loss after provider dispatch remains reconcile-only and never replays",
):
    if coverage not in product["covers"]:
        product["covers"].append(coverage)
map_path.write_text(json.dumps(implementation_map, indent=2) + "\n", encoding="utf-8")

replace(
    "docs/modules/runtime.codex/FAULT_MATRIX.md",
    '''- `codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs`: real Agentd + real App Server + named runtime.codex caller + signed final-use authority, with a mock Responses provider; asserts exactly one physical model request and durable terminal correlation.
''',
    '''- `codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs`: real Agentd + real App Server + named runtime.codex caller + signed final-use authority, with a controlled Responses provider; asserts exactly one physical model request, durable terminal correlation, duplicate/reopen no-replay, cancellation/timeout monotonicity, and process-loss reconcile-only behavior.
- `DurableInferenceControl::native_journal_status`: bounded operator visibility for active/unresolved runs, history growth and capacity alarms. It grants no retry, release, deletion or compaction authority.
''',
)
replace(
    "docs/modules/runtime.codex/TECHNICAL.md",
    '''- [codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs): launches the real Agentd/App Server product process, drives the named runtime.codex caller through a signed final-use grant into a mock Responses transport, and proves one physical provider request plus a durable terminal correlation receipt.
''',
    '''- [codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs): launches the real Agentd/App Server product process, drives the named runtime.codex caller through a signed final-use grant into a controlled Responses transport, and proves one physical provider request, durable terminal correlation, duplicate/reopen no-replay, sticky cancellation/timeout, and process-loss reconciliation.
''',
)
replace(
    "docs/modules/runtime.codex/TECHNICAL.md",
    '''Current operating and state-format references:
''',
    '''The native journal exposes a bounded `native_journal_status` operator view with exact record, active, unresolved, byte and capacity counts. Near-capacity is an alert/fail-closed condition; it is not permission to delete deduplication history, release an unknown effect, or claim an unimplemented compaction protocol. Target deployments must retain and reconcile unresolved identities, archive evidence under an independently reviewed retention policy, and keep real-provider/revocation-distribution qualification separate from repository source tests.

Current operating and state-format references:
''',
)
replace(
    "qualification/module-execution-dossiers/detail/runtime.codex.md",
    '''- **Lost acknowledgement and durable reconciliation:** [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs) commits the exact dispatch before the external await and emits a non-serializable one-shot pre-effect abort proof. Only the same live process may use that proof to release a definitely-unsent dispatch. After process loss the proof cannot be recreated, so recovery is reconcile-only. Same-connection `turn/started` can recover a lost `turn/start` response; reopened unknown requests use `thread/read(includeTurns=true)` and require the exact stable `client_user_message_id` plus original `UserMessage` content. Same-id/different-input and duplicate exact turns are hard conflicts. Missing App Server history remains indeterminate.
''',
    '''- **Lost acknowledgement and durable reconciliation:** [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs) commits the exact dispatch before the external await and emits a non-serializable one-shot pre-effect abort proof. Only the same live process may use that proof to release a definitely-unsent dispatch. Effect certainty is independent from retry policy: an explicit pre-admission invalid request may be non-retryable while still releasing capacity; accepted-or-unknown results remain reconcile-only. Cancellation, timeout and quarantine are sticky durable boundary decisions, so later provider terminal facts can supplement history but cannot promote the business boundary to success. After process loss the proof cannot be recreated, so recovery is reconcile-only. Same-connection `turn/started` can recover a lost `turn/start` response; reopened unknown requests use `thread/read(includeTurns=true)` and require the exact stable `client_user_message_id` plus original `UserMessage` content. Same-id/different-input and duplicate exact turns are hard conflicts. Missing App Server history remains indeterminate.
''',
)

print("runtime.codex convergence materialized")
