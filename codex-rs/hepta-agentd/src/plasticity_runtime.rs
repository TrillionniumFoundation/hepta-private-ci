//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! Parameter and topology submissions use separate bounded queues and a fair
//! alternating dispatcher. Mutable writers, current owner stores, trust roots,
//! and anchor stores remain behind one exclusive execution state. Synchronous
//! verification and durable I/O run on a blocking worker rather than a Tokio
//! executor thread. This grants no selection, installation, topology-application,
//! promotion, or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicUsize;
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
use tokio::sync::Notify;
use tokio::sync::mpsc;
use tokio::sync::mpsc::error::TryRecvError;
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

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const MAX_REQUEST_ENCODED_BYTES: usize = 8 * 1024 * 1024;
const MAX_REQUEST_WORK_UNITS: usize = 1_000_000;
const MAX_QUEUED_ENCODED_BYTES: usize = 64 * 1024 * 1024;
const MAX_QUEUED_WORK_UNITS: usize = 4_000_000;
const COMPATIBILITY_DEADLINE_MILLIS: u64 = 5 * 60 * 1_000;
const CANCELLATION_PENDING: u8 = 0;
const CANCELLATION_CANCELLED: u8 = 1;
const CANCELLATION_STARTED: u8 = 2;

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    BudgetExceeded,
    Cancelled,
    DeadlineExceeded,
    Indeterminate,
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
pub struct PlasticityRuntimeRequestOptionsV1 {
    pub deadline_unix_millis: u64,
    pub encoded_bytes: usize,
    pub estimated_work_units: usize,
}

impl PlasticityRuntimeRequestOptionsV1 {
    pub fn new(
        deadline_unix_millis: u64,
        encoded_bytes: usize,
        estimated_work_units: usize,
    ) -> Result<Self, PlasticityRuntimeCallErrorV1> {
        let value = Self {
            deadline_unix_millis,
            encoded_bytes,
            estimated_work_units,
        };
        value.validate()?;
        Ok(value)
    }

    fn compatibility(encoded_bytes: usize, estimated_work_units: usize) -> Self {
        let deadline_unix_millis = current_unix_millis()
            .saturating_add(COMPATIBILITY_DEADLINE_MILLIS);
        Self {
            deadline_unix_millis,
            encoded_bytes: encoded_bytes.clamp(1, MAX_REQUEST_ENCODED_BYTES),
            estimated_work_units: estimated_work_units.clamp(1, MAX_REQUEST_WORK_UNITS),
        }
    }

    fn validate(self) -> Result<(), PlasticityRuntimeCallErrorV1> {
        if self.deadline_unix_millis == 0
            || self.encoded_bytes == 0
            || self.encoded_bytes > MAX_REQUEST_ENCODED_BYTES
            || self.estimated_work_units == 0
            || self.estimated_work_units > MAX_REQUEST_WORK_UNITS
        {
            return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded);
        }
        if self.deadline_unix_millis <= current_unix_millis() {
            return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
        }
        Ok(())
    }
}

/// Cancellation succeeds only before the owner marks a request started. Once a
/// durable operation begins, cancellation returns `false`; a caller-side timeout
/// is then `Indeterminate` until the terminal receipt is reconciled.
#[derive(Clone)]
pub struct PlasticityRuntimeCancellationV1 {
    state: Arc<AtomicU8>,
    notify: Arc<Notify>,
}

impl Default for PlasticityRuntimeCancellationV1 {
    fn default() -> Self {
        Self::new()
    }
}

impl PlasticityRuntimeCancellationV1 {
    #[must_use]
    pub fn new() -> Self {
        Self {
            state: Arc::new(AtomicU8::new(CANCELLATION_PENDING)),
            notify: Arc::new(Notify::new()),
        }
    }

    /// Returns true only when queued work was cancelled before durable execution.
    pub fn cancel(&self) -> bool {
        if self
            .state
            .compare_exchange(
                CANCELLATION_PENDING,
                CANCELLATION_CANCELLED,
                Ordering::AcqRel,
                Ordering::Acquire,
            )
            .is_ok()
        {
            self.notify.notify_waiters();
            true
        } else {
            false
        }
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.state.load(Ordering::Acquire) == CANCELLATION_CANCELLED
    }

    fn try_start(&self) -> bool {
        self.state
            .compare_exchange(
                CANCELLATION_PENDING,
                CANCELLATION_STARTED,
                Ordering::AcqRel,
                Ordering::Acquire,
            )
            .is_ok()
    }

    async fn cancelled(&self) {
        loop {
            if self.is_cancelled() {
                return;
            }
            self.notify.notified().await;
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PlasticityRuntimeMetricsSnapshotV1 {
    pub parameter_admitted: u64,
    pub topology_admitted: u64,
    pub parameter_completed: u64,
    pub topology_completed: u64,
    pub cancelled_before_start: u64,
    pub deadline_before_start: u64,
    pub budget_rejected: u64,
    pub response_abandoned_before_start: u64,
    pub queue_wait_nanos_total: u64,
    pub queue_wait_nanos_max: u64,
    pub host_execution_nanos_total: u64,
    pub host_execution_nanos_max: u64,
}

#[derive(Default)]
struct PlasticityRuntimeMetricsV1 {
    parameter_admitted: AtomicU64,
    topology_admitted: AtomicU64,
    parameter_completed: AtomicU64,
    topology_completed: AtomicU64,
    cancelled_before_start: AtomicU64,
    deadline_before_start: AtomicU64,
    budget_rejected: AtomicU64,
    response_abandoned_before_start: AtomicU64,
    queue_wait_nanos_total: AtomicU64,
    queue_wait_nanos_max: AtomicU64,
    host_execution_nanos_total: AtomicU64,
    host_execution_nanos_max: AtomicU64,
}

impl PlasticityRuntimeMetricsV1 {
    fn snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        PlasticityRuntimeMetricsSnapshotV1 {
            parameter_admitted: self.parameter_admitted.load(Ordering::Relaxed),
            topology_admitted: self.topology_admitted.load(Ordering::Relaxed),
            parameter_completed: self.parameter_completed.load(Ordering::Relaxed),
            topology_completed: self.topology_completed.load(Ordering::Relaxed),
            cancelled_before_start: self.cancelled_before_start.load(Ordering::Relaxed),
            deadline_before_start: self.deadline_before_start.load(Ordering::Relaxed),
            budget_rejected: self.budget_rejected.load(Ordering::Relaxed),
            response_abandoned_before_start: self
                .response_abandoned_before_start
                .load(Ordering::Relaxed),
            queue_wait_nanos_total: self.queue_wait_nanos_total.load(Ordering::Relaxed),
            queue_wait_nanos_max: self.queue_wait_nanos_max.load(Ordering::Relaxed),
            host_execution_nanos_total: self
                .host_execution_nanos_total
                .load(Ordering::Relaxed),
            host_execution_nanos_max: self.host_execution_nanos_max.load(Ordering::Relaxed),
        }
    }

    fn record_queue_wait(&self, elapsed: Duration) {
        let nanos = duration_nanos(elapsed);
        self.queue_wait_nanos_total
            .fetch_add(nanos, Ordering::Relaxed);
        update_max(&self.queue_wait_nanos_max, nanos);
    }

    fn record_host_execution(&self, elapsed: Duration) {
        let nanos = duration_nanos(elapsed);
        self.host_execution_nanos_total
            .fetch_add(nanos, Ordering::Relaxed);
        update_max(&self.host_execution_nanos_max, nanos);
    }
}

struct RuntimeBudgetV1 {
    queued_bytes: AtomicUsize,
    queued_work: AtomicUsize,
}

impl RuntimeBudgetV1 {
    fn new() -> Self {
        Self {
            queued_bytes: AtomicUsize::new(0),
            queued_work: AtomicUsize::new(0),
        }
    }

    fn reserve(
        self: &Arc<Self>,
        options: PlasticityRuntimeRequestOptionsV1,
    ) -> Result<RuntimeBudgetReservationV1, PlasticityRuntimeCallErrorV1> {
        options.validate()?;
        if !reserve_counter(
            &self.queued_bytes,
            options.encoded_bytes,
            MAX_QUEUED_ENCODED_BYTES,
        ) {
            return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded);
        }
        if !reserve_counter(
            &self.queued_work,
            options.estimated_work_units,
            MAX_QUEUED_WORK_UNITS,
        ) {
            self.queued_bytes
                .fetch_sub(options.encoded_bytes, Ordering::AcqRel);
            return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded);
        }
        Ok(RuntimeBudgetReservationV1 {
            budget: Arc::clone(self),
            encoded_bytes: options.encoded_bytes,
            estimated_work_units: options.estimated_work_units,
        })
    }
}

struct RuntimeBudgetReservationV1 {
    budget: Arc<RuntimeBudgetV1>,
    encoded_bytes: usize,
    estimated_work_units: usize,
}

impl Drop for RuntimeBudgetReservationV1 {
    fn drop(&mut self) {
        self.budget
            .queued_bytes
            .fetch_sub(self.encoded_bytes, Ordering::AcqRel);
        self.budget
            .queued_work
            .fetch_sub(self.estimated_work_units, Ordering::AcqRel);
    }
}

struct ParameterCommandV1 {
    request: Box<ParameterPlasticityProductRequestV1>,
    now: u64,
    options: PlasticityRuntimeRequestOptionsV1,
    cancellation: PlasticityRuntimeCancellationV1,
    enqueued_at: Instant,
    _reservation: RuntimeBudgetReservationV1,
    response: oneshot::Sender<
        Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
    >,
}

struct TopologyCommandV1 {
    request: Box<TopologyPlasticityProductRequestV1>,
    now: u64,
    options: PlasticityRuntimeRequestOptionsV1,
    cancellation: PlasticityRuntimeCancellationV1,
    enqueued_at: Instant,
    _reservation: RuntimeBudgetReservationV1,
    response: oneshot::Sender<
        Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
    >,
}

enum RuntimeCommandV1 {
    Parameter(ParameterCommandV1),
    Topology(TopologyCommandV1),
}

/// Bounded product handle. It contains no writer, owner store, or trust root.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<ParameterCommandV1>,
    topology_sender: mpsc::Sender<TopologyCommandV1>,
    budget: Arc<RuntimeBudgetV1>,
    metrics: Arc<PlasticityRuntimeMetricsV1>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let options = PlasticityRuntimeRequestOptionsV1::compatibility(
            estimate_parameter_bytes(&request),
            estimate_parameter_work(&request),
        );
        self.propose_parameter_with_options(
            request,
            now,
            options,
            PlasticityRuntimeCancellationV1::new(),
        )
        .await
    }

    pub async fn propose_parameter_with_options(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        options: PlasticityRuntimeRequestOptionsV1,
        cancellation: PlasticityRuntimeCancellationV1,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let reservation = match self.budget.reserve(options) {
            Ok(value) => value,
            Err(error) => {
                self.metrics.budget_rejected.fetch_add(1, Ordering::Relaxed);
                return Err(error);
            }
        };
        let deadline = runtime_deadline(options.deadline_unix_millis)?;
        let (response, receive) = oneshot::channel();
        let command = ParameterCommandV1 {
            request: Box::new(request),
            now,
            options,
            cancellation: cancellation.clone(),
            enqueued_at: Instant::now(),
            _reservation: reservation,
            response,
        };
        tokio::select! {
            result = self.parameter_sender.send(command) => {
                result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
                self.metrics.parameter_admitted.fetch_add(1, Ordering::Relaxed);
            }
            _ = cancellation.cancelled() => return Err(PlasticityRuntimeCallErrorV1::Cancelled),
            _ = tokio::time::sleep_until(deadline) => {
                let _ = cancellation.cancel();
                return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
            }
        }
        await_parameter_response(receive, deadline, cancellation).await
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let options = PlasticityRuntimeRequestOptionsV1::compatibility(
            estimate_topology_bytes(&request),
            estimate_topology_work(&request),
        );
        self.propose_topology_with_options(
            request,
            now,
            options,
            PlasticityRuntimeCancellationV1::new(),
        )
        .await
    }

    pub async fn propose_topology_with_options(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        options: PlasticityRuntimeRequestOptionsV1,
        cancellation: PlasticityRuntimeCancellationV1,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let reservation = match self.budget.reserve(options) {
            Ok(value) => value,
            Err(error) => {
                self.metrics.budget_rejected.fetch_add(1, Ordering::Relaxed);
                return Err(error);
            }
        };
        let deadline = runtime_deadline(options.deadline_unix_millis)?;
        let (response, receive) = oneshot::channel();
        let command = TopologyCommandV1 {
            request: Box::new(request),
            now,
            options,
            cancellation: cancellation.clone(),
            enqueued_at: Instant::now(),
            _reservation: reservation,
            response,
        };
        tokio::select! {
            result = self.topology_sender.send(command) => {
                result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
                self.metrics.topology_admitted.fetch_add(1, Ordering::Relaxed);
            }
            _ = cancellation.cancelled() => return Err(PlasticityRuntimeCallErrorV1::Cancelled),
            _ = tokio::time::sleep_until(deadline) => {
                let _ = cancellation.cancel();
                return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
            }
        }
        await_topology_response(receive, deadline, cancellation).await
    }

    #[must_use]
    pub fn metrics_snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        self.metrics.snapshot()
    }
}

async fn await_parameter_response(
    receive: oneshot::Receiver<
        Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
    >,
    deadline: tokio::time::Instant,
    cancellation: PlasticityRuntimeCancellationV1,
) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
    tokio::select! {
        result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
        _ = tokio::time::sleep_until(deadline) => {
            if cancellation.cancel() {
                Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
            } else {
                Err(PlasticityRuntimeCallErrorV1::Indeterminate)
            }
        }
    }
}

async fn await_topology_response(
    receive: oneshot::Receiver<
        Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
    >,
    deadline: tokio::time::Instant,
    cancellation: PlasticityRuntimeCancellationV1,
) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
    tokio::select! {
        result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
        _ = tokio::time::sleep_until(deadline) => {
            if cancellation.cancel() {
                Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
            } else {
                Err(PlasticityRuntimeCallErrorV1::Indeterminate)
            }
        }
    }
}

/// Immutable construction envelope consumed exactly once by Agentd composition.
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

/// Exact owner retained for the Agentd generation.
pub struct PlasticityRuntimeOwnerV1 {
    parameter_receiver: mpsc::Receiver<ParameterCommandV1>,
    topology_receiver: mpsc::Receiver<TopologyCommandV1>,
    execution: Arc<Mutex<PlasticityExecutionStateV1>>,
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
    let budget = Arc::new(RuntimeBudgetV1::new());
    let metrics = Arc::new(PlasticityRuntimeMetricsV1::default());
    let execution = Arc::new(Mutex::new(PlasticityExecutionStateV1 {
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
            budget,
            metrics: Arc::clone(&metrics),
        },
        PlasticityRuntimeOwnerV1 {
            parameter_receiver,
            topology_receiver,
            execution,
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
        let mut parameter_open = true;
        let mut topology_open = true;
        loop {
            let command = self
                .next_command(
                    prefer_parameter,
                    &mut parameter_open,
                    &mut topology_open,
                    &cancellation,
                )
                .await;
            let Some(command) = command else {
                return Ok(());
            };
            prefer_parameter = !prefer_parameter;
            let ready = state.plasticity_admission_ready()?;
            match command {
                RuntimeCommandV1::Parameter(command) => {
                    self.process_parameter(command, ready).await;
                }
                RuntimeCommandV1::Topology(command) => {
                    self.process_topology(command, ready).await;
                }
            }
        }
    }

    async fn next_command(
        &mut self,
        prefer_parameter: bool,
        parameter_open: &mut bool,
        topology_open: &mut bool,
        cancellation: &CancellationToken,
    ) -> Option<RuntimeCommandV1> {
        loop {
            if prefer_parameter && *parameter_open {
                match self.parameter_receiver.try_recv() {
                    Ok(command) => return Some(RuntimeCommandV1::Parameter(command)),
                    Err(TryRecvError::Disconnected) => *parameter_open = false,
                    Err(TryRecvError::Empty) => {}
                }
            }
            if !prefer_parameter && *topology_open {
                match self.topology_receiver.try_recv() {
                    Ok(command) => return Some(RuntimeCommandV1::Topology(command)),
                    Err(TryRecvError::Disconnected) => *topology_open = false,
                    Err(TryRecvError::Empty) => {}
                }
            }
            if *parameter_open {
                match self.parameter_receiver.try_recv() {
                    Ok(command) => return Some(RuntimeCommandV1::Parameter(command)),
                    Err(TryRecvError::Disconnected) => *parameter_open = false,
                    Err(TryRecvError::Empty) => {}
                }
            }
            if *topology_open {
                match self.topology_receiver.try_recv() {
                    Ok(command) => return Some(RuntimeCommandV1::Topology(command)),
                    Err(TryRecvError::Disconnected) => *topology_open = false,
                    Err(TryRecvError::Empty) => {}
                }
            }
            if !*parameter_open && !*topology_open {
                cancellation.cancelled().await;
                return None;
            }
            tokio::select! {
                _ = cancellation.cancelled() => return None,
                command = self.parameter_receiver.recv(), if *parameter_open => {
                    match command {
                        Some(command) => return Some(RuntimeCommandV1::Parameter(command)),
                        None => *parameter_open = false,
                    }
                }
                command = self.topology_receiver.recv(), if *topology_open => {
                    match command {
                        Some(command) => return Some(RuntimeCommandV1::Topology(command)),
                        None => *topology_open = false,
                    }
                }
            }
        }
    }

    async fn process_parameter(&self, command: ParameterCommandV1, ready: bool) {
        let ParameterCommandV1 {
            request,
            now,
            options,
            cancellation,
            enqueued_at,
            _reservation,
            response,
        } = command;
        self.metrics.record_queue_wait(enqueued_at.elapsed());
        if response.is_closed() {
            self.metrics
                .response_abandoned_before_start
                .fetch_add(1, Ordering::Relaxed);
            return;
        }
        if cancellation.is_cancelled() || !cancellation.try_start() {
            self.metrics
                .cancelled_before_start
                .fetch_add(1, Ordering::Relaxed);
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Cancelled));
            return;
        }
        if options.deadline_unix_millis <= current_unix_millis() {
            self.metrics
                .deadline_before_start
                .fetch_add(1, Ordering::Relaxed);
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
            return;
        }
        if !ready {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return;
        }
        let execution = Arc::clone(&self.execution);
        let started = Instant::now();
        let result = tokio::task::spawn_blocking(move || {
            let mut execution = execution
                .lock()
                .map_err(|_| PlasticityRuntimeCallErrorV1::Indeterminate)?;
            let PlasticityExecutionStateV1 {
                artifacts,
                ledger,
                owner_evidence_resolver,
                owner_evidence_policy,
                verifier,
                parameter_writer,
                parameter_anchor_store,
                ..
            } = &mut *execution;
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
        .unwrap_or(Err(PlasticityRuntimeCallErrorV1::Indeterminate));
        self.metrics.record_host_execution(started.elapsed());
        self.metrics
            .parameter_completed
            .fetch_add(1, Ordering::Relaxed);
        let _ = response.send(result);
        drop(_reservation);
    }

    async fn process_topology(&self, command: TopologyCommandV1, ready: bool) {
        let TopologyCommandV1 {
            request,
            now,
            options,
            cancellation,
            enqueued_at,
            _reservation,
            response,
        } = command;
        self.metrics.record_queue_wait(enqueued_at.elapsed());
        if response.is_closed() {
            self.metrics
                .response_abandoned_before_start
                .fetch_add(1, Ordering::Relaxed);
            return;
        }
        if cancellation.is_cancelled() || !cancellation.try_start() {
            self.metrics
                .cancelled_before_start
                .fetch_add(1, Ordering::Relaxed);
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Cancelled));
            return;
        }
        if options.deadline_unix_millis <= current_unix_millis() {
            self.metrics
                .deadline_before_start
                .fetch_add(1, Ordering::Relaxed);
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
            return;
        }
        if !ready {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return;
        }
        let execution = Arc::clone(&self.execution);
        let started = Instant::now();
        let result = tokio::task::spawn_blocking(move || {
            let mut execution = execution
                .lock()
                .map_err(|_| PlasticityRuntimeCallErrorV1::Indeterminate)?;
            let PlasticityExecutionStateV1 {
                artifacts,
                ledger,
                verifier,
                topology_writer,
                topology_anchor_store,
                ..
            } = &mut *execution;
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
        .unwrap_or(Err(PlasticityRuntimeCallErrorV1::Indeterminate));
        self.metrics.record_host_execution(started.elapsed());
        self.metrics
            .topology_completed
            .fetch_add(1, Ordering::Relaxed);
        let _ = response.send(result);
        drop(_reservation);
    }
}

fn estimate_parameter_bytes(request: &ParameterPlasticityProductRequestV1) -> usize {
    let signal_bytes = request.generator_profile.signals.len().saturating_mul(160);
    let delta_count = request
        .generated
        .candidates
        .iter()
        .map(|candidate| candidate.parameter_deltas.len())
        .sum::<usize>();
    2_048usize
        .saturating_add(signal_bytes)
        .saturating_add(delta_count.saturating_mul(128))
        .saturating_add(request.evaluations.len().saturating_mul(1_024))
}

fn estimate_parameter_work(request: &ParameterPlasticityProductRequestV1) -> usize {
    request
        .generator_profile
        .signals
        .len()
        .saturating_mul(request.generator_profile.update_scales.len().max(1))
        .saturating_add(request.generated.candidates.len().saturating_mul(8))
        .saturating_add(request.evaluations.len().saturating_mul(64))
        .max(1)
}

fn estimate_topology_bytes(request: &TopologyPlasticityProductRequestV1) -> usize {
    2_048usize
        .saturating_add(request.changes.len().saturating_mul(512))
        .saturating_add(request.handoffs.len().saturating_mul(384))
}

fn estimate_topology_work(request: &TopologyPlasticityProductRequestV1) -> usize {
    request
        .changes
        .len()
        .saturating_mul(64)
        .saturating_add(request.handoffs.len().saturating_mul(32))
        .max(1)
}

fn runtime_deadline(
    deadline_unix_millis: u64,
) -> Result<tokio::time::Instant, PlasticityRuntimeCallErrorV1> {
    let remaining = deadline_unix_millis
        .checked_sub(current_unix_millis())
        .ok_or(PlasticityRuntimeCallErrorV1::DeadlineExceeded)?;
    Ok(tokio::time::Instant::now() + Duration::from_millis(remaining))
}

fn current_unix_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(u64::MAX)
}

fn reserve_counter(counter: &AtomicUsize, amount: usize, maximum: usize) -> bool {
    let mut current = counter.load(Ordering::Acquire);
    loop {
        let Some(next) = current.checked_add(amount) else {
            return false;
        };
        if next > maximum {
            return false;
        }
        match counter.compare_exchange_weak(
            current,
            next,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => return true,
            Err(observed) => current = observed,
        }
    }
}

fn duration_nanos(duration: Duration) -> u64 {
    duration.as_nanos().try_into().unwrap_or(u64::MAX)
}

fn update_max(counter: &AtomicU64, value: u64) {
    let mut current = counter.load(Ordering::Relaxed);
    while value > current {
        match counter.compare_exchange_weak(
            current,
            value,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

#[cfg(test)]
#[path = "plasticity_runtime_lifetime_tests.rs"]
mod lifetime_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_queue_capacity_and_request_budgets_are_bounded() {
        assert!(validate_plasticity_runtime_capacity(1).is_ok());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE).is_ok());
        assert!(validate_plasticity_runtime_capacity(0).is_err());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE + 1).is_err());
        assert!(PlasticityRuntimeRequestOptionsV1::new(
            current_unix_millis().saturating_add(1_000),
            1,
            1,
        )
        .is_ok());
        assert!(matches!(
            PlasticityRuntimeRequestOptionsV1::new(
                current_unix_millis().saturating_add(1_000),
                MAX_REQUEST_ENCODED_BYTES + 1,
                1,
            ),
            Err(PlasticityRuntimeCallErrorV1::BudgetExceeded)
        ));
    }

    #[tokio::test]
    async fn cancellation_is_only_effective_before_start() {
        let cancellation = PlasticityRuntimeCancellationV1::new();
        assert!(cancellation.cancel());
        cancellation.cancelled().await;
        assert!(!cancellation.cancel());

        let started = PlasticityRuntimeCancellationV1::new();
        assert!(started.try_start());
        assert!(!started.cancel());
        assert!(!started.is_cancelled());
    }

    #[test]
    fn global_budget_reservation_is_released_on_drop() {
        let budget = Arc::new(RuntimeBudgetV1::new());
        let options = PlasticityRuntimeRequestOptionsV1 {
            deadline_unix_millis: current_unix_millis().saturating_add(1_000),
            encoded_bytes: MAX_QUEUED_ENCODED_BYTES,
            estimated_work_units: 1,
        };
        let reservation = budget.reserve(options).expect("reserve");
        assert!(matches!(
            budget.reserve(PlasticityRuntimeRequestOptionsV1 {
                deadline_unix_millis: current_unix_millis().saturating_add(1_000),
                encoded_bytes: 1,
                estimated_work_units: 1,
            }),
            Err(PlasticityRuntimeCallErrorV1::BudgetExceeded)
        ));
        drop(reservation);
        assert!(budget.reserve(PlasticityRuntimeRequestOptionsV1 {
            deadline_unix_millis: current_unix_millis().saturating_add(1_000),
            encoded_bytes: 1,
            estimated_work_units: 1,
        })
        .is_ok());
    }
}
