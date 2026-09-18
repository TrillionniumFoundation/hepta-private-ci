//! Selected-host composition for governed learning.plasticity.
//!
//! Agentd is the existing process/lifecycle host, so this module resolves current
//! owner-store frontiers and owns the independent proposal-registry anchor/fence
//! service without creating a second execution spine. It still grants no model
//! installation, selection, topology mutation, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::{Read, Seek, SeekFrom, Write};

use codex_hepta_intelligence::{
    AnchoredPlasticityWriterErrorV1, AnchoredPlasticityWriterV1, ParameterPlasticityProductErrorV1,
    ParameterPlasticityProductReceiptV1, ParameterPlasticityProductRequestV1,
    PlasticityAdmissionEvidenceV1, PlasticityAnchorCommitterV1,
    propose_authenticated_parameter_plasticity_v1,
};
use codex_hepta_learning_artifacts::{ArtifactKind, ArtifactRegistry};
use codex_hepta_learning_ledger::{DurableLedger, DurableLedgerError, LearningEvidenceVerifierV1};
use codex_hepta_plasticity::{
    DurableRegistryAnchorV1, GeneratedParameterCandidateSetV3, ParameterGeneratorProfileV3,
    ProposalWindowV2,
};
use codex_hepta_types::{Digest32, Generation, StableId};

const ANCHOR_MAGIC: &[u8; 8] = b"HPTAANC1";
const ANCHOR_BYTES: usize = 8 + 32 + 8 + 8 + 32 + 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdPlasticityHostErrorV1 {
    AnchorBusy,
    AnchorNotRegular,
    AnchorCorrupt,
    AnchorScopeMismatch,
    AnchorFenceOverflow,
    AnchorIo(std::io::ErrorKind),
    MissingAnchor,
    ArtifactMissing,
    ArtifactIneligible,
    ArtifactBinding,
    Ledger(DurableLedgerError),
    Writer(AnchoredPlasticityWriterErrorV1),
    Product(ParameterPlasticityProductErrorV1),
    AdmissionDrift,
    OwnerEvidence(PlasticityOwnerEvidenceErrorV1),
}

impl fmt::Display for AgentdPlasticityHostErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdPlasticityHostErrorV1 {}
impl From<DurableLedgerError> for AgentdPlasticityHostErrorV1 {
    fn from(value: DurableLedgerError) -> Self {
        Self::Ledger(value)
    }
}
impl From<AnchoredPlasticityWriterErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: AnchoredPlasticityWriterErrorV1) -> Self {
        Self::Writer(value)
    }
}
impl From<ParameterPlasticityProductErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: ParameterPlasticityProductErrorV1) -> Self {
        Self::Product(value)
    }
}

impl From<PlasticityOwnerEvidenceErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: PlasticityOwnerEvidenceErrorV1) -> Self {
        Self::OwnerEvidence(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlasticityOwnerEvidenceKindV1 {
    Dataset,
    UpdateRule,
    Modulator,
    ModulatorBroadcast,
    Eligibility,
    ParameterSignal,
}

impl PlasticityOwnerEvidenceKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Dataset => 0,
            Self::UpdateRule => 1,
            Self::Modulator => 2,
            Self::ModulatorBroadcast => 3,
            Self::Eligibility => 4,
            Self::ParameterSignal => 5,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityOwnerEvidenceQueryV1 {
    pub kind: PlasticityOwnerEvidenceKindV1,
    pub evidence_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub dataset_digest: Digest32,
    pub baseline_generation: Generation,
    pub layer_id: Option<StableId>,
    pub parameter_id: Option<StableId>,
    pub now: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPlasticityOwnerEvidenceV1 {
    pub kind: PlasticityOwnerEvidenceKindV1,
    pub evidence_digest: Digest32,
    pub owner_id: StableId,
    pub owner_store_head_digest: Digest32,
    pub owner_receipt_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub dataset_digest: Digest32,
    pub baseline_generation: Generation,
    pub layer_id: Option<StableId>,
    pub parameter_id: Option<StableId>,
    pub observed_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityOwnerEvidenceErrorV1 {
    Unavailable,
    Missing,
    Unauthorized,
    Stale,
    ContextMismatch,
    InvalidReceipt,
}

impl fmt::Display for PlasticityOwnerEvidenceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityOwnerEvidenceErrorV1 {}

/// Deployment-owned resolver for learning facts that are not owned by Agentd.
///
/// Implementations MUST resolve the requested digest against the authoritative
/// owner store and authenticate the returned owner receipt. There is deliberately
/// no permissive/default implementation in Agentd.
pub trait PlasticityOwnerEvidenceResolverV1 {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1>;
}

pub fn verify_agentd_plasticity_owner_evidence_v1(
    resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    query: &PlasticityOwnerEvidenceQueryV1,
) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
    validate_owner_evidence_query(query)?;
    let receipt = resolver.resolve(query)?;
    if receipt.kind != query.kind
        || receipt.evidence_digest != query.evidence_digest
        || receipt.objective_digest != query.objective_digest
        || receipt.selected_artifact_digest != query.selected_artifact_digest
        || receipt.window != query.window
        || receipt.dataset_digest != query.dataset_digest
        || receipt.baseline_generation != query.baseline_generation
        || receipt.layer_id != query.layer_id
        || receipt.parameter_id != query.parameter_id
    {
        return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
    }
    if receipt.owner_store_head_digest.is_zero() || receipt.owner_receipt_digest.is_zero() {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    if receipt.observed_at > receipt.expires_at
        || query.now < receipt.observed_at
        || query.now > receipt.expires_at
    {
        return Err(PlasticityOwnerEvidenceErrorV1::Stale);
    }

    let mut bytes = b"hepta.agentd.plasticity-owner-evidence.v1\0".to_vec();
    bytes.push(receipt.kind.tag());
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    push_owner_id(&mut bytes, &receipt.owner_id)?;
    for digest in [
        receipt.owner_store_head_digest,
        receipt.owner_receipt_digest,
        receipt.objective_digest,
        receipt.selected_artifact_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_owner_id(&mut bytes, &receipt.window.window_id)?;
    bytes.extend_from_slice(receipt.window.window_digest.as_array());
    bytes.extend_from_slice(receipt.dataset_digest.as_array());
    bytes.extend_from_slice(&receipt.baseline_generation.get().to_be_bytes());
    push_optional_owner_id(&mut bytes, receipt.layer_id.as_ref())?;
    push_optional_owner_id(&mut bytes, receipt.parameter_id.as_ref())?;
    bytes.extend_from_slice(&receipt.observed_at.to_be_bytes());
    bytes.extend_from_slice(&receipt.expires_at.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_owner_evidence_query(
    query: &PlasticityOwnerEvidenceQueryV1,
) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
    if query.evidence_digest.is_zero()
        || query.objective_digest.is_zero()
        || query.selected_artifact_digest.is_zero()
        || query.window.window_digest.is_zero()
        || query.dataset_digest.is_zero()
    {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    match query.kind {
        PlasticityOwnerEvidenceKindV1::ParameterSignal => {
            if query.layer_id.is_none() || query.parameter_id.is_none() {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
        _ => {
            if query.layer_id.is_some() || query.parameter_id.is_some() {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
    }
    Ok(())
}

fn push_owner_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
    let length = u32::try_from(value.as_str().len())
        .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
    Ok(())
}

fn push_optional_owner_id(
    bytes: &mut Vec<u8>,
    value: Option<&StableId>,
) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
    match value {
        Some(value) => {
            bytes.push(1);
            push_owner_id(bytes, value)?;
        }
        None => bytes.push(0),
    }
    Ok(())
}

struct LockedAnchorFile(File);
impl LockedAnchorFile {
    fn acquire(file: File) -> Result<Self, AgentdPlasticityHostErrorV1> {
        if !file
            .metadata()
            .map_err(|e| AgentdPlasticityHostErrorV1::AnchorIo(e.kind()))?
            .is_file()
        {
            return Err(AgentdPlasticityHostErrorV1::AnchorNotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(AgentdPlasticityHostErrorV1::AnchorBusy),
            Err(TryLockError::Error(error)) => {
                Err(AgentdPlasticityHostErrorV1::AnchorIo(error.kind()))
            }
        }
    }
}
impl Drop for LockedAnchorFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

/// Independently durable host state for the proposal-registry fence and last
/// acknowledged anchor. The caller must place this file in a rollback domain
/// independent from the proposal registry file.
pub struct AgentdPlasticityAnchorStoreV1 {
    file: LockedAnchorFile,
    scope: Digest32,
    fence: u64,
    anchor: Option<DurableRegistryAnchorV1>,
    poisoned: bool,
}

impl AgentdPlasticityAnchorStoreV1 {
    pub fn open(file: File, scope: Digest32) -> Result<Self, AgentdPlasticityHostErrorV1> {
        if scope.is_zero() {
            return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
        }
        let mut file = LockedAnchorFile::acquire(file)?;
        let length = file
            .0
            .metadata()
            .map_err(|e| AgentdPlasticityHostErrorV1::AnchorIo(e.kind()))?
            .len();
        if length == 0 {
            let mut store = Self {
                file,
                scope,
                fence: 0,
                anchor: None,
                poisoned: false,
            };
            store.persist_state()?;
            return Ok(store);
        }
        if length != ANCHOR_BYTES as u64 {
            return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
        }
        file.0
            .seek(SeekFrom::Start(0))
            .map_err(|e| AgentdPlasticityHostErrorV1::AnchorIo(e.kind()))?;
        let mut bytes = [0_u8; ANCHOR_BYTES];
        file.0
            .read_exact(&mut bytes)
            .map_err(|e| AgentdPlasticityHostErrorV1::AnchorIo(e.kind()))?;
        if &bytes[..8] != ANCHOR_MAGIC
            || Digest32::of_bytes(&bytes[..ANCHOR_BYTES - 32]).as_array()
                != &bytes[ANCHOR_BYTES - 32..]
        {
            return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
        }
        let stored_scope = Digest32::from_array(
            bytes[8..40]
                .try_into()
                .map_err(|_| AgentdPlasticityHostErrorV1::AnchorCorrupt)?,
        );
        if stored_scope != scope {
            return Err(AgentdPlasticityHostErrorV1::AnchorScopeMismatch);
        }
        let fence = u64::from_be_bytes(
            bytes[40..48]
                .try_into()
                .map_err(|_| AgentdPlasticityHostErrorV1::AnchorCorrupt)?,
        );
        let sequence = u64::from_be_bytes(
            bytes[48..56]
                .try_into()
                .map_err(|_| AgentdPlasticityHostErrorV1::AnchorCorrupt)?,
        );
        let frame_digest = Digest32::from_array(
            bytes[56..88]
                .try_into()
                .map_err(|_| AgentdPlasticityHostErrorV1::AnchorCorrupt)?,
        );
        let anchor = if sequence == 0 {
            if !frame_digest.is_zero() {
                return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
            }
            None
        } else {
            if frame_digest.is_zero() || fence == 0 {
                return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
            }
            Some(DurableRegistryAnchorV1 {
                sequence,
                frame_digest,
            })
        };
        Ok(Self {
            file,
            scope,
            fence,
            anchor,
            poisoned: false,
        })
    }

    /// Issue a strictly increasing fence for a newly enrolled registry generation.
    /// Existing acknowledged history retains its original fence on reopen.
    pub fn issue_next_fence(&mut self) -> Result<u64, AgentdPlasticityHostErrorV1> {
        if self.poisoned || self.anchor.is_some() {
            return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
        }
        self.fence = self
            .fence
            .checked_add(1)
            .ok_or(AgentdPlasticityHostErrorV1::AnchorFenceOverflow)?;
        if self.fence == 0 {
            return Err(AgentdPlasticityHostErrorV1::AnchorFenceOverflow);
        }
        self.persist_state()?;
        Ok(self.fence)
    }

    pub const fn fence(&self) -> u64 {
        self.fence
    }

    pub const fn anchor(&self) -> Option<DurableRegistryAnchorV1> {
        self.anchor
    }

    fn persist_state(&mut self) -> Result<(), AgentdPlasticityHostErrorV1> {
        let mut bytes = Vec::with_capacity(ANCHOR_BYTES);
        bytes.extend_from_slice(ANCHOR_MAGIC);
        bytes.extend_from_slice(self.scope.as_array());
        bytes.extend_from_slice(&self.fence.to_be_bytes());
        match self.anchor {
            Some(anchor) => {
                bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
                bytes.extend_from_slice(anchor.frame_digest.as_array());
            }
            None => {
                bytes.extend_from_slice(&0_u64.to_be_bytes());
                bytes.extend_from_slice(Digest32::ZERO.as_array());
            }
        }
        let checksum = Digest32::of_bytes(&bytes);
        bytes.extend_from_slice(checksum.as_array());
        self.file
            .0
            .seek(SeekFrom::Start(0))
            .and_then(|_| self.file.0.write_all(&bytes))
            .and_then(|_| self.file.0.set_len(ANCHOR_BYTES as u64))
            .and_then(|_| self.file.0.sync_all())
            .map_err(|error| {
                self.poisoned = true;
                AgentdPlasticityHostErrorV1::AnchorIo(error.kind())
            })
    }
}

impl PlasticityAnchorCommitterV1 for AgentdPlasticityAnchorStoreV1 {
    fn persist_anchor(
        &mut self,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        anchor: DurableRegistryAnchorV1,
    ) -> bool {
        if self.poisoned
            || registry_scope_digest != self.scope
            || writer_fence != self.fence
            || writer_fence == 0
            || anchor.sequence == 0
            || anchor.frame_digest.is_zero()
        {
            self.poisoned = true;
            return false;
        }
        if let Some(current) = self.anchor {
            if anchor.sequence < current.sequence
                || (anchor.sequence == current.sequence && anchor != current)
            {
                self.poisoned = true;
                return false;
            }
            if anchor == current {
                return true;
            }
        }
        self.anchor = Some(anchor);
        self.persist_state().is_ok()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdPlasticityAdmissionInputV1 {
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub generator_profile: ParameterGeneratorProfileV3,
    pub generated: GeneratedParameterCandidateSetV3,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub eligibility_digest: Digest32,
}

pub fn resolve_agentd_plasticity_owner_evidence_set_v1(
    input: &AgentdPlasticityAdmissionInputV1,
    resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    now: u64,
) -> Result<Digest32, AgentdPlasticityHostErrorV1> {
    if input.generator_profile.selected_artifact_digest != input.generated.selected_artifact_digest
        || input.generator_profile.window != input.generated.window
    {
        return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch.into());
    }

    let mut digests = Vec::with_capacity(5 + input.generator_profile.signals.len());
    for (kind, evidence_digest) in [
        (PlasticityOwnerEvidenceKindV1::Dataset, input.dataset_digest),
        (PlasticityOwnerEvidenceKindV1::UpdateRule, input.update_rule_digest),
        (PlasticityOwnerEvidenceKindV1::Modulator, input.modulator_digest),
        (PlasticityOwnerEvidenceKindV1::ModulatorBroadcast, input.modulator_broadcast_digest),
        (PlasticityOwnerEvidenceKindV1::Eligibility, input.eligibility_digest),
    ] {
        digests.push(verify_agentd_plasticity_owner_evidence_v1(
            resolver,
            &owner_evidence_query(input, kind, evidence_digest, None, None, now),
        )?);
    }

    let mut signals = input.generator_profile.signals.iter().collect::<Vec<_>>();
    signals.sort_by(|left, right| {
        left.layer_id
            .cmp(&right.layer_id)
            .then_with(|| left.parameter_id.cmp(&right.parameter_id))
    });
    for signal in signals {
        digests.push(verify_agentd_plasticity_owner_evidence_v1(
            resolver,
            &owner_evidence_query(
                input,
                PlasticityOwnerEvidenceKindV1::ParameterSignal,
                signal.evidence_digest,
                Some(signal.layer_id.clone()),
                Some(signal.parameter_id.clone()),
                now,
            ),
        )?);
    }

    let mut bytes = b"hepta.agentd.plasticity-owner-evidence-set.v1\0".to_vec();
    let count = u32::try_from(digests.len())
        .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn owner_evidence_query(
    input: &AgentdPlasticityAdmissionInputV1,
    kind: PlasticityOwnerEvidenceKindV1,
    evidence_digest: Digest32,
    layer_id: Option<StableId>,
    parameter_id: Option<StableId>,
    now: u64,
) -> PlasticityOwnerEvidenceQueryV1 {
    PlasticityOwnerEvidenceQueryV1 {
        kind,
        evidence_digest,
        objective_digest: input.objective_digest,
        selected_artifact_digest: input.generated.selected_artifact_digest,
        window: input.generated.window.clone(),
        dataset_digest: input.dataset_digest,
        baseline_generation: input.baseline_generation,
        layer_id,
        parameter_id,
        now,
    }
}

/// Resolve the exact owner-store frontiers that an Observer must attest.
///
/// Artifact identity/current eligibility comes directly from the authoritative
/// ArtifactRegistry. The qualification/evidence frontier is the current durable
/// learning-ledger head, never a caller-selected opaque value.
pub fn resolve_agentd_plasticity_admission_v1(
    input: &AgentdPlasticityAdmissionInputV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    owner_evidence_resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    now: u64,
) -> Result<PlasticityAdmissionEvidenceV1, AgentdPlasticityHostErrorV1> {
    let manifest = artifacts
        .manifest(&input.baseline_id)
        .ok_or(AgentdPlasticityHostErrorV1::ArtifactMissing)?;
    if !artifacts.is_eligible(&input.baseline_id) {
        return Err(AgentdPlasticityHostErrorV1::ArtifactIneligible);
    }
    if !matches!(
        manifest.kind,
        ArtifactKind::Parameters | ArtifactKind::Model
    ) || manifest.content_digest != input.generated.selected_artifact_digest
        || manifest.objective_digest != input.objective_digest
        || manifest.generation != input.baseline_generation
        || input.baseline_generation.next() != Ok(input.candidate_generation)
    {
        return Err(AgentdPlasticityHostErrorV1::ArtifactBinding);
    }
    let artifact_registry_head_digest = artifacts.snapshot().head_digest;
    let ledger_snapshot = ledger.snapshot()?;
    if artifact_registry_head_digest.is_zero() || ledger_snapshot.head_digest.is_zero() {
        return Err(AgentdPlasticityHostErrorV1::ArtifactBinding);
    }
    let owner_evidence_set_digest =
        resolve_agentd_plasticity_owner_evidence_set_v1(input, owner_evidence_resolver, now)?;
    Ok(PlasticityAdmissionEvidenceV1 {
        baseline_id: input.baseline_id.clone(),
        objective_digest: input.objective_digest,
        selected_artifact_digest: input.generated.selected_artifact_digest,
        artifact_registry_binding: manifest.compatibility_digest,
        artifact_registry_head_digest,
        qualification_evidence_head_digest: ledger_snapshot.head_digest,
        owner_evidence_set_digest,
        window: input.generated.window.clone(),
        baseline_generation: input.baseline_generation,
        candidate_generation: input.candidate_generation,
        dataset_digest: input.dataset_digest,
        update_rule_digest: input.update_rule_digest,
        modulator_digest: input.modulator_digest,
        modulator_broadcast_digest: input.modulator_broadcast_digest,
        eligibility_digest: input.eligibility_digest,
        generator_digest: input.generated.generator_digest,
    })
}

/// Actual Agentd host callsite. It recomputes owner-store frontiers immediately
/// before the product adapter runs, so a stale Observer signature cannot be
/// transplanted across artifact/ledger changes.
pub fn propose_agentd_plasticity_v1(
    mut request: ParameterPlasticityProductRequestV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    owner_evidence_resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredPlasticityWriterV1,
    anchor_store: &mut AgentdPlasticityAnchorStoreV1,
    now: u64,
) -> Result<ParameterPlasticityProductReceiptV1, AgentdPlasticityHostErrorV1> {
    let resolved = resolve_agentd_plasticity_admission_v1(
        &AgentdPlasticityAdmissionInputV1 {
            baseline_id: request.admission.baseline_id.clone(),
            objective_digest: request.admission.objective_digest,
            generator_profile: request.generator_profile.clone(),
            generated: request.generated.clone(),
            baseline_generation: request.admission.baseline_generation,
            candidate_generation: request.admission.candidate_generation,
            dataset_digest: request.admission.dataset_digest,
            update_rule_digest: request.admission.update_rule_digest,
            modulator_digest: request.admission.modulator_digest,
            modulator_broadcast_digest: request.admission.modulator_broadcast_digest,
            eligibility_digest: request.admission.eligibility_digest,
        },
        artifacts,
        ledger,
        owner_evidence_resolver,
        now,
    )?;
    if resolved != request.admission {
        return Err(AgentdPlasticityHostErrorV1::AdmissionDrift);
    }
    request.admission = resolved;
    propose_authenticated_parameter_plasticity_v1(request, verifier, writer, anchor_store, now)
        .map_err(Into::into)
}

pub fn bootstrap_agentd_plasticity_writer_v1(
    registry_file: File,
    anchor_file: File,
    registry_scope_digest: Digest32,
    maximum_records: usize,
) -> Result<(AnchoredPlasticityWriterV1, AgentdPlasticityAnchorStoreV1), AgentdPlasticityHostErrorV1>
{
    let mut anchor_store = AgentdPlasticityAnchorStoreV1::open(anchor_file, registry_scope_digest)?;
    if anchor_store.anchor().is_some() {
        return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
    }
    let fence = anchor_store.issue_next_fence()?;
    let writer = AnchoredPlasticityWriterV1::bootstrap_new(
        registry_file,
        registry_scope_digest,
        fence,
        maximum_records,
    )?;
    Ok((writer, anchor_store))
}

pub fn reopen_agentd_plasticity_writer_v1(
    registry_file: File,
    anchor_file: File,
    registry_scope_digest: Digest32,
    maximum_records: usize,
) -> Result<(AnchoredPlasticityWriterV1, AgentdPlasticityAnchorStoreV1), AgentdPlasticityHostErrorV1>
{
    let anchor_store = AgentdPlasticityAnchorStoreV1::open(anchor_file, registry_scope_digest)?;
    let anchor = anchor_store
        .anchor()
        .ok_or(AgentdPlasticityHostErrorV1::MissingAnchor)?;
    let fence = anchor_store.fence();
    if fence == 0 {
        return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
    }
    let writer = AnchoredPlasticityWriterV1::reopen_anchored(
        registry_file,
        registry_scope_digest,
        fence,
        maximum_records,
        anchor,
    )?;
    Ok((writer, anchor_store))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempfile;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    struct EchoOwnerEvidenceResolver;

    impl PlasticityOwnerEvidenceResolverV1 for EchoOwnerEvidenceResolver {
        fn resolve(
            &self,
            query: &PlasticityOwnerEvidenceQueryV1,
        ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
            Ok(VerifiedPlasticityOwnerEvidenceV1 {
                kind: query.kind,
                evidence_digest: query.evidence_digest,
                owner_id: StableId::new("owner:learning").expect("id"),
                owner_store_head_digest: digest(b"owner-head"),
                owner_receipt_digest: digest(b"owner-receipt"),
                objective_digest: query.objective_digest,
                selected_artifact_digest: query.selected_artifact_digest,
                window: query.window.clone(),
                dataset_digest: query.dataset_digest,
                baseline_generation: query.baseline_generation,
                layer_id: query.layer_id.clone(),
                parameter_id: query.parameter_id.clone(),
                observed_at: 49,
                expires_at: 51,
            })
        }
    }

    fn owner_query() -> PlasticityOwnerEvidenceQueryV1 {
        PlasticityOwnerEvidenceQueryV1 {
            kind: PlasticityOwnerEvidenceKindV1::UpdateRule,
            evidence_digest: digest(b"update-rule"),
            objective_digest: digest(b"objective"),
            selected_artifact_digest: digest(b"artifact"),
            window: ProposalWindowV2 {
                window_id: StableId::new("window:owner-evidence").expect("id"),
                window_digest: digest(b"window"),
            },
            dataset_digest: digest(b"dataset"),
            baseline_generation: Generation::new(7).expect("generation"),
            layer_id: None,
            parameter_id: None,
            now: 50,
        }
    }

    #[test]
    fn owner_evidence_receipt_is_context_bound() {
        assert!(
            !verify_agentd_plasticity_owner_evidence_v1(
                &EchoOwnerEvidenceResolver,
                &owner_query(),
            )
            .expect("verified owner evidence")
            .is_zero()
        );
    }

    struct MismatchedOwnerEvidenceResolver;

    impl PlasticityOwnerEvidenceResolverV1 for MismatchedOwnerEvidenceResolver {
        fn resolve(
            &self,
            query: &PlasticityOwnerEvidenceQueryV1,
        ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
            let mut receipt = EchoOwnerEvidenceResolver.resolve(query)?;
            receipt.dataset_digest = digest(b"different-dataset");
            Ok(receipt)
        }
    }

    #[test]
    fn owner_evidence_rejects_context_substitution() {
        assert_eq!(
            verify_agentd_plasticity_owner_evidence_v1(
                &MismatchedOwnerEvidenceResolver,
                &owner_query(),
            ),
            Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
        );
    }

    #[test]
    fn anchor_store_fence_is_monotonic_and_reopen_preserves_acknowledged_state() {
        let anchor_file = tempfile().expect("anchor file");
        let scope = digest(b"scope");
        let mut store =
            AgentdPlasticityAnchorStoreV1::open(anchor_file.try_clone().expect("clone"), scope)
                .expect("open");
        assert_eq!(store.issue_next_fence().expect("fence"), 1);
        let expected = DurableRegistryAnchorV1 {
            sequence: 1,
            frame_digest: digest(b"frame"),
        };
        assert!(store.persist_anchor(scope, 1, expected));
        drop(store);

        let reopened = AgentdPlasticityAnchorStoreV1::open(anchor_file, scope).expect("reopen");
        assert_eq!(reopened.fence(), 1);
        assert_eq!(reopened.anchor(), Some(expected));
    }
}
