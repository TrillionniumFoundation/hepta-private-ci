//! Non-test control.engineering coordinator for governed plasticity iteration.
//!
//! The coordinator validates one `IterationEnvelopeV1`, freezes the exact
//! artifact/window/grammar/generation/owner frontier, verifies generator coverage
//! under an independent Observer, and then submits through Agentd's named
//! learning-plasticity producer. It never receives a registry writer and exposes
//! no selection, installation, activation, promotion or release operation.

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
use std::time::Duration;

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_evaluation_signing_payload_v1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::build_generator_coverage_receipt_v1;
use codex_hepta_plasticity::generator_coverage_signing_payload_v1;
use codex_hepta_plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::Instant;
use tokio::time::timeout_at;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;
use crate::PlasticityRuntimeCallErrorV1;

const MAX_COORDINATOR_QUEUE: usize = 64;
const JOURNAL_MAGIC: &[u8; 8] = b"HPTITER1";
const FRAME_MAGIC: &[u8; 8] = b"HPTITFR1";
const JOURNAL_VERSION: u16 = 1;
const HEADER_PREFIX_BYTES: usize = 8 + 2 + 32 + 8 + 4;
const HEADER_BYTES: usize = HEADER_PREFIX_BYTES + 32;
const MAX_JOURNAL_RECORDS: usize = 65_536;
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 4_096;
const MAX_FILE_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum IterationPlasticityKindV1 {
    Parameter,
    Topology,
}
impl IterationPlasticityKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Parameter => 0,
            Self::Topology => 1,
        }
    }
    fn from_tag(value: u8) -> Result<Self, DurableIterationJournalErrorV1> {
        match value {
            0 => Ok(Self::Parameter),
            1 => Ok(Self::Topology),
            _ => Err(DurableIterationJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum IterationPlasticityTerminalDispositionV1 {
    ParameterCommitted,
    TopologyCommitted,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
    IncompleteCoverage,
}
impl IterationPlasticityTerminalDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::ParameterCommitted => 0,
            Self::TopologyCommitted => 1,
            Self::ZeroEligibleSignals => 2,
            Self::PolicyDisabledUpdates => 3,
            Self::IncompleteCoverage => 4,
        }
    }
    fn from_tag(value: u8) -> Result<Self, DurableIterationJournalErrorV1> {
        match value {
            0 => Ok(Self::ParameterCommitted),
            1 => Ok(Self::TopologyCommitted),
            2 => Ok(Self::ZeroEligibleSignals),
            3 => Ok(Self::PolicyDisabledUpdates),
            4 => Ok(Self::IncompleteCoverage),
            _ => Err(DurableIterationJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenPlasticityContextV1 {
    pub envelope_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub grammar_digest: Digest32,
    pub owner_frontier_digest: Digest32,
    pub freeze_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationPlasticityTerminalReceiptV1 {
    pub sequence: u64,
    pub envelope_id: StableId,
    pub envelope_digest: Digest32,
    pub freeze_digest: Digest32,
    pub proposal_id: StableId,
    pub candidate_generation: u64,
    pub kind: IterationPlasticityKindV1,
    pub disposition: IterationPlasticityTerminalDispositionV1,
    pub request_digest: Digest32,
    pub terminal_payload_digest: Digest32,
    pub coverage_digest: Digest32,
    pub observed_unix_seconds: u64,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableIterationJournalErrorV1 {
    Busy,
    NotRegular,
    InvalidScope,
    InvalidFence,
    InvalidLimit,
    BootstrapRequiresEmptyFile,
    ContextMismatch,
    Capacity,
    Conflict,
    Corrupt,
    Poisoned,
    Indeterminate(std::io::ErrorKind),
    Io(std::io::ErrorKind),
    Arithmetic,
}
impl fmt::Display for DurableIterationJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for DurableIterationJournalErrorV1 {}
impl From<std::io::Error> for DurableIterationJournalErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, DurableIterationJournalErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(DurableIterationJournalErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableIterationJournalErrorV1::Busy),
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

/// Durable, checksum-chained terminal journal owned by control.engineering.
/// It stores only terminal coordination receipts and cannot mutate proposal
/// registries or selected artifacts.
pub struct DurableIterationTerminalJournalV1 {
    file: LockedFile,
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
    by_identity: BTreeMap<Digest32, IterationPlasticityTerminalReceiptV1>,
    frame_digests: Vec<Digest32>,
    poisoned: bool,
}

impl DurableIterationTerminalJournalV1 {
    pub fn bootstrap_new(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableIterationJournalErrorV1> {
        Self::open_inner(file, scope, writer_fence, maximum_records, true)
    }

    pub fn reopen(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableIterationJournalErrorV1> {
        Self::open_inner(file, scope, writer_fence, maximum_records, false)
    }

    fn open_inner(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        bootstrap: bool,
    ) -> Result<Self, DurableIterationJournalErrorV1> {
        validate_journal_context(scope, writer_fence, maximum_records)?;
        let expected_header = encode_header(scope, writer_fence, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let physical_length = file.metadata()?.len();
        if physical_length > MAX_FILE_BYTES {
            return Err(DurableIterationJournalErrorV1::Capacity);
        }
        if bootstrap && physical_length != 0 {
            return Err(DurableIterationJournalErrorV1::BootstrapRequiresEmptyFile);
        }
        if physical_length == 0 {
            if !bootstrap {
                return Err(DurableIterationJournalErrorV1::ContextMismatch);
            }
            write_durable(&mut file, &expected_header)?;
        } else {
            if physical_length < HEADER_BYTES as u64 {
                return Err(DurableIterationJournalErrorV1::Corrupt);
            }
            file.seek(SeekFrom::Start(0))?;
            let mut header = vec![0_u8; HEADER_BYTES];
            file.read_exact(&mut header)?;
            validate_header(&header)?;
            if header != expected_header {
                return Err(DurableIterationJournalErrorV1::ContextMismatch);
            }
        }

        let mut journal = Self {
            file,
            scope,
            writer_fence,
            maximum_records,
            by_identity: BTreeMap::new(),
            frame_digests: Vec::new(),
            poisoned: false,
        };
        let physical_length = journal.file.metadata()?.len();
        let mut offset = HEADER_BYTES as u64;
        let mut incomplete_tail = false;
        while offset < physical_length {
            if physical_length - offset < 4 {
                incomplete_tail = true;
                break;
            }
            journal.file.seek(SeekFrom::Start(offset))?;
            let mut len = [0_u8; 4];
            journal.file.read_exact(&mut len)?;
            let frame_length = u32::from_be_bytes(len) as usize;
            if frame_length == 0 || frame_length > MAX_FRAME_BYTES {
                return Err(DurableIterationJournalErrorV1::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_length as u64)
                .ok_or(DurableIterationJournalErrorV1::Capacity)?;
            if physical_length - offset < total {
                incomplete_tail = true;
                break;
            }
            if journal.frame_digests.len() >= maximum_records {
                return Err(DurableIterationJournalErrorV1::Capacity);
            }
            let mut frame = vec![0_u8; frame_length];
            journal.file.read_exact(&mut frame)?;
            let receipt = decode_frame(&frame)?;
            let expected_sequence = journal.frame_digests.len() as u64 + 1;
            let expected_predecessor = journal
                .frame_digests
                .last()
                .copied()
                .unwrap_or(Digest32::ZERO);
            if receipt.sequence != expected_sequence
                || receipt.predecessor_frame_digest != expected_predecessor
            {
                return Err(DurableIterationJournalErrorV1::Corrupt);
            }
            let identity = terminal_identity_digest(&receipt)?;
            if journal.by_identity.insert(identity, receipt.clone()).is_some() {
                return Err(DurableIterationJournalErrorV1::Corrupt);
            }
            journal.frame_digests.push(receipt.frame_digest);
            offset = offset
                .checked_add(total)
                .ok_or(DurableIterationJournalErrorV1::Capacity)?;
        }
        if incomplete_tail {
            journal
                .file
                .set_len(offset)
                .and_then(|_| journal.file.sync_all())
                .map_err(|error| DurableIterationJournalErrorV1::Indeterminate(error.kind()))?;
        }
        Ok(journal)
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope
    }

    #[must_use]
    pub const fn writer_fence(&self) -> u64 {
        self.writer_fence
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.by_identity.len()
    }

    pub fn lookup(
        &self,
        template: &IterationPlasticityTerminalReceiptV1,
    ) -> Result<Option<&IterationPlasticityTerminalReceiptV1>, DurableIterationJournalErrorV1> {
        Ok(self.by_identity.get(&terminal_identity_digest(template)?))
    }

    pub fn append(
        &mut self,
        mut receipt: IterationPlasticityTerminalReceiptV1,
    ) -> Result<IterationPlasticityTerminalReceiptV1, DurableIterationJournalErrorV1> {
        if self.poisoned {
            return Err(DurableIterationJournalErrorV1::Poisoned);
        }
        validate_terminal_template(&receipt)?;
        let identity = terminal_identity_digest(&receipt)?;
        if let Some(existing) = self.by_identity.get(&identity) {
            if existing.envelope_digest == receipt.envelope_digest
                && existing.freeze_digest == receipt.freeze_digest
                && existing.request_digest == receipt.request_digest
                && existing.terminal_payload_digest == receipt.terminal_payload_digest
                && existing.coverage_digest == receipt.coverage_digest
                && existing.disposition == receipt.disposition
            {
                return Ok(existing.clone());
            }
            return Err(DurableIterationJournalErrorV1::Conflict);
        }
        if self.by_identity.len() >= self.maximum_records {
            return Err(DurableIterationJournalErrorV1::Capacity);
        }
        receipt.sequence = self.frame_digests.len() as u64 + 1;
        receipt.predecessor_frame_digest = self
            .frame_digests
            .last()
            .copied()
            .unwrap_or(Digest32::ZERO);
        receipt.frame_digest = Digest32::ZERO;
        let frame = encode_frame(&mut receipt)?;
        let length = u32::try_from(frame.len())
            .map_err(|_| DurableIterationJournalErrorV1::Arithmetic)?;
        let write_result = self
            .file
            .seek(SeekFrom::End(0))
            .and_then(|_| self.file.write_all(&length.to_be_bytes()))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|_| self.file.sync_all());
        if let Err(error) = write_result {
            self.poisoned = true;
            return Err(DurableIterationJournalErrorV1::Indeterminate(error.kind()));
        }
        self.frame_digests.push(receipt.frame_digest);
        self.by_identity.insert(identity, receipt.clone());
        Ok(receipt)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlEngineeringParameterIterationRequestV1 {
    pub envelope: IterationEnvelopeV1,
    pub frozen: FrozenPlasticityContextV1,
    pub product: ParameterPlasticityProductRequestV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub coverage_attestation: SignedLearningEvidenceV1,
    /// Queue admission must occur before this logical Unix-second deadline.
    pub deadline_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlEngineeringTopologyIterationRequestV1 {
    pub envelope: IterationEnvelopeV1,
    pub frozen: FrozenPlasticityContextV1,
    pub product: TopologyPlasticityProductRequestV1,
    pub deadline_unix_seconds: u64,
}

#[derive(Debug)]
pub enum ControlEngineeringIterationErrorV1 {
    Closed,
    DeadlineExceeded,
    Cancelled,
    InvalidEnvelope(String),
    Binding(&'static str),
    Coverage(GeneratorCoverageErrorV1),
    Evidence(SignedEvidenceError),
    Product(PlasticityRuntimeCallErrorV1),
    Journal(DurableIterationJournalErrorV1),
    Arithmetic,
}
impl fmt::Display for ControlEngineeringIterationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ControlEngineeringIterationErrorV1 {}
impl From<GeneratorCoverageErrorV1> for ControlEngineeringIterationErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<SignedEvidenceError> for ControlEngineeringIterationErrorV1 {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<PlasticityRuntimeCallErrorV1> for ControlEngineeringIterationErrorV1 {
    fn from(value: PlasticityRuntimeCallErrorV1) -> Self {
        Self::Product(value)
    }
}
impl From<DurableIterationJournalErrorV1> for ControlEngineeringIterationErrorV1 {
    fn from(value: DurableIterationJournalErrorV1) -> Self {
        Self::Journal(value)
    }
}

#[derive(Clone)]
pub struct ControlEngineeringIterationHandleV1 {
    sender: mpsc::Sender<ControlEngineeringIterationCommandV1>,
}

pub struct ControlEngineeringIterationBootstrapV1 {
    receiver: mpsc::Receiver<ControlEngineeringIterationCommandV1>,
    journal: DurableIterationTerminalJournalV1,
}

enum ControlEngineeringIterationCommandV1 {
    Parameter {
        request: Box<ControlEngineeringParameterIterationRequestV1>,
        now: u64,
        deadline: Instant,
        response: oneshot::Sender<
            Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1>,
        >,
    },
    Topology {
        request: Box<ControlEngineeringTopologyIterationRequestV1>,
        now: u64,
        deadline: Instant,
        response: oneshot::Sender<
            Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1>,
        >,
    },
}

pub fn control_engineering_iteration_channel_v1(
    capacity: usize,
    journal: DurableIterationTerminalJournalV1,
) -> Result<
    (
        ControlEngineeringIterationHandleV1,
        ControlEngineeringIterationBootstrapV1,
    ),
    AgentdError,
> {
    if !(1..=MAX_COORDINATOR_QUEUE).contains(&capacity) {
        return Err(AgentdError::Invalid(format!(
            "control.engineering iteration queue capacity must be within 1..={MAX_COORDINATOR_QUEUE}"
        )));
    }
    let (sender, receiver) = mpsc::channel(capacity);
    Ok((
        ControlEngineeringIterationHandleV1 { sender },
        ControlEngineeringIterationBootstrapV1 { receiver, journal },
    ))
}

impl ControlEngineeringIterationHandleV1 {
    pub async fn submit_parameter(
        &self,
        request: ControlEngineeringParameterIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        let deadline = logical_deadline(now, request.deadline_unix_seconds)?;
        let (response, receive) = oneshot::channel();
        timeout_at(
            deadline,
            self.sender.send(ControlEngineeringIterationCommandV1::Parameter {
                request: Box::new(request),
                now,
                deadline,
                response,
            }),
        )
        .await
        .map_err(|_| ControlEngineeringIterationErrorV1::DeadlineExceeded)?
        .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?
    }

    pub async fn submit_topology(
        &self,
        request: ControlEngineeringTopologyIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        let deadline = logical_deadline(now, request.deadline_unix_seconds)?;
        let (response, receive) = oneshot::channel();
        timeout_at(
            deadline,
            self.sender.send(ControlEngineeringIterationCommandV1::Topology {
                request: Box::new(request),
                now,
                deadline,
                response,
            }),
        )
        .await
        .map_err(|_| ControlEngineeringIterationErrorV1::DeadlineExceeded)?
        .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?
    }
}

impl ControlEngineeringIterationBootstrapV1 {
    pub(crate) async fn run(
        mut self,
        state: std::sync::Arc<AgentdState>,
        verifier: LearningEvidenceVerifierV1,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                command = self.receiver.recv() => command,
            };
            let Some(command) = command else {
                cancellation.cancelled().await;
                return Ok(());
            };
            match command {
                ControlEngineeringIterationCommandV1::Parameter {
                    request,
                    now,
                    deadline,
                    response,
                } => {
                    if response.is_closed() {
                        continue;
                    }
                    let result = if Instant::now() >= deadline {
                        Err(ControlEngineeringIterationErrorV1::DeadlineExceeded)
                    } else {
                        self.coordinate_parameter(&state, &verifier, *request, now)
                            .await
                    };
                    let _ = response.send(result);
                }
                ControlEngineeringIterationCommandV1::Topology {
                    request,
                    now,
                    deadline,
                    response,
                } => {
                    if response.is_closed() {
                        continue;
                    }
                    let result = if Instant::now() >= deadline {
                        Err(ControlEngineeringIterationErrorV1::DeadlineExceeded)
                    } else {
                        self.coordinate_topology(&state, &verifier, *request, now)
                            .await
                    };
                    let _ = response.send(result);
                }
            }
        }
    }

    async fn coordinate_parameter(
        &mut self,
        state: &AgentdState,
        verifier: &LearningEvidenceVerifierV1,
        request: ControlEngineeringParameterIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        validate_envelope(&request.envelope, now, request.deadline_unix_seconds)?;
        verify_generated_parameter_candidates_v3(
            request.product.generator_profile.clone(),
            &request.product.generated,
        )
        .map_err(|_| ControlEngineeringIterationErrorV1::Binding("generated candidate set"))?;
        let frozen = freeze_parameter_context_v1(&request.envelope, &request.product)?;
        if frozen != request.frozen {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "frozen parameter context",
            ));
        }
        if request.product.generated.candidates.len()
            > request.envelope.maximum_candidates as usize
        {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "iteration candidate budget",
            ));
        }
        let expected_coverage = build_generator_coverage_receipt_v1(
            &request.product.generator_profile,
            frozen.owner_frontier_digest,
        )?;
        if expected_coverage != request.coverage {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "generator coverage",
            ));
        }
        let coverage_payload = generator_coverage_signing_payload_v1(&request.coverage)?;
        let coverage_observer = verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &request.coverage_attestation,
            &coverage_payload,
            now,
        )?;
        let admission_payload =
            plasticity_admission_signing_payload_v1(&request.product.admission);
        let admission_observer = verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &request.product.admission_attestation,
            &admission_payload,
            now,
        )?;
        if coverage_observer.principal() != admission_observer.principal()
            || coverage_observer.controller_id() != admission_observer.controller_id()
            || request.coverage_attestation.objective_digest != request.envelope.objective_digest
            || request.product.admission_attestation.objective_digest
                != request.envelope.objective_digest
        {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "coverage observer",
            ));
        }

        let request_digest = parameter_iteration_request_digest(&request)?;
        let (disposition, terminal_payload_digest) = match request.coverage.disposition {
            GeneratorCoverageDispositionV1::Complete => {
                let product = state
                    .submit_parameter_plasticity_v1(request.product.clone(), now)
                    .await?;
                (
                    IterationPlasticityTerminalDispositionV1::ParameterCommitted,
                    parameter_product_digest(&product),
                )
            }
            GeneratorCoverageDispositionV1::ZeroEligibleSignals => (
                IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals,
                coverage_terminal_digest(
                    IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals,
                    &request.coverage,
                    frozen.freeze_digest,
                ),
            ),
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates => (
                IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates,
                coverage_terminal_digest(
                    IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates,
                    &request.coverage,
                    frozen.freeze_digest,
                ),
            ),
            GeneratorCoverageDispositionV1::IncompleteSignals => (
                IterationPlasticityTerminalDispositionV1::IncompleteCoverage,
                coverage_terminal_digest(
                    IterationPlasticityTerminalDispositionV1::IncompleteCoverage,
                    &request.coverage,
                    frozen.freeze_digest,
                ),
            ),
        };
        let template = terminal_template(
            &request.envelope,
            &frozen,
            request.product.proposal_id.clone(),
            IterationPlasticityKindV1::Parameter,
            disposition,
            request_digest,
            terminal_payload_digest,
            request.coverage.coverage_digest,
            now,
        )?;
        self.journal.append(template).map_err(Into::into)
    }

    async fn coordinate_topology(
        &mut self,
        state: &AgentdState,
        verifier: &LearningEvidenceVerifierV1,
        request: ControlEngineeringTopologyIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        validate_envelope(&request.envelope, now, request.deadline_unix_seconds)?;
        let frozen = freeze_topology_context_v1(&request.envelope, &request.product)?;
        if frozen != request.frozen {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "frozen topology context",
            ));
        }
        if request.product.changes.len().saturating_add(1)
            > request.envelope.maximum_candidates as usize
        {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "iteration topology candidate budget",
            ));
        }
        let generation_payload = topology_generation_signing_payload_v1(&request.product)
            .map_err(|_| ControlEngineeringIterationErrorV1::Binding("topology generation"))?;
        let admission_payload = topology_admission_signing_payload_v1(&request.product.admission);
        let evaluation_payload = topology_evaluation_signing_payload_v1(&request.product.admission);
        let generator = verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &request.product.generator_attestation,
            &generation_payload,
            now,
        )?;
        let observer = verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &request.product.observer_attestation,
            &admission_payload,
            now,
        )?;
        let evaluator = verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &request.product.evaluator_attestation,
            &evaluation_payload,
            now,
        )?;
        verify_signed_role_separation(&generator, &observer, now)?;
        verify_signed_role_separation(&generator, &evaluator, now)?;
        verify_signed_independent_roles_v1(&observer, &evaluator, now)?;
        if request.product.admission.objective_digest != request.envelope.objective_digest {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "topology objective",
            ));
        }

        let request_digest = topology_iteration_request_digest(&request)?;
        let product = state
            .submit_topology_plasticity_v1(request.product.clone(), now)
            .await?;
        let template = terminal_template(
            &request.envelope,
            &frozen,
            request.product.proposal_id.clone(),
            IterationPlasticityKindV1::Topology,
            IterationPlasticityTerminalDispositionV1::TopologyCommitted,
            request_digest,
            topology_product_digest(&product),
            Digest32::of_bytes(b"hepta.control-engineering.topology-coverage.not-applicable.v1"),
            now,
        )?;
        self.journal.append(template).map_err(Into::into)
    }
}

pub fn freeze_parameter_context_v1(
    envelope: &IterationEnvelopeV1,
    product: &ParameterPlasticityProductRequestV1,
) -> Result<FrozenPlasticityContextV1, ControlEngineeringIterationErrorV1> {
    if product.generator_profile.mutation_policy.mutation_grammar_digest
        != envelope.grammar_digest
        || product.admission.objective_digest != envelope.objective_digest
        || product.generator_profile.selected_artifact_digest
            != product.admission.selected_artifact_digest
        || product.generator_profile.window != product.admission.window
        || product.generated.selected_artifact_digest
            != product.admission.selected_artifact_digest
        || product.generated.window != product.admission.window
        || product.admission.owner_evidence_set_digest.is_zero()
    {
        return Err(ControlEngineeringIterationErrorV1::Binding(
            "parameter freeze inputs",
        ));
    }
    freeze_context(
        envelope,
        product.admission.selected_artifact_digest,
        product.admission.window.clone(),
        product.admission.baseline_generation,
        product.admission.candidate_generation,
        product.admission.owner_evidence_set_digest,
    )
}

pub fn freeze_topology_context_v1(
    envelope: &IterationEnvelopeV1,
    product: &TopologyPlasticityProductRequestV1,
) -> Result<FrozenPlasticityContextV1, ControlEngineeringIterationErrorV1> {
    if product.admission.objective_digest != envelope.objective_digest
        || product.selected_artifact_digest != product.admission.selected_artifact_digest
        || product.window != product.admission.window
        || product.baseline_generation != product.admission.baseline_generation
        || product.candidate_generation != product.admission.candidate_generation
    {
        return Err(ControlEngineeringIterationErrorV1::Binding(
            "topology freeze inputs",
        ));
    }
    let mut frontier = b"hepta.control-engineering.topology-owner-frontier.v1\0".to_vec();
    for digest in [
        product.admission.artifact_registry_head_digest,
        product.admission.qualification_evidence_head_digest,
        product.admission.evaluation_receipt_digest,
    ] {
        frontier.extend_from_slice(digest.as_array());
    }
    freeze_context(
        envelope,
        product.selected_artifact_digest,
        product.window.clone(),
        product.baseline_generation,
        product.candidate_generation,
        Digest32::of_bytes(&frontier),
    )
}

fn freeze_context(
    envelope: &IterationEnvelopeV1,
    selected_artifact_digest: Digest32,
    window: ProposalWindowV2,
    baseline_generation: Generation,
    candidate_generation: Generation,
    owner_frontier_digest: Digest32,
) -> Result<FrozenPlasticityContextV1, ControlEngineeringIterationErrorV1> {
    if selected_artifact_digest.is_zero()
        || window.window_digest.is_zero()
        || envelope.grammar_digest.is_zero()
        || owner_frontier_digest.is_zero()
        || baseline_generation.next() != Ok(candidate_generation)
    {
        return Err(ControlEngineeringIterationErrorV1::Binding(
            "frozen context",
        ));
    }
    let envelope_digest = iteration_envelope_digest_v1(envelope)?;
    let mut bytes = b"hepta.control-engineering.plasticity-freeze.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(selected_artifact_digest.as_array());
    push_id(&mut bytes, &window.window_id)?;
    bytes.extend_from_slice(window.window_digest.as_array());
    bytes.extend_from_slice(&baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(envelope.grammar_digest.as_array());
    bytes.extend_from_slice(owner_frontier_digest.as_array());
    let freeze_digest = Digest32::of_bytes(&bytes);
    Ok(FrozenPlasticityContextV1 {
        envelope_digest,
        selected_artifact_digest,
        window,
        baseline_generation,
        candidate_generation,
        grammar_digest: envelope.grammar_digest,
        owner_frontier_digest,
        freeze_digest,
    })
}

pub fn iteration_envelope_digest_v1(
    envelope: &IterationEnvelopeV1,
) -> Result<Digest32, ControlEngineeringIterationErrorV1> {
    envelope
        .validate()
        .map_err(ControlEngineeringIterationErrorV1::InvalidEnvelope)?;
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

fn validate_envelope(
    envelope: &IterationEnvelopeV1,
    now: u64,
    deadline: u64,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    envelope
        .validate()
        .map_err(ControlEngineeringIterationErrorV1::InvalidEnvelope)?;
    if now > envelope.expiry_unix_seconds
        || deadline <= now
        || deadline > envelope.expiry_unix_seconds
    {
        return Err(ControlEngineeringIterationErrorV1::DeadlineExceeded);
    }
    Ok(())
}

fn logical_deadline(
    now: u64,
    deadline: u64,
) -> Result<Instant, ControlEngineeringIterationErrorV1> {
    let seconds = deadline
        .checked_sub(now)
        .filter(|seconds| *seconds > 0)
        .ok_or(ControlEngineeringIterationErrorV1::DeadlineExceeded)?;
    Instant::now()
        .checked_add(Duration::from_secs(seconds))
        .ok_or(ControlEngineeringIterationErrorV1::DeadlineExceeded)
}

fn terminal_template(
    envelope: &IterationEnvelopeV1,
    frozen: &FrozenPlasticityContextV1,
    proposal_id: StableId,
    kind: IterationPlasticityKindV1,
    disposition: IterationPlasticityTerminalDispositionV1,
    request_digest: Digest32,
    terminal_payload_digest: Digest32,
    coverage_digest: Digest32,
    observed_unix_seconds: u64,
) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
    if request_digest.is_zero()
        || terminal_payload_digest.is_zero()
        || coverage_digest.is_zero()
        || observed_unix_seconds == 0
    {
        return Err(ControlEngineeringIterationErrorV1::Binding(
            "terminal receipt",
        ));
    }
    Ok(IterationPlasticityTerminalReceiptV1 {
        sequence: 0,
        envelope_id: envelope.envelope_id.clone(),
        envelope_digest: frozen.envelope_digest,
        freeze_digest: frozen.freeze_digest,
        proposal_id,
        candidate_generation: frozen.candidate_generation.get(),
        kind,
        disposition,
        request_digest,
        terminal_payload_digest,
        coverage_digest,
        observed_unix_seconds,
        predecessor_frame_digest: Digest32::ZERO,
        frame_digest: Digest32::ZERO,
    })
}

fn parameter_iteration_request_digest(
    request: &ControlEngineeringParameterIterationRequestV1,
) -> Result<Digest32, ControlEngineeringIterationErrorV1> {
    let mut bytes = b"hepta.control-engineering.parameter-iteration-request.v1\0".to_vec();
    bytes.extend_from_slice(request.frozen.freeze_digest.as_array());
    push_id(&mut bytes, &request.product.proposal_id)?;
    bytes.extend_from_slice(request.product.generated.generator_digest.as_array());
    bytes.extend_from_slice(request.coverage.coverage_digest.as_array());
    bytes.extend_from_slice(request.product.expected_registry_predecessor.as_array());
    push_signed_evidence(&mut bytes, &request.product.generator_attestation);
    push_signed_evidence(&mut bytes, &request.product.admission_attestation);
    push_signed_evidence(&mut bytes, &request.coverage_attestation);
    match &request.product.no_change_attestation {
        Some(evidence) => {
            bytes.push(1);
            push_signed_evidence(&mut bytes, evidence);
        }
        None => bytes.push(0),
    }
    let mut evaluations = request.product.evaluations.iter().collect::<Vec<_>>();
    evaluations.sort_by(|left, right| left.bundle.candidate_id.cmp(&right.bundle.candidate_id));
    push_len(&mut bytes, evaluations.len())?;
    for evaluation in evaluations {
        push_id(&mut bytes, &evaluation.bundle.candidate_id)?;
        let payload = evaluation_signing_payload_v2(&evaluation.bundle, &evaluation.metric_roles)
            .map_err(|_| ControlEngineeringIterationErrorV1::Binding("evaluation payload"))?;
        bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        push_signed_evidence(&mut bytes, &evaluation.evidence.generator_plan);
        push_signed_evidence(&mut bytes, &evaluation.evidence.evaluator_bundle);
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn topology_iteration_request_digest(
    request: &ControlEngineeringTopologyIterationRequestV1,
) -> Result<Digest32, ControlEngineeringIterationErrorV1> {
    let mut bytes = b"hepta.control-engineering.topology-iteration-request.v1\0".to_vec();
    bytes.extend_from_slice(request.frozen.freeze_digest.as_array());
    push_id(&mut bytes, &request.product.proposal_id)?;
    for payload in [
        topology_generation_signing_payload_v1(&request.product)
            .map_err(|_| ControlEngineeringIterationErrorV1::Binding("topology generation"))?,
        topology_admission_signing_payload_v1(&request.product.admission),
        topology_evaluation_signing_payload_v1(&request.product.admission),
    ] {
        bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    }
    for evidence in [
        &request.product.generator_attestation,
        &request.product.observer_attestation,
        &request.product.evaluator_attestation,
    ] {
        push_signed_evidence(&mut bytes, evidence);
    }
    bytes.extend_from_slice(request.product.expected_registry_predecessor.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn parameter_product_digest(receipt: &ParameterPlasticityProductReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.parameter-product-terminal.v1\0".to_vec();
    for digest in [
        receipt.proposal.proposal_digest,
        receipt.registry.frame_digest,
        receipt.committed_registry_anchor.frame_digest,
        receipt.composition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn topology_product_digest(receipt: &TopologyPlasticityProductReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.topology-product-terminal.v1\0".to_vec();
    for digest in [
        receipt.governed.proposal.proposal_digest,
        receipt.governed.admission_digest,
        receipt.durable.frame_digest,
        receipt.next_registry_anchor.frame_digest,
        receipt.composition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn coverage_terminal_digest(
    disposition: IterationPlasticityTerminalDispositionV1,
    coverage: &GeneratorCoverageReceiptV1,
    freeze_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.coverage-terminal.v1\0".to_vec();
    bytes.push(disposition.tag());
    bytes.extend_from_slice(coverage.coverage_digest.as_array());
    bytes.extend_from_slice(freeze_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_signed_evidence(bytes: &mut Vec<u8>, evidence: &SignedLearningEvidenceV1) {
    bytes.extend_from_slice(Digest32::of_bytes(&evidence.signing_bytes()).as_array());
    bytes.extend_from_slice(&evidence.signature);
}

fn validate_journal_context(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<(), DurableIterationJournalErrorV1> {
    if scope.is_zero() {
        return Err(DurableIterationJournalErrorV1::InvalidScope);
    }
    if writer_fence == 0 {
        return Err(DurableIterationJournalErrorV1::InvalidFence);
    }
    if !(1..=MAX_JOURNAL_RECORDS).contains(&maximum_records) {
        return Err(DurableIterationJournalErrorV1::InvalidLimit);
    }
    Ok(())
}

fn encode_header(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<Vec<u8>, DurableIterationJournalErrorV1> {
    let mut bytes = Vec::with_capacity(HEADER_BYTES);
    bytes.extend_from_slice(JOURNAL_MAGIC);
    bytes.extend_from_slice(&JOURNAL_VERSION.to_be_bytes());
    bytes.extend_from_slice(scope.as_array());
    bytes.extend_from_slice(&writer_fence.to_be_bytes());
    let maximum_records = u32::try_from(maximum_records)
        .map_err(|_| DurableIterationJournalErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&maximum_records.to_be_bytes());
    let digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

fn validate_header(bytes: &[u8]) -> Result<(), DurableIterationJournalErrorV1> {
    if bytes.len() != HEADER_BYTES
        || &bytes[..8] != JOURNAL_MAGIC
        || u16::from_be_bytes([bytes[8], bytes[9]]) != JOURNAL_VERSION
        || Digest32::of_bytes(&bytes[..HEADER_PREFIX_BYTES])
            != Digest32::from_array(
                bytes[HEADER_PREFIX_BYTES..HEADER_BYTES]
                    .try_into()
                    .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
            )
    {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    Ok(())
}

fn write_durable(
    file: &mut File,
    bytes: &[u8],
) -> Result<(), DurableIterationJournalErrorV1> {
    file.seek(SeekFrom::Start(0))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| DurableIterationJournalErrorV1::Indeterminate(error.kind()))
}

fn encode_frame(
    receipt: &mut IterationPlasticityTerminalReceiptV1,
) -> Result<Vec<u8>, DurableIterationJournalErrorV1> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(FRAME_MAGIC);
    bytes.extend_from_slice(&receipt.sequence.to_be_bytes());
    bytes.extend_from_slice(receipt.predecessor_frame_digest.as_array());
    bytes.extend_from_slice(terminal_identity_digest(receipt)?.as_array());
    encode_terminal_body(&mut bytes, receipt)?;
    receipt.frame_digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(receipt.frame_digest.as_array());
    if bytes.len() > MAX_FRAME_BYTES {
        return Err(DurableIterationJournalErrorV1::Capacity);
    }
    Ok(bytes)
}

fn decode_frame(bytes: &[u8]) -> Result<IterationPlasticityTerminalReceiptV1, DurableIterationJournalErrorV1> {
    let mut cursor = ByteCursor::new(bytes);
    if cursor.take_array::<8>()? != *FRAME_MAGIC {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    let sequence = cursor.take_u64()?;
    let predecessor_frame_digest = cursor.take_digest()?;
    let encoded_identity = cursor.take_digest()?;
    let mut receipt = decode_terminal_body(&mut cursor)?;
    let frame_digest = cursor.take_digest()?;
    if !cursor.is_done()
        || frame_digest != Digest32::of_bytes(&bytes[..bytes.len().saturating_sub(32)])
    {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    receipt.sequence = sequence;
    receipt.predecessor_frame_digest = predecessor_frame_digest;
    receipt.frame_digest = frame_digest;
    if terminal_identity_digest(&receipt)? != encoded_identity {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    validate_terminal_template(&receipt)?;
    Ok(receipt)
}

fn encode_terminal_body(
    bytes: &mut Vec<u8>,
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<(), DurableIterationJournalErrorV1> {
    push_journal_id(bytes, &receipt.envelope_id)?;
    bytes.extend_from_slice(receipt.envelope_digest.as_array());
    bytes.extend_from_slice(receipt.freeze_digest.as_array());
    push_journal_id(bytes, &receipt.proposal_id)?;
    bytes.extend_from_slice(&receipt.candidate_generation.to_be_bytes());
    bytes.push(receipt.kind.tag());
    bytes.push(receipt.disposition.tag());
    for digest in [
        receipt.request_digest,
        receipt.terminal_payload_digest,
        receipt.coverage_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.observed_unix_seconds.to_be_bytes());
    Ok(())
}

fn decode_terminal_body(
    cursor: &mut ByteCursor<'_>,
) -> Result<IterationPlasticityTerminalReceiptV1, DurableIterationJournalErrorV1> {
    Ok(IterationPlasticityTerminalReceiptV1 {
        sequence: 0,
        envelope_id: cursor.take_id()?,
        envelope_digest: cursor.take_digest()?,
        freeze_digest: cursor.take_digest()?,
        proposal_id: cursor.take_id()?,
        candidate_generation: cursor.take_u64()?,
        kind: IterationPlasticityKindV1::from_tag(cursor.take_u8()?)?,
        disposition: IterationPlasticityTerminalDispositionV1::from_tag(cursor.take_u8()?)?,
        request_digest: cursor.take_digest()?,
        terminal_payload_digest: cursor.take_digest()?,
        coverage_digest: cursor.take_digest()?,
        observed_unix_seconds: cursor.take_u64()?,
        predecessor_frame_digest: Digest32::ZERO,
        frame_digest: Digest32::ZERO,
    })
}

fn validate_terminal_template(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<(), DurableIterationJournalErrorV1> {
    if receipt.envelope_digest.is_zero()
        || receipt.freeze_digest.is_zero()
        || receipt.candidate_generation == 0
        || receipt.request_digest.is_zero()
        || receipt.terminal_payload_digest.is_zero()
        || receipt.coverage_digest.is_zero()
        || receipt.observed_unix_seconds == 0
    {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    match (receipt.kind, receipt.disposition) {
        (
            IterationPlasticityKindV1::Parameter,
            IterationPlasticityTerminalDispositionV1::ParameterCommitted
                | IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals
                | IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates
                | IterationPlasticityTerminalDispositionV1::IncompleteCoverage,
        )
        | (
            IterationPlasticityKindV1::Topology,
            IterationPlasticityTerminalDispositionV1::TopologyCommitted,
        ) => Ok(()),
        _ => Err(DurableIterationJournalErrorV1::Corrupt),
    }
}

fn terminal_identity_digest(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<Digest32, DurableIterationJournalErrorV1> {
    let mut bytes = b"hepta.control-engineering.iteration-terminal-identity.v1\0".to_vec();
    bytes.extend_from_slice(receipt.envelope_digest.as_array());
    push_journal_id(&mut bytes, &receipt.proposal_id)?;
    bytes.extend_from_slice(&receipt.candidate_generation.to_be_bytes());
    bytes.push(receipt.kind.tag());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| ControlEngineeringIterationErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(
    bytes: &mut Vec<u8>,
    value: usize,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    let value = u32::try_from(value).map_err(|_| ControlEngineeringIterationErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn push_journal_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), DurableIterationJournalErrorV1> {
    let raw = value.as_str().as_bytes();
    if raw.len() > MAX_ID_BYTES {
        return Err(DurableIterationJournalErrorV1::Capacity);
    }
    let length = u32::try_from(raw.len()).map_err(|_| DurableIterationJournalErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

struct ByteCursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> ByteCursor<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    fn take_array<const N: usize>(&mut self) -> Result<[u8; N], DurableIterationJournalErrorV1> {
        let end = self
            .offset
            .checked_add(N)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn take_u8(&mut self) -> Result<u8, DurableIterationJournalErrorV1> {
        Ok(self.take_array::<1>()?[0])
    }
    fn take_u32(&mut self) -> Result<u32, DurableIterationJournalErrorV1> {
        Ok(u32::from_be_bytes(self.take_array::<4>()?))
    }
    fn take_u64(&mut self) -> Result<u64, DurableIterationJournalErrorV1> {
        Ok(u64::from_be_bytes(self.take_array::<8>()?))
    }
    fn take_digest(&mut self) -> Result<Digest32, DurableIterationJournalErrorV1> {
        Ok(Digest32::from_array(self.take_array::<32>()?))
    }
    fn take_id(&mut self) -> Result<StableId, DurableIterationJournalErrorV1> {
        let length = self.take_u32()? as usize;
        if length == 0 || length > MAX_ID_BYTES {
            return Err(DurableIterationJournalErrorV1::Corrupt);
        }
        let end = self
            .offset
            .checked_add(length)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?;
        let raw = self
            .bytes
            .get(self.offset..end)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?;
        self.offset = end;
        let value = std::str::from_utf8(raw).map_err(|_| DurableIterationJournalErrorV1::Corrupt)?;
        StableId::new(value.to_string()).map_err(|_| DurableIterationJournalErrorV1::Corrupt)
    }
    fn is_done(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use std::io::Write;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn terminal(request: &[u8]) -> IterationPlasticityTerminalReceiptV1 {
        IterationPlasticityTerminalReceiptV1 {
            sequence: 0,
            envelope_id: id("envelope:journal"),
            envelope_digest: digest(b"envelope"),
            freeze_digest: digest(b"freeze"),
            proposal_id: id("proposal:journal"),
            candidate_generation: 2,
            kind: IterationPlasticityKindV1::Parameter,
            disposition: IterationPlasticityTerminalDispositionV1::ParameterCommitted,
            request_digest: digest(request),
            terminal_payload_digest: digest(b"terminal"),
            coverage_digest: digest(b"coverage"),
            observed_unix_seconds: 10,
            predecessor_frame_digest: Digest32::ZERO,
            frame_digest: Digest32::ZERO,
        }
    }

    #[test]
    fn terminal_journal_reopens_and_replays_idempotently() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let scope = digest(b"scope");
        let first = {
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(fixture.path())
                .expect("open");
            let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(file, scope, 7, 8)
                .expect("journal");
            let first = journal.append(terminal(b"request")).expect("append");
            assert_eq!(journal.append(terminal(b"request")).expect("retry"), first);
            first
        };
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(fixture.path())
            .expect("reopen");
        let journal = DurableIterationTerminalJournalV1::reopen(file, scope, 7, 8)
            .expect("recover");
        assert_eq!(journal.record_count(), 1);
        assert_eq!(journal.lookup(&terminal(b"request")).expect("lookup"), Some(&first));
    }

    #[test]
    fn terminal_identity_rejects_semantic_drift() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(fixture.path())
            .expect("open");
        let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(
            file,
            digest(b"scope"),
            9,
            8,
        )
        .expect("journal");
        journal.append(terminal(b"request-a")).expect("append");
        assert_eq!(
            journal.append(terminal(b"request-b")),
            Err(DurableIterationJournalErrorV1::Conflict)
        );
    }

    #[test]
    fn incomplete_tail_is_repaired_but_complete_drift_is_not() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let scope = digest(b"scope");
        {
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(fixture.path())
                .expect("open");
            let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(file, scope, 11, 8)
                .expect("journal");
            journal.append(terminal(b"request")).expect("append");
        }
        let valid = std::fs::metadata(fixture.path()).expect("metadata").len();
        {
            let mut file = OpenOptions::new()
                .append(true)
                .open(fixture.path())
                .expect("append");
            file.write_all(&[0, 0, 0]).expect("tail");
            file.sync_all().expect("sync");
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(fixture.path())
            .expect("reopen");
        DurableIterationTerminalJournalV1::reopen(file, scope, 11, 8).expect("recover");
        assert_eq!(std::fs::metadata(fixture.path()).expect("metadata").len(), valid);
    }
}
