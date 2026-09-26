//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! The owner is deliberately internal to Agentd rather than a new public wire API.
//! Callers receive bounded typed handles; all mutable proposal writers, current
//! artifact/learning frontiers, trust verification and external anchor stores stay
//! inside the daemon task. This grants no selection, model installation, topology
//! application, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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

#[path = "durable_fs.rs"]
pub(crate) mod durable_fs;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const MAX_PLASTICITY_REQUEST_BYTES: u64 = 16 * 1024 * 1024;
const MAX_PLASTICITY_REQUEST_WORK: u64 = 16_384;
const DEFAULT_PLASTICITY_DEADLINE_SECONDS: u64 = 30;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeBudgetV1 {
    /// Absolute Unix deadline, independent from evidence observation time.
    pub deadline_unix_seconds: u64,
    /// Conservative in-memory request-size estimate supplied by the producer.
    pub encoded_bytes: u64,
    /// Deterministic upper bound over generator/evaluation/topology work units.
    pub estimated_work: u64,
}

impl PlasticityRuntimeBudgetV1 {
    pub fn validate(self, wall_now: u64) -> Result<(), PlasticityRuntimeCallErrorV1> {
        if self.deadline_unix_seconds <= wall_now {
            return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
        }
        if self.encoded_bytes == 0
            || self.encoded_bytes > MAX_PLASTICITY_REQUEST_BYTES
            || self.estimated_work == 0
            || self.estimated_work > MAX_PLASTICITY_REQUEST_WORK
        {
            return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PlasticityRuntimeMetricsSnapshotV1 {
    pub parameter_enqueued: u64,
    pub topology_enqueued: u64,
    pub cancelled_before_execution: u64,
    pub deadline_rejections: u64,
    pub budget_rejections: u64,
    pub completed: u64,
    pub queue_wait_micros: u64,
    /// Includes current-frontier resolution, cryptographic verification,
    /// registry append, fsync and external anchor commit. Product receipts remain
    /// the authoritative source for the exact durability boundary.
    pub verification_append_anchor_micros: u64,
}

#[derive(Default)]
struct PlasticityRuntimeMetricsV1 {
    parameter_enqueued: AtomicU64,
    topology_enqueued: AtomicU64,
    cancelled_before_execution: AtomicU64,
    deadline_rejections: AtomicU64,
    budget_rejections: AtomicU64,
    completed: AtomicU64,
    queue_wait_micros: AtomicU64,
    verification_append_anchor_micros: AtomicU64,
}

impl PlasticityRuntimeMetricsV1 {
    fn snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        PlasticityRuntimeMetricsSnapshotV1 {
            parameter_enqueued: self.parameter_enqueued.load(Ordering::Relaxed),
            topology_enqueued: self.topology_enqueued.load(Ordering::Relaxed),
            cancelled_before_execution: self
                .cancelled_before_execution
                .load(Ordering::Relaxed),
            deadline_rejections: self.deadline_rejections.load(Ordering::Relaxed),
            budget_rejections: self.budget_rejections.load(Ordering::Relaxed),
            completed: self.completed.load(Ordering::Relaxed),
            queue_wait_micros: self.queue_wait_micros.load(Ordering::Relaxed),
            verification_append_anchor_micros: self
                .verification_append_anchor_micros
                .load(Ordering::Relaxed),
        }
    }

    fn add_duration(counter: &AtomicU64, duration: Duration) {
        let micros = u64::try_from(duration.as_micros()).unwrap_or(u64::MAX);
        counter.fetch_add(micros, Ordering::Relaxed);
    }

    fn record_rejection(&self, error: &PlasticityRuntimeCallErrorV1) {
        match error {
            PlasticityRuntimeCallErrorV1::DeadlineExceeded => {
                self.deadline_rejections.fetch_add(1, Ordering::Relaxed);
            }
            PlasticityRuntimeCallErrorV1::BudgetExceeded => {
                self.budget_rejections.fetch_add(1, Ordering::Relaxed);
            }
            _ => {}
        }
    }
}

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    Cancelled,
    DeadlineExceeded,
    BudgetExceeded,
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

struct RuntimeEnvelopeV1<T, R> {
    request: Box<T>,
    evidence_now: u64,
    budget: PlasticityRuntimeBudgetV1,
    enqueued_at: Instant,
    cancellation: CancellationToken,
    response: oneshot::Sender<Result<R, PlasticityRuntimeCallErrorV1>>,
}

type ParameterCommandV1 =
    RuntimeEnvelopeV1<ParameterPlasticityProductRequestV1, ParameterPlasticityProductReceiptV1>;
type TopologyCommandV1 =
    RuntimeEnvelopeV1<TopologyPlasticityProductRequestV1, TopologyPlasticityProductReceiptV1>;

/// Bounded in-process product handle. It contains no writer, store or trust-root
/// material, so dropping/recreating a handle cannot create another owner.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<ParameterCommandV1>,
    topology_sender: mpsc::Sender<TopologyCommandV1>,
    metrics: Arc<PlasticityRuntimeMetricsV1>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        evidence_now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let budget = estimate_parameter_budget(&request)?;
        self.propose_parameter_with_budget(
            request,
            evidence_now,
            budget,
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_parameter_with_budget(
        &self,
        request: ParameterPlasticityProductRequestV1,
        evidence_now: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        if let Err(error) = budget.validate(wall_clock_unix_seconds()?) {
            self.metrics.record_rejection(&error);
            return Err(error);
        }
        let (response, receive) = oneshot::channel();
        let command = RuntimeEnvelopeV1 {
            request: Box::new(request),
            evidence_now,
            budget,
            enqueued_at: Instant::now(),
            cancellation: cancellation.clone(),
            response,
        };
        tokio::select! {
            _ = cancellation.cancelled() => {
                self.metrics.cancelled_before_execution.fetch_add(1, Ordering::Relaxed);
                Err(PlasticityRuntimeCallErrorV1::Cancelled)
            }
            sent = self.parameter_sender.send(command) => {
                sent.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
                self.metrics.parameter_enqueued.fetch_add(1, Ordering::Relaxed);
                receive_before_deadline(receive, budget.deadline_unix_seconds, cancellation).await
            }
        }
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        evidence_now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let budget = estimate_topology_budget(&request)?;
        self.propose_topology_with_budget(
            request,
            evidence_now,
            budget,
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_topology_with_budget(
        &self,
        request: TopologyPlasticityProductRequestV1,
        evidence_now: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        if let Err(error) = budget.validate(wall_clock_unix_seconds()?) {
            self.metrics.record_rejection(&error);
            return Err(error);
        }
        let (response, receive) = oneshot::channel();
        let command = RuntimeEnvelopeV1 {
            request: Box::new(request),
            evidence_now,
            budget,
            enqueued_at: Instant::now(),
            cancellation: cancellation.clone(),
            response,
        };
        tokio::select! {
            _ = cancellation.cancelled() => {
                self.metrics.cancelled_before_execution.fetch_add(1, Ordering::Relaxed);
                Err(PlasticityRuntimeCallErrorV1::Cancelled)
            }
            sent = self.topology_sender.send(command) => {
                sent.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
                self.metrics.topology_enqueued.fetch_add(1, Ordering::Relaxed);
                receive_before_deadline(receive, budget.deadline_unix_seconds, cancellation).await
            }
        }
    }

    #[must_use]
    pub fn metrics(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        self.metrics.snapshot()
    }
}

async fn receive_before_deadline<T>(
    receive: oneshot::Receiver<Result<T, PlasticityRuntimeCallErrorV1>>,
    deadline_unix_seconds: u64,
    cancellation: CancellationToken,
) -> Result<T, PlasticityRuntimeCallErrorV1> {
    let remaining = remaining_until(deadline_unix_seconds)?;
    tokio::select! {
        _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
        value = tokio::time::timeout(remaining, receive) => match value {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err(PlasticityRuntimeCallErrorV1::Closed),
            Err(_) => Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded),
        }
    }
}

fn remaining_until(deadline_unix_seconds: u64) -> Result<Duration, PlasticityRuntimeCallErrorV1> {
    deadline_unix_seconds
        .checked_sub(wall_clock_unix_seconds()?)
        .filter(|value| *value > 0)
        .map(Duration::from_secs)
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
}

fn default_deadline() -> Result<u64, PlasticityRuntimeCallErrorV1> {
    wall_clock_unix_seconds()?
        .checked_add(DEFAULT_PLASTICITY_DEADLINE_SECONDS)
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
}

fn estimate_parameter_budget(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let signal_count = u64::try_from(request.generator_profile.signals.len())
        .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let scale_count = u64::try_from(request.generator_profile.update_scales.len())
        .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let candidate_count = u64::try_from(request.generated.candidates.len())
        .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let delta_count = request.generated.candidates.iter().try_fold(0_u64, |sum, candidate| {
        let count = u64::try_from(candidate.parameter_deltas.len())
            .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
        sum.checked_add(count)
            .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)
    })?;
    let evaluation_count = u64::try_from(request.evaluations.len())
        .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let estimated_work = signal_count
        .checked_mul(scale_count.max(1))
        .and_then(|value| value.checked_add(candidate_count))
        .and_then(|value| value.checked_add(delta_count))
        .and_then(|value| value.checked_add(evaluation_count))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?
        .max(1);
    let encoded_bytes = 4_096_u64
        .checked_add(signal_count.saturating_mul(192))
        .and_then(|value| value.checked_add(delta_count.saturating_mul(160)))
        .and_then(|value| value.checked_add(evaluation_count.saturating_mul(4_096)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    Ok(PlasticityRuntimeBudgetV1 {
        deadline_unix_seconds: default_deadline()?,
        encoded_bytes,
        estimated_work,
    })
}

fn estimate_topology_budget(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let change_count = u64::try_from(request.changes.len())
        .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let handoff_count = u64::try_from(request.handoffs.len())
        .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    Ok(PlasticityRuntimeBudgetV1 {
        deadline_unix_seconds: default_deadline()?,
        encoded_bytes: 4_096_u64
            .checked_add(change_count.saturating_mul(1_024))
            .and_then(|value| value.checked_add(handoff_count.saturating_mul(512)))
            .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?,
        estimated_work: change_count
            .checked_add(handoff_count)
            .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?
            .max(1),
    })
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

struct PlasticityRuntimeResourcesV1 {
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
    parameter_receiver: mpsc::Receiver<ParameterCommandV1>,
    topology_receiver: mpsc::Receiver<TopologyCommandV1>,
    resources: Arc<Mutex<PlasticityRuntimeResourcesV1>>,
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
    let resources = Arc::new(Mutex::new(PlasticityRuntimeResourcesV1 {
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
            resources,
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

impl PlasticityRuntimeOwnerV1 {
    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let mut prefer_parameter = true;
        loop {
            let command = self
                .next_command(prefer_parameter, &cancellation)
                .await;
            prefer_parameter = !prefer_parameter;
            let Some(command) = command else {
                if cancellation.is_cancelled() {
                    return Ok(());
                }
                cancellation.cancelled().await;
                return Ok(());
            };
            match command {
                NextPlasticityCommandV1::Parameter(command) => {
                    self.execute_parameter(Arc::clone(&state), command).await?;
                }
                NextPlasticityCommandV1::Topology(command) => {
                    self.execute_topology(Arc::clone(&state), command).await?;
                }
            }
        }
    }

    async fn next_command(
        &mut self,
        prefer_parameter: bool,
        cancellation: &CancellationToken,
    ) -> Option<NextPlasticityCommandV1> {
        if prefer_parameter {
            if let Ok(command) = self.parameter_receiver.try_recv() {
                return Some(NextPlasticityCommandV1::Parameter(command));
            }
            if let Ok(command) = self.topology_receiver.try_recv() {
                return Some(NextPlasticityCommandV1::Topology(command));
            }
        } else {
            if let Ok(command) = self.topology_receiver.try_recv() {
                return Some(NextPlasticityCommandV1::Topology(command));
            }
            if let Ok(command) = self.parameter_receiver.try_recv() {
                return Some(NextPlasticityCommandV1::Parameter(command));
            }
        }
        tokio::select! {
            _ = cancellation.cancelled() => None,
            command = self.parameter_receiver.recv() => command.map(NextPlasticityCommandV1::Parameter),
            command = self.topology_receiver.recv() => command.map(NextPlasticityCommandV1::Topology),
        }
    }

    async fn execute_parameter(
        &self,
        state: Arc<AgentdState>,
        command: ParameterCommandV1,
    ) -> Result<(), AgentdError> {
        let RuntimeEnvelopeV1 {
            request,
            evidence_now,
            budget,
            enqueued_at,
            cancellation,
            response,
        } = command;
        if response.is_closed() || cancellation.is_cancelled() {
            self.metrics.cancelled_before_execution.fetch_add(1, Ordering::Relaxed);
            return Ok(());
        }
        if let Err(error) = budget.validate(wall_clock_unix_seconds().map_err(runtime_error)?) {
            self.metrics.record_rejection(&error);
            let _ = response.send(Err(error));
            return Ok(());
        }
        PlasticityRuntimeMetricsV1::add_duration(
            &self.metrics.queue_wait_micros,
            enqueued_at.elapsed(),
        );
        if !state.plasticity_admission_ready()? {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return Ok(());
        }
        let resources = Arc::clone(&self.resources);
        let started = Instant::now();
        let result = tokio::task::spawn_blocking(move || {
            let mut resources = resources
                .lock()
                .map_err(|_| PlasticityRuntimeCallErrorV1::OwnerPoisoned)?;
            let PlasticityRuntimeResourcesV1 {
                artifacts,
                ledger,
                owner_evidence_resolver,
                owner_evidence_policy,
                verifier,
                parameter_writer,
                parameter_anchor_store,
                ..
            } = &mut *resources;
            propose_agentd_plasticity_v1(
                *request,
                artifacts,
                ledger,
                owner_evidence_resolver.as_ref(),
                owner_evidence_policy,
                verifier,
                parameter_writer,
                parameter_anchor_store,
                evidence_now,
            )
            .map_err(PlasticityRuntimeCallErrorV1::Parameter)
        })
        .await
        .map_err(|_| AgentdError::Protocol("plasticity parameter worker panicked".to_string()))?;
        PlasticityRuntimeMetricsV1::add_duration(
            &self.metrics.verification_append_anchor_micros,
            started.elapsed(),
        );
        if result.is_ok() {
            self.metrics.completed.fetch_add(1, Ordering::Relaxed);
        }
        let _ = response.send(result);
        Ok(())
    }

    async fn execute_topology(
        &self,
        state: Arc<AgentdState>,
        command: TopologyCommandV1,
    ) -> Result<(), AgentdError> {
        let RuntimeEnvelopeV1 {
            request,
            evidence_now,
            budget,
            enqueued_at,
            cancellation,
            response,
        } = command;
        if response.is_closed() || cancellation.is_cancelled() {
            self.metrics.cancelled_before_execution.fetch_add(1, Ordering::Relaxed);
            return Ok(());
        }
        if let Err(error) = budget.validate(wall_clock_unix_seconds().map_err(runtime_error)?) {
            self.metrics.record_rejection(&error);
            let _ = response.send(Err(error));
            return Ok(());
        }
        PlasticityRuntimeMetricsV1::add_duration(
            &self.metrics.queue_wait_micros,
            enqueued_at.elapsed(),
        );
        if !state.plasticity_admission_ready()? {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return Ok(());
        }
        let resources = Arc::clone(&self.resources);
        let started = Instant::now();
        let result = tokio::task::spawn_blocking(move || {
            let mut resources = resources
                .lock()
                .map_err(|_| PlasticityRuntimeCallErrorV1::OwnerPoisoned)?;
            let PlasticityRuntimeResourcesV1 {
                artifacts,
                ledger,
                verifier,
                topology_writer,
                topology_anchor_store,
                ..
            } = &mut *resources;
            propose_agentd_topology_plasticity_v1(
                *request,
                artifacts,
                ledger,
                verifier,
                topology_writer,
                topology_anchor_store,
                evidence_now,
            )
            .map_err(PlasticityRuntimeCallErrorV1::Topology)
        })
        .await
        .map_err(|_| AgentdError::Protocol("plasticity topology worker panicked".to_string()))?;
        PlasticityRuntimeMetricsV1::add_duration(
            &self.metrics.verification_append_anchor_micros,
            started.elapsed(),
        );
        if result.is_ok() {
            self.metrics.completed.fetch_add(1, Ordering::Relaxed);
        }
        let _ = response.send(result);
        Ok(())
    }
}

enum NextPlasticityCommandV1 {
    Parameter(ParameterCommandV1),
    Topology(TopologyCommandV1),
}

fn wall_clock_unix_seconds() -> Result<u64, PlasticityRuntimeCallErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| PlasticityRuntimeCallErrorV1::DeadlineExceeded)
}

fn runtime_error(_error: PlasticityRuntimeCallErrorV1) -> AgentdError {
    AgentdError::Invalid("system time is before Unix epoch".to_string())
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
    fn runtime_budget_rejects_expired_and_oversized_requests() {
        assert!(matches!(
            PlasticityRuntimeBudgetV1 {
                deadline_unix_seconds: 10,
                encoded_bytes: 1,
                estimated_work: 1,
            }
            .validate(10),
            Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
        ));
        assert!(matches!(
            PlasticityRuntimeBudgetV1 {
                deadline_unix_seconds: 11,
                encoded_bytes: MAX_PLASTICITY_REQUEST_BYTES + 1,
                estimated_work: 1,
            }
            .validate(10),
            Err(PlasticityRuntimeCallErrorV1::BudgetExceeded)
        ));
    }
}
