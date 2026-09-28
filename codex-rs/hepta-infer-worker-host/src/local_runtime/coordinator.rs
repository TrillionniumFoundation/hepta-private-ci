use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::InferenceRequest;
use codex_hepta_infer_core::durable_control::RequestRecord;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

use super::AttestedModelHandle;
use super::DriverReconciliation;
use super::DriverRunObservation;
use super::DriverTerminalStatus;
use super::LocalModelDriver;
use super::LocalRuntimeError;
use super::ResourceManager;
use super::ResourceSnapshot;
use super::TokenUsage;
use super::TrustedDeviceAuthority;
use super::VerifiedInput;
use super::VerifiedModelManifest;
use super::VerifiedResourceGrant;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalRunOutcome {
    Settled {
        state: RequestState,
        output_digest: Option<Digest32>,
        usage: TokenUsage,
        idempotent: bool,
    },
    PreviouslySettled {
        state: RequestState,
        observation_digest: Option<String>,
        consumed_tokens: u32,
        usage_units: u64,
    },
    UsagePending {
        output_digest: Option<Digest32>,
        reason: String,
    },
    ReconciliationRequired {
        state: RequestState,
        reason: String,
    },
    CancelledBeforeDispatch,
}

pub struct LocalInferenceRuntime<D, A> {
    driver: Arc<D>,
    device_authority: Arc<A>,
    resources: ResourceManager,
    worker_id: StableId,
    handles: Mutex<BTreeMap<String, AttestedModelHandle>>,
}

impl<D, A> LocalInferenceRuntime<D, A>
where
    D: LocalModelDriver,
    A: TrustedDeviceAuthority,
{
    pub fn new(
        driver: Arc<D>,
        device_authority: Arc<A>,
        resources: ResourceManager,
        worker_id: StableId,
    ) -> Self {
        Self {
            driver,
            device_authority,
            resources,
            worker_id,
            handles: Mutex::new(BTreeMap::new()),
        }
    }

    pub fn resource_snapshot(&self) -> Result<ResourceSnapshot, LocalRuntimeError> {
        self.resources.snapshot()
    }

    pub async fn load_model(
        &self,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
    ) -> Result<AttestedModelHandle, LocalRuntimeError> {
        if unix_time_ms()? >= grant.claims().expires_at_ms {
            return Err(LocalRuntimeError::Expired);
        }
        let reservation = self.resources.reserve_model(grant, manifest)?;
        let loaded = self.driver.load(manifest, grant).await?;
        let verification = match self
            .device_authority
            .verify_loaded_model(&loaded, manifest, grant)
        {
            Ok(value) => value,
            Err(error) => {
                let cleanup = self.driver.discard_unattested(loaded).await;
                if !matches!(cleanup, Ok(ref observed) if observed.terminal_observed) {
                    reservation.mark_zombie("unattested load cleanup was not observed")?;
                }
                return Err(error);
            }
        };
        let handle = AttestedModelHandle::from_verification(verification, manifest, grant)?;
        reservation.commit(&handle)?;
        {
            let mut handles = self
                .handles
                .lock()
                .map_err(|_| LocalRuntimeError::LockPoisoned)?;
            if handles
                .insert(handle.model_id().as_str().to_string(), handle.clone())
                .is_some()
            {
                return Err(LocalRuntimeError::Conflict);
            }
        }
        self.reconcile_device_memory(grant)?;
        Ok(handle)
    }

    pub async fn unload_model(
        &self,
        model_id: &StableId,
    ) -> Result<(), LocalRuntimeError> {
        let handle = {
            let handles = self
                .handles
                .lock()
                .map_err(|_| LocalRuntimeError::LockPoisoned)?;
            handles
                .get(model_id.as_str())
                .cloned()
                .ok_or(LocalRuntimeError::Conflict)?
        };
        let permit = self.resources.begin_unload(model_id)?;
        match self.driver.unload(&handle).await {
            Ok(observation) => {
                permit.complete(&observation)?;
                let mut handles = self
                    .handles
                    .lock()
                    .map_err(|_| LocalRuntimeError::LockPoisoned)?;
                handles.remove(model_id.as_str());
                Ok(())
            }
            Err(error) => {
                permit.mark_zombie(format!("driver unload failed: {error}"))?;
                Err(error)
            }
        }
    }

    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
        input: &VerifiedInput,
        cancellation: &CancellationToken,
    ) -> Result<LocalRunOutcome, LocalRuntimeError> {
        let handle = {
            let handles = self
                .handles
                .lock()
                .map_err(|_| LocalRuntimeError::LockPoisoned)?;
            handles
                .get(manifest.claims().model_id.as_str())
                .cloned()
                .ok_or(LocalRuntimeError::Conflict)?
        };
        validate_execution_tuple(&handle, grant, manifest)?;
        let request = control_request(grant, manifest, input);
        let request_id = request.request_id.clone();
        let mut record = match control.get(&request_id).cloned() {
            Some(current) => {
                if current.request != request {
                    return Err(LocalRuntimeError::Conflict);
                }
                current
            }
            None => {
                let now_ms = unix_time_ms()?;
                if now_ms >= grant.claims().expires_at_ms
                    || input.deadline().is_elapsed()
                    || now_ms >= input.deadline().absolute_unix_ms()
                {
                    return Err(LocalRuntimeError::Expired);
                }
                control.submit(now_ms, request)?;
                control.get(&request_id).cloned().ok_or_else(|| {
                    LocalRuntimeError::Control("submitted request disappeared".to_string())
                })?
            }
        };
        if matches!(
            record.state,
            RequestState::Completed | RequestState::Failed | RequestState::Cancelled
        ) {
            return Ok(previous_outcome(&record));
        }
        if record.state == RequestState::Indeterminate {
            return Ok(LocalRunOutcome::ReconciliationRequired {
                state: record.state,
                reason: "durable owner is indeterminate; explicit resolution is required"
                    .to_string(),
            });
        }
        if matches!(record.state, RequestState::Assigned | RequestState::Cancelling) {
            return self
                .reconcile_existing(control, &record, input.operation_id())
                .await;
        }
        let now_ms = unix_time_ms()?;
        if now_ms >= grant.claims().expires_at_ms
            || input.deadline().is_elapsed()
            || now_ms >= input.deadline().absolute_unix_ms()
        {
            return Err(LocalRuntimeError::Expired);
        }
        if cancellation.is_cancelled() {
            control.cancel(&request_id, record.revision)?;
            return Ok(LocalRunOutcome::CancelledBeforeDispatch);
        }
        if record.state == RequestState::Pending {
            let reservation = control_reservation(grant, input);
            control.reserve(now_ms, &request_id, record.revision, reservation)?;
            record = control.get(&request_id).cloned().ok_or_else(|| {
                LocalRuntimeError::Control("reserved request disappeared".to_string())
            })?;
        }
        if record.state != RequestState::Reserved {
            return Err(LocalRuntimeError::Control(
                "local request did not reach Reserved".to_string(),
            ));
        }
        let request_reservation = self.resources.reserve_request(
            grant,
            input,
            &manifest.claims().model_id,
        )?;
        let assignment = control_assignment(&self.worker_id, grant, manifest, input, &handle);
        control.assign(&request_id, record.revision, assignment)?;
        record = control.get(&request_id).cloned().ok_or_else(|| {
            LocalRuntimeError::Control("assigned request disappeared".to_string())
        })?;
        let result = self
            .driver
            .run(&handle, input, cancellation, input.deadline())
            .await;
        let outcome = match result {
            Ok(observation) => {
                self.reconcile_device_memory(grant)?;
                settle_or_hold(control, &record, observation)
            }
            Err(error) => match self.driver.inspect(input.operation_id()).await? {
                DriverReconciliation::Terminal(observation) => {
                    self.reconcile_device_memory(grant)?;
                    settle_or_hold(control, &record, observation)
                }
                DriverReconciliation::Running => Ok(LocalRunOutcome::ReconciliationRequired {
                    state: record.state,
                    reason: format!("driver returned {error}; operation is still running"),
                }),
                DriverReconciliation::NotFound => Ok(LocalRunOutcome::ReconciliationRequired {
                    state: record.state,
                    reason: format!(
                        "driver returned {error}; durable assignment exists but inspect found no terminal evidence"
                    ),
                }),
                DriverReconciliation::Ambiguous { reason } => {
                    Ok(LocalRunOutcome::ReconciliationRequired {
                        state: record.state,
                        reason: format!("driver returned {error}; inspect is ambiguous: {reason}"),
                    })
                }
            },
        }?;
        request_reservation.release()?;
        Ok(outcome)
    }

    async fn reconcile_existing(
        &self,
        control: &mut DurableInferenceControl,
        record: &RequestRecord,
        operation_id: &StableId,
    ) -> Result<LocalRunOutcome, LocalRuntimeError> {
        match self.driver.inspect(operation_id).await? {
            DriverReconciliation::Terminal(observation) => {
                settle_or_hold(control, record, observation)
            }
            DriverReconciliation::Running => Ok(LocalRunOutcome::ReconciliationRequired {
                state: record.state,
                reason: "reopened assigned operation is still running; no replay".to_string(),
            }),
            DriverReconciliation::NotFound => Ok(LocalRunOutcome::ReconciliationRequired {
                state: record.state,
                reason: "reopened assigned operation has no exact terminal evidence; no replay"
                    .to_string(),
            }),
            DriverReconciliation::Ambiguous { reason } => {
                Ok(LocalRunOutcome::ReconciliationRequired {
                    state: record.state,
                    reason: format!("reopened operation is ambiguous: {reason}; no replay"),
                })
            }
        }
    }

    fn reconcile_device_memory(
        &self,
        grant: &VerifiedResourceGrant,
    ) -> Result<(), LocalRuntimeError> {
        let observation = self.device_authority.observe_total_memory(
            &grant.claims().device_id,
            grant.claims().worker_generation,
        )?;
        self.resources.reconcile_observed_memory(observation)?;
        Ok(())
    }
}

fn control_request(
    grant: &VerifiedResourceGrant,
    manifest: &VerifiedModelManifest,
    input: &VerifiedInput,
) -> InferenceRequest {
    InferenceRequest {
        request_id: input.operation_id().as_str().to_string(),
        principal_id: grant.claims().worker_subject.as_str().to_string(),
        model_digest: manifest.claims().model_digest.to_string(),
        payload_digest: input.payload_digest().to_string(),
        maximum_tokens: input.maximum_tokens(),
        deadline_ms: input.deadline().absolute_unix_ms(),
        semantic_digest: input.semantic_digest().to_string(),
    }
}

fn control_reservation(
    grant: &VerifiedResourceGrant,
    input: &VerifiedInput,
) -> Reservation {
    let digest = Digest32::of_bytes(input.operation_id().as_str().as_bytes());
    Reservation {
        reservation_id: format!("local-reservation:{digest}"),
        quota_units: grant.claims().maximum_aggregate_memory_bytes,
        maximum_tokens: input.maximum_tokens(),
        authority_epoch: grant.claims().authority_epoch,
        valid_until_ms: input
            .deadline()
            .absolute_unix_ms()
            .min(grant.claims().expires_at_ms),
    }
}

fn control_assignment(
    worker_id: &StableId,
    grant: &VerifiedResourceGrant,
    manifest: &VerifiedModelManifest,
    input: &VerifiedInput,
    handle: &AttestedModelHandle,
) -> Assignment {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.local-model-assignment.v1");
    bytes.extend_from_slice(handle.attestation_digest().as_array());
    bytes.extend_from_slice(grant.authority_witness_digest().as_array());
    bytes.extend_from_slice(manifest.artifact_witness_digest().as_array());
    bytes.extend_from_slice(input.semantic_digest().as_array());
    Assignment {
        worker_id: worker_id.as_str().to_string(),
        worker_generation: grant.claims().worker_generation.get(),
        assignment_digest: Digest32::of_bytes(&bytes).to_string(),
    }
}

fn settle_or_hold(
    control: &mut DurableInferenceControl,
    record: &RequestRecord,
    observation: DriverRunObservation,
) -> Result<LocalRunOutcome, LocalRuntimeError> {
    if observation.observation_digest.is_zero() {
        return Err(LocalRuntimeError::Driver(
            "driver observation digest is zero".to_string(),
        ));
    }
    if !observation.terminal_observed {
        return Ok(LocalRunOutcome::ReconciliationRequired {
            state: record.state,
            reason: "driver did not observe a terminal state; durable assignment retained"
                .to_string(),
        });
    }
    let TokenUsage::Observed {
        consumed_tokens,
        usage_units,
    } = observation.usage
    else {
        return Ok(LocalRunOutcome::UsagePending {
            output_digest: observation.output_digest,
            reason: "terminal provider state lacks trusted usage; durable assignment retained"
                .to_string(),
        });
    };
    let terminal_status = match observation
        .terminal_status
        .ok_or_else(|| LocalRuntimeError::Driver("terminal status missing".to_string()))?
    {
        DriverTerminalStatus::Completed => RequestState::Completed,
        DriverTerminalStatus::Failed => RequestState::Failed,
        DriverTerminalStatus::Cancelled => RequestState::Cancelled,
    };
    if terminal_status == RequestState::Completed && observation.output_digest.is_none() {
        return Err(LocalRuntimeError::Driver(
            "completed local inference omitted output digest".to_string(),
        ));
    }
    let reservation = record
        .reservation
        .as_ref()
        .ok_or_else(|| LocalRuntimeError::Control("reservation missing".to_string()))?;
    let assignment = record
        .assignment
        .as_ref()
        .ok_or_else(|| LocalRuntimeError::Control("assignment missing".to_string()))?;
    let terminal = TerminalObservation {
        request_id: record.request.request_id.clone(),
        reservation_id: reservation.reservation_id.clone(),
        worker_id: assignment.worker_id.clone(),
        worker_generation: assignment.worker_generation,
        model_digest: record.request.model_digest.clone(),
        payload_digest: record.request.payload_digest.clone(),
        terminal_observed: true,
        terminal_status: Some(terminal_status),
        output_digest: observation.output_digest.map(|digest| digest.to_string()),
        consumed_tokens,
        usage_units,
    };
    let receipt = control.settle(
        &record.request.request_id,
        record.revision,
        observation.observation_digest.to_string(),
        terminal,
    )?;
    Ok(LocalRunOutcome::Settled {
        state: receipt.state,
        output_digest: observation.output_digest,
        usage: TokenUsage::Observed {
            consumed_tokens,
            usage_units,
        },
        idempotent: receipt.idempotent,
    })
}

fn previous_outcome(record: &RequestRecord) -> LocalRunOutcome {
    LocalRunOutcome::PreviouslySettled {
        state: record.state,
        observation_digest: record.terminal_observation_digest.clone(),
        consumed_tokens: record.consumed_tokens,
        usage_units: record.usage_units,
    }
}

fn validate_execution_tuple(
    handle: &AttestedModelHandle,
    grant: &VerifiedResourceGrant,
    manifest: &VerifiedModelManifest,
) -> Result<(), LocalRuntimeError> {
    if handle.model_id() != &manifest.claims().model_id
        || handle.model_digest() != manifest.claims().model_digest
        || handle.device_id() != &grant.claims().device_id
        || handle.worker_generation() != grant.claims().worker_generation
    {
        return Err(LocalRuntimeError::Conflict);
    }
    Ok(())
}

fn unix_time_ms() -> Result<u64, LocalRuntimeError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| LocalRuntimeError::Clock(error.to_string()))?;
    u64::try_from(elapsed.as_millis())
        .map_err(|_| LocalRuntimeError::Clock("wall clock overflow".to_string()))
}
