//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! Parameter and topology requests enter separate bounded queues and are drained
//! with alternating priority. Synchronous filesystem/cryptographic work executes
//! on Tokio's blocking pool behind one exclusive owner core. Callers retain an
//! absolute deadline and cancellation token. The owner grants no selection,
//! model installation, topology application, promotion or release authority.

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
use crate::SelfIterationParameterReceiptV1;
use crate::SelfIterationParameterSubmissionV1;
use crate::SelfIterationPlasticityErrorV1;
use crate::SelfIterationTerminalJournalErrorV1;
use crate::SelfIterationTerminalJournalV1;
use crate::SelfIterationTopologyReceiptV1;
use crate::SelfIterationTopologySubmissionV1;
use crate::authenticate_self_iteration_parameter_v1;
use crate::finalize_self_iteration_parameter_receipt_v1;
use crate::finalize_self_iteration_topology_receipt_v1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;
use crate::validate_self_iteration_topology_bindings_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const DEFAULT_PLASTICITY_DEADLINE_SECONDS: u64 = 30;
const MAX_PLASTICITY_DEADLINE_SECONDS: u64 = 300;
const MAX_PLASTICITY_ESTIMATED_BYTES: usize = 4 * 1024 * 1024;
const MAX_PLASTICITY_ESTIMATED_WORK: usize = 16_384;
const MAX_SELF_ITERATION_TERMINAL_RECORDS: usize = 16_384;

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    Cancelled,
    InvalidDeadline,
    DeadlineExceeded,
    BudgetExceeded,
    Clock,
    Parameter(AgentdPlasticityHostErrorV1),
    Topology(AgentdTopologyHostErrorV1),
    SelfIteration(SelfIterationPlasticityErrorV1),
    TerminalJournal(SelfIterationTerminalJournalErrorV1),
}
impl fmt::Display for PlasticityRuntimeCallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityRuntimeCallErrorV1 {}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PlasticityRuntimeMetricsSnapshotV1 {
    pub dequeued_commands: u64,
    pub cancelled_before_execution: u64,
    pub unavailable_rejections: u64,
    pub deadline_rejections: u64,
    pub budget_rejections: u64,
    pub queue_wait_micros: u64,
    pub execution_micros: u64,
    pub terminal_commit_micros: u64,
}

#[derive(Default)]
struct PlasticityRuntimeMetricsV1 {
    dequeued_commands: AtomicU64,
    cancelled_before_execution: AtomicU64,
    unavailable_rejections: AtomicU64,
    deadline_rejections: AtomicU64,
    budget_rejections: AtomicU64,
    queue_wait_micros: AtomicU64,
    execution_micros: AtomicU64,
    terminal_commit_micros: AtomicU64,
}
impl PlasticityRuntimeMetricsV1 {
    fn snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        PlasticityRuntimeMetricsSnapshotV1 {
            dequeued_commands: self.dequeued_commands.load(Ordering::Relaxed),
            cancelled_before_execution: self
                .cancelled_before_execution
                .load(Ordering::Relaxed),
            unavailable_rejections: self.unavailable_rejections.load(Ordering::Relaxed),
            deadline_rejections: self.deadline_rejections.load(Ordering::Relaxed),
            budget_rejections: self.budget_rejections.load(Ordering::Relaxed),
            queue_wait_micros: self.queue_wait_micros.load(Ordering::Relaxed),
            execution_micros: self.execution_micros.load(Ordering::Relaxed),
            terminal_commit_micros: self.terminal_commit_micros.load(Ordering::Relaxed),
        }
    }
}

struct RuntimeRequestControlV1 {
    deadline_unix_seconds: u64,
    cancellation: CancellationToken,
    enqueued_at: Instant,
    estimated_bytes: usize,
    estimated_work: usize,
}
impl RuntimeRequestControlV1 {
    fn new(
        now: u64,
        deadline_unix_seconds: u64,
        cancellation: CancellationToken,
        estimated_bytes: usize,
        estimated_work: usize,
    ) -> Result<Self, PlasticityRuntimeCallErrorV1> {
        validate_deadline(now, deadline_unix_seconds)?;
        validate_budget(estimated_bytes, estimated_work)?;
        Ok(Self {
            deadline_unix_seconds,
            cancellation,
            enqueued_at: Instant::now(),
            estimated_bytes,
            estimated_work,
        })
    }
}

enum ParameterRuntimeCommandV1 {
    Product {
        request: Box<ParameterPlasticityProductRequestV1>,
        now: u64,
        control: RuntimeRequestControlV1,
        response: oneshot::Sender<
            Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
    SelfIteration {
        submission: Box<SelfIterationParameterSubmissionV1>,
        now: u64,
        control: RuntimeRequestControlV1,
        response: oneshot::Sender<
            Result<SelfIterationParameterReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
}

enum TopologyRuntimeCommandV1 {
    Product {
        request: Box<TopologyPlasticityProductRequestV1>,
        now: u64,
        control: RuntimeRequestControlV1,
        response: oneshot::Sender<
            Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
    SelfIteration {
        submission: Box<SelfIterationTopologySubmissionV1>,
        now: u64,
        control: RuntimeRequestControlV1,
        response: oneshot::Sender<
            Result<SelfIterationTopologyReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
}

enum RuntimeCommandV1 {
    Parameter(ParameterRuntimeCommandV1),
    Topology(TopologyRuntimeCommandV1),
}

#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<ParameterRuntimeCommandV1>,
    topology_sender: mpsc::Sender<TopologyRuntimeCommandV1>,
    metrics: Arc<PlasticityRuntimeMetricsV1>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.propose_parameter_controlled(
            request,
            now,
            now.saturating_add(DEFAULT_PLASTICITY_DEADLINE_SECONDS),
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_parameter_controlled(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (estimated_bytes, estimated_work) = estimate_parameter_request(&request)?;
        let control = RuntimeRequestControlV1::new(
            now,
            deadline_unix_seconds,
            cancellation.clone(),
            estimated_bytes,
            estimated_work,
        )?;
        let (response, receive) = oneshot::channel();
        send_with_cancellation(
            &self.parameter_sender,
            ParameterRuntimeCommandV1::Product {
                request: Box::new(request),
                now,
                control,
                response,
            },
            &cancellation,
        )
        .await?;
        receive_with_control(receive, now, deadline_unix_seconds, cancellation).await
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.propose_topology_controlled(
            request,
            now,
            now.saturating_add(DEFAULT_PLASTICITY_DEADLINE_SECONDS),
            CancellationToken::new(),
        )
        .await
    }

    pub async fn propose_topology_controlled(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (estimated_bytes, estimated_work) = estimate_topology_request(&request)?;
        let control = RuntimeRequestControlV1::new(
            now,
            deadline_unix_seconds,
            cancellation.clone(),
            estimated_bytes,
            estimated_work,
        )?;
        let (response, receive) = oneshot::channel();
        send_with_cancellation(
            &self.topology_sender,
            TopologyRuntimeCommandV1::Product {
                request: Box::new(request),
                now,
                control,
                response,
            },
            &cancellation,
        )
        .await?;
        receive_with_control(receive, now, deadline_unix_seconds, cancellation).await
    }

    pub async fn propose_self_iteration_parameter(
        &self,
        submission: SelfIterationParameterSubmissionV1,
        now: u64,
        cancellation: CancellationToken,
    ) -> Result<SelfIterationParameterReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = submission.deadline_unix_seconds;
        let (base_bytes, base_work) = estimate_parameter_request(&submission.request)?;
        let missing = submission.coverage.missing_parameters.len();
        let control = RuntimeRequestControlV1::new(
            now,
            deadline,
            cancellation.clone(),
            base_bytes
                .checked_add(missing.saturating_mul(128))
                .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?,
            base_work
                .checked_add(missing)
                .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?,
        )?;
        let (response, receive) = oneshot::channel();
        send_with_cancellation(
            &self.parameter_sender,
            ParameterRuntimeCommandV1::SelfIteration {
                submission: Box::new(submission),
                now,
                control,
                response,
            },
            &cancellation,
        )
        .await?;
        receive_with_control(receive, now, deadline, cancellation).await
    }

    pub async fn propose_self_iteration_topology(
        &self,
        submission: SelfIterationTopologySubmissionV1,
        now: u64,
        cancellation: CancellationToken,
    ) -> Result<SelfIterationTopologyReceiptV1, PlasticityRuntimeCallErrorV1> {
        let deadline = submission.deadline_unix_seconds;
        let (estimated_bytes, estimated_work) = estimate_topology_request(&submission.request)?;
        let control = RuntimeRequestControlV1::new(
            now,
            deadline,
            cancellation.clone(),
            estimated_bytes,
            estimated_work,
        )?;
        let (response, receive) = oneshot::channel();
        send_with_cancellation(
            &self.topology_sender,
            TopologyRuntimeCommandV1::SelfIteration {
                submission: Box::new(submission),
                now,
                control,
                response,
            },
            &cancellation,
        )
        .await?;
        receive_with_control(receive, now, deadline, cancellation).await
    }

    #[must_use]
    pub fn metrics_snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        self.metrics.snapshot()
    }
}

async fn send_with_cancellation<T>(
    sender: &mpsc::Sender<T>,
    command: T,
    cancellation: &CancellationToken,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    tokio::select! {
        _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
        result = sender.send(command) => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed),
    }
}

async fn receive_with_control<T>(
    receive: oneshot::Receiver<Result<T, PlasticityRuntimeCallErrorV1>>,
    now: u64,
    deadline_unix_seconds: u64,
    cancellation: CancellationToken,
) -> Result<T, PlasticityRuntimeCallErrorV1> {
    let wait = Duration::from_secs(deadline_unix_seconds.saturating_sub(now));
    let timeout_cancellation = cancellation.clone();
    tokio::select! {
        _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
        result = tokio::time::timeout(wait, receive) => match result {
            Ok(Ok(value)) => value,
            Ok(Err(_)) => Err(PlasticityRuntimeCallErrorV1::Closed),
            Err(_) => {
                timeout_cancellation.cancel();
                Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
            }
        },
    }
}

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

    fn into_channel_with_terminal_journal(
        self,
        terminal_journal: SelfIterationTerminalJournalV1,
    ) -> Result<(PlasticityRuntimeHandleV1, PlasticityRuntimeOwnerV1), AgentdError> {
        plasticity_runtime_channel_internal_v1(
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
            Some(terminal_journal),
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
    terminal_journal: Option<SelfIterationTerminalJournalV1>,
}

pub struct PlasticityRuntimeOwnerV1 {
    parameter_receiver: mpsc::Receiver<ParameterRuntimeCommandV1>,
    topology_receiver: mpsc::Receiver<TopologyRuntimeCommandV1>,
    metrics: Arc<PlasticityRuntimeMetricsV1>,
    core: Arc<Mutex<PlasticityRuntimeCoreV1>>,
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
    plasticity_runtime_channel_internal_v1(
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
        None,
    )
}

#[allow(clippy::too_many_arguments)]
fn plasticity_runtime_channel_internal_v1(
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
    terminal_journal: Option<SelfIterationTerminalJournalV1>,
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
        terminal_journal,
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
            metrics,
            core,
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
            let terminal_journal = SelfIterationTerminalJournalV1::open_for_agent(
                state.identity(),
                MAX_SELF_ITERATION_TERMINAL_RECORDS,
            )
            .map_err(|error| {
                AgentdError::Invalid(format!(
                    "self-iteration terminal journal failed to open: {error}"
                ))
            })?;
            let (handle, owner) =
                bootstrap.into_channel_with_terminal_journal(terminal_journal)?;
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
                    Some(command) = self.parameter_receiver.recv() => RuntimeCommandV1::Parameter(command),
                    Some(command) = self.topology_receiver.recv() => RuntimeCommandV1::Topology(command),
                    else => {
                        cancellation.cancelled().await;
                        return Ok(());
                    }
                }
            } else {
                tokio::select! {
                    biased;
                    _ = cancellation.cancelled() => return Ok(()),
                    Some(command) = self.topology_receiver.recv() => RuntimeCommandV1::Topology(command),
                    Some(command) = self.parameter_receiver.recv() => RuntimeCommandV1::Parameter(command),
                    else => {
                        cancellation.cancelled().await;
                        return Ok(());
                    }
                }
            };
            prefer_parameter = matches!(command, RuntimeCommandV1::Topology(_));
            let ready = state.plasticity_admission_ready()?;
            match command {
                RuntimeCommandV1::Parameter(command) => {
                    self.execute_parameter(command, ready).await;
                }
                RuntimeCommandV1::Topology(command) => {
                    self.execute_topology(command, ready).await;
                }
            }
        }
    }

    async fn execute_parameter(&self, command: ParameterRuntimeCommandV1, ready: bool) {
        match command {
            ParameterRuntimeCommandV1::Product {
                request,
                now,
                control,
                response,
            } => {
                if let Err(error) = self.preflight(&control, response.is_closed(), ready) {
                    let _ = response.send(Err(error));
                    return;
                }
                let core = Arc::clone(&self.core);
                let started = Instant::now();
                let result = tokio::task::spawn_blocking(move || {
                    let mut core = core
                        .lock()
                        .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
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
                .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)
                .and_then(|result| result);
                self.record_execution(started);
                let _ = response.send(result);
            }
            ParameterRuntimeCommandV1::SelfIteration {
                submission,
                now,
                control,
                response,
            } => {
                if let Err(error) = self.preflight(&control, response.is_closed(), ready) {
                    let _ = response.send(Err(error));
                    return;
                }
                let core = Arc::clone(&self.core);
                let metrics = Arc::clone(&self.metrics);
                let started = Instant::now();
                let result = tokio::task::spawn_blocking(move || {
                    let mut core = core
                        .lock()
                        .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
                    authenticate_self_iteration_parameter_v1(&submission, &core.verifier, now)
                        .map_err(PlasticityRuntimeCallErrorV1::SelfIteration)?;
                    let product = {
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
                            submission.request.clone(),
                            artifacts,
                            ledger,
                            owner_evidence_resolver.as_ref(),
                            owner_evidence_policy,
                            verifier,
                            parameter_writer,
                            parameter_anchor_store,
                            now,
                        )
                        .map_err(PlasticityRuntimeCallErrorV1::Parameter)?
                    };
                    let terminal =
                        finalize_self_iteration_parameter_receipt_v1(&submission, &product)
                            .map_err(PlasticityRuntimeCallErrorV1::SelfIteration)?;
                    let commit_started = Instant::now();
                    core.terminal_journal
                        .as_mut()
                        .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?
                        .append_parameter(terminal.clone())
                        .map_err(PlasticityRuntimeCallErrorV1::TerminalJournal)?;
                    metrics.terminal_commit_micros.fetch_add(
                        duration_micros(commit_started.elapsed()),
                        Ordering::Relaxed,
                    );
                    Ok(terminal)
                })
                .await
                .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)
                .and_then(|result| result);
                self.record_execution(started);
                let _ = response.send(result);
            }
        }
    }

    async fn execute_topology(&self, command: TopologyRuntimeCommandV1, ready: bool) {
        match command {
            TopologyRuntimeCommandV1::Product {
                request,
                now,
                control,
                response,
            } => {
                if let Err(error) = self.preflight(&control, response.is_closed(), ready) {
                    let _ = response.send(Err(error));
                    return;
                }
                let core = Arc::clone(&self.core);
                let started = Instant::now();
                let result = tokio::task::spawn_blocking(move || {
                    let mut core = core
                        .lock()
                        .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
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
                .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)
                .and_then(|result| result);
                self.record_execution(started);
                let _ = response.send(result);
            }
            TopologyRuntimeCommandV1::SelfIteration {
                submission,
                now,
                control,
                response,
            } => {
                if let Err(error) = self.preflight(&control, response.is_closed(), ready) {
                    let _ = response.send(Err(error));
                    return;
                }
                let core = Arc::clone(&self.core);
                let metrics = Arc::clone(&self.metrics);
                let started = Instant::now();
                let result = tokio::task::spawn_blocking(move || {
                    let mut core = core
                        .lock()
                        .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
                    validate_self_iteration_topology_bindings_v1(&submission, now)
                        .map_err(PlasticityRuntimeCallErrorV1::SelfIteration)?;
                    let product = {
                        let PlasticityRuntimeCoreV1 {
                            artifacts,
                            ledger,
                            verifier,
                            topology_writer,
                            topology_anchor_store,
                            ..
                        } = &mut *core;
                        propose_agentd_topology_plasticity_v1(
                            submission.request.clone(),
                            artifacts,
                            ledger,
                            verifier,
                            topology_writer,
                            topology_anchor_store,
                            now,
                        )
                        .map_err(PlasticityRuntimeCallErrorV1::Topology)?
                    };
                    let terminal =
                        finalize_self_iteration_topology_receipt_v1(&submission, &product)
                            .map_err(PlasticityRuntimeCallErrorV1::SelfIteration)?;
                    let commit_started = Instant::now();
                    core.terminal_journal
                        .as_mut()
                        .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?
                        .append_topology(terminal.clone())
                        .map_err(PlasticityRuntimeCallErrorV1::TerminalJournal)?;
                    metrics.terminal_commit_micros.fetch_add(
                        duration_micros(commit_started.elapsed()),
                        Ordering::Relaxed,
                    );
                    Ok(terminal)
                })
                .await
                .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)
                .and_then(|result| result);
                self.record_execution(started);
                let _ = response.send(result);
            }
        }
    }

    fn preflight(
        &self,
        control: &RuntimeRequestControlV1,
        response_closed: bool,
        ready: bool,
    ) -> Result<(), PlasticityRuntimeCallErrorV1> {
        self.metrics
            .dequeued_commands
            .fetch_add(1, Ordering::Relaxed);
        self.metrics.queue_wait_micros.fetch_add(
            duration_micros(control.enqueued_at.elapsed()),
            Ordering::Relaxed,
        );
        if response_closed || control.cancellation.is_cancelled() {
            self.metrics
                .cancelled_before_execution
                .fetch_add(1, Ordering::Relaxed);
            return Err(PlasticityRuntimeCallErrorV1::Cancelled);
        }
        if !ready {
            self.metrics
                .unavailable_rejections
                .fetch_add(1, Ordering::Relaxed);
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        if unix_seconds()? > control.deadline_unix_seconds {
            self.metrics
                .deadline_rejections
                .fetch_add(1, Ordering::Relaxed);
            control.cancellation.cancel();
            return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
        }
        if control.estimated_bytes > MAX_PLASTICITY_ESTIMATED_BYTES
            || control.estimated_work > MAX_PLASTICITY_ESTIMATED_WORK
        {
            self.metrics
                .budget_rejections
                .fetch_add(1, Ordering::Relaxed);
            return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded);
        }
        Ok(())
    }

    fn record_execution(&self, started: Instant) {
        self.metrics.execution_micros.fetch_add(
            duration_micros(started.elapsed()),
            Ordering::Relaxed,
        );
    }
}

fn validate_deadline(
    now: u64,
    deadline_unix_seconds: u64,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    let horizon = deadline_unix_seconds
        .checked_sub(now)
        .ok_or(PlasticityRuntimeCallErrorV1::InvalidDeadline)?;
    if horizon == 0 || horizon > MAX_PLASTICITY_DEADLINE_SECONDS {
        return Err(PlasticityRuntimeCallErrorV1::InvalidDeadline);
    }
    Ok(())
}

fn validate_budget(
    estimated_bytes: usize,
    estimated_work: usize,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    if estimated_bytes > MAX_PLASTICITY_ESTIMATED_BYTES
        || estimated_work > MAX_PLASTICITY_ESTIMATED_WORK
    {
        return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded);
    }
    Ok(())
}

fn estimate_parameter_request(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<(usize, usize), PlasticityRuntimeCallErrorV1> {
    let generator_work = request
        .generator_profile
        .signals
        .len()
        .checked_mul(request.generator_profile.update_scales.len().max(1))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let delta_work = request
        .generated
        .candidates
        .iter()
        .try_fold(0_usize, |sum, candidate| {
            sum.checked_add(candidate.parameter_deltas.len())
        })
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let work = generator_work
        .checked_add(delta_work)
        .and_then(|value| value.checked_add(request.evaluations.len()))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let bytes = work
        .checked_mul(256)
        .and_then(|value| value.checked_add(8 * 1024))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    validate_budget(bytes, work)?;
    Ok((bytes, work))
}

fn estimate_topology_request(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<(usize, usize), PlasticityRuntimeCallErrorV1> {
    let work = request
        .changes
        .len()
        .checked_add(request.handoffs.len())
        .and_then(|value| value.checked_add(1))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    let bytes = work
        .checked_mul(1024)
        .and_then(|value| value.checked_add(8 * 1024))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded)?;
    validate_budget(bytes, work)?;
    Ok((bytes, work))
}

fn unix_seconds() -> Result<u64, PlasticityRuntimeCallErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| PlasticityRuntimeCallErrorV1::Clock)
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
    fn runtime_deadline_is_absolute_and_bounded() {
        assert!(validate_deadline(10, 11).is_ok());
        assert!(validate_deadline(10, 10).is_err());
        assert!(validate_deadline(10, 9).is_err());
        assert!(
            validate_deadline(10, 10 + MAX_PLASTICITY_DEADLINE_SECONDS + 1).is_err()
        );
    }

    #[test]
    fn runtime_work_budget_is_bounded() {
        assert!(validate_budget(MAX_PLASTICITY_ESTIMATED_BYTES, 1).is_ok());
        assert!(validate_budget(MAX_PLASTICITY_ESTIMATED_BYTES + 1, 1).is_err());
        assert!(validate_budget(1, MAX_PLASTICITY_ESTIMATED_WORK + 1).is_err());
    }
}
