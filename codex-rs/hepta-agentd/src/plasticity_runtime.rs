//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! The owner is deliberately internal to Agentd rather than a new public wire API.
//! Callers receive bounded typed handles; all mutable proposal writers, current
//! artifact/learning frontiers, trust verification and external anchor stores stay
//! inside the daemon task. Parameter and topology use separate bounded queues with
//! alternating preference plus one aggregate byte/work admission ledger shared by
//! both queues. Synchronous cryptographic and durable-file work runs on Tokio's
//! blocking pool so it cannot stall an async runtime worker. This grants no
//! selection, model installation, topology application, promotion or release authority.

use std::collections::VecDeque;
use std::error::Error as StdError;
use std::fmt;
use std::mem::size_of;
use std::mem::size_of_val;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::TopologyOperationV2;
use codex_hepta_plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
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
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
const MAX_PLASTICITY_RUNTIME_ENCODED_BYTES: u32 = 2 * 1024 * 1024;
const MAX_PLASTICITY_RUNTIME_WORK_UNITS: u32 = 16_384;
const MAX_PLASTICITY_RUNTIME_TOTAL_ENCODED_BYTES: u32 = 8 * 1024 * 1024;
const MAX_PLASTICITY_RUNTIME_TOTAL_WORK_UNITS: u32 = 65_536;
const MAX_PLASTICITY_STATIC_CACHE_ENTRIES: usize = 64;
const DEFAULT_PLASTICITY_DEADLINE_SECONDS: u64 = 30;
const REQUEST_FOOTPRINT_FIXED_OVERHEAD: usize = 4_096;
const REQUEST_RETAINED_COPY_FACTOR: usize = 3;
const MAX_STABLE_ID_HEAP_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityRuntimeBudgetV1 {
    /// Conservative retained-footprint charge for the complete typed request.
    /// This is intentionally larger than a compact wire encoding and includes a
    /// fixed allocation/scratch allowance.
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
    pub static_validation_micros: u64,
    pub quota_admission_micros: u64,
    pub queue_wait_micros: u64,
    pub blocking_execution_micros: u64,
    pub total_micros: u64,
    pub encoded_bytes: u32,
    pub estimated_work_units: u32,
    pub static_validation_cache_hit: bool,
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
    Overloaded(&'static str),
    Invalid(&'static str),
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PreparedPlasticityRequestV1 {
    budget: PlasticityRuntimeBudgetV1,
    static_validation_micros: u64,
    cache_hit: bool,
}

struct PlasticityRuntimeReservationV1 {
    _encoded_bytes: OwnedSemaphorePermit,
    _work_units: OwnedSemaphorePermit,
}

struct PlasticityRuntimeAdmissionV1 {
    encoded_bytes: Arc<Semaphore>,
    work_units: Arc<Semaphore>,
}

impl PlasticityRuntimeAdmissionV1 {
    fn new() -> Self {
        Self {
            encoded_bytes: Arc::new(Semaphore::new(
                MAX_PLASTICITY_RUNTIME_TOTAL_ENCODED_BYTES as usize,
            )),
            work_units: Arc::new(Semaphore::new(
                MAX_PLASTICITY_RUNTIME_TOTAL_WORK_UNITS as usize,
            )),
        }
    }

    fn reserve(
        &self,
        budget: PlasticityRuntimeBudgetV1,
    ) -> Result<PlasticityRuntimeReservationV1, PlasticityRuntimeCallErrorV1> {
        validate_budget_limits(budget)?;
        let encoded_bytes = Arc::clone(&self.encoded_bytes)
            .try_acquire_many_owned(budget.encoded_bytes)
            .map_err(|_| PlasticityRuntimeCallErrorV1::Overloaded("aggregate encoded bytes"))?;
        let work_units = match Arc::clone(&self.work_units)
            .try_acquire_many_owned(budget.estimated_work_units)
        {
            Ok(permit) => permit,
            Err(_) => {
                drop(encoded_bytes);
                return Err(PlasticityRuntimeCallErrorV1::Overloaded(
                    "aggregate work units",
                ));
            }
        };
        Ok(PlasticityRuntimeReservationV1 {
            _encoded_bytes: encoded_bytes,
            _work_units: work_units,
        })
    }
}

struct PlasticityStaticValidationCacheV1 {
    entries: VecDeque<Digest32>,
}

impl PlasticityStaticValidationCacheV1 {
    fn new() -> Self {
        Self {
            entries: VecDeque::with_capacity(MAX_PLASTICITY_STATIC_CACHE_ENTRIES),
        }
    }

    fn contains(&mut self, key: Digest32) -> bool {
        let Some(position) = self.entries.iter().position(|candidate| *candidate == key) else {
            return false;
        };
        let Some(entry) = self.entries.remove(position) else {
            return false;
        };
        self.entries.push_back(entry);
        true
    }

    fn insert(&mut self, key: Digest32) {
        if let Some(position) = self.entries.iter().position(|candidate| *candidate == key) {
            let _ = self.entries.remove(position);
        }
        if self.entries.len() == MAX_PLASTICITY_STATIC_CACHE_ENTRIES {
            let _ = self.entries.pop_front();
        }
        self.entries.push_back(key);
    }
}

struct ParameterRuntimeCommandV1 {
    request: Box<ParameterPlasticityProductRequestV1>,
    context: PlasticityRuntimeRequestContextV1,
    required_budget: PlasticityRuntimeBudgetV1,
    submitted_at: Instant,
    queued_at: Instant,
    static_validation_micros: u64,
    quota_admission_micros: u64,
    static_validation_cache_hit: bool,
    reservation: PlasticityRuntimeReservationV1,
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
    required_budget: PlasticityRuntimeBudgetV1,
    submitted_at: Instant,
    queued_at: Instant,
    static_validation_micros: u64,
    quota_admission_micros: u64,
    static_validation_cache_hit: bool,
    reservation: PlasticityRuntimeReservationV1,
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
    admission: Arc<PlasticityRuntimeAdmissionV1>,
    static_validation_cache: Arc<Mutex<PlasticityStaticValidationCacheV1>>,
}

impl PlasticityRuntimeHandleV1 {
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        evidence_time_unix_seconds: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let submitted_at = Instant::now();
        let prepared = self.prepare_parameter(&request)?;
        let context = default_context(evidence_time_unix_seconds, prepared.budget)?;
        self.propose_parameter_prepared(request, context, prepared, submitted_at)
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
        let submitted_at = Instant::now();
        let prepared = self.prepare_parameter(&request)?;
        self.propose_parameter_prepared(request, context, prepared, submitted_at)
            .await
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        evidence_time_unix_seconds: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let submitted_at = Instant::now();
        let prepared = self.prepare_topology(&request)?;
        let context = default_context(evidence_time_unix_seconds, prepared.budget)?;
        self.propose_topology_prepared(request, context, prepared, submitted_at)
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
        let submitted_at = Instant::now();
        let prepared = self.prepare_topology(&request)?;
        self.propose_topology_prepared(request, context, prepared, submitted_at)
            .await
    }

    fn prepare_parameter(
        &self,
        request: &ParameterPlasticityProductRequestV1,
    ) -> Result<PreparedPlasticityRequestV1, PlasticityRuntimeCallErrorV1> {
        let started = Instant::now();
        let budget = parameter_budget(request)?;
        let key = parameter_static_validation_key(request)?;
        let cache_hit = lock_static_cache(&self.static_validation_cache).contains(key);
        if !cache_hit {
            verify_generated_parameter_candidates_v3(
                request.generator_profile.clone(),
                &request.generated,
            )
            .map_err(|_| PlasticityRuntimeCallErrorV1::Invalid("parameter static validation"))?;
            lock_static_cache(&self.static_validation_cache).insert(key);
        }
        Ok(PreparedPlasticityRequestV1 {
            budget,
            static_validation_micros: duration_micros(started.elapsed()),
            cache_hit,
        })
    }

    fn prepare_topology(
        &self,
        request: &TopologyPlasticityProductRequestV1,
    ) -> Result<PreparedPlasticityRequestV1, PlasticityRuntimeCallErrorV1> {
        let started = Instant::now();
        let budget = topology_budget(request)?;
        let key = topology_static_validation_key(request)?;
        let cache_hit = lock_static_cache(&self.static_validation_cache).contains(key);
        if !cache_hit {
            topology_generation_signing_payload_v1(request)
                .map_err(|_| PlasticityRuntimeCallErrorV1::Invalid("topology static validation"))?;
            lock_static_cache(&self.static_validation_cache).insert(key);
        }
        Ok(PreparedPlasticityRequestV1 {
            budget,
            static_validation_micros: duration_micros(started.elapsed()),
            cache_hit,
        })
    }

    async fn propose_parameter_prepared(
        &self,
        request: ParameterPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
        prepared: PreparedPlasticityRequestV1,
        submitted_at: Instant,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<ParameterPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        validate_context(&context, prepared.budget)?;
        let quota_started = Instant::now();
        let reservation = self.admission.reserve(prepared.budget)?;
        let quota_admission_micros = duration_micros(quota_started.elapsed());
        let (response, receive) = oneshot::channel();
        let cancellation = context.cancellation.clone();
        let deadline = context.deadline_unix_seconds;
        let command = ParameterRuntimeCommandV1 {
            request: Box::new(request),
            context,
            required_budget: prepared.budget,
            submitted_at,
            queued_at: Instant::now(),
            static_validation_micros: prepared.static_validation_micros,
            quota_admission_micros,
            static_validation_cache_hit: prepared.cache_hit,
            reservation,
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

    async fn propose_topology_prepared(
        &self,
        request: TopologyPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
        prepared: PreparedPlasticityRequestV1,
        submitted_at: Instant,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<TopologyPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        validate_context(&context, prepared.budget)?;
        let quota_started = Instant::now();
        let reservation = self.admission.reserve(prepared.budget)?;
        let quota_admission_micros = duration_micros(quota_started.elapsed());
        let (response, receive) = oneshot::channel();
        let cancellation = context.cancellation.clone();
        let deadline = context.deadline_unix_seconds;
        let command = TopologyRuntimeCommandV1 {
            request: Box::new(request),
            context,
            required_budget: prepared.budget,
            submitted_at,
            queued_at: Instant::now(),
            static_validation_micros: prepared.static_validation_micros,
            quota_admission_micros,
            static_validation_cache_hit: prepared.cache_hit,
            reservation,
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
    let admission = Arc::new(PlasticityRuntimeAdmissionV1::new());
    let static_validation_cache = Arc::new(Mutex::new(PlasticityStaticValidationCacheV1::new()));
    Ok((
        PlasticityRuntimeHandleV1 {
            parameter_sender,
            topology_sender,
            admission,
            static_validation_cache,
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
                if !cancellation.is_cancelled() {
                    cancellation.cancelled().await;
                }
                self.reject_queued_requests();
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
            // Shutdown must make progress even while producers keep both queues
            // nonempty. Once a command begins durable work, shutdown waits for
            // that command and reconciliation rather than pretending it was undone.
            if cancellation.is_cancelled() {
                return None;
            }
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

    fn reject_queued_requests(&mut self) {
        self.parameter_receiver.close();
        self.topology_receiver.close();
        while let Ok(command) = self.parameter_receiver.try_recv() {
            let _ = command
                .response
                .send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
        }
        while let Ok(command) = self.topology_receiver.try_recv() {
            let _ = command
                .response
                .send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
        }
    }

    async fn process_parameter(
        &mut self,
        state: &Arc<AgentdState>,
        command: ParameterRuntimeCommandV1,
    ) -> Result<(), AgentdError> {
        let ParameterRuntimeCommandV1 {
            request,
            context,
            required_budget,
            submitted_at,
            queued_at,
            static_validation_micros,
            quota_admission_micros,
            static_validation_cache_hit,
            reservation: _reservation,
            response,
        } = command;
        if response.is_closed() || context.cancellation.is_cancelled() {
            return Ok(());
        }
        if let Err(error) = validate_context(&context, required_budget) {
            let _ = response.send(Err(error));
            return Ok(());
        }
        if !state.plasticity_admission_ready()? {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return Ok(());
        }

        let engine = self.engine.take().ok_or_else(|| {
            AgentdError::Protocol("plasticity runtime engine missing".to_string())
        })?;
        let execution_started = Instant::now();
        let evidence_time = context.evidence_time_unix_seconds;
        let state_at_use = Arc::clone(state);
        let worker = tokio::task::spawn_blocking(move || {
            let mut engine = engine;
            let result = match state_at_use.plasticity_admission_ready() {
                Ok(true) => propose_agentd_plasticity_v1(
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
                .map_err(PlasticityRuntimeCallErrorV1::Parameter),
                Ok(false) | Err(_) => Err(PlasticityRuntimeCallErrorV1::Unavailable),
            };
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
            submitted_at,
            queued_at,
            execution_started,
            blocking_execution,
            static_validation_micros,
            quota_admission_micros,
            required_budget,
            static_validation_cache_hit,
        );
        let _ = response.send(result.map(|receipt| PlasticityRuntimeOutcomeV1 { receipt, timing }));
        Ok(())
    }

    async fn process_topology(
        &mut self,
        state: &Arc<AgentdState>,
        command: TopologyRuntimeCommandV1,
    ) -> Result<(), AgentdError> {
        let TopologyRuntimeCommandV1 {
            request,
            context,
            required_budget,
            submitted_at,
            queued_at,
            static_validation_micros,
            quota_admission_micros,
            static_validation_cache_hit,
            reservation: _reservation,
            response,
        } = command;
        if response.is_closed() || context.cancellation.is_cancelled() {
            return Ok(());
        }
        if let Err(error) = validate_context(&context, required_budget) {
            let _ = response.send(Err(error));
            return Ok(());
        }
        if !state.plasticity_admission_ready()? {
            let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
            return Ok(());
        }

        let engine = self.engine.take().ok_or_else(|| {
            AgentdError::Protocol("plasticity runtime engine missing".to_string())
        })?;
        let execution_started = Instant::now();
        let evidence_time = context.evidence_time_unix_seconds;
        let state_at_use = Arc::clone(state);
        let worker = tokio::task::spawn_blocking(move || {
            let mut engine = engine;
            let result = match state_at_use.plasticity_admission_ready() {
                Ok(true) => propose_agentd_topology_plasticity_v1(
                    *request,
                    &engine.artifacts,
                    &engine.ledger,
                    &engine.verifier,
                    &mut engine.topology_writer,
                    &mut engine.topology_anchor_store,
                    evidence_time,
                )
                .map_err(PlasticityRuntimeCallErrorV1::Topology),
                Ok(false) | Err(_) => Err(PlasticityRuntimeCallErrorV1::Unavailable),
            };
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
            submitted_at,
            queued_at,
            execution_started,
            blocking_execution,
            static_validation_micros,
            quota_admission_micros,
            required_budget,
            static_validation_cache_hit,
        );
        let _ = response.send(result.map(|receipt| PlasticityRuntimeOutcomeV1 { receipt, timing }));
        Ok(())
    }
}

pub fn recommended_parameter_budget_v1(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let budget = parameter_budget(request)?;
    verify_generated_parameter_candidates_v3(request.generator_profile.clone(), &request.generated)
        .map_err(|_| PlasticityRuntimeCallErrorV1::Invalid("parameter static validation"))?;
    Ok(budget)
}

pub fn recommended_topology_budget_v1(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let budget = topology_budget(request)?;
    topology_generation_signing_payload_v1(request)
        .map_err(|_| PlasticityRuntimeCallErrorV1::Invalid("topology static validation"))?;
    Ok(budget)
}

fn parameter_budget(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let signals = request.generator_profile.signals.len();
    let scales = request.generator_profile.update_scales.len().max(1);
    let signal_evaluations = checked_product(signals, scales, "signal work arithmetic")?;
    let deltas = request
        .generated
        .candidates
        .iter()
        .try_fold(0_usize, |sum, candidate| {
            sum.checked_add(candidate.parameter_deltas.len())
        })
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded(
            "delta arithmetic",
        ))?;
    let evaluation_work = request
        .evaluations
        .iter()
        .try_fold(0_usize, |sum, evaluation| {
            let bundle = &evaluation.bundle;
            let variable = bundle
                .metrics
                .len()
                .checked_add(evaluation.metric_roles.len())
                .and_then(|value| value.checked_add(bundle.snapshot_ids.len()))
                .and_then(|value| value.checked_add(bundle.future_window_ids.len()))
                .and_then(|value| value.checked_add(bundle.retention_receipt_digests.len()))
                .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded(
                    "evaluation work arithmetic",
                ))?;
            let this_evaluation = 64_usize.checked_add(variable).ok_or(
                PlasticityRuntimeCallErrorV1::BudgetExceeded("evaluation work arithmetic"),
            )?;
            sum.checked_add(this_evaluation)
                .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded(
                    "evaluation work arithmetic",
                ))
        })?;
    let work = signal_evaluations
        .checked_add(deltas)
        .and_then(|value| value.checked_add(evaluation_work))
        .and_then(|value| value.checked_add(request.generator_profile.mutation_policy.rules.len()))
        .and_then(|value| value.checked_add(request.generated.candidates.len()))
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded(
            "work arithmetic",
        ))?;
    budget_from_usize(parameter_retained_bytes(request)?, work.max(1))
}

fn topology_budget(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<PlasticityRuntimeBudgetV1, PlasticityRuntimeCallErrorV1> {
    let changes = request.changes.len();
    let handoffs = request.handoffs.len();
    let work = checked_product(changes, 64, "topology change work arithmetic")?
        .checked_add(checked_product(
            handoffs,
            32,
            "topology handoff work arithmetic",
        )?)
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded(
            "topology work arithmetic",
        ))?
        .max(1);
    budget_from_usize(topology_retained_bytes(request)?, work)
}

#[derive(Default)]
struct RetainedSizeV1 {
    bytes: usize,
}

impl RetainedSizeV1 {
    fn add(&mut self, bytes: usize) -> Result<(), PlasticityRuntimeCallErrorV1> {
        self.bytes =
            self.bytes
                .checked_add(bytes)
                .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded(
                    "byte arithmetic",
                ))?;
        Ok(())
    }

    fn vector<T>(&mut self, values: &Vec<T>) -> Result<(), PlasticityRuntimeCallErrorV1> {
        self.add(values.capacity().checked_mul(size_of::<T>()).ok_or(
            PlasticityRuntimeCallErrorV1::BudgetExceeded("vector capacity arithmetic"),
        )?)
    }

    fn id(&mut self, _value: &StableId) -> Result<(), PlasticityRuntimeCallErrorV1> {
        self.add(MAX_STABLE_ID_HEAP_BYTES)
    }

    fn attestation(
        &mut self,
        value: &SignedLearningEvidenceV1,
    ) -> Result<(), PlasticityRuntimeCallErrorV1> {
        self.id(&value.evidence_id)?;
        self.id(&value.principal_id)
    }
}

fn parameter_retained_bytes(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<usize, PlasticityRuntimeCallErrorV1> {
    let mut size = RetainedSizeV1::default();
    size.add(size_of_val(request))?;
    size.add(REQUEST_FOOTPRINT_FIXED_OVERHEAD)?;
    size.id(&request.proposal_id)?;

    let profile = &request.generator_profile;
    size.id(&profile.window.window_id)?;
    size.vector(&profile.norm_layers)?;
    for layer in &profile.norm_layers {
        size.id(&layer.layer_id)?;
    }
    size.id(&profile.mutation_policy.policy_id)?;
    size.id(&profile.mutation_policy.window.window_id)?;
    size.vector(&profile.mutation_policy.rules)?;
    for rule in &profile.mutation_policy.rules {
        size.id(&rule.parameter_id)?;
        size.id(&rule.layer_id)?;
    }
    size.vector(&profile.update_scales)?;
    size.vector(&profile.signals)?;
    for signal in &profile.signals {
        size.id(&signal.layer_id)?;
        size.id(&signal.parameter_id)?;
    }

    let generated = &request.generated;
    size.id(&generated.window.window_id)?;
    size.vector(&generated.norm_layers)?;
    for layer in &generated.norm_layers {
        size.id(&layer.layer_id)?;
    }
    size.vector(&generated.candidates)?;
    for candidate in &generated.candidates {
        size.id(&candidate.candidate_id)?;
        size.vector(&candidate.parameter_deltas)?;
        for delta in &candidate.parameter_deltas {
            size.id(&delta.layer_id)?;
            size.id(&delta.parameter_id)?;
        }
    }

    size.attestation(&request.generator_attestation)?;
    size.id(&request.admission.baseline_id)?;
    size.id(&request.admission.window.window_id)?;
    size.attestation(&request.admission_attestation)?;
    if let Some(attestation) = &request.no_change_attestation {
        size.attestation(attestation)?;
    }
    size.vector(&request.evaluations)?;
    for evaluation in &request.evaluations {
        let bundle = &evaluation.bundle;
        size.id(&bundle.evaluation_id)?;
        size.id(&bundle.candidate_id)?;
        size.id(&bundle.baseline_id)?;
        size.id(&bundle.generator.principal_id)?;
        size.id(&bundle.evaluator.principal_id)?;
        size.id(&bundle.frozen_plan.plan_id)?;
        size.id(&bundle.frozen_plan.candidate_id)?;
        size.id(&bundle.frozen_plan.baseline_id)?;
        size.id(&bundle.frozen_plan.final_holdout_window_id)?;
        size.id(&bundle.holdout_use.plan_id)?;
        size.id(&bundle.holdout_use.candidate_id)?;
        size.id(&bundle.holdout_use.baseline_id)?;
        size.id(&bundle.holdout_use.final_holdout_window_id)?;
        size.vector(&bundle.retention_receipt_digests)?;
        size.vector(&bundle.snapshot_ids)?;
        for id in &bundle.snapshot_ids {
            size.id(id)?;
        }
        size.vector(&bundle.future_window_ids)?;
        for id in &bundle.future_window_ids {
            size.id(id)?;
        }
        size.vector(&bundle.metrics)?;
        for metric in &bundle.metrics {
            size.id(&metric.metric_id)?;
        }
        size.vector(&evaluation.metric_roles)?;
        for role in &evaluation.metric_roles {
            size.id(&role.metric_id)?;
        }
        size.attestation(&evaluation.evidence.generator_plan)?;
        size.attestation(&evaluation.evidence.evaluator_bundle)?;
    }
    retained_with_scratch(size.bytes)
}

fn topology_retained_bytes(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<usize, PlasticityRuntimeCallErrorV1> {
    let mut size = RetainedSizeV1::default();
    size.add(size_of_val(request))?;
    size.add(REQUEST_FOOTPRINT_FIXED_OVERHEAD)?;
    size.id(&request.proposal_id)?;
    size.id(&request.proposer_generation_id)?;
    size.id(&request.window.window_id)?;
    size.vector(&request.changes)?;
    for change in &request.changes {
        size.id(&change.module_id)?;
    }
    size.vector(&request.handoffs)?;
    for handoff in &request.handoffs {
        size.id(&handoff.module_id)?;
        size.id(&handoff.from_owner)?;
        size.id(&handoff.to_owner)?;
    }
    size.id(&request.admission.baseline_id)?;
    size.id(&request.admission.window.window_id)?;
    size.attestation(&request.generator_attestation)?;
    size.attestation(&request.observer_attestation)?;
    size.attestation(&request.evaluator_attestation)?;
    retained_with_scratch(size.bytes)
}

fn retained_with_scratch(bytes: usize) -> Result<usize, PlasticityRuntimeCallErrorV1> {
    bytes.checked_mul(REQUEST_RETAINED_COPY_FACTOR).ok_or(
        PlasticityRuntimeCallErrorV1::BudgetExceeded("retained copy arithmetic"),
    )
}

fn parameter_static_validation_key(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<Digest32, PlasticityRuntimeCallErrorV1> {
    let profile = &request.generator_profile;
    let generated = &request.generated;
    let mut bytes = b"hepta.agentd.plasticity-parameter-static-cache.v1\0".to_vec();
    bytes.extend_from_slice(profile.selected_artifact_digest.as_array());
    push_key_id(&mut bytes, &profile.window.window_id)?;
    bytes.extend_from_slice(profile.window.window_digest.as_array());
    push_key_len(&mut bytes, profile.norm_layers.len())?;
    for layer in &profile.norm_layers {
        push_key_id(&mut bytes, &layer.layer_id)?;
        bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    push_key_id(&mut bytes, &profile.mutation_policy.policy_id)?;
    bytes.extend_from_slice(profile.mutation_policy.mutation_grammar_digest.as_array());
    bytes.extend_from_slice(profile.mutation_policy.selected_artifact_digest.as_array());
    push_key_id(&mut bytes, &profile.mutation_policy.window.window_id)?;
    bytes.extend_from_slice(profile.mutation_policy.window.window_digest.as_array());
    push_key_len(&mut bytes, profile.mutation_policy.rules.len())?;
    for rule in &profile.mutation_policy.rules {
        push_key_id(&mut bytes, &rule.parameter_id)?;
        push_key_id(&mut bytes, &rule.layer_id)?;
        bytes.push(match rule.surface {
            ParameterMutationSurfaceV1::LearnableParameter => 0,
            ParameterMutationSurfaceV1::Authority => 1,
            ParameterMutationSurfaceV1::Evaluator => 2,
            ParameterMutationSurfaceV1::Deletion => 3,
            ParameterMutationSurfaceV1::RuntimeTopology => 4,
            ParameterMutationSurfaceV1::Credential => 5,
        });
        bytes.extend_from_slice(&rule.minimum_delta.raw().to_be_bytes());
        bytes.extend_from_slice(&rule.maximum_delta.raw().to_be_bytes());
    }
    bytes.extend_from_slice(profile.mutation_policy.policy_digest.as_array());
    push_key_len(&mut bytes, profile.update_scales.len())?;
    for scale in &profile.update_scales {
        bytes.extend_from_slice(&scale.raw().to_be_bytes());
    }
    push_key_len(&mut bytes, profile.signals.len())?;
    for signal in &profile.signals {
        push_key_id(&mut bytes, &signal.layer_id)?;
        push_key_id(&mut bytes, &signal.parameter_id)?;
        for value in [
            signal.eligibility,
            signal.modulator,
            signal.learning_rate,
            signal.lower_bound,
            signal.upper_bound,
        ] {
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        bytes.extend_from_slice(signal.evidence_digest.as_array());
    }

    bytes.extend_from_slice(generated.selected_artifact_digest.as_array());
    push_key_id(&mut bytes, &generated.window.window_id)?;
    bytes.extend_from_slice(generated.window.window_digest.as_array());
    push_key_len(&mut bytes, generated.norm_layers.len())?;
    for layer in &generated.norm_layers {
        push_key_id(&mut bytes, &layer.layer_id)?;
        bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    push_key_len(&mut bytes, generated.candidates.len())?;
    for candidate in &generated.candidates {
        push_key_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(match candidate.kind {
            ParameterCandidateKindV2::NoChange => 0,
            ParameterCandidateKindV2::Update => 1,
        });
        push_key_len(&mut bytes, candidate.parameter_deltas.len())?;
        for delta in &candidate.parameter_deltas {
            push_key_id(&mut bytes, &delta.layer_id)?;
            push_key_id(&mut bytes, &delta.parameter_id)?;
            bytes.extend_from_slice(&delta.delta.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.lower_bound.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.upper_bound.raw().to_be_bytes());
            bytes.extend_from_slice(delta.evidence_digest.as_array());
        }
    }
    bytes.extend_from_slice(generated.generator_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn topology_static_validation_key(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<Digest32, PlasticityRuntimeCallErrorV1> {
    let mut bytes = b"hepta.agentd.plasticity-topology-static-cache.v1\0".to_vec();
    push_key_id(&mut bytes, &request.proposal_id)?;
    push_key_id(&mut bytes, &request.proposer_generation_id)?;
    bytes.extend_from_slice(request.selected_artifact_digest.as_array());
    push_key_id(&mut bytes, &request.window.window_id)?;
    bytes.extend_from_slice(request.window.window_digest.as_array());
    bytes.extend_from_slice(&request.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(request.rollback_predecessor_digest.as_array());
    push_key_len(&mut bytes, request.changes.len())?;
    for change in &request.changes {
        push_key_id(&mut bytes, &change.module_id)?;
        bytes.push(match change.operation {
            TopologyOperationV2::Add => 0,
            TopologyOperationV2::Remove => 1,
            TopologyOperationV2::Replace => 2,
            TopologyOperationV2::Split => 3,
            TopologyOperationV2::Merge => 4,
            TopologyOperationV2::Rewire => 5,
            TopologyOperationV2::Retire => 6,
        });
        push_optional_key_digest(&mut bytes, change.predecessor_digest);
        push_optional_key_digest(&mut bytes, change.candidate_digest);
        for digest in [
            change.capability_typing_digest,
            change.compatibility_plan_digest,
            change.lesion_ablation_digest,
            change.resource_review_digest,
            change.security_review_digest,
            change.migration_digest,
            change.rollback_digest,
            change.writer_handoff_digest,
            change.evidence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
    }
    push_key_len(&mut bytes, request.handoffs.len())?;
    for handoff in &request.handoffs {
        push_key_id(&mut bytes, &handoff.module_id)?;
        push_key_id(&mut bytes, &handoff.from_owner)?;
        push_key_id(&mut bytes, &handoff.to_owner)?;
        bytes.extend_from_slice(&handoff.predecessor_writer_fence.to_be_bytes());
        bytes.extend_from_slice(&handoff.successor_writer_fence.to_be_bytes());
        for digest in [
            handoff.source_store_digest,
            handoff.migration_digest,
            handoff.rollback_digest,
            handoff.acknowledgement_contract_digest,
            handoff.plan_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_optional_key_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_key_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), PlasticityRuntimeCallErrorV1> {
    push_key_len(bytes, value.as_str().len())?;
    bytes.extend_from_slice(value.as_str().as_bytes());
    Ok(())
}

fn push_key_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), PlasticityRuntimeCallErrorV1> {
    let value = u32::try_from(value)
        .map_err(|_| PlasticityRuntimeCallErrorV1::BudgetExceeded("key length"))?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn checked_product(
    left: usize,
    right: usize,
    label: &'static str,
) -> Result<usize, PlasticityRuntimeCallErrorV1> {
    left.checked_mul(right)
        .ok_or(PlasticityRuntimeCallErrorV1::BudgetExceeded(label))
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
    if budget.encoded_bytes == 0 || budget.encoded_bytes > MAX_PLASTICITY_RUNTIME_ENCODED_BYTES {
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

#[allow(clippy::too_many_arguments)]
fn timing(
    submitted_at: Instant,
    queued_at: Instant,
    execution_started: Instant,
    blocking_execution: Duration,
    static_validation_micros: u64,
    quota_admission_micros: u64,
    budget: PlasticityRuntimeBudgetV1,
    static_validation_cache_hit: bool,
) -> PlasticityRuntimeTimingV1 {
    PlasticityRuntimeTimingV1 {
        static_validation_micros,
        quota_admission_micros,
        queue_wait_micros: duration_micros(execution_started.saturating_duration_since(queued_at)),
        blocking_execution_micros: duration_micros(blocking_execution),
        total_micros: duration_micros(submitted_at.elapsed()),
        encoded_bytes: budget.encoded_bytes,
        estimated_work_units: budget.estimated_work_units,
        static_validation_cache_hit,
    }
}

fn lock_static_cache(
    cache: &Mutex<PlasticityStaticValidationCacheV1>,
) -> std::sync::MutexGuard<'_, PlasticityStaticValidationCacheV1> {
    // This cache holds no authority decision and is safe to rebuild after a panic.
    cache
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
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
    fn plasticity_runtime_queue_capacity_is_bounded() {
        assert!(validate_plasticity_runtime_capacity(1).is_ok());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE).is_ok());
        assert!(validate_plasticity_runtime_capacity(0).is_err());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE + 1).is_err());
    }

    #[test]
    fn plasticity_runtime_context_rejects_expired_cancelled_and_unbounded_work() {
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
            PlasticityRuntimeRequestContextV1::new(1, unix_now(), valid, CancellationToken::new(),),
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
            Err(PlasticityRuntimeCallErrorV1::BudgetExceeded(
                "encoded bytes"
            ))
        ));
    }

    #[test]
    fn plasticity_aggregate_quota_spans_parameter_and_topology_work() {
        let admission = PlasticityRuntimeAdmissionV1::new();
        let maximum = PlasticityRuntimeBudgetV1 {
            encoded_bytes: MAX_PLASTICITY_RUNTIME_ENCODED_BYTES,
            estimated_work_units: MAX_PLASTICITY_RUNTIME_WORK_UNITS,
        };
        let first = admission.reserve(maximum).expect("first reservation");
        let second = admission.reserve(maximum).expect("second reservation");
        let third = admission.reserve(maximum).expect("third reservation");
        let fourth = admission.reserve(maximum).expect("fourth reservation");
        assert!(matches!(
            admission.reserve(maximum),
            Err(PlasticityRuntimeCallErrorV1::Overloaded(
                "aggregate encoded bytes"
            ))
        ));
        drop(first);
        assert!(admission.reserve(maximum).is_ok());
        drop((second, third, fourth));
    }

    #[test]
    fn plasticity_static_cache_is_exact_and_bounded() {
        let mut cache = PlasticityStaticValidationCacheV1::new();
        let first = Digest32::of_bytes(b"first");
        cache.insert(first);
        assert!(cache.contains(first));
        for index in 0..=MAX_PLASTICITY_STATIC_CACHE_ENTRIES {
            cache.insert(Digest32::of_bytes(&index.to_be_bytes()));
        }
        assert!(cache.entries.len() <= MAX_PLASTICITY_STATIC_CACHE_ENTRIES);
        assert!(!cache.contains(first));
    }
}
