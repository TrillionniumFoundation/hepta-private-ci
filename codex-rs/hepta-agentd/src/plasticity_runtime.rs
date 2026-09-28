//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! The owner is deliberately internal to Agentd rather than a new public wire API.
//! Callers receive bounded typed handles; all mutable proposal writers, current
//! artifact/learning frontiers, trust verification and external anchor stores stay
//! inside the daemon task. Parameter and topology use separate bounded queues with
//! alternating preference. Synchronous cryptographic and durable-file work runs on
//! Tokio's blocking pool so it cannot stall an async runtime worker. This grants no
//! selection, model installation, topology application, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
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

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const MAX_PLASTICITY_RUNTIME_ENCODED_BYTES: u32 = 2 * 1024 * 1024;
const MAX_PLASTICITY_RUNTIME_WORK_UNITS: u32 = 16_384;
const DEFAULT_PLASTICITY_DEADLINE_SECONDS: u64 = 30;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeBudgetV1 {
    pub encoded_bytes: u32,
    pub estimated_work_units: u32,
}

#[derive(Clone, Debug)]
pub struct PlasticityRuntimeRequestContextV1 {
    pub evidence_time_unix_seconds: u64,
    pub deadline_unix_seconds: u64,
    pub budget: PlasticityRuntimeBudgetV1,
    pub cancellation: CancellationToken,
}

impl PlasticityRuntimeRequestContextV1 {
    pub fn new(
        evidence_time_unix_seconds: u64,
        deadline_unix_seconds: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<Self, PlasticityRuntimeCallErrorV1> {
        let context = Self {
            evidence_time_unix_seconds,
            deadline_unix_seconds,
            budget,
            cancellation,
        };
        validate_context_common(&context)?;
        Ok(context)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeTimingV1 {
    pub queue_wait_micros: u64,
    pub blocking_execution_micros: u64,
    pub total_micros: u64,
    pub encoded_bytes: u32,
    pub estimated_work_units: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeOutcomeV1<T> {
    pub receipt: T,
    pub timing: PlasticityRuntimeTimingV1,
}

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    Cancelled,
    DeadlineExceeded,
    BudgetExceeded(&'static str),
    WorkerFailed,
    Parameter(AgentdPlasticityHostErrorV1),
    Topology(AgentdTopologyHostErrorV1),
}

impl fmt::Display for PlasticityRuntimeCallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityRuntimeCallErrorV1 {}

struct ParameterRuntimeCommandV1 {
    request: Box<ParameterPlasticityProductRequestV1>,
    context: PlasticityRuntimeRequestContextV1,
    queued_at: Instant,
    response: oneshot::Sender<
        Result<
            PlasticityRuntimeOutcomeV1<ParameterPlasticityProductReceiptV1>,
            PlasticityRuntimeCallErrorV1,
        >,
    >,
}

struct TopologyRuntimeCommandV1 {
    request: Box<TopologyPlasticityProductRequestV1>,
    context: PlasticityRuntimeRequestContextV1,
    queued_at: Instant,
    response: oneshot::Sender<
        Result<
            PlasticityRuntimeOutcomeV1<TopologyPlasticityProductReceiptV1>,
            PlasticityRuntimeCallErrorV1,
        >,
    >,
}

enum NextRuntimeCommandV1 {
    Parameter(ParameterRuntimeCommandV1),
    Topology(TopologyRuntimeCommandV1),
}

/// Bounded in-process product handle. It contains no writer, store or trust-root
/// material, so dropping/recreating a handle cannot create another owner.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    parameter_sender: mpsc::Sender<ParameterRuntimeCommandV1>,
    topology_sender: mpsc::Sender<TopologyRuntimeCommandV1>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        evidence_time_unix_seconds: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let budget = recommended_parameter_budget_v1(&request)?;
        let context = default_context(evidence_time_unix_seconds, budget)?;
        self.propose_parameter_with_context(request, context)
            .await
            .map(|outcome| outcome.receipt)
    }

    pub async fn propose_parameter_with_context(
        &self,
        request: ParameterPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<ParameterPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        let required = recommended_parameter_budget_v1(&request)?;
        validate_context(&context, required)?;
        let (response, receive) = oneshot::channel();
        let cancellation = context.cancellation.clone();
        let deadline = context.deadline_unix_seconds;
        let command = ParameterRuntimeCommandV1 {
            request: Box::new(request),
            context,
            queued_at: Instant::now(),
            response,
        };
        tokio::select! {
            _ = cancellation.cancelled() => return Err(PlasticityRuntimeCallErrorV1::Cancelled),
            _ = wait_until_unix(deadline) => {
                return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
            }
            result = self.parameter_sender.send(command) => {
                result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
            }
        }
        tokio::select! {
            _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
            _ = wait_until_unix(deadline) => Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded),
            result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        }
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        evidence_time_unix_seconds: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let budget = recommended_topology_budget_v1(&request)?;
        let context = default_context(evidence_time_unix_seconds, budget)?;
        self.propose_topology_with_context(request, context)
            .await
            .map(|outcome| outcome.receipt)
    }

    pub async fn propose_topology_with_context(
        &self,
        request: TopologyPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<TopologyPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        let required = recommended_topology_budget_v1(&request)?;
        validate_context(&context, required)?;
        let (response, receive) = oneshot::channel();
        let cancellation = context.cancellation.clone();
        let deadline = context.deadline_unix_seconds;
        let command = TopologyRuntimeCommandV1 {
            request: Box::new(request),
            context,
            queued_at: Instant::now(),
            response,
        };
        tokio::select! {
            _ = cancellation.cancelled() => return Err(PlasticityRuntimeCallErrorV1::Cancelled),
            _ = wait_until_unix(deadline) => {
                return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
            }
            result = self.topology_sender.send(command) => {
                result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
            }
        }
        tokio::select! {
            _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
            _ = wait_until_unix(deadline) => Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded),
            result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        }
    }
}

/// Immutable construction envelope consumed exactly once by Agentd runtime
/// composition. Creating this value does not start a second owner or grant
/// proposal authority; the real daemon creates the bounded channels and retains
/// the resulting owner/handle pair for its generation.
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

struct PlasticityRuntimeEngineV1 {
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
    engine: Option<PlasticityRuntimeEngineV1>,
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
    validate_plasticity_runtime_capacity(capacity)?;
    let (parameter_sender, parameter_receiver) = mpsc::channel(capacity);
    let (topology_sender, topology_receiver) = mpsc::channel(capacity);
    Ok((
        PlasticityRuntimeHandleV1 {
            parameter_sender,
            topology_sender,
        },
        PlasticityRuntimeOwnerV1 {
            parameter_receiver,
            topology_receiver,
            engine: Some(PlasticityRuntimeEngineV1 {
                artifacts,
                ledger,
                owner_evidence_resolver,
                owner_evidence_policy,
                verifier,
                parameter_writer,
                parameter_anchor_store,
                topology_writer,
                topology_anchor_store,
            }),
            prefer_parameter: true,
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
                // Plasticity is opt-in. The absence of an explicitly composed
                // owner means this generation has no proposal writer.
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
        loop {
            let Some(command) = self.next_command(&cancellation).await else {
                // Losing all producer handles is not a daemon failure. Keep the
                // exclusive stores/fences alive until the generation shuts down.
                cancellation.cancelled().await;
                return Ok(());
            };
            match command {
                NextRuntimeCommandV1::Parameter(command) => {
                    self.prefer_parameter = false;
                    self.process_parameter(&state, command).await?;
                }
                NextRuntimeCommandV1::Topology(command) => {
                    self.prefer_parameter = true;
                    self.process_topology(&state, command).await?;
                }
            }
        }
    }

    async fn next_command(
        &mut self,
        cancellation: &CancellationToken,
    ) -> Option<NextRuntimeCommandV1> {
        loop {
            if self.prefer_parameter {
                if let Ok(command) = self.parameter_receiver.try_recv() {
                    return Some(NextRuntimeCommandV1::Parameter(command));
                }
                if let Ok(command) = self.topology_receiver.try_recv() {
                    return Some(NextRuntimeCommandV1::Topology(command));
                }
            } else {
                if let Ok(command) = self.topology_receiver.try_recv() {
                    return Some(NextRuntimeCommandV1::Topology(command));
                }
                if let Ok(command) = self.parameter_receiver.try_recv() {
                    return Some(NextRuntimeCommandV1::Parameter(command));
                }
            }

            let parameter_open = !self.parameter_receiver.is_closed();
            let topology_open = !self.topology_receiver.is_closed();
            match (parameter_open, topology_open) {
                (false, false) => return None,
                (true, false) => {
                    tokio::select! {
                        _ = cancellation.cancelled() => return None,
                        command = self.parameter_receiver.recv() => {
                            if let Some(command) = command {
                                return Some(NextRuntimeCommandV1::Parameter(command));
                            }
                        }
                    }
                }
                (false, true) => {
                    tokio::select! {
                        _ = cancellation.cancelled() => return None,
                        command = self.topology_receiver.recv() => {
                            if let Some(command) = command {
                                return Some(NextRuntimeCommandV1::Topology(command));
                            }
                        }
                    }
                }
                (true, true) if self.prefer_parameter => {
                    tokio::select! {
                        biased;
                        _ = cancellation.cancelled() => return None,
                        command = self.parameter_receiver.recv() => {
                            if let Some(command) = command {
                                return Some(NextRuntimeCommandV1::Parameter(command));
                            }
                        }
                        command = self.topology_receiver.recv() => {
                            if let Some(command) = command {
                                return Some(NextRuntimeCommandV1::Topology(command));
                            }
                        }
                    }
                }
                (true, true) => {
                    tokio::select! {
                        biased;
                        _ = cancellation.cancelled() => return None,
                        command = self.topology_receiver.recv() => {
                            if let Some(command) = command {
                                return Some(NextRuntimeCommandV1::Topology(command));
                            }
                        }
                        command = self.parameter_receiver.recv() => {
                            if let Some(command) = command {
                                return Some(NextRuntimeCommandV1::Parameter(command));
                            }
                        }
                    }
                }
            }
        }
    }

    async fn process_parameter(
        &mut self,
        state: &AgentdState,
        command: ParameterRuntimeCommandV1,
    ) -> Result<(), AgentdError> {
        let ParameterRuntimeCommandV1 {
            request,
            context,
            queued_at,
            response,
        } = command;
        if response.is_closed() || context.cancellation.is_cancelled() {
            return Ok(());
        }
        if deadline_expired(context.deadline_unix_seconds) {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
            return Ok(());
        }
        validate_context(&context, recommended_parameter_budget_v1(&request).map_err(|error| {
            AgentdError::Protocol(format!("invalid parameter runtime budget: {error}"))
        })?)
        .map_err(|error| AgentdError::Protocol(format!("invalid parameter context: {error}")))?;
        if !state.plasticity_admission_ready()? {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return Ok(());
        }

        let engine = self
            .engine
            .take()
            .ok_or_else(|| AgentdError::Protocol("plasticity runtime engine missing".to_string()))?;
        let execution_started = Instant::now();
        let evidence_time = context.evidence_time_unix_seconds;
        let worker = tokio::task::spawn_blocking(move || {
            let mut engine = engine;
            let result = propose_agentd_plasticity_v1(
                *request,
                &engine.artifacts,
                &engine.ledger,
                engine.owner_evidence_resolver.as_ref(),
                &engine.owner_evidence_policy,
                &engine.verifier,
                &mut engine.parameter_writer,
                &mut engine.parameter_anchor_store,
                evidence_time,
            )
            .map_err(PlasticityRuntimeCallErrorV1::Parameter);
            (engine, result)
        })
        .await;
        let blocking_execution = execution_started.elapsed();
        let (engine, result) = match worker {
            Ok(value) => value,
            Err(_) => {
                let _ = response.send(Err(PlasticityRuntimeCallErrorV1::WorkerFailed));
                return Err(AgentdError::Protocol(
                    "plasticity parameter blocking worker failed".to_string(),
                ));
            }
        };
        self.engine = Some(engine);
        if response.is_closed() || context.cancellation.is_cancelled() {
            return Ok(());
        }
        let timing = timing(
            queued_at,
            execution_started,
            blocking_execution,
            context.budget,
        );
        let _ = response.send(result.map(|receipt| PlasticityRuntimeOutcomeV1 {
            receipt,
            timing,
        }));
        Ok(())
    }

    async fn process_topology(
        &mut self,
        state: &AgentdState,
        command: TopologyRuntimeCommandV1,
    ) -> Result<(), AgentdError> {
        let TopologyRuntimeCommandV1 {
            request,
            context,
            queued_at,
            response,
        } = command;
        if response.is_closed() || context.cancellation.is_cancelled() {
            return Ok(());
        }
        if deadline_expired(context.deadline_unix_seconds) {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded));
            return Ok(());
        }
        validate_context(&context, recommended_topology_budget_v1(&request).map_err(|error| {
            AgentdError::Protocol(format!("invalid topology runtime budget: {error}"))
        })?)
        .map_err(|error| AgentdError::Protocol(format!("invalid topology context: {error}")))?;
        if !state.plasticity_admission_ready()? {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return Ok(());
        }

        let engine = self
            .engine
            .take()
            .ok_or_else(|| AgentdError::Protocol("plasticity runtime engine missing".to_string()))?;
        let execution_started = Instant::now();
        let evidence_time = context.evidence_time_unix_seconds;
        let worker = tokio::task::spawn_blocking(move || {
            let mut engine = engine;
            let result = propose_agentd_topology_plasticity_v1(
                *request,
                &engine.artifacts,
                &engine.ledger,
                &engine.verifier,
                &mut engine.topology_writer,
                &mut engine.topology_anchor_store,
                evidence_time,
            )
            .map_err(PlasticityRuntimeCallErrorV1::Topology);
            (engine, result)
        })
        .await;
        let blocking_execution = execution_started.elapsed();
        let (engine, result) = match worker {
            Ok(value) => value,
            Err(_) => {
                let _ = response.send(Err(PlasticityRuntimeCallErrorV1::WorkerFailed));
                return Err(AgentdError::Protocol(
                    "plasticity topology blocking worker failed".to_string(),
                ));
            }
        };
        self.engine = Some(engine);
        if response.is_closed() || context.cancellation.is_cancelled() {
            return Ok(());
        }
        let timing = timing(
            queued_at,
            execution_started,
            blocking_execution,
            context.budget,
        );
        let _ = response.send(result.map(|receipt| PlasticityRuntimeOutcomeV1 {
            receipt,
            timing,
        }));
        Ok(())
    }
}

pub fn recommended_parameter_budget_v1(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let signals = request.generator_profile.signals.len();
    let scales = request.generator_profile.update_scales.len().max(1);
    let signal_evaluations = signals
        .checked_mul(scales)
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded("work arithmetic"))?;
    let deltas = request
        .generated
        .candidates
        .iter()
        .try_fold(0_usize, |sum, candidate| {
            sum.checked_add(candidate.parameter_deltas.len())
        })
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded("delta arithmetic"))?;
    let evaluations = request.evaluations.len();
    let encoded = 4_096_usize
        .checked_add(signals.saturating_mul(192))
        .and_then(|value| value.checked_add(deltas.saturating_mul(160)))
        .and_then(|value| value.checked_add(evaluations.saturating_mul(4_096)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded("byte arithmetic"))?;
    let work = signal_evaluations
        .checked_add(deltas)
        .and_then(|value| value.checked_add(evaluations.saturating_mul(64)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded("work arithmetic"))?;
    budget_from_usize(encoded, work.max(1))
}

pub fn recommended_topology_budget_v1(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let changes = request.changes.len();
    let handoffs = request.handoffs.len();
    let encoded = 4_096_usize
        .checked_add(changes.saturating_mul(1_024))
        .and_then(|value| value.checked_add(handoffs.saturating_mul(512)))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded("byte arithmetic"))?;
    let work = changes
        .saturating_mul(64)
        .saturating_add(handoffs.saturating_mul(32))
        .max(1);
    budget_from_usize(encoded, work)
}

fn budget_from_usize(
    encoded_bytes: usize,
    estimated_work_units: usize,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let budget = PlasticityRuntimeBudgetV1 {
        encoded_bytes: u32::try_from(encoded_bytes)
            .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded("encoded bytes"))?,
        estimated_work_units: u32::try_from(estimated_work_units)
            .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded("work units"))?,
    };
    validate_budget_limits(budget)?;
    Ok(budget)
}

fn default_context(
    evidence_time_unix_seconds: u64,
    budget: PlasticityRuntimeBudgetV1,
) -> Result<PlasticityRuntimeRequestContextV1, PlasticityRuntimeCallErrorV1> {
    PlasticityRuntimeRequestContextV1::new(
        evidence_time_unix_seconds,
        unix_now().saturating_add(DEFAULT_PLASTICITY_DEADLINE_SECONDS),
        budget,
        CancellationToken::new(),
    )
}

fn validate_context_common(
    context: &PlasticityRuntimeRequestContextV1,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    if context.deadline_unix_seconds == 0 || deadline_expired(context.deadline_unix_seconds) {
        return Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded);
    }
    if context.cancellation.is_cancelled() {
        return Err(PlasticityRuntimeCallErrorV1::Cancelled);
    }
    validate_budget_limits(context.budget)
}

fn validate_context(
    context: &PlasticityRuntimeRequestContextV1,
    required: PlasticityRuntimeBudgetV1,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    validate_context_common(context)?;
    if context.budget.encoded_bytes < required.encoded_bytes {
        return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded(
            "underdeclared encoded bytes",
        ));
    }
    if context.budget.estimated_work_units < required.estimated_work_units {
        return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded(
            "underdeclared work units",
        ));
    }
    Ok(())
}

fn validate_budget_limits(
    budget: PlasticityRuntimeBudgetV1,
) -> Result<(), PlasticityRuntimeCallErrorV1> {
    if budget.encoded_bytes == 0
        || budget.encoded_bytes > MAX_PLASTICITY_RUNTIME_ENCODED_BYTES
    {
        return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded(
            "encoded bytes",
        ));
    }
    if budget.estimated_work_units == 0
        || budget.estimated_work_units > MAX_PLASTICITY_RUNTIME_WORK_UNITS
    {
        return Err(PlasticityRuntimeCallErrorV1::BudgetExceeded("work units"));
    }
    Ok(())
}

fn timing(
    queued_at: Instant,
    execution_started: Instant,
    blocking_execution: Duration,
    budget: PlasticityRuntimeBudgetV1,
) -> PlasticityRuntimeTimingV1 {
    PlasticityRuntimeTimingV1 {
        queue_wait_micros: duration_micros(execution_started.saturating_duration_since(queued_at)),
        blocking_execution_micros: duration_micros(blocking_execution),
        total_micros: duration_micros(queued_at.elapsed()),
        encoded_bytes: budget.encoded_bytes,
        estimated_work_units: budget.estimated_work_units,
    }
}

fn duration_micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn deadline_expired(deadline_unix_seconds: u64) -> bool {
    unix_now() >= deadline_unix_seconds
}

async fn wait_until_unix(deadline_unix_seconds: u64) {
    let delay = deadline_unix_seconds.saturating_sub(unix_now());
    if delay > 0 {
        tokio::time::sleep(Duration::from_secs(delay)).await;
    }
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
    fn runtime_context_rejects_expired_cancelled_and_unbounded_work() {
        let valid = PlasticityRuntimeBudgetV1 {
            encoded_bytes: 1,
            estimated_work_units: 1,
        };
        assert!(
            PlasticityRuntimeRequestContextV1::new(
                1,
                unix_now().saturating_add(30),
                valid,
                CancellationToken::new(),
            )
            .is_ok()
        );
        assert!(matches!(
            PlasticityRuntimeRequestContextV1::new(
                1,
                unix_now(),
                valid,
                CancellationToken::new(),
            ),
            Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded)
        ));
        let cancelled = CancellationToken::new();
        cancelled.cancel();
        assert!(matches!(
            PlasticityRuntimeRequestContextV1::new(
                1,
                unix_now().saturating_add(30),
                valid,
                cancelled,
            ),
            Err(PlasticityRuntimeCallErrorV1::Cancelled)
        ));
        assert!(matches!(
            validate_budget_limits(PlasticityRuntimeBudgetV1 {
                encoded_bytes: MAX_PLASTICITY_RUNTIME_ENCODED_BYTES + 1,
                estimated_work_units: 1,
            }),
            Err(PlasticityRuntimeCallErrorV1::BudgetExceeded("encoded bytes"))
        ));
    }
}
