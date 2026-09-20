//! Selected-host composition for governed learning.plasticity.
//!
//! Agentd is the existing process/lifecycle host, so this module resolves current
//! owner-store frontiers and owns the independent proposal-registry anchor/fence
//! service without creating a second execution spine. It still grants no model
//! installation, selection, topology mutation, promotion or release authority.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

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
    ParameterPlasticitySignalV3, ProposalWindowV2,
};
use codex_hepta_types::{Digest32, FixedQ32, Generation, StableId};

use crate::plasticity_anchor_journal::{
    AdaptiveAnchorJournalErrorV1, AdaptiveAnchorJournalV1, AdaptiveAnchorV1,
};

const ANCHOR_MAGIC: [u8; 8] = *b"HPTAANC2";

#[derive(Debug)]
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
    OwnerEvidencePolicy(PlasticityOwnerEvidencePolicyErrorV1),
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
impl From<PlasticityOwnerEvidencePolicyErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: PlasticityOwnerEvidencePolicyErrorV1) -> Self {
        Self::OwnerEvidencePolicy(value)
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
    MutationPolicy,
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
            Self::MutationPolicy => 6,
        }
    }
}

const PLASTICITY_OWNER_EVIDENCE_KINDS_V1: [PlasticityOwnerEvidenceKindV1; 7] = [
    PlasticityOwnerEvidenceKindV1::Dataset,
    PlasticityOwnerEvidenceKindV1::UpdateRule,
    PlasticityOwnerEvidenceKindV1::Modulator,
    PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
    PlasticityOwnerEvidenceKindV1::Eligibility,
    PlasticityOwnerEvidenceKindV1::ParameterSignal,
    PlasticityOwnerEvidenceKindV1::MutationPolicy,
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityOwnerEvidencePolicyErrorV1 {
    EmptyPolicy,
    MissingKind(PlasticityOwnerEvidenceKindV1),
}
impl fmt::Display for PlasticityOwnerEvidencePolicyErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityOwnerEvidencePolicyErrorV1 {}

/// Host-owned policy mapping every plasticity evidence class to the authoritative
/// owner identities allowed to attest it. The resolver proves a store receipt;
/// this policy independently prevents a valid receipt from the wrong owner from
/// satisfying the request.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityOwnerEvidencePolicyV1 {
    allowed_owners: BTreeMap<PlasticityOwnerEvidenceKindV1, BTreeSet<StableId>>,
}
impl PlasticityOwnerEvidencePolicyV1 {
    pub fn from_rules(
        rules: Vec<(PlasticityOwnerEvidenceKindV1, StableId)>,
    ) -> Result<Self, PlasticityOwnerEvidencePolicyErrorV1> {
        if rules.is_empty() {
            return Err(PlasticityOwnerEvidencePolicyErrorV1::EmptyPolicy);
        }
        let mut allowed_owners =
            BTreeMap::<PlasticityOwnerEvidenceKindV1, BTreeSet<StableId>>::new();
        for (kind, owner_id) in rules {
            allowed_owners.entry(kind).or_default().insert(owner_id);
        }
        for kind in PLASTICITY_OWNER_EVIDENCE_KINDS_V1 {
            if allowed_owners.get(&kind).is_none_or(BTreeSet::is_empty) {
                return Err(PlasticityOwnerEvidencePolicyErrorV1::MissingKind(kind));
            }
        }
        Ok(Self { allowed_owners })
    }

    fn allows(&self, kind: PlasticityOwnerEvidenceKindV1, owner_id: &StableId) -> bool {
        self.allowed_owners
            .get(&kind)
            .is_some_and(|owners| owners.contains(owner_id))
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.plasticity-owner-evidence-policy.v1\0".to_vec();
        for kind in PLASTICITY_OWNER_EVIDENCE_KINDS_V1 {
            bytes.push(kind.tag());
            if let Some(owners) = self.allowed_owners.get(&kind) {
                bytes.extend_from_slice(
                    &u32::try_from(owners.len())
                        .unwrap_or(u32::MAX)
                        .to_be_bytes(),
                );
                for owner in owners {
                    let raw = owner.as_str().as_bytes();
                    bytes.extend_from_slice(
                        &u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes(),
                    );
                    bytes.extend_from_slice(raw);
                }
            } else {
                bytes.extend_from_slice(&0_u32.to_be_bytes());
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityOwnerEvidenceQueryV1 {
    pub kind: PlasticityOwnerEvidenceKindV1,
    pub evidence_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub artifact_registry_head_digest: Digest32,
    pub qualification_evidence_head_digest: Digest32,
    pub window: ProposalWindowV2,
    pub dataset_digest: Digest32,
    pub baseline_generation: Generation,
    pub layer_id: Option<StableId>,
    pub parameter_id: Option<StableId>,
    pub signal_eligibility: Option<FixedQ32>,
    pub signal_modulator: Option<FixedQ32>,
    pub signal_learning_rate: Option<FixedQ32>,
    pub signal_lower_bound: Option<FixedQ32>,
    pub signal_upper_bound: Option<FixedQ32>,
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
    pub artifact_registry_head_digest: Digest32,
    pub qualification_evidence_head_digest: Digest32,
    pub window: ProposalWindowV2,
    pub dataset_digest: Digest32,
    pub baseline_generation: Generation,
    pub layer_id: Option<StableId>,
    pub parameter_id: Option<StableId>,
    pub signal_eligibility: Option<FixedQ32>,
    pub signal_modulator: Option<FixedQ32>,
    pub signal_learning_rate: Option<FixedQ32>,
    pub signal_lower_bound: Option<FixedQ32>,
    pub signal_upper_bound: Option<FixedQ32>,
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
    policy: &PlasticityOwnerEvidencePolicyV1,
    query: &PlasticityOwnerEvidenceQueryV1,
) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
    validate_owner_evidence_query(query)?;
    let receipt = resolver.resolve(query)?;
    if receipt.kind != query.kind
        || receipt.evidence_digest != query.evidence_digest
        || receipt.objective_digest != query.objective_digest
        || receipt.selected_artifact_digest != query.selected_artifact_digest
        || receipt.artifact_registry_head_digest != query.artifact_registry_head_digest
        || receipt.qualification_evidence_head_digest != query.qualification_evidence_head_digest
        || receipt.window != query.window
        || receipt.dataset_digest != query.dataset_digest
        || receipt.baseline_generation != query.baseline_generation
        || receipt.layer_id != query.layer_id
        || receipt.parameter_id != query.parameter_id
        || receipt.signal_eligibility != query.signal_eligibility
        || receipt.signal_modulator != query.signal_modulator
        || receipt.signal_learning_rate != query.signal_learning_rate
        || receipt.signal_lower_bound != query.signal_lower_bound
        || receipt.signal_upper_bound != query.signal_upper_bound
    {
        return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
    }
    if receipt.owner_store_head_digest.is_zero() || receipt.owner_receipt_digest.is_zero() {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    if !policy.allows(query.kind, &receipt.owner_id) {
        return Err(PlasticityOwnerEvidenceErrorV1::Unauthorized);
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
        receipt.artifact_registry_head_digest,
        receipt.qualification_evidence_head_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_owner_id(&mut bytes, &receipt.window.window_id)?;
    bytes.extend_from_slice(receipt.window.window_digest.as_array());
    bytes.extend_from_slice(receipt.dataset_digest.as_array());
    bytes.extend_from_slice(&receipt.baseline_generation.get().to_be_bytes());
    push_optional_owner_id(&mut bytes, receipt.layer_id.as_ref())?;
    push_optional_owner_id(&mut bytes, receipt.parameter_id.as_ref())?;
    for value in [
        receipt.signal_eligibility,
        receipt.signal_modulator,
        receipt.signal_learning_rate,
        receipt.signal_lower_bound,
        receipt.signal_upper_bound,
    ] {
        push_optional_fixed_q32(&mut bytes, value);
    }
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
        || query.artifact_registry_head_digest.is_zero()
        || query.qualification_evidence_head_digest.is_zero()
        || query.window.window_digest.is_zero()
        || query.dataset_digest.is_zero()
    {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    let signal_values = [
        query.signal_eligibility,
        query.signal_modulator,
        query.signal_learning_rate,
        query.signal_lower_bound,
        query.signal_upper_bound,
    ];
    match query.kind {
        PlasticityOwnerEvidenceKindV1::ParameterSignal => {
            if query.layer_id.is_none()
                || query.parameter_id.is_none()
                || signal_values.iter().any(Option::is_none)
            {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
        _ => {
            if query.layer_id.is_some()
                || query.parameter_id.is_some()
                || signal_values.iter().any(Option::is_some)
            {
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

fn push_optional_fixed_q32(bytes: &mut Vec<u8>, value: Option<FixedQ32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
}

/// Independently durable append-only host journal for the proposal-registry fence
/// and last acknowledged anchor. The caller must place this file in a rollback
/// domain independent from the proposal registry file.
pub struct AgentdPlasticityAnchorStoreV1 {
    journal: AdaptiveAnchorJournalV1,
}

impl From<AdaptiveAnchorJournalErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: AdaptiveAnchorJournalErrorV1) -> Self {
        match value {
            AdaptiveAnchorJournalErrorV1::Busy => Self::AnchorBusy,
            AdaptiveAnchorJournalErrorV1::NotRegular => Self::AnchorNotRegular,
            AdaptiveAnchorJournalErrorV1::ScopeMismatch => Self::AnchorScopeMismatch,
            AdaptiveAnchorJournalErrorV1::FenceOverflow => Self::AnchorFenceOverflow,
            AdaptiveAnchorJournalErrorV1::Io(kind) => Self::AnchorIo(kind),
            AdaptiveAnchorJournalErrorV1::InvalidScope
            | AdaptiveAnchorJournalErrorV1::Corrupt
            | AdaptiveAnchorJournalErrorV1::GenerationPending
            | AdaptiveAnchorJournalErrorV1::Capacity => Self::AnchorCorrupt,
        }
    }
}

impl AgentdPlasticityAnchorStoreV1 {
    pub fn open(file: File, scope: Digest32) -> Result<Self, AgentdPlasticityHostErrorV1> {
        Ok(Self {
            journal: AdaptiveAnchorJournalV1::open(file, scope, ANCHOR_MAGIC)?,
        })
    }

    /// Issue a strictly newer fence for a new proposal-registry generation.
    /// A pending unacknowledged generation cannot skip to another fence.
    pub fn issue_next_fence(&mut self) -> Result<u64, AgentdPlasticityHostErrorV1> {
        self.journal.issue_new_registry_fence().map_err(Into::into)
    }

    pub const fn fence(&self) -> u64 {
        self.journal.state().writer_fence
    }

    pub fn anchor(&self) -> Option<DurableRegistryAnchorV1> {
        self.journal
            .state()
            .anchor
            .map(|anchor| DurableRegistryAnchorV1 {
                sequence: anchor.sequence,
                frame_digest: anchor.frame_digest,
            })
    }

    pub fn previous_anchor(&self) -> Option<DurableRegistryAnchorV1> {
        self.journal
            .state()
            .previous_anchor
            .map(|anchor| DurableRegistryAnchorV1 {
                sequence: anchor.sequence,
                frame_digest: anchor.frame_digest,
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
        self.journal
            .persist_anchor(
                registry_scope_digest,
                writer_fence,
                AdaptiveAnchorV1 {
                    sequence: anchor.sequence,
                    frame_digest: anchor.frame_digest,
                },
            )
            .is_ok()
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
    policy: &PlasticityOwnerEvidencePolicyV1,
    artifact_registry_head_digest: Digest32,
    qualification_evidence_head_digest: Digest32,
    now: u64,
) -> Result<Digest32, AgentdPlasticityHostErrorV1> {
    if input.generator_profile.selected_artifact_digest != input.generated.selected_artifact_digest
        || input.generator_profile.window != input.generated.window
    {
        return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch.into());
    }

    let mut digests = Vec::with_capacity(6 + input.generator_profile.signals.len());
    for (kind, evidence_digest) in [
        (PlasticityOwnerEvidenceKindV1::Dataset, input.dataset_digest),
        (
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            input.update_rule_digest,
        ),
        (
            PlasticityOwnerEvidenceKindV1::Modulator,
            input.modulator_digest,
        ),
        (
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            input.modulator_broadcast_digest,
        ),
        (
            PlasticityOwnerEvidenceKindV1::Eligibility,
            input.eligibility_digest,
        ),
        (
            PlasticityOwnerEvidenceKindV1::MutationPolicy,
            input.generator_profile.mutation_policy.policy_digest,
        ),
    ] {
        digests.push(verify_agentd_plasticity_owner_evidence_v1(
            resolver,
            policy,
            &owner_evidence_query(
                input,
                kind,
                evidence_digest,
                None,
                artifact_registry_head_digest,
                qualification_evidence_head_digest,
                now,
            ),
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
            policy,
            &owner_evidence_query(
                input,
                PlasticityOwnerEvidenceKindV1::ParameterSignal,
                signal.evidence_digest,
                Some(signal),
                artifact_registry_head_digest,
                qualification_evidence_head_digest,
                now,
            ),
        )?);
    }

    let mut bytes = b"hepta.agentd.plasticity-owner-evidence-set.v1\0".to_vec();
    bytes.extend_from_slice(policy.digest().as_array());
    let count =
        u32::try_from(digests.len()).map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
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
    signal: Option<&ParameterPlasticitySignalV3>,
    artifact_registry_head_digest: Digest32,
    qualification_evidence_head_digest: Digest32,
    now: u64,
) -> PlasticityOwnerEvidenceQueryV1 {
    PlasticityOwnerEvidenceQueryV1 {
        kind,
        evidence_digest,
        objective_digest: input.objective_digest,
        selected_artifact_digest: input.generated.selected_artifact_digest,
        artifact_registry_head_digest,
        qualification_evidence_head_digest,
        window: input.generated.window.clone(),
        dataset_digest: input.dataset_digest,
        baseline_generation: input.baseline_generation,
        layer_id: signal.map(|value| value.layer_id.clone()),
        parameter_id: signal.map(|value| value.parameter_id.clone()),
        signal_eligibility: signal.map(|value| value.eligibility),
        signal_modulator: signal.map(|value| value.modulator),
        signal_learning_rate: signal.map(|value| value.learning_rate),
        signal_lower_bound: signal.map(|value| value.lower_bound),
        signal_upper_bound: signal.map(|value| value.upper_bound),
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
    owner_evidence_policy: &PlasticityOwnerEvidencePolicyV1,
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
    let owner_evidence_set_digest = resolve_agentd_plasticity_owner_evidence_set_v1(
        input,
        owner_evidence_resolver,
        owner_evidence_policy,
        artifact_registry_head_digest,
        ledger_snapshot.head_digest,
        now,
    )?;
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
    owner_evidence_policy: &PlasticityOwnerEvidencePolicyV1,
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
        owner_evidence_policy,
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
    if anchor_store.anchor().is_some() || anchor_store.fence() != 0 {
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

pub fn rollover_agentd_plasticity_writer_v1(
    registry_file: File,
    anchor_file: File,
    registry_scope_digest: Digest32,
    maximum_records: usize,
    expected_previous_anchor: DurableRegistryAnchorV1,
) -> Result<(AnchoredPlasticityWriterV1, AgentdPlasticityAnchorStoreV1), AgentdPlasticityHostErrorV1>
{
    let mut anchor_store = AgentdPlasticityAnchorStoreV1::open(anchor_file, registry_scope_digest)?;
    if anchor_store.anchor() != Some(expected_previous_anchor) {
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

/// Resume a generation whose fence was durably issued but whose new registry is
/// still empty. This never issues another fence and therefore cannot skip a
/// generation after a crash between fence reservation and registry enrollment.
pub fn resume_agentd_plasticity_writer_v1(
    registry_file: File,
    anchor_file: File,
    registry_scope_digest: Digest32,
    maximum_records: usize,
) -> Result<(AnchoredPlasticityWriterV1, AgentdPlasticityAnchorStoreV1), AgentdPlasticityHostErrorV1>
{
    let anchor_store = AgentdPlasticityAnchorStoreV1::open(anchor_file, registry_scope_digest)?;
    if anchor_store.fence() == 0 || anchor_store.anchor().is_some() {
        return Err(AgentdPlasticityHostErrorV1::AnchorCorrupt);
    }
    let writer = AnchoredPlasticityWriterV1::resume_unacknowledged_bootstrap(
        registry_file,
        registry_scope_digest,
        anchor_store.fence(),
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
                artifact_registry_head_digest: query.artifact_registry_head_digest,
                qualification_evidence_head_digest: query.qualification_evidence_head_digest,
                window: query.window.clone(),
                dataset_digest: query.dataset_digest,
                baseline_generation: query.baseline_generation,
                layer_id: query.layer_id.clone(),
                parameter_id: query.parameter_id.clone(),
                signal_eligibility: query.signal_eligibility,
                signal_modulator: query.signal_modulator,
                signal_learning_rate: query.signal_learning_rate,
                signal_lower_bound: query.signal_lower_bound,
                signal_upper_bound: query.signal_upper_bound,
                observed_at: 49,
                expires_at: 51,
            })
        }
    }

    fn owner_policy() -> PlasticityOwnerEvidencePolicyV1 {
        let owner = StableId::new("owner:learning").expect("id");
        PlasticityOwnerEvidencePolicyV1::from_rules(
            PLASTICITY_OWNER_EVIDENCE_KINDS_V1
                .into_iter()
                .map(|kind| (kind, owner.clone()))
                .collect(),
        )
        .expect("owner policy")
    }

    fn owner_query() -> PlasticityOwnerEvidenceQueryV1 {
        PlasticityOwnerEvidenceQueryV1 {
            kind: PlasticityOwnerEvidenceKindV1::UpdateRule,
            evidence_digest: digest(b"update-rule"),
            objective_digest: digest(b"objective"),
            selected_artifact_digest: digest(b"artifact"),
            artifact_registry_head_digest: digest(b"artifact-head"),
            qualification_evidence_head_digest: digest(b"ledger-head"),
            window: ProposalWindowV2 {
                window_id: StableId::new("window:owner-evidence").expect("id"),
                window_digest: digest(b"window"),
            },
            dataset_digest: digest(b"dataset"),
            baseline_generation: Generation::new(7).expect("generation"),
            layer_id: None,
            parameter_id: None,
            signal_eligibility: None,
            signal_modulator: None,
            signal_learning_rate: None,
            signal_lower_bound: None,
            signal_upper_bound: None,
            now: 50,
        }
    }

    #[test]
    fn owner_evidence_receipt_is_context_bound() {
        assert!(
            !verify_agentd_plasticity_owner_evidence_v1(
                &EchoOwnerEvidenceResolver,
                &owner_policy(),
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
    fn owner_evidence_set_includes_mutation_policy_and_canonical_kinds() {
        use std::cell::RefCell;

        struct RecordingResolver {
            seen: RefCell<Vec<(PlasticityOwnerEvidenceKindV1, Digest32)>>,
        }

        impl PlasticityOwnerEvidenceResolverV1 for RecordingResolver {
            fn resolve(
                &self,
                query: &PlasticityOwnerEvidenceQueryV1,
            ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1>
            {
                self.seen
                    .borrow_mut()
                    .push((query.kind, query.evidence_digest));
                EchoOwnerEvidenceResolver.resolve(query)
            }
        }

        let selected_artifact_digest = digest(b"artifact");
        let window = ProposalWindowV2 {
            window_id: StableId::new("window:set").expect("id"),
            window_digest: digest(b"window"),
        };
        let mutation_policy = codex_hepta_plasticity::build_parameter_mutation_policy_v1(
            StableId::new("policy:set").expect("id"),
            digest(b"mutation-grammar"),
            selected_artifact_digest,
            window.clone(),
            Vec::new(),
        )
        .expect("mutation policy");
        let profile = ParameterGeneratorProfileV3 {
            selected_artifact_digest,
            window: window.clone(),
            norm_layers: Vec::new(),
            update_scales: Vec::new(),
            signals: Vec::new(),
            mutation_policy: mutation_policy.clone(),
        };
        let generated = GeneratedParameterCandidateSetV3 {
            selected_artifact_digest,
            window,
            norm_layers: Vec::new(),
            candidates: Vec::new(),
            generator_digest: digest(b"generator"),
        };
        let input = AgentdPlasticityAdmissionInputV1 {
            baseline_id: StableId::new("artifact:baseline").expect("id"),
            objective_digest: digest(b"objective"),
            generator_profile: profile,
            generated,
            baseline_generation: Generation::new(7).expect("generation"),
            candidate_generation: Generation::new(8).expect("generation"),
            dataset_digest: digest(b"dataset"),
            update_rule_digest: digest(b"update-rule"),
            modulator_digest: digest(b"modulator"),
            modulator_broadcast_digest: digest(b"broadcast"),
            eligibility_digest: digest(b"eligibility"),
        };
        let resolver = RecordingResolver {
            seen: RefCell::new(Vec::new()),
        };
        let set_digest = resolve_agentd_plasticity_owner_evidence_set_v1(
            &input,
            &resolver,
            &owner_policy(),
            digest(b"artifact-head"),
            digest(b"ledger-head"),
            50,
        )
        .expect("owner evidence set");
        assert!(!set_digest.is_zero());

        let seen = resolver.seen.borrow();
        assert_eq!(seen.len(), 6);
        assert!(seen.contains(&(
            PlasticityOwnerEvidenceKindV1::MutationPolicy,
            mutation_policy.policy_digest,
        )));
    }

    #[test]
    fn owner_evidence_rejects_context_substitution() {
        assert_eq!(
            verify_agentd_plasticity_owner_evidence_v1(
                &MismatchedOwnerEvidenceResolver,
                &owner_policy(),
                &owner_query(),
            ),
            Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
        );
    }

    struct WrongOwnerResolver;
    impl PlasticityOwnerEvidenceResolverV1 for WrongOwnerResolver {
        fn resolve(
            &self,
            query: &PlasticityOwnerEvidenceQueryV1,
        ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
            let mut receipt = EchoOwnerEvidenceResolver.resolve(query)?;
            receipt.owner_id = StableId::new("owner:wrong").expect("id");
            Ok(receipt)
        }
    }

    struct SignalValueDriftResolver;
    impl PlasticityOwnerEvidenceResolverV1 for SignalValueDriftResolver {
        fn resolve(
            &self,
            query: &PlasticityOwnerEvidenceQueryV1,
        ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
            let mut receipt = EchoOwnerEvidenceResolver.resolve(query)?;
            receipt.signal_modulator = Some(FixedQ32::ONE);
            Ok(receipt)
        }
    }

    #[test]
    fn owner_evidence_rejects_parameter_signal_value_substitution() {
        let mut query = owner_query();
        query.kind = PlasticityOwnerEvidenceKindV1::ParameterSignal;
        query.evidence_digest = digest(b"parameter-signal");
        query.layer_id = Some(StableId::new("layer:signal").expect("id"));
        query.parameter_id = Some(StableId::new("parameter:signal").expect("id"));
        query.signal_eligibility = Some(FixedQ32::from_raw(11));
        query.signal_modulator = Some(FixedQ32::from_raw(12));
        query.signal_learning_rate = Some(FixedQ32::from_raw(13));
        query.signal_lower_bound = Some(FixedQ32::from_raw(-100));
        query.signal_upper_bound = Some(FixedQ32::from_raw(100));

        assert_eq!(
            verify_agentd_plasticity_owner_evidence_v1(
                &SignalValueDriftResolver,
                &owner_policy(),
                &query,
            ),
            Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
        );
    }

    #[test]
    fn owner_evidence_policy_rejects_authenticated_wrong_owner() {
        assert_eq!(
            verify_agentd_plasticity_owner_evidence_v1(
                &WrongOwnerResolver,
                &owner_policy(),
                &owner_query(),
            ),
            Err(PlasticityOwnerEvidenceErrorV1::Unauthorized)
        );
    }

    #[test]
    fn retained_external_anchor_blocks_rolled_back_registry_reopen() {
        let registry_file = tempfile().expect("registry file");
        let anchor_file = tempfile().expect("anchor file");
        let scope = digest(b"rollback-domain-scope");
        let (writer, mut anchor_store) = bootstrap_agentd_plasticity_writer_v1(
            registry_file.try_clone().expect("registry clone"),
            anchor_file.try_clone().expect("anchor clone"),
            scope,
            8,
        )
        .expect("bootstrap");
        drop(writer);

        // Simulate the independently retained acknowledgement surviving while
        // the proposal registry has been rolled back to its header-only prefix.
        let acknowledged = DurableRegistryAnchorV1 {
            sequence: 1,
            frame_digest: digest(b"acknowledged-frame"),
        };
        assert!(anchor_store.persist_anchor(scope, 1, acknowledged));
        drop(anchor_store);

        let result = reopen_agentd_plasticity_writer_v1(
            registry_file,
            anchor_file,
            scope,
            8,
        );
        assert!(matches!(
            result,
            Err(AgentdPlasticityHostErrorV1::Writer(
                AnchoredPlasticityWriterErrorV1::Registry(
                    codex_hepta_plasticity::DurableProposalRegistryError::AcknowledgedHistoryMissing
                )
            ))
        ));
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
