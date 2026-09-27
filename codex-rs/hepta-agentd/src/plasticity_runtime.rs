//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! Parameter and topology submissions use separate bounded queues, a shared byte
//! and work-unit budget, fair dequeue, caller cancellation checks and absolute
//! queue-admission deadlines. Synchronous filesystem and cryptographic work runs
//! on the blocking pool while the sole mutable owner remains generation fenced.
//! No handle contains a writer, trust root or authority to select/apply a proposal.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
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
use tokio::time::Instant;
use tokio::time::timeout_at;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdPlasticityHostErrorV1;
use crate::AgentdState;
use crate::AgentdTopologyAnchorStoreV1;
use crate::AgentdTopologyHostErrorV1;
use crate::AgentdTopologyWriterV1;
use crate::ControlEngineeringIterationBootstrapV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const MAX_PLASTICITY_RUNTIME_BYTES: usize = 256 * 1024 * 1024;
const MAX_PLASTICITY_RUNTIME_WORK_UNITS: usize = 1_048_576;
const DEFAULT_INFLIGHT_BYTES: usize = 32 * 1024 * 1024;
const DEFAULT_INFLIGHT_WORK_UNITS: usize = 65_536;
const DEFAULT_QUEUE_DEADLINE_SECONDS: u64 = 30;

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    DeadlineExceeded,
    RequestTooLarge,
    WorkBudgetExceeded,
    OwnerPoisoned,
    Parameter(AgentdPlasticityHostErrorV1),
    Topology(AgentdTopologyHostErrorV1),
}
impl fmt::Display for PlasticityRuntimeCallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityRuntimeCallErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeLimitsV1 {
    pub queue_capacity_per_kind: usize,
    pub maximum_inflight_encoded_bytes: usize,
    pub maximum_inflight_work_units: usize,
    pub default_queue_deadline_seconds: u64,
}
impl PlasticityRuntimeLimitsV1 {
    pub fn validate(self) -> Result<Self, AgentdError> {
        if !(1..=MAX_PLASTICITY_RUNTIME_QUEUE).contains(&self.queue_capacity_per_kind) {
            return Err(AgentdError::Invalid(format!(
                "plasticity queue capacity must be within 1..={MAX_PLASTICITY_RUNTIME_QUEUE}"
            )));
        }
        if !(1..=MAX_PLASTICITY_RUNTIME_BYTES).contains(&self.maximum_inflight_encoded_bytes) {
            return Err(AgentdError::Invalid(format!(
                "plasticity byte budget must be within 1..={MAX_PLASTICITY_RUNTIME_BYTES}"
            )));
        }
        if !(1..=MAX_PLASTICITY_RUNTIME_WORK_UNITS)
            .contains(&self.maximum_inflight_work_units)
        {
            return Err(AgentdError::Invalid(format!(
                "plasticity work budget must be within 1..={MAX_PLASTICITY_RUNTIME_WORK_UNITS}"
            )));
        }
        if self.default_queue_deadline_seconds == 0
            || self.default_queue_deadline_seconds > 3_600
        {
            return Err(AgentdError::Invalid(
                "plasticity default queue deadline must be within 1..=3600 seconds".to_string(),
            ));
        }
        Ok(self)
    }
}
impl Default for PlasticityRuntimeLimitsV1 {
    fn default() -> Self {
        Self {
            queue_capacity_per_kind: MAX_PLASTICITY_RUNTIME_QUEUE,
            maximum_inflight_encoded_bytes: DEFAULT_INFLIGHT_BYTES,
            maximum_inflight_work_units: DEFAULT_INFLIGHT_WORK_UNITS,
            default_queue_deadline_seconds: DEFAULT_QUEUE_DEADLINE_SECONDS,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PlasticityRuntimeMetricsV1 {
    pub parameter_enqueued: u64,
    pub topology_enqueued: u64,
    pub completed: u64,
    pub failed: u64,
    pub deadline_rejected: u64,
    pub cancelled_before_start: u64,
    pub unavailable: u64,
    pub byte_budget_rejected: u64,
    pub work_budget_rejected: u64,
    pub queue_wait_micros_total: u64,
    pub queue_wait_micros_max: u64,
    pub service_micros_total: u64,
    pub service_micros_max: u64,
}

#[derive(Default)]
struct PlasticityRuntimeMetricsInnerV1 {
    parameter_enqueued: AtomicU64,
    topology_enqueued: AtomicU64,
    completed: AtomicU64,
    failed: AtomicU64,
    deadline_rejected: AtomicU64,
    cancelled_before_start: AtomicU64,
    unavailable: AtomicU64,
    byte_budget_rejected: AtomicU64,
    work_budget_rejected: AtomicU64,
    queue_wait_micros_total: AtomicU64,
    queue_wait_micros_max: AtomicU64,
    service_micros_total: AtomicU64,
    service_micros_max: AtomicU64,
}
impl PlasticityRuntimeMetricsInnerV1 {
    fn snapshot(&self) -> PlasticityRuntimeMetricsV1 {
        let load = |value: &AtomicU64| value.load(Ordering::Relaxed);
        PlasticityRuntimeMetricsV1 {
            parameter_enqueued: load(&self.parameter_enqueued),
            topology_enqueued: load(&self.topology_enqueued),
            completed: load(&self.completed),
            failed: load(&self.failed),
            deadline_rejected: load(&self.deadline_rejected),
            cancelled_before_start: load(&self.cancelled_before_start),
            unavailable: load(&self.unavailable),
            byte_budget_rejected: load(&self.byte_budget_rejected),
            work_budget_rejected: load(&self.work_budget_rejected),
            queue_wait_micros_total: load(&self.queue_wait_micros_total),
            queue_wait_micros_max: load(&self.queue_wait_micros_max),
            service_micros_total: load(&self.service_micros_total),
            service_micros_max: load(&self.service_micros_max),
        }
    }
    fn observe_queue_wait(&self, elapsed: Duration) {
        observe_duration(
            &self.queue_wait_micros_total,
            &self.queue_wait_micros_max,
            elapsed,
        );
    }
    fn observe_service(&self, elapsed: Duration) {
        observe_duration(
            &self.service_micros_total,
            &self.service_micros_max,
            elapsed,
        );
    }
}

fn observe_duration(total: &AtomicU64, maximum: &AtomicU64, elapsed: Duration) {
    let micros = u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX);
    total.fetch_add(micros, Ordering::Relaxed);
    maximum.fetch_max(micros, Ordering::Relaxed);
}

struct RuntimeBudgetPermitsV1 {
    _bytes: OwnedSemaphorePermit,
    _work: OwnedSemaphorePermit,
}

struct ParameterCommandV1 {
    request: Box<ParameterPlasticityProductRequestV1>,
    now: u64,
    deadline: Instant,
    enqueued_at: Instant,
    _permits: RuntimeBudgetPermitsV1,
    response: oneshot::Sender<Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>>,
}

struct TopologyCommandV1 {
    request: Box<TopologyPlasticityProductRequestV1>,
    now: u64,
    deadline: Instant,
    enqueued_at: Instant,
    _permits: RuntimeBudgetPermitsV1,
    response: oneshot::Sender<Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>>,
}

enum PlasticityRuntimeCommandV1 {
    Parameter(ParameterCommandV1),
    Topology(TopologyCommandV1),
}

/// Bounded product handle. The handle contains no writer, store or trust root.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<ParameterCommandV1>,
    topology_sender: mpsc::Sender<TopologyCommandV1>,
    byte_budget: Arc<Semaphore>,
    work_budget: Arc<Semaphore>,
    limits: PlasticityRuntimeLimitsV1,
    metrics: Arc<PlasticityRuntimeMetricsInnerV1>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = now
            .checked_add(self.limits.default_queue_deadline_seconds)
            .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)?;
        self.propose_parameter_until(request, now, deadline).await
    }

    pub async fn propose_parameter_until(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = deadline_instant(now, deadline_unix_seconds)?;
        let (bytes, work) = estimate_parameter_request(&request)?;
        let permits = self.acquire_budgets(bytes, work, deadline).await?;
        let (response, receive) = oneshot::channel();
        let command = ParameterCommandV1 {
            request: Box::new(request),
            now,
            deadline,
            enqueued_at: Instant::now(),
            _permits: permits,
            response,
        };
        timeout_at(deadline, self.parameter_sender.send(command))
            .await
            .map_err(|_| {
                self.metrics.deadline_rejected.fetch_add(1, Ordering::Relaxed);
                PlasticityRuntimeCallErrorV1::DeadlineExceeded
            })?
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        self.metrics.parameter_enqueued.fetch_add(1, Ordering::Relaxed);
        receive.await.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = now
            .checked_add(self.limits.default_queue_deadline_seconds)
            .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)?;
        self.propose_topology_until(request, now, deadline).await
    }

    pub async fn propose_topology_until(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = deadline_instant(now, deadline_unix_seconds)?;
        let (bytes, work) = estimate_topology_request(&request)?;
        let permits = self.acquire_budgets(bytes, work, deadline).await?;
        let (response, receive) = oneshot::channel();
        let command = TopologyCommandV1 {
            request: Box::new(request),
            now,
            deadline,
            enqueued_at: Instant::now(),
            _permits: permits,
            response,
        };
        timeout_at(deadline, self.topology_sender.send(command))
            .await
            .map_err(|_| {
                self.metrics.deadline_rejected.fetch_add(1, Ordering::Relaxed);
                PlasticityRuntimeCallErrorV1::DeadlineExceeded
            })?
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        self.metrics.topology_enqueued.fetch_add(1, Ordering::Relaxed);
        receive.await.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }

    #[must_use]
    pub fn metrics(&self) -> PlasticityRuntimeMetricsV1 {
        self.metrics.snapshot()
    }

    async fn acquire_budgets(
        &self,
        bytes: usize,
        work: usize,
        deadline: Instant,
    ) -> Result<RuntimeBudgetPermitsV1, PlasticityRuntimeCallErrorV1> {
        if bytes > self.limits.maximum_inflight_encoded_bytes {
            self.metrics
                .byte_budget_rejected
                .fetch_add(1, Ordering::Relaxed);
            return Err(PlasticityRuntimeCallErrorV1::RequestTooLarge);
        }
        if work > self.limits.maximum_inflight_work_units {
            self.metrics
                .work_budget_rejected
                .fetch_add(1, Ordering::Relaxed);
            return Err(PlasticityRuntimeCallErrorV1::WorkBudgetExceeded);
        }
        let byte_count = u32::try_from(bytes.max(1))
            .map_err(|_| PlasticityRuntimeCallErrorV1::RequestTooLarge)?;
        let work_count = u32::try_from(work.max(1))
            .map_err(|_| PlasticityRuntimeCallErrorV1::WorkBudgetExceeded)?;
        let byte_permit = timeout_at(
            deadline,
            Arc::clone(&self.byte_budget).acquire_many_owned(byte_count),
        )
        .await
        .map_err(|_| {
            self.metrics.deadline_rejected.fetch_add(1, Ordering::Relaxed);
            PlasticityRuntimeCallErrorV1::DeadlineExceeded
        })?
        .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        let work_permit = match timeout_at(
            deadline,
            Arc::clone(&self.work_budget).acquire_many_owned(work_count),
        )
        .await
        {
            Ok(Ok(permit)) => permit,
            Ok(Err(_)) => return Err(PlasticityRuntimeCallErrorV1::Closed),
            Err(_) => {
                self.metrics.deadline_rejected.fetch_add(1, Ordering::Relaxed);
                return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
            }
        };
        Ok(RuntimeBudgetPermitsV1 {
            _bytes: byte_permit,
            _work: work_permit,
        })
    }
}

/// Immutable construction envelope consumed exactly once by Agentd runtime.
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
    control_engineering_iteration: Option<ControlEngineeringIterationBootstrapV1>,
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
        let limits = PlasticityRuntimeLimitsV1 {
            queue_capacity_per_kind: capacity,
            ..PlasticityRuntimeLimitsV1::default()
        }
        .validate()?;
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
            control_engineering_iteration: None,
        })
    }

    pub fn with_runtime_limits(
        mut self,
        limits: PlasticityRuntimeLimitsV1,
    ) -> Result<Self, AgentdError> {
        self.limits = limits.validate()?;
        Ok(self)
    }

    pub fn with_control_engineering_iteration(
        mut self,
        coordinator: ControlEngineeringIterationBootstrapV1,
    ) -> Result<Self, AgentdError> {
        if self.control_engineering_iteration.is_some() {
            return Err(AgentdError::Invalid(
                "control.engineering plasticity coordinator already configured".to_string(),
            ));
        }
        self.control_engineering_iteration = Some(coordinator);
        Ok(self)
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
            self.control_engineering_iteration,
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

/// Exact mutable owner retained for the lifetime of one Agentd generation.
pub struct PlasticityRuntimeOwnerV1 {
    parameter_receiver: mpsc::Receiver<ParameterCommandV1>,
    topology_receiver: mpsc::Receiver<TopologyCommandV1>,
    stores: Arc<Mutex<PlasticityRuntimeStoresV1>>,
    coordinator_verifier: LearningEvidenceVerifierV1,
    control_engineering_iteration: Option<ControlEngineeringIterationBootstrapV1>,
    metrics: Arc<PlasticityRuntimeMetricsInnerV1>,
    prefer_parameter: bool,
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
    let limits = PlasticityRuntimeLimitsV1 {
        queue_capacity_per_kind: capacity,
        ..PlasticityRuntimeLimitsV1::default()
    }
    .validate()?;
    plasticity_runtime_channel_with_limits_v1(
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
        None,
    )
}

#[allow(clippy::too_many_arguments)]
fn plasticity_runtime_channel_with_limits_v1(
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
    control_engineering_iteration: Option<ControlEngineeringIterationBootstrapV1>,
) -> Result<(PlasticityRuntimeHandleV1, PlasticityRuntimeOwnerV1), AgentdError> {
    let limits = limits.validate()?;
    let (parameter_sender, parameter_receiver) = mpsc::channel(limits.queue_capacity_per_kind);
    let (topology_sender, topology_receiver) = mpsc::channel(limits.queue_capacity_per_kind);
    let byte_budget = Arc::new(Semaphore::new(limits.maximum_inflight_encoded_bytes));
    let work_budget = Arc::new(Semaphore::new(limits.maximum_inflight_work_units));
    let metrics = Arc::new(PlasticityRuntimeMetricsInnerV1::default());
    let coordinator_verifier = verifier.clone();
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
            byte_budget,
            work_budget,
            limits,
            metrics: Arc::clone(&metrics),
        },
        PlasticityRuntimeOwnerV1 {
            parameter_receiver,
            topology_receiver,
            stores,
            coordinator_verifier,
            control_engineering_iteration,
            metrics,
            prefer_parameter: true,
        },
    ))
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
        let coordinator = self.control_engineering_iteration.take();
        if let Some(coordinator) = coordinator {
            let coordinator_state = Arc::clone(&state);
            let coordinator_verifier = self.coordinator_verifier.clone();
            let coordinator_cancellation = cancellation.clone();
            tokio::try_join!(
                self.run_commands(state, cancellation),
                coordinator.run(
                    coordinator_state,
                    coordinator_verifier,
                    coordinator_cancellation,
                ),
            )?;
            Ok(())
        } else {
            self.run_commands(state, cancellation).await
        }
    }

    async fn run_commands(
        &mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                command = self.next_command() => command,
            };
            let Some(command) = command else {
                cancellation.cancelled().await;
                return Ok(());
            };
            let ready = state.plasticity_admission_ready()?;
            match command {
                PlasticityRuntimeCommandV1::Parameter(command) => {
                    self.execute_parameter(command, ready).await;
                }
                PlasticityRuntimeCommandV1::Topology(command) => {
                    self.execute_topology(command, ready).await;
                }
            }
        }
    }

    async fn next_command(&mut self) -> Option<PlasticityRuntimeCommandV1> {
        loop {
            if self.prefer_parameter {
                if let Ok(command) = self.parameter_receiver.try_recv() {
                    self.prefer_parameter = false;
                    return Some(PlasticityRuntimeCommandV1::Parameter(command));
                }
                if let Ok(command) = self.topology_receiver.try_recv() {
                    self.prefer_parameter = true;
                    return Some(PlasticityRuntimeCommandV1::Topology(command));
                }
            } else {
                if let Ok(command) = self.topology_receiver.try_recv() {
                    self.prefer_parameter = true;
                    return Some(PlasticityRuntimeCommandV1::Topology(command));
                }
                if let Ok(command) = self.parameter_receiver.try_recv() {
                    self.prefer_parameter = false;
                    return Some(PlasticityRuntimeCommandV1::Parameter(command));
                }
            }
            let parameter_open = !self.parameter_receiver.is_closed();
            let topology_open = !self.topology_receiver.is_closed();
            if !parameter_open && !topology_open {
                return None;
            }
            if self.prefer_parameter {
                tokio::select! {
                    command = self.parameter_receiver.recv(), if parameter_open => {
                        if let Some(command) = command {
                            self.prefer_parameter = false;
                            return Some(PlasticityRuntimeCommandV1::Parameter(command));
                        }
                    }
                    command = self.topology_receiver.recv(), if topology_open => {
                        if let Some(command) = command {
                            self.prefer_parameter = true;
                            return Some(PlasticityRuntimeCommandV1::Topology(command));
                        }
                    }
                }
            } else {
                tokio::select! {
                    command = self.topology_receiver.recv(), if topology_open => {
                        if let Some(command) = command {
                            self.prefer_parameter = true;
                            return Some(PlasticityRuntimeCommandV1::Topology(command));
                        }
                    }
                    command = self.parameter_receiver.recv(), if parameter_open => {
                        if let Some(command) = command {
                            self.prefer_parameter = false;
                            return Some(PlasticityRuntimeCommandV1::Parameter(command));
                        }
                    }
                }
            }
        }
    }

    async fn execute_parameter(&self, command: ParameterCommandV1, ready: bool) {
        self.metrics.observe_queue_wait(command.enqueued_at.elapsed());
        if command.response.is_closed() {
            self.metrics
                .cancelled_before_start
                .fetch_add(1, Ordering::Relaxed);
            return;
        }
        if Instant::now() >= command.deadline {
            self.metrics.deadline_rejected.fetch_add(1, Ordering::Relaxed);
            let _ = command
                .response
                .send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
            return;
        }
        if !ready {
            self.metrics.unavailable.fetch_add(1, Ordering::Relaxed);
            let _ = command
                .response
                .send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return;
        }
        let service_started = Instant::now();
        let stores = Arc::clone(&self.stores);
        let result = tokio::task::spawn_blocking(move || {
            let product = match stores.lock() {
                Ok(mut stores) => {
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
                        *command.request,
                        artifacts,
                        ledger,
                        owner_evidence_resolver.as_ref(),
                        owner_evidence_policy,
                        verifier,
                        parameter_writer,
                        parameter_anchor_store,
                        command.now,
                    )
                    .map_err(PlasticityRuntimeCallErrorV1::Parameter)
                }
                Err(_) => Err(PlasticityRuntimeCallErrorV1::OwnerPoisoned),
            };
            (command.response, product)
        })
        .await;
        self.metrics.observe_service(service_started.elapsed());
        match result {
            Ok((response, product)) => {
                if product.is_ok() {
                    self.metrics.completed.fetch_add(1, Ordering::Relaxed);
                } else {
                    self.metrics.failed.fetch_add(1, Ordering::Relaxed);
                }
                let _ = response.send(product);
            }
            Err(_) => {
                self.metrics.unavailable.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    async fn execute_topology(&self, command: TopologyCommandV1, ready: bool) {
        self.metrics.observe_queue_wait(command.enqueued_at.elapsed());
        if command.response.is_closed() {
            self.metrics
                .cancelled_before_start
                .fetch_add(1, Ordering::Relaxed);
            return;
        }
        if Instant::now() >= command.deadline {
            self.metrics.deadline_rejected.fetch_add(1, Ordering::Relaxed);
            let _ = command
                .response
                .send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
            return;
        }
        if !ready {
            self.metrics.unavailable.fetch_add(1, Ordering::Relaxed);
            let _ = command
                .response
                .send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return;
        }
        let service_started = Instant::now();
        let stores = Arc::clone(&self.stores);
        let result = tokio::task::spawn_blocking(move || {
            let product = match stores.lock() {
                Ok(mut stores) => {
                    let PlasticityRuntimeStoresV1 {
                        artifacts,
                        ledger,
                        verifier,
                        topology_writer,
                        topology_anchor_store,
                        ..
                    } = &mut *stores;
                    propose_agentd_topology_plasticity_v1(
                        *command.request,
                        artifacts,
                        ledger,
                        verifier,
                        topology_writer,
                        topology_anchor_store,
                        command.now,
                    )
                    .map_err(PlasticityRuntimeCallErrorV1::Topology)
                }
                Err(_) => Err(PlasticityRuntimeCallErrorV1::OwnerPoisoned),
            };
            (command.response, product)
        })
        .await;
        self.metrics.observe_service(service_started.elapsed());
        match result {
            Ok((response, product)) => {
                if product.is_ok() {
                    self.metrics.completed.fetch_add(1, Ordering::Relaxed);
                } else {
                    self.metrics.failed.fetch_add(1, Ordering::Relaxed);
                }
                let _ = response.send(product);
            }
            Err(_) => {
                self.metrics.unavailable.fetch_add(1, Ordering::Relaxed);
            }
        }
    }
}

fn deadline_instant(
    now: u64,
    deadline_unix_seconds: u64,
) -> Result<Instant, PlasticityRuntimeCallErrorV1> {
    let seconds = deadline_unix_seconds
        .checked_sub(now)
        .filter(|seconds| *seconds > 0)
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)?;
    Instant::now()
        .checked_add(Duration::from_secs(seconds))
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
}

fn estimate_parameter_request(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<(usize, usize), PlasticityRuntimeCallErrorV1> {
    let signals = request.generator_profile.signals.len();
    let scales = request.generator_profile.update_scales.len().max(1);
    let deltas = request
        .generated
        .candidates
        .iter()
        .try_fold(0_usize, |sum, candidate| {
            sum.checked_add(candidate.parameter_deltas.len())
        })
        .ok_or(PlasticityRuntimeCallErrorV1::RequestTooLarge)?;
    let evaluations = request.evaluations.len();
    let bytes = 4_096_usize
        .checked_add(signals.saturating_mul(192))
        .and_then(|value| value.checked_add(deltas.saturating_mul(160)))
        .and_then(|value| value.checked_add(evaluations.saturating_mul(4_096)))
        .ok_or(PlasticityRuntimeCallErrorV1::RequestTooLarge)?;
    let work = 1_usize
        .checked_add(signals.saturating_mul(scales))
        .and_then(|value| value.checked_add(deltas))
        .and_then(|value| value.checked_add(evaluations.saturating_mul(32)))
        .ok_or(PlasticityRuntimeCallErrorV1::WorkBudgetExceeded)?;
    Ok((bytes, work))
}

fn estimate_topology_request(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<(usize, usize), PlasticityRuntimeCallErrorV1> {
    let changes = request.changes.len();
    let handoffs = request.handoffs.len();
    let bytes = 4_096_usize
        .checked_add(changes.saturating_mul(1_024))
        .and_then(|value| value.checked_add(handoffs.saturating_mul(512)))
        .ok_or(PlasticityRuntimeCallErrorV1::RequestTooLarge)?;
    let work = 1_usize
        .checked_add(changes.saturating_mul(32))
        .and_then(|value| value.checked_add(handoffs.saturating_mul(16)))
        .ok_or(PlasticityRuntimeCallErrorV1::WorkBudgetExceeded)?;
    Ok((bytes, work))
}

#[cfg(test)]
#[path = "plasticity_runtime_lifetime_tests.rs"]
mod lifetime_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_limits_are_bounded() {
        assert!(
            PlasticityRuntimeLimitsV1 {
                queue_capacity_per_kind: 1,
                ..PlasticityRuntimeLimitsV1::default()
            }
            .validate()
            .is_ok()
        );
        assert!(
            PlasticityRuntimeLimitsV1 {
                queue_capacity_per_kind: 0,
                ..PlasticityRuntimeLimitsV1::default()
            }
            .validate()
            .is_err()
        );
        assert!(
            PlasticityRuntimeLimitsV1 {
                maximum_inflight_encoded_bytes: MAX_PLASTICITY_RUNTIME_BYTES + 1,
                ..PlasticityRuntimeLimitsV1::default()
            }
            .validate()
            .is_err()
        );
    }

    #[test]
    fn logical_deadline_must_advance() {
        assert!(deadline_instant(10, 11).is_ok());
        assert!(matches!(
            deadline_instant(10, 10),
            Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
        ));
    }
}
