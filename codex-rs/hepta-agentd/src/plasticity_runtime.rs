//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! Parameter and topology submissions enter separate bounded queues. A fair
//! scheduler moves synchronous verification, file IO and cryptographic work to a
//! dedicated blocking worker while the Tokio runtime remains responsive. All
//! writers, trust roots and owner stores remain exclusive to one generation.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_intelligence::CoveredParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::CoveredParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::AgentdCoveredPlasticityHostErrorV1;
use crate::AgentdError;
use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdPlasticityHostErrorV1;
use crate::AgentdState;
use crate::AgentdTopologyAnchorStoreV1;
use crate::AgentdTopologyHostErrorV1;
use crate::AgentdTopologyWriterV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::propose_agentd_covered_plasticity_v1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const MAX_PLASTICITY_RUNTIME_BYTES: usize = 64 * 1024 * 1024;
const MAX_PLASTICITY_RUNTIME_WORK_UNITS: usize = 131_072;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeRequestBudgetV1 {
    pub maximum_encoded_bytes: usize,
    pub maximum_work_units: usize,
    pub deadline_unix_seconds: u64,
}

impl PlasticityRuntimeRequestBudgetV1 {
    pub const fn bounded(
        maximum_encoded_bytes: usize,
        maximum_work_units: usize,
        deadline_unix_seconds: u64,
    ) -> Self {
        Self {
            maximum_encoded_bytes,
            maximum_work_units,
            deadline_unix_seconds,
        }
    }

    const fn legacy() -> Self {
        Self {
            maximum_encoded_bytes: MAX_PLASTICITY_RUNTIME_BYTES,
            maximum_work_units: MAX_PLASTICITY_RUNTIME_WORK_UNITS,
            deadline_unix_seconds: u64::MAX,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeTelemetryV1 {
    pub queue_wait_micros: u64,
    pub execution_micros: u64,
    pub estimated_encoded_bytes: u64,
    pub estimated_work_units: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeOutcomeV1<T> {
    pub receipt: T,
    pub telemetry: PlasticityRuntimeTelemetryV1,
}

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    Cancelled,
    DeadlineExceeded,
    BudgetExceeded,
    Indeterminate,
    WorkerPanicked,
    Parameter(AgentdPlasticityHostErrorV1),
    CoveredParameter(AgentdCoveredPlasticityHostErrorV1),
    Topology(AgentdTopologyHostErrorV1),
}

impl fmt::Display for PlasticityRuntimeCallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityRuntimeCallErrorV1 {}

struct RuntimeAdmissionV1 {
    enqueued_at: Instant,
    estimated_bytes: usize,
    estimated_work: usize,
    budget: PlasticityRuntimeRequestBudgetV1,
    cancellation: CancellationToken,
    _byte_permit: OwnedSemaphorePermit,
    _work_permit: OwnedSemaphorePermit,
}

enum PlasticityRuntimeCommandV1 {
    Parameter {
        request: Box<ParameterPlasticityProductRequestV1>,
        now: u64,
        admission: RuntimeAdmissionV1,
        response: oneshot::Sender<
            Result<
                PlasticityRuntimeOutcomeV1<ParameterPlasticityProductReceiptV1>,
                PlasticityRuntimeCallErrorV1,
            >,
        >,
    },
    CoveredParameter {
        request: Box<CoveredParameterPlasticityProductRequestV1>,
        now: u64,
        admission: RuntimeAdmissionV1,
        response: oneshot::Sender<
            Result<
                PlasticityRuntimeOutcomeV1<CoveredParameterPlasticityProductReceiptV1>,
                PlasticityRuntimeCallErrorV1,
            >,
        >,
    },
    Topology {
        request: Box<TopologyPlasticityProductRequestV1>,
        now: u64,
        admission: RuntimeAdmissionV1,
        response: oneshot::Sender<
            Result<
                PlasticityRuntimeOutcomeV1<TopologyPlasticityProductReceiptV1>,
                PlasticityRuntimeCallErrorV1,
            >,
        >,
    },
}

/// Bounded in-process product handle. It contains no writer, store or trust-root
/// material, so dropping/recreating a handle cannot create another owner.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<PlasticityRuntimeCommandV1>,
    topology_sender: mpsc::Sender<PlasticityRuntimeCommandV1>,
    byte_budget: Arc<Semaphore>,
    work_budget: Arc<Semaphore>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.propose_parameter_bounded(
            request,
            now,
            PlasticityRuntimeRequestBudgetV1::legacy(),
            CancellationToken::new(),
        )
        .await
        .map(|outcome| outcome.receipt)
    }

    pub async fn propose_parameter_bounded(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<ParameterPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        let estimate = estimate_parameter(&request);
        let admission = self.admit(estimate, budget, cancellation.clone()).await?;
        let (response, receive) = oneshot::channel();
        self.dispatch(
            &self.parameter_sender,
            PlasticityRuntimeCommandV1::Parameter {
                request: Box::new(request),
                now,
                admission,
                response,
            },
            cancellation,
            receive,
        )
        .await
    }

    pub async fn propose_covered_parameter(
        &self,
        request: CoveredParameterPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<CoveredParameterPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        let estimate = estimate_parameter(&request.product);
        let admission = self.admit(estimate, budget, cancellation.clone()).await?;
        let (response, receive) = oneshot::channel();
        self.dispatch(
            &self.parameter_sender,
            PlasticityRuntimeCommandV1::CoveredParameter {
                request: Box::new(request),
                now,
                admission,
                response,
            },
            cancellation,
            receive,
        )
        .await
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.propose_topology_bounded(
            request,
            now,
            PlasticityRuntimeRequestBudgetV1::legacy(),
            CancellationToken::new(),
        )
        .await
        .map(|outcome| outcome.receipt)
    }

    pub async fn propose_topology_bounded(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<TopologyPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        let estimate = estimate_topology(&request);
        let admission = self.admit(estimate, budget, cancellation.clone()).await?;
        let (response, receive) = oneshot::channel();
        self.dispatch(
            &self.topology_sender,
            PlasticityRuntimeCommandV1::Topology {
                request: Box::new(request),
                now,
                admission,
                response,
            },
            cancellation,
            receive,
        )
        .await
    }

    async fn admit(
        &self,
        (estimated_bytes, estimated_work): (usize, usize),
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<RuntimeAdmissionV1, PlasticityRuntimeCallErrorV1> {
        if estimated_bytes == 0
            || estimated_work == 0
            || estimated_bytes > budget.maximum_encoded_bytes
            || estimated_work > budget.maximum_work_units
            || budget.maximum_encoded_bytes > MAX_PLASTICITY_RUNTIME_BYTES
            || budget.maximum_work_units > MAX_PLASTICITY_RUNTIME_WORK_UNITS
        {
            return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded);
        }
        if deadline_expired(budget.deadline_unix_seconds) {
            return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
        }
        let byte_permits = u32::try_from(estimated_bytes)
            .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
        let work_permits = u32::try_from(estimated_work)
            .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
        let byte_budget = Arc::clone(&self.byte_budget);
        let byte_permit = tokio::select! {
            _ = cancellation.cancelled() => return Err(PlasticityRuntimeCallErrorV1::Cancelled),
            permit = byte_budget.acquire_many_owned(byte_permits) =>
                permit.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        };
        let work_budget = Arc::clone(&self.work_budget);
        let work_permit = tokio::select! {
            _ = cancellation.cancelled() => return Err(PlasticityRuntimeCallErrorV1::Cancelled),
            permit = work_budget.acquire_many_owned(work_permits) =>
                permit.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        };
        Ok(RuntimeAdmissionV1 {
            enqueued_at: Instant::now(),
            estimated_bytes,
            estimated_work,
            budget,
            cancellation,
            _byte_permit: byte_permit,
            _work_permit: work_permit,
        })
    }

    async fn dispatch<T>(
        &self,
        sender: &mpsc::Sender<PlasticityRuntimeCommandV1>,
        command: PlasticityRuntimeCommandV1,
        cancellation: CancellationToken,
        receive: oneshot::Receiver<
            Result<PlasticityRuntimeOutcomeV1<T>, PlasticityRuntimeCallErrorV1>,
        >,
    ) -> Result<PlasticityRuntimeOutcomeV1<T>, PlasticityRuntimeCallErrorV1> {
        tokio::select! {
            _ = cancellation.cancelled() => return Err(PlasticityRuntimeCallErrorV1::Cancelled),
            result = sender.send(command) => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        }
        tokio::select! {
            _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Indeterminate),
            result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        }
    }
}

/// Immutable construction envelope consumed exactly once by Agentd runtime.
pub struct PlasticityRuntimeBootstrapV1 {
    capacity: usize,
    artifacts: ArtifactRegistry,
    ledger: DurableLedger,
    owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
    verifier: LearningEvidenceVerifierV1,
    parameter_writer: AnchoredPlasticityWriterV1,
    parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
    topology_writer: AgentdTopologyWriterV1,
    topology_anchor_store: AgentdTopologyAnchorStoreV1,
}

impl PlasticityRuntimeBootstrapV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        capacity: usize,
        artifacts: ArtifactRegistry,
        ledger: DurableLedger,
        owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
        owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
        verifier: LearningEvidenceVerifierV1,
        parameter_writer: AnchoredPlasticityWriterV1,
        parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
        topology_writer: AgentdTopologyWriterV1,
        topology_anchor_store: AgentdTopologyAnchorStoreV1,
    ) -> Result<Self, AgentdError> {
        validate_plasticity_runtime_capacity(capacity)?;
        Ok(Self {
            capacity,
            artifacts,
            ledger,
            owner_evidence_resolver,
            owner_evidence_policy,
            verifier,
            parameter_writer,
            parameter_anchor_store,
            topology_writer,
            topology_anchor_store,
        })
    }

    pub(crate) fn into_channel(
        self,
    ) -> Result<(PlasticityRuntimeHandleV1, PlasticityRuntimeOwnerV1), AgentdError> {
        plasticity_runtime_channel_v1(
            self.capacity,
            self.artifacts,
            self.ledger,
            self.owner_evidence_resolver,
            self.owner_evidence_policy,
            self.verifier,
            self.parameter_writer,
            self.parameter_anchor_store,
            self.topology_writer,
            self.topology_anchor_store,
        )
    }
}

struct PlasticityExecutionStateV1 {
    artifacts: ArtifactRegistry,
    ledger: DurableLedger,
    owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
    verifier: LearningEvidenceVerifierV1,
    parameter_writer: AnchoredPlasticityWriterV1,
    parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
    topology_writer: AgentdTopologyWriterV1,
    topology_anchor_store: AgentdTopologyAnchorStoreV1,
}

/// Exact mutable owner retained for the lifetime of the Agentd generation.
pub struct PlasticityRuntimeOwnerV1 {
    parameter_receiver: mpsc::Receiver<PlasticityRuntimeCommandV1>,
    topology_receiver: mpsc::Receiver<PlasticityRuntimeCommandV1>,
    execution: Arc<Mutex<PlasticityExecutionStateV1>>,
}

#[allow(clippy::too_many_arguments)]
pub fn plasticity_runtime_channel_v1(
    capacity: usize,
    artifacts: ArtifactRegistry,
    ledger: DurableLedger,
    owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
    verifier: LearningEvidenceVerifierV1,
    parameter_writer: AnchoredPlasticityWriterV1,
    parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
    topology_writer: AgentdTopologyWriterV1,
    topology_anchor_store: AgentdTopologyAnchorStoreV1,
) -> Result<(PlasticityRuntimeHandleV1, PlasticityRuntimeOwnerV1), AgentdError> {
    validate_plasticity_runtime_capacity(capacity)?;
    let (parameter_sender, parameter_receiver) = mpsc::channel(capacity);
    let (topology_sender, topology_receiver) = mpsc::channel(capacity);
    let byte_budget = Arc::new(Semaphore::new(MAX_PLASTICITY_RUNTIME_BYTES));
    let work_budget = Arc::new(Semaphore::new(MAX_PLASTICITY_RUNTIME_WORK_UNITS));
    Ok((
        PlasticityRuntimeHandleV1 {
            parameter_sender,
            topology_sender,
            byte_budget: Arc::clone(&byte_budget),
            work_budget: Arc::clone(&work_budget),
        },
        PlasticityRuntimeOwnerV1 {
            parameter_receiver,
            topology_receiver,
            execution: Arc::new(Mutex::new(PlasticityExecutionStateV1 {
                artifacts,
                ledger,
                owner_evidence_resolver,
                owner_evidence_policy,
                verifier,
                parameter_writer,
                parameter_anchor_store,
                topology_writer,
                topology_anchor_store,
            })),
        },
    ))
}

fn validate_plasticity_runtime_capacity(capacity: usize) -> Result<(), AgentdError> {
    if !(1..=MAX_PLASTICITY_RUNTIME_QUEUE).contains(&capacity) {
        return Err(AgentdError::Invalid(format!(
            "plasticity runtime queue capacity must be within 1..={MAX_PLASTICITY_RUNTIME_QUEUE}"
        )));
    }
    Ok(())
}

pub(crate) fn compose_plasticity_runtime_v1(
    state: &Arc<AgentdState>,
    bootstrap: Option<PlasticityRuntimeBootstrapV1>,
) -> Result<Option<PlasticityRuntimeOwnerV1>, AgentdError> {
    match bootstrap {
        Some(bootstrap) => {
            let (handle, owner) = bootstrap.into_channel()?;
            state.attach_plasticity_runtime(handle)?;
            Ok(Some(owner))
        }
        None => Ok(None),
    }
}

#[cfg(test)]
pub(crate) fn spawn_plasticity_runtime_v1(
    state: Arc<AgentdState>,
    owner: Option<PlasticityRuntimeOwnerV1>,
    cancellation: CancellationToken,
) -> tokio::task::JoinHandle<Result<(), AgentdError>> {
    tokio::spawn(async move {
        match owner {
            Some(owner) => owner.run(state, cancellation).await,
            None => {
                cancellation.cancelled().await;
                Ok(())
            }
        }
    })
}

impl PlasticityRuntimeOwnerV1 {
    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let mut prefer_parameter = true;
        loop {
            let command = if prefer_parameter {
                tokio::select! {
                    biased;
                    _ = cancellation.cancelled() => return Ok(()),
                    command = self.parameter_receiver.recv() => command,
                    command = self.topology_receiver.recv() => command,
                }
            } else {
                tokio::select! {
                    biased;
                    _ = cancellation.cancelled() => return Ok(()),
                    command = self.topology_receiver.recv() => command,
                    command = self.parameter_receiver.recv() => command,
                }
            };
            let Some(command) = command else {
                if self.parameter_receiver.is_closed() && self.topology_receiver.is_closed() {
                    cancellation.cancelled().await;
                    return Ok(());
                }
                prefer_parameter = !prefer_parameter;
                continue;
            };
            prefer_parameter = !prefer_parameter;
            if !state.plasticity_admission_ready()? {
                reject(command, PlasticityRuntimeCallErrorV1::Unavailable);
                continue;
            }
            if let Some(error) = command_preflight_error(&command) {
                reject(command, error);
                continue;
            }
            let execution = Arc::clone(&self.execution);
            tokio::task::spawn_blocking(move || execute_command(execution, command))
                .await
                .map_err(|_| {
                    AgentdError::Protocol("plasticity blocking worker panicked".to_string())
                })?;
        }
    }
}

fn execute_command(
    execution: Arc<Mutex<PlasticityExecutionStateV1>>,
    command: PlasticityRuntimeCommandV1,
) {
    let started = Instant::now();
    let mut state = match execution.lock() {
        Ok(state) => state,
        Err(_) => {
            reject(command, PlasticityRuntimeCallErrorV1::WorkerPanicked);
            return;
        }
    };
    let PlasticityExecutionStateV1 {
        artifacts,
        ledger,
        owner_evidence_resolver,
        owner_evidence_policy,
        verifier,
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    } = &mut *state;
    match command {
        PlasticityRuntimeCommandV1::Parameter {
            request,
            now,
            admission,
            response,
        } => {
            if response.is_closed() || admission.cancellation.is_cancelled() {
                return;
            }
            let result = propose_agentd_plasticity_v1(
                *request,
                artifacts,
                ledger,
                owner_evidence_resolver.as_ref(),
                owner_evidence_policy,
                verifier,
                parameter_writer,
                parameter_anchor_store,
                now,
            )
            .map_err(PlasticityRuntimeCallErrorV1::Parameter)
            .map(|receipt| outcome(receipt, &admission, started));
            let _ = response.send(result);
        }
        PlasticityRuntimeCommandV1::CoveredParameter {
            request,
            now,
            admission,
            response,
        } => {
            if response.is_closed() || admission.cancellation.is_cancelled() {
                return;
            }
            let result = propose_agentd_covered_plasticity_v1(
                *request,
                artifacts,
                ledger,
                owner_evidence_resolver.as_ref(),
                owner_evidence_policy,
                verifier,
                parameter_writer,
                parameter_anchor_store,
                now,
            )
            .map_err(PlasticityRuntimeCallErrorV1::CoveredParameter)
            .map(|receipt| outcome(receipt, &admission, started));
            let _ = response.send(result);
        }
        PlasticityRuntimeCommandV1::Topology {
            request,
            now,
            admission,
            response,
        } => {
            if response.is_closed() || admission.cancellation.is_cancelled() {
                return;
            }
            let result = propose_agentd_topology_plasticity_v1(
                *request,
                artifacts,
                ledger,
                verifier,
                topology_writer,
                topology_anchor_store,
                now,
            )
            .map_err(PlasticityRuntimeCallErrorV1::Topology)
            .map(|receipt| outcome(receipt, &admission, started));
            let _ = response.send(result);
        }
    }
}

fn outcome<T>(
    receipt: T,
    admission: &RuntimeAdmissionV1,
    started: Instant,
) -> PlasticityRuntimeOutcomeV1<T> {
    PlasticityRuntimeOutcomeV1 {
        receipt,
        telemetry: PlasticityRuntimeTelemetryV1 {
            queue_wait_micros: micros(started.saturating_duration_since(admission.enqueued_at)),
            execution_micros: micros(started.elapsed()),
            estimated_encoded_bytes: admission.estimated_bytes as u64,
            estimated_work_units: admission.estimated_work as u64,
        },
    }
}

fn reject(command: PlasticityRuntimeCommandV1, error: PlasticityRuntimeCallErrorV1) {
    match command {
        PlasticityRuntimeCommandV1::Parameter { response, .. } => {
            let _ = response.send(Err(error));
        }
        PlasticityRuntimeCommandV1::CoveredParameter { response, .. } => {
            let _ = response.send(Err(error));
        }
        PlasticityRuntimeCommandV1::Topology { response, .. } => {
            let _ = response.send(Err(error));
        }
    }
}

fn command_preflight_error(
    command: &PlasticityRuntimeCommandV1,
) -> Option<PlasticityRuntimeCallErrorV1> {
    let admission = match command {
        PlasticityRuntimeCommandV1::Parameter { admission, .. }
        | PlasticityRuntimeCommandV1::CoveredParameter { admission, .. }
        | PlasticityRuntimeCommandV1::Topology { admission, .. } => admission,
    };
    if admission.cancellation.is_cancelled() {
        Some(PlasticityRuntimeCallErrorV1::Cancelled)
    } else if deadline_expired(admission.budget.deadline_unix_seconds) {
        Some(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
    } else {
        None
    }
}

fn deadline_expired(deadline: u64) -> bool {
    deadline != u64::MAX && unix_now().is_some_and(|now| now > deadline)
}

fn unix_now() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_secs())
}

fn micros(duration: std::time::Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn estimate_parameter(request: &ParameterPlasticityProductRequestV1) -> (usize, usize) {
    let signals = request.generator_profile.signals.len();
    let scales = request.generator_profile.update_scales.len().max(1);
    let deltas = request
        .generated
        .candidates
        .iter()
        .map(|candidate| candidate.parameter_deltas.len())
        .sum::<usize>();
    let evaluations = request.evaluations.len();
    let bytes = 4_096usize
        .saturating_add(signals.saturating_mul(160))
        .saturating_add(deltas.saturating_mul(128))
        .saturating_add(evaluations.saturating_mul(512));
    let work = 1usize
        .saturating_add(signals.saturating_mul(scales))
        .saturating_add(deltas)
        .saturating_add(evaluations);
    (bytes.max(1), work.max(1))
}

fn estimate_topology(_request: &TopologyPlasticityProductRequestV1) -> (usize, usize) {
    (16 * 1024, 1_024)
}

#[cfg(test)]
#[path = "plasticity_runtime_lifetime_tests.rs"]
mod lifetime_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_queue_capacity_is_bounded() {
        assert!(validate_plasticity_runtime_capacity(1).is_ok());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE).is_ok());
        assert!(validate_plasticity_runtime_capacity(0).is_err());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE + 1).is_err());
    }

    #[test]
    fn deadlines_and_request_budgets_fail_closed() {
        assert!(deadline_expired(1));
        let budget = PlasticityRuntimeRequestBudgetV1::bounded(0, 1, u64::MAX);
        assert_eq!(budget.maximum_encoded_bytes, 0);
    }
}
