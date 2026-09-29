#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_before_once(relative: str, marker: str, addition: str) -> None:
    replace_once(relative, marker, addition + marker)


# ---------------------------------------------------------------------------
# Durable native journal: persist generic usage and observation time evidence.
# ---------------------------------------------------------------------------
native = "codex-rs/hepta-infer-core/src/native_control.rs"

replace_once(
    native,
    '''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunRecord {
    pub request: NativeRequest,
    pub revision: u64,
    pub state: NativeReservationState,
    pub dispatch: Option<NativeDispatch>,
    pub turn_id: Option<String>,
    pub cancel_requested: bool,
    /// A locally proven pre-dispatch stop releases a slot without pretending
    /// to have observed a provider terminal event or zero token consumption.
    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    pub observation: Option<NativeRunOutput>,
}

#[derive(Clone, Debug, Default)]
pub(super) struct NativeJournal {
''',
    '''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunRecord {
    pub request: NativeRequest,
    pub revision: u64,
    pub state: NativeReservationState,
    pub dispatch: Option<NativeDispatch>,
    pub turn_id: Option<String>,
    pub cancel_requested: bool,
    /// A locally proven pre-dispatch stop releases a slot without pretending
    /// to have observed a provider terminal event or zero token consumption.
    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    pub observation: Option<NativeRunOutput>,
    /// Generic usage observed by a qualified local driver or reconciler.
    /// Hosted output-token observations remain in `NativeRunOutput`.
    #[serde(default)]
    pub observed_usage_units: Option<u64>,
    /// First durable nonterminal observation time. Historical records may lack
    /// this field and must not be assigned an invented age.
    #[serde(default)]
    pub first_indeterminate_at_unix_ms: Option<u64>,
    /// Most recent durable observation time, monotonic for one request.
    #[serde(default)]
    pub last_observed_at_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NativeJournal {
''',
)

replace_once(
    native,
    '''    Observe {
        request_id: String,
        output: NativeRunOutput,
    },
''',
    '''    Observe {
        request_id: String,
        output: NativeRunOutput,
        /// Zero is accepted only while replaying a pre-metadata journal event.
        #[serde(default)]
        observed_at_unix_ms: u64,
        /// `None` is unknown and never means zero.
        #[serde(default)]
        usage_units: Option<u64>,
    },
''',
)

replace_once(
    native,
    '''    /// Trusted host port: validates exact assignment and monotonic observations.
    /// Only matching terminal observations release local execution capacity.
    /// Missing usage never becomes zero and unknown execution may later settle.
    pub fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.observation.as_ref() == Some(&output) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Observe {
                request_id: request_id.to_string(),
                output,
            },
        )
    }
''',
    '''    /// Trusted host port: validates exact assignment and monotonic observations.
    /// Only matching terminal observations release local execution capacity.
    /// Missing usage never becomes zero and unknown execution may later settle.
    pub fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        self.settle_native_with_usage_at(
            request_id,
            output,
            None,
            host_unix_time_ms()?,
        )
    }

    /// Settle an observation with independently bounded generic usage and an
    /// explicit trusted-host observation time. This is used by the local-model
    /// adapter so usage and indeterminate age survive restart.
    pub fn settle_native_with_usage_at(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
        usage_units: Option<u64>,
        observed_at_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error> {
        if observed_at_unix_ms == 0 {
            return Err(Error::InvalidTime);
        }
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.observation.as_ref() == Some(&output)
            && usage_units.is_none_or(|usage| record.observed_usage_units == Some(usage))
        {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Observe {
                request_id: request_id.to_string(),
                output,
                observed_at_unix_ms,
                usage_units,
            },
        )
    }
''',
)

replace_once(
    native,
    '''                    pre_dispatch_stop: None,
                    dispatch_rejection: None,
                    observation: None,
                },
''',
    '''                    pre_dispatch_stop: None,
                    dispatch_rejection: None,
                    observation: None,
                    observed_usage_units: None,
                    first_indeterminate_at_unix_ms: None,
                    last_observed_at_unix_ms: None,
                },
''',
)

replace_once(
    native,
    '''            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
''',
    '''            Event::Observe {
                output,
                observed_at_unix_ms,
                usage_units,
                ..
            } => {
                if record.dispatch_rejection.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
                apply_observation_metadata(
                    record,
                    observed_at_unix_ms,
                    usage_units,
                )?;
            }
''',
)

insert_before_once(
    native,
    "\n#[cfg(test)]\n#[path = \"native_control_tests.rs\"]\nmod tests;\n",
    r'''
fn apply_observation_metadata(
    record: &mut NativeRunRecord,
    observed_at_unix_ms: u64,
    usage_units: Option<u64>,
) -> Result<(), Error> {
    if observed_at_unix_ms != 0 {
        if record
            .last_observed_at_unix_ms
            .is_some_and(|previous| observed_at_unix_ms < previous)
        {
            return Err(Error::Conflict);
        }
        record.last_observed_at_unix_ms = Some(observed_at_unix_ms);
        if record.state == NativeReservationState::Indeterminate
            && record.first_indeterminate_at_unix_ms.is_none()
        {
            record.first_indeterminate_at_unix_ms = Some(observed_at_unix_ms);
        }
    }
    if let Some(usage) = usage_units {
        if record
            .observed_usage_units
            .is_some_and(|previous| usage < previous)
        {
            return Err(Error::Conflict);
        }
        record.observed_usage_units = Some(usage);
    }
    Ok(())
}

fn host_unix_time_ms() -> Result<u64, Error> {
    let elapsed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| Error::InvalidTime)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| Error::InvalidTime)
}

''',
)

# ---------------------------------------------------------------------------
# Local driver: a bounded, explicit post-entry interrupt/reconcile port.
# ---------------------------------------------------------------------------
driver = "codex-rs/hepta-infer-worker-host/src/experimental_local/driver.rs"

replace_once(
    driver,
    '''#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DriverReconciliation {
''',
    '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriverInterruptReason {
    Cancelled,
    DeadlineElapsed,
}

impl DriverInterruptReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Cancelled => "cancelled after local effect entry",
            Self::DeadlineElapsed => "deadline elapsed after local effect entry",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DriverReconciliation {
''',
)

replace_once(
    driver,
    '''    fn inspect<'a>(
        &'a self,
        operation_id: &'a str,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverReconciliation>;

    fn unload<'a>(
''',
    '''    /// Request interruption after durable effect entry. The default is
    /// deliberately ambiguous: dropping a run future is never proof that the
    /// physical runtime stopped.
    fn interrupt<'a>(
        &'a self,
        _operation_id: &'a str,
        _handle: &'a AttestedModelHandle,
        reason: DriverInterruptReason,
    ) -> LocalFuture<'a, DriverReconciliation> {
        Box::pin(async move {
            Ok(DriverReconciliation::Ambiguous {
                reason: format!(
                    "{}; driver supplied no qualified interrupt observation",
                    reason.as_str()
                ),
            })
        })
    }

    fn inspect<'a>(
        &'a self,
        operation_id: &'a str,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverReconciliation>;

    fn unload<'a>(
''',
)

replace_once(
    "codex-rs/hepta-infer-worker-host/src/experimental_local.rs",
    "pub use driver::DriverLoadObservation;\n",
    "pub use driver::DriverInterruptReason;\npub use driver::DriverLoadObservation;\n",
)

# ---------------------------------------------------------------------------
# Local durable adapter: worker-owned mid-run cancellation/deadline, persistent
# usage and age, and no replay after effect entry.
# ---------------------------------------------------------------------------
durable = "codex-rs/hepta-infer-worker-host/src/experimental_local/durable.rs"

replace_once(
    durable,
    '''use serde::Serialize;
use tokio_util::sync::CancellationToken;
''',
    '''use std::time::Duration;

use serde::Serialize;
use tokio_util::sync::CancellationToken;
''',
)
replace_once(
    durable,
    "use super::DriverLoadObservation;\n",
    "use super::DriverInterruptReason;\nuse super::DriverLoadObservation;\n",
)
replace_once(
    durable,
    '''const LOCAL_PROVIDER_ID: &str = "local.model.experimental";
const MAX_LOCAL_OUTPUT_BYTES: usize = 1024 * 1024;
''',
    '''const LOCAL_PROVIDER_ID: &str = "local.model.experimental";
const MAX_LOCAL_OUTPUT_BYTES: usize = 1024 * 1024;
const LOCAL_INTERRUPT_GRACE: Duration = Duration::from_secs(3);
''',
)

replace_once(
    durable,
    '''        let observed = match self.driver.run(handle, input, cancellation, deadline).await {
            Ok(observed) => observed,
            Err(error) => {
                let output = indeterminate_output(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    None,
                    "driver returned after effect entry without a trusted terminal observation",
                );
                let settled = control
                    .settle_native(&admission.request_id, output)
                    .map_err(control_error)?;
                request_resources.quarantine()?;
                self.resources
                    .fence_generation("local driver result unknown after effect entry")?;
                let mut result = result_from_record(&settled)?;
                result.stop_reason = Some(format!(
                    "{}; {error}",
                    result.stop_reason.unwrap_or_default()
                ));
                return Ok(result);
            }
        };
''',
    '''        let now_ms = self.clock.now_ms()?;
        let remaining_ms = deadline
            .as_millis()
            .checked_sub(now_ms)
            .ok_or(LocalWorkerError::DeadlineExpired)?;
        let driver_outcome = {
            let run = self.driver.run(handle, input, cancellation, deadline);
            tokio::pin!(run);
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => Err(DriverInterruptReason::Cancelled),
                _ = tokio::time::sleep(Duration::from_millis(remaining_ms)) => {
                    Err(DriverInterruptReason::DeadlineElapsed)
                }
                result = &mut run => Ok(result),
            }
        };
        let observed = match driver_outcome {
            Ok(Ok(observed)) => observed,
            Ok(Err(error)) => {
                let output = indeterminate_output(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    None,
                    "driver returned after effect entry without a trusted terminal observation",
                );
                let settled = self.settle_local(
                    control,
                    &admission.request_id,
                    output,
                    None,
                )?;
                request_resources.quarantine()?;
                self.resources
                    .fence_generation("local driver result unknown after effect entry")?;
                let mut result = result_from_record(&settled)?;
                result.stop_reason = Some(format!(
                    "{}; {error}",
                    result.stop_reason.unwrap_or_default()
                ));
                return Ok(result);
            }
            Err(reason) => {
                return self
                    .interrupt_after_effect(
                        control,
                        grant,
                        manifest,
                        handle,
                        &admission,
                        request_resources,
                        reason,
                    )
                    .await;
            }
        };
''',
)

replace_once(
    durable,
    '''            let settled = control
                .settle_native(&admission.request_id, output)
                .map_err(control_error)?;
            request_resources.quarantine()?;
            self.resources
                .fence_generation("nonterminal local execution requires reconciliation")?;
''',
    '''            let settled = self.settle_local(
                control,
                &admission.request_id,
                output,
                observed.usage_units,
            )?;
            request_resources.quarantine()?;
            self.resources
                .fence_generation("nonterminal local execution requires reconciliation")?;
''',
)
replace_once(
    durable,
    '''        let settled = control
            .settle_native(&admission.request_id, output)
            .map_err(control_error)?;
        request_resources.complete()?;
        result_from_record(&settled)
''',
    '''        let release_resources =
            output.boundary_status != NativeBoundaryStatus::Quarantined;
        let settled = self.settle_local(
            control,
            &admission.request_id,
            output,
            observed.usage_units,
        )?;
        if release_resources {
            request_resources.complete()?;
        } else {
            request_resources.quarantine()?;
            self.resources.fence_generation(
                "terminal local execution lacked trusted release evidence",
            )?;
        }
        result_from_record(&settled)
''',
)

replace_once(
    durable,
    '''                let settled = control
                    .settle_native(&record.request.request_id, output)
                    .map_err(control_error)?;
                self.resources
                    .resolve_quarantine_if_present(&record.request.request_id)?;
                result_from_record(&settled)
''',
    '''                let release_resources =
                    output.boundary_status != NativeBoundaryStatus::Quarantined;
                let settled = self.settle_local(
                    control,
                    &record.request.request_id,
                    output,
                    observed.usage_units,
                )?;
                if release_resources {
                    self.resources
                        .resolve_quarantine_if_present(&record.request.request_id)?;
                } else {
                    self.resources.fence_generation(
                        "terminal reconciliation lacked trusted resource evidence",
                    )?;
                }
                result_from_record(&settled)
''',
)

replace_once(
    durable,
    '''            DriverReconciliation::Pending {
                observed_tokens,
                usage_units: _,
            } => {
                let tokens = merge_observed_tokens(record, observed_tokens);
''',
    '''            DriverReconciliation::Pending {
                observed_tokens,
                usage_units,
            } => {
                let tokens = merge_observed_tokens(record, observed_tokens);
                let usage_units = merge_observed_usage(record, usage_units);
''',
)
replace_once(
    durable,
    '''                let settled = control
                    .settle_native(&record.request.request_id, output)
                    .map_err(control_error)?;
                self.resources
                    .fence_generation("reopened local operation remains pending")?;
''',
    '''                let settled = self.settle_local(
                    control,
                    &record.request.request_id,
                    output,
                    usage_units,
                )?;
                self.resources
                    .fence_generation("reopened local operation remains pending")?;
''',
)
replace_once(
    durable,
    '''                let settled = control
                    .settle_native(&record.request.request_id, output)
                    .map_err(control_error)?;
                self.resources
                    .fence_generation("local driver history missing during recovery")?;
''',
    '''                let settled = self.settle_local(
                    control,
                    &record.request.request_id,
                    output,
                    record.observed_usage_units,
                )?;
                self.resources
                    .fence_generation("local driver history missing during recovery")?;
''',
)
replace_once(
    durable,
    '''                let settled = control
                    .settle_native(&record.request.request_id, output)
                    .map_err(control_error)?;
                self.resources
                    .fence_generation("ambiguous local recovery observation")?;
''',
    '''                let settled = self.settle_local(
                    control,
                    &record.request.request_id,
                    output,
                    record.observed_usage_units,
                )?;
                self.resources
                    .fence_generation("ambiguous local recovery observation")?;
''',
)

replace_once(
    durable,
    '''    fn validate_generation(&self, grant: &VerifiedResourceGrant) -> Result<(), LocalWorkerError> {
''',
    r'''    fn settle_local(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        output: NativeRunOutput,
        usage_units: Option<u64>,
    ) -> Result<NativeRunRecord, LocalWorkerError> {
        control
            .settle_native_with_usage_at(
                request_id,
                output,
                usage_units,
                self.clock.now_ms()?,
            )
            .map_err(control_error)
    }

    async fn interrupt_after_effect(
        &self,
        control: &mut DurableInferenceControl,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
        handle: &AttestedModelHandle,
        admission: &LocalRunAdmission,
        request_resources: super::resources::RequestReservation,
        reason: DriverInterruptReason,
    ) -> Result<LocalRunResult, LocalWorkerError> {
        let boundary_status = match reason {
            DriverInterruptReason::Cancelled => NativeBoundaryStatus::Cancelled,
            DriverInterruptReason::DeadlineElapsed => NativeBoundaryStatus::TimedOut,
        };
        let reconciliation = tokio::time::timeout(
            LOCAL_INTERRUPT_GRACE,
            self.driver
                .interrupt(&admission.request_id, handle, reason),
        )
        .await;
        match reconciliation {
            Ok(Ok(DriverReconciliation::Terminal(observed))) => {
                validate_run_observation(&observed, admission, grant)?;
                if !observed.terminal_observed {
                    return Err(LocalWorkerError::InvalidObservation(
                        "interrupt terminal observation was nonterminal",
                    ));
                }
                let usage_units = observed.usage_units;
                let boundary = self.terminal_boundary(grant, handle, &observed).await;
                let output = terminal_output(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    observed,
                    boundary,
                    Some((boundary_status, reason.as_str().to_string())),
                )?;
                let release_resources =
                    output.boundary_status != NativeBoundaryStatus::Quarantined;
                let settled = self.settle_local(
                    control,
                    &admission.request_id,
                    output,
                    usage_units,
                )?;
                if release_resources {
                    request_resources.complete()?;
                } else {
                    request_resources.quarantine()?;
                    self.resources.fence_generation(
                        "interrupt terminal observation lacked trusted resource evidence",
                    )?;
                }
                result_from_record(&settled)
            }
            Ok(Ok(DriverReconciliation::Pending {
                observed_tokens,
                usage_units,
            })) => {
                let output = indeterminate_output_with_boundary(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    observed_tokens,
                    reason.as_str(),
                    boundary_status,
                );
                let settled = self.settle_local(
                    control,
                    &admission.request_id,
                    output,
                    usage_units,
                )?;
                request_resources.quarantine()?;
                self.resources.fence_generation(
                    "local interrupt left the physical execution pending",
                )?;
                result_from_record(&settled)
            }
            Ok(Ok(DriverReconciliation::MissingHistory)) => {
                let output = indeterminate_output_with_boundary(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    None,
                    "interrupt outcome missing from local driver history",
                    boundary_status,
                );
                let settled =
                    self.settle_local(control, &admission.request_id, output, None)?;
                request_resources.quarantine()?;
                self.resources.fence_generation(
                    "local interrupt outcome is missing and requires reconciliation",
                )?;
                result_from_record(&settled)
            }
            Ok(Ok(DriverReconciliation::Ambiguous { reason: detail })) => {
                let detail = bounded_reason(&detail)?;
                let output = indeterminate_output_with_boundary(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    None,
                    &format!("{}; {detail}", reason.as_str()),
                    boundary_status,
                );
                let settled =
                    self.settle_local(control, &admission.request_id, output, None)?;
                request_resources.quarantine()?;
                self.resources.fence_generation(
                    "local interrupt was ambiguous and requires reconciliation",
                )?;
                result_from_record(&settled)
            }
            Ok(Err(error)) => {
                let output = indeterminate_output_with_boundary(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    None,
                    &format!("{}; interrupt failed: {error}", reason.as_str()),
                    boundary_status,
                );
                let settled =
                    self.settle_local(control, &admission.request_id, output, None)?;
                request_resources.quarantine()?;
                self.resources.fence_generation(
                    "local interrupt failed after effect entry",
                )?;
                result_from_record(&settled)
            }
            Err(_) => {
                let output = indeterminate_output_with_boundary(
                    &admission.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    None,
                    &format!(
                        "{}; interrupt exceeded {} ms",
                        reason.as_str(),
                        LOCAL_INTERRUPT_GRACE.as_millis()
                    ),
                    boundary_status,
                );
                let settled =
                    self.settle_local(control, &admission.request_id, output, None)?;
                request_resources.quarantine()?;
                self.resources.fence_generation(
                    "local interrupt timed out after effect entry",
                )?;
                result_from_record(&settled)
            }
        }
    }

    fn validate_generation(&self, grant: &VerifiedResourceGrant) -> Result<(), LocalWorkerError> {
''',
)

replace_once(
    durable,
    '''fn terminal_output(
    request_id: &str,
    model_id: &str,
    handle_id: &str,
    observed: DriverRunObservation,
    boundary: TerminalBoundary,
) -> Result<NativeRunOutput, LocalWorkerError> {
''',
    '''fn terminal_output(
    request_id: &str,
    model_id: &str,
    handle_id: &str,
    observed: DriverRunObservation,
    boundary: TerminalBoundary,
    forced_boundary: Option<(NativeBoundaryStatus, String)>,
) -> Result<NativeRunOutput, LocalWorkerError> {
''',
)
replace_once(
    durable,
    '''            observed,
            boundary,
        )?;
''',
    '''            observed,
            boundary,
            None,
        )?;
''',
)
replace_once(
    durable,
    '''                    observed,
                    boundary,
                )?;
''',
    '''                    observed,
                    boundary,
                    None,
                )?;
''',
)
replace_once(
    durable,
    '''    let receipt_digest = local_terminal_receipt_digest(
''',
    '''    let (boundary_status, stop_reason) =
        if boundary_status != NativeBoundaryStatus::Quarantined
            && let Some((forced, reason)) = forced_boundary
        {
            (forced, Some(reason))
        } else {
            (boundary_status, stop_reason)
        };
    let receipt_digest = local_terminal_receipt_digest(
''',
)

replace_once(
    durable,
    '''fn indeterminate_output(
    request_id: &str,
    model_id: &str,
    handle_id: &str,
    observed_tokens: Option<u64>,
    reason: &str,
) -> NativeRunOutput {
    NativeRunOutput {
''',
    '''fn indeterminate_output(
    request_id: &str,
    model_id: &str,
    handle_id: &str,
    observed_tokens: Option<u64>,
    reason: &str,
) -> NativeRunOutput {
    indeterminate_output_with_boundary(
        request_id,
        model_id,
        handle_id,
        observed_tokens,
        reason,
        NativeBoundaryStatus::Quarantined,
    )
}

fn indeterminate_output_with_boundary(
    request_id: &str,
    model_id: &str,
    handle_id: &str,
    observed_tokens: Option<u64>,
    reason: &str,
    boundary_status: NativeBoundaryStatus,
) -> NativeRunOutput {
    NativeRunOutput {
''',
)
replace_once(
    durable,
    '''        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Quarantined,
        output: String::new(),
''',
    '''        status: NativeRunStatus::Indeterminate,
        boundary_status,
        output: String::new(),
''',
)

replace_once(
    durable,
    '''    let status = match output.status {
        NativeRunStatus::Completed => LocalRunStatus::Succeeded,
        NativeRunStatus::Failed => LocalRunStatus::Failed,
        NativeRunStatus::Interrupted => LocalRunStatus::Interrupted,
        NativeRunStatus::Indeterminate => LocalRunStatus::Indeterminate,
    };
''',
    '''    let status = if output.boundary_status == NativeBoundaryStatus::Quarantined {
        LocalRunStatus::Indeterminate
    } else if matches!(
        output.boundary_status,
        NativeBoundaryStatus::Cancelled | NativeBoundaryStatus::TimedOut
    ) {
        LocalRunStatus::Interrupted
    } else {
        match output.status {
            NativeRunStatus::Completed => LocalRunStatus::Succeeded,
            NativeRunStatus::Failed => LocalRunStatus::Failed,
            NativeRunStatus::Interrupted => LocalRunStatus::Interrupted,
            NativeRunStatus::Indeterminate => LocalRunStatus::Indeterminate,
        }
    };
''',
)
replace_once(
    durable,
    '''        observed_usage_units: None,
        terminal_observed: output.terminal_observed,
        quarantined: output.boundary_status == NativeBoundaryStatus::Quarantined,
''',
    '''        observed_usage_units: record.observed_usage_units,
        terminal_observed: output.terminal_observed,
        quarantined: record.state != NativeReservationState::Released
            || output.boundary_status == NativeBoundaryStatus::Quarantined,
''',
)

insert_before_once(
    durable,
    "\nfn resource_matches(\n",
    r'''
fn merge_observed_usage(record: &NativeRunRecord, next: Option<u64>) -> Option<u64> {
    match (record.observed_usage_units, next) {
        (Some(previous), Some(candidate)) => Some(previous.max(candidate)),
        (Some(previous), None) => Some(previous),
        (None, candidate) => candidate,
    }
}

''',
)

# ---------------------------------------------------------------------------
# Recovery snapshot consumes persisted age evidence first.
# ---------------------------------------------------------------------------
recovery = "codex-rs/hepta-infer-worker-host/src/native_recovery.rs"
replace_once(
    recovery,
    '''    /// `first_indeterminate_ms` is an operator-owned monotonic projection. The
    /// current v1 journal has no trusted wall-clock field, so age is reported
    /// only when every currently indeterminate request has supplied evidence.
''',
    '''    /// New journal records carry the first durable indeterminate observation
    /// time. `first_indeterminate_ms` remains a compatibility projection for
    /// historical records that predate persisted age evidence.
''',
)
replace_once(
    recovery,
    '''                match first_indeterminate_ms.get(&record.request.request_id) {
                    Some(first_seen) if *first_seen <= now_ms => {
                        oldest_indeterminate_age_ms =
                            oldest_indeterminate_age_ms.max(now_ms - *first_seen);
                    }
                    _ => age_evidence_complete = false,
                }
''',
    '''                let first_seen = record.first_indeterminate_at_unix_ms.or_else(|| {
                    first_indeterminate_ms
                        .get(&record.request.request_id)
                        .copied()
                });
                match first_seen {
                    Some(first_seen) if first_seen <= now_ms => {
                        oldest_indeterminate_age_ms =
                            oldest_indeterminate_age_ms.max(now_ms - first_seen);
                    }
                    _ => age_evidence_complete = false,
                }
''',
)

# ---------------------------------------------------------------------------
# Replace brittle source-text ordering assertion with an actual paused runtime
# event sequence in the real Agentd/App Server product test.
# ---------------------------------------------------------------------------
app_tests = "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs"
replace_once(
    app_tests,
    '''#[test]
fn cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start() {
    let source = include_str!("native_app_server.rs");
    let durable_dispatch = source
        .find("control.dispatch_native_with_pre_effect_abort(")
        .expect("durable native dispatch");
    let revalidation = source
        .find("owner.revalidate_cognitive_context(snapshot).await")
        .expect("final-use cognitive revalidation");
    let turn_start = source
        .find("client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart")
        .expect("physical turn start");
    let durable_stop = source
        .find("control.abort_native_before_effect(")
        .expect("durable pre-turn stop");
    assert!(durable_dispatch < revalidation);
    assert!(revalidation < turn_start);
    assert!(durable_stop < turn_start);
}

''',
    "",
)
replace_once(
    app_tests,
    '''    let accepted = driver
        .run(
            &mut durable,
            NativeAdmission {
                request_id: ACCEPT_REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            "answer from the verified memory".to_string(),
            Some("lemon".to_string()),
            &CancellationToken::new(),
        )
        .await?;
''',
    r'''    let sequence_hook = Arc::new(FinalRevalidationTestHook {
        reached: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    install_final_revalidation_test_hook(Arc::clone(&sequence_hook));
    let accepted_cancellation = CancellationToken::new();
    let accepted_run = driver.run(
        &mut durable,
        NativeAdmission {
            request_id: ACCEPT_REQUEST_ID.to_string(),
            maximum_in_flight: 1,
        },
        "answer from the verified memory".to_string(),
        Some("lemon".to_string()),
        &accepted_cancellation,
    );
    let persisted_before_effect = async {
        sequence_hook.reached.notified().await;
        let journal_text = std::fs::read_to_string(&journal)?;
        assert!(journal_text.contains("\"Dispatch\""));
        assert!(journal_text.contains(ACCEPT_REQUEST_ID));
        assert!(journal_text.contains("\"codex_request_digest\""));
        assert!(journal_text.contains("\"codex_authority_witness_sha256\""));
        assert!(!journal_text.contains("\"Started\""));
        assert_eq!(
            response_mock.requests().len(),
            0,
            "physical provider request must not precede final-use revalidation"
        );
        sequence_hook.release.notify_one();
        Ok::<_, Box<dyn std::error::Error + Send + Sync>>(())
    };
    let accepted = match tokio::time::timeout(Duration::from_secs(30), async {
        let (worker_result, sequence_result) =
            tokio::join!(accepted_run, persisted_before_effect);
        sequence_result?;
        worker_result
    })
    .await
    {
        Ok(result) => result?,
        Err(_) => return Err("timed out proving durable-before-effect sequence".into()),
    };
''',
)

# ---------------------------------------------------------------------------
# Test fixtures and regressions for interrupt, persistent usage, and age.
# ---------------------------------------------------------------------------
local_tests = "codex-rs/hepta-infer-worker-host/src/experimental_local_tests.rs"
replace_once(
    local_tests,
    '''    inspections: AtomicUsize,
    failed_load_cleanups: AtomicUsize,
''',
    '''    inspections: AtomicUsize,
    interrupts: AtomicUsize,
    failed_load_cleanups: AtomicUsize,
''',
)
replace_once(
    local_tests,
    '''    fail_unload: AtomicBool,
    corrupt_load_identity: AtomicBool,
    run_observation: Mutex<DriverRunObservation>,
    reconciliation: Mutex<DriverReconciliation>,
''',
    '''    fail_unload: AtomicBool,
    corrupt_load_identity: AtomicBool,
    hang_run: AtomicBool,
    run_observation: Mutex<DriverRunObservation>,
    reconciliation: Mutex<DriverReconciliation>,
    interrupt_reconciliation: Mutex<DriverReconciliation>,
''',
)
replace_once(
    local_tests,
    '''                inspections: AtomicUsize::new(0),
                failed_load_cleanups: AtomicUsize::new(0),
''',
    '''                inspections: AtomicUsize::new(0),
                interrupts: AtomicUsize::new(0),
                failed_load_cleanups: AtomicUsize::new(0),
''',
)
replace_once(
    local_tests,
    '''                fail_unload: AtomicBool::new(false),
                corrupt_load_identity: AtomicBool::new(false),
                run_observation: Mutex::new(success_observation()),
                reconciliation: Mutex::new(DriverReconciliation::MissingHistory),
''',
    '''                fail_unload: AtomicBool::new(false),
                corrupt_load_identity: AtomicBool::new(false),
                hang_run: AtomicBool::new(false),
                run_observation: Mutex::new(success_observation()),
                reconciliation: Mutex::new(DriverReconciliation::MissingHistory),
                interrupt_reconciliation: Mutex::new(
                    DriverReconciliation::MissingHistory,
                ),
''',
)
replace_once(
    local_tests,
    '''        self.state.runs.fetch_add(1, Ordering::SeqCst);
        let observed = self
            .state
            .run_observation
            .lock()
            .expect("run observation lock")
            .clone();
        Box::pin(async move { Ok(observed) })
    }

    fn inspect<'a>(
''',
    '''        self.state.runs.fetch_add(1, Ordering::SeqCst);
        if self.state.hang_run.load(Ordering::SeqCst) {
            return Box::pin(std::future::pending());
        }
        let observed = self
            .state
            .run_observation
            .lock()
            .expect("run observation lock")
            .clone();
        Box::pin(async move { Ok(observed) })
    }

    fn interrupt<'a>(
        &'a self,
        _operation_id: &'a str,
        _handle: &'a AttestedModelHandle,
        _reason: DriverInterruptReason,
    ) -> LocalFuture<'a, DriverReconciliation> {
        self.state.interrupts.fetch_add(1, Ordering::SeqCst);
        let observed = self
            .state
            .interrupt_reconciliation
            .lock()
            .expect("interrupt reconciliation lock")
            .clone();
        Box::pin(async move { Ok(observed) })
    }

    fn inspect<'a>(
''',
)

path = ROOT / local_tests
text = path.read_text(encoding="utf-8")
addition = r'''

#[tokio::test]
async fn mid_run_cancellation_interrupts_once_and_persists_usage_and_age() {
    let (grant, _) = signed_grant(512);
    let manifest = manifest(&grant);
    let driver = FakeDriver::new();
    driver.state.hang_run.store(true, Ordering::SeqCst);
    *driver
        .state
        .interrupt_reconciliation
        .lock()
        .expect("interrupt reconciliation") = DriverReconciliation::Pending {
        observed_tokens: Some(3),
        usage_units: Some(5),
    };
    let worker = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("worker");
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    let directory = tempdir().expect("tempdir");
    let journal = directory.path().join("local-cancel.journal");
    let mut control = DurableInferenceControl::open(&journal, 64).expect("control");
    let cancellation = CancellationToken::new();
    let verified_input = input();

    let run = worker.run(
        &mut control,
        &grant,
        &manifest,
        &handle,
        admission("request.local.cancel"),
        &verified_input,
        &cancellation,
    );
    let cancel = async {
        tokio::task::yield_now().await;
        cancellation.cancel();
    };
    let (result, ()) = tokio::join!(run, cancel);
    let result = result.expect("cancelled result");
    assert_eq!(result.status, LocalRunStatus::Interrupted);
    assert_eq!(result.observed_tokens, Some(3));
    assert_eq!(result.observed_usage_units, Some(5));
    assert!(result.quarantined);
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 1);
    assert_eq!(driver.state.interrupts.load(Ordering::SeqCst), 1);

    let record = control
        .native_record("request.local.cancel")
        .expect("durable cancelled record");
    assert_eq!(
        record
            .observation
            .as_ref()
            .expect("cancelled observation")
            .boundary_status,
        codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus::Cancelled
    );
    assert_eq!(record.observed_usage_units, Some(5));
    assert_eq!(record.first_indeterminate_at_unix_ms, Some(1_000));
    assert_eq!(record.last_observed_at_unix_ms, Some(1_000));
    let resources = worker.resources().snapshot().expect("resource snapshot");
    assert_eq!(resources.active_or_quarantined_requests, 1);
    assert_eq!(resources.request_bytes, 20);
    assert!(resources.fenced_reason.is_some());
}

#[tokio::test]
async fn worker_deadline_interrupts_hung_driver_without_replay() {
    let (grant, _) = signed_grant(512);
    let manifest = manifest(&grant);
    let driver = FakeDriver::new();
    driver.state.hang_run.store(true, Ordering::SeqCst);
    *driver
        .state
        .interrupt_reconciliation
        .lock()
        .expect("interrupt reconciliation") = DriverReconciliation::Ambiguous {
        reason: "runtime did not acknowledge interrupt".to_string(),
    };
    let worker = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("worker");
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    let directory = tempdir().expect("tempdir");
    let journal = directory.path().join("local-deadline.journal");
    let mut control = DurableInferenceControl::open(&journal, 64).expect("control");
    let mut bounded = admission("request.local.deadline");
    bounded.requested_deadline_ms = 1_001;
    let verified_input = input();
    let cancellation = CancellationToken::new();

    let result = worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            bounded.clone(),
            &verified_input,
            &cancellation,
        )
        .await
        .expect("deadline result");
    assert_eq!(result.status, LocalRunStatus::Interrupted);
    assert!(result.quarantined);
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 1);
    assert_eq!(driver.state.interrupts.load(Ordering::SeqCst), 1);
    let record = control
        .native_record("request.local.deadline")
        .expect("deadline record");
    assert_eq!(
        record
            .observation
            .as_ref()
            .expect("deadline observation")
            .boundary_status,
        codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus::TimedOut
    );

    *driver
        .state
        .reconciliation
        .lock()
        .expect("reconciliation") = DriverReconciliation::MissingHistory;
    let reopened = worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            bounded,
            &verified_input,
            &CancellationToken::new(),
        )
        .await
        .expect("recovery remains indeterminate");
    assert!(reopened.quarantined);
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 1);
    assert_eq!(driver.state.inspections.load(Ordering::SeqCst), 1);
}
'''
if addition.strip() in text:
    raise SystemExit("experimental_local_tests.rs: tests already present")
path.write_text(text.rstrip() + addition + "\n", encoding="utf-8")

native_tests = ROOT / "codex-rs/hepta-infer-core/src/native_control_tests.rs"
text = native_tests.read_text(encoding="utf-8")
addition = r'''

#[test]
fn generic_usage_and_indeterminate_age_are_durable_and_monotonic() {
    let path = path("usage-age");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let unknown = control
        .settle_native_with_usage_at(
            "r1",
            output(NativeRunStatus::Indeterminate, Some(4)),
            Some(11),
            1_000,
        )
        .unwrap();
    assert_eq!(unknown.observed_usage_units, Some(11));
    assert_eq!(unknown.first_indeterminate_at_unix_ms, Some(1_000));
    assert_eq!(unknown.last_observed_at_unix_ms, Some(1_000));
    assert_eq!(
        control.settle_native_with_usage_at(
            "r1",
            output(NativeRunStatus::Indeterminate, Some(4)),
            Some(10),
            1_001,
        ),
        Err(Error::Conflict)
    );
    assert_eq!(
        control.settle_native_with_usage_at(
            "r1",
            output(NativeRunStatus::Indeterminate, Some(4)),
            Some(11),
            999,
        ),
        Err(Error::Conflict)
    );
    drop(control);

    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let terminal = control
        .settle_native_with_usage_at(
            "r1",
            output(NativeRunStatus::Completed, Some(7)),
            Some(13),
            1_300,
        )
        .unwrap();
    assert_eq!(terminal.state, NativeReservationState::Released);
    assert_eq!(terminal.observed_usage_units, Some(13));
    assert_eq!(terminal.first_indeterminate_at_unix_ms, Some(1_000));
    assert_eq!(terminal.last_observed_at_unix_ms, Some(1_300));
    drop(control);

    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&terminal));
    drop(control);
    std::fs::remove_file(path).unwrap();
}
'''
if addition.strip() in text:
    raise SystemExit("native_control_tests.rs: test already present")
native_tests.write_text(text.rstrip() + addition + "\n", encoding="utf-8")

# ---------------------------------------------------------------------------
# Documentation: split source/composition/external status and record new
# cancellation, usage, and age semantics.
# ---------------------------------------------------------------------------
technical = "docs/modules/inference.worker/TECHNICAL.md"
replace_once(
    technical,
    '''#### `INFER-V4-T4`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
''',
    '''#### `INFER-V4-T4`

- Source implementation state: `source_implemented`.
- Product composition state: `product_composition_pending`.
- External qualification state: `external_qualification_pending`.
- Canonical package state remains `planned`; priority: `2`; parallel class: `contract_coordinated`.
''',
)
replace_once(
    technical,
    '''#### `INFER-V4-T5`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
''',
    '''#### `INFER-V4-T5`

- Source implementation state: `source_implemented`.
- Product composition state: `product_composition_pending`.
- External qualification state: `external_qualification_pending`.
- Canonical package state remains `planned`; priority: `2`; parallel class: `contract_coordinated`.
''',
)

runbook = ROOT / "docs/modules/inference.worker/RECOVERY_AND_OPERATIONS.md"
text = runbook.read_text(encoding="utf-8")
needle = '''The v1 journal does not contain a trusted wall-clock timestamp for first
indeterminate observation. Age is reportable only when an operator-owned
monotonic projection supplies evidence for every current indeterminate record;
otherwise `age_evidence_complete` is false and age is `None`.
'''
replacement = '''New native observations persist their host observation time and the first
indeterminate time. `oldest_indeterminate_age_ms` therefore survives restart
for new records. Historical records may still require the operator-owned
compatibility projection; when neither source is available,
`age_evidence_complete` is false and age is `None`.

Experimental local observations also persist independently bounded
`usage_units`; an absent value remains unknown. Mid-run cancellation and
deadline expiry are owned by the worker rather than delegated to driver
cooperation: the in-flight future is dropped, the driver receives one bounded
interrupt/reconcile call, and any missing, pending, ambiguous, failed or timed
out interrupt retains request resources and fences the generation. A later
invocation may inspect the original operation but may never call `run` again.
'''
if text.count(needle) != 1:
    raise SystemExit("RECOVERY_AND_OPERATIONS.md: age paragraph not found exactly once")
runbook.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

print("stage-a patch applied")
