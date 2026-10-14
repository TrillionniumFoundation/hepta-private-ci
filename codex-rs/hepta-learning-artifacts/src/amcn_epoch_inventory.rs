//! Research-only projection of the ORIGINAL authenticated current Artifact
//! Registry view into a bounded Cell epoch membership inventory.
//!
//! This module neither signs an Epoch nor issues selected-model, source-use,
//! activation or FinalUse authority. The input VerifiedCurrentRegistryViewV1 is
//! opaque to external callers and may only be obtained after the existing
//! ArtifactOwnerVerifierV1 checks a signed CURRENT head and exact snapshot.
//! Currentness must still be re-established under an owner-held effect fence;
//! a once-verified view is NOT a durable lease across concurrent mutations.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::{AuthorityPosture, Digest32, StableId};

use crate::{
    ArtifactEvent, ArtifactKind, ArtifactManifest, VerifiedCurrentRegistryViewV1,
};

const ENROLLED_DOMAIN: &[u8] = b"hepta.amcn.epoch.enrolled-manifests.v1";
const QUARANTINED_DOMAIN: &[u8] = b"hepta.amcn.epoch.quarantined-manifests.v1";
const MEMBER_DOMAIN: &[u8] = b"hepta.amcn.epoch.artifact-identity.v1";

pub const AMCN_OWNER_EPOCH_MAX_MANIFESTS: usize = 65_536;
pub const AMCN_OWNER_EPOCH_MAX_QUARANTINED: usize = 16_384;
pub const AMCN_OWNER_EPOCH_PRODUCTION_ACCEPTED: bool = false;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AmcnOwnerEpochError {
    MissingCurrentWitness,
    CurrentHeadMismatch,
    RegistryContentMismatch,
    EmptyEligibleInventory,
    RegistryOverBudget,
    InvalidManifest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AmcnVerifiedRegistryEpochPopulationV1 {
    current_registry_head_digest: Digest32,
    current_registry_binding_digest: Digest32,
    current_witness_digest: Digest32,
    current_trust_digest: Digest32,
    /// Exact IDs and manifest commitments; ONLY Model/Parameters are included.
    enrolled_model_and_head_manifests: Vec<(StableId, Digest32)>,
    /// Revoked, quarantined OR descendants with unavailable ancestors.
    quarantined_model_and_head_manifest_digests: Vec<Digest32>,
    enrolled_manifest_set_digest: Digest32,
    quarantined_manifest_set_digest: Digest32,
    /// A verified current view is NOT a selection grant.
    authority: AuthorityPosture,
}

impl AmcnVerifiedRegistryEpochPopulationV1 {
    pub const fn current_registry_head_digest(&self) -> Digest32 {
        self.current_registry_head_digest
    }
    pub const fn current_witness_digest(&self) -> Digest32 {
        self.current_witness_digest
    }
    pub const fn current_trust_digest(&self) -> Digest32 {
        self.current_trust_digest
    }
    pub const fn enrolled_manifest_set_digest(&self) -> Digest32 {
        self.enrolled_manifest_set_digest
    }
    pub const fn quarantined_manifest_set_digest(&self) -> Digest32 {
        self.quarantined_manifest_set_digest
    }
    pub fn enrolled_model_and_head_manifests(&self) -> &[(StableId, Digest32)] {
        &self.enrolled_model_and_head_manifests
    }
    pub fn quarantined_model_and_head_manifest_digests(&self) -> &[Digest32] {
        &self.quarantined_model_and_head_manifest_digests
    }
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
    pub const fn production_accepted(&self) -> bool {
        false
    }
}

/// Stable key binding an Artifact identity to the exact selected model tuple
/// fields admitted by the ORIGINAL registry. Never use only a content hash:
/// distinct Cells could share binary bytes while having different lineage.
fn member_digest(manifest: &ArtifactManifest) -> Digest32 {
    let id = manifest.artifact_id.as_str().as_bytes();
    let mut bytes = Vec::with_capacity(MEMBER_DOMAIN.len() + id.len() + 140);
    bytes.extend_from_slice(MEMBER_DOMAIN);
    bytes.extend_from_slice(&(id.len() as u32).to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(&manifest.generation.get().to_be_bytes());
    bytes.push(manifest.kind.tag());
    for digest in [
        manifest.content_digest,
        manifest.objective_digest,
        manifest.support_digest,
        manifest.compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    if let Some(parent) = &manifest.predecessor_id {
        let parent = parent.as_str().as_bytes();
        bytes.extend_from_slice(&(parent.len() as u32).to_be_bytes());
        bytes.extend_from_slice(parent);
    } else {
        bytes.extend_from_slice(&0_u32.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

/// Canonical exact domain/count/32-byte sorted set hashing. Must stay bytewise
/// identical to Neuron amcn_shadow_epoch.rs enrolment/withdrawal check.
fn digest_manifest_set(domain: &[u8], values: &BTreeSet<Digest32>) -> Digest32 {
    let mut bytes = Vec::with_capacity(domain.len() + 8 + 32 * values.len());
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(value.as_array());
    }
    Digest32::of_bytes(&bytes)
}

/// Use the existing opaque verified Registry view, not caller-written JSON.
///
/// The expected pins MUST come from an independent current signed head held
/// by the host. This only projects an already-authenticated snapshot; it is
/// not proof that source training datasets are admitted or selector approved.
pub fn project_verified_amcn_artifact_epoch_v1(
    view: &VerifiedCurrentRegistryViewV1,
    expected_registry_head: Digest32,
    expected_witness: Digest32,
    expected_trust: Digest32,
) -> Result<AmcnVerifiedRegistryEpochPopulationV1, AmcnOwnerEpochError> {
    if expected_registry_head.is_zero()
        || expected_witness.is_zero()
        || expected_trust.is_zero()
    {
        return Err(AmcnOwnerEpochError::MissingCurrentWitness);
    }
    let receipt = view.receipt();
    if receipt.head_digest != expected_registry_head
        || view.witness_digest() != expected_witness
        || view.trust_digest() != expected_trust
    {
        return Err(AmcnOwnerEpochError::CurrentHeadMismatch);
    }
    let registry = view.registry();
    let records = registry.records();
    if receipt.records != records.len()
        || records.last().map(|r| r.chain_digest) != Some(receipt.head_digest)
    {
        return Err(AmcnOwnerEpochError::RegistryContentMismatch);
    }
    let mut models = BTreeMap::<StableId, Digest32>::new();
    for record in records {
        if let ArtifactEvent::Register { manifest, .. } = &record.event {
            if !matches!(manifest.kind, ArtifactKind::Model | ArtifactKind::Parameters) {
                continue;
            }
            if models.len() >= AMCN_OWNER_EPOCH_MAX_MANIFESTS {
                return Err(AmcnOwnerEpochError::RegistryOverBudget);
            }
            let digest = member_digest(manifest);
            if digest.is_zero()
                || models.insert(manifest.artifact_id.clone(), digest).is_some()
            {
                return Err(AmcnOwnerEpochError::InvalidManifest);
            }
        }
    }
    if models.is_empty() {
        return Err(AmcnOwnerEpochError::EmptyEligibleInventory);
    }
    let enrolled: BTreeSet<_> = models.values().copied().collect();
    if enrolled.len() != models.len() {
        return Err(AmcnOwnerEpochError::InvalidManifest);
    }
    let mut quarantined = BTreeSet::new();
    for (id, digest) in &models {
        if !registry.is_eligible(id) {
            if quarantined.len() >= AMCN_OWNER_EPOCH_MAX_QUARANTINED {
                return Err(AmcnOwnerEpochError::RegistryOverBudget);
            }
            quarantined.insert(*digest);
        }
    }
    Ok(AmcnVerifiedRegistryEpochPopulationV1 {
        current_registry_head_digest: receipt.head_digest,
        current_registry_binding_digest: receipt.binding,
        current_witness_digest: view.witness_digest(),
        current_trust_digest: view.trust_digest(),
        enrolled_model_and_head_manifests: models.into_iter().collect(),
        quarantined_model_and_head_manifest_digests: quarantined.iter().copied().collect(),
        enrolled_manifest_set_digest: digest_manifest_set(ENROLLED_DOMAIN, &enrolled),
        quarantined_manifest_set_digest: digest_manifest_set(QUARANTINED_DOMAIN, &quarantined),
        authority: AuthorityPosture::DENY_ALL,
    })
}
