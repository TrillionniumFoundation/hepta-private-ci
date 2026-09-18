//! Explicit Agentd host for governed learning.plasticity proposal construction.
//!
//! Agentd owns only lifecycle/composition and the host anti-rollback journal. It
//! does not become the writer for learning artifacts, qualification evidence or
//! plasticity proposals. The owning registries/resolvers remain authoritative.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::{Read, Seek, SeekFrom, Write};

use codex_hepta_intelligence::{
    AnchoredPlasticityWriterV1, ParameterPlasticityProductErrorV1,
    ParameterPlasticityProductReceiptV1, ParameterPlasticityProductRequestV1,
    PlasticityAnchorCommitterV1, propose_authenticated_parameter_plasticity_v1,
};
use codex_hepta_learning_artifacts::{ArtifactKind, ArtifactManifest, ArtifactRegistry};
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::{Digest32, Generation, StableId};

const ANCHOR_MAGIC: &[u8; 8] = b"HPAF0001";
const ANCHOR_HEADER_BYTES: usize = 8 + 32 + 32;
const ANCHOR_FRAME_BYTES: usize = 1 + 8 + 8 + 32 + 32;
const ANCHOR_TAG_FENCE: u8 = 0;
const ANCHOR_TAG_COMMIT: u8 = 1;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlasticityOwnerEvidenceKindV1 {
    UpdateRule,
    Modulator,
    ModulatorBroadcast,
    Eligibility,
    ParameterSignal,
}

impl PlasticityOwnerEvidenceKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::UpdateRule => 0,
            Self::Modulator => 1,
            Self::ModulatorBroadcast => 2,
            Self::Eligibility => 3,
            Self::ParameterSignal => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityOwnerEvidenceQueryV1 {
    pub kind: PlasticityOwnerEvidenceKindV1,
    pub evidence_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window_id: StableId,
    pub window_digest: Digest32,
    pub dataset_digest: Digest32,
    pub baseline_generation: Generation,
    pub layer_id: Option<StableId>,
    pub parameter_id: Option<StableId>,
    pub now: u64,
}

/// Canonical context identity that an owner-store adapter must bind into the
/// authenticated receipt it returns. Agentd recomputes this value rather than
/// trusting the resolver to describe which request it verified.
pub fn plasticity_owner_evidence_query_digest_v1(
    query: &PlasticityOwnerEvidenceQueryV1,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.plasticity-owner-evidence-query.v1\0".to_vec();
    bytes.push(query.kind.tag());
    bytes.extend_from_slice(query.evidence_digest.as_array());
    bytes.extend_from_slice(query.objective_digest.as_array());
    bytes.extend_from_slice(query.selected_artifact_digest.as_array());
    push_id(&mut bytes, &query.window_id);
    bytes.extend_from_slice(query.window_digest.as_array());
    bytes.extend_from_slice(query.dataset_digest.as_array());
    bytes.extend_from_slice(&query.baseline_generation.get().to_be_bytes());
    match &query.layer_id {
        Some(layer_id) => {
            bytes.push(1);
            push_id(&mut bytes, layer_id);
        }
        None => bytes.push(0),
    }
    match &query.parameter_id {
        Some(parameter_id) => {
            bytes.push(1);
            push_id(&mut bytes, parameter_id);
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&query.now.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityOwnerEvidenceReceiptV1 {
    pub evidence_digest: Digest32,
    pub query_digest: Digest32,
    pub owner_id: StableId,
    pub owner_receipt_digest: Digest32,
    pub frontier_head_digest: Digest32,
    pub observed_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityOwnerEvidenceErrorV1 {
    Unavailable,
    Missing,
    Unauthorized,
    ContextMismatch,
    Stale,
    InvalidReceipt,
}
impl fmt::Display for PlasticityOwnerEvidenceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityOwnerEvidenceErrorV1 {}

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

/// Explicit host policy for which owner identities may attest each evidence kind.
/// The resolver authenticates an owner-store receipt; this policy independently
/// prevents a valid receipt from the wrong owner from satisfying the request.
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
        for kind in [
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            PlasticityOwnerEvidenceKindV1::Modulator,
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            PlasticityOwnerEvidenceKindV1::Eligibility,
            PlasticityOwnerEvidenceKindV1::ParameterSignal,
        ] {
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
        for kind in [
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            PlasticityOwnerEvidenceKindV1::Modulator,
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            PlasticityOwnerEvidenceKindV1::Eligibility,
            PlasticityOwnerEvidenceKindV1::ParameterSignal,
        ] {
            bytes.push(kind.tag());
            if let Some(owners) = self.allowed_owners.get(&kind) {
                bytes.extend_from_slice(
                    &u32::try_from(owners.len()).unwrap_or(u32::MAX).to_be_bytes(),
                );
                for owner in owners {
                    push_id(&mut bytes, owner);
                }
            } else {
                bytes.extend_from_slice(&0_u32.to_be_bytes());
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Selected-host adapter to the actual owner stores. Implementations must resolve
/// the requested digest from its owner registry and authenticate the returned
/// owner receipt; copying the query into a receipt is not a valid implementation.
pub trait PlasticityOwnerEvidenceResolverV1 {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<PlasticityOwnerEvidenceReceiptV1, PlasticityOwnerEvidenceErrorV1>;
}

#[derive(Debug)]
pub enum AgentdPlasticityHostErrorV1 {
    Artifact(&'static str),
    Evidence(PlasticityOwnerEvidenceErrorV1),
    EvidencePolicy(PlasticityOwnerEvidencePolicyErrorV1),
    EvidenceFrontierMismatch,
    Product(ParameterPlasticityProductErrorV1),
}
impl fmt::Display for AgentdPlasticityHostErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdPlasticityHostErrorV1 {}
impl From<PlasticityOwnerEvidenceErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: PlasticityOwnerEvidenceErrorV1) -> Self {
        Self::Evidence(value)
    }
}
impl From<PlasticityOwnerEvidencePolicyErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: PlasticityOwnerEvidencePolicyErrorV1) -> Self {
        Self::EvidencePolicy(value)
    }
}
impl From<ParameterPlasticityProductErrorV1> for AgentdPlasticityHostErrorV1 {
    fn from(value: ParameterPlasticityProductErrorV1) -> Self {
        Self::Product(value)
    }
}

/// Non-test selected-host call surface. It actively re-reads the authoritative
/// artifact registry and resolves every learning evidence digest before invoking
/// the authenticated product adapter.
pub struct AgentdPlasticityHostV1<'a, R: PlasticityOwnerEvidenceResolverV1 + ?Sized> {
    artifacts: &'a ArtifactRegistry,
    evidence: &'a R,
    evidence_policy: &'a PlasticityOwnerEvidencePolicyV1,
}

impl<'a, R: PlasticityOwnerEvidenceResolverV1 + ?Sized> AgentdPlasticityHostV1<'a, R> {
    pub const fn new(
        artifacts: &'a ArtifactRegistry,
        evidence: &'a R,
        evidence_policy: &'a PlasticityOwnerEvidencePolicyV1,
    ) -> Self {
        Self {
            artifacts,
            evidence,
            evidence_policy,
        }
    }

    pub fn propose_parameter_plasticity(
        &self,
        mut request: ParameterPlasticityProductRequestV1,
        verifier: &LearningEvidenceVerifierV1,
        writer: &mut AnchoredPlasticityWriterV1,
        anchor_committer: &mut impl PlasticityAnchorCommitterV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, AgentdPlasticityHostErrorV1> {
        self.verify_artifact_frontier(&request)?;
        request.host_evidence_verification_digest = self.verify_owner_evidence(&request, now)?;
        propose_authenticated_parameter_plasticity_v1(
            request,
            verifier,
            writer,
            anchor_committer,
            now,
        )
        .map_err(Into::into)
    }

    fn verify_artifact_frontier(
        &self,
        request: &ParameterPlasticityProductRequestV1,
    ) -> Result<(), AgentdPlasticityHostErrorV1> {
        let admission = &request.admission;
        let manifest = self
            .artifacts
            .manifest(&admission.baseline_id)
            .ok_or(AgentdPlasticityHostErrorV1::Artifact("baseline missing"))?;
        if !self.artifacts.is_eligible(&admission.baseline_id) {
            return Err(AgentdPlasticityHostErrorV1::Artifact(
                "baseline lineage unavailable",
            ));
        }
        if !matches!(manifest.kind, ArtifactKind::Parameters | ArtifactKind::Model) {
            return Err(AgentdPlasticityHostErrorV1::Artifact("baseline kind"));
        }
        if manifest.content_digest != admission.selected_artifact_digest
            || manifest.objective_digest != admission.objective_digest
            || manifest.generation != admission.baseline_generation
        {
            return Err(AgentdPlasticityHostErrorV1::Artifact("baseline binding"));
        }
        let head = self.artifacts.snapshot().head_digest;
        if head.is_zero() || head != admission.artifact_registry_head_digest {
            return Err(AgentdPlasticityHostErrorV1::Artifact(
                "artifact registry head",
            ));
        }
        if artifact_frontier_binding_v1(manifest, head) != admission.artifact_registry_binding {
            return Err(AgentdPlasticityHostErrorV1::Artifact(
                "artifact frontier binding",
            ));
        }
        Ok(())
    }

    fn verify_owner_evidence(
        &self,
        request: &ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<Digest32, AgentdPlasticityHostErrorV1> {
        let admission = &request.admission;
        let mut frontier: Option<Digest32> = None;
        let mut verification =
            b"hepta.agentd.plasticity-owner-evidence-verification.v1\0".to_vec();
        verification.extend_from_slice(self.evidence_policy.digest().as_array());
        for (kind, digest, layer_id, parameter_id) in [
            (
                PlasticityOwnerEvidenceKindV1::UpdateRule,
                admission.update_rule_digest,
                None,
                None,
            ),
            (
                PlasticityOwnerEvidenceKindV1::Modulator,
                admission.modulator_digest,
                None,
                None,
            ),
            (
                PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
                admission.modulator_broadcast_digest,
                None,
                None,
            ),
            (
                PlasticityOwnerEvidenceKindV1::Eligibility,
                admission.eligibility_digest,
                None,
                None,
            ),
        ] {
            let receipt =
                self.resolve_one(request, kind, digest, layer_id, parameter_id, now)?;
            bind_frontier(&mut frontier, &receipt)?;
            verification.extend_from_slice(
                plasticity_owner_evidence_receipt_digest_v1(&receipt).as_array(),
            );
        }
        for signal in &request.generator_profile.signals {
            let receipt = self.resolve_one(
                request,
                PlasticityOwnerEvidenceKindV1::ParameterSignal,
                signal.evidence_digest,
                Some(signal.layer_id.clone()),
                Some(signal.parameter_id.clone()),
                now,
            )?;
            bind_frontier(&mut frontier, &receipt)?;
            verification.extend_from_slice(
                plasticity_owner_evidence_receipt_digest_v1(&receipt).as_array(),
            );
        }
        if frontier != Some(admission.qualification_evidence_head_digest) {
            return Err(AgentdPlasticityHostErrorV1::EvidenceFrontierMismatch);
        }
        verification.extend_from_slice(admission.qualification_evidence_head_digest.as_array());
        Ok(Digest32::of_bytes(&verification))
    }

    fn resolve_one(
        &self,
        request: &ParameterPlasticityProductRequestV1,
        kind: PlasticityOwnerEvidenceKindV1,
        evidence_digest: Digest32,
        layer_id: Option<StableId>,
        parameter_id: Option<StableId>,
        now: u64,
    ) -> Result<PlasticityOwnerEvidenceReceiptV1, AgentdPlasticityHostErrorV1> {
        if evidence_digest.is_zero() || now == 0 {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt.into());
        }
        let admission = &request.admission;
        let query = PlasticityOwnerEvidenceQueryV1 {
            kind,
            evidence_digest,
            objective_digest: admission.objective_digest,
            selected_artifact_digest: admission.selected_artifact_digest,
            window_id: admission.window.window_id.clone(),
            window_digest: admission.window.window_digest,
            dataset_digest: admission.dataset_digest,
            baseline_generation: admission.baseline_generation,
            layer_id,
            parameter_id,
            now,
        };
        let query_digest = plasticity_owner_evidence_query_digest_v1(&query);
        let receipt = self.evidence.resolve(&query)?;
        if receipt.evidence_digest != evidence_digest
            || receipt.owner_receipt_digest.is_zero()
            || receipt.frontier_head_digest.is_zero()
        {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt.into());
        }
        if receipt.query_digest != query_digest {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch.into());
        }
        if !self.evidence_policy.allows(kind, &receipt.owner_id) {
            return Err(PlasticityOwnerEvidenceErrorV1::Unauthorized.into());
        }
        if receipt.observed_at > receipt.expires_at
            || now < receipt.observed_at
            || now > receipt.expires_at
        {
            return Err(PlasticityOwnerEvidenceErrorV1::Stale.into());
        }
        Ok(receipt)
    }
}

/// Stable binding used by the Observer attestation. It is deliberately derived
/// from the authoritative artifact registry, not caller-provided prose.
pub fn artifact_frontier_binding_v1(manifest: &ArtifactManifest, head: Digest32) -> Digest32 {
    let mut bytes = b"hepta.agentd.plasticity-artifact-frontier.v1\0".to_vec();
    push_id(&mut bytes, &manifest.artifact_id);
    bytes.extend_from_slice(&manifest.generation.get().to_be_bytes());
    bytes.extend_from_slice(manifest.content_digest.as_array());
    bytes.extend_from_slice(manifest.objective_digest.as_array());
    bytes.extend_from_slice(manifest.support_digest.as_array());
    bytes.extend_from_slice(manifest.compatibility_digest.as_array());
    bytes.extend_from_slice(head.as_array());
    Digest32::of_bytes(&bytes)
}

fn plasticity_owner_evidence_receipt_digest_v1(
    receipt: &PlasticityOwnerEvidenceReceiptV1,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.plasticity-owner-evidence-receipt.v1\0".to_vec();
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    bytes.extend_from_slice(receipt.query_digest.as_array());
    push_id(&mut bytes, &receipt.owner_id);
    bytes.extend_from_slice(receipt.owner_receipt_digest.as_array());
    bytes.extend_from_slice(receipt.frontier_head_digest.as_array());
    bytes.extend_from_slice(&receipt.observed_at.to_be_bytes());
    bytes.extend_from_slice(&receipt.expires_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn bind_frontier(
    frontier: &mut Option<Digest32>,
    receipt: &PlasticityOwnerEvidenceReceiptV1,
) -> Result<(), AgentdPlasticityHostErrorV1> {
    match *frontier {
        None => *frontier = Some(receipt.frontier_head_digest),
        Some(value) if value == receipt.frontier_head_digest => {}
        Some(_) => return Err(AgentdPlasticityHostErrorV1::EvidenceFrontierMismatch),
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AgentdPlasticityAnchorStateV1 {
    pub writer_fence: u64,
    pub anchor: Option<codex_hepta_intelligence::DurableRegistryAnchorV1>,
}

#[derive(Debug)]
pub enum AgentdPlasticityAnchorStoreErrorV1 {
    Busy,
    NotRegular,
    InvalidScope,
    Corrupt,
    FenceOverflow,
    Io(std::io::ErrorKind),
}
impl fmt::Display for AgentdPlasticityAnchorStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdPlasticityAnchorStoreErrorV1 {}
impl From<std::io::Error> for AgentdPlasticityAnchorStoreErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

/// Append-only host journal for writer-fence issuance and independently retained
/// registry anchors. The deployment must place this file in a rollback domain
/// independent from the proposal registry file.
pub struct AgentdPlasticityAnchorFenceStoreV1 {
    file: File,
    scope: Digest32,
    state: AgentdPlasticityAnchorStateV1,
}

impl AgentdPlasticityAnchorFenceStoreV1 {
    pub fn open(
        mut file: File,
        scope: Digest32,
    ) -> Result<Self, AgentdPlasticityAnchorStoreErrorV1> {
        if scope.is_zero() {
            return Err(AgentdPlasticityAnchorStoreErrorV1::InvalidScope);
        }
        if !file.metadata()?.is_file() {
            return Err(AgentdPlasticityAnchorStoreErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => {
                return Err(AgentdPlasticityAnchorStoreErrorV1::Busy);
            }
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }
        let expected_header = encode_anchor_header(scope);
        let length = file.metadata()?.len();
        if length == 0 {
            file.write_all(&expected_header)?;
            file.sync_all()?;
        } else {
            if length < ANCHOR_HEADER_BYTES as u64 {
                return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt);
            }
            let mut header = vec![0_u8; ANCHOR_HEADER_BYTES];
            file.seek(SeekFrom::Start(0))?;
            file.read_exact(&mut header)?;
            if header != expected_header {
                return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt);
            }
        }
        let mut state = AgentdPlasticityAnchorStateV1 {
            writer_fence: 0,
            anchor: None,
        };
        let mut offset = ANCHOR_HEADER_BYTES as u64;
        let length = file.metadata()?.len();
        while offset < length {
            if length - offset < ANCHOR_FRAME_BYTES as u64 {
                return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt);
            }
            file.seek(SeekFrom::Start(offset))?;
            let mut frame = [0_u8; ANCHOR_FRAME_BYTES];
            file.read_exact(&mut frame)?;
            apply_anchor_frame(&frame, &mut state)?;
            offset += ANCHOR_FRAME_BYTES as u64;
        }
        Ok(Self { file, scope, state })
    }

    #[must_use]
    pub const fn state(&self) -> AgentdPlasticityAnchorStateV1 {
        self.state
    }

    /// Reserve a strictly newer fence for a newly enrolled proposal-registry file.
    /// Reopening an existing registry uses `state().writer_fence` instead.
    pub fn issue_new_registry_fence(
        &mut self,
    ) -> Result<u64, AgentdPlasticityAnchorStoreErrorV1> {
        let next = self
            .state
            .writer_fence
            .checked_add(1)
            .ok_or(AgentdPlasticityAnchorStoreErrorV1::FenceOverflow)?;
        let frame = encode_anchor_frame(ANCHOR_TAG_FENCE, next, None);
        append_anchor_frame(&mut self.file, &frame)?;
        self.state = AgentdPlasticityAnchorStateV1 {
            writer_fence: next,
            anchor: None,
        };
        Ok(next)
    }
}

impl PlasticityAnchorCommitterV1 for AgentdPlasticityAnchorFenceStoreV1 {
    fn persist_anchor(
        &mut self,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        anchor: codex_hepta_intelligence::DurableRegistryAnchorV1,
    ) -> bool {
        if registry_scope_digest != self.scope
            || writer_fence == 0
            || writer_fence != self.state.writer_fence
            || anchor.sequence == 0
            || anchor.frame_digest.is_zero()
        {
            return false;
        }
        if let Some(current) = self.state.anchor {
            if anchor.sequence < current.sequence
                || (anchor.sequence == current.sequence
                    && anchor.frame_digest != current.frame_digest)
            {
                return false;
            }
            if anchor == current {
                return true;
            }
        }
        let frame = encode_anchor_frame(ANCHOR_TAG_COMMIT, writer_fence, Some(anchor));
        if append_anchor_frame(&mut self.file, &frame).is_err() {
            return false;
        }
        self.state.anchor = Some(anchor);
        true
    }
}

impl Drop for AgentdPlasticityAnchorFenceStoreV1 {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

fn encode_anchor_header(scope: Digest32) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(ANCHOR_HEADER_BYTES);
    bytes.extend_from_slice(ANCHOR_MAGIC);
    bytes.extend_from_slice(scope.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    bytes
}

fn encode_anchor_frame(
    tag: u8,
    writer_fence: u64,
    anchor: Option<codex_hepta_intelligence::DurableRegistryAnchorV1>,
) -> [u8; ANCHOR_FRAME_BYTES] {
    let mut frame = [0_u8; ANCHOR_FRAME_BYTES];
    frame[0] = tag;
    frame[1..9].copy_from_slice(&writer_fence.to_be_bytes());
    if let Some(anchor) = anchor {
        frame[9..17].copy_from_slice(&anchor.sequence.to_be_bytes());
        frame[17..49].copy_from_slice(anchor.frame_digest.as_array());
    }
    let checksum = Digest32::of_bytes(&frame[..49]);
    frame[49..81].copy_from_slice(checksum.as_array());
    frame
}

fn apply_anchor_frame(
    frame: &[u8; ANCHOR_FRAME_BYTES],
    state: &mut AgentdPlasticityAnchorStateV1,
) -> Result<(), AgentdPlasticityAnchorStoreErrorV1> {
    if Digest32::of_bytes(&frame[..49]).as_array() != &frame[49..81] {
        return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt);
    }
    let fence = u64::from_be_bytes(frame[1..9].try_into().expect("fixed slice"));
    let sequence = u64::from_be_bytes(frame[9..17].try_into().expect("fixed slice"));
    let digest = Digest32::from_array(frame[17..49].try_into().expect("fixed slice"));
    match frame[0] {
        ANCHOR_TAG_FENCE => {
            if fence == 0 || fence != state.writer_fence.saturating_add(1) || sequence != 0 || !digest.is_zero() {
                return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt);
            }
            *state = AgentdPlasticityAnchorStateV1 {
                writer_fence: fence,
                anchor: None,
            };
        }
        ANCHOR_TAG_COMMIT => {
            if fence == 0 || fence != state.writer_fence || sequence == 0 || digest.is_zero() {
                return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt);
            }
            let next = codex_hepta_intelligence::DurableRegistryAnchorV1 {
                sequence,
                frame_digest: digest,
            };
            if let Some(current) = state.anchor {
                if next.sequence < current.sequence
                    || (next.sequence == current.sequence
                        && next.frame_digest != current.frame_digest)
                {
                    return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt);
                }
            }
            state.anchor = Some(next);
        }
        _ => return Err(AgentdPlasticityAnchorStoreErrorV1::Corrupt),
    }
    Ok(())
}

fn append_anchor_frame(
    file: &mut File,
    frame: &[u8; ANCHOR_FRAME_BYTES],
) -> Result<(), AgentdPlasticityAnchorStoreErrorV1> {
    file.seek(SeekFrom::End(0))?;
    file.write_all(frame)?;
    file.sync_all()?;
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
