//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! Parameter and topology requests have independent bounded ingress queues and are
//! fairly arbitrated by one exclusive mutable core. Synchronous verification and
//! durable I/O run on Tokio's blocking pool rather than an async scheduler worker.
//! The handle enforces deadline, cancellation, byte and work budgets before enqueue.
//! Once a durable operation starts it is allowed to finish; a timed-out caller must
//! reconcile by deterministic proposal identity rather than assume no write.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant as StdInstant;

use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdPlasticityHostErrorV1;
use crate::AgentdState;
use crate::AgentdTopologyAnchorStoreV1;
use crate::AgentdTopologyHostErrorV1;
use crate::AgentdTopologyWriterV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;

#[path = "plasticity_iteration_coordinator.rs"]
mod iteration_coordinator;
pub use iteration_coordinator::ControlEngineeringPlasticityCoordinatorV1;
pub use iteration_coordinator::ControlEngineeringPlasticityErrorV1;
pub use iteration_coordinator::ParameterPlasticityIterationV1;
pub use iteration_coordinator::PlasticityIterationKindV1;
pub use iteration_coordinator::PlasticityIterationTerminalReceiptV1;
pub use iteration_coordinator::PlasticityIterationTerminalV1;
pub use iteration_coordinator::TopologyPlasticityIterationV1;
pub use iteration_coordinator::iteration_envelope_digest_v1;
pub use iteration_coordinator::parameter_iteration_proposal_id_v1;
pub use iteration_coordinator::topology_iteration_proposal_id_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const MAX_PLASTICITY_REQUEST_BYTES: usize = 8 * 1024 * 1024;
const MAX_PLASTICITY_ESTIMATED_WORK: usize = 16_384;
const DEFAULT_PLASTICITY_DEADLINE_SECONDS: u64 = 30;

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    Cancelled,
    DeadlineExceeded,
    BudgetExceeded {
        estimated_bytes: usize,
        estimated_work: usize,
    },
    WorkerFailed,
    Poisoned,
    Parameter(AgentdPlasticityHostErrorV1),
    Topology(AgentdTopologyHostErrorV1),
}
impl fmt::Display for PlasticityRuntimeCallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityRuntimeCallErrorV1 {}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PlasticityRuntimeMetricsSnapshotV1 {
    pub parameter_enqueued: u64,
    pub topology_enqueued: u64,
    pub completed: u64,
    pub cancelled_before_start: u64,
    pub expired_before_start: u64,
    pub budget_rejected: u64,
    pub late_completion: u64,
    pub queue_wait_micros: u64,
    pub service_micros: u64,
}

#[derive(Default)]
struct PlasticityRuntimeMetricsV1 {
    parameter_enqueued: AtomicU64,
    topology_enqueued: AtomicU64,
    completed: AtomicU64,
    cancelled_before_start: AtomicU64,
    expired_before_start: AtomicU64,
    budget_rejected: AtomicU64,
    late_completion: AtomicU64,
    queue_wait_micros: AtomicU64,
    service_micros: AtomicU64,
}
impl PlasticityRuntimeMetricsV1 {
    fn snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        PlasticityRuntimeMetricsSnapshotV1 {
            parameter_enqueued: self.parameter_enqueued.load(Ordering::Relaxed),
            topology_enqueued: self.topology_enqueued.load(Ordering::Relaxed),
            completed: self.completed.load(Ordering::Relaxed),
            cancelled_before_start: self.cancelled_before_start.load(Ordering::Relaxed),
            expired_before_start: self.expired_before_start.load(Ordering::Relaxed),
            budget_rejected: self.budget_rejected.load(Ordering::Relaxed),
            late_completion: self.late_completion.load(Ordering::Relaxed),
            queue_wait_micros: self.queue_wait_micros.load(Ordering::Relaxed),
            service_micros: self.service_micros.load(Ordering::Relaxed),
        }
    }
}

enum PlasticityRuntimeCommandV1 {
    Parameter {
        request: Box<ParameterPlasticityProductRequestV1>,
        now: u64,
        queued_at: StdInstant,
        deadline: Instant,
        cancellation: CancellationToken,
        response: oneshot::Sender<
            Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
    Topology {
        request: Box<TopologyPlasticityProductRequestV1>,
        now: u64,
        queued_at: StdInstant,
        deadline: Instant,
        cancellation: CancellationToken,
        response: oneshot::Sender<
            Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
}

/// Bounded in-process product handle. It contains no writer, store or trust-root
/// material, so dropping/recreating a handle cannot create another owner.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<PlasticityRuntimeCommandV1>,
    topology_sender: mpsc::Sender<PlasticityRuntimeCommandV1>,
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
            now.saturating_add(DEFAULT_PLASTICITY_DEADLINE_SECONDS),
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_parameter_with_control(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (estimated_bytes, estimated_work) = estimate_parameter_request(&request)?;
        if let Err(error) = validate_request_budget(estimated_bytes, estimated_work) {
            self.metrics.budget_rejected.fetch_add(1, Ordering::Relaxed);
            return Err(error);
        }
        let deadline = deadline_instant(now, deadline_unix_seconds)?;
        let child = cancellation.child_token();
        let _drop_guard = CancelOnDrop(child.clone());
        let (response, receive) = oneshot::channel();
        let command = PlasticityRuntimeCommandV1::Parameter {
            request: Box::new(request),
            now,
            queued_at: StdInstant::now(),
            deadline,
            cancellation: child.clone(),
            response,
        };
        send_before_deadline(&self.parameter_sender, command, deadline, &child).await?;
        self.metrics.parameter_enqueued.fetch_add(1, Ordering::Relaxed);
        receive_before_deadline(receive, deadline, &child).await?
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.propose_topology_with_control(
            request,
            now,
            now.saturating_add(DEFAULT_PLASTICITY_DEADLINE_SECONDS),
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_topology_with_control(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (estimated_bytes, estimated_work) = estimate_topology_request(&request)?;
        if let Err(error) = validate_request_budget(estimated_bytes, estimated_work) {
            self.metrics.budget_rejected.fetch_add(1, Ordering::Relaxed);
            return Err(error);
        }
        let deadline = deadline_instant(now, deadline_unix_seconds)?;
        let child = cancellation.child_token();
        let _drop_guard = CancelOnDrop(child.clone());
        let (response, receive) = oneshot::channel();
        let command = PlasticityRuntimeCommandV1::Topology {
            request: Box::new(request),
            now,
            queued_at: StdInstant::now(),
            deadline,
            cancellation: child.clone(),
            response,
        };
        send_before_deadline(&self.topology_sender, command, deadline, &child).await?;
        self.metrics.topology_enqueued.fetch_add(1, Ordering::Relaxed);
        receive_before_deadline(receive, deadline, &child).await?
    }

    #[must_use]
    pub fn metrics(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        self.metrics.snapshot()
    }
}

struct CancelOnDrop(CancellationToken);
impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

async fn send_before_deadline(
    sender: &mpsc::Sender<PlasticityRuntimeCommandV1>,
    command: PlasticityRuntimeCommandV1,
    deadline: Instant,
    cancellation: &CancellationToken,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    tokio::select! {
        _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
        result = tokio::time::timeout_at(deadline, sender.send(command)) => match result {
            Ok(Ok(())) => Ok(()),
            Ok(Err(_)) => Err(PlasticityRuntimeCallErrorV1::Closed),
            Err(_) => Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded),
        },
    }
}

async fn receive_before_deadline<T>(
    receive: oneshot::Receiver<Result<T, PlasticityRuntimeCallErrorV1>>,
    deadline: Instant,
    cancellation: &CancellationToken,
) -> Result<Result<T, PlasticityRuntimeCallErrorV1>, PlasticityRuntimeCallErrorV1> {
    tokio::select! {
        _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
        result = tokio::time::timeout_at(deadline, receive) => match result {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => Err(PlasticityRuntimeCallErrorV1::Closed),
            Err(_) => Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded),
        },
    }
}

fn deadline_instant(
    now: u64,
    deadline_unix_seconds: u64,
) -> Result<Instant, PlasticityRuntimeCallErrorV1> {
    let remaining = deadline_unix_seconds
        .checked_sub(now)
        .filter(|remaining| *remaining > 0)
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)?;
    Instant::now()
        .checked_add(Duration::from_secs(remaining))
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
}

/// Immutable construction envelope consumed exactly once by Agentd runtime
/// composition. Creating this value does not start a second owner or grant
/// proposal authority.
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

struct PlasticityRuntimeCoreV1 {
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
    core: Arc<Mutex<PlasticityRuntimeCoreV1>>,
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
    validate_plasticity_runtime_capacity(capacity)?;
    let (parameter_sender, parameter_receiver) = mpsc::channel(capacity);
    let (topology_sender, topology_receiver) = mpsc::channel(capacity);
    let metrics = Arc::new(PlasticityRuntimeMetricsV1::default());
    let core = Arc::new(Mutex::new(PlasticityRuntimeCoreV1 {
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
            metrics: Arc::clone(&metrics),
        },
        PlasticityRuntimeOwnerV1 {
            parameter_receiver,
            topology_receiver,
            core,
            metrics,
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

enum QueuePollV1 {
    Command(PlasticityRuntimeCommandV1),
    ParameterClosed,
    TopologyClosed,
    Cancelled,
}

impl PlasticityRuntimeOwnerV1 {
    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let mut prefer_parameter = true;
        let mut parameter_closed = false;
        let mut topology_closed = false;
        loop {
            if parameter_closed && topology_closed {
                cancellation.cancelled().await;
                return Ok(());
            }
            let polled = self
                .next_command(
                    prefer_parameter,
                    parameter_closed,
                    topology_closed,
                    &cancellation,
                )
                .await;
            match polled {
                QueuePollV1::Cancelled => return Ok(()),
                QueuePollV1::ParameterClosed => parameter_closed = true,
                QueuePollV1::TopologyClosed => topology_closed = true,
                QueuePollV1::Command(command) => {
                    prefer_parameter = !prefer_parameter;
                    let ready = state.plasticity_admission_ready()?;
                    self.process(command, ready).await;
                }
            }
        }
    }

    async fn next_command(
        &mut self,
        prefer_parameter: bool,
        parameter_closed: bool,
        topology_closed: bool,
        cancellation: &CancellationToken,
    ) -> QueuePollV1 {
        if parameter_closed {
            return tokio::select! {
                _ = cancellation.cancelled() => QueuePollV1::Cancelled,
                value = self.topology_receiver.recv() => match value {
                    Some(command) => QueuePollV1::Command(command),
                    None => QueuePollV1::TopologyClosed,
                },
            };
        }
        if topology_closed {
            return tokio::select! {
                _ = cancellation.cancelled() => QueuePollV1::Cancelled,
                value = self.parameter_receiver.recv() => match value {
                    Some(command) => QueuePollV1::Command(command),
                    None => QueuePollV1::ParameterClosed,
                },
            };
        }
        if prefer_parameter {
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => QueuePollV1::Cancelled,
                value = self.parameter_receiver.recv() => match value {
                    Some(command) => QueuePollV1::Command(command),
                    None => QueuePollV1::ParameterClosed,
                },
                value = self.topology_receiver.recv() => match value {
                    Some(command) => QueuePollV1::Command(command),
                    None => QueuePollV1::TopologyClosed,
                },
            }
        } else {
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => QueuePollV1::Cancelled,
                value = self.topology_receiver.recv() => match value {
                    Some(command) => QueuePollV1::Command(command),
                    None => QueuePollV1::TopologyClosed,
                },
                value = self.parameter_receiver.recv() => match value {
                    Some(command) => QueuePollV1::Command(command),
                    None => QueuePollV1::ParameterClosed,
                },
            }
        }
    }

    async fn process(&self, command: PlasticityRuntimeCommandV1, ready: bool) {
        match command {
            PlasticityRuntimeCommandV1::Parameter {
                request,
                now,
                queued_at,
                deadline,
                cancellation,
                response,
            } => {
                self.metrics.queue_wait_micros.fetch_add(
                    duration_micros(queued_at.elapsed()),
                    Ordering::Relaxed,
                );
                if !ready {
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                    return;
                }
                if response.is_closed() || cancellation.is_cancelled() {
                    self.metrics.cancelled_before_start.fetch_add(1, Ordering::Relaxed);
                    return;
                }
                if Instant::now() >= deadline {
                    self.metrics.expired_before_start.fetch_add(1, Ordering::Relaxed);
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
                    return;
                }
                let core = Arc::clone(&self.core);
                let started = StdInstant::now();
                let result = tokio::task::spawn_blocking(move || {
                    let mut core = core
                        .lock()
                        .map_err(|_| PlasticityRuntimeCallErrorV1::Poisoned)?;
                    let PlasticityRuntimeCoreV1 {
                        artifacts,
                        ledger,
                        owner_evidence_resolver,
                        owner_evidence_policy,
                        verifier,
                        parameter_writer,
                        parameter_anchor_store,
                        ..
                    } = &mut *core;
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
                .map_err(|_| PlasticityRuntimeCallErrorV1::WorkerFailed)
                .and_then(|value| value);
                self.finish(response, result, started);
            }
            PlasticityRuntimeCommandV1::Topology {
                request,
                now,
                queued_at,
                deadline,
                cancellation,
                response,
            } => {
                self.metrics.queue_wait_micros.fetch_add(
                    duration_micros(queued_at.elapsed()),
                    Ordering::Relaxed,
                );
                if !ready {
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                    return;
                }
                if response.is_closed() || cancellation.is_cancelled() {
                    self.metrics.cancelled_before_start.fetch_add(1, Ordering::Relaxed);
                    return;
                }
                if Instant::now() >= deadline {
                    self.metrics.expired_before_start.fetch_add(1, Ordering::Relaxed);
                    let _ = response.send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
                    return;
                }
                let core = Arc::clone(&self.core);
                let started = StdInstant::now();
                let result = tokio::task::spawn_blocking(move || {
                    let mut core = core
                        .lock()
                        .map_err(|_| PlasticityRuntimeCallErrorV1::Poisoned)?;
                    let PlasticityRuntimeCoreV1 {
                        artifacts,
                        ledger,
                        verifier,
                        topology_writer,
                        topology_anchor_store,
                        ..
                    } = &mut *core;
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
                .map_err(|_| PlasticityRuntimeCallErrorV1::WorkerFailed)
                .and_then(|value| value);
                self.finish(response, result, started);
            }
        }
    }

    fn finish<T>(
        &self,
        response: oneshot::Sender<Result<T, PlasticityRuntimeCallErrorV1>>,
        result: Result<T, PlasticityRuntimeCallErrorV1>,
        started: StdInstant,
    ) {
        self.metrics.service_micros.fetch_add(
            duration_micros(started.elapsed()),
            Ordering::Relaxed,
        );
        self.metrics.completed.fetch_add(1, Ordering::Relaxed);
        if response.send(result).is_err() {
            self.metrics.late_completion.fetch_add(1, Ordering::Relaxed);
        }
    }
}

fn estimate_parameter_request(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<(usize, usize), PlasticityRuntimeCallErrorV1> {
    let candidates = request.generated.candidates.len();
    let deltas = request
        .generated
        .candidates
        .iter()
        .try_fold(0_usize, |total, candidate| {
            total.checked_add(candidate.parameter_deltas.len())
        })
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded {
            estimated_bytes: usize::MAX,
            estimated_work: usize::MAX,
        })?;
    let signals = request.generator_profile.signals.len();
    let scales = request.generator_profile.update_scales.len().max(1);
    let evaluations = request.evaluations.len();
    let estimated_work = signals
        .checked_mul(scales)
        .and_then(|value| value.checked_add(deltas))
        .and_then(|value| value.checked_add(evaluations.saturating_mul(16)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded {
            estimated_bytes: usize::MAX,
            estimated_work: usize::MAX,
        })?;
    let estimated_bytes = 4_096_usize
        .checked_add(signals.saturating_mul(192))
        .and_then(|value| value.checked_add(deltas.saturating_mul(160)))
        .and_then(|value| value.checked_add(candidates.saturating_mul(256)))
        .and_then(|value| value.checked_add(evaluations.saturating_mul(4_096)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded {
            estimated_bytes: usize::MAX,
            estimated_work,
        })?;
    Ok((estimated_bytes, estimated_work))
}

fn estimate_topology_request(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<(usize, usize), PlasticityRuntimeCallErrorV1> {
    let changes = request.changes.len();
    let handoffs = request.handoffs.len();
    let estimated_work = changes
        .checked_mul(16)
        .and_then(|value| value.checked_add(handoffs.saturating_mul(8)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded {
            estimated_bytes: usize::MAX,
            estimated_work: usize::MAX,
        })?;
    let estimated_bytes = 4_096_usize
        .checked_add(changes.saturating_mul(1_024))
        .and_then(|value| value.checked_add(handoffs.saturating_mul(768)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded {
            estimated_bytes: usize::MAX,
            estimated_work,
        })?;
    Ok((estimated_bytes, estimated_work))
}

fn validate_request_budget(
    estimated_bytes: usize,
    estimated_work: usize,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    if estimated_bytes > MAX_PLASTICITY_REQUEST_BYTES
        || estimated_work > MAX_PLASTICITY_ESTIMATED_WORK
    {
        return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded {
            estimated_bytes,
            estimated_work,
        });
    }
    Ok(())
}

fn duration_micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
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
    fn byte_and_work_budgets_fail_closed() {
        assert!(validate_request_budget(1, 1).is_ok());
        assert!(matches!(
            validate_request_budget(MAX_PLASTICITY_REQUEST_BYTES + 1, 1),
            Err(PlasticityRuntimeCallErrorV1::BudgetExceeded { .. })
        ));
        assert!(matches!(
            validate_request_budget(1, MAX_PLASTICITY_ESTIMATED_WORK + 1),
            Err(PlasticityRuntimeCallErrorV1::BudgetExceeded { .. })
        ));
    }

    #[test]
    fn deadline_is_absolute_and_must_be_future() {
        assert!(deadline_instant(10, 11).is_ok());
        assert!(matches!(
            deadline_instant(10, 10),
            Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
        ));
    }
}
