//! Control-engineering-owned, authority-free self-iteration coordination.
//!
//! One validated `IterationEnvelopeV1` is bound to one frozen parameter or
//! topology proposal, submitted through the named Agentd plasticity producer,
//! and recorded in a checksum-chained terminal journal. The coordinator owns no
//! proposal registry writer and exposes no selection, activation, promotion,
//! release, or runtime-mutation operation.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::str::FromStr;

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::GeneratorCoverageRequestV1;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;

const JOURNAL_MAGIC: &[u8; 8] = b"HPTITR02";
const FORMAT_VERSION: u16 = 2;
const MAX_RECORDS: usize = 65_536;
const MAX_HEADER_BYTES: usize = 16 * 1024;
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_FILE_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationProposalKindV1 {
    Parameter,
    Topology,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationTerminalDispositionV1 {
    Committed,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
    Rejected,
    Unavailable,
    Cancelled,
    DeadlineExceeded,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SelfIterationJournalAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationContextV1 {
    pub envelope: IterationEnvelopeV1,
    pub proposal_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub mutation_grammar_digest: Digest32,
    pub owner_frontier_digest: Digest32,
    pub deadline_unix_millis: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationTerminalReceiptV1 {
    pub sequence: u64,
    pub idempotency_key: Digest32,
    pub envelope_digest: Digest32,
    pub request_digest: Digest32,
    pub proposal_id: StableId,
    pub proposal_kind: SelfIterationProposalKindV1,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub disposition: SelfIterationTerminalDispositionV1,
    pub coverage_digest: Option<Digest32>,
    pub composition_digest: Option<Digest32>,
    pub registry_frame_digest: Option<Digest32>,
    pub error_digest: Option<Digest32>,
    pub observed_unix_seconds: u64,
    pub receipt_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
}

#[derive(Debug)]
pub enum SelfIterationCoordinatorErrorV1 {
    InvalidEnvelope(String),
    Expired,
    Binding(&'static str),
    Coverage(codex_hepta_plasticity::GeneratorCoverageErrorV1),
    Generator(codex_hepta_plasticity::ParameterGeneratorErrorV3),
    Topology(codex_hepta_intelligence::TopologyPlasticityProductErrorV1),
    IdempotencyConflict,
    Journal(SelfIterationJournalErrorV1),
}

impl fmt::Display for SelfIterationCoordinatorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SelfIterationCoordinatorErrorV1 {}
impl From<codex_hepta_plasticity::GeneratorCoverageErrorV1>
    for SelfIterationCoordinatorErrorV1
{
    fn from(value: codex_hepta_plasticity::GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<codex_hepta_plasticity::ParameterGeneratorErrorV3>
    for SelfIterationCoordinatorErrorV1
{
    fn from(value: codex_hepta_plasticity::ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}
impl From<codex_hepta_intelligence::TopologyPlasticityProductErrorV1>
    for SelfIterationCoordinatorErrorV1
{
    fn from(value: codex_hepta_intelligence::TopologyPlasticityProductErrorV1) -> Self {
        Self::Topology(value)
    }
}
impl From<SelfIterationJournalErrorV1> for SelfIterationCoordinatorErrorV1 {
    fn from(value: SelfIterationJournalErrorV1) -> Self {
        Self::Journal(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SelfIterationJournalErrorV1 {
    Busy,
    NotRegular,
    InvalidPath,
    InvalidScope,
    InvalidRollbackDomain,
    InvalidFence,
    InvalidLimit,
    BootstrapRequiresEmptyFile,
    InvalidAnchor,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    ContextMismatch,
    Capacity,
    Corrupt,
    Conflict,
    Indeterminate,
    Io(std::io::ErrorKind),
    Identity,
    Arithmetic,
}

impl fmt::Display for SelfIterationJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SelfIterationJournalErrorV1 {}
impl From<std::io::Error> for SelfIterationJournalErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}
impl From<serde_json::Error> for SelfIterationJournalErrorV1 {
    fn from(_: serde_json::Error) -> Self {
        Self::Corrupt
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JournalHeaderWireV1 {
    schema: String,
    scope_digest: String,
    rollback_domain_digest: String,
    writer_fence: u64,
    maximum_records: u32,
    storage_identity_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TerminalSemanticsWireV1 {
    idempotency_key: String,
    envelope_digest: String,
    request_digest: String,
    proposal_id: String,
    proposal_kind: String,
    baseline_generation: u64,
    candidate_generation: u64,
    disposition: String,
    coverage_digest: Option<String>,
    composition_digest: Option<String>,
    registry_frame_digest: Option<String>,
    error_digest: Option<String>,
    observed_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TerminalFrameWireV1 {
    sequence: u64,
    predecessor_frame_digest: String,
    semantics: TerminalSemanticsWireV1,
    receipt_digest: String,
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, SelfIterationJournalErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(SelfIterationJournalErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(SelfIterationJournalErrorV1::Busy),
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

pub struct SelfIterationReceiptJournalV1 {
    file: LockedFile,
    scope_digest: Digest32,
    rollback_domain_digest: Digest32,
    writer_fence: u64,
    maximum_records: usize,
    storage_identity_digest: Digest32,
    header_end: u64,
    by_key: BTreeMap<Digest32, SelfIterationTerminalReceiptV1>,
    frame_digests: Vec<Digest32>,
}

impl SelfIterationReceiptJournalV1 {
    pub fn create_new(
        path: &Path,
        scope_digest: Digest32,
        rollback_domain_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, SelfIterationJournalErrorV1> {
        validate_context_values(
            scope_digest,
            rollback_domain_digest,
            writer_fence,
            maximum_records,
        )?;
        let file = secure_create_new(path)?;
        sync_parent(path)?;
        Self::open_internal(
            file,
            scope_digest,
            rollback_domain_digest,
            writer_fence,
            maximum_records,
            None,
            true,
        )
    }

    pub fn reopen_anchored_path(
        path: &Path,
        scope_digest: Digest32,
        rollback_domain_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: SelfIterationJournalAnchorV1,
    ) -> Result<Self, SelfIterationJournalErrorV1> {
        let file = secure_open_existing(path)?;
        Self::reopen_anchored(
            file,
            scope_digest,
            rollback_domain_digest,
            writer_fence,
            maximum_records,
            anchor,
        )
    }

    pub fn bootstrap_empty(
        file: File,
        scope_digest: Digest32,
        rollback_domain_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, SelfIterationJournalErrorV1> {
        if file.metadata()?.len() != 0 {
            return Err(SelfIterationJournalErrorV1::BootstrapRequiresEmptyFile);
        }
        Self::open_internal(
            file,
            scope_digest,
            rollback_domain_digest,
            writer_fence,
            maximum_records,
            None,
            true,
        )
    }

    pub fn reopen_anchored(
        file: File,
        scope_digest: Digest32,
        rollback_domain_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: SelfIterationJournalAnchorV1,
    ) -> Result<Self, SelfIterationJournalErrorV1> {
        if anchor.sequence == 0 || anchor.frame_digest.is_zero() {
            return Err(SelfIterationJournalErrorV1::InvalidAnchor);
        }
        Self::open_internal(
            file,
            scope_digest,
            rollback_domain_digest,
            writer_fence,
            maximum_records,
            Some(anchor),
            false,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn open_internal(
        file: File,
        scope_digest: Digest32,
        rollback_domain_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: Option<SelfIterationJournalAnchorV1>,
        bootstrap: bool,
    ) -> Result<Self, SelfIterationJournalErrorV1> {
        validate_context_values(
            scope_digest,
            rollback_domain_digest,
            writer_fence,
            maximum_records,
        )?;
        let storage_identity_digest = storage_identity_digest(&file)?;
        let expected_header = JournalHeaderWireV1 {
            schema: "hepta.control-engineering.self-iteration-journal.v1".to_string(),
            scope_digest: scope_digest.to_string(),
            rollback_domain_digest: rollback_domain_digest.to_string(),
            writer_fence,
            maximum_records: u32::try_from(maximum_records)
                .map_err(|_| SelfIterationJournalErrorV1::InvalidLimit)?,
            storage_identity_digest: storage_identity_digest.to_string(),
        };
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() > MAX_FILE_BYTES {
            return Err(SelfIterationJournalErrorV1::Capacity);
        }
        let header_end = if bootstrap {
            if file.metadata()?.len() != 0 {
                return Err(SelfIterationJournalErrorV1::BootstrapRequiresEmptyFile);
            }
            write_header(&mut file, &expected_header)?
        } else {
            let (actual, header_end) = read_header(&mut file)?;
            if actual != expected_header {
                return Err(SelfIterationJournalErrorV1::ContextMismatch);
            }
            header_end
        };

        let mut journal = Self {
            file,
            scope_digest,
            rollback_domain_digest,
            writer_fence,
            maximum_records,
            storage_identity_digest,
            header_end,
            by_key: BTreeMap::new(),
            frame_digests: Vec::new(),
        };
        journal.replay(anchor)?;
        Ok(journal)
    }

    fn replay(
        &mut self,
        anchor: Option<SelfIterationJournalAnchorV1>,
    ) -> Result<(), SelfIterationJournalErrorV1> {
        let physical_length = self.file.metadata()?.len();
        let mut offset = self.header_end;
        let mut incomplete_tail = false;
        while offset < physical_length {
            if physical_length - offset < 4 {
                incomplete_tail = true;
                break;
            }
            self.file.seek(SeekFrom::Start(offset))?;
            let mut length_bytes = [0_u8; 4];
            self.file.read_exact(&mut length_bytes)?;
            let frame_length = u32::from_be_bytes(length_bytes) as usize;
            if frame_length == 0 || frame_length > MAX_FRAME_BYTES {
                return Err(SelfIterationJournalErrorV1::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_length as u64)
                .and_then(|value| value.checked_add(32))
                .ok_or(SelfIterationJournalErrorV1::Capacity)?;
            if physical_length - offset < total {
                incomplete_tail = true;
                break;
            }
            if self.frame_digests.len() >= self.maximum_records {
                return Err(SelfIterationJournalErrorV1::Capacity);
            }
            let mut payload = vec![0_u8; frame_length];
            self.file.read_exact(&mut payload)?;
            let mut digest_bytes = [0_u8; 32];
            self.file.read_exact(&mut digest_bytes)?;
            let frame_digest = Digest32::from_array(digest_bytes);
            let expected_predecessor = self
                .frame_digests
                .last()
                .copied()
                .unwrap_or(Digest32::ZERO);
            let receipt = decode_frame(
                &payload,
                frame_digest,
                self.frame_digests.len() as u64 + 1,
                expected_predecessor,
            )?;
            if self
                .by_key
                .insert(receipt.idempotency_key, receipt.clone())
                .is_some()
            {
                return Err(SelfIterationJournalErrorV1::Corrupt);
            }
            self.frame_digests.push(receipt.frame_digest);
            offset = offset
                .checked_add(total)
                .ok_or(SelfIterationJournalErrorV1::Capacity)?;
        }

        if let Some(anchor) = anchor {
            let recovered = anchor
                .sequence
                .checked_sub(1)
                .and_then(|value| usize::try_from(value).ok())
                .and_then(|index| self.frame_digests.get(index))
                .ok_or(SelfIterationJournalErrorV1::AcknowledgedHistoryMissing)?;
            if *recovered != anchor.frame_digest {
                return Err(SelfIterationJournalErrorV1::AnchorMismatch);
            }
        }
        if incomplete_tail {
            self.file
                .set_len(offset)
                .and_then(|_| self.file.sync_all())
                .map_err(|_| SelfIterationJournalErrorV1::Indeterminate)?;
        }
        Ok(())
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn rollback_domain_digest(&self) -> Digest32 {
        self.rollback_domain_digest
    }

    #[must_use]
    pub const fn writer_fence(&self) -> u64 {
        self.writer_fence
    }

    #[must_use]
    pub const fn storage_identity_digest(&self) -> Digest32 {
        self.storage_identity_digest
    }

    #[must_use]
    pub fn current_anchor(&self) -> Option<SelfIterationJournalAnchorV1> {
        self.frame_digests
            .last()
            .copied()
            .map(|frame_digest| SelfIterationJournalAnchorV1 {
                sequence: self.frame_digests.len() as u64,
                frame_digest,
            })
    }

    #[must_use]
    pub fn get(&self, key: Digest32) -> Option<&SelfIterationTerminalReceiptV1> {
        self.by_key.get(&key)
    }

    fn append(
        &mut self,
        expected_predecessor: Digest32,
        mut receipt: SelfIterationTerminalReceiptV1,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationJournalErrorV1> {
        let actual_predecessor = self
            .frame_digests
            .last()
            .copied()
            .unwrap_or(Digest32::ZERO);
        if expected_predecessor != actual_predecessor {
            return Err(SelfIterationJournalErrorV1::Conflict);
        }
        if let Some(existing) = self.by_key.get(&receipt.idempotency_key) {
            if existing.request_digest == receipt.request_digest {
                return Ok(existing.clone());
            }
            return Err(SelfIterationJournalErrorV1::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(SelfIterationJournalErrorV1::Capacity);
        }

        receipt.sequence = self.frame_digests.len() as u64 + 1;
        receipt.predecessor_frame_digest = actual_predecessor;
        receipt.receipt_digest = digest_terminal_semantics(&receipt)?;
        let payload = encode_frame(&receipt)?;
        let mut frame_material = b"hepta.control-engineering.self-iteration-frame.v1\0".to_vec();
        frame_material.extend_from_slice(actual_predecessor.as_array());
        frame_material.extend_from_slice(&payload);
        receipt.frame_digest = Digest32::of_bytes(&frame_material);
        let length = u32::try_from(payload.len())
            .map_err(|_| SelfIterationJournalErrorV1::Capacity)?;

        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&length.to_be_bytes())
            .and_then(|_| self.file.write_all(&payload))
            .and_then(|_| self.file.write_all(receipt.frame_digest.as_array()))
            .and_then(|_| self.file.sync_all())
            .map_err(|_| SelfIterationJournalErrorV1::Indeterminate)?;
        self.frame_digests.push(receipt.frame_digest);
        self.by_key
            .insert(receipt.idempotency_key, receipt.clone());
        Ok(receipt)
    }
}

pub struct SelfIterationPlasticityCoordinatorV1 {
    journal: SelfIterationReceiptJournalV1,
}

impl SelfIterationPlasticityCoordinatorV1 {
    #[must_use]
    pub fn new(journal: SelfIterationReceiptJournalV1) -> Self {
        Self { journal }
    }

    #[must_use]
    pub fn current_anchor(&self) -> Option<SelfIterationJournalAnchorV1> {
        self.journal.current_anchor()
    }

    #[must_use]
    pub const fn storage_identity_digest(&self) -> Digest32 {
        self.journal.storage_identity_digest()
    }

    pub async fn submit_parameter(
        &mut self,
        producer: &PlasticityRuntimeHandleV1,
        context: SelfIterationContextV1,
        coverage_request: GeneratorCoverageRequestV1,
        coverage: GeneratorCoverageReceiptV1,
        request: ParameterPlasticityProductRequestV1,
        now_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
        let envelope_digest = validate_submission_context(&context, now_unix_seconds)?;
        if request.proposal_id != context.proposal_id
            || request.generated.selected_artifact_digest != context.selected_artifact_digest
            || request.generated.window != context.window
            || request.admission.baseline_generation != context.baseline_generation
            || request.admission.candidate_generation != context.candidate_generation
            || request.generator_profile.mutation_policy.mutation_grammar_digest
                != context.mutation_grammar_digest
            || coverage.owner_frontier_digest != context.owner_frontier_digest
            || coverage.mutation_grammar_digest != context.mutation_grammar_digest
        {
            return Err(SelfIterationCoordinatorErrorV1::Binding(
                "parameter self-iteration context",
            ));
        }
        verify_generated_parameter_candidates_v3(
            request.generator_profile.clone(),
            &request.generated,
        )?;
        verify_generator_coverage_receipt_v1(
            &request.generator_profile,
            coverage_request,
            &coverage,
        )?;

        let request_digest = digest_parameter_request(&context, &coverage, &request)?;
        let idempotency_key = idempotency_key(
            envelope_digest,
            &context,
            SelfIterationProposalKindV1::Parameter,
        )?;
        if let Some(existing) = self.journal.get(idempotency_key) {
            if existing.request_digest == request_digest {
                return Ok(existing.clone());
            }
            return Err(SelfIterationCoordinatorErrorV1::IdempotencyConflict);
        }

        let terminal = match coverage.disposition {
            GeneratorCoverageDispositionV1::ZeroEligibleSignals => TerminalMaterialV1 {
                disposition: SelfIterationTerminalDispositionV1::ZeroEligibleSignals,
                coverage_digest: Some(coverage.coverage_digest),
                composition_digest: None,
                registry_frame_digest: None,
                error_digest: None,
            },
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates => TerminalMaterialV1 {
                disposition: SelfIterationTerminalDispositionV1::PolicyDisabledUpdates,
                coverage_digest: Some(coverage.coverage_digest),
                composition_digest: None,
                registry_frame_digest: None,
                error_digest: None,
            },
            GeneratorCoverageDispositionV1::Complete => {
                if cancellation.is_cancelled() {
                    terminal_error(
                        SelfIterationTerminalDispositionV1::Cancelled,
                        Some(coverage.coverage_digest),
                        b"cancelled-before-parameter-submit",
                    )
                } else if deadline_expired(context.deadline_unix_millis) {
                    terminal_error(
                        SelfIterationTerminalDispositionV1::DeadlineExceeded,
                        Some(coverage.coverage_digest),
                        b"deadline-before-parameter-submit",
                    )
                } else {
                    match producer.propose_parameter(request, now_unix_seconds).await {
                        Ok(receipt) => parameter_success(&coverage, &receipt),
                        Err(error) => runtime_error(Some(coverage.coverage_digest), &error),
                    }
                }
            }
        };
        self.persist_terminal(
            &context,
            envelope_digest,
            request_digest,
            idempotency_key,
            SelfIterationProposalKindV1::Parameter,
            terminal,
            now_unix_seconds,
        )
    }

    pub async fn submit_topology(
        &mut self,
        producer: &PlasticityRuntimeHandleV1,
        context: SelfIterationContextV1,
        request: TopologyPlasticityProductRequestV1,
        now_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
        let envelope_digest = validate_submission_context(&context, now_unix_seconds)?;
        if request.proposal_id != context.proposal_id
            || request.selected_artifact_digest != context.selected_artifact_digest
            || request.window != context.window
            || request.baseline_generation != context.baseline_generation
            || request.candidate_generation != context.candidate_generation
        {
            return Err(SelfIterationCoordinatorErrorV1::Binding(
                "topology self-iteration context",
            ));
        }
        let generation_payload = topology_generation_signing_payload_v1(&request)?;
        let request_digest = digest_topology_request(&context, &request, &generation_payload)?;
        let idempotency_key = idempotency_key(
            envelope_digest,
            &context,
            SelfIterationProposalKindV1::Topology,
        )?;
        if let Some(existing) = self.journal.get(idempotency_key) {
            if existing.request_digest == request_digest {
                return Ok(existing.clone());
            }
            return Err(SelfIterationCoordinatorErrorV1::IdempotencyConflict);
        }

        let terminal = if cancellation.is_cancelled() {
            terminal_error(
                SelfIterationTerminalDispositionV1::Cancelled,
                None,
                b"cancelled-before-topology-submit",
            )
        } else if deadline_expired(context.deadline_unix_millis) {
            terminal_error(
                SelfIterationTerminalDispositionV1::DeadlineExceeded,
                None,
                b"deadline-before-topology-submit",
            )
        } else {
            match producer.propose_topology(request, now_unix_seconds).await {
                Ok(receipt) => topology_success(&receipt),
                Err(error) => runtime_error(None, &error),
            }
        };
        self.persist_terminal(
            &context,
            envelope_digest,
            request_digest,
            idempotency_key,
            SelfIterationProposalKindV1::Topology,
            terminal,
            now_unix_seconds,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn persist_terminal(
        &mut self,
        context: &SelfIterationContextV1,
        envelope_digest: Digest32,
        request_digest: Digest32,
        idempotency_key: Digest32,
        proposal_kind: SelfIterationProposalKindV1,
        terminal: TerminalMaterialV1,
        observed_unix_seconds: u64,
    ) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
        let predecessor = self
            .journal
            .current_anchor()
            .map(|anchor| anchor.frame_digest)
            .unwrap_or(Digest32::ZERO);
        let receipt = SelfIterationTerminalReceiptV1 {
            sequence: 0,
            idempotency_key,
            envelope_digest,
            request_digest,
            proposal_id: context.proposal_id.clone(),
            proposal_kind,
            baseline_generation: context.baseline_generation,
            candidate_generation: context.candidate_generation,
            disposition: terminal.disposition,
            coverage_digest: terminal.coverage_digest,
            composition_digest: terminal.composition_digest,
            registry_frame_digest: terminal.registry_frame_digest,
            error_digest: terminal.error_digest,
            observed_unix_seconds,
            receipt_digest: Digest32::ZERO,
            predecessor_frame_digest: Digest32::ZERO,
            frame_digest: Digest32::ZERO,
        };
        self.journal.append(predecessor, receipt).map_err(Into::into)
    }
}

struct TerminalMaterialV1 {
    disposition: SelfIterationTerminalDispositionV1,
    coverage_digest: Option<Digest32>,
    composition_digest: Option<Digest32>,
    registry_frame_digest: Option<Digest32>,
    error_digest: Option<Digest32>,
}

fn parameter_success(
    coverage: &GeneratorCoverageReceiptV1,
    receipt: &ParameterPlasticityProductReceiptV1,
) -> TerminalMaterialV1 {
    TerminalMaterialV1 {
        disposition: SelfIterationTerminalDispositionV1::Committed,
        coverage_digest: Some(coverage.coverage_digest),
        composition_digest: Some(receipt.composition_digest),
        registry_frame_digest: Some(receipt.registry.frame_digest),
        error_digest: None,
    }
}

fn topology_success(receipt: &TopologyPlasticityProductReceiptV1) -> TerminalMaterialV1 {
    TerminalMaterialV1 {
        disposition: SelfIterationTerminalDispositionV1::Committed,
        coverage_digest: None,
        composition_digest: Some(receipt.composition_digest),
        registry_frame_digest: Some(receipt.durable.frame_digest),
        error_digest: None,
    }
}

fn runtime_error(
    coverage_digest: Option<Digest32>,
    error: &PlasticityRuntimeCallErrorV1,
) -> TerminalMaterialV1 {
    let disposition = match error {
        PlasticityRuntimeCallErrorV1::Unavailable | PlasticityRuntimeCallErrorV1::Closed => {
            SelfIterationTerminalDispositionV1::Unavailable
        }
        _ => SelfIterationTerminalDispositionV1::Rejected,
    };
    terminal_error(disposition, coverage_digest, format!("{error:?}").as_bytes())
}

fn terminal_error(
    disposition: SelfIterationTerminalDispositionV1,
    coverage_digest: Option<Digest32>,
    bytes: &[u8],
) -> TerminalMaterialV1 {
    TerminalMaterialV1 {
        disposition,
        coverage_digest,
        composition_digest: None,
        registry_frame_digest: None,
        error_digest: Some(Digest32::of_bytes(bytes)),
    }
}

fn validate_submission_context(
    context: &SelfIterationContextV1,
    now_unix_seconds: u64,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    context
        .envelope
        .validate()
        .map_err(SelfIterationCoordinatorErrorV1::InvalidEnvelope)?;
    if context.envelope.expiry_unix_seconds < now_unix_seconds {
        return Err(SelfIterationCoordinatorErrorV1::Expired);
    }
    if context.selected_artifact_digest.is_zero()
        || context.window.window_digest.is_zero()
        || context.mutation_grammar_digest.is_zero()
        || context.owner_frontier_digest.is_zero()
        || context.envelope.grammar_digest != context.mutation_grammar_digest
        || context.baseline_generation.next() != Ok(context.candidate_generation)
        || context.deadline_unix_millis == 0
    {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "self-iteration envelope/context",
        ));
    }
    digest_envelope(&context.envelope).map_err(Into::into)
}

fn deadline_expired(deadline_unix_millis: u64) -> bool {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    now >= u128::from(deadline_unix_millis)
}

fn digest_envelope(
    envelope: &IterationEnvelopeV1,
) -> Result<Digest32, SelfIterationJournalErrorV1> {
    let mut bytes = b"hepta.control-engineering.iteration-envelope.v1\0".to_vec();
    push_id(&mut bytes, &envelope.envelope_id)?;
    for digest in [
        envelope.base_commit,
        envelope.base_tree,
        envelope.objective_digest,
        envelope.grammar_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&envelope.maximum_files.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_diff_bytes.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_candidates.to_be_bytes());
    bytes.push(envelope.maximum_parallel_sandboxes);
    bytes.extend_from_slice(&envelope.expiry_unix_seconds.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn idempotency_key(
    envelope_digest: Digest32,
    context: &SelfIterationContextV1,
    kind: SelfIterationProposalKindV1,
) -> Result<Digest32, SelfIterationJournalErrorV1> {
    let mut bytes = b"hepta.control-engineering.plasticity-idempotency.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    push_id(&mut bytes, &context.proposal_id)?;
    bytes.extend_from_slice(&context.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&context.candidate_generation.get().to_be_bytes());
    bytes.push(match kind {
        SelfIterationProposalKindV1::Parameter => 0,
        SelfIterationProposalKindV1::Topology => 1,
    });
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_parameter_request(
    context: &SelfIterationContextV1,
    coverage: &GeneratorCoverageReceiptV1,
    request: &ParameterPlasticityProductRequestV1,
) -> Result<Digest32, SelfIterationJournalErrorV1> {
    let mut bytes = b"hepta.control-engineering.parameter-request.v1\0".to_vec();
    push_context(&mut bytes, context)?;
    for digest in [
        request.generated.generator_digest,
        request.admission.objective_digest,
        request.admission.artifact_registry_head_digest,
        request.admission.qualification_evidence_head_digest,
        request.admission.owner_evidence_set_digest,
        request.admission.dataset_digest,
        request.admission.update_rule_digest,
        request.admission.modulator_digest,
        request.admission.modulator_broadcast_digest,
        request.admission.eligibility_digest,
        request.expected_registry_predecessor,
        coverage.coverage_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_topology_request(
    context: &SelfIterationContextV1,
    request: &TopologyPlasticityProductRequestV1,
    generation_payload: &[u8],
) -> Result<Digest32, SelfIterationJournalErrorV1> {
    let mut bytes = b"hepta.control-engineering.topology-request.v1\0".to_vec();
    push_context(&mut bytes, context)?;
    bytes.extend_from_slice(Digest32::of_bytes(generation_payload).as_array());
    for digest in [
        request.admission.objective_digest,
        request.admission.artifact_registry_head_digest,
        request.admission.qualification_evidence_head_digest,
        request.admission.evaluation_receipt_digest,
        request.expected_registry_predecessor,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_context(
    bytes: &mut Vec<u8>,
    context: &SelfIterationContextV1,
) -> Result<(), SelfIterationJournalErrorV1> {
    push_id(bytes, &context.proposal_id)?;
    bytes.extend_from_slice(context.selected_artifact_digest.as_array());
    push_id(bytes, &context.window.window_id)?;
    bytes.extend_from_slice(context.window.window_digest.as_array());
    bytes.extend_from_slice(&context.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&context.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(context.mutation_grammar_digest.as_array());
    bytes.extend_from_slice(context.owner_frontier_digest.as_array());
    Ok(())
}

fn validate_context_values(
    scope_digest: Digest32,
    rollback_domain_digest: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<(), SelfIterationJournalErrorV1> {
    if scope_digest.is_zero() {
        return Err(SelfIterationJournalErrorV1::InvalidScope);
    }
    if rollback_domain_digest.is_zero() {
        return Err(SelfIterationJournalErrorV1::InvalidRollbackDomain);
    }
    if writer_fence == 0 {
        return Err(SelfIterationJournalErrorV1::InvalidFence);
    }
    if !(1..=MAX_RECORDS).contains(&maximum_records) {
        return Err(SelfIterationJournalErrorV1::InvalidLimit);
    }
    Ok(())
}

fn write_header(
    file: &mut File,
    header: &JournalHeaderWireV1,
) -> Result<u64, SelfIterationJournalErrorV1> {
    let payload = serde_json::to_vec(header)?;
    if payload.is_empty() || payload.len() > MAX_HEADER_BYTES {
        return Err(SelfIterationJournalErrorV1::Capacity);
    }
    let length = u32::try_from(payload.len())
        .map_err(|_| SelfIterationJournalErrorV1::Capacity)?;
    let digest = Digest32::of_bytes(&payload);
    file.seek(SeekFrom::Start(0))?;
    file.write_all(JOURNAL_MAGIC)
        .and_then(|_| file.write_all(&FORMAT_VERSION.to_be_bytes()))
        .and_then(|_| file.write_all(&length.to_be_bytes()))
        .and_then(|_| file.write_all(&payload))
        .and_then(|_| file.write_all(digest.as_array()))
        .and_then(|_| file.sync_all())
        .map_err(|_| SelfIterationJournalErrorV1::Indeterminate)?;
    Ok(8 + 2 + 4 + u64::from(length) + 32)
}

fn read_header(
    file: &mut File,
) -> Result<(JournalHeaderWireV1, u64), SelfIterationJournalErrorV1> {
    file.seek(SeekFrom::Start(0))?;
    let mut magic = [0_u8; 8];
    file.read_exact(&mut magic)?;
    if &magic != JOURNAL_MAGIC {
        return Err(SelfIterationJournalErrorV1::Corrupt);
    }
    let mut version = [0_u8; 2];
    file.read_exact(&mut version)?;
    if u16::from_be_bytes(version) != FORMAT_VERSION {
        return Err(SelfIterationJournalErrorV1::Corrupt);
    }
    let mut length_bytes = [0_u8; 4];
    file.read_exact(&mut length_bytes)?;
    let length = u32::from_be_bytes(length_bytes) as usize;
    if length == 0 || length > MAX_HEADER_BYTES {
        return Err(SelfIterationJournalErrorV1::Corrupt);
    }
    let mut payload = vec![0_u8; length];
    file.read_exact(&mut payload)?;
    let mut digest_bytes = [0_u8; 32];
    file.read_exact(&mut digest_bytes)?;
    if Digest32::of_bytes(&payload) != Digest32::from_array(digest_bytes) {
        return Err(SelfIterationJournalErrorV1::Corrupt);
    }
    let header = serde_json::from_slice(&payload)?;
    let end = 8_u64
        .checked_add(2)
        .and_then(|value| value.checked_add(4))
        .and_then(|value| value.checked_add(length as u64))
        .and_then(|value| value.checked_add(32))
        .ok_or(SelfIterationJournalErrorV1::Capacity)?;
    Ok((header, end))
}

fn encode_frame(
    receipt: &SelfIterationTerminalReceiptV1,
) -> Result<Vec<u8>, SelfIterationJournalErrorV1> {
    let frame = TerminalFrameWireV1 {
        sequence: receipt.sequence,
        predecessor_frame_digest: receipt.predecessor_frame_digest.to_string(),
        semantics: terminal_semantics_wire(receipt),
        receipt_digest: receipt.receipt_digest.to_string(),
    };
    let payload = serde_json::to_vec(&frame)?;
    if payload.is_empty() || payload.len() > MAX_FRAME_BYTES {
        return Err(SelfIterationJournalErrorV1::Capacity);
    }
    Ok(payload)
}

fn decode_frame(
    payload: &[u8],
    frame_digest: Digest32,
    expected_sequence: u64,
    expected_predecessor: Digest32,
) -> Result<SelfIterationTerminalReceiptV1, SelfIterationJournalErrorV1> {
    let frame: TerminalFrameWireV1 = serde_json::from_slice(payload)?;
    if frame.sequence != expected_sequence
        || parse_digest(&frame.predecessor_frame_digest)? != expected_predecessor
    {
        return Err(SelfIterationJournalErrorV1::Corrupt);
    }
    let mut frame_material = b"hepta.control-engineering.self-iteration-frame.v1\0".to_vec();
    frame_material.extend_from_slice(expected_predecessor.as_array());
    frame_material.extend_from_slice(payload);
    if Digest32::of_bytes(&frame_material) != frame_digest {
        return Err(SelfIterationJournalErrorV1::Corrupt);
    }
    let mut receipt = receipt_from_wire(frame)?;
    receipt.frame_digest = frame_digest;
    if digest_terminal_semantics(&receipt)? != receipt.receipt_digest {
        return Err(SelfIterationJournalErrorV1::Corrupt);
    }
    Ok(receipt)
}

fn terminal_semantics_wire(receipt: &SelfIterationTerminalReceiptV1) -> TerminalSemanticsWireV1 {
    TerminalSemanticsWireV1 {
        idempotency_key: receipt.idempotency_key.to_string(),
        envelope_digest: receipt.envelope_digest.to_string(),
        request_digest: receipt.request_digest.to_string(),
        proposal_id: receipt.proposal_id.to_string(),
        proposal_kind: proposal_kind_name(receipt.proposal_kind).to_string(),
        baseline_generation: receipt.baseline_generation.get(),
        candidate_generation: receipt.candidate_generation.get(),
        disposition: disposition_name(receipt.disposition).to_string(),
        coverage_digest: receipt.coverage_digest.map(|value| value.to_string()),
        composition_digest: receipt.composition_digest.map(|value| value.to_string()),
        registry_frame_digest: receipt.registry_frame_digest.map(|value| value.to_string()),
        error_digest: receipt.error_digest.map(|value| value.to_string()),
        observed_unix_seconds: receipt.observed_unix_seconds,
    }
}

fn receipt_from_wire(
    frame: TerminalFrameWireV1,
) -> Result<SelfIterationTerminalReceiptV1, SelfIterationJournalErrorV1> {
    let semantics = frame.semantics;
    Ok(SelfIterationTerminalReceiptV1 {
        sequence: frame.sequence,
        idempotency_key: parse_digest(&semantics.idempotency_key)?,
        envelope_digest: parse_digest(&semantics.envelope_digest)?,
        request_digest: parse_digest(&semantics.request_digest)?,
        proposal_id: StableId::new(semantics.proposal_id)
            .map_err(|_| SelfIterationJournalErrorV1::Identity)?,
        proposal_kind: parse_proposal_kind(&semantics.proposal_kind)?,
        baseline_generation: Generation::new(semantics.baseline_generation)
            .map_err(|_| SelfIterationJournalErrorV1::Corrupt)?,
        candidate_generation: Generation::new(semantics.candidate_generation)
            .map_err(|_| SelfIterationJournalErrorV1::Corrupt)?,
        disposition: parse_disposition(&semantics.disposition)?,
        coverage_digest: parse_optional_digest(semantics.coverage_digest)?,
        composition_digest: parse_optional_digest(semantics.composition_digest)?,
        registry_frame_digest: parse_optional_digest(semantics.registry_frame_digest)?,
        error_digest: parse_optional_digest(semantics.error_digest)?,
        observed_unix_seconds: semantics.observed_unix_seconds,
        receipt_digest: parse_digest(&frame.receipt_digest)?,
        predecessor_frame_digest: parse_digest(&frame.predecessor_frame_digest)?,
        frame_digest: Digest32::ZERO,
    })
}

fn digest_terminal_semantics(
    receipt: &SelfIterationTerminalReceiptV1,
) -> Result<Digest32, SelfIterationJournalErrorV1> {
    let payload = serde_json::to_vec(&terminal_semantics_wire(receipt))?;
    let mut bytes = b"hepta.control-engineering.self-iteration-terminal.v1\0".to_vec();
    bytes.extend_from_slice(&receipt.sequence.to_be_bytes());
    bytes.extend_from_slice(receipt.predecessor_frame_digest.as_array());
    bytes.extend_from_slice(&payload);
    Ok(Digest32::of_bytes(&bytes))
}

const fn proposal_kind_name(kind: SelfIterationProposalKindV1) -> &'static str {
    match kind {
        SelfIterationProposalKindV1::Parameter => "parameter",
        SelfIterationProposalKindV1::Topology => "topology",
    }
}

fn parse_proposal_kind(
    value: &str,
) -> Result<SelfIterationProposalKindV1, SelfIterationJournalErrorV1> {
    match value {
        "parameter" => Ok(SelfIterationProposalKindV1::Parameter),
        "topology" => Ok(SelfIterationProposalKindV1::Topology),
        _ => Err(SelfIterationJournalErrorV1::Corrupt),
    }
}

const fn disposition_name(value: SelfIterationTerminalDispositionV1) -> &'static str {
    match value {
        SelfIterationTerminalDispositionV1::Committed => "committed",
        SelfIterationTerminalDispositionV1::ZeroEligibleSignals => "zero_eligible_signals",
        SelfIterationTerminalDispositionV1::PolicyDisabledUpdates => "policy_disabled_updates",
        SelfIterationTerminalDispositionV1::Rejected => "rejected",
        SelfIterationTerminalDispositionV1::Unavailable => "unavailable",
        SelfIterationTerminalDispositionV1::Cancelled => "cancelled",
        SelfIterationTerminalDispositionV1::DeadlineExceeded => "deadline_exceeded",
        SelfIterationTerminalDispositionV1::Indeterminate => "indeterminate",
    }
}

fn parse_disposition(
    value: &str,
) -> Result<SelfIterationTerminalDispositionV1, SelfIterationJournalErrorV1> {
    match value {
        "committed" => Ok(SelfIterationTerminalDispositionV1::Committed),
        "zero_eligible_signals" => Ok(SelfIterationTerminalDispositionV1::ZeroEligibleSignals),
        "policy_disabled_updates" => Ok(SelfIterationTerminalDispositionV1::PolicyDisabledUpdates),
        "rejected" => Ok(SelfIterationTerminalDispositionV1::Rejected),
        "unavailable" => Ok(SelfIterationTerminalDispositionV1::Unavailable),
        "cancelled" => Ok(SelfIterationTerminalDispositionV1::Cancelled),
        "deadline_exceeded" => Ok(SelfIterationTerminalDispositionV1::DeadlineExceeded),
        "indeterminate" => Ok(SelfIterationTerminalDispositionV1::Indeterminate),
        _ => Err(SelfIterationJournalErrorV1::Corrupt),
    }
}

fn parse_digest(value: &str) -> Result<Digest32, SelfIterationJournalErrorV1> {
    Digest32::from_str(value).map_err(|_| SelfIterationJournalErrorV1::Corrupt)
}

fn parse_optional_digest(
    value: Option<String>,
) -> Result<Option<Digest32>, SelfIterationJournalErrorV1> {
    value.map(|value| parse_digest(&value)).transpose()
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), SelfIterationJournalErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| SelfIterationJournalErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn validate_parent(path: &Path) -> Result<(), SelfIterationJournalErrorV1> {
    if !path.is_absolute() {
        return Err(SelfIterationJournalErrorV1::InvalidPath);
    }
    let parent = path
        .parent()
        .ok_or(SelfIterationJournalErrorV1::InvalidPath)?;
    if parent.canonicalize()? != parent {
        return Err(SelfIterationJournalErrorV1::InvalidPath);
    }
    Ok(())
}

fn secure_create_new(path: &Path) -> Result<File, SelfIterationJournalErrorV1> {
    validate_parent(path)?;
    let mut options = OpenOptions::new();
    options.create_new(true).read(true).write(true);
    #[cfg(unix)]
    {
        options.mode(0o600);
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    options.open(path).map_err(Into::into)
}

fn secure_open_existing(path: &Path) -> Result<File, SelfIterationJournalErrorV1> {
    if !path.is_absolute() {
        return Err(SelfIterationJournalErrorV1::InvalidPath);
    }
    let before = std::fs::symlink_metadata(path)?;
    if before.file_type().is_symlink() || !before.is_file() {
        return Err(SelfIterationJournalErrorV1::NotRegular);
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    let file = options.open(path)?;
    let after = file.metadata()?;
    #[cfg(unix)]
    if before.dev() != after.dev() || before.ino() != after.ino() {
        return Err(SelfIterationJournalErrorV1::ContextMismatch);
    }
    Ok(file)
}

fn sync_parent(path: &Path) -> Result<(), SelfIterationJournalErrorV1> {
    #[cfg(unix)]
    {
        let parent = path
            .parent()
            .ok_or(SelfIterationJournalErrorV1::InvalidPath)?;
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

fn storage_identity_digest(file: &File) -> Result<Digest32, SelfIterationJournalErrorV1> {
    let metadata = file.metadata()?;
    let mut bytes = b"hepta.control-engineering.storage-identity.v1\0".to_vec();
    #[cfg(unix)]
    {
        bytes.extend_from_slice(&metadata.dev().to_be_bytes());
        bytes.extend_from_slice(&metadata.ino().to_be_bytes());
    }
    #[cfg(not(unix))]
    bytes.extend_from_slice(&metadata.len().to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }
    fn receipt(key: &[u8], request: &[u8]) -> SelfIterationTerminalReceiptV1 {
        SelfIterationTerminalReceiptV1 {
            sequence: 0,
            idempotency_key: digest(key),
            envelope_digest: digest(b"envelope"),
            request_digest: digest(request),
            proposal_id: id("proposal:1"),
            proposal_kind: SelfIterationProposalKindV1::Parameter,
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            disposition: SelfIterationTerminalDispositionV1::Committed,
            coverage_digest: Some(digest(b"coverage")),
            composition_digest: Some(digest(b"composition")),
            registry_frame_digest: Some(digest(b"registry")),
            error_digest: None,
            observed_unix_seconds: 1,
            receipt_digest: Digest32::ZERO,
            predecessor_frame_digest: Digest32::ZERO,
            frame_digest: Digest32::ZERO,
        }
    }

    #[test]
    fn journal_is_idempotent_and_reopens_from_external_anchor() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("terminal.journal");
        let scope = digest(b"scope");
        let rollback = digest(b"rollback-domain");
        let anchor = {
            let mut journal = SelfIterationReceiptJournalV1::create_new(
                &path, scope, rollback, 7, 8,
            )
            .expect("create");
            let first = journal
                .append(Digest32::ZERO, receipt(b"key", b"request"))
                .expect("append");
            let replay = journal
                .append(first.frame_digest, receipt(b"key", b"request"))
                .expect("replay");
            assert_eq!(first, replay);
            journal.current_anchor().expect("anchor")
        };
        let journal = SelfIterationReceiptJournalV1::reopen_anchored_path(
            &path, scope, rollback, 7, 8, anchor,
        )
        .expect("reopen");
        assert_eq!(journal.current_anchor(), Some(anchor));
        assert!(journal.get(digest(b"key")).is_some());
    }

    #[test]
    fn same_idempotency_key_with_semantic_drift_conflicts() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("terminal.journal");
        let mut journal = SelfIterationReceiptJournalV1::create_new(
            &path,
            digest(b"scope"),
            digest(b"rollback-domain"),
            9,
            8,
        )
        .expect("create");
        let first = journal
            .append(Digest32::ZERO, receipt(b"key", b"request-a"))
            .expect("first");
        assert_eq!(
            journal
                .append(first.frame_digest, receipt(b"key", b"request-b"))
                .expect_err("conflict"),
            SelfIterationJournalErrorV1::Conflict
        );
    }

    #[test]
    fn incomplete_tail_is_repaired_after_anchor_validation() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("terminal.journal");
        let scope = digest(b"scope");
        let rollback = digest(b"rollback-domain");
        let anchor = {
            let mut journal = SelfIterationReceiptJournalV1::create_new(
                &path, scope, rollback, 11, 8,
            )
            .expect("create");
            journal
                .append(Digest32::ZERO, receipt(b"key", b"request"))
                .expect("append");
            journal.current_anchor().expect("anchor")
        };
        let valid_length = std::fs::metadata(&path).expect("metadata").len();
        {
            let mut file = OpenOptions::new().append(true).open(&path).expect("open");
            file.write_all(&[0, 0, 0]).expect("tail");
            file.sync_all().expect("sync");
        }
        let journal = SelfIterationReceiptJournalV1::reopen_anchored_path(
            &path, scope, rollback, 11, 8, anchor,
        )
        .expect("repair");
        drop(journal);
        assert_eq!(
            std::fs::metadata(&path).expect("metadata").len(),
            valid_length
        );
    }

    #[cfg(unix)]
    #[test]
    fn secure_open_rejects_symlink_targets() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().expect("tempdir");
        let target = directory.path().join("target");
        let link = directory.path().join("link");
        std::fs::write(&target, b"target").expect("write");
        symlink(&target, &link).expect("symlink");
        assert!(matches!(
            secure_open_existing(&link),
            Err(SelfIterationJournalErrorV1::NotRegular)
        ));
    }
}
