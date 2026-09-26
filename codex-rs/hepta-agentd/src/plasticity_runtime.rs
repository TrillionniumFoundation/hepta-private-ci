//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! The owner is deliberately internal to Agentd rather than a public mutation API.
//! Parameter and topology traffic enter through distinct bounded lanes, share byte
//! and work budgets, and are scheduled fairly. Synchronous verification and durable
//! I/O execute on Tokio's blocking pool so they cannot stall the async control loop.
//! The handle owns no writer, trust root, owner store, selection or activation power.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_intelligence::AnchoredPlasticityWriterErrorV1;
use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_intelligence::ParameterPlasticityProductErrorV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductErrorV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_plasticity::DurableProposalRegistryError;
use codex_hepta_plasticity::DurableTopologyRegistryErrorV1;
use codex_hepta_types::Digest32;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdPlasticityHostErrorV1;
use crate::AgentdState;
use crate::AgentdTopologyAnchorStoreV1;
use crate::AgentdTopologyHostErrorV1;
use crate::AgentdTopologyWriterV1;
use crate::ParameterSelfIterationRequestV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::PreparedParameterSelfIterationV1;
use crate::PreparedTopologySelfIterationV1;
use crate::SelfIterationCoordinatorErrorV1;
use crate::SelfIterationTerminalReceiptV1;
use crate::TopologySelfIterationRequestV1;
use crate::complete_parameter_self_iteration_v1;
use crate::complete_topology_self_iteration_v1;
use crate::prepare_parameter_self_iteration_v1;
use crate::prepare_topology_self_iteration_v1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;
use crate::reject_self_iteration_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const DEFAULT_MAX_QUEUED_ENCODED_BYTES: u32 = 16 * 1024 * 1024;
const DEFAULT_MAX_QUEUED_WORK_UNITS: u32 = 131_072;
const MAX_RUNTIME_BUDGET: u32 = 64 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeLimitsV1 {
    pub lane_capacity: usize,
    pub maximum_queued_encoded_bytes: u32,
    pub maximum_queued_work_units: u32,
}

impl PlasticityRuntimeLimitsV1 {
    pub fn from_lane_capacity(lane_capacity: usize) -> Result<Self, AgentdError> {
        let limits = Self {
            lane_capacity,
            maximum_queued_encoded_bytes: DEFAULT_MAX_QUEUED_ENCODED_BYTES,
            maximum_queued_work_units: DEFAULT_MAX_QUEUED_WORK_UNITS,
        };
        validate_plasticity_runtime_limits(limits)?;
        Ok(limits)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeMetricsSnapshotV1 {
    pub accepted_parameter_requests: u64,
    pub accepted_topology_requests: u64,
    pub completed_parameter_requests: u64,
    pub completed_topology_requests: u64,
    pub overloaded_requests: u64,
    pub cancelled_requests: u64,
    pub deadline_exceeded_requests: u64,
    pub total_queue_wait_micros: u64,
    pub total_processing_micros: u64,
}

#[derive(Default)]
struct PlasticityRuntimeMetricsV1 {
    accepted_parameter_requests: AtomicU64,
    accepted_topology_requests: AtomicU64,
    completed_parameter_requests: AtomicU64,
    completed_topology_requests: AtomicU64,
    overloaded_requests: AtomicU64,
    cancelled_requests: AtomicU64,
    deadline_exceeded_requests: AtomicU64,
    total_queue_wait_micros: AtomicU64,
    total_processing_micros: AtomicU64,
}

impl PlasticityRuntimeMetricsV1 {
    fn snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        PlasticityRuntimeMetricsSnapshotV1 {
            accepted_parameter_requests: self.accepted_parameter_requests.load(Ordering::Relaxed),
            accepted_topology_requests: self.accepted_topology_requests.load(Ordering::Relaxed),
            completed_parameter_requests: self.completed_parameter_requests.load(Ordering::Relaxed),
            completed_topology_requests: self.completed_topology_requests.load(Ordering::Relaxed),
            overloaded_requests: self.overloaded_requests.load(Ordering::Relaxed),
            cancelled_requests: self.cancelled_requests.load(Ordering::Relaxed),
            deadline_exceeded_requests: self.deadline_exceeded_requests.load(Ordering::Relaxed),
            total_queue_wait_micros: self.total_queue_wait_micros.load(Ordering::Relaxed),
            total_processing_micros: self.total_processing_micros.load(Ordering::Relaxed),
        }
    }

    fn add_queue_wait(&self, duration: Duration) {
        atomic_saturating_add(&self.total_queue_wait_micros, duration.as_micros());
    }

    fn add_processing(&self, duration: Duration) {
        atomic_saturating_add(&self.total_processing_micros, duration.as_micros());
    }
}

fn atomic_saturating_add(target: &AtomicU64, value: u128) {
    let value = u64::try_from(value).unwrap_or(u64::MAX);
    let _ = target.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
        Some(current.saturating_add(value))
    });
}

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    Overloaded,
    Cancelled,
    DeadlineExceeded,
    Internal(&'static str),
    Coordination(SelfIterationCoordinatorErrorV1),
    Parameter(AgentdPlasticityHostErrorV1),
    Topology(AgentdTopologyHostErrorV1),
}

impl fmt::Display for PlasticityRuntimeCallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityRuntimeCallErrorV1 {}
impl From<SelfIterationCoordinatorErrorV1> for PlasticityRuntimeCallErrorV1 {
    fn from(value: SelfIterationCoordinatorErrorV1) -> Self {
        Self::Coordination(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterSelfIterationRuntimeReceiptV1 {
    pub terminal: SelfIterationTerminalReceiptV1,
    pub product: Option<ParameterPlasticityProductReceiptV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologySelfIterationRuntimeReceiptV1 {
    pub terminal: SelfIterationTerminalReceiptV1,
    pub product: Option<TopologyPlasticityProductReceiptV1>,
}

struct QueueBudgetPermitsV1 {
    _encoded_bytes: OwnedSemaphorePermit,
    _work_units: OwnedSemaphorePermit,
}

struct RuntimeCommandControlV1 {
    cancellation: CancellationToken,
    deadline: Option<Instant>,
    enqueued_at: Instant,
    _budget: QueueBudgetPermitsV1,
}

impl RuntimeCommandControlV1 {
    fn terminal_error(&self) -> Option<PlasticityRuntimeCallErrorV1> {
        if self.cancellation.is_cancelled() {
            return Some(PlasticityRuntimeCallErrorV1::Cancelled);
        }
        if self.deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            return Some(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
        }
        None
    }
}

enum ParameterRuntimeCommandV1 {
    Product {
        request: Box<ParameterPlasticityProductRequestV1>,
        now: u64,
        control: RuntimeCommandControlV1,
        response: oneshot::Sender<
            Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
    SelfIteration {
        prepared: Box<PreparedParameterSelfIterationV1>,
        now: u64,
        control: RuntimeCommandControlV1,
        response: oneshot::Sender<
            Result<ParameterSelfIterationRuntimeReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
}

enum TopologyRuntimeCommandV1 {
    Product {
        request: Box<TopologyPlasticityProductRequestV1>,
        now: u64,
        control: RuntimeCommandControlV1,
        response: oneshot::Sender<
            Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
    SelfIteration {
        prepared: Box<PreparedTopologySelfIterationV1>,
        now: u64,
        control: RuntimeCommandControlV1,
        response: oneshot::Sender<
            Result<TopologySelfIterationRuntimeReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
}

/// Bounded in-process product handle. It contains no writer, store or trust-root
/// material. Parameter and topology lanes are independent while their aggregate
/// queued memory/work remains bounded by shared semaphores.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<ParameterRuntimeCommandV1>,
    topology_sender: mpsc::Sender<TopologyRuntimeCommandV1>,
    encoded_byte_budget: Arc<Semaphore>,
    work_budget: Arc<Semaphore>,
    metrics: Arc<PlasticityRuntimeMetricsV1>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.propose_parameter_with_control(
            request,
            now,
            u64::MAX,
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_parameter_with_control(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        caller_cancellation: CancellationToken,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = runtime_deadline(now, deadline_unix_seconds)?;
        let cancellation = caller_cancellation.child_token();
        let (encoded_bytes, work_units) = estimate_parameter_request(&request);
        let budget = self.acquire_budget(encoded_bytes, work_units)?;
        let (response, receive) = oneshot::channel();
        let command = ParameterRuntimeCommandV1::Product {
            request: Box::new(request),
            now,
            control: RuntimeCommandControlV1 {
                cancellation: cancellation.clone(),
                deadline,
                enqueued_at: Instant::now(),
                _budget: budget,
            },
            response,
        };
        send_command(
            &self.parameter_sender,
            command,
            &cancellation,
            deadline,
            &self.metrics,
        )
        .await?;
        self.metrics
            .accepted_parameter_requests
            .fetch_add(1, Ordering::Relaxed);
        wait_response(receive, cancellation, deadline, &self.metrics).await
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.propose_topology_with_control(
            request,
            now,
            u64::MAX,
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_topology_with_control(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        caller_cancellation: CancellationToken,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = runtime_deadline(now, deadline_unix_seconds)?;
        let cancellation = caller_cancellation.child_token();
        let (encoded_bytes, work_units) = estimate_topology_request(&request);
        let budget = self.acquire_budget(encoded_bytes, work_units)?;
        let (response, receive) = oneshot::channel();
        let command = TopologyRuntimeCommandV1::Product {
            request: Box::new(request),
            now,
            control: RuntimeCommandControlV1 {
                cancellation: cancellation.clone(),
                deadline,
                enqueued_at: Instant::now(),
                _budget: budget,
            },
            response,
        };
        send_command(
            &self.topology_sender,
            command,
            &cancellation,
            deadline,
            &self.metrics,
        )
        .await?;
        self.metrics
            .accepted_topology_requests
            .fetch_add(1, Ordering::Relaxed);
        wait_response(receive, cancellation, deadline, &self.metrics).await
    }

    pub async fn coordinate_parameter_self_iteration(
        &self,
        request: ParameterSelfIterationRequestV1,
        now: u64,
        caller_cancellation: CancellationToken,
    ) -> Result<ParameterSelfIterationRuntimeReceiptV1, PlasticityRuntimeCallErrorV1> {
        let absolute_deadline = request.deadline_unix_seconds;
        let prepared = prepare_parameter_self_iteration_v1(request, now)?;
        let deadline = runtime_deadline(now, absolute_deadline)?;
        let cancellation = caller_cancellation.child_token();
        let (encoded_bytes, work_units) = estimate_parameter_request(&prepared.request);
        let budget = self.acquire_budget(encoded_bytes, work_units)?;
        let (response, receive) = oneshot::channel();
        let command = ParameterRuntimeCommandV1::SelfIteration {
            prepared: Box::new(prepared),
            now,
            control: RuntimeCommandControlV1 {
                cancellation: cancellation.clone(),
                deadline,
                enqueued_at: Instant::now(),
                _budget: budget,
            },
            response,
        };
        send_command(
            &self.parameter_sender,
            command,
            &cancellation,
            deadline,
            &self.metrics,
        )
        .await?;
        self.metrics
            .accepted_parameter_requests
            .fetch_add(1, Ordering::Relaxed);
        wait_response(receive, cancellation, deadline, &self.metrics).await
    }

    pub async fn coordinate_topology_self_iteration(
        &self,
        request: TopologySelfIterationRequestV1,
        now: u64,
        caller_cancellation: CancellationToken,
    ) -> Result<TopologySelfIterationRuntimeReceiptV1, PlasticityRuntimeCallErrorV1> {
        let absolute_deadline = request.deadline_unix_seconds;
        let prepared = prepare_topology_self_iteration_v1(request, now)?;
        let deadline = runtime_deadline(now, absolute_deadline)?;
        let cancellation = caller_cancellation.child_token();
        let (encoded_bytes, work_units) = estimate_topology_request(&prepared.request);
        let budget = self.acquire_budget(encoded_bytes, work_units)?;
        let (response, receive) = oneshot::channel();
        let command = TopologyRuntimeCommandV1::SelfIteration {
            prepared: Box::new(prepared),
            now,
            control: RuntimeCommandControlV1 {
                cancellation: cancellation.clone(),
                deadline,
                enqueued_at: Instant::now(),
                _budget: budget,
            },
            response,
        };
        send_command(
            &self.topology_sender,
            command,
            &cancellation,
            deadline,
            &self.metrics,
        )
        .await?;
        self.metrics
            .accepted_topology_requests
            .fetch_add(1, Ordering::Relaxed);
        wait_response(receive, cancellation, deadline, &self.metrics).await
    }

    #[must_use]
    pub fn metrics_snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        self.metrics.snapshot()
    }

    fn acquire_budget(
        &self,
        encoded_bytes: u32,
        work_units: u32,
    ) -> Result<QueueBudgetPermitsV1, PlasticityRuntimeCallErrorV1> {
        let encoded_bytes = encoded_bytes.max(1);
        let work_units = work_units.max(1);
        let encoded = self
            .encoded_byte_budget
            .clone()
            .try_acquire_many_owned(encoded_bytes)
            .map_err(|_| {
                self.metrics
                    .overloaded_requests
                    .fetch_add(1, Ordering::Relaxed);
                PlasticityRuntimeCallErrorV1::Overloaded
            })?;
        let work = self
            .work_budget
            .clone()
            .try_acquire_many_owned(work_units)
            .map_err(|_| {
                self.metrics
                    .overloaded_requests
                    .fetch_add(1, Ordering::Relaxed);
                PlasticityRuntimeCallErrorV1::Overloaded
            })?;
        Ok(QueueBudgetPermitsV1 {
            _encoded_bytes: encoded,
            _work_units: work,
        })
    }
}

async fn send_command<T: Send>(
    sender: &mpsc::Sender<T>,
    command: T,
    cancellation: &CancellationToken,
    deadline: Option<Instant>,
    metrics: &PlasticityRuntimeMetricsV1,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    match deadline {
        Some(deadline) => {
            tokio::select! {
                _ = cancellation.cancelled() => {
                    metrics.cancelled_requests.fetch_add(1, Ordering::Relaxed);
                    Err(PlasticityRuntimeCallErrorV1::Cancelled)
                }
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)) => {
                    cancellation.cancel();
                    metrics.deadline_exceeded_requests.fetch_add(1, Ordering::Relaxed);
                    Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
                }
                result = sender.send(command) => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed),
            }
        }
        None => {
            tokio::select! {
                _ = cancellation.cancelled() => {
                    metrics.cancelled_requests.fetch_add(1, Ordering::Relaxed);
                    Err(PlasticityRuntimeCallErrorV1::Cancelled)
                }
                result = sender.send(command) => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed),
            }
        }
    }
}

async fn wait_response<T>(
    receive: oneshot::Receiver<Result<T, PlasticityRuntimeCallErrorV1>>,
    cancellation: CancellationToken,
    deadline: Option<Instant>,
    metrics: &PlasticityRuntimeMetricsV1,
) -> Result<T, PlasticityRuntimeCallErrorV1> {
    match deadline {
        Some(deadline) => {
            tokio::select! {
                _ = cancellation.cancelled() => {
                    metrics.cancelled_requests.fetch_add(1, Ordering::Relaxed);
                    Err(PlasticityRuntimeCallErrorV1::Cancelled)
                }
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)) => {
                    cancellation.cancel();
                    metrics.deadline_exceeded_requests.fetch_add(1, Ordering::Relaxed);
                    Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
                }
                result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
            }
        }
        None => {
            tokio::select! {
                _ = cancellation.cancelled() => {
                    metrics.cancelled_requests.fetch_add(1, Ordering::Relaxed);
                    Err(PlasticityRuntimeCallErrorV1::Cancelled)
                }
                result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
            }
        }
    }
}

fn runtime_deadline(
    now: u64,
    deadline_unix_seconds: u64,
) -> Result<Option<Instant>, PlasticityRuntimeCallErrorV1> {
    if deadline_unix_seconds == u64::MAX {
        return Ok(None);
    }
    let remaining = deadline_unix_seconds
        .checked_sub(now)
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)?;
    Instant::now()
        .checked_add(Duration::from_secs(remaining))
        .map(Some)
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
}

fn estimate_parameter_request(request: &ParameterPlasticityProductRequestV1) -> (u32, u32) {
    let signals = request.generator_profile.signals.len() as u64;
    let scales = request.generator_profile.update_scales.len() as u64;
    let candidates = request.generated.candidates.len() as u64;
    let deltas = request
        .generated
        .candidates
        .iter()
        .map(|candidate| candidate.parameter_deltas.len() as u64)
        .sum::<u64>();
    let evaluations = request.evaluations.len() as u64;
    let bytes = 4_096_u64
        .saturating_add(signals.saturating_mul(160))
        .saturating_add(scales.saturating_mul(16))
        .saturating_add(candidates.saturating_mul(256))
        .saturating_add(deltas.saturating_mul(160))
        .saturating_add(evaluations.saturating_mul(2_048));
    let work = 16_u64
        .saturating_add(signals.saturating_mul(scales.max(1)))
        .saturating_add(deltas)
        .saturating_add(evaluations.saturating_mul(32));
    (bounded_budget(bytes), bounded_budget(work))
}

fn estimate_topology_request(request: &TopologyPlasticityProductRequestV1) -> (u32, u32) {
    let changes = request.changes.len() as u64;
    let handoffs = request.handoffs.len() as u64;
    let bytes = 4_096_u64
        .saturating_add(changes.saturating_mul(768))
        .saturating_add(handoffs.saturating_mul(512));
    let work = 16_u64
        .saturating_add(changes.saturating_mul(16))
        .saturating_add(handoffs.saturating_mul(8));
    (bounded_budget(bytes), bounded_budget(work))
}

fn bounded_budget(value: u64) -> u32 {
    u32::try_from(value.min(u64::from(MAX_RUNTIME_BUDGET)))
        .unwrap_or(MAX_RUNTIME_BUDGET)
        .max(1)
}

/// Immutable construction envelope consumed once by Agentd runtime composition.
pub struct PlasticityRuntimeBootstrapV1 {
    limits: PlasticityRuntimeLimitsV1,
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
        Self::new_with_limits(
            PlasticityRuntimeLimitsV1::from_lane_capacity(capacity)?,
            artifacts,
            ledger,
            owner_evidence_resolver,
            owner_evidence_policy,
            verifier,
            parameter_writer,
            parameter_anchor_store,
            topology_writer,
            topology_anchor_store,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn new_with_limits(
        limits: PlasticityRuntimeLimitsV1,
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
        validate_plasticity_runtime_limits(limits)?;
        Ok(Self {
            limits,
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
        plasticity_runtime_channel_with_limits_v1(
            self.limits,
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

struct PlasticityRuntimeStoresV1 {
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
    parameter_receiver: mpsc::Receiver<ParameterRuntimeCommandV1>,
    topology_receiver: mpsc::Receiver<TopologyRuntimeCommandV1>,
    stores: Arc<Mutex<PlasticityRuntimeStoresV1>>,
    metrics: Arc<PlasticityRuntimeMetricsV1>,
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
    plasticity_runtime_channel_with_limits_v1(
        PlasticityRuntimeLimitsV1::from_lane_capacity(capacity)?,
        artifacts,
        ledger,
        owner_evidence_resolver,
        owner_evidence_policy,
        verifier,
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    )
}

#[allow(clippy::too_many_arguments)]
pub fn plasticity_runtime_channel_with_limits_v1(
    limits: PlasticityRuntimeLimitsV1,
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
    validate_plasticity_runtime_limits(limits)?;
    let (parameter_sender, parameter_receiver) = mpsc::channel(limits.lane_capacity);
    let (topology_sender, topology_receiver) = mpsc::channel(limits.lane_capacity);
    let encoded_byte_budget = Arc::new(Semaphore::new(
        limits.maximum_queued_encoded_bytes as usize,
    ));
    let work_budget = Arc::new(Semaphore::new(limits.maximum_queued_work_units as usize));
    let metrics = Arc::new(PlasticityRuntimeMetricsV1::default());
    let stores = Arc::new(Mutex::new(PlasticityRuntimeStoresV1 {
        artifacts,
        ledger,
        owner_evidence_resolver,
        owner_evidence_policy,
        verifier,
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    }));
    Ok((
        PlasticityRuntimeHandleV1 {
            parameter_sender,
            topology_sender,
            encoded_byte_budget,
            work_budget,
            metrics: metrics.clone(),
        },
        PlasticityRuntimeOwnerV1 {
            parameter_receiver,
            topology_receiver,
            stores,
            metrics,
        },
    ))
}

fn validate_plasticity_runtime_limits(limits: PlasticityRuntimeLimitsV1) -> Result<(), AgentdError> {
    if !(1..=MAX_PLASTICITY_RUNTIME_QUEUE).contains(&limits.lane_capacity) {
        return Err(AgentdError::Invalid(format!(
            "plasticity runtime lane capacity must be within 1..={MAX_PLASTICITY_RUNTIME_QUEUE}"
        )));
    }
    for (name, value) in [
        (
            "maximum queued encoded bytes",
            limits.maximum_queued_encoded_bytes,
        ),
        ("maximum queued work units", limits.maximum_queued_work_units),
    ] {
        if value == 0 || value > MAX_RUNTIME_BUDGET {
            return Err(AgentdError::Invalid(format!(
                "plasticity runtime {name} must be within 1..={MAX_RUNTIME_BUDGET}"
            )));
        }
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

enum NextRuntimeCommandV1 {
    Parameter(Option<ParameterRuntimeCommandV1>),
    Topology(Option<TopologyRuntimeCommandV1>),
}

impl PlasticityRuntimeOwnerV1 {
    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let mut parameter_closed = false;
        let mut topology_closed = false;
        loop {
            if parameter_closed && topology_closed {
                cancellation.cancelled().await;
                return Ok(());
            }
            let next = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                command = self.parameter_receiver.recv(), if !parameter_closed => {
                    NextRuntimeCommandV1::Parameter(command)
                }
                command = self.topology_receiver.recv(), if !topology_closed => {
                    NextRuntimeCommandV1::Topology(command)
                }
            };
            match next {
                NextRuntimeCommandV1::Parameter(Some(command)) => {
                    self.process_parameter(&state, command).await?;
                }
                NextRuntimeCommandV1::Topology(Some(command)) => {
                    self.process_topology(&state, command).await?;
                }
                NextRuntimeCommandV1::Parameter(None) => parameter_closed = true,
                NextRuntimeCommandV1::Topology(None) => topology_closed = true,
            }
        }
    }

    async fn process_parameter(
        &self,
        state: &AgentdState,
        command: ParameterRuntimeCommandV1,
    ) -> Result<(), AgentdError> {
        match command {
            ParameterRuntimeCommandV1::Product {
                request,
                now,
                control,
                response,
            } => {
                self.metrics.add_queue_wait(control.enqueued_at.elapsed());
                if response.is_closed() {
                    return Ok(());
                }
                if let Some(error) = control.terminal_error() {
                    let _ = response.send(Err(error));
                    return Ok(());
                }
                if !state.plasticity_admission_ready()? {
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                    return Ok(());
                }
                let started = Instant::now();
                let stores = self.stores.clone();
                let cancellation = control.cancellation.clone();
                let result = tokio::task::spawn_blocking(move || {
                    if cancellation.is_cancelled() {
                        return Err(PlasticityRuntimeCallErrorV1::Cancelled);
                    }
                    let mut stores = stores.lock().map_err(|_| {
                        PlasticityRuntimeCallErrorV1::Internal(
                            "plasticity runtime stores poisoned",
                        )
                    })?;
                    let PlasticityRuntimeStoresV1 {
                        artifacts,
                        ledger,
                        owner_evidence_resolver,
                        owner_evidence_policy,
                        verifier,
                        parameter_writer,
                        parameter_anchor_store,
                        ..
                    } = &mut *stores;
                    propose_agentd_plasticity_v1(
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
                })
                .await
                .unwrap_or(Err(PlasticityRuntimeCallErrorV1::Internal(
                    "plasticity blocking worker failed",
                )));
                self.metrics.add_processing(started.elapsed());
                self.metrics
                    .completed_parameter_requests
                    .fetch_add(1, Ordering::Relaxed);
                let _ = response.send(result);
            }
            ParameterRuntimeCommandV1::SelfIteration {
                prepared,
                now,
                control,
                response,
            } => {
                self.metrics.add_queue_wait(control.enqueued_at.elapsed());
                if response.is_closed() {
                    return Ok(());
                }
                if let Some(error) = control.terminal_error() {
                    let _ = response.send(Err(error));
                    return Ok(());
                }
                if !state.plasticity_admission_ready()? {
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                    return Ok(());
                }
                let context = prepared.context.clone();
                let request = prepared.request;
                let started = Instant::now();
                let stores = self.stores.clone();
                let cancellation = control.cancellation.clone();
                let product = tokio::task::spawn_blocking(move || {
                    if cancellation.is_cancelled() {
                        return Err(PlasticityRuntimeCallErrorV1::Cancelled);
                    }
                    let mut stores = stores.lock().map_err(|_| {
                        PlasticityRuntimeCallErrorV1::Internal(
                            "plasticity runtime stores poisoned",
                        )
                    })?;
                    let PlasticityRuntimeStoresV1 {
                        artifacts,
                        ledger,
                        owner_evidence_resolver,
                        owner_evidence_policy,
                        verifier,
                        parameter_writer,
                        parameter_anchor_store,
                        ..
                    } = &mut *stores;
                    propose_agentd_plasticity_v1(
                        request,
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
                })
                .await
                .unwrap_or(Err(PlasticityRuntimeCallErrorV1::Internal(
                    "plasticity blocking worker failed",
                )));
                let result = parameter_self_iteration_result(&context, product);
                self.metrics.add_processing(started.elapsed());
                self.metrics
                    .completed_parameter_requests
                    .fetch_add(1, Ordering::Relaxed);
                let _ = response.send(result);
            }
        }
        Ok(())
    }

    async fn process_topology(
        &self,
        state: &AgentdState,
        command: TopologyRuntimeCommandV1,
    ) -> Result<(), AgentdError> {
        match command {
            TopologyRuntimeCommandV1::Product {
                request,
                now,
                control,
                response,
            } => {
                self.metrics.add_queue_wait(control.enqueued_at.elapsed());
                if response.is_closed() {
                    return Ok(());
                }
                if let Some(error) = control.terminal_error() {
                    let _ = response.send(Err(error));
                    return Ok(());
                }
                if !state.plasticity_admission_ready()? {
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                    return Ok(());
                }
                let started = Instant::now();
                let stores = self.stores.clone();
                let cancellation = control.cancellation.clone();
                let result = tokio::task::spawn_blocking(move || {
                    if cancellation.is_cancelled() {
                        return Err(PlasticityRuntimeCallErrorV1::Cancelled);
                    }
                    let mut stores = stores.lock().map_err(|_| {
                        PlasticityRuntimeCallErrorV1::Internal(
                            "plasticity runtime stores poisoned",
                        )
                    })?;
                    let PlasticityRuntimeStoresV1 {
                        artifacts,
                        ledger,
                        verifier,
                        topology_writer,
                        topology_anchor_store,
                        ..
                    } = &mut *stores;
                    propose_agentd_topology_plasticity_v1(
                        *request,
                        artifacts,
                        ledger,
                        verifier,
                        topology_writer,
                        topology_anchor_store,
                        now,
                    )
                    .map_err(PlasticityRuntimeCallErrorV1::Topology)
                })
                .await
                .unwrap_or(Err(PlasticityRuntimeCallErrorV1::Internal(
                    "plasticity blocking worker failed",
                )));
                self.metrics.add_processing(started.elapsed());
                self.metrics
                    .completed_topology_requests
                    .fetch_add(1, Ordering::Relaxed);
                let _ = response.send(result);
            }
            TopologyRuntimeCommandV1::SelfIteration {
                prepared,
                now,
                control,
                response,
            } => {
                self.metrics.add_queue_wait(control.enqueued_at.elapsed());
                if response.is_closed() {
                    return Ok(());
                }
                if let Some(error) = control.terminal_error() {
                    let _ = response.send(Err(error));
                    return Ok(());
                }
                if !state.plasticity_admission_ready()? {
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                    return Ok(());
                }
                let context = prepared.context.clone();
                let request = prepared.request;
                let started = Instant::now();
                let stores = self.stores.clone();
                let cancellation = control.cancellation.clone();
                let product = tokio::task::spawn_blocking(move || {
                    if cancellation.is_cancelled() {
                        return Err(PlasticityRuntimeCallErrorV1::Cancelled);
                    }
                    let mut stores = stores.lock().map_err(|_| {
                        PlasticityRuntimeCallErrorV1::Internal(
                            "plasticity runtime stores poisoned",
                        )
                    })?;
                    let PlasticityRuntimeStoresV1 {
                        artifacts,
                        ledger,
                        verifier,
                        topology_writer,
                        topology_anchor_store,
                        ..
                    } = &mut *stores;
                    propose_agentd_topology_plasticity_v1(
                        request,
                        artifacts,
                        ledger,
                        verifier,
                        topology_writer,
                        topology_anchor_store,
                        now,
                    )
                    .map_err(PlasticityRuntimeCallErrorV1::Topology)
                })
                .await
                .unwrap_or(Err(PlasticityRuntimeCallErrorV1::Internal(
                    "plasticity blocking worker failed",
                )));
                let result = topology_self_iteration_result(&context, product);
                self.metrics.add_processing(started.elapsed());
                self.metrics
                    .completed_topology_requests
                    .fetch_add(1, Ordering::Relaxed);
                let _ = response.send(result);
            }
        }
        Ok(())
    }
}

fn parameter_self_iteration_result(
    context: &crate::PreparedSelfIterationContextV1,
    product: Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
) -> Result<ParameterSelfIterationRuntimeReceiptV1, PlasticityRuntimeCallErrorV1> {
    match product {
        Ok(product) => Ok(ParameterSelfIterationRuntimeReceiptV1 {
            terminal: complete_parameter_self_iteration_v1(context, &product)?,
            product: Some(product),
        }),
        Err(PlasticityRuntimeCallErrorV1::Parameter(error)) => {
            let failure_digest = runtime_failure_digest(b"parameter", &error);
            Ok(ParameterSelfIterationRuntimeReceiptV1 {
                terminal: reject_self_iteration_v1(
                    context,
                    failure_digest,
                    parameter_error_requires_reconciliation_v1(&error),
                )?,
                product: None,
            })
        }
        Err(error) => Err(error),
    }
}

fn topology_self_iteration_result(
    context: &crate::PreparedSelfIterationContextV1,
    product: Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
) -> Result<TopologySelfIterationRuntimeReceiptV1, PlasticityRuntimeCallErrorV1> {
    match product {
        Ok(product) => Ok(TopologySelfIterationRuntimeReceiptV1 {
            terminal: complete_topology_self_iteration_v1(context, &product)?,
            product: Some(product),
        }),
        Err(PlasticityRuntimeCallErrorV1::Topology(error)) => {
            let failure_digest = runtime_failure_digest(b"topology", &error);
            Ok(TopologySelfIterationRuntimeReceiptV1 {
                terminal: reject_self_iteration_v1(
                    context,
                    failure_digest,
                    topology_error_requires_reconciliation_v1(&error),
                )?,
                product: None,
            })
        }
        Err(error) => Err(error),
    }
}

fn runtime_failure_digest(label: &[u8], error: &impl fmt::Debug) -> Digest32 {
    let mut bytes = b"hepta.agentd.plasticity-runtime-failure.v1\0".to_vec();
    bytes.extend_from_slice(label);
    bytes.extend_from_slice(format!("{error:?}").as_bytes());
    Digest32::of_bytes(&bytes)
}

pub(crate) fn parameter_error_requires_reconciliation_v1(
    error: &AgentdPlasticityHostErrorV1,
) -> bool {
    match error {
        AgentdPlasticityHostErrorV1::AnchorIo(_) => true,
        AgentdPlasticityHostErrorV1::Writer(AnchoredPlasticityWriterErrorV1::Registry(
            error,
        )) => matches!(
            error,
            DurableProposalRegistryError::Indeterminate
                | DurableProposalRegistryError::Poisoned
                | DurableProposalRegistryError::Io(_)
        ),
        AgentdPlasticityHostErrorV1::Product(
            ParameterPlasticityProductErrorV1::AnchorPersistenceFailed,
        ) => true,
        AgentdPlasticityHostErrorV1::Product(ParameterPlasticityProductErrorV1::Registry(
            error,
        )) => matches!(
            error,
            DurableProposalRegistryError::Indeterminate
                | DurableProposalRegistryError::Poisoned
                | DurableProposalRegistryError::Io(_)
        ),
        _ => false,
    }
}

pub(crate) fn topology_error_requires_reconciliation_v1(
    error: &AgentdTopologyHostErrorV1,
) -> bool {
    match error {
        AgentdTopologyHostErrorV1::AnchorIo(_)
        | AgentdTopologyHostErrorV1::AnchorPersistenceFailed
        | AgentdTopologyHostErrorV1::Poisoned => true,
        AgentdTopologyHostErrorV1::Registry(error) => matches!(
            error,
            DurableTopologyRegistryErrorV1::Indeterminate
                | DurableTopologyRegistryErrorV1::Poisoned
                | DurableTopologyRegistryErrorV1::Io(_)
        ),
        AgentdTopologyHostErrorV1::Product(TopologyPlasticityProductErrorV1::Registry(
            error,
        )) => matches!(
            error,
            DurableTopologyRegistryErrorV1::Indeterminate
                | DurableTopologyRegistryErrorV1::Poisoned
                | DurableTopologyRegistryErrorV1::Io(_)
        ),
        _ => false,
    }
}

#[cfg(test)]
#[path = "plasticity_runtime_lifetime_tests.rs"]
mod lifetime_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_limits_bound_both_lanes_and_resource_budgets() {
        assert!(PlasticityRuntimeLimitsV1::from_lane_capacity(1).is_ok());
        assert!(
            PlasticityRuntimeLimitsV1::from_lane_capacity(MAX_PLASTICITY_RUNTIME_QUEUE).is_ok()
        );
        assert!(PlasticityRuntimeLimitsV1::from_lane_capacity(0).is_err());
        assert!(
            PlasticityRuntimeLimitsV1::from_lane_capacity(MAX_PLASTICITY_RUNTIME_QUEUE + 1)
                .is_err()
        );
        assert!(
            validate_plasticity_runtime_limits(PlasticityRuntimeLimitsV1 {
                lane_capacity: 1,
                maximum_queued_encoded_bytes: 0,
                maximum_queued_work_units: 1,
            })
            .is_err()
        );
    }

    #[test]
    fn absolute_deadline_is_converted_to_bounded_monotonic_time() {
        assert!(runtime_deadline(10, 11).expect("deadline").is_some());
        assert!(runtime_deadline(10, u64::MAX).expect("unbounded").is_none());
        assert!(matches!(
            runtime_deadline(11, 10),
            Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
        ));
    }
}
