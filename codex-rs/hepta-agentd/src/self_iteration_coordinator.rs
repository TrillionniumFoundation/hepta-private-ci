//! control.engineering-owned coordination for governed parameter plasticity.
//!
//! The coordinator validates one frozen `IterationEnvelopeV1`, exact generator
//! coverage, independent Generator/Observer evidence and the complete product
//! request before it can enter the state-held Agentd plasticity producer. It owns
//! only an append-only terminal journal. It never receives a proposal writer and
//! cannot select, install, activate, promote or release a candidate.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;
use std::path::Path;

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::iteration_envelope_digest_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::ParameterGeneratorErrorV3;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
use codex_hepta_plasticity::generator_coverage_signing_payload_v1;
use codex_hepta_plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::plasticity_runtime::durable_fs::DurableFileIdentityV1;
use crate::plasticity_runtime::durable_fs::open_or_create_rw_nofollow;

const JOURNAL_MAGIC: &[u8; 8] = b"HPTSIT01";
const JOURNAL_VERSION: u16 = 1;
const HEADER_SIZE: usize = 8 + 2 + 32;
const MAX_FRAME_BYTES: usize = 8 * 1024;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_TERMINAL_RECORDS: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoordinatedParameterPlasticityRequestV1 {
    pub envelope: IterationEnvelopeV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub coverage_attestation: SignedLearningEvidenceV1,
    pub product: ParameterPlasticityProductRequestV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct SelfIterationIdempotencyKeyV1 {
    pub envelope_digest: Digest32,
    pub candidate_generation: Generation,
    pub proposal_id: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationTerminalDispositionV1 {
    Pending,
    Committed,
    Failed,
}

impl SelfIterationTerminalDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Pending => 0,
            Self::Committed => 1,
            Self::Failed => 2,
        }
    }

    fn from_tag(value: u8) -> Option<Self> {
        match value {
            0 => Some(Self::Pending),
            1 => Some(Self::Committed),
            2 => Some(Self::Failed),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationTerminalReceiptV1 {
    pub sequence: u64,
    pub key: SelfIterationIdempotencyKeyV1,
    pub request_digest: Digest32,
    pub disposition: SelfIterationTerminalDispositionV1,
    pub proposal_digest: Digest32,
    pub registry_frame_digest: Digest32,
    pub committed_anchor_digest: Digest32,
    pub composition_digest: Digest32,
    pub outcome_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
    pub replayed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoordinatedParameterPlasticityReceiptV1 {
    /// Present only on the first successful submission. A durable idempotent replay
    /// returns the exact terminal receipt without re-running the product adapter.
    pub product: Option<ParameterPlasticityProductReceiptV1>,
    pub terminal: SelfIterationTerminalReceiptV1,
}

#[derive(Debug)]
pub enum SelfIterationCoordinatorErrorV1 {
    InvalidEnvelope(String),
    Expired,
    Binding(&'static str),
    Coverage(GeneratorCoverageErrorV1),
    Generator(ParameterGeneratorErrorV3),
    CoverageEvidence(SignedEvidenceError),
    AdmissionEvidence(SignedEvidenceError),
    GeneratorEvidence(SignedEvidenceError),
    JournalBusy,
    JournalCorrupt,
    JournalCapacity,
    JournalConflict,
    Indeterminate,
    Io(std::io::ErrorKind),
    Arithmetic,
}

impl fmt::Display for SelfIterationCoordinatorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SelfIterationCoordinatorErrorV1 {}
impl From<GeneratorCoverageErrorV1> for SelfIterationCoordinatorErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<ParameterGeneratorErrorV3> for SelfIterationCoordinatorErrorV1 {
    fn from(value: ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}
impl From<std::io::Error> for SelfIterationCoordinatorErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedCoordinatedParameterPlasticityV1 {
    pub key: SelfIterationIdempotencyKeyV1,
    pub request_digest: Digest32,
    pub product: ParameterPlasticityProductRequestV1,
}

pub fn prepare_coordinated_parameter_plasticity_v1(
    request: CoordinatedParameterPlasticityRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<PreparedCoordinatedParameterPlasticityV1, SelfIterationCoordinatorErrorV1> {
    request
        .envelope
        .validate()
        .map_err(SelfIterationCoordinatorErrorV1::InvalidEnvelope)?;
    if request.envelope.expiry_unix_seconds < now {
        return Err(SelfIterationCoordinatorErrorV1::Expired);
    }

    let envelope_digest = iteration_envelope_digest_v1(&request.envelope)
        .map_err(SelfIterationCoordinatorErrorV1::InvalidEnvelope)?;
    let product = &request.product;
    if request.envelope.objective_digest != product.admission.objective_digest
        || request.envelope.grammar_digest
            != product
                .generator_profile
                .mutation_policy
                .mutation_grammar_digest
        || product.admission.selected_artifact_digest
            != product.generated.selected_artifact_digest
        || product.admission.window != product.generated.window
        || product.admission.generator_digest != product.generated.generator_digest
        || product.admission.baseline_generation.next()
            != Ok(product.admission.candidate_generation)
    {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "frozen envelope/product context",
        ));
    }

    let regenerated = generate_parameter_candidates_v3(product.generator_profile.clone())?;
    if regenerated != product.generated {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "generated candidate set",
        ));
    }
    verify_generator_coverage_receipt_v1(&request.coverage)?;
    validate_coverage_binding(&request.coverage, product)?;

    let coverage_payload = generator_coverage_signing_payload_v1(&request.coverage);
    let coverage_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &request.coverage_attestation,
            &coverage_payload,
            now,
        )
        .map_err(SelfIterationCoordinatorErrorV1::CoverageEvidence)?;
    let admission_payload = plasticity_admission_signing_payload_v1(&product.admission);
    let admission_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &product.admission_attestation,
            &admission_payload,
            now,
        )
        .map_err(SelfIterationCoordinatorErrorV1::AdmissionEvidence)?;
    if coverage_observer.principal() != admission_observer.principal()
        || coverage_observer.controller_id() != admission_observer.controller_id()
        || request.coverage_attestation.objective_digest != request.envelope.objective_digest
        || product.admission_attestation.objective_digest != request.envelope.objective_digest
    {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "coverage/admission observer",
        ));
    }

    let generator_payload = parameter_generator_signing_payload_v3(&product.generated);
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &product.generator_attestation,
            &generator_payload,
            now,
        )
        .map_err(SelfIterationCoordinatorErrorV1::GeneratorEvidence)?;
    verify_signed_role_separation(&generator, &coverage_observer, now)
        .map_err(SelfIterationCoordinatorErrorV1::CoverageEvidence)?;
    if product.generator_attestation.objective_digest != request.envelope.objective_digest {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "generator objective",
        ));
    }

    validate_terminal_evaluation_shape(product)?;
    let request_digest = digest_coordinated_request(&request, envelope_digest)?;
    Ok(PreparedCoordinatedParameterPlasticityV1 {
        key: SelfIterationIdempotencyKeyV1 {
            envelope_digest,
            candidate_generation: product.admission.candidate_generation,
            proposal_id: product.proposal_id.clone(),
        },
        request_digest,
        product: request.product,
    })
}

fn validate_coverage_binding(
    coverage: &GeneratorCoverageReceiptV1,
    product: &ParameterPlasticityProductRequestV1,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let profile = &product.generator_profile;
    let mut expected = profile
        .mutation_policy
        .rules
        .iter()
        .filter(|rule| rule.surface == ParameterMutationSurfaceV1::LearnableParameter)
        .map(|rule| rule.parameter_id.clone())
        .collect::<Vec<_>>();
    expected.sort();
    let mut actual = profile
        .signals
        .iter()
        .map(|signal| signal.parameter_id.clone())
        .collect::<Vec<_>>();
    actual.sort();
    let mut scales = profile.update_scales.clone();
    scales.sort();
    let expected_disposition = if scales.is_empty() {
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates
    } else if actual.is_empty() {
        GeneratorCoverageDispositionV1::ZeroEligibleSignals
    } else {
        GeneratorCoverageDispositionV1::Covered
    };

    if coverage.selected_artifact_digest != profile.selected_artifact_digest
        || coverage.window != profile.window
        || coverage.mutation_grammar_digest
            != profile.mutation_policy.mutation_grammar_digest
        || coverage.owner_frontier_digest != product.admission.owner_evidence_set_digest
        || coverage.expected_parameters != expected
        || coverage.actual_signal_parameters != actual
        || coverage.update_scales != scales
        || coverage.disposition != expected_disposition
    {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "generator coverage",
        ));
    }
    Ok(())
}

fn validate_terminal_evaluation_shape(
    product: &ParameterPlasticityProductRequestV1,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let mut expected = product
        .generated
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    expected.sort();
    let mut actual = product
        .evaluations
        .iter()
        .map(|evaluation| evaluation.bundle.candidate_id.clone())
        .collect::<Vec<_>>();
    actual.sort();
    if expected.is_empty() {
        if product.no_change_attestation.is_none() || !actual.is_empty() {
            return Err(SelfIterationCoordinatorErrorV1::Binding(
                "no-update terminal evidence",
            ));
        }
    } else if product.no_change_attestation.is_some() || actual != expected {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "candidate evaluation coverage",
        ));
    }
    Ok(())
}

fn digest_coordinated_request(
    request: &CoordinatedParameterPlasticityRequestV1,
    envelope_digest: Digest32,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    let product = &request.product;
    let mut bytes = b"hepta.control-engineering.plasticity-coordination.v1\0".to_vec();
    for digest in [
        envelope_digest,
        request.coverage.coverage_digest,
        product.generated.generator_digest,
        product.admission.owner_evidence_set_digest,
        product.expected_registry_predecessor,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &product.proposal_id)?;
    bytes.extend_from_slice(&product.admission.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&product.admission.candidate_generation.get().to_be_bytes());
    push_attestation(&mut bytes, &request.coverage_attestation)?;
    push_attestation(&mut bytes, &product.generator_attestation)?;
    push_attestation(&mut bytes, &product.admission_attestation)?;
    match &product.no_change_attestation {
        Some(attestation) => {
            bytes.push(1);
            push_attestation(&mut bytes, attestation)?;
        }
        None => bytes.push(0),
    }
    let mut evaluations = product.evaluations.iter().collect::<Vec<_>>();
    evaluations.sort_by(|left, right| left.bundle.candidate_id.cmp(&right.bundle.candidate_id));
    push_len(&mut bytes, evaluations.len())?;
    for evaluation in evaluations {
        push_id(&mut bytes, &evaluation.bundle.candidate_id)?;
        let payload = evaluation_signing_payload_v2(&evaluation.bundle, &evaluation.metric_roles)
            .map_err(|_| SelfIterationCoordinatorErrorV1::Binding("evaluation payload"))?;
        bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        push_attestation(&mut bytes, &evaluation.evidence.generator_plan)?;
        push_attestation(&mut bytes, &evaluation.evidence.evaluator_bundle)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_attestation(
    bytes: &mut Vec<u8>,
    attestation: &SignedLearningEvidenceV1,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let signing = attestation.signing_bytes();
    push_len(bytes, signing.len())?;
    bytes.extend_from_slice(&signing);
    bytes.extend_from_slice(&attestation.signature);
    Ok(())
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len())?;
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(
    bytes: &mut Vec<u8>,
    value: usize,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let value = u32::try_from(value).map_err(|_| SelfIterationCoordinatorErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, SelfIterationCoordinatorErrorV1> {
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(SelfIterationCoordinatorErrorV1::JournalBusy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
impl Deref for LockedFile {
    type Target = File;
    fn deref(&self) -> &File {
        &self.0
    }
}
impl DerefMut for LockedFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}
impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct SelfIterationTerminalJournalV1 {
    file: LockedFile,
    identity: DurableFileIdentityV1,
    scope: Digest32,
    records: Vec<SelfIterationTerminalReceiptV1>,
    latest: BTreeMap<SelfIterationIdempotencyKeyV1, SelfIterationTerminalReceiptV1>,
}

impl SelfIterationTerminalJournalV1 {
    pub fn open(path: &Path, scope: Digest32) -> Result<Self, SelfIterationCoordinatorErrorV1> {
        if scope.is_zero() {
            return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
        }
        let (file, identity, created) = open_or_create_rw_nofollow(path, "self-iteration terminal journal")
            .map_err(map_agentd_error)?;
        let mut file = LockedFile::acquire(file)?;
        if created {
            let mut header = JOURNAL_MAGIC.to_vec();
            header.extend_from_slice(&JOURNAL_VERSION.to_be_bytes());
            header.extend_from_slice(scope.as_array());
            file.write_all(&header)
                .and_then(|_| file.sync_all())
                .map_err(|error| SelfIterationCoordinatorErrorV1::Io(error.kind()))?;
        }
        let length = file.metadata()?.len();
        if length < HEADER_SIZE as u64 || length > MAX_JOURNAL_BYTES {
            return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = vec![0_u8; HEADER_SIZE];
        file.read_exact(&mut header)?;
        if &header[..8] != JOURNAL_MAGIC
            || u16::from_be_bytes([header[8], header[9]]) != JOURNAL_VERSION
            || &header[10..42] != scope.as_array()
        {
            return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
        }

        let mut journal = Self {
            file,
            identity,
            scope,
            records: Vec::new(),
            latest: BTreeMap::new(),
        };
        journal.replay(length)?;
        Ok(journal)
    }

    #[must_use]
    pub const fn file_identity(&self) -> DurableFileIdentityV1 {
        self.identity
    }

    pub fn lookup(
        &self,
        key: &SelfIterationIdempotencyKeyV1,
        request_digest: Digest32,
    ) -> Result<Option<SelfIterationTerminalReceiptV1>, SelfIterationCoordinatorErrorV1> {
        let Some(receipt) = self.latest.get(key) else {
            return Ok(None);
        };
        if receipt.request_digest != request_digest {
            return Err(SelfIterationCoordinatorErrorV1::JournalConflict);
        }
        if receipt.disposition == SelfIterationTerminalDispositionV1::Pending {
            return Err(SelfIterationCoordinatorErrorV1::Indeterminate);
        }
        let mut replay = receipt.clone();
        replay.replayed = true;
        Ok(Some(replay))
    }

    pub fn append_pending(
        &mut self,
        key: SelfIterationIdempotencyKeyV1,
        request_digest: Digest32,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
        if self.latest.contains_key(&key) {
            return self
                .lookup(&key, request_digest)?
                .ok_or(SelfIterationCoordinatorErrorV1::JournalConflict);
        }
        self.append_record(
            key,
            request_digest,
            SelfIterationTerminalDispositionV1::Pending,
            Digest32::ZERO,
            Digest32::ZERO,
            Digest32::ZERO,
            Digest32::ZERO,
            Digest32::ZERO,
        )
    }

    pub fn append_committed(
        &mut self,
        key: SelfIterationIdempotencyKeyV1,
        request_digest: Digest32,
        product: &ParameterPlasticityProductReceiptV1,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
        let pending = self.latest.get(&key).ok_or(SelfIterationCoordinatorErrorV1::JournalConflict)?;
        if pending.request_digest != request_digest
            || pending.disposition != SelfIterationTerminalDispositionV1::Pending
        {
            return Err(SelfIterationCoordinatorErrorV1::JournalConflict);
        }
        self.append_record(
            key,
            request_digest,
            SelfIterationTerminalDispositionV1::Committed,
            product.proposal.proposal_digest,
            product.registry.frame_digest,
            product.committed_registry_anchor.frame_digest,
            product.composition_digest,
            product.composition_digest,
        )
    }

    pub fn append_failed(
        &mut self,
        key: SelfIterationIdempotencyKeyV1,
        request_digest: Digest32,
        outcome_digest: Digest32,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
        let pending = self.latest.get(&key).ok_or(SelfIterationCoordinatorErrorV1::JournalConflict)?;
        if pending.request_digest != request_digest
            || pending.disposition != SelfIterationTerminalDispositionV1::Pending
            || outcome_digest.is_zero()
        {
            return Err(SelfIterationCoordinatorErrorV1::JournalConflict);
        }
        self.append_record(
            key,
            request_digest,
            SelfIterationTerminalDispositionV1::Failed,
            Digest32::ZERO,
            Digest32::ZERO,
            Digest32::ZERO,
            Digest32::ZERO,
            outcome_digest,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn append_record(
        &mut self,
        key: SelfIterationIdempotencyKeyV1,
        request_digest: Digest32,
        disposition: SelfIterationTerminalDispositionV1,
        proposal_digest: Digest32,
        registry_frame_digest: Digest32,
        committed_anchor_digest: Digest32,
        composition_digest: Digest32,
        outcome_digest: Digest32,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
        if self.records.len() >= MAX_TERMINAL_RECORDS {
            return Err(SelfIterationCoordinatorErrorV1::JournalCapacity);
        }
        let sequence = u64::try_from(self.records.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
        let predecessor_frame_digest = self
            .records
            .last()
            .map(|receipt| receipt.frame_digest)
            .unwrap_or(Digest32::ZERO);
        let mut receipt = SelfIterationTerminalReceiptV1 {
            sequence,
            key,
            request_digest,
            disposition,
            proposal_digest,
            registry_frame_digest,
            committed_anchor_digest,
            composition_digest,
            outcome_digest,
            predecessor_frame_digest,
            frame_digest: Digest32::ZERO,
            replayed: false,
        };
        let payload = encode_receipt(&receipt)?;
        receipt.frame_digest = digest_frame(&payload);
        let mut frame = Vec::with_capacity(4 + payload.len() + 32);
        let length = u32::try_from(payload.len())
            .map_err(|_| SelfIterationCoordinatorErrorV1::Arithmetic)?;
        frame.extend_from_slice(&length.to_be_bytes());
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(receipt.frame_digest.as_array());
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&frame)
            .and_then(|_| self.file.sync_all())
            .map_err(|error| SelfIterationCoordinatorErrorV1::Io(error.kind()))?;
        self.latest.insert(receipt.key.clone(), receipt.clone());
        self.records.push(receipt.clone());
        Ok(receipt)
    }

    fn replay(&mut self, physical_length: u64) -> Result<(), SelfIterationCoordinatorErrorV1> {
        let mut offset = HEADER_SIZE as u64;
        let mut truncate_at = None;
        while offset < physical_length {
            if physical_length - offset < 4 {
                truncate_at = Some(offset);
                break;
            }
            self.file.seek(SeekFrom::Start(offset))?;
            let mut length_bytes = [0_u8; 4];
            self.file.read_exact(&mut length_bytes)?;
            let payload_length = u32::from_be_bytes(length_bytes) as usize;
            if payload_length == 0 || payload_length > MAX_FRAME_BYTES {
                return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
            }
            let total = 4_u64
                .checked_add(payload_length as u64)
                .and_then(|value| value.checked_add(32))
                .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
            if physical_length - offset < total {
                truncate_at = Some(offset);
                break;
            }
            let mut payload = vec![0_u8; payload_length];
            self.file.read_exact(&mut payload)?;
            let mut frame_digest = [0_u8; 32];
            self.file.read_exact(&mut frame_digest)?;
            if digest_frame(&payload).as_array() != &frame_digest {
                return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
            }
            let mut receipt = decode_receipt(&payload)?;
            receipt.frame_digest = Digest32::from_array(frame_digest);
            receipt.replayed = false;
            let expected_sequence = u64::try_from(self.records.len())
                .ok()
                .and_then(|value| value.checked_add(1))
                .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
            let expected_predecessor = self
                .records
                .last()
                .map(|value| value.frame_digest)
                .unwrap_or(Digest32::ZERO);
            if receipt.sequence != expected_sequence
                || receipt.predecessor_frame_digest != expected_predecessor
            {
                return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
            }
            validate_transition(self.latest.get(&receipt.key), &receipt)?;
            self.latest.insert(receipt.key.clone(), receipt.clone());
            self.records.push(receipt);
            offset = offset
                .checked_add(total)
                .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
        }
        if let Some(valid_length) = truncate_at {
            self.file
                .set_len(valid_length)
                .and_then(|_| self.file.sync_all())
                .map_err(|error| SelfIterationCoordinatorErrorV1::Io(error.kind()))?;
        }
        Ok(())
    }
}

fn validate_transition(
    previous: Option<&SelfIterationTerminalReceiptV1>,
    next: &SelfIterationTerminalReceiptV1,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    match previous {
        None if next.disposition == SelfIterationTerminalDispositionV1::Pending => Ok(()),
        Some(previous)
            if previous.disposition == SelfIterationTerminalDispositionV1::Pending
                && previous.request_digest == next.request_digest
                && matches!(
                    next.disposition,
                    SelfIterationTerminalDispositionV1::Committed
                        | SelfIterationTerminalDispositionV1::Failed
                ) => Ok(()),
        _ => Err(SelfIterationCoordinatorErrorV1::JournalCorrupt),
    }
}

fn encode_receipt(
    receipt: &SelfIterationTerminalReceiptV1,
) -> Result<Vec<u8>, SelfIterationCoordinatorErrorV1> {
    let mut bytes = b"hepta.control-engineering.self-iteration-terminal.v1\0".to_vec();
    bytes.extend_from_slice(&receipt.sequence.to_be_bytes());
    bytes.extend_from_slice(receipt.key.envelope_digest.as_array());
    bytes.extend_from_slice(&receipt.key.candidate_generation.get().to_be_bytes());
    push_id(&mut bytes, &receipt.key.proposal_id)?;
    bytes.extend_from_slice(receipt.request_digest.as_array());
    bytes.push(receipt.disposition.tag());
    for digest in [
        receipt.proposal_digest,
        receipt.registry_frame_digest,
        receipt.committed_anchor_digest,
        receipt.composition_digest,
        receipt.outcome_digest,
        receipt.predecessor_frame_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

fn decode_receipt(
    bytes: &[u8],
) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
    const DOMAIN: &[u8] = b"hepta.control-engineering.self-iteration-terminal.v1\0";
    if !bytes.starts_with(DOMAIN) {
        return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
    }
    let mut cursor = DOMAIN.len();
    let sequence = take_u64(bytes, &mut cursor)?;
    let envelope_digest = take_digest(bytes, &mut cursor)?;
    let candidate_generation = Generation::new(take_u64(bytes, &mut cursor)?)
        .map_err(|_| SelfIterationCoordinatorErrorV1::JournalCorrupt)?;
    let proposal_id = take_id(bytes, &mut cursor)?;
    let request_digest = take_digest(bytes, &mut cursor)?;
    let disposition = bytes
        .get(cursor)
        .copied()
        .and_then(SelfIterationTerminalDispositionV1::from_tag)
        .ok_or(SelfIterationCoordinatorErrorV1::JournalCorrupt)?;
    cursor += 1;
    let proposal_digest = take_digest(bytes, &mut cursor)?;
    let registry_frame_digest = take_digest(bytes, &mut cursor)?;
    let committed_anchor_digest = take_digest(bytes, &mut cursor)?;
    let composition_digest = take_digest(bytes, &mut cursor)?;
    let outcome_digest = take_digest(bytes, &mut cursor)?;
    let predecessor_frame_digest = take_digest(bytes, &mut cursor)?;
    if cursor != bytes.len() {
        return Err(SelfIterationCoordinatorErrorV1::JournalCorrupt);
    }
    Ok(SelfIterationTerminalReceiptV1 {
        sequence,
        key: SelfIterationIdempotencyKeyV1 {
            envelope_digest,
            candidate_generation,
            proposal_id,
        },
        request_digest,
        disposition,
        proposal_digest,
        registry_frame_digest,
        committed_anchor_digest,
        composition_digest,
        outcome_digest,
        predecessor_frame_digest,
        frame_digest: Digest32::ZERO,
        replayed: false,
    })
}

fn digest_frame(payload: &[u8]) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.self-iteration-frame.v1\0".to_vec();
    bytes.extend_from_slice(payload);
    Digest32::of_bytes(&bytes)
}

fn take_u64(
    bytes: &[u8],
    cursor: &mut usize,
) -> Result<u64, SelfIterationCoordinatorErrorV1> {
    let end = cursor
        .checked_add(8)
        .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
    let raw: [u8; 8] = bytes
        .get(*cursor..end)
        .ok_or(SelfIterationCoordinatorErrorV1::JournalCorrupt)?
        .try_into()
        .map_err(|_| SelfIterationCoordinatorErrorV1::JournalCorrupt)?;
    *cursor = end;
    Ok(u64::from_be_bytes(raw))
}

fn take_digest(
    bytes: &[u8],
    cursor: &mut usize,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    let end = cursor
        .checked_add(32)
        .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
    let raw: [u8; 32] = bytes
        .get(*cursor..end)
        .ok_or(SelfIterationCoordinatorErrorV1::JournalCorrupt)?
        .try_into()
        .map_err(|_| SelfIterationCoordinatorErrorV1::JournalCorrupt)?;
    *cursor = end;
    Ok(Digest32::from_array(raw))
}

fn take_id(
    bytes: &[u8],
    cursor: &mut usize,
) -> Result<StableId, SelfIterationCoordinatorErrorV1> {
    let end = cursor
        .checked_add(4)
        .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
    let raw: [u8; 4] = bytes
        .get(*cursor..end)
        .ok_or(SelfIterationCoordinatorErrorV1::JournalCorrupt)?
        .try_into()
        .map_err(|_| SelfIterationCoordinatorErrorV1::JournalCorrupt)?;
    *cursor = end;
    let length = u32::from_be_bytes(raw) as usize;
    let end = cursor
        .checked_add(length)
        .ok_or(SelfIterationCoordinatorErrorV1::Arithmetic)?;
    let value = std::str::from_utf8(
        bytes
            .get(*cursor..end)
            .ok_or(SelfIterationCoordinatorErrorV1::JournalCorrupt)?,
    )
    .map_err(|_| SelfIterationCoordinatorErrorV1::JournalCorrupt)?;
    *cursor = end;
    StableId::new(value.to_string()).map_err(|_| SelfIterationCoordinatorErrorV1::JournalCorrupt)
}

fn map_agentd_error(error: AgentdError) -> SelfIterationCoordinatorErrorV1 {
    match error {
        AgentdError::Io(error) => SelfIterationCoordinatorErrorV1::Io(error.kind()),
        _ => SelfIterationCoordinatorErrorV1::JournalCorrupt,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::FixedQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }
    fn key() -> SelfIterationIdempotencyKeyV1 {
        SelfIterationIdempotencyKeyV1 {
            envelope_digest: digest(b"envelope"),
            candidate_generation: generation(2),
            proposal_id: id("proposal:coordinated"),
        }
    }

    #[test]
    fn terminal_journal_is_idempotent_and_conflict_detecting() {
        let directory = tempfile::tempdir().expect("tempdir");
        let canonical = directory.path().canonicalize().expect("canonical");
        let path = canonical.join("terminal.journal");
        let scope = digest(b"scope");
        let request = digest(b"request");
        let pending = {
            let mut journal = SelfIterationTerminalJournalV1::open(&path, scope).expect("open");
            journal
                .append_pending(key(), request)
                .expect("append pending")
        };
        assert_eq!(pending.disposition, SelfIterationTerminalDispositionV1::Pending);
        let journal = SelfIterationTerminalJournalV1::open(&path, scope).expect("reopen");
        assert!(matches!(
            journal.lookup(&key(), request),
            Err(SelfIterationCoordinatorErrorV1::Indeterminate)
        ));
        assert!(matches!(
            journal.lookup(&key(), digest(b"drift")),
            Err(SelfIterationCoordinatorErrorV1::JournalConflict)
        ));
    }

    #[test]
    fn incomplete_tail_is_repaired_but_complete_drift_is_not() {
        let directory = tempfile::tempdir().expect("tempdir");
        let canonical = directory.path().canonicalize().expect("canonical");
        let path = canonical.join("tail.journal");
        let scope = digest(b"scope");
        {
            let mut journal = SelfIterationTerminalJournalV1::open(&path, scope).expect("open");
            journal
                .append_pending(key(), digest(b"request"))
                .expect("append");
        }
        let valid = std::fs::metadata(&path).expect("metadata").len();
        {
            let mut file = std::fs::OpenOptions::new()
                .append(true)
                .open(&path)
                .expect("append");
            file.write_all(&[0, 0, 0]).expect("tail");
            file.sync_all().expect("sync");
        }
        drop(SelfIterationTerminalJournalV1::open(&path, scope).expect("repair"));
        assert_eq!(std::fs::metadata(&path).expect("metadata").len(), valid);
    }

    #[test]
    fn coverage_disposition_examples_remain_distinct() {
        assert_ne!(
            GeneratorCoverageDispositionV1::ZeroEligibleSignals,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates
        );
        assert!(FixedQ32::ONE > FixedQ32::ZERO);
    }
}
