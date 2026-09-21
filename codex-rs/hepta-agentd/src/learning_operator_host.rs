//! Product-side offline/shadow learning.operator composition.
//!
//! This host deliberately separates candidate generation from independent
//! selection. It may reproduce a frozen dataset, train one deny-all tabular
//! candidate, publish immutable bytes through learning.artifacts, and verify
//! signed independent evaluation. It cannot create a Selected lifecycle event.
//! A later host may load the candidate only after observing an externally
//! authenticated Selector transition in the artifact-owner lifecycle journal.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::sync::Arc;

use codex_hepta_bellman_operator::OperatorDatasetBindingError;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularPayloadError;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_bellman_operator::VerifiedOperatorDatasetV2;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_bound_v2;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence::EvaluatedShadowError;
use codex_hepta_intelligence::evaluated_candidate_signing_payload_v1;
use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::SignedEvaluationError;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactLifecycleEventV1;
use codex_hepta_learning_artifacts::ArtifactLifecycleJournalError;
use codex_hepta_learning_artifacts::ArtifactLifecycleJournalV2;
use codex_hepta_learning_artifacts::ArtifactLifecycleStateV1;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::ArtifactRegistryError;
use codex_hepta_learning_artifacts::ArtifactStorageError;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::LifecycleActorEvidenceV2;
use codex_hepta_learning_artifacts::LifecycleActorRoleV2;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::read_candidate_payload;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CurrentCognitiveRegistry;
use crate::PinnedCognitiveRanker;

const JOURNAL_MAGIC: &[u8; 8] = b"HEPTOP01";
const JOURNAL_DOMAIN: &[u8] = b"hepta.agentd.offline-operator-journal.v1";
const MAX_JOURNAL_BYTES: u64 = 4 * 1024 * 1024;
const MAX_JOURNAL_RECORDS: usize = 4_096;
const MAX_FRAME_BYTES: usize = 512;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OfflineOperatorPhaseV1 {
    Prepared,
    Trained,
    Published,
    EvaluatedEligible,
    EvaluatedRejected,
    SelectionObserved,
    Reloaded,
}

impl OfflineOperatorPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::Trained => 1,
            Self::Published => 2,
            Self::EvaluatedEligible => 3,
            Self::EvaluatedRejected => 4,
            Self::SelectionObserved => 5,
            Self::Reloaded => 6,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, OfflineOperatorJournalError> {
        match tag {
            0 => Ok(Self::Prepared),
            1 => Ok(Self::Trained),
            2 => Ok(Self::Published),
            3 => Ok(Self::EvaluatedEligible),
            4 => Ok(Self::EvaluatedRejected),
            5 => Ok(Self::SelectionObserved),
            6 => Ok(Self::Reloaded),
            _ => Err(OfflineOperatorJournalError::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OfflineOperatorJournalRecordV1 {
    pub sequence: u64,
    pub operation_id: StableId,
    pub phase: OfflineOperatorPhaseV1,
    pub request_digest: Digest32,
    pub stage_digest: Digest32,
    pub predecessor_chain_digest: Digest32,
    pub chain_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OfflineOperatorJournalDispositionV1 {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OfflineOperatorJournalReceiptV1 {
    pub disposition: OfflineOperatorJournalDispositionV1,
    pub sequence: u64,
    pub phase: OfflineOperatorPhaseV1,
    pub request_digest: Digest32,
    pub stage_digest: Digest32,
    pub head_digest: Digest32,
}

/// Durable coordination only. Ledger/artifact/evaluation truth remains with the
/// existing owners; this journal stores phase bindings needed to reconcile a
/// crash without inventing a selection or repeating changed semantics.
pub struct OfflineOperatorJournalV1 {
    file: File,
    records: Vec<OfflineOperatorJournalRecordV1>,
    head_digest: Digest32,
    poisoned: bool,
}

impl fmt::Debug for OfflineOperatorJournalV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OfflineOperatorJournalV1")
            .field("records", &self.records)
            .field("head_digest", &self.head_digest)
            .field("poisoned", &self.poisoned)
            .finish_non_exhaustive()
    }
}

impl Drop for OfflineOperatorJournalV1 {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

impl OfflineOperatorJournalV1 {
    /// Open an already host-authorized regular file and retain the exclusive
    /// writer lock for the journal lifetime. The caller owns directory
    /// creation, ACLs and containing-directory durability.
    pub fn open(mut file: File) -> Result<Self, OfflineOperatorJournalError> {
        if !file.metadata()?.is_file() {
            return Err(OfflineOperatorJournalError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(OfflineOperatorJournalError::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }
        let length = file.metadata()?.len();
        if length > MAX_JOURNAL_BYTES {
            return Err(OfflineOperatorJournalError::Capacity);
        }
        if length == 0 {
            file.write_all(JOURNAL_MAGIC)
                .and_then(|()| file.sync_all())
                .map_err(|_| OfflineOperatorJournalError::Indeterminate)?;
        }
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_JOURNAL_BYTES + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_JOURNAL_BYTES || !bytes.starts_with(JOURNAL_MAGIC) {
            return Err(OfflineOperatorJournalError::Corrupt);
        }
        let records = decode_records(&bytes[JOURNAL_MAGIC.len()..])?;
        let head_digest = records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        file.seek(SeekFrom::End(0))?;
        Ok(Self {
            file,
            records,
            head_digest,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn records(&self) -> &[OfflineOperatorJournalRecordV1] {
        &self.records
    }

    #[must_use]
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    pub fn prepare(
        &mut self,
        operation_id: StableId,
        request_digest: Digest32,
    ) -> Result<OfflineOperatorJournalReceiptV1, OfflineOperatorJournalError> {
        if request_digest.is_zero() {
            return Err(OfflineOperatorJournalError::InvalidDigest);
        }
        if let Some(existing) = self.last_for(&operation_id).cloned() {
            if existing.request_digest != request_digest {
                return Err(OfflineOperatorJournalError::OperationConflict);
            }
            let prepared = self
                .record_for_phase(&operation_id, OfflineOperatorPhaseV1::Prepared)
                .ok_or(OfflineOperatorJournalError::Corrupt)?;
            return Ok(self.replay_receipt(prepared));
        }
        self.append_record(
            operation_id,
            OfflineOperatorPhaseV1::Prepared,
            request_digest,
            request_digest,
        )
    }

    pub fn advance(
        &mut self,
        operation_id: &StableId,
        request_digest: Digest32,
        phase: OfflineOperatorPhaseV1,
        stage_digest: Digest32,
    ) -> Result<OfflineOperatorJournalReceiptV1, OfflineOperatorJournalError> {
        if request_digest.is_zero() || stage_digest.is_zero() {
            return Err(OfflineOperatorJournalError::InvalidDigest);
        }
        let Some(existing) = self.last_for(operation_id).cloned() else {
            return Err(OfflineOperatorJournalError::InvalidTransition);
        };
        if existing.request_digest != request_digest {
            return Err(OfflineOperatorJournalError::OperationConflict);
        }
        if let Some(record) = self.record_for_phase(operation_id, phase) {
            if record.request_digest != request_digest || record.stage_digest != stage_digest {
                return Err(OfflineOperatorJournalError::OperationConflict);
            }
            return Ok(self.replay_receipt(record));
        }
        if !allowed_phase_transition(existing.phase, phase) {
            return Err(OfflineOperatorJournalError::InvalidTransition);
        }
        self.append_record(operation_id.clone(), phase, request_digest, stage_digest)
    }

    fn last_for(&self, operation_id: &StableId) -> Option<&OfflineOperatorJournalRecordV1> {
        self.records
            .iter()
            .rev()
            .find(|record| &record.operation_id == operation_id)
    }

    fn record_for_phase(
        &self,
        operation_id: &StableId,
        phase: OfflineOperatorPhaseV1,
    ) -> Option<&OfflineOperatorJournalRecordV1> {
        self.records
            .iter()
            .find(|record| &record.operation_id == operation_id && record.phase == phase)
    }

    fn replay_receipt(
        &self,
        record: &OfflineOperatorJournalRecordV1,
    ) -> OfflineOperatorJournalReceiptV1 {
        OfflineOperatorJournalReceiptV1 {
            disposition: OfflineOperatorJournalDispositionV1::IdempotentReplay,
            sequence: record.sequence,
            phase: record.phase,
            request_digest: record.request_digest,
            stage_digest: record.stage_digest,
            head_digest: self.head_digest,
        }
    }

    fn append_record(
        &mut self,
        operation_id: StableId,
        phase: OfflineOperatorPhaseV1,
        request_digest: Digest32,
        stage_digest: Digest32,
    ) -> Result<OfflineOperatorJournalReceiptV1, OfflineOperatorJournalError> {
        if self.poisoned {
            return Err(OfflineOperatorJournalError::Poisoned);
        }
        if self.records.len() >= MAX_JOURNAL_RECORDS {
            return Err(OfflineOperatorJournalError::Capacity);
        }
        let sequence = u64::try_from(self.records.len())
            .map_err(|_| OfflineOperatorJournalError::Capacity)?
            .checked_add(1)
            .ok_or(OfflineOperatorJournalError::Capacity)?;
        let predecessor_chain_digest = self.head_digest;
        let chain_digest = digest_record(
            sequence,
            &operation_id,
            phase,
            request_digest,
            stage_digest,
            predecessor_chain_digest,
        );
        let record = OfflineOperatorJournalRecordV1 {
            sequence,
            operation_id,
            phase,
            request_digest,
            stage_digest,
            predecessor_chain_digest,
            chain_digest,
        };
        let frame = encode_record(&record)?;
        if self
            .file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(OfflineOperatorJournalError::Indeterminate);
        }
        self.head_digest = record.chain_digest;
        self.records.push(record.clone());
        Ok(OfflineOperatorJournalReceiptV1 {
            disposition: OfflineOperatorJournalDispositionV1::Appended,
            sequence,
            phase,
            request_digest,
            stage_digest,
            head_digest: self.head_digest,
        })
    }
}

const fn allowed_phase_transition(
    current: OfflineOperatorPhaseV1,
    next: OfflineOperatorPhaseV1,
) -> bool {
    matches!(
        (current, next),
        (
            OfflineOperatorPhaseV1::Prepared,
            OfflineOperatorPhaseV1::Trained
        ) | (
            OfflineOperatorPhaseV1::Trained,
            OfflineOperatorPhaseV1::Published
        ) | (
            OfflineOperatorPhaseV1::Published,
            OfflineOperatorPhaseV1::EvaluatedEligible
        ) | (
            OfflineOperatorPhaseV1::Published,
            OfflineOperatorPhaseV1::EvaluatedRejected
        ) | (
            OfflineOperatorPhaseV1::EvaluatedEligible,
            OfflineOperatorPhaseV1::SelectionObserved
        ) | (
            OfflineOperatorPhaseV1::SelectionObserved,
            OfflineOperatorPhaseV1::Reloaded
        )
    )
}

fn encode_record(
    record: &OfflineOperatorJournalRecordV1,
) -> Result<Vec<u8>, OfflineOperatorJournalError> {
    let id = record.operation_id.as_str().as_bytes();
    let id_len = u16::try_from(id.len()).map_err(|_| OfflineOperatorJournalError::Capacity)?;
    let mut body = Vec::with_capacity(8 + 1 + 2 + id.len() + 32 * 4);
    body.extend_from_slice(&record.sequence.to_be_bytes());
    body.push(record.phase.tag());
    body.extend_from_slice(&id_len.to_be_bytes());
    body.extend_from_slice(id);
    body.extend_from_slice(record.request_digest.as_array());
    body.extend_from_slice(record.stage_digest.as_array());
    body.extend_from_slice(record.predecessor_chain_digest.as_array());
    body.extend_from_slice(record.chain_digest.as_array());
    if body.len() > MAX_FRAME_BYTES {
        return Err(OfflineOperatorJournalError::Capacity);
    }
    let mut frame = Vec::with_capacity(4 + body.len());
    frame.extend_from_slice(
        &u32::try_from(body.len())
            .map_err(|_| OfflineOperatorJournalError::Capacity)?
            .to_be_bytes(),
    );
    frame.extend_from_slice(&body);
    Ok(frame)
}

fn decode_records(
    bytes: &[u8],
) -> Result<Vec<OfflineOperatorJournalRecordV1>, OfflineOperatorJournalError> {
    let mut offset = 0_usize;
    let mut records = Vec::new();
    let mut expected_predecessor = Digest32::ZERO;
    while offset < bytes.len() {
        if records.len() >= MAX_JOURNAL_RECORDS || bytes.len() - offset < 4 {
            return Err(OfflineOperatorJournalError::Corrupt);
        }
        let length = u32::from_be_bytes(
            bytes[offset..offset + 4]
                .try_into()
                .map_err(|_| OfflineOperatorJournalError::Corrupt)?,
        ) as usize;
        offset += 4;
        if length == 0 || length > MAX_FRAME_BYTES || bytes.len() - offset < length {
            return Err(OfflineOperatorJournalError::Corrupt);
        }
        let body = &bytes[offset..offset + length];
        offset += length;
        let record = decode_record(body)?;
        let expected_sequence = u64::try_from(records.len())
            .map_err(|_| OfflineOperatorJournalError::Capacity)?
            .checked_add(1)
            .ok_or(OfflineOperatorJournalError::Capacity)?;
        if record.sequence != expected_sequence
            || record.predecessor_chain_digest != expected_predecessor
            || record.chain_digest
                != digest_record(
                    record.sequence,
                    &record.operation_id,
                    record.phase,
                    record.request_digest,
                    record.stage_digest,
                    record.predecessor_chain_digest,
                )
        {
            return Err(OfflineOperatorJournalError::Corrupt);
        }
        if let Some(previous) = records
            .iter()
            .rev()
            .find(|previous| previous.operation_id == record.operation_id)
        {
            if previous.request_digest != record.request_digest
                || !allowed_phase_transition(previous.phase, record.phase)
            {
                return Err(OfflineOperatorJournalError::Corrupt);
            }
        } else if record.phase != OfflineOperatorPhaseV1::Prepared {
            return Err(OfflineOperatorJournalError::Corrupt);
        }
        expected_predecessor = record.chain_digest;
        records.push(record);
    }
    Ok(records)
}

fn decode_record(
    body: &[u8],
) -> Result<OfflineOperatorJournalRecordV1, OfflineOperatorJournalError> {
    const FIXED_WITHOUT_ID: usize = 8 + 1 + 2 + 32 * 4;
    if body.len() < FIXED_WITHOUT_ID {
        return Err(OfflineOperatorJournalError::Corrupt);
    }
    let sequence = u64::from_be_bytes(
        body[0..8]
            .try_into()
            .map_err(|_| OfflineOperatorJournalError::Corrupt)?,
    );
    let phase = OfflineOperatorPhaseV1::from_tag(body[8])?;
    let id_len = u16::from_be_bytes(
        body[9..11]
            .try_into()
            .map_err(|_| OfflineOperatorJournalError::Corrupt)?,
    ) as usize;
    let expected = FIXED_WITHOUT_ID
        .checked_add(id_len)
        .ok_or(OfflineOperatorJournalError::Corrupt)?;
    if body.len() != expected {
        return Err(OfflineOperatorJournalError::Corrupt);
    }
    let mut cursor = 11_usize;
    let operation_id = StableId::new(
        std::str::from_utf8(&body[cursor..cursor + id_len])
            .map_err(|_| OfflineOperatorJournalError::Corrupt)?
            .to_owned(),
    )
    .map_err(|_| OfflineOperatorJournalError::Corrupt)?;
    cursor += id_len;
    let request_digest = take_digest(body, &mut cursor)?;
    let stage_digest = take_digest(body, &mut cursor)?;
    let predecessor_chain_digest = take_digest(body, &mut cursor)?;
    let chain_digest = take_digest(body, &mut cursor)?;
    Ok(OfflineOperatorJournalRecordV1 {
        sequence,
        operation_id,
        phase,
        request_digest,
        stage_digest,
        predecessor_chain_digest,
        chain_digest,
    })
}

fn take_digest(bytes: &[u8], cursor: &mut usize) -> Result<Digest32, OfflineOperatorJournalError> {
    let end = cursor
        .checked_add(32)
        .ok_or(OfflineOperatorJournalError::Corrupt)?;
    let raw: [u8; 32] = bytes
        .get(*cursor..end)
        .ok_or(OfflineOperatorJournalError::Corrupt)?
        .try_into()
        .map_err(|_| OfflineOperatorJournalError::Corrupt)?;
    *cursor = end;
    Ok(Digest32::from_array(raw))
}

fn digest_record(
    sequence: u64,
    operation_id: &StableId,
    phase: OfflineOperatorPhaseV1,
    request_digest: Digest32,
    stage_digest: Digest32,
    predecessor_chain_digest: Digest32,
) -> Digest32 {
    let mut bytes = JOURNAL_DOMAIN.to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    let raw = operation_id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
    bytes.push(phase.tag());
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(stage_digest.as_array());
    bytes.extend_from_slice(predecessor_chain_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OfflineOperatorJournalError {
    Busy,
    NotRegular,
    Capacity,
    Corrupt,
    InvalidDigest,
    InvalidTransition,
    OperationConflict,
    Poisoned,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for OfflineOperatorJournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OfflineOperatorJournalError {}

impl From<io::Error> for OfflineOperatorJournalError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

pub enum OfflineOperatorPayloadTargetV1 {
    Create(CreateOnlyArtifactFile),
    Existing(File),
}

pub struct OfflineOperatorCandidateRequestV1<'a> {
    pub operation_id: StableId,
    pub dataset: &'a DatasetSnapshotReceiptV3,
    pub plan: TabularOperatorPlanV1,
    pub register_event_id: StableId,
    pub trained_lifecycle_event_id: StableId,
    pub evaluated_lifecycle_event_id: StableId,
    pub producer_actor: LifecycleActorEvidenceV2,
    pub evaluator_actor: LifecycleActorEvidenceV2,
    pub manifest: ArtifactManifest,
    pub payload_target: OfflineOperatorPayloadTargetV1,
    pub registry_snapshot_target: CreateOnlyArtifactFile,
    pub registry_binding: Digest32,
    pub evaluation: IndependentEvaluationBundleV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub evaluation_evidence: &'a SignedEvaluationEvidenceV1,
    pub candidate_evidence: &'a SignedLearningEvidenceV1,
    pub now: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OfflineOperatorCandidateReceiptV1 {
    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub model: TabularOperatorArtifactV1,
    pub model_pin: TabularPayloadPinV1,
    pub selected_spec: PinnedCandidateSpec,
    pub evaluation: SignedEvaluationDecisionV1,
    pub publication_digest: Digest32,
    pub coordination_head_digest: Digest32,
}

/// Named Agentd product caller for the offline/shadow operator path.
///
/// The host owns only a durable coordination journal. It delegates dataset
/// truth, candidate storage, evaluation and lifecycle selection to their
/// existing owners and returns only DENY_ALL model/evidence objects.
pub struct AgentdOfflineOperatorHostV1 {
    owner: AgentId,
    body_generation: u64,
    journal: OfflineOperatorJournalV1,
}

impl AgentdOfflineOperatorHostV1 {
    pub fn new(
        owner: AgentId,
        body_generation: u64,
        journal: OfflineOperatorJournalV1,
    ) -> Result<Self, LearningOperatorHostError> {
        if body_generation == 0 {
            return Err(LearningOperatorHostError::Binding(
                "body generation must be non-zero",
            ));
        }
        Ok(Self {
            owner,
            body_generation,
            journal,
        })
    }

    #[must_use]
    pub fn coordination_head_digest(&self) -> Digest32 {
        self.journal.head_digest()
    }

    #[must_use]
    pub fn coordination_records(&self) -> &[OfflineOperatorJournalRecordV1] {
        self.journal.records()
    }

    pub fn train_evaluate_publish(
        &mut self,
        registry: &mut ArtifactRegistry,
        lifecycle: &mut ArtifactLifecycleJournalV2,
        verifier: &LearningEvidenceVerifierV1,
        request: OfflineOperatorCandidateRequestV1<'_>,
    ) -> Result<OfflineOperatorCandidateReceiptV1, LearningOperatorHostError> {
        let dataset = VerifiedOperatorDatasetV2::from_receipt(request.dataset, request.now)?;
        let request_digest = digest_product_request(&request)?;
        self.journal
            .prepare(request.operation_id.clone(), request_digest)?;

        let model = fit_tabular_operator_bound_v2(&dataset, request.plan)?;
        let bytes = encode_tabular_payload_v1(&model)?;
        let model_pin = TabularPayloadPinV1 {
            payload_digest: Digest32::of_bytes(&bytes),
            artifact_digest: model.artifact_digest,
            objective_digest: model.objective_digest,
            dataset_digest: model.dataset_digest,
            sensor_core_digest: model.sensor_core_digest,
            training_profile_digest: model.training_profile_digest,
            generation: model.generation,
        };
        validate_manifest_binding(&request.manifest, &model, &model_pin, bytes.len())?;
        let trained_digest = digest_trained(&model_pin);
        self.journal.advance(
            &request.operation_id,
            request_digest,
            OfflineOperatorPhaseV1::Trained,
            trained_digest,
        )?;

        authenticate_candidate_bytes(
            verifier,
            &request.evaluation,
            &request.metric_roles,
            &bytes,
            model.generation.get(),
            request.candidate_evidence,
            request.now,
        )?;

        let mut staged_registry = registry.clone();
        let register_receipt = staged_registry.append(ArtifactEvent::Register {
            event_id: request.register_event_id,
            manifest: request.manifest.clone(),
        })?;
        persist_or_reconcile_payload(
            request.payload_target,
            &staged_registry,
            &request.manifest.artifact_id,
            &bytes,
        )?;
        let snapshot_receipt = write_registry_snapshot(
            request.registry_snapshot_target,
            &staged_registry,
            request.registry_binding,
        )?;
        let publication_digest = digest_publication(
            register_receipt.event_digest,
            &snapshot_receipt,
            model_pin.payload_digest,
        );
        if request.producer_actor.role != LifecycleActorRoleV2::Producer
            || request.producer_actor.actor_id != model.producer_id
        {
            return Err(LearningOperatorHostError::Binding(
                "producer lifecycle actor does not identify the trainer",
            ));
        }
        let (trained_event_digest, trained_chain_digest) = ensure_lifecycle_event(
            lifecycle,
            &model.producer_id,
            request.producer_actor.clone(),
            ArtifactLifecycleEventV1 {
                event_id: request.trained_lifecycle_event_id.clone(),
                artifact_id: model.artifact_id.clone(),
                prior_state: ArtifactLifecycleStateV1::Proposed,
                next_state: ArtifactLifecycleStateV1::Trained,
                actor_id: request.producer_actor.actor_id.clone(),
                actor_credential_digest: request.producer_actor.credential_digest,
                evidence_digest: publication_digest,
                authority_epoch: request.producer_actor.authority_epoch,
                occurred_at: request.now,
            },
            request.now,
        )?;
        *registry = staged_registry;
        let published_stage_digest = Digest32::of_parts(&[
            publication_digest.as_array(),
            trained_event_digest.as_array(),
            trained_chain_digest.as_array(),
        ]);
        self.journal.advance(
            &request.operation_id,
            request_digest,
            OfflineOperatorPhaseV1::Published,
            published_stage_digest,
        )?;

        if request.evaluation.candidate_id != model.artifact_id
            || request.evaluation.objective_digest != model.objective_digest
            || request.evaluation.dataset_digest != model.dataset_digest
        {
            return Err(LearningOperatorHostError::Binding(
                "evaluation does not identify the trained candidate",
            ));
        }
        if request.evaluator_actor.role != LifecycleActorRoleV2::Evaluator
            || request.evaluator_actor.actor_id
                != request.evaluation_evidence.evaluator_bundle.principal_id
            || request.evaluator_actor.actor_id == model.producer_id
            || request.evaluator_actor.actor_id != request.evaluation.evaluator.principal_id
            || request.evaluator_actor.credential_digest
                != request.evaluation.evaluator.credential_chain_digest
            || request.evaluator_actor.authority_epoch
                != request.evaluation.evaluator.authority_epoch
        {
            return Err(LearningOperatorHostError::Binding(
                "evaluator lifecycle actor does not match signed evaluator",
            ));
        }
        let evaluation = decide_with_signed_evidence_v2(
            request.evaluation,
            request.metric_roles,
            request.evaluation_evidence,
            verifier,
            request.now,
        )?;
        let evaluation_digest = digest_evaluation_decision(&evaluation);
        let (evaluated_event_digest, evaluated_chain_digest) = ensure_lifecycle_event(
            lifecycle,
            &model.producer_id,
            request.evaluator_actor.clone(),
            ArtifactLifecycleEventV1 {
                event_id: request.evaluated_lifecycle_event_id.clone(),
                artifact_id: model.artifact_id.clone(),
                prior_state: ArtifactLifecycleStateV1::Trained,
                next_state: ArtifactLifecycleStateV1::Evaluated,
                actor_id: request.evaluator_actor.actor_id.clone(),
                actor_credential_digest: request.evaluator_actor.credential_digest,
                evidence_digest: evaluation.decision.evidence_digest,
                authority_epoch: request.evaluator_actor.authority_epoch,
                occurred_at: request.now,
            },
            request.now,
        )?;
        let evaluated_stage_digest = Digest32::of_parts(&[
            evaluation_digest.as_array(),
            evaluated_event_digest.as_array(),
            evaluated_chain_digest.as_array(),
        ]);
        if evaluation.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            self.journal.advance(
                &request.operation_id,
                request_digest,
                OfflineOperatorPhaseV1::EvaluatedRejected,
                evaluated_stage_digest,
            )?;
            return Err(LearningOperatorHostError::EvaluationRejected(
                evaluation.decision.disposition,
            ));
        }
        let evaluated = self.journal.advance(
            &request.operation_id,
            request_digest,
            OfflineOperatorPhaseV1::EvaluatedEligible,
            evaluated_stage_digest,
        )?;

        Ok(OfflineOperatorCandidateReceiptV1 {
            operation_id: request.operation_id,
            request_digest,
            model,
            model_pin,
            selected_spec: PinnedCandidateSpec {
                registry_receipt: snapshot_receipt,
                manifest: request.manifest,
            },
            evaluation,
            publication_digest,
            coordination_head_digest: evaluated.head_digest,
        })
    }

    /// Observe an externally selected artifact and construct the launch-bound
    /// Agentd read consumer. No selection is inferred from evaluation success.
    #[allow(clippy::too_many_arguments)]
    pub fn load_selected_ranker(
        &mut self,
        candidate: &OfflineOperatorCandidateReceiptV1,
        lifecycle: &ArtifactLifecycleJournalV2,
        snapshot: File,
        payload: File,
        current: Arc<dyn CurrentCognitiveRegistry>,
    ) -> Result<PinnedCognitiveRanker, LearningOperatorHostError> {
        let last = lifecycle
            .records()
            .iter()
            .rev()
            .find(|record| record.event.artifact_id == candidate.model.artifact_id)
            .ok_or(LearningOperatorHostError::Selection(
                "artifact lifecycle contains no candidate state",
            ))?;
        if last.producer_id != candidate.selected_spec.manifest.producer_id
            || last.event.next_state != ArtifactLifecycleStateV1::Selected
            || last.actor.role != LifecycleActorRoleV2::Selector
            || last.event.evidence_digest != candidate.evaluation.decision.evidence_digest
            || last.actor.actor_id == last.producer_id
        {
            return Err(LearningOperatorHostError::Selection(
                "latest lifecycle state is not the independently selected evaluation",
            ));
        }
        let selection_digest = Digest32::of_parts(&[
            last.event_digest.as_array(),
            last.chain_digest.as_array(),
            candidate.evaluation.decision.evidence_digest.as_array(),
        ]);
        self.journal.advance(
            &candidate.operation_id,
            candidate.request_digest,
            OfflineOperatorPhaseV1::SelectionObserved,
            selection_digest,
        )?;

        let ranker = PinnedCognitiveRanker::load(
            self.owner.clone(),
            self.body_generation,
            snapshot,
            payload,
            candidate.selected_spec.clone(),
            candidate.model_pin.clone(),
            current,
        )
        .map_err(LearningOperatorHostError::Ranker)?;
        let reload_digest = Digest32::of_parts(&[
            selection_digest.as_array(),
            candidate.model_pin.artifact_digest.as_array(),
            candidate.model_pin.payload_digest.as_array(),
        ]);
        self.journal.advance(
            &candidate.operation_id,
            candidate.request_digest,
            OfflineOperatorPhaseV1::Reloaded,
            reload_digest,
        )?;
        Ok(ranker)
    }
}

fn digest_product_request(
    request: &OfflineOperatorCandidateRequestV1<'_>,
) -> Result<Digest32, LearningOperatorHostError> {
    let mut bytes = b"hepta.agentd.offline-operator-request.v1".to_vec();
    push_id(&mut bytes, &request.operation_id)?;
    bytes.extend_from_slice(request.dataset.snapshot.dataset_digest.as_array());
    bytes.extend_from_slice(request.dataset.snapshot.ledger_head_digest.as_array());
    push_id(&mut bytes, &request.plan.artifact_id)?;
    push_id(&mut bytes, &request.plan.producer_id)?;
    bytes.extend_from_slice(&request.plan.generation.get().to_be_bytes());
    for digest in [
        request.plan.objective_digest,
        request.plan.dataset_digest,
        request.plan.sensor_core_digest,
        request.plan.training_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(
        &u64::try_from(request.plan.minimum_samples_per_cell)
            .map_err(|_| LearningOperatorHostError::Binding("sample floor overflow"))?
            .to_be_bytes(),
    );
    let mut sensors = request.plan.sensor_ids.clone();
    sensors.sort();
    let mut actions = request.plan.action_ids.clone();
    actions.sort();
    for values in [&sensors, &actions] {
        bytes.extend_from_slice(
            &u32::try_from(values.len())
                .map_err(|_| LearningOperatorHostError::Binding("identifier count overflow"))?
                .to_be_bytes(),
        );
        for value in values {
            push_id(&mut bytes, value)?;
        }
    }
    let mut samples = request.plan.samples.clone();
    samples.sort_by_key(|sample| sample.sample_id.clone());
    bytes.extend_from_slice(
        &u32::try_from(samples.len())
            .map_err(|_| LearningOperatorHostError::Binding("sample count overflow"))?
            .to_be_bytes(),
    );
    for sample in samples {
        push_id(&mut bytes, &sample.sample_id)?;
        push_id(&mut bytes, &sample.sensor_id)?;
        push_id(&mut bytes, &sample.action_id)?;
        bytes.extend_from_slice(&sample.target.raw().to_be_bytes());
        bytes.extend_from_slice(sample.evidence_digest.as_array());
    }
    push_id(&mut bytes, &request.register_event_id)?;
    push_id(&mut bytes, &request.trained_lifecycle_event_id)?;
    push_id(&mut bytes, &request.evaluated_lifecycle_event_id)?;
    digest_lifecycle_actor(&mut bytes, &request.producer_actor)?;
    digest_lifecycle_actor(&mut bytes, &request.evaluator_actor)?;
    push_id(&mut bytes, &request.manifest.artifact_id)?;
    bytes.push(match request.manifest.kind {
        ArtifactKind::Prompt => 0,
        ArtifactKind::Policy => 1,
        ArtifactKind::Model => 2,
        ArtifactKind::Workflow => 3,
        ArtifactKind::Skill => 4,
        ArtifactKind::Parameters => 5,
        ArtifactKind::Topology => 6,
        ArtifactKind::Code => 7,
        ArtifactKind::ExternalAdapter => 8,
    });
    bytes.extend_from_slice(&request.manifest.generation.get().to_be_bytes());
    match &request.manifest.predecessor_id {
        Some(predecessor) => {
            bytes.push(1);
            push_id(&mut bytes, predecessor)?;
        }
        None => bytes.push(0),
    }
    for digest in [
        request.manifest.content_digest,
        request.manifest.objective_digest,
        request.manifest.support_digest,
        request.manifest.compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &request.manifest.producer_id)?;
    bytes.extend_from_slice(&request.manifest.encoded_size_bytes.to_be_bytes());
    bytes.extend_from_slice(request.registry_binding.as_array());
    let evaluation_payload =
        evaluation_signing_payload_v2(&request.evaluation, &request.metric_roles)
            .map_err(|_| LearningOperatorHostError::Binding("evaluation payload is invalid"))?;
    bytes.extend_from_slice(Digest32::of_bytes(&evaluation_payload).as_array());
    bytes.extend_from_slice(
        Digest32::of_bytes(&request.candidate_evidence.signing_bytes()).as_array(),
    );
    Ok(Digest32::of_bytes(&bytes))
}

fn persist_or_reconcile_payload(
    target: OfflineOperatorPayloadTargetV1,
    registry: &ArtifactRegistry,
    artifact_id: &StableId,
    expected_bytes: &[u8],
) -> Result<Digest32, LearningOperatorHostError> {
    match target {
        OfflineOperatorPayloadTargetV1::Create(file) => Ok(write_candidate_payload(
            file,
            registry,
            artifact_id,
            expected_bytes,
        )?),
        OfflineOperatorPayloadTargetV1::Existing(file) => {
            let observed = read_candidate_payload(file, registry, artifact_id)?;
            if observed != expected_bytes {
                return Err(LearningOperatorHostError::Binding(
                    "existing artifact payload differs from deterministic replay",
                ));
            }
            Ok(Digest32::of_bytes(&observed))
        }
    }
}

fn ensure_lifecycle_event(
    lifecycle: &mut ArtifactLifecycleJournalV2,
    producer_id: &StableId,
    actor: LifecycleActorEvidenceV2,
    event: ArtifactLifecycleEventV1,
    now: u64,
) -> Result<(Digest32, Digest32), LearningOperatorHostError> {
    if let Some(existing) = lifecycle
        .records()
        .iter()
        .find(|record| record.event.event_id == event.event_id)
    {
        if existing.producer_id != *producer_id
            || existing.actor != actor
            || existing.event != event
        {
            return Err(LearningOperatorHostError::Binding(
                "lifecycle event identity was reused with different semantics",
            ));
        }
        return Ok((existing.event_digest, existing.chain_digest));
    }
    let receipt = lifecycle.append(lifecycle.head_digest(), producer_id, actor, event, now)?;
    Ok((receipt.event_digest, receipt.head_digest))
}

fn digest_lifecycle_actor(
    bytes: &mut Vec<u8>,
    actor: &LifecycleActorEvidenceV2,
) -> Result<(), LearningOperatorHostError> {
    push_id(bytes, &actor.actor_id)?;
    bytes.extend_from_slice(actor.credential_digest.as_array());
    bytes.push(match actor.role {
        LifecycleActorRoleV2::Producer => 0,
        LifecycleActorRoleV2::Evaluator => 1,
        LifecycleActorRoleV2::ShadowOperator => 2,
        LifecycleActorRoleV2::CanaryOperator => 3,
        LifecycleActorRoleV2::HumanOperator => 4,
        LifecycleActorRoleV2::Selector => 5,
        LifecycleActorRoleV2::QuarantineAuthority => 6,
        LifecycleActorRoleV2::RevocationAuthority => 7,
        LifecycleActorRoleV2::RetirementAuthority => 8,
    });
    bytes.extend_from_slice(&actor.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&actor.verified_at.to_be_bytes());
    bytes.extend_from_slice(&actor.expires_at.to_be_bytes());
    Ok(())
}

fn authenticate_candidate_bytes(
    verifier: &LearningEvidenceVerifierV1,
    evaluation: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
    bytes: &[u8],
    generation: u64,
    evidence: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<(), LearningOperatorHostError> {
    let payload = evaluated_candidate_signing_payload_v1(evaluation, roles, bytes, generation)?;
    let verified = verifier.verify(LearningEvidenceRoleV1::Evaluator, evidence, &payload, now)?;
    if verified.principal() != &evaluation.evaluator
        || evidence.objective_digest != evaluation.objective_digest
    {
        return Err(LearningOperatorHostError::Binding(
            "candidate bytes are not signed by the evaluation principal",
        ));
    }
    Ok(())
}

fn validate_manifest_binding(
    manifest: &ArtifactManifest,
    model: &TabularOperatorArtifactV1,
    pin: &TabularPayloadPinV1,
    encoded_bytes: usize,
) -> Result<(), LearningOperatorHostError> {
    if manifest.artifact_id != model.artifact_id
        || manifest.kind != ArtifactKind::Policy
        || manifest.generation != model.generation
        || manifest.content_digest != pin.payload_digest
        || manifest.objective_digest != model.objective_digest
        || manifest.support_digest != model.dataset_digest
        || manifest.producer_id != model.producer_id
        || manifest.encoded_size_bytes
            != u64::try_from(encoded_bytes)
                .map_err(|_| LearningOperatorHostError::Binding("payload length overflow"))?
    {
        return Err(LearningOperatorHostError::Binding(
            "artifact manifest does not bind the trained operator",
        ));
    }
    Ok(())
}

fn digest_trained(pin: &TabularPayloadPinV1) -> Digest32 {
    Digest32::of_parts(&[
        pin.payload_digest.as_array(),
        pin.artifact_digest.as_array(),
        pin.objective_digest.as_array(),
        pin.dataset_digest.as_array(),
        pin.sensor_core_digest.as_array(),
        pin.training_profile_digest.as_array(),
    ])
}

fn digest_publication(
    register_event_digest: Digest32,
    snapshot: &RegistrySnapshotReceipt,
    payload_digest: Digest32,
) -> Digest32 {
    Digest32::of_parts(&[
        register_event_digest.as_array(),
        snapshot.binding.as_array(),
        snapshot.head_digest.as_array(),
        snapshot.file_digest.as_array(),
        payload_digest.as_array(),
    ])
}

fn digest_evaluation_decision(decision: &SignedEvaluationDecisionV1) -> Digest32 {
    Digest32::of_parts(&[
        decision.decision.evidence_digest.as_array(),
        decision.trust_digest.as_array(),
        decision.authentication_digest.as_array(),
    ])
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), LearningOperatorHostError> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| LearningOperatorHostError::Binding("identifier length overflow"))?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

#[derive(Debug)]
pub enum LearningOperatorHostError {
    Journal(OfflineOperatorJournalError),
    Dataset(OperatorDatasetBindingError),
    ArtifactRegistry(ArtifactRegistryError),
    ArtifactStorage(ArtifactStorageError),
    ArtifactLifecycle(ArtifactLifecycleJournalError),
    Evaluation(SignedEvaluationError),
    CandidateBinding(EvaluatedShadowError),
    Evidence(SignedEvidenceError),
    Payload(TabularPayloadError),
    EvaluationRejected(IndependentEvaluationDispositionV1),
    Binding(&'static str),
    Selection(&'static str),
    Ranker(String),
}

impl fmt::Display for LearningOperatorHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningOperatorHostError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Journal(error) => Some(error),
            Self::Dataset(error) => Some(error),
            Self::ArtifactRegistry(error) => Some(error),
            Self::ArtifactStorage(error) => Some(error),
            Self::ArtifactLifecycle(error) => Some(error),
            Self::Evaluation(error) => Some(error),
            Self::CandidateBinding(error) => Some(error),
            Self::Evidence(error) => Some(error),
            Self::Payload(error) => Some(error),
            Self::EvaluationRejected(_)
            | Self::Binding(_)
            | Self::Selection(_)
            | Self::Ranker(_) => None,
        }
    }
}

impl From<OfflineOperatorJournalError> for LearningOperatorHostError {
    fn from(value: OfflineOperatorJournalError) -> Self {
        Self::Journal(value)
    }
}

impl From<OperatorDatasetBindingError> for LearningOperatorHostError {
    fn from(value: OperatorDatasetBindingError) -> Self {
        Self::Dataset(value)
    }
}

impl From<ArtifactRegistryError> for LearningOperatorHostError {
    fn from(value: ArtifactRegistryError) -> Self {
        Self::ArtifactRegistry(value)
    }
}

impl From<ArtifactStorageError> for LearningOperatorHostError {
    fn from(value: ArtifactStorageError) -> Self {
        Self::ArtifactStorage(value)
    }
}

impl From<ArtifactLifecycleJournalError> for LearningOperatorHostError {
    fn from(value: ArtifactLifecycleJournalError) -> Self {
        Self::ArtifactLifecycle(value)
    }
}

impl From<SignedEvaluationError> for LearningOperatorHostError {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Evaluation(value)
    }
}

impl From<EvaluatedShadowError> for LearningOperatorHostError {
    fn from(value: EvaluatedShadowError) -> Self {
        Self::CandidateBinding(value)
    }
}

impl From<SignedEvidenceError> for LearningOperatorHostError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

impl From<TabularPayloadError> for LearningOperatorHostError {
    fn from(value: TabularPayloadError) -> Self {
        Self::Payload(value)
    }
}

#[cfg(test)]
#[path = "learning_operator_host_tests.rs"]
mod tests;
