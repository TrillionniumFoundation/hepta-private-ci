//! Durable ambiguity tracking for intelligence Decision/Outcome publication.
//!
//! The learning ledger remains the sole fact owner. This outbox persists only
//! the exact append identity, semantic digest and terminal observation needed to
//! determine whether a process-loss window committed the intended fact. It never
//! stores signing keys, invents evidence or authorizes replay. Missing records
//! remain `Indeterminate` until the authoritative caller retries the same typed
//! request; a matching durable ledger record becomes `Acknowledged` without
//! redispatching the physical run.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedDecisionRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const OUTBOX_SCHEMA_VERSION: u32 = 1;
const MAX_OUTBOX_BYTES: u64 = 4 * 1024 * 1024;
const MAX_OUTBOX_RECORDS: usize = 4_096;
const MAX_REASON_BYTES: usize = 512;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IntelligenceLearningAppendKindV1 {
    Decision,
    Outcome,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IntelligenceLearningAppendStateV1 {
    Prepared,
    Acknowledged,
    Rejected,
    Revoked,
    Indeterminate,
}

impl IntelligenceLearningAppendStateV1 {
    #[must_use]
    pub const fn terminal(self) -> bool {
        matches!(self, Self::Acknowledged | Self::Rejected | Self::Revoked)
    }
}

/// One process-loss-safe publication identity. Every digest is lower-case
/// canonical hex. Mutable transition fields are excluded from semantic equality.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntelligenceLearningIntentV1 {
    pub operation_id: String,
    pub kind: IntelligenceLearningAppendKindV1,
    pub record_id: String,
    pub run_id: String,
    pub episode_id: String,
    pub expected_predecessor: String,
    pub run_snapshot_digest: String,
    pub objective_digest: String,
    pub support_digest: String,
    pub semantic_digest: String,
    pub authentication_digest: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: String,
    pub state: IntelligenceLearningAppendStateV1,
    pub revision: u64,
    pub observed_sequence: Option<u64>,
    pub observed_event_digest: Option<String>,
    pub observed_chain_digest: Option<String>,
    pub reason_digest: Option<String>,
}

impl IntelligenceLearningIntentV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        kind: IntelligenceLearningAppendKindV1,
        record_id: &StableId,
        run_id: &StableId,
        episode_id: &StableId,
        expected_predecessor: Digest32,
        run_snapshot_digest: Digest32,
        objective_digest: Digest32,
        support_digest: Digest32,
        semantic_digest: Digest32,
        authentication_digest: Digest32,
        authority_epoch: u64,
        generation: u64,
        fence_digest: &str,
    ) -> Result<Self, IntelligenceLearningOutboxErrorV1> {
        let mut operation_bytes = b"hepta.agentd.intelligence-learning-operation.v1\0".to_vec();
        operation_bytes.push(match kind {
            IntelligenceLearningAppendKindV1::Decision => 0,
            IntelligenceLearningAppendKindV1::Outcome => 1,
        });
        push_id(&mut operation_bytes, record_id);
        push_id(&mut operation_bytes, run_id);
        push_id(&mut operation_bytes, episode_id);
        operation_bytes.extend_from_slice(semantic_digest.as_array());
        let operation_digest = Digest32::of_bytes(&operation_bytes);
        let operation_id = format!("intelligence-learning:{operation_digest}");
        StableId::new(operation_id.clone())
            .map_err(|_| IntelligenceLearningOutboxErrorV1::Invalid("operation id"))?;
        let value = Self {
            operation_id,
            kind,
            record_id: record_id.to_string(),
            run_id: run_id.to_string(),
            episode_id: episode_id.to_string(),
            expected_predecessor: expected_predecessor.to_string(),
            run_snapshot_digest: run_snapshot_digest.to_string(),
            objective_digest: objective_digest.to_string(),
            support_digest: support_digest.to_string(),
            semantic_digest: semantic_digest.to_string(),
            authentication_digest: authentication_digest.to_string(),
            authority_epoch,
            generation,
            fence_digest: fence_digest.to_string(),
            state: IntelligenceLearningAppendStateV1::Prepared,
            revision: 1,
            observed_sequence: None,
            observed_event_digest: None,
            observed_chain_digest: None,
            reason_digest: None,
        };
        value.validate()?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), IntelligenceLearningOutboxErrorV1> {
        for value in [
            self.operation_id.as_str(),
            self.record_id.as_str(),
            self.run_id.as_str(),
            self.episode_id.as_str(),
        ] {
            StableId::new(value)
                .map_err(|_| IntelligenceLearningOutboxErrorV1::Invalid("identifier"))?;
        }
        for value in [
            self.expected_predecessor.as_str(),
            self.run_snapshot_digest.as_str(),
            self.objective_digest.as_str(),
            self.support_digest.as_str(),
            self.semantic_digest.as_str(),
            self.authentication_digest.as_str(),
            self.fence_digest.as_str(),
        ] {
            parse_digest(value)?;
        }
        if self.authority_epoch == 0 || self.generation == 0 || self.revision == 0 {
            return Err(IntelligenceLearningOutboxErrorV1::Invalid(
                "epoch or revision",
            ));
        }
        for value in [
            self.observed_event_digest.as_deref(),
            self.observed_chain_digest.as_deref(),
            self.reason_digest.as_deref(),
        ]
        .into_iter()
        .flatten()
        {
            parse_digest(value)?;
        }
        if self.state == IntelligenceLearningAppendStateV1::Acknowledged
            && (self.observed_sequence.is_none()
                || self.observed_event_digest.is_none()
                || self.observed_chain_digest.is_none())
        {
            return Err(IntelligenceLearningOutboxErrorV1::Invalid(
                "acknowledgement evidence",
            ));
        }
        Ok(())
    }

    fn same_semantics(&self, other: &Self) -> bool {
        self.operation_id == other.operation_id
            && self.kind == other.kind
            && self.record_id == other.record_id
            && self.run_id == other.run_id
            && self.episode_id == other.episode_id
            && self.expected_predecessor == other.expected_predecessor
            && self.run_snapshot_digest == other.run_snapshot_digest
            && self.objective_digest == other.objective_digest
            && self.support_digest == other.support_digest
            && self.semantic_digest == other.semantic_digest
            && self.authentication_digest == other.authentication_digest
            && self.authority_epoch == other.authority_epoch
            && self.generation == other.generation
            && self.fence_digest == other.fence_digest
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct IntelligenceLearningOutboxFileV1 {
    schema_version: u32,
    records: Vec<IntelligenceLearningIntentV1>,
}

/// Single-writer durable outbox. The Agentd process writer lock remains the
/// outer concurrency fence; this type performs atomic replace plus directory
/// sync for every state transition.
pub struct DurableIntelligenceLearningOutboxV1 {
    path: PathBuf,
    records: BTreeMap<String, IntelligenceLearningIntentV1>,
}

impl DurableIntelligenceLearningOutboxV1 {
    pub fn open(path: PathBuf) -> Result<Self, IntelligenceLearningOutboxErrorV1> {
        validate_outbox_path(&path)?;
        if !path.exists() {
            let mut value = Self {
                path,
                records: BTreeMap::new(),
            };
            value.persist()?;
            return Ok(value);
        }
        validate_existing_file(&path)?;
        let metadata = std::fs::metadata(&path)?;
        if metadata.len() == 0 || metadata.len() > MAX_OUTBOX_BYTES {
            return Err(IntelligenceLearningOutboxErrorV1::Invalid("outbox size"));
        }
        let bytes = std::fs::read(&path)?;
        let decoded: IntelligenceLearningOutboxFileV1 = serde_json::from_slice(&bytes)?;
        if decoded.schema_version != OUTBOX_SCHEMA_VERSION
            || decoded.records.len() > MAX_OUTBOX_RECORDS
        {
            return Err(IntelligenceLearningOutboxErrorV1::Invalid(
                "outbox schema or capacity",
            ));
        }
        let mut records = BTreeMap::new();
        for record in decoded.records {
            record.validate()?;
            if records
                .insert(record.operation_id.clone(), record)
                .is_some()
            {
                return Err(IntelligenceLearningOutboxErrorV1::Conflict);
            }
        }
        Ok(Self {
            path,
            records,
        })
    }

    pub fn prepare(
        &mut self,
        intent: IntelligenceLearningIntentV1,
    ) -> Result<IntelligenceLearningIntentV1, IntelligenceLearningOutboxErrorV1> {
        intent.validate()?;
        if let Some(current) = self.records.get(&intent.operation_id) {
            if current.same_semantics(&intent) {
                return Ok(current.clone());
            }
            return Err(IntelligenceLearningOutboxErrorV1::Conflict);
        }
        if self.records.len() >= MAX_OUTBOX_RECORDS {
            return Err(IntelligenceLearningOutboxErrorV1::Capacity);
        }
        self.records
            .insert(intent.operation_id.clone(), intent.clone());
        self.persist()?;
        Ok(intent)
    }

    pub fn acknowledge(
        &mut self,
        operation_id: &str,
        receipt: &AppendReceipt,
    ) -> Result<IntelligenceLearningIntentV1, IntelligenceLearningOutboxErrorV1> {
        self.transition_observed(
            operation_id,
            IntelligenceLearningAppendStateV1::Acknowledged,
            Some(receipt.sequence.get()),
            Some(receipt.event_digest),
            Some(receipt.chain_digest),
            None,
        )
    }

    pub fn mark_indeterminate(
        &mut self,
        operation_id: &str,
        receipt: Option<&AppendReceipt>,
        reason: &str,
    ) -> Result<IntelligenceLearningIntentV1, IntelligenceLearningOutboxErrorV1> {
        self.transition_observed(
            operation_id,
            IntelligenceLearningAppendStateV1::Indeterminate,
            receipt.map(|value| value.sequence.get()),
            receipt.map(|value| value.event_digest),
            receipt.map(|value| value.chain_digest),
            Some(reason_digest(reason)?),
        )
    }

    pub fn mark_rejected(
        &mut self,
        operation_id: &str,
        reason: &str,
    ) -> Result<IntelligenceLearningIntentV1, IntelligenceLearningOutboxErrorV1> {
        self.transition_observed(
            operation_id,
            IntelligenceLearningAppendStateV1::Rejected,
            None,
            None,
            None,
            Some(reason_digest(reason)?),
        )
    }

    pub fn mark_revoked(
        &mut self,
        operation_id: &str,
        reason: &str,
    ) -> Result<IntelligenceLearningIntentV1, IntelligenceLearningOutboxErrorV1> {
        self.transition_observed(
            operation_id,
            IntelligenceLearningAppendStateV1::Revoked,
            None,
            None,
            None,
            Some(reason_digest(reason)?),
        )
    }

    #[must_use]
    pub fn backlog(&self) -> usize {
        self.records
            .values()
            .filter(|record| {
                matches!(
                    record.state,
                    IntelligenceLearningAppendStateV1::Prepared
                        | IntelligenceLearningAppendStateV1::Indeterminate
                )
            })
            .count()
    }

    #[must_use]
    pub fn record(&self, operation_id: &str) -> Option<&IntelligenceLearningIntentV1> {
        self.records.get(operation_id)
    }

    #[must_use]
    pub fn snapshot(&self) -> Vec<IntelligenceLearningIntentV1> {
        self.records.values().cloned().collect()
    }

    /// Reconcile every unresolved intent against the freshly recovered product
    /// ledger. A matching record is acknowledged; a conflicting record id is a
    /// deterministic rejection; absence remains indeterminate and is never
    /// interpreted as permission to replay a physical run.
    pub fn reconcile(
        &mut self,
        ledger: &LedgerWriter,
    ) -> Result<usize, IntelligenceLearningOutboxErrorV1> {
        let records = ledger.records()?;
        self.reconcile_records(&records)
    }

    pub fn reconcile_records(
        &mut self,
        records: &[LedgerRecord],
    ) -> Result<usize, IntelligenceLearningOutboxErrorV1> {
        let mut changed = 0usize;
        let unresolved = self
            .records
            .values()
            .filter(|record| {
                matches!(
                    record.state,
                    IntelligenceLearningAppendStateV1::Prepared
                        | IntelligenceLearningAppendStateV1::Indeterminate
                )
            })
            .map(|record| record.operation_id.clone())
            .collect::<Vec<_>>();
        for operation_id in unresolved {
            let record_id = self
                .records
                .get(&operation_id)
                .ok_or(IntelligenceLearningOutboxErrorV1::Missing)?
                .record_id
                .clone();
            let observed = records
                .iter()
                .find(|record| record.event.record_id().as_str() == record_id);
            match observed {
                Some(record) => {
                    let expected = parse_digest(
                        &self
                            .records
                            .get(&operation_id)
                            .ok_or(IntelligenceLearningOutboxErrorV1::Missing)?
                            .semantic_digest,
                    )?;
                    if durable_event_semantic_digest(&record.event) == Some(expected) {
                        self.transition_observed(
                            &operation_id,
                            IntelligenceLearningAppendStateV1::Acknowledged,
                            Some(record.sequence.get()),
                            Some(record.event_digest),
                            Some(record.chain_digest),
                            None,
                        )?;
                    } else {
                        self.transition_observed(
                            &operation_id,
                            IntelligenceLearningAppendStateV1::Rejected,
                            Some(record.sequence.get()),
                            Some(record.event_digest),
                            Some(record.chain_digest),
                            Some(reason_digest("record identity conflict")?),
                        )?;
                    }
                    changed = changed
                        .checked_add(1)
                        .ok_or(IntelligenceLearningOutboxErrorV1::Capacity)?;
                }
                None => {
                    let state = self
                        .records
                        .get(&operation_id)
                        .ok_or(IntelligenceLearningOutboxErrorV1::Missing)?
                        .state;
                    if state == IntelligenceLearningAppendStateV1::Prepared {
                        self.transition_observed(
                            &operation_id,
                            IntelligenceLearningAppendStateV1::Indeterminate,
                            None,
                            None,
                            None,
                            Some(reason_digest("record absent after process recovery")?),
                        )?;
                        changed = changed
                            .checked_add(1)
                            .ok_or(IntelligenceLearningOutboxErrorV1::Capacity)?;
                    }
                }
            }
        }
        Ok(changed)
    }

    #[allow(clippy::too_many_arguments)]
    fn transition_observed(
        &mut self,
        operation_id: &str,
        next: IntelligenceLearningAppendStateV1,
        sequence: Option<u64>,
        event_digest: Option<Digest32>,
        chain_digest: Option<Digest32>,
        reason_digest: Option<Digest32>,
    ) -> Result<IntelligenceLearningIntentV1, IntelligenceLearningOutboxErrorV1> {
        let current = self
            .records
            .get_mut(operation_id)
            .ok_or(IntelligenceLearningOutboxErrorV1::Missing)?;
        if current.state.terminal() {
            if current.state == next
                && current.observed_sequence == sequence
                && current.observed_event_digest.as_deref()
                    == event_digest.as_ref().map(ToString::to_string).as_deref()
                && current.observed_chain_digest.as_deref()
                    == chain_digest.as_ref().map(ToString::to_string).as_deref()
            {
                return Ok(current.clone());
            }
            return Err(IntelligenceLearningOutboxErrorV1::Conflict);
        }
        current.state = next;
        current.revision = current
            .revision
            .checked_add(1)
            .ok_or(IntelligenceLearningOutboxErrorV1::Capacity)?;
        current.observed_sequence = sequence;
        current.observed_event_digest = event_digest.map(|value| value.to_string());
        current.observed_chain_digest = chain_digest.map(|value| value.to_string());
        current.reason_digest = reason_digest.map(|value| value.to_string());
        current.validate()?;
        let result = current.clone();
        self.persist()?;
        Ok(result)
    }

    fn persist(&mut self) -> Result<(), IntelligenceLearningOutboxErrorV1> {
        let file = IntelligenceLearningOutboxFileV1 {
            schema_version: OUTBOX_SCHEMA_VERSION,
            records: self.records.values().cloned().collect(),
        };
        let bytes = serde_json::to_vec(&file)?;
        if bytes.is_empty() || bytes.len() as u64 > MAX_OUTBOX_BYTES {
            return Err(IntelligenceLearningOutboxErrorV1::Capacity);
        }
        let parent = self
            .path
            .parent()
            .ok_or(IntelligenceLearningOutboxErrorV1::Invalid("outbox parent"))?;
        let file_name = self
            .path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or(IntelligenceLearningOutboxErrorV1::Invalid("outbox filename"))?;
        let temporary = parent.join(format!(".{file_name}.{}.tmp", std::process::id()));
        if temporary.exists() {
            let metadata = std::fs::symlink_metadata(&temporary)?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(IntelligenceLearningOutboxErrorV1::Invalid(
                    "unsafe temporary outbox",
                ));
            }
            std::fs::remove_file(&temporary)?;
        }
        let mut output = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        output.write_all(&bytes)?;
        output.sync_all()?;
        std::fs::rename(&temporary, &self.path)?;
        sync_parent(parent)?;
        Ok(())
    }
}

#[derive(Debug, thiserror::Error)]
pub enum IntelligenceLearningOutboxErrorV1 {
    #[error("invalid intelligence learning outbox: {0}")]
    Invalid(&'static str),
    #[error("intelligence learning outbox conflict")]
    Conflict,
    #[error("intelligence learning outbox capacity exceeded")]
    Capacity,
    #[error("intelligence learning outbox record is missing")]
    Missing,
    #[error("intelligence learning outbox I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("intelligence learning outbox JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("intelligence learning ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
}

pub(crate) fn signed_learning_evidence_digest(
    evidence: &SignedLearningEvidenceV1,
) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}

pub(crate) fn production_decision_semantic_digest(
    request: &ProductionDecisionV2,
    authentication_digest: Digest32,
) -> Result<Digest32, ProductionLedgerError> {
    let completeness_digest = validate_candidate_set_completeness(&request.completeness)?;
    Ok(decision_semantic_digest_fields(
        &request.record_id,
        &request.episode_id,
        request.run_snapshot_digest,
        request.objective_digest,
        request.policy_digest,
        &request.candidate_ids,
        &request.selected_candidate_id,
        request.selected_propensity.raw(),
        completeness_digest,
        request.support_digest,
        authentication_digest,
    ))
}

pub(crate) fn production_outcome_semantic_digest(
    outcome: &AuthenticatedOutcomeV1,
    authentication_digest: Digest32,
) -> Digest32 {
    outcome_semantic_digest_fields(
        &outcome.record_id,
        &outcome.outcome_id,
        &outcome.episode_id,
        &outcome.observer.principal_id,
        &outcome.observer.controllerless_digest(),
        outcome.observed_at,
        outcome.value,
        outcome.unit_profile_digest,
        outcome.support_digest,
        outcome.watermark.latest_observable_at,
        outcome.watermark.expected_delay_profile_digest,
        match outcome.watermark.terminality {
            codex_hepta_learning_ledger::OutcomeTerminalityV1::Pending => 0,
            codex_hepta_learning_ledger::OutcomeTerminalityV1::Censored => 1,
            codex_hepta_learning_ledger::OutcomeTerminalityV1::Terminal => 2,
        },
        outcome.watermark.censoring_reason.as_ref(),
        outcome.watermark.correction_predecessor.as_ref(),
        outcome.watermark.finalized_at,
        authentication_digest,
    )
}

fn durable_event_semantic_digest(event: &LedgerEvent) -> Option<Digest32> {
    match event {
        LedgerEvent::AuthenticatedDecisionV2(value) => {
            Some(authenticated_decision_record_semantic_digest(value))
        }
        LedgerEvent::AuthenticatedOutcomeV2(value) => {
            Some(authenticated_outcome_record_semantic_digest(value))
        }
        _ => None,
    }
}

fn authenticated_decision_record_semantic_digest(
    value: &AuthenticatedDecisionRecordV2,
) -> Digest32 {
    decision_semantic_digest_fields(
        &value.record_id,
        &value.episode_id,
        value.run_snapshot_digest,
        value.objective_digest,
        value.policy_digest,
        &value.candidate_ids,
        &value.selected_candidate_id,
        value.selected_propensity.raw(),
        value.candidate_completeness_digest,
        value.support_digest,
        value.authentication_digest,
    )
}

fn authenticated_outcome_record_semantic_digest(
    value: &AuthenticatedOutcomeRecordV2,
) -> Digest32 {
    let mut principal_bytes = b"hepta.agentd.intelligence-outcome-principal.v1\0".to_vec();
    push_id(&mut principal_bytes, &value.observer_id);
    push_id(&mut principal_bytes, &value.observer_controller_id);
    principal_bytes.extend_from_slice(value.observer_credential_chain_digest.as_array());
    principal_bytes.extend_from_slice(value.observer_signing_key_digest.as_array());
    principal_bytes.extend_from_slice(value.observer_scope_digest.as_array());
    principal_bytes.extend_from_slice(&value.observer_authority_epoch.to_be_bytes());
    let principal_digest = Digest32::of_bytes(&principal_bytes);
    outcome_semantic_digest_fields(
        &value.record_id,
        &value.outcome_id,
        &value.episode_id,
        &value.observer_id,
        &principal_digest,
        value.observed_at,
        value.value,
        value.unit_profile_digest,
        value.support_digest,
        value.latest_observable_at,
        value.expected_delay_profile_digest,
        match value.terminality {
            AuthenticatedOutcomeTerminality::Pending => 0,
            AuthenticatedOutcomeTerminality::Censored => 1,
            AuthenticatedOutcomeTerminality::Terminal => 2,
        },
        value.censoring_reason.as_ref(),
        value.correction_predecessor.as_ref(),
        value.finalized_at,
        value.authentication_digest,
    )
}

#[allow(clippy::too_many_arguments)]
fn decision_semantic_digest_fields(
    record_id: &StableId,
    episode_id: &StableId,
    run_snapshot_digest: Digest32,
    objective_digest: Digest32,
    policy_digest: Digest32,
    candidate_ids: &[StableId],
    selected_candidate_id: &StableId,
    selected_propensity_raw: u64,
    completeness_digest: Digest32,
    support_digest: Digest32,
    authentication_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-decision-durable-semantics.v1\0".to_vec();
    push_id(&mut bytes, record_id);
    push_id(&mut bytes, episode_id);
    bytes.extend_from_slice(run_snapshot_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(candidate_ids_digest_v2(candidate_ids).as_array());
    push_id(&mut bytes, selected_candidate_id);
    bytes.extend_from_slice(&selected_propensity_raw.to_be_bytes());
    bytes.extend_from_slice(completeness_digest.as_array());
    bytes.extend_from_slice(support_digest.as_array());
    bytes.extend_from_slice(authentication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn outcome_semantic_digest_fields(
    record_id: &StableId,
    outcome_id: &StableId,
    episode_id: &StableId,
    observer_id: &StableId,
    observer_principal_digest: &Digest32,
    observed_at: Option<u64>,
    value: Option<FixedQ32>,
    unit_profile_digest: Digest32,
    support_digest: Digest32,
    latest_observable_at: u64,
    expected_delay_profile_digest: Digest32,
    terminality: u8,
    censoring_reason: Option<&StableId>,
    correction_predecessor: Option<&StableId>,
    finalized_at: Option<u64>,
    authentication_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-outcome-durable-semantics.v1\0".to_vec();
    push_id(&mut bytes, record_id);
    push_id(&mut bytes, outcome_id);
    push_id(&mut bytes, episode_id);
    push_id(&mut bytes, observer_id);
    bytes.extend_from_slice(observer_principal_digest.as_array());
    push_optional_u64(&mut bytes, observed_at);
    push_optional_fixed(&mut bytes, value);
    bytes.extend_from_slice(unit_profile_digest.as_array());
    bytes.extend_from_slice(support_digest.as_array());
    bytes.extend_from_slice(&latest_observable_at.to_be_bytes());
    bytes.extend_from_slice(expected_delay_profile_digest.as_array());
    bytes.push(terminality);
    push_optional_id(&mut bytes, censoring_reason);
    push_optional_id(&mut bytes, correction_predecessor);
    push_optional_u64(&mut bytes, finalized_at);
    bytes.extend_from_slice(authentication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn validate_outbox_path(path: &Path) -> Result<(), IntelligenceLearningOutboxErrorV1> {
    if !path.is_absolute() {
        return Err(IntelligenceLearningOutboxErrorV1::Invalid(
            "outbox path must be absolute",
        ));
    }
    let parent = path
        .parent()
        .ok_or(IntelligenceLearningOutboxErrorV1::Invalid("outbox parent"))?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(IntelligenceLearningOutboxErrorV1::Invalid(
            "unsafe outbox parent",
        ));
    }
    Ok(())
}

fn validate_existing_file(path: &Path) -> Result<(), IntelligenceLearningOutboxErrorV1> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(IntelligenceLearningOutboxErrorV1::Invalid(
            "unsafe outbox file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o022 != 0 {
            return Err(IntelligenceLearningOutboxErrorV1::Invalid(
                "group/world-writable outbox",
            ));
        }
    }
    Ok(())
}

#[cfg(unix)]
fn sync_parent(parent: &Path) -> Result<(), std::io::Error> {
    File::open(parent)?.sync_all()
}

#[cfg(not(unix))]
fn sync_parent(_parent: &Path) -> Result<(), std::io::Error> {
    Ok(())
}

fn parse_digest(value: &str) -> Result<Digest32, IntelligenceLearningOutboxErrorV1> {
    Digest32::from_str(value)
        .filter(|digest| !digest.is_zero())
        .map_err(|_| IntelligenceLearningOutboxErrorV1::Invalid("digest"))
}

fn reason_digest(reason: &str) -> Result<Digest32, IntelligenceLearningOutboxErrorV1> {
    if reason.trim().is_empty() || reason.len() > MAX_REASON_BYTES || reason.as_bytes().contains(&0)
    {
        return Err(IntelligenceLearningOutboxErrorV1::Invalid("reason"));
    }
    Ok(Digest32::of_bytes(reason.as_bytes()))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

fn push_optional_fixed(bytes: &mut Vec<u8>, value: Option<FixedQ32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
}

trait ObserverPrincipalDigestV1 {
    fn controllerless_digest(&self) -> Digest32;
}

impl ObserverPrincipalDigestV1 for codex_hepta_learning_ledger::AuthenticatedPrincipalV1 {
    fn controllerless_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.intelligence-outcome-principal.v1\0".to_vec();
        push_id(&mut bytes, &self.principal_id);
        // The controller id is supplied by authenticated evidence and is not in
        // the asserted principal. The authentication digest below closes that
        // identity; durable reconciliation compares the full stored principal.
        push_id(
            &mut bytes,
            &StableId::new("controller.from.evidence").expect("static id"),
        );
        bytes.extend_from_slice(self.credential_chain_digest.as_array());
        bytes.extend_from_slice(self.signing_key_digest.as_array());
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn intent() -> IntelligenceLearningIntentV1 {
        IntelligenceLearningIntentV1::new(
            IntelligenceLearningAppendKindV1::Decision,
            &id("run.1"),
            &id("run.1"),
            &id("episode.1"),
            digest("predecessor"),
            digest("snapshot"),
            digest("objective"),
            digest("support"),
            digest("semantics"),
            digest("authentication"),
            7,
            42,
            &digest("fence").to_string(),
        )
        .unwrap()
    }

    #[test]
    fn prepared_intent_survives_process_reopen_and_absence_becomes_indeterminate() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("intelligence-learning-outbox.json");
        let operation_id = {
            let mut outbox = DurableIntelligenceLearningOutboxV1::open(path.clone()).unwrap();
            let intent = outbox.prepare(intent()).unwrap();
            assert_eq!(outbox.backlog(), 1);
            intent.operation_id
        };
        let mut reopened = DurableIntelligenceLearningOutboxV1::open(path).unwrap();
        assert_eq!(reopened.backlog(), 1);
        assert_eq!(reopened.reconcile_records(&[]).unwrap(), 1);
        assert_eq!(
            reopened.record(&operation_id).unwrap().state,
            IntelligenceLearningAppendStateV1::Indeterminate
        );
    }

    #[test]
    fn terminal_state_is_idempotent_but_semantic_reuse_conflicts() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("intelligence-learning-outbox.json");
        let mut outbox = DurableIntelligenceLearningOutboxV1::open(path).unwrap();
        let prepared = outbox.prepare(intent()).unwrap();
        let receipt = AppendReceipt {
            disposition: codex_hepta_learning_ledger::AppendDisposition::Appended,
            sequence: codex_hepta_types::LogicalSequence::new(1).unwrap(),
            event_digest: digest("event"),
            chain_digest: digest("chain"),
        };
        let first = outbox.acknowledge(&prepared.operation_id, &receipt).unwrap();
        let repeated = outbox.acknowledge(&prepared.operation_id, &receipt).unwrap();
        assert_eq!(first, repeated);
        let mut changed = intent();
        changed.support_digest = digest("different-support").to_string();
        assert_eq!(
            outbox.prepare(changed).unwrap_err().to_string(),
            IntelligenceLearningOutboxErrorV1::Conflict.to_string()
        );
    }
}