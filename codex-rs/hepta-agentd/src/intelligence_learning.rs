//! Durable product Decision/Outcome closure for canonical intelligence.
//!
//! The product path uses the sole `learning.ledger::LedgerWriter`; the legacy
//! qualification append seam is not promoted.  Before a ledger mutation can be
//! attempted, an immutable payload is synced to disk and a `kernel.operations`
//! intent/outbox row is committed.  Unknown effects are reconciled by replaying
//! the exact payload and original ledger predecessor through the idempotent
//! product writer.  A new logical event is never synthesized during recovery.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
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
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_operations::DispatchEffect;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_operations::DurableOperationIntentV1;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_operations::OperationBacklogMetrics;
use codex_hepta_operations::PrepareDisposition;
use codex_hepta_operations::ReconciliationOutcome;
use codex_hepta_operations::ReconciliationReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::RunPhase;
use crate::RunReceipt;

const LEARNING_PAYLOAD_SCHEMA_VERSION: u32 = 1;
const LEARNING_DESTINATION_ID: &str = "learning.ledger";
const MAX_LEARNING_PAYLOAD_BYTES: usize = 1_048_576;
const CLAIM_LEASE: Duration = Duration::from_secs(30);
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
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub evidence: SignedLearningEvidenceV1,
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

/// Exact run/decision/physical-terminal digest consumed as Outcome support.
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

/// Exact immutable snapshot digest recorded in the product Decision.
pub fn intelligence_run_snapshot_digest_v1(
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<Digest32, AgentdIntelligenceLearningErrorV1> {
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

/// Formal product Decision append. This path is available in the default build
/// and admits only through `LedgerWriter`.
pub fn append_intelligence_decision_v1(
    writer: &mut LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceDecisionAppendV1,
) -> Result<AppendReceipt, AgentdIntelligenceLearningErrorV1> {
    let payload = decision_payload(prepared, request)?;
    apply_decision(writer, &payload).map_err(Into::into)
}

/// Formal product Outcome append bound to the same Decision, candidate,
/// snapshot and observed physical terminal run.
pub fn append_intelligence_outcome_v1(
    writer: &mut LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceOutcomeAppendV1,
) -> Result<AppendReceipt, AgentdIntelligenceLearningErrorV1> {
    let payload = outcome_payload(prepared, request)?;
    apply_outcome(writer, &payload).map_err(Into::into)
}

/// Durable product host.  Payload files are immutable sidecars; logical state,
/// leasing, fencing and terminal reconciliation are owned by kernel.operations.
pub struct AgentdIntelligenceLearningHostV1 {
    operations: DurableOperationStore,
    payload_root: PathBuf,
    destination: StableId,
    worker_id: StableId,
    generation: Generation,
    authority: FinalUseAuthority,
    grants: Arc<dyn AgentdFinalUseGrantProvider>,
    writer: Mutex<LedgerWriter>,
}

impl AgentdIntelligenceLearningHostV1 {
    #[allow(clippy::too_many_arguments)]
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
            destination: StableId::new(LEARNING_DESTINATION_ID).map_err(|error| {
                AgentdIntelligenceLearningErrorV1::InvalidValue(error.to_string())
            })?,
            worker_id,
            generation,
            authority,
            grants,
            writer: Mutex::new(writer),
        })
    }

    pub async fn enqueue_decision(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: AgentdIntelligenceDecisionAppendV1,
    ) -> Result<PrepareDisposition, AgentdIntelligenceLearningErrorV1> {
        let payload = LearningPayloadV1::Decision(decision_payload(prepared, request)?);
        self.enqueue(prepared, payload, None).await
    }

    pub async fn enqueue_outcome(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: AgentdIntelligenceOutcomeAppendV1,
    ) -> Result<PrepareDisposition, AgentdIntelligenceLearningErrorV1> {
        let payload = LearningPayloadV1::Outcome(outcome_payload(prepared, request)?);
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
        let snapshot = prepared.run_snapshot();
        if snapshot.generation != self.generation.get() {
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
        persist_payload(&self.payload_root, payload_digest, &encoded)?;
        let scope_id = envelope.payload.run_id()?;
        let operation_id = envelope.payload.operation_id()?;
        let prepared = self
            .operations
            .prepare_intent(&DurableOperationIntentV1 {
                scope_id,
                operation_id,
                expected_predecessor,
                destination: self.destination.clone(),
                payload_digest,
                owner_generation: self.generation,
            })
            .await?;
        Ok(prepared.disposition)
    }

    /// Dispatch one queued Decision/Outcome through final-use authority and the
    /// sole product writer. Returns `None` when no queued operation exists.
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
        let payload = self.load_payload(claim.intent.payload_digest)?;
        validate_claim_payload(&claim.intent, &payload)?;
        let signed = self
            .grants
            .signed_grant(&claim.intent.final_use_binding())?;
        let authorized = self
            .operations
            .authorize_dispatch(&self.authority, &signed, &claim)
            .await?;
        let observation = self
            .operations
            .execute_authorized(authorized, |_| {
                let applied = match self.writer.lock() {
                    Ok(mut writer) => classify_apply(apply_payload(&mut writer, &payload)),
                    Err(_) => ApplyObservation::Indeterminate(Digest32::of_bytes(
                        b"hepta.agentd.intelligence-learning.writer-poisoned.v1",
                    )),
                };
                match &applied {
                    ApplyObservation::Acknowledged(receipt) => DispatchEffect::Dispatched {
                        value: applied.clone(),
                        dispatch_digest: receipt.chain_digest,
                        acknowledgement_digest: Some(receipt.chain_digest),
                    },
                    ApplyObservation::Rejected(digest)
                    | ApplyObservation::Revoked(digest)
                    | ApplyObservation::Indeterminate(digest) => DispatchEffect::Indeterminate {
                        value: applied.clone(),
                        reason_digest: *digest,
                    },
                }
            })
            .await?;
        Ok(Some(
            self.settle_observation(
                &claim.intent.scope_id,
                &claim.intent.operation_id,
                observation,
            )
            .await?,
        ))
    }

    /// Reconcile dispatching/dispatched/indeterminate records after process
    /// restart. The destination is observed first. If the exact event is already
    /// present, the operation is acknowledged without consuming new authority.
    /// Otherwise the exact payload/original predecessor may be replayed only
    /// behind a fresh final-use grant for the adopted operation generation.
    pub async fn reconcile_unsettled(
        &self,
        limit: u32,
    ) -> Result<Vec<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1> {
        if limit == 0 || limit > MAX_RECONCILE_BATCH {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "reconciliation limit",
            ));
        }
        let records = self
            .operations
            .unsettled_operations(&self.destination, limit)
            .await?;
        let mut receipts = Vec::with_capacity(records.len());
        for record in records {
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
            let payload = self.load_payload(record.intent.payload_digest)?;
            validate_claim_payload(&record.intent, &payload)?;
            let observation = match self.writer.lock() {
                Ok(mut writer) => match observe_applied_payload(&writer, &payload) {
                    Ok(Some(receipt)) => ApplyObservation::Acknowledged(receipt),
                    Ok(None) => {
                        let binding = record.intent.final_use_binding();
                        let signed = self.grants.signed_grant(&binding)?;
                        match claim_final_use(&self.authority, &signed, &binding) {
                            Ok(token) => {
                                match dispatch_final_use(&self.authority, token, &binding, || {
                                    apply_payload(&mut writer, &payload)
                                }) {
                                    Ok(result) => classify_apply(result),
                                    Err(error) => classify_authority_error(error),
                                }
                            }
                            Err(error) => classify_authority_error(error),
                        }
                    }
                    Err(error) => classify_apply(Err(error)),
                },
                Err(_) => ApplyObservation::Indeterminate(Digest32::of_bytes(
                    b"hepta.agentd.intelligence-learning.writer-poisoned.v1",
                )),
            };
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

    fn load_payload(
        &self,
        payload_digest: Digest32,
    ) -> Result<PersistedLearningEnvelopeV1, AgentdIntelligenceLearningErrorV1> {
        let path = payload_path(&self.payload_root, payload_digest);
        let metadata = std::fs::symlink_metadata(&path)
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
        if metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() == 0
            || metadata.len() > MAX_LEARNING_PAYLOAD_BYTES as u64
        {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "learning payload file",
            ));
        }
        let bytes = std::fs::read(&path)
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
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

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PersistedLearningEnvelopeV1 {
    schema_version: u32,
    owner_generation: u64,
    payload: LearningPayloadV1,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
enum LearningPayloadV1 {
    Decision(DecisionPayloadV1),
    Outcome(OutcomePayloadV1),
}

impl LearningPayloadV1 {
    fn run_id(&self) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        parse_id(match self {
            Self::Decision(value) => &value.record_id,
            Self::Outcome(value) => &value.decision_record_id,
        })
    }

    fn episode_id(&self) -> &str {
        match self {
            Self::Decision(value) => &value.episode_id,
            Self::Outcome(value) => &value.episode_id,
        }
    }

    fn run_snapshot_digest(&self) -> Result<Digest32, AgentdIntelligenceLearningErrorV1> {
        parse_digest(match self {
            Self::Decision(value) => &value.run_snapshot_digest,
            Self::Outcome(value) => &value.expected_run_snapshot_digest,
        })
    }

    fn operation_id(&self) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        match self {
            Self::Decision(value) => decision_operation_id(
                &parse_id(&value.record_id)?,
                &value.episode_id,
                parse_digest(&value.run_snapshot_digest)?,
                parse_digest(&value.decision_digest)?,
            ),
            Self::Outcome(value) => outcome_operation_id(
                &parse_id(&value.decision_record_id)?,
                &value.outcome.outcome_id,
                parse_digest(&value.physical_binding_digest)?,
            ),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DecisionPayloadV1 {
    expected_ledger_predecessor: String,
    record_id: String,
    episode_id: String,
    run_snapshot_digest: String,
    objective_digest: String,
    policy_digest: String,
    candidate_ids: Vec<String>,
    selected_candidate_id: String,
    selected_propensity_raw: u64,
    completeness: CompletenessPayloadV1,
    support_digest: String,
    decision_digest: String,
    evidence: EvidencePayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OutcomePayloadV1 {
    expected_ledger_predecessor: String,
    decision_record_id: String,
    episode_id: String,
    expected_run_snapshot_digest: String,
    selected_candidate_id: String,
    physical_binding_digest: String,
    outcome: OutcomePayloadRecordV1,
    evidence: EvidencePayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompletenessPayloadV1 {
    set_id: String,
    state_digest: String,
    generator_id: String,
    generator_code_digest: String,
    grammar_digest: String,
    hard_filter_digest: String,
    truncation_digest: String,
    candidates_digest: String,
    candidate_count: u32,
    omitted_count_bound: u32,
    canonical_order_digest: String,
    complete_for_generator: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidencePayloadV1 {
    evidence_id: String,
    principal_id: String,
    role: String,
    trust_digest: String,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PrincipalPayloadV1 {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OutcomePayloadRecordV1 {
    record_id: String,
    outcome_id: String,
    episode_id: String,
    observer: PrincipalPayloadV1,
    observed_at: Option<u64>,
    value_raw: Option<i64>,
    unit_profile_digest: String,
    support_digest: String,
    latest_observable_at: u64,
    expected_delay_profile_digest: String,
    terminality: String,
    censoring_reason: Option<String>,
    correction_predecessor: Option<String>,
    finalized_at: Option<u64>,
}

#[derive(Clone, Debug)]
enum ApplyObservation {
    Acknowledged(AppendReceipt),
    Rejected(Digest32),
    Revoked(Digest32),
    Indeterminate(Digest32),
}

fn decision_payload(
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceDecisionAppendV1,
) -> Result<DecisionPayloadV1, AgentdIntelligenceLearningErrorV1> {
    if request.expected_ledger_predecessor.is_zero() && request.episode_id.as_str().is_empty() {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "decision identity",
        ));
    }
    let (selected_candidate_id, selected_propensity) = selected_decision(prepared)?;
    let snapshot = prepared.run_snapshot();
    let run_snapshot_digest = intelligence_run_snapshot_digest_v1(prepared)?;
    Ok(DecisionPayloadV1 {
        expected_ledger_predecessor: request.expected_ledger_predecessor.to_string(),
        record_id: snapshot.run_id,
        episode_id: request.episode_id.to_string(),
        run_snapshot_digest: run_snapshot_digest.to_string(),
        objective_digest: prepared.envelope.objective_digest.to_string(),
        policy_digest: request.policy_digest.to_string(),
        candidate_ids: prepared
            .candidate_ids()
            .iter()
            .map(ToString::to_string)
            .collect(),
        selected_candidate_id: selected_candidate_id.to_string(),
        selected_propensity_raw: selected_propensity.raw(),
        completeness: request.completeness.into(),
        support_digest: prepared.dispatch_proposal_digest.to_string(),
        decision_digest: prepared.envelope.decision.decision_digest.to_string(),
        evidence: EvidencePayloadV1::from_typed(&request.evidence),
        now: request.now,
    })
}

fn outcome_payload(
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceOutcomeAppendV1,
) -> Result<OutcomePayloadV1, AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, _) = selected_decision(prepared)?;
    let snapshot = prepared.run_snapshot();
    let run_id = parse_id(&snapshot.run_id)?;
    if request.decision_record_id != run_id
        || request.outcome.episode_id != request.episode_id
        || request.outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
    {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "outcome decision/episode/terminality binding",
        ));
    }
    let run_snapshot_digest = intelligence_run_snapshot_digest_v1(prepared)?;
    let physical_binding_digest = intelligence_physical_terminal_binding_digest_v1(
        prepared,
        &request.run_receipt,
        request.provider_terminal_digest,
    )?;
    if request.outcome.support_digest != physical_binding_digest {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "outcome physical support binding",
        ));
    }
    Ok(OutcomePayloadV1 {
        expected_ledger_predecessor: request.expected_ledger_predecessor.to_string(),
        decision_record_id: request.decision_record_id.to_string(),
        episode_id: request.episode_id.to_string(),
        expected_run_snapshot_digest: run_snapshot_digest.to_string(),
        selected_candidate_id: selected_candidate_id.to_string(),
        physical_binding_digest: physical_binding_digest.to_string(),
        outcome: OutcomePayloadRecordV1::from_typed(&request.outcome),
        evidence: EvidencePayloadV1::from_typed(&request.evidence),
        now: request.now,
    })
}

fn observe_applied_payload(
    writer: &LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<Option<AppendReceipt>, ProductionLedgerError> {
    let records = writer.records()?;
    let matched = records.iter().rev().find(|record| match &envelope.payload {
        LearningPayloadV1::Decision(payload) => {
            let Ok(record_id) = ledger_id(&payload.record_id) else {
                return false;
            };
            let Ok(episode_id) = ledger_id(&payload.episode_id) else {
                return false;
            };
            let Ok(run_snapshot_digest) = ledger_digest(&payload.run_snapshot_digest) else {
                return false;
            };
            let Ok(objective_digest) = ledger_digest(&payload.objective_digest) else {
                return false;
            };
            let Ok(policy_digest) = ledger_digest(&payload.policy_digest) else {
                return false;
            };
            let Ok(selected_candidate_id) = ledger_id(&payload.selected_candidate_id) else {
                return false;
            };
            let Ok(support_digest) = ledger_digest(&payload.support_digest) else {
                return false;
            };
            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(completeness_digest) = validate_candidate_set_completeness(&completeness) else {
                return false;
            };
            let Ok(candidate_ids) = payload
                .candidate_ids
                .iter()
                .map(|value| ledger_id(value))
                .collect::<Result<Vec<_>, _>>()
            else {
                return false;
            };
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedDecisionV2(value)
                    if value.record_id == record_id
                        && value.episode_id == episode_id
                        && value.run_snapshot_digest == run_snapshot_digest
                        && value.objective_digest == objective_digest
                        && value.policy_digest == policy_digest
                        && value.candidate_ids == candidate_ids
                        && value.selected_candidate_id == selected_candidate_id
                        && value.selected_propensity.raw() == payload.selected_propensity_raw
                        && value.candidate_completeness_digest == completeness_digest
                        && value.support_digest == support_digest
            )
        }
        LearningPayloadV1::Outcome(payload) => {
            let Ok(expected) = payload.outcome.to_typed() else {
                return false;
            };
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedOutcomeV2(value) if value == &expected
            )
        }
    });
    Ok(matched.map(|record| AppendReceipt {
        disposition: AppendDisposition::IdempotentReplay,
        sequence: record.sequence,
        event_digest: record.event_digest,
        chain_digest: record.chain_digest,
    }))
}

fn apply_payload(
    writer: &mut LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<AppendReceipt, ProductionLedgerError> {
    match &envelope.payload {
        LearningPayloadV1::Decision(value) => apply_decision(writer, value),
        LearningPayloadV1::Outcome(value) => apply_outcome(writer, value),
    }
}

fn apply_decision(
    writer: &mut LedgerWriter,
    payload: &DecisionPayloadV1,
) -> Result<AppendReceipt, ProductionLedgerError> {
    let request = ProductionDecisionV2 {
        record_id: ledger_id(&payload.record_id)?,
        episode_id: ledger_id(&payload.episode_id)?,
        run_snapshot_digest: ledger_digest(&payload.run_snapshot_digest)?,
        objective_digest: ledger_digest(&payload.objective_digest)?,
        policy_digest: ledger_digest(&payload.policy_digest)?,
        candidate_ids: payload
            .candidate_ids
            .iter()
            .map(|value| ledger_id(value))
            .collect::<Result<Vec<_>, _>>()?,
        selected_candidate_id: ledger_id(&payload.selected_candidate_id)?,
        selected_propensity: ProbabilityQ32::from_raw(payload.selected_propensity_raw)
            .map_err(|_| ProductionLedgerError::Binding("decision propensity"))?,
        completeness: payload.completeness.to_typed()?,
        support_digest: ledger_digest(&payload.support_digest)?,
    };
    let evidence = payload
        .evidence
        .to_typed(LearningEvidenceRoleV1::Generator)?;
    writer.append_decision(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        request,
        &evidence,
        payload.now,
    )
}

fn apply_outcome(
    writer: &mut LedgerWriter,
    payload: &OutcomePayloadV1,
) -> Result<AppendReceipt, ProductionLedgerError> {
    let decision_record_id = ledger_id(&payload.decision_record_id)?;
    let episode_id = ledger_id(&payload.episode_id)?;
    writer.verify_active_decision_binding(&decision_record_id, &episode_id)?;
    let expected_snapshot = ledger_digest(&payload.expected_run_snapshot_digest)?;
    let expected_candidate = ledger_id(&payload.selected_candidate_id)?;
    let records = writer.records()?;
    let decision_matches = records.iter().rev().any(|record| {
        matches!(
            &record.event,
            LedgerEvent::AuthenticatedDecisionV2(value)
                if value.record_id == decision_record_id
                    && value.episode_id == episode_id
                    && value.run_snapshot_digest == expected_snapshot
                    && value.selected_candidate_id == expected_candidate
        )
    });
    if !decision_matches {
        return Err(ProductionLedgerError::Binding(
            "outcome decision/candidate/snapshot",
        ));
    }
    let outcome = payload.outcome.to_typed()?;
    if outcome.episode_id != episode_id
        || outcome.support_digest != ledger_digest(&payload.physical_binding_digest)?
        || outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
    {
        return Err(ProductionLedgerError::Binding(
            "outcome physical terminal binding",
        ));
    }
    let evidence = payload
        .evidence
        .to_typed(LearningEvidenceRoleV1::Observer)?;
    writer.append_outcome(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        outcome,
        &evidence,
        payload.now,
    )
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
                ProductionLedgerError::Evidence(SignedEvidenceError::Revoked) => {
                    ApplyObservation::Revoked(digest)
                }
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
    if envelope.owner_generation > intent.owner_generation.get()
        || envelope.payload.run_id()? != intent.scope_id
        || envelope.payload.operation_id()? != intent.operation_id
    {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "learning intent/payload identity",
        ));
    }
    Ok(())
}

fn selected_decision(
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<(&StableId, ProbabilityQ32), AgentdIntelligenceLearningErrorV1> {
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
    run_snapshot_digest: Digest32,
    decision_digest: Digest32,
) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
    let mut bytes = b"hepta.agentd.intelligence-learning-decision-operation.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    push_string(&mut bytes, episode_id)?;
    bytes.extend_from_slice(run_snapshot_digest.as_array());
    bytes.extend_from_slice(decision_digest.as_array());
    StableId::new(format!(
        "intelligence.decision:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|error| AgentdIntelligenceLearningErrorV1::InvalidValue(error.to_string()))
}

fn outcome_operation_id(
    run_id: &StableId,
    outcome_id: &str,
    physical_binding_digest: Digest32,
) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
    let mut bytes = b"hepta.agentd.intelligence-learning-outcome-operation.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    push_string(&mut bytes, outcome_id)?;
    bytes.extend_from_slice(physical_binding_digest.as_array());
    StableId::new(format!(
        "intelligence.outcome:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|error| AgentdIntelligenceLearningErrorV1::InvalidValue(error.to_string()))
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

fn persist_payload(
    root: &Path,
    digest: Digest32,
    bytes: &[u8],
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let final_path = payload_path(root, digest);
    if final_path.exists() {
        let existing = std::fs::read(&final_path)
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
        if existing == bytes {
            return Ok(());
        }
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "immutable learning payload conflict",
        ));
    }
    let temporary = root.join(format!("{}.tmp-{}", digest, std::process::id()));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(&temporary)
        .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
    std::fs::rename(&temporary, &final_path)
        .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
    sync_directory(root)?;
    Ok(())
}

fn payload_path(root: &Path, digest: Digest32) -> PathBuf {
    root.join(format!("{digest}.json"))
}

fn ensure_private_directory(path: &Path) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    std::fs::create_dir_all(path)
        .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "learning outbox directory",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = metadata.permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(path, permissions)
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
    }
    sync_directory(path)
}

fn sync_directory(path: &Path) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))
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

impl From<CandidateSetCompletenessReceiptV1> for CompletenessPayloadV1 {
    fn from(value: CandidateSetCompletenessReceiptV1) -> Self {
        Self {
            set_id: value.set_id.to_string(),
            state_digest: value.state_digest.to_string(),
            generator_id: value.generator_id.to_string(),
            generator_code_digest: value.generator_code_digest.to_string(),
            grammar_digest: value.grammar_digest.to_string(),
            hard_filter_digest: value.hard_filter_digest.to_string(),
            truncation_digest: value.truncation_digest.to_string(),
            candidates_digest: value.candidates_digest.to_string(),
            candidate_count: value.candidate_count,
            omitted_count_bound: value.omitted_count_bound,
            canonical_order_digest: value.canonical_order_digest.to_string(),
            complete_for_generator: value.complete_for_generator,
        }
    }
}

impl CompletenessPayloadV1 {
    fn to_typed(&self) -> Result<CandidateSetCompletenessReceiptV1, ProductionLedgerError> {
        Ok(CandidateSetCompletenessReceiptV1 {
            set_id: ledger_id(&self.set_id)?,
            state_digest: ledger_digest(&self.state_digest)?,
            generator_id: ledger_id(&self.generator_id)?,
            generator_code_digest: ledger_digest(&self.generator_code_digest)?,
            grammar_digest: ledger_digest(&self.grammar_digest)?,
            hard_filter_digest: ledger_digest(&self.hard_filter_digest)?,
            truncation_digest: ledger_digest(&self.truncation_digest)?,
            candidates_digest: ledger_digest(&self.candidates_digest)?,
            candidate_count: self.candidate_count,
            omitted_count_bound: self.omitted_count_bound,
            canonical_order_digest: ledger_digest(&self.canonical_order_digest)?,
            complete_for_generator: self.complete_for_generator,
        })
    }
}

impl EvidencePayloadV1 {
    fn from_typed(value: &SignedLearningEvidenceV1) -> Self {
        Self {
            evidence_id: value.evidence_id.to_string(),
            principal_id: value.principal_id.to_string(),
            role: role_name(value.role).to_string(),
            trust_digest: value.trust_digest.to_string(),
            scope_digest: value.scope_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            authority_epoch: value.authority_epoch,
            issued_at: value.issued_at,
            expires_at: value.expires_at,
            payload_digest: value.payload_digest.to_string(),
            signature: value.signature.to_vec(),
        }
    }

    fn to_typed(
        &self,
        expected_role: LearningEvidenceRoleV1,
    ) -> Result<SignedLearningEvidenceV1, ProductionLedgerError> {
        if self.role != role_name(expected_role) || self.signature.len() != 64 {
            return Err(ProductionLedgerError::Binding(
                "learning evidence role/signature",
            ));
        }
        let signature: [u8; 64] = self
            .signature
            .as_slice()
            .try_into()
            .map_err(|_| ProductionLedgerError::Binding("learning evidence signature"))?;
        Ok(SignedLearningEvidenceV1 {
            evidence_id: ledger_id(&self.evidence_id)?,
            principal_id: ledger_id(&self.principal_id)?,
            role: expected_role,
            trust_digest: ledger_digest(&self.trust_digest)?,
            scope_digest: ledger_digest(&self.scope_digest)?,
            objective_digest: ledger_digest(&self.objective_digest)?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            payload_digest: ledger_digest(&self.payload_digest)?,
            signature,
        })
    }
}

impl PrincipalPayloadV1 {
    fn from_typed(value: &AuthenticatedPrincipalV1) -> Self {
        Self {
            principal_id: value.principal_id.to_string(),
            credential_chain_digest: value.credential_chain_digest.to_string(),
            signing_key_digest: value.signing_key_digest.to_string(),
            scope_digest: value.scope_digest.to_string(),
            authority_epoch: value.authority_epoch,
            authenticated_at: value.authenticated_at,
            expires_at: value.expires_at,
        }
    }

    fn to_typed(&self) -> Result<AuthenticatedPrincipalV1, ProductionLedgerError> {
        Ok(AuthenticatedPrincipalV1 {
            principal_id: ledger_id(&self.principal_id)?,
            credential_chain_digest: ledger_digest(&self.credential_chain_digest)?,
            signing_key_digest: ledger_digest(&self.signing_key_digest)?,
            scope_digest: ledger_digest(&self.scope_digest)?,
            authority_epoch: self.authority_epoch,
            authenticated_at: self.authenticated_at,
            expires_at: self.expires_at,
        })
    }
}

impl OutcomePayloadRecordV1 {
    fn from_typed(value: &AuthenticatedOutcomeV1) -> Self {
        Self {
            record_id: value.record_id.to_string(),
            outcome_id: value.outcome_id.to_string(),
            episode_id: value.episode_id.to_string(),
            observer: PrincipalPayloadV1::from_typed(&value.observer),
            observed_at: value.observed_at,
            value_raw: value.value.map(FixedQ32::raw),
            unit_profile_digest: value.unit_profile_digest.to_string(),
            support_digest: value.support_digest.to_string(),
            latest_observable_at: value.watermark.latest_observable_at,
            expected_delay_profile_digest: value
                .watermark
                .expected_delay_profile_digest
                .to_string(),
            terminality: terminality_name(value.watermark.terminality).to_string(),
            censoring_reason: value
                .watermark
                .censoring_reason
                .as_ref()
                .map(ToString::to_string),
            correction_predecessor: value
                .watermark
                .correction_predecessor
                .as_ref()
                .map(ToString::to_string),
            finalized_at: value.watermark.finalized_at,
        }
    }

    fn to_typed(&self) -> Result<AuthenticatedOutcomeV1, ProductionLedgerError> {
        let terminality = match self.terminality.as_str() {
            "pending" => OutcomeTerminalityV1::Pending,
            "censored" => OutcomeTerminalityV1::Censored,
            "terminal" => OutcomeTerminalityV1::Terminal,
            _ => return Err(ProductionLedgerError::Binding("outcome terminality")),
        };
        Ok(AuthenticatedOutcomeV1 {
            record_id: ledger_id(&self.record_id)?,
            outcome_id: ledger_id(&self.outcome_id)?,
            episode_id: ledger_id(&self.episode_id)?,
            observer: self.observer.to_typed()?,
            observed_at: self.observed_at,
            value: self.value_raw.map(FixedQ32::from_raw),
            unit_profile_digest: ledger_digest(&self.unit_profile_digest)?,
            support_digest: ledger_digest(&self.support_digest)?,
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: self.latest_observable_at,
                expected_delay_profile_digest: ledger_digest(&self.expected_delay_profile_digest)?,
                terminality,
                censoring_reason: self
                    .censoring_reason
                    .as_deref()
                    .map(ledger_id)
                    .transpose()?,
                correction_predecessor: self
                    .correction_predecessor
                    .as_deref()
                    .map(ledger_id)
                    .transpose()?,
                finalized_at: self.finalized_at,
            },
        })
    }
}

fn role_name(value: LearningEvidenceRoleV1) -> &'static str {
    match value {
        LearningEvidenceRoleV1::Generator => "generator",
        LearningEvidenceRoleV1::Observer => "observer",
        LearningEvidenceRoleV1::Evaluator => "evaluator",
        LearningEvidenceRoleV1::CreditAllocator => "credit_allocator",
        LearningEvidenceRoleV1::UnlearningAuthority => "unlearning_authority",
        LearningEvidenceRoleV1::Selector => "selector",
    }
}

fn terminality_name(value: OutcomeTerminalityV1) -> &'static str {
    match value {
        OutcomeTerminalityV1::Pending => "pending",
        OutcomeTerminalityV1::Censored => "censored",
        OutcomeTerminalityV1::Terminal => "terminal",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn operation_ids_are_kind_separated_and_stable() {
        let run = StableId::new("run.learning").expect("run id");
        let snapshot = Digest32::of_bytes(b"snapshot");
        let decision = Digest32::of_bytes(b"decision");
        let physical = Digest32::of_bytes(b"physical");
        let first = decision_operation_id(&run, "episode.one", snapshot, decision)
            .expect("decision operation");
        let second = decision_operation_id(&run, "episode.one", snapshot, decision)
            .expect("decision operation");
        let outcome =
            outcome_operation_id(&run, "outcome.one", physical).expect("outcome operation");
        assert_eq!(first, second);
        assert_ne!(first, outcome);
    }

    #[test]
    fn evidence_payload_rejects_role_substitution() {
        let value = EvidencePayloadV1 {
            evidence_id: "evidence.one".to_string(),
            principal_id: "principal.one".to_string(),
            role: "generator".to_string(),
            trust_digest: Digest32::of_bytes(b"trust").to_string(),
            scope_digest: Digest32::of_bytes(b"scope").to_string(),
            objective_digest: Digest32::of_bytes(b"objective").to_string(),
            authority_epoch: 1,
            issued_at: 1,
            expires_at: 2,
            payload_digest: Digest32::of_bytes(b"payload").to_string(),
            signature: vec![0; 64],
        };
        assert!(value.to_typed(LearningEvidenceRoleV1::Generator).is_ok());
        assert!(value.to_typed(LearningEvidenceRoleV1::Observer).is_err());
    }
}
