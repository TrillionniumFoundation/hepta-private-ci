//! Durable product Decision/Outcome closure for canonical intelligence.
//!
//! The sole destination writer remains learning.ledger::LedgerWriter. Immutable
//! V2 payloads precede operation publication. Recovery observes the exact event
//! first; only an absent event may be applied under fresh authority and the
//! host's CURRENT verification time. Event timestamps and predecessors never
//! change during replay.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::dispatch_final_use;
use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_operations::DispatchEffect;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_operations::DurableOperationIntentV1;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_operations::OperationBacklogMetrics;
use codex_hepta_operations::PrepareDisposition;
use codex_hepta_operations::ReconciliationOutcome;
use codex_hepta_operations::ReconciliationReceiptV1;
use codex_hepta_operations::UnsettledOperationCursorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::RunPhase;
use crate::RunReceipt;

#[path = "intelligence_learning_clock.rs"]
mod clock;
#[path = "intelligence_learning_exact.rs"]
mod exact;
#[path = "intelligence_learning_io.rs"]
mod io;
#[path = "intelligence_learning_payload.rs"]
mod payload;

use payload::LearningPayloadV1;
use payload::PersistedLearningEnvelopeV1;
use payload::apply_decision;
use payload::apply_outcome;
use payload::apply_payload;
use payload::decision_payload;
use payload::observe_applied_payload;
use payload::outcome_payload;

const LEARNING_PAYLOAD_SCHEMA_VERSION: u32 = 2;
const LEARNING_DESTINATION_ID: &str = "learning.ledger";
const MAX_LEARNING_PAYLOAD_BYTES: usize = 1_048_576;
const CLAIM_LEASE: Duration = Duration::from_secs(30);
const GRANT_RETRY_DELAY: Duration = Duration::from_secs(1);
const MAX_RECONCILE_BATCH: u32 = 256;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceLearningDispositionV1 {
    Acknowledged,
    Rejected,
    Revoked,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceLearningReceiptV1 {
    pub operation_id: StableId,
    pub disposition: AgentdIntelligenceLearningDispositionV1,
    pub evidence_digest: Digest32,
    pub append: Option<AppendReceipt>,
}

#[derive(Clone, Debug)]
pub struct AgentdIntelligenceDecisionAppendV1 {
    pub expected_ledger_predecessor: Digest32,
    pub episode_id: StableId,
    pub policy_digest: Digest32,
    /// Proof for sorted policy actions plus the intrinsic `abstain` candidate.
    /// Count and digests must cover at most 127 actions plus abstention, and the
    /// generator evidence must sign that same inclusive learning universe.
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub evidence: SignedLearningEvidenceV1,
    /// Historical event/enqueue time in Unix milliseconds; never replay authority.
    pub now: u64,
}

#[derive(Clone, Debug)]
pub struct AgentdIntelligenceOutcomeAppendV1 {
    pub expected_ledger_predecessor: Digest32,
    pub decision_record_id: StableId,
    pub episode_id: StableId,
    pub run_receipt: RunReceipt,
    pub provider_terminal_digest: Digest32,
    pub outcome: AuthenticatedOutcomeV1,
    pub evidence: SignedLearningEvidenceV1,
    /// Historical event/enqueue time in Unix milliseconds; never replay authority.
    pub now: u64,
}

#[derive(Debug)]
pub enum AgentdIntelligenceLearningErrorV1 {
    Invalid(&'static str),
    InvalidValue(String),
    Io(String),
    Json(String),
    Operation(DurableOperationError),
    Authority(FinalUseError),
    Ledger(ProductionLedgerError),
    Agentd(AgentdError),
    Poisoned,
    IoBusy,
    IoIndeterminate,
}

impl AgentdIntelligenceLearningErrorV1 {
    /// Transient transport/storage/authority failures retain the same durable
    /// operation. Corruption and writer poisoning require supervised recovery.
    pub(crate) fn is_transient(&self) -> bool {
        match self {
            Self::Io(_) | Self::IoBusy | Self::IoIndeterminate => true,
            Self::Agentd(AgentdError::GenerationFenced(_) | AgentdError::Invalid(_)) => false,
            Self::Agentd(
                AgentdError::Protocol(_) | AgentdError::Overloaded { .. } | AgentdError::Io(_),
            ) => true,
            Self::Agentd(_) => false,
            Self::Operation(DurableOperationError::Unavailable(_)) => true,
            Self::Authority(error) | Self::Operation(DurableOperationError::Authority(error)) => {
                matches!(
                    error,
                    FinalUseError::Unavailable
                        | FinalUseError::CapacityExceeded
                        | FinalUseError::DispatchInProgress
                        | FinalUseError::StateLocked
                        | FinalUseError::AlreadyClaimed
                )
            }
            _ => false,
        }
    }
}

impl fmt::Display for AgentdIntelligenceLearningErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdIntelligenceLearningErrorV1 {}
impl From<DurableOperationError> for AgentdIntelligenceLearningErrorV1 {
    fn from(value: DurableOperationError) -> Self {
        Self::Operation(value)
    }
}
impl From<ProductionLedgerError> for AgentdIntelligenceLearningErrorV1 {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}
impl From<FinalUseError> for AgentdIntelligenceLearningErrorV1 {
    fn from(value: FinalUseError) -> Self {
        Self::Authority(value)
    }
}
impl From<AgentdError> for AgentdIntelligenceLearningErrorV1 {
    fn from(value: AgentdError) -> Self {
        Self::Agentd(value)
    }
}

pub fn intelligence_physical_terminal_binding_digest_v1(
    prepared: &PreparedAgentdIntelligenceRunV1,
    run_receipt: &RunReceipt,
    provider_terminal_digest: Digest32,
) -> Result<Digest32, AgentdIntelligenceLearningErrorV1> {
    if provider_terminal_digest.is_zero()
        || !run_receipt.terminal_observed
        || !matches!(
            run_receipt.phase,
            RunPhase::Succeeded | RunPhase::Failed | RunPhase::Cancelled
        )
    {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "physical terminal observation",
        ));
    }
    let snapshot = prepared.run_snapshot();
    let attachment = prepared.context_attachment();
    if run_receipt.run_id != snapshot.run_id
        || run_receipt.authority_epoch != snapshot.authority_epoch
        || run_receipt.generation != snapshot.generation
        || run_receipt.fence_digest != snapshot.fence_digest
        || run_receipt.deadline_ms != snapshot.deadline_ms
        || run_receipt.context_digest.as_deref() != Some(attachment.context_digest.as_str())
        || run_receipt.compilation_receipt_digest.as_deref()
            != Some(attachment.compilation_receipt_digest.as_str())
    {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "terminal run/context identity",
        ));
    }
    let (candidate_id, propensity) = selected_decision(prepared)?;
    let mut bytes = b"hepta.agentd.intelligence-physical-terminal.v1\0".to_vec();
    push_string(&mut bytes, &snapshot.run_id)?;
    bytes.extend_from_slice(&run_receipt.revision.to_be_bytes());
    bytes.push(run_phase_tag(run_receipt.phase));
    push_string(&mut bytes, &snapshot.request_digest)?;
    push_string(&mut bytes, &snapshot.objective_digest)?;
    push_string(&mut bytes, &snapshot.body_digest)?;
    push_string(&mut bytes, &snapshot.artifact_set_digest)?;
    bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
    push_string(&mut bytes, &snapshot.fence_digest)?;
    bytes.extend_from_slice(&snapshot.deadline_ms.to_be_bytes());
    push_string(&mut bytes, &attachment.context_digest)?;
    bytes.extend_from_slice(prepared.envelope.envelope_digest.as_array());
    bytes.extend_from_slice(prepared.envelope.decision.decision_digest.as_array());
    push_id(&mut bytes, candidate_id)?;
    bytes.extend_from_slice(&propensity.raw().to_be_bytes());
    bytes.extend_from_slice(provider_terminal_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn intelligence_run_snapshot_digest_v1(
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<Digest32, AgentdIntelligenceLearningErrorV1> {
    require_prepared_integrity(prepared)?;
    let snapshot = prepared.run_snapshot();
    let attachment = prepared.context_attachment();
    let mut bytes = b"hepta.agentd.intelligence-learning-snapshot.v1\0".to_vec();
    for value in [
        &snapshot.run_id,
        &snapshot.request_digest,
        &snapshot.objective_digest,
        &snapshot.body_digest,
        &snapshot.artifact_set_digest,
        &snapshot.fence_digest,
        &attachment.context_digest,
        &attachment.compilation_receipt_digest,
    ] {
        push_string(&mut bytes, value)?;
    }
    bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
    bytes.extend_from_slice(&snapshot.deadline_ms.to_be_bytes());
    bytes.extend_from_slice(prepared.canonical_snapshot().digest().as_array());
    bytes.extend_from_slice(prepared.envelope.envelope_digest.as_array());
    bytes.extend_from_slice(prepared.envelope.decision.decision_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

/// Low-level owner adapter; a product caller uses the durable host below.
pub fn append_intelligence_decision_v1(
    writer: &mut LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceDecisionAppendV1,
) -> Result<AppendReceipt, AgentdIntelligenceLearningErrorV1> {
    let payload = decision_payload(writer, prepared, request)?;
    apply_decision(writer, &payload).map_err(Into::into)
}

pub fn append_intelligence_outcome_v1(
    writer: &mut LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceOutcomeAppendV1,
) -> Result<AppendReceipt, AgentdIntelligenceLearningErrorV1> {
    let payload = outcome_payload(writer, prepared, request)?;
    apply_outcome(writer, &payload).map_err(Into::into)
}

pub struct AgentdIntelligenceLearningHostV1 {
    operations: DurableOperationStore,
    payload_root: PathBuf,
    destination: StableId,
    worker_id: StableId,
    generation: Generation,
    authority: FinalUseAuthority,
    grants: Arc<dyn AgentdFinalUseGrantProvider>,
    writer: Arc<Mutex<LedgerWriter>>,
    io_slots: Arc<tokio::sync::Semaphore>,
    reconciliation_gate: tokio::sync::Semaphore,
    reconciliation_cursor: Mutex<Option<UnsettledOperationCursorV1>>,
}

impl AgentdIntelligenceLearningHostV1 {
    pub async fn open(
        root: &Path,
        writer: LedgerWriter,
        authority: FinalUseAuthority,
        grants: Arc<dyn AgentdFinalUseGrantProvider>,
        worker_id: StableId,
        generation: Generation,
    ) -> Result<Self, AgentdIntelligenceLearningErrorV1> {
        if !root.is_absolute() {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "learning outbox root must be absolute",
            ));
        }
        ensure_private_directory(root)?;
        let payload_root = root.join("payloads");
        ensure_private_directory(&payload_root)?;
        let operations = DurableOperationStore::open(&root.join("operations.sqlite")).await?;
        Ok(Self {
            operations,
            payload_root,
            destination: parse_id(LEARNING_DESTINATION_ID)?,
            worker_id,
            generation,
            authority,
            grants,
            writer: Arc::new(Mutex::new(writer)),
            io_slots: Arc::new(tokio::sync::Semaphore::new(4)),
            reconciliation_gate: tokio::sync::Semaphore::new(1),
            reconciliation_cursor: Mutex::new(None),
        })
    }

    pub async fn enqueue_decision(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: AgentdIntelligenceDecisionAppendV1,
    ) -> Result<PrepareDisposition, AgentdIntelligenceLearningErrorV1> {
        let frozen = prepared.clone();
        let writer = Arc::clone(&self.writer);
        let payload = self
            .run_io(move || {
                let writer = writer
                    .lock()
                    .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                Ok(LearningPayloadV1::Decision(decision_payload(
                    &writer, &frozen, request,
                )?))
            })
            .await?;
        self.enqueue(prepared, payload, None).await
    }

    pub async fn enqueue_outcome(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: AgentdIntelligenceOutcomeAppendV1,
    ) -> Result<PrepareDisposition, AgentdIntelligenceLearningErrorV1> {
        let frozen = prepared.clone();
        let writer = Arc::clone(&self.writer);
        let payload = self
            .run_io(move || {
                let writer = writer
                    .lock()
                    .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                Ok(LearningPayloadV1::Outcome(outcome_payload(
                    &writer, &frozen, request,
                )?))
            })
            .await?;
        let predecessor = decision_operation_id(
            &payload.run_id()?,
            payload.episode_id(),
            payload.run_snapshot_digest()?,
            prepared.envelope.decision.decision_digest,
        )?;
        self.enqueue(prepared, payload, Some(predecessor)).await
    }

    async fn enqueue(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        payload: LearningPayloadV1,
        expected_predecessor: Option<StableId>,
    ) -> Result<PrepareDisposition, AgentdIntelligenceLearningErrorV1> {
        if prepared.run_snapshot().generation != self.generation.get() {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "learning outbox generation",
            ));
        }
        let envelope = PersistedLearningEnvelopeV1 {
            schema_version: LEARNING_PAYLOAD_SCHEMA_VERSION,
            owner_generation: self.generation.get(),
            payload,
        };
        let encoded = serde_json::to_vec(&envelope)
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Json(error.to_string()))?;
        if encoded.is_empty() || encoded.len() > MAX_LEARNING_PAYLOAD_BYTES {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "learning payload size",
            ));
        }
        let payload_digest = Digest32::of_bytes(&encoded);
        let root = self.payload_root.clone();
        self.run_io(move || persist_payload(&root, payload_digest, &encoded))
            .await?;
        let prepared = self
            .operations
            .prepare_intent(&DurableOperationIntentV1 {
                scope_id: envelope.payload.run_id()?,
                operation_id: envelope.payload.operation_id()?,
                expected_predecessor,
                destination: self.destination.clone(),
                payload_digest,
                owner_generation: self.generation,
            })
            .await?;
        Ok(prepared.disposition)
    }

    pub async fn dispatch_next(
        &self,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        let Some(claim) = self
            .operations
            .claim_next(
                &self.destination,
                &self.worker_id,
                self.generation,
                CLAIM_LEASE,
            )
            .await?
        else {
            return Ok(None);
        };
        let payload = self.load_payload(claim.intent.payload_digest).await?;
        validate_claim_payload(&claim.intent, &payload)?;
        let grants = Arc::clone(&self.grants);
        let binding = claim.intent.final_use_binding();
        let signed = match self
            .run_io(move || grants.signed_grant(&binding).map_err(Into::into))
            .await
        {
            Ok(value) => value,
            Err(error) => {
                // The authority provider failed before dispatch admission. The
                // operations owner verifies Prepared + exact lease atomically;
                // a stale/post-dispatch claim can never be requeued here.
                self.operations
                    .defer_pre_dispatch_claim_v1(&claim, GRANT_RETRY_DELAY)
                    .await?;
                return Err(error);
            }
        };
        let authorized = self
            .operations
            .authorize_dispatch(&self.authority, &signed, &claim)
            .await?;
        let observation = self.execute_ledger_operation(authorized, payload).await?;
        Ok(Some(
            self.settle_observation(
                &claim.intent.scope_id,
                &claim.intent.operation_id,
                observation,
            )
            .await?,
        ))
    }

    pub async fn reconcile_unsettled(
        &self,
        limit: u32,
    ) -> Result<Vec<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1> {
        if limit == 0 || limit > MAX_RECONCILE_BATCH {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "reconciliation limit",
            ));
        }
        // Serialize page ownership, not the daemon's run coordinator. Resetting
        // this scheduling cursor after a process restart cannot authorize work.
        let _page_ownership = self.reconciliation_gate.acquire().await.map_err(|_| {
            AgentdIntelligenceLearningErrorV1::Invalid("reconciliation owner closed")
        })?;
        let cursor = self
            .reconciliation_cursor
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .clone();
        let page = self
            .operations
            .unsettled_operation_page_v1(&self.destination, cursor.as_ref(), limit)
            .await?;
        *self
            .reconciliation_cursor
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)? = page.next_cursor;
        let mut receipts = Vec::with_capacity(page.records.len());
        for record in page.records {
            let record = if record.intent.owner_generation == self.generation {
                record
            } else {
                self.operations
                    .adopt_unsettled_generation(
                        &record.intent.scope_id,
                        &record.intent.operation_id,
                        self.generation,
                    )
                    .await?
            };
            let payload = self.load_payload(record.intent.payload_digest).await?;
            validate_claim_payload(&record.intent, &payload)?;
            let writer = Arc::clone(&self.writer);
            let grants = Arc::clone(&self.grants);
            let authority = self.authority.clone();
            let binding = record.intent.final_use_binding();
            let observation = self
                .run_io(move || {
                    Ok(match writer.lock() {
                        Ok(mut writer) => match observe_applied_payload(&mut writer, &payload) {
                            Ok(Some(receipt)) => ApplyObservation::Acknowledged(receipt),
                            Ok(None) => match grants.signed_grant(&binding) {
                                Err(error) => {
                                    unknown(format!("grant-unavailable:{error}").as_bytes())
                                }
                                Ok(signed) => {
                                    match claim_final_use(&authority, &signed, &binding) {
                                        Ok(token) => match dispatch_final_use(
                                            &authority,
                                            token,
                                            &binding,
                                            || apply_payload(&mut writer, &payload),
                                        ) {
                                            Ok(result) => classify_apply(result),
                                            Err(error) => classify_authority_error(error),
                                        },
                                        Err(error) => classify_authority_error(error),
                                    }
                                }
                            },
                            Err(error) => classify_apply(Err(error)),
                        },
                        Err(_) => unknown(b"writer-poisoned"),
                    })
                })
                .await?;
            receipts.push(
                self.settle_observation(
                    &record.intent.scope_id,
                    &record.intent.operation_id,
                    observation,
                )
                .await?,
            );
        }
        Ok(receipts)
    }

    #[must_use]
    pub const fn owner_generation(&self) -> Generation {
        self.generation
    }

    pub async fn backlog_metrics(
        &self,
    ) -> Result<OperationBacklogMetrics, AgentdIntelligenceLearningErrorV1> {
        self.operations.backlog_metrics().await.map_err(Into::into)
    }

    pub fn writer_trust_generation(&self) -> Result<u64, AgentdIntelligenceLearningErrorV1> {
        Ok(self
            .writer
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .trust_generation())
    }

    async fn load_payload(
        &self,
        payload_digest: Digest32,
    ) -> Result<PersistedLearningEnvelopeV1, AgentdIntelligenceLearningErrorV1> {
        let path = payload_path(&self.payload_root, payload_digest);
        self.run_io(move || {
            let bytes = crate::intelligence_files::read_bounded(&path, MAX_LEARNING_PAYLOAD_BYTES)
                .map_err(io_error)?;
            if Digest32::of_bytes(&bytes) != payload_digest {
                return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                    "learning payload digest",
                ));
            }
            let value: PersistedLearningEnvelopeV1 = serde_json::from_slice(&bytes)
                .map_err(|error| AgentdIntelligenceLearningErrorV1::Json(error.to_string()))?;
            if value.schema_version != LEARNING_PAYLOAD_SCHEMA_VERSION {
                return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                    "learning payload schema",
                ));
            }
            Ok(value)
        })
        .await
    }

    async fn settle_observation(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        observation: ApplyObservation,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        let (disposition, evidence_digest, append, terminal) = match observation {
            ApplyObservation::Acknowledged(receipt) => (
                AgentdIntelligenceLearningDispositionV1::Acknowledged,
                receipt.chain_digest,
                Some(receipt),
                Some(ReconciliationOutcome::Applied),
            ),
            ApplyObservation::Rejected(digest) => (
                AgentdIntelligenceLearningDispositionV1::Rejected,
                digest,
                None,
                Some(ReconciliationOutcome::NotApplied),
            ),
            ApplyObservation::Revoked(digest) => (
                AgentdIntelligenceLearningDispositionV1::Revoked,
                digest,
                None,
                Some(ReconciliationOutcome::Quarantined),
            ),
            ApplyObservation::Indeterminate(digest) => (
                AgentdIntelligenceLearningDispositionV1::Indeterminate,
                digest,
                None,
                None,
            ),
        };
        if let Some(outcome) = terminal {
            self.operations
                .observe_terminal(
                    scope_id,
                    operation_id,
                    &ReconciliationReceiptV1 {
                        outcome,
                        evidence_digest,
                        observer_id: self.worker_id.clone(),
                        observer_generation: self.generation,
                    },
                )
                .await?;
        }
        Ok(AgentdIntelligenceLearningReceiptV1 {
            operation_id: operation_id.clone(),
            disposition,
            evidence_digest,
            append,
        })
    }
}

#[derive(Clone, Debug)]
enum ApplyObservation {
    Acknowledged(AppendReceipt),
    Rejected(Digest32),
    Revoked(Digest32),
    Indeterminate(Digest32),
}

fn unknown(reason: &[u8]) -> ApplyObservation {
    let mut bytes = b"hepta.agentd.intelligence-learning.unknown.v1\0".to_vec();
    bytes.extend_from_slice(reason);
    ApplyObservation::Indeterminate(Digest32::of_bytes(&bytes))
}

fn classify_authority_error(error: FinalUseError) -> ApplyObservation {
    let digest = Digest32::of_bytes(
        format!("hepta.agentd.intelligence-learning-authority.v1:{error:?}").as_bytes(),
    );
    match error {
        FinalUseError::Revoked
        | FinalUseError::EpochMismatch
        | FinalUseError::StaleRevocationHead
        | FinalUseError::Expired => ApplyObservation::Revoked(digest),
        FinalUseError::InvalidGrant
        | FinalUseError::InvalidTrust
        | FinalUseError::AntiRollbackViolation
        | FinalUseError::InvalidSignature
        | FinalUseError::BindingMismatch
        | FinalUseError::NotYetValid => ApplyObservation::Rejected(digest),
        FinalUseError::AlreadyClaimed
        | FinalUseError::CapacityExceeded
        | FinalUseError::DispatchInProgress
        | FinalUseError::Unavailable
        | FinalUseError::UnsafeStateDirectory
        | FinalUseError::StateLocked => ApplyObservation::Indeterminate(digest),
    }
}

fn classify_apply(result: Result<AppendReceipt, ProductionLedgerError>) -> ApplyObservation {
    match result {
        Ok(receipt) => ApplyObservation::Acknowledged(receipt),
        Err(error) => {
            let digest = error_digest(&error);
            match error {
                ProductionLedgerError::Evidence(
                    SignedEvidenceError::Revoked | SignedEvidenceError::ValidityWindow,
                ) => ApplyObservation::Revoked(digest),
                ProductionLedgerError::Binding(
                    clock::CLOCK_UNAVAILABLE | clock::CLOCK_BEHIND_EVENT,
                ) => ApplyObservation::Indeterminate(digest),
                ProductionLedgerError::IndeterminateAfterLedgerCommit { .. }
                | ProductionLedgerError::IndeterminateAfterTopologyChange { .. }
                | ProductionLedgerError::WitnessLag
                | ProductionLedgerError::Durable(DurableLedgerError::Indeterminate)
                | ProductionLedgerError::Durable(DurableLedgerError::Io(_)) => {
                    ApplyObservation::Indeterminate(digest)
                }
                _ => ApplyObservation::Rejected(digest),
            }
        }
    }
}

fn validate_claim_payload(
    intent: &DurableOperationIntentV1,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    if intent.destination.as_str() != LEARNING_DESTINATION_ID
        || envelope.owner_generation > intent.owner_generation.get()
        || envelope.payload.run_id()? != intent.scope_id
        || envelope.payload.operation_id()? != intent.operation_id
        || intent.expected_predecessor.is_some()
            != matches!(envelope.payload, LearningPayloadV1::Outcome(_))
    {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "learning intent/payload identity",
        ));
    }
    Ok(())
}

fn require_prepared_integrity(
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    prepared
        .validate_integrity()
        .map_err(|_| AgentdIntelligenceLearningErrorV1::Invalid("prepared intelligence binding"))
}

fn selected_decision(
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<(&StableId, ProbabilityQ32), AgentdIntelligenceLearningErrorV1> {
    require_prepared_integrity(prepared)?;
    match &prepared.envelope.decision.decision {
        AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } if propensity.raw() > 0
            && prepared
                .candidate_ids()
                .iter()
                .any(|value| value == candidate_id) =>
        {
            Ok((candidate_id, *propensity))
        }
        _ => Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "selected canonical decision",
        )),
    }
}

fn decision_operation_id(
    run_id: &StableId,
    episode_id: &str,
    snapshot: Digest32,
    decision: Digest32,
) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
    let mut bytes = b"hepta.agentd.intelligence-learning-decision-operation.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    push_string(&mut bytes, episode_id)?;
    bytes.extend_from_slice(snapshot.as_array());
    bytes.extend_from_slice(decision.as_array());
    parse_id(&format!(
        "intelligence.decision:{}",
        Digest32::of_bytes(&bytes)
    ))
}

fn outcome_operation_id(
    run_id: &StableId,
    outcome_id: &str,
    physical: Digest32,
) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
    let mut bytes = b"hepta.agentd.intelligence-learning-outcome-operation.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    push_string(&mut bytes, outcome_id)?;
    bytes.extend_from_slice(physical.as_array());
    parse_id(&format!(
        "intelligence.outcome:{}",
        Digest32::of_bytes(&bytes)
    ))
}

fn run_phase_tag(value: RunPhase) -> u8 {
    match value {
        RunPhase::Admitted => 0,
        RunPhase::ContextAttached => 1,
        RunPhase::Dispatched => 2,
        RunPhase::Cancelling => 3,
        RunPhase::Cancelled => 4,
        RunPhase::Succeeded => 5,
        RunPhase::Failed => 6,
        RunPhase::Indeterminate => 7,
    }
}

fn error_digest(error: &ProductionLedgerError) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-learning-error.v1\0".to_vec();
    bytes.extend_from_slice(format!("{error:?}").as_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
fn read_payload_bytes(path: &Path) -> Result<Vec<u8>, AgentdIntelligenceLearningErrorV1> {
    crate::intelligence_files::read_bounded(path, MAX_LEARNING_PAYLOAD_BYTES).map_err(io_error)
}

fn persist_payload(
    root: &Path,
    digest: Digest32,
    bytes: &[u8],
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    crate::intelligence_files::publish_immutable(
        root,
        &format!("{digest}.json"),
        bytes,
        MAX_LEARNING_PAYLOAD_BYTES,
    )
    .map_err(io_error)
}

fn payload_path(root: &Path, digest: Digest32) -> PathBuf {
    root.join(format!("{digest}.json"))
}
fn ensure_private_directory(path: &Path) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    std::fs::create_dir_all(path).map_err(io_error)?;
    let metadata = std::fs::symlink_metadata(path).map_err(io_error)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "learning outbox directory",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).map_err(io_error)?;
    }
    sync_directory(path)
}
fn sync_directory(path: &Path) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(io_error)
}
fn io_error(error: std::io::Error) -> AgentdIntelligenceLearningErrorV1 {
    AgentdIntelligenceLearningErrorV1::Io(error.to_string())
}
fn parse_id(value: &str) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
    StableId::new(value)
        .map_err(|error| AgentdIntelligenceLearningErrorV1::InvalidValue(error.to_string()))
}
fn parse_digest(value: &str) -> Result<Digest32, AgentdIntelligenceLearningErrorV1> {
    Digest32::from_str(value)
        .map_err(|error| AgentdIntelligenceLearningErrorV1::InvalidValue(error.to_string()))
}
fn ledger_id(value: &str) -> Result<StableId, ProductionLedgerError> {
    StableId::new(value).map_err(|_| ProductionLedgerError::Binding("stable identity"))
}
fn ledger_digest(value: &str) -> Result<Digest32, ProductionLedgerError> {
    Digest32::from_str(value).map_err(|_| ProductionLedgerError::Binding("digest"))
}
fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    push_string(bytes, value.as_str())
}
fn push_string(bytes: &mut Vec<u8>, value: &str) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let length = u32::try_from(value.len())
        .map_err(|_| AgentdIntelligenceLearningErrorV1::Invalid("identity length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

#[cfg(test)]
mod file_tests {
    use super::*;

    #[test]
    #[cfg(any(target_os = "linux", target_os = "android", target_vendor = "apple"))]
    fn immutable_payload_publication_is_idempotent_and_bounded() {
        use std::os::unix::fs::PermissionsExt;
        let temporary = tempfile::tempdir().expect("root");
        let root = temporary.path().canonicalize().expect("canonical root");
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("private root");
        let bytes = b"payload";
        let digest = Digest32::of_bytes(bytes);
        persist_payload(root.as_path(), digest, bytes).expect("publish");
        persist_payload(root.as_path(), digest, bytes).expect("same payload");
        assert!(persist_payload(root.as_path(), digest, b"different").is_err());
        assert_eq!(
            read_payload_bytes(&payload_path(root.as_path(), digest)).expect("read"),
            bytes
        );
        let large = root.as_path().join("large.json");
        std::fs::write(&large, vec![0; MAX_LEARNING_PAYLOAD_BYTES + 1]).expect("large file");
        assert!(read_payload_bytes(&large).is_err());
    }

    #[test]
    fn clock_failures_remain_indeterminate_and_expiry_is_quarantined() {
        assert!(matches!(
            classify_apply(Err(ProductionLedgerError::Binding(
                clock::CLOCK_BEHIND_EVENT
            ))),
            ApplyObservation::Indeterminate(_)
        ));
        assert!(matches!(
            classify_apply(Err(ProductionLedgerError::Evidence(
                SignedEvidenceError::ValidityWindow
            ))),
            ApplyObservation::Revoked(_)
        ));
    }
}
