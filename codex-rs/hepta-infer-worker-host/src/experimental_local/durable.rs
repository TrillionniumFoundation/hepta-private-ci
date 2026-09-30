use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use std::time::Duration;

use serde::Serialize;
use tokio_util::sync::CancellationToken;

use super::AttestedModelHandle;
use super::DriverInterruptReason;
use super::DriverLoadObservation;
use super::DriverReconciliation;
use super::DriverRunObservation;
use super::DriverTerminalStatus;
use super::LocalModelDriver;
use super::LocalWorkerError;
use super::ResourceManager;
use super::TrustedClock;
use super::TrustedReleaseObservation;
use super::TrustedResourceObservation;
use super::TrustedResourceObserver;
use super::VerifiedInput;
use super::VerifiedModelManifest;
use super::VerifiedResourceGrant;
use super::digest;
use super::validate_digest;
use super::validate_identity;

const LOCAL_PROVIDER_ID: &str = "local.model.experimental";
const MAX_LOCAL_OUTPUT_BYTES: usize = 1024 * 1024;
const LOCAL_INTERRUPT_GRACE: Duration = Duration::from_secs(3);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalRunAdmission {
    pub request_id: String,
    pub maximum_in_flight: usize,
    pub maximum_tokens: u32,
    pub maximum_usage_units: u64,
    pub expected_transient_memory_bytes: u64,
    pub requested_deadline_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalRunStatus {
    Succeeded,
    Failed,
    Interrupted,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalRunResult {
    pub request_id: String,
    pub status: LocalRunStatus,
    pub output_digest: Option<String>,
    pub observed_tokens: Option<u64>,
    pub observed_usage_units: Option<u64>,
    pub terminal_observed: bool,
    pub quarantined: bool,
    pub stop_reason: Option<String>,
    pub receipt_digest: Option<String>,
}

pub struct DurableLocalModelWorker<D, O, C> {
    driver: D,
    observer: O,
    clock: C,
    resources: ResourceManager,
    worker_subject: String,
    generation: u64,
    grant_witness_digest: String,
}

impl<D, O, C> DurableLocalModelWorker<D, O, C>
where
    D: LocalModelDriver,
    O: TrustedResourceObserver,
    C: TrustedClock,
{
    pub fn new(
        driver: D,
        observer: O,
        clock: C,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalWorkerError> {
        let worker_subject = grant.worker_subject().to_string();
        let generation = grant.worker_generation();
        grant.ensure_current(&clock, &worker_subject, generation)?;
        Ok(Self {
            driver,
            observer,
            clock,
            resources: ResourceManager::new(grant),
            worker_subject,
            generation,
            grant_witness_digest: grant.witness_digest().to_string(),
        })
    }

    pub fn resources(&self) -> &ResourceManager {
        &self.resources
    }

    pub async fn load_model(
        &self,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
    ) -> Result<AttestedModelHandle, LocalWorkerError> {
        self.validate_generation(grant)?;
        let mut reservation = self
            .resources
            .reserve_model(manifest.expected_resident_memory_bytes())?;
        let load = match self.driver.load(manifest, grant).await {
            Ok(load) => load,
            Err(error) => return Err(error),
        };
        let observed = match self
            .observer
            .observe_model(&load.handle_id, &load.device_uuid, self.generation)
            .await
        {
            Ok(observed) => observed,
            Err(error) => {
                if !self.cleanup_failed_load(&load, grant).await {
                    reservation.retain_for_repair(
                        "trusted resource observation failed after physical model load and cleanup was not independently confirmed",
                    )?;
                }
                return Err(error);
            }
        };
        let handle = match AttestedModelHandle::attest(load.clone(), observed, manifest, grant) {
            Ok(handle) => handle,
            Err(error) => {
                if !self.cleanup_failed_load(&load, grant).await {
                    reservation.retain_for_repair(
                        "loaded model failed trusted attestation and cleanup was not independently confirmed",
                    )?;
                }
                return Err(error);
            }
        };
        if let Err(error) = reservation.commit(&handle) {
            let cleanup = self.driver.unload(&handle).await;
            let release = self.observer.observe_release(&handle).await;
            let cleanup_confirmed = matches!(cleanup, Ok(value) if value.terminal_observed)
                && matches!(release, Ok(value) if release_matches(&value, &handle));
            if !cleanup_confirmed {
                reservation.retain_for_repair(
                    "model exceeded aggregate capacity and cleanup was not independently confirmed",
                )?;
            }
            return Err(error);
        }
        Ok(handle)
    }

    async fn cleanup_failed_load(
        &self,
        load: &DriverLoadObservation,
        grant: &VerifiedResourceGrant,
    ) -> bool {
        let cleanup = self.driver.cleanup_failed_load(load).await;
        let released = self
            .observer
            .observe_unattested_release(&load.handle_id, &load.device_uuid, self.generation)
            .await;
        matches!(cleanup, Ok(value) if value.terminal_observed)
            && matches!(released, Ok(value) if unattested_release_matches(&value, load, grant))
    }

    pub async fn unload_model(
        &self,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
        handle: &AttestedModelHandle,
    ) -> Result<(), LocalWorkerError> {
        self.validate_generation(grant)?;
        handle.verify_for(manifest, grant)?;
        self.resources.begin_unload(handle)?;
        let unloaded = match self.driver.unload(handle).await {
            Ok(value) => value,
            Err(error) => {
                self.resources.fail_unload(handle)?;
                return Err(error);
            }
        };
        if !unloaded.terminal_observed {
            self.resources.fail_unload(handle)?;
            return Err(LocalWorkerError::InvalidObservation(
                "driver did not observe terminal unload",
            ));
        }
        let released = match self.observer.observe_release(handle).await {
            Ok(value) => value,
            Err(error) => {
                self.resources.fail_unload(handle)?;
                return Err(error);
            }
        };
        if !release_matches(&released, handle) {
            self.resources.fail_unload(handle)?;
            self.resources
                .fence_generation("unload lacked trusted zero-residency observation")?;
            return Err(LocalWorkerError::InvalidObservation(
                "trusted release observation mismatch",
            ));
        }
        self.resources.complete_unload(handle)
    }

    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
        handle: &AttestedModelHandle,
        admission: LocalRunAdmission,
        input: &VerifiedInput,
        cancellation: &CancellationToken,
    ) -> Result<LocalRunResult, LocalWorkerError> {
        self.validate_generation(grant)?;
        handle.verify_for(manifest, grant)?;
        validate_admission(&admission, grant)?;
        let deadline = grant.bind_deadline(&self.clock, admission.requested_deadline_ms)?;
        let payload_digest = local_payload_digest(
            grant,
            manifest,
            handle,
            &admission,
            input,
            deadline.as_millis(),
        )?;
        let request = NativeRequest {
            request_id: admission.request_id.clone(),
            principal_id: self.worker_subject.clone(),
            worker_generation: self.generation,
            model: manifest.model_id().to_string(),
            payload_digest,
        };
        let record = control
            .reserve_native(request, admission.maximum_in_flight)
            .map_err(control_error)?;
        if record.state != NativeReservationState::Reserved {
            return self
                .recover_existing(control, grant, manifest, handle, &admission, &record)
                .await;
        }

        let request_resources = match self.resources.reserve_request(
            &admission.request_id,
            handle,
            admission.expected_transient_memory_bytes,
        ) {
            Ok(reservation) => reservation,
            Err(error) => {
                control
                    .stop_native_before_dispatch(
                        &admission.request_id,
                        "local aggregate resource admission denied".to_string(),
                    )
                    .map_err(control_error)?;
                return Err(error);
            }
        };
        let dispatch = NativeDispatch {
            thread_id: handle.handle_id().to_string(),
            model_provider: LOCAL_PROVIDER_ID.to_string(),
            context_digest: grant.witness_digest().to_string(),
            owner_context_digest: Some(manifest.semantic_digest().to_string()),
            codex_payload_digest: None,
            codex_request_digest: None,
            app_server_version: None,
            protocol_id: None,
            codex_source_admission_digest: None,
            codex_home_digest: None,
            codex_connection_id: None,
            codex_session_id: None,
            codex_deadline_ms: None,
            codex_authority_epoch: None,
            codex_revocation_revision: None,
            codex_revocation_head_sha256: None,
            codex_authority_witness_sha256: None,
        };
        let (_dispatch_record, abort_token) = control
            .dispatch_native_with_pre_effect_abort(&admission.request_id, dispatch)
            .map_err(control_error)?;
        if cancellation.is_cancelled() || deadline.is_expired(&self.clock)? {
            let reason = if cancellation.is_cancelled() {
                "cancelled before local effect entry"
            } else {
                "deadline elapsed before local effect entry"
            };
            control
                .abort_native_before_effect(abort_token, reason.to_string())
                .map_err(control_error)?;
            request_resources.complete()?;
            return Err(if cancellation.is_cancelled() {
                LocalWorkerError::Driver(reason.to_string())
            } else {
                LocalWorkerError::DeadlineExpired
            });
        }
        if let Err(error) =
            control.native_started(&admission.request_id, admission.request_id.clone())
        {
            control
                .abort_native_before_effect(
                    abort_token,
                    "failed to persist local effect entry".to_string(),
                )
                .map_err(control_error)?;
            request_resources.complete()?;
            return Err(control_error(error));
        }
        drop(abort_token);
        if let Err(error) = request_resources.mark_running() {
            let output = indeterminate_output(
                &admission.request_id,
                manifest.model_id(),
                handle.handle_id(),
                None,
                "local resource ledger failed after durable effect entry; no replay permitted",
            );
            let settled = control
                .settle_native(&admission.request_id, output)
                .map_err(control_error)?;
            request_resources.quarantine()?;
            self.resources
                .fence_generation("local resource ledger failed after effect entry")?;
            let mut result = result_from_record(&settled)?;
            result.stop_reason = Some(format!(
                "{}; {error}",
                result.stop_reason.unwrap_or_default()
            ));
            return Ok(result);
        }

        let now_ms = self.clock.now_ms()?;
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
        validate_run_observation(&observed, &admission, grant)?;
        if !observed.terminal_observed {
            let output = indeterminate_output(
                &admission.request_id,
                manifest.model_id(),
                handle.handle_id(),
                observed.observed_tokens,
                observed
                    .stop_reason
                    .as_deref()
                    .unwrap_or("driver reported nonterminal local execution"),
            );
            let settled = self.settle_local(
                control,
                &admission.request_id,
                output,
                observed.usage_units,
            )?;
            request_resources.quarantine()?;
            self.resources
                .fence_generation("nonterminal local execution requires reconciliation")?;
            return result_from_record(&settled);
        }

        let boundary = self.terminal_boundary(grant, handle, &observed).await;
        let output = terminal_output(
            &admission.request_id,
            manifest.model_id(),
            handle.handle_id(),
            observed,
            boundary,
            None,
        )?;
        let release_resources =
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
    }

    async fn recover_existing(
        &self,
        control: &mut DurableInferenceControl,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
        handle: &AttestedModelHandle,
        admission: &LocalRunAdmission,
        record: &NativeRunRecord,
    ) -> Result<LocalRunResult, LocalWorkerError> {
        validate_existing_binding(record, grant, manifest, handle)?;
        if record
            .observation
            .as_ref()
            .is_some_and(|output| output.terminal_observed)
        {
            return result_from_record(record);
        }
        let reconciled = self
            .driver
            .inspect(&record.request.request_id, handle)
            .await?;
        match reconciled {
            DriverReconciliation::Terminal(observed) => {
                validate_run_observation(&observed, admission, grant)?;
                if !observed.terminal_observed {
                    return Err(LocalWorkerError::InvalidObservation(
                        "terminal reconciliation was nonterminal",
                    ));
                }
                let boundary = self.terminal_boundary(grant, handle, &observed).await;
                let output = terminal_output(
                    &record.request.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    observed,
                    boundary,
                    None,
                )?;
                let release_resources =
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
            }
            DriverReconciliation::Pending {
                observed_tokens,
                usage_units,
            } => {
                let tokens = merge_observed_tokens(record, observed_tokens);
                let usage_units = merge_observed_usage(record, usage_units);
                let output = indeterminate_output(
                    &record.request.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    tokens,
                    "local operation is still pending during reconciliation",
                );
                let settled = self.settle_local(
                    control,
                    &record.request.request_id,
                    output,
                    usage_units,
                )?;
                self.resources
                    .fence_generation("reopened local operation remains pending")?;
                result_from_record(&settled)
            }
            DriverReconciliation::MissingHistory => {
                let output = indeterminate_output(
                    &record.request.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    merge_observed_tokens(record, None),
                    "local driver history is missing; operation quarantined without replay",
                );
                let settled = self.settle_local(
                    control,
                    &record.request.request_id,
                    output,
                    record.observed_usage_units,
                )?;
                self.resources
                    .fence_generation("local driver history missing during recovery")?;
                result_from_record(&settled)
            }
            DriverReconciliation::Ambiguous { reason } => {
                let reason = bounded_reason(&reason)?;
                let output = indeterminate_output(
                    &record.request.request_id,
                    manifest.model_id(),
                    handle.handle_id(),
                    merge_observed_tokens(record, None),
                    &reason,
                );
                let settled = self.settle_local(
                    control,
                    &record.request.request_id,
                    output,
                    record.observed_usage_units,
                )?;
                self.resources
                    .fence_generation("ambiguous local recovery observation")?;
                result_from_record(&settled)
            }
        }
    }

    async fn terminal_boundary(
        &self,
        grant: &VerifiedResourceGrant,
        handle: &AttestedModelHandle,
        observed: &DriverRunObservation,
    ) -> TerminalBoundary {
        if let Err(error) = grant.ensure_current(&self.clock, &self.worker_subject, self.generation)
        {
            let _ = self
                .resources
                .fence_generation("resource grant was no longer current at terminal observation");
            return TerminalBoundary::Quarantined(error.to_string());
        }
        match self
            .observer
            .observe_model(handle.handle_id(), handle.device_uuid(), self.generation)
            .await
        {
            Ok(resource) if resource_matches(&resource, handle, grant) => {
                if observed.status == DriverTerminalStatus::Succeeded {
                    TerminalBoundary::Authorized
                } else {
                    TerminalBoundary::Observed
                }
            }
            Ok(_) => {
                let _ = self.resources.fence_generation(
                    "terminal local execution had a mismatched trusted resource observation",
                );
                TerminalBoundary::Quarantined(
                    "trusted terminal resource observation mismatch".to_string(),
                )
            }
            Err(error) => {
                let _ = self.resources.fence_generation(
                    "terminal local execution lacked trusted resource observation",
                );
                TerminalBoundary::Quarantined(error.to_string())
            }
        }
    }

    fn settle_local(
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
        if grant.witness_digest() != self.grant_witness_digest {
            return Err(LocalWorkerError::InvalidGrant(
                "process grant changed without a new generation",
            ));
        }
        grant.ensure_current(&self.clock, &self.worker_subject, self.generation)?;
        self.resources
            .ensure_current(self.generation, grant.device_epoch())
    }
}

#[derive(Clone, Debug)]
enum TerminalBoundary {
    Authorized,
    Observed,
    Quarantined(String),
}

fn validate_admission(
    admission: &LocalRunAdmission,
    grant: &VerifiedResourceGrant,
) -> Result<(), LocalWorkerError> {
    validate_identity(&admission.request_id, "local request")?;
    if admission.maximum_in_flight == 0
        || admission.maximum_in_flight
            > usize::try_from(grant.maximum_concurrency())
                .map_err(|_| LocalWorkerError::ArithmeticOverflow)?
        || admission.maximum_tokens == 0
        || admission.maximum_tokens > grant.maximum_tokens()
        || admission.maximum_usage_units == 0
        || admission.maximum_usage_units > grant.claims().maximum_usage_units
        || admission.expected_transient_memory_bytes > grant.maximum_aggregate_memory_bytes()
    {
        return Err(LocalWorkerError::CapacityExceeded);
    }
    Ok(())
}

fn validate_run_observation(
    observed: &DriverRunObservation,
    admission: &LocalRunAdmission,
    grant: &VerifiedResourceGrant,
) -> Result<(), LocalWorkerError> {
    if observed.output.len() > MAX_LOCAL_OUTPUT_BYTES
        || observed
            .stop_reason
            .as_ref()
            .is_some_and(|reason| reason.is_empty() || reason.len() > 4096)
        || observed.terminal_observed == (observed.status == DriverTerminalStatus::Indeterminate)
        || observed
            .observed_tokens
            .is_some_and(|tokens| tokens > u64::from(admission.maximum_tokens))
        || observed
            .observed_tokens
            .is_some_and(|tokens| tokens > u64::from(grant.maximum_tokens()))
        || observed
            .usage_units
            .is_some_and(|usage| usage > admission.maximum_usage_units)
        || observed
            .usage_units
            .is_some_and(|usage| usage > grant.claims().maximum_usage_units)
    {
        return Err(LocalWorkerError::InvalidObservation(
            "local run observation violated bounds or terminality",
        ));
    }
    Ok(())
}

fn validate_existing_binding(
    record: &NativeRunRecord,
    grant: &VerifiedResourceGrant,
    manifest: &VerifiedModelManifest,
    handle: &AttestedModelHandle,
) -> Result<(), LocalWorkerError> {
    if record.request.principal_id != grant.worker_subject()
        || record.request.worker_generation != grant.worker_generation()
        || record.request.model != manifest.model_id()
    {
        return Err(LocalWorkerError::InvalidTransition(
            "durable local request binding changed",
        ));
    }
    if let Some(dispatch) = &record.dispatch
        && (dispatch.thread_id != handle.handle_id()
            || dispatch.model_provider != LOCAL_PROVIDER_ID
            || dispatch.context_digest != grant.witness_digest()
            || dispatch.owner_context_digest.as_deref() != Some(manifest.semantic_digest()))
    {
        return Err(LocalWorkerError::InvalidTransition(
            "durable local dispatch binding changed",
        ));
    }
    Ok(())
}

#[derive(Serialize)]
struct LocalPayloadBinding<'a> {
    schema: &'static str,
    request_id: &'a str,
    worker_subject: &'a str,
    worker_generation: u64,
    grant_witness_digest: &'a str,
    manifest_semantic_digest: &'a str,
    handle_id: &'a str,
    handle_attestation_digest: &'a str,
    input_digest: &'a str,
    maximum_tokens: u32,
    maximum_usage_units: u64,
    expected_transient_memory_bytes: u64,
    deadline_ms: u64,
}

fn local_payload_digest(
    grant: &VerifiedResourceGrant,
    manifest: &VerifiedModelManifest,
    handle: &AttestedModelHandle,
    admission: &LocalRunAdmission,
    input: &VerifiedInput,
    deadline_ms: u64,
) -> Result<String, LocalWorkerError> {
    let binding = LocalPayloadBinding {
        schema: "hepta.local-model-operation.v1",
        request_id: &admission.request_id,
        worker_subject: grant.worker_subject(),
        worker_generation: grant.worker_generation(),
        grant_witness_digest: grant.witness_digest(),
        manifest_semantic_digest: manifest.semantic_digest(),
        handle_id: handle.handle_id(),
        handle_attestation_digest: handle.resource_attestation_digest(),
        input_digest: input.digest(),
        maximum_tokens: admission.maximum_tokens,
        maximum_usage_units: admission.maximum_usage_units,
        expected_transient_memory_bytes: admission.expected_transient_memory_bytes,
        deadline_ms,
    };
    let encoded = serde_json::to_vec(&binding)
        .map_err(|_| LocalWorkerError::InvalidInput("local payload encoding"))?;
    Ok(digest(&encoded))
}

fn terminal_output(
    request_id: &str,
    model_id: &str,
    handle_id: &str,
    observed: DriverRunObservation,
    boundary: TerminalBoundary,
    forced_boundary: Option<(NativeBoundaryStatus, String)>,
) -> Result<NativeRunOutput, LocalWorkerError> {
    let output_digest = digest(&observed.output);
    validate_digest(&output_digest, "local output digest")?;
    let status = match observed.status {
        DriverTerminalStatus::Succeeded => NativeRunStatus::Completed,
        DriverTerminalStatus::Failed => NativeRunStatus::Failed,
        DriverTerminalStatus::Interrupted => NativeRunStatus::Interrupted,
        DriverTerminalStatus::Indeterminate => {
            return Err(LocalWorkerError::InvalidObservation(
                "terminal observation cannot be indeterminate",
            ));
        }
    };
    let (boundary_status, owner_authority, stop_reason) = match boundary {
        TerminalBoundary::Authorized => (
            NativeBoundaryStatus::Succeeded,
            NativeOwnerAuthority::ObservedReady,
            observed.stop_reason,
        ),
        TerminalBoundary::Observed => {
            let boundary = match observed.status {
                DriverTerminalStatus::Failed => NativeBoundaryStatus::Failed,
                DriverTerminalStatus::Interrupted => NativeBoundaryStatus::Interrupted,
                DriverTerminalStatus::Succeeded | DriverTerminalStatus::Indeterminate => {
                    NativeBoundaryStatus::Quarantined
                }
            };
            (
                boundary,
                NativeOwnerAuthority::ObservedReady,
                observed.stop_reason,
            )
        }
        TerminalBoundary::Quarantined(reason) => (
            NativeBoundaryStatus::Quarantined,
            NativeOwnerAuthority::Lost {
                reason: reason.clone(),
            },
            Some(reason),
        ),
    };
    let (boundary_status, stop_reason) =
        if boundary_status != NativeBoundaryStatus::Quarantined
            && let Some((forced, reason)) = forced_boundary
        {
            (forced, Some(reason))
        } else {
            (boundary_status, stop_reason)
        };
    let receipt_digest = local_terminal_receipt_digest(
        request_id,
        model_id,
        handle_id,
        status,
        boundary_status,
        &output_digest,
        observed.observed_tokens,
        observed.usage_units,
    )?;
    Ok(NativeRunOutput {
        thread_id: handle_id.to_string(),
        turn_id: request_id.to_string(),
        model: model_id.to_string(),
        model_provider: LOCAL_PROVIDER_ID.to_string(),
        status,
        boundary_status,
        output: output_digest,
        observed_output_tokens: observed.observed_tokens,
        terminal_observed: true,
        owner_authority,
        stop_reason,
        codex_terminal_correlation_digest: Some(receipt_digest),
    })
}

fn local_terminal_receipt_digest(
    request_id: &str,
    model_id: &str,
    handle_id: &str,
    status: NativeRunStatus,
    boundary: NativeBoundaryStatus,
    output_digest: &str,
    observed_tokens: Option<u64>,
    usage_units: Option<u64>,
) -> Result<String, LocalWorkerError> {
    let encoded = serde_json::to_vec(&(
        "hepta.local-model-terminal.v1",
        request_id,
        model_id,
        handle_id,
        format!("{status:?}"),
        format!("{boundary:?}"),
        output_digest,
        observed_tokens,
        usage_units,
    ))
    .map_err(|_| LocalWorkerError::InvalidObservation("terminal receipt encoding"))?;
    Ok(digest(&encoded))
}

fn indeterminate_output(
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
        thread_id: handle_id.to_string(),
        turn_id: request_id.to_string(),
        model: model_id.to_string(),
        model_provider: LOCAL_PROVIDER_ID.to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status,
        output: String::new(),
        observed_output_tokens: observed_tokens,
        terminal_observed: false,
        owner_authority: NativeOwnerAuthority::Unverified,
        stop_reason: Some(reason.chars().take(4096).collect()),
        codex_terminal_correlation_digest: None,
    }
}

fn result_from_record(record: &NativeRunRecord) -> Result<LocalRunResult, LocalWorkerError> {
    let output = record
        .observation
        .as_ref()
        .ok_or(LocalWorkerError::InvalidTransition(
            "durable local result is missing an observation",
        ))?;
    if output.model_provider != LOCAL_PROVIDER_ID {
        return Err(LocalWorkerError::InvalidTransition(
            "durable result is not a local-model observation",
        ));
    }
    let status = if output.boundary_status == NativeBoundaryStatus::Quarantined {
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
    let output_digest = if output.output.is_empty() {
        None
    } else {
        validate_digest(&output.output, "durable local output digest")?;
        Some(output.output.clone())
    };
    Ok(LocalRunResult {
        request_id: record.request.request_id.clone(),
        status,
        output_digest,
        observed_tokens: output.observed_output_tokens,
        observed_usage_units: record.observed_usage_units,
        terminal_observed: output.terminal_observed,
        quarantined: record.state != NativeReservationState::Released
            || output.boundary_status == NativeBoundaryStatus::Quarantined,
        stop_reason: output.stop_reason.clone(),
        receipt_digest: output.codex_terminal_correlation_digest.clone(),
    })
}

fn merge_observed_tokens(record: &NativeRunRecord, next: Option<u64>) -> Option<u64> {
    match (
        record
            .observation
            .as_ref()
            .and_then(|output| output.observed_output_tokens),
        next,
    ) {
        (Some(previous), Some(candidate)) => Some(previous.max(candidate)),
        (Some(previous), None) => Some(previous),
        (None, candidate) => candidate,
    }
}

fn merge_observed_usage(record: &NativeRunRecord, next: Option<u64>) -> Option<u64> {
    match (record.observed_usage_units, next) {
        (Some(previous), Some(candidate)) => Some(previous.max(candidate)),
        (Some(previous), None) => Some(previous),
        (None, candidate) => candidate,
    }
}


fn resource_matches(
    observed: &TrustedResourceObservation,
    handle: &AttestedModelHandle,
    grant: &VerifiedResourceGrant,
) -> bool {
    observed.handle_id == handle.handle_id()
        && observed.worker_generation == grant.worker_generation()
        && observed.device_uuid == handle.device_uuid()
        && observed.device_epoch == grant.device_epoch()
        && observed.resident_memory_bytes > 0
        && observed.resident_memory_bytes <= grant.maximum_aggregate_memory_bytes()
        && validate_digest(
            &observed.attestation_digest,
            "terminal resource attestation",
        )
        .is_ok()
}

fn release_matches(
    released: &TrustedReleaseObservation,
    handle: &AttestedModelHandle,
) -> bool {
    released.handle_id == handle.handle_id()
        && released.worker_generation == handle.worker_generation
        && released.device_uuid == handle.device_uuid()
        && released.device_epoch == handle.device_epoch()
        && released.resident_memory_bytes == 0
        && validate_identity(&released.observer_id, "release observer").is_ok()
        && validate_digest(&released.attestation_digest, "release attestation").is_ok()
}

fn unattested_release_matches(
    released: &TrustedReleaseObservation,
    load: &DriverLoadObservation,
    grant: &VerifiedResourceGrant,
) -> bool {
    released.handle_id == load.handle_id
        && released.worker_generation == grant.worker_generation()
        && released.device_uuid == load.device_uuid
        && released.device_epoch == grant.device_epoch()
        && released.resident_memory_bytes == 0
        && validate_identity(&released.observer_id, "failed-load release observer").is_ok()
        && validate_digest(
            &released.attestation_digest,
            "failed-load release attestation",
        )
        .is_ok()
}

fn bounded_reason(reason: &str) -> Result<String, LocalWorkerError> {
    if reason.is_empty() {
        return Err(LocalWorkerError::InvalidObservation(
            "empty reconciliation reason",
        ));
    }
    Ok(reason.chars().take(4096).collect())
}

fn control_error(error: codex_hepta_infer_core::durable_control::Error) -> LocalWorkerError {
    LocalWorkerError::Control(error.to_string())
}
