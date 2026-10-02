//! Authenticated CURRENT checks for a frozen plasticity generation.
//!
//! The deployment host supplies the independent CURRENT distribution path and
//! public trust. This adapter reads the existing artifact-owner signed format;
//! it owns no signing key, writer lease or registry mutation capability.

use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::read_signed_current_artifact_head_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::AgentdError;

/// Independent artifact-owner CURRENT provider, checked before each proposal.
/// Implementations must return only an owner-authenticated view and obtain the
/// newest authorized head from their deployment's trusted distribution source.
/// An unavailable source is an error, never permission to reuse an older view.
pub trait PlasticityCurrentArtifactsV1: Send + Sync {
    fn current(&self, now: u64) -> Result<VerifiedCurrentRegistryViewV1, AgentdError>;
}

/// Read-only adapter for a host-maintained CURRENT file in the native signed
/// artifact-owner format and an independently pinned immutable snapshot.
pub struct PlasticityCurrentArtifactFilesV1 {
    snapshot_path: PathBuf,
    current_head_path: PathBuf,
    frozen_receipt: RegistrySnapshotReceipt,
    trust: ArtifactOwnerTrustV1,
    verifier: ArtifactOwnerVerifierV1,
}

impl PlasticityCurrentArtifactFilesV1 {
    pub fn new(
        snapshot_path: PathBuf,
        current_head_path: PathBuf,
        frozen_receipt: RegistrySnapshotReceipt,
        trust: ArtifactOwnerTrustV1,
    ) -> Result<Self, AgentdError> {
        if snapshot_path == current_head_path
            || !snapshot_path.is_absolute()
            || !current_head_path.is_absolute()
            || frozen_receipt.binding.is_zero()
            || frozen_receipt.head_digest.is_zero()
            || frozen_receipt.file_digest.is_zero()
            || frozen_receipt.records == 0
        {
            return Err(AgentdError::Invalid(
                "plasticity CURRENT requires distinct absolute paths and an independent frozen receipt"
                    .to_string(),
            ));
        }
        let verifier = ArtifactOwnerVerifierV1::new(trust.clone()).map_err(|error| {
            AgentdError::Invalid(format!("invalid plasticity artifact-owner trust: {error}"))
        })?;
        Ok(Self {
            snapshot_path,
            current_head_path,
            frozen_receipt,
            trust,
            verifier,
        })
    }
}

impl PlasticityCurrentArtifactsV1 for PlasticityCurrentArtifactFilesV1 {
    fn current(&self, now: u64) -> Result<VerifiedCurrentRegistryViewV1, AgentdError> {
        let signed =
            read_signed_current_artifact_head_v1(open_regular_read_only(&self.current_head_path)?)
                .map_err(|error| {
                    AgentdError::Invalid(format!("plasticity CURRENT record rejected: {error}"))
                })?;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.trust.registry_id.clone(),
            minimum_generation: self.trust.minimum_registry_generation,
            expected_predecessor_head_digest: signed.witness.predecessor_head_digest,
            minimum_authority_epoch: self.trust.minimum_authority_epoch,
            now,
        };
        let current = self
            .verifier
            .verify_current_head(&signed, &requirement)
            .map_err(|error| {
                AgentdError::Invalid(format!("plasticity CURRENT authentication failed: {error}"))
            })?;
        // Authenticate the independently discovered head before inspecting the
        // old snapshot. A changed head requires a new generation, even when it
        // is a valid extension rather than a revocation.
        if current.signed.binding != self.frozen_receipt.binding
            || current.signed.witness.head_digest != self.frozen_receipt.head_digest
        {
            return Err(AgentdError::GenerationFenced(
                "plasticity artifact CURRENT changed; refresh and rebootstrap the frozen generation"
                    .to_string(),
            ));
        }
        self.verifier
            .verify_current_registry_view(
                open_regular_read_only(&self.snapshot_path)?,
                self.frozen_receipt,
                &signed,
                &requirement,
            )
            .map_err(|error| {
                AgentdError::Invalid(format!("plasticity CURRENT snapshot rejected: {error}"))
            })
    }
}

fn open_regular_read_only(path: &Path) -> Result<File, AgentdError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Invalid(
            "plasticity artifact CURRENT paths must be regular non-symlink files".to_string(),
        ));
    }
    Ok(File::open(path)?)
}

pub(crate) struct FrozenPlasticityArtifactsV1 {
    provider: Arc<dyn PlasticityCurrentArtifactsV1>,
    receipt: RegistrySnapshotReceipt,
    accepted_trust: Option<Digest32>,
    eligible_artifacts: Vec<StableId>,
    requires_full_admission: bool,
}

impl FrozenPlasticityArtifactsV1 {
    pub(crate) fn new(
        provider: Arc<dyn PlasticityCurrentArtifactsV1>,
        receipt: RegistrySnapshotReceipt,
        artifacts: &ArtifactRegistry,
    ) -> Result<Self, AgentdError> {
        if receipt.binding.is_zero()
            || receipt.file_digest.is_zero()
            || receipt.head_digest.is_zero()
            || receipt.records != artifacts.records().len()
            || receipt.head_digest != artifacts.snapshot().head_digest
        {
            return Err(AgentdError::Invalid(
                "plasticity CURRENT receipt does not bind the frozen artifact registry".to_string(),
            ));
        }
        Ok(Self {
            provider,
            receipt,
            accepted_trust: None,
            eligible_artifacts: artifacts
                .records()
                .iter()
                .filter_map(|record| match &record.event {
                    codex_hepta_learning_artifacts::ArtifactEvent::Register {
                        manifest, ..
                    } if artifacts.is_eligible(&manifest.artifact_id) => {
                        Some(manifest.artifact_id.clone())
                    }
                    _ => None,
                })
                .collect(),
            requires_full_admission: false,
        })
    }

    pub(crate) fn verify(&mut self, now: u64) -> Result<(), AgentdError> {
        let current = self.provider.current(now)?;
        if current.receipt() != self.receipt {
            return Err(AgentdError::GenerationFenced(
                "plasticity artifact CURRENT differs from the frozen snapshot; refresh and rebootstrap"
                    .to_string(),
            ));
        }
        if self
            .accepted_trust
            .is_some_and(|trust| trust != current.trust_digest())
        {
            return Err(AgentdError::GenerationFenced(
                "plasticity artifact-owner trust changed; refresh and rebootstrap required"
                    .to_string(),
            ));
        }
        // Full provenance is time-dependent even when the signed registry
        // receipt stays unchanged. Never downgrade a previously strict view.
        let full = current.verified_at().is_some();
        let admission_valid = match current.verified_at() {
            Some(verified_at) => {
                verified_at == now
                    && self.eligible_artifacts.iter().all(|artifact| {
                        current.full_admission(artifact).is_some() && current.is_eligible(artifact)
                    })
            }
            None => !self.requires_full_admission,
        };
        if !admission_valid {
            return Err(AgentdError::GenerationFenced(
                "plasticity full artifact provenance expired, changed or became unavailable; rebootstrap required".to_string(),
            ));
        }
        self.requires_full_admission |= full;
        self.accepted_trust = Some(current.trust_digest());
        Ok(())
    }
}

/// Additive host-selected descriptor configuration. It carries only public
/// artifact-owner trust and a trusted distribution path, never signing material.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CurrentArtifactsDescriptorV1 {
    pub(crate) current_head_path: PathBuf,
    registry_id: String,
    withdrawal_scope_digest: String,
    minimum_registry_generation: u64,
    genesis_predecessor_head_digest: String,
    minimum_authority_epoch: u64,
    writer_signers: Vec<CurrentArtifactSignerDescriptorV1>,
    head_signers: Vec<CurrentArtifactSignerDescriptorV1>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CurrentArtifactSignerDescriptorV1 {
    signer_id: String,
    verifying_key_hex: String,
    minimum_authority_epoch: u64,
    maximum_authority_epoch: u64,
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

impl CurrentArtifactsDescriptorV1 {
    pub(crate) fn provider(
        &self,
        snapshot_path: PathBuf,
        frozen_receipt: RegistrySnapshotReceipt,
    ) -> Result<Arc<dyn PlasticityCurrentArtifactsV1>, AgentdError> {
        let parse_signers = |signers: &[CurrentArtifactSignerDescriptorV1]| {
            if signers.is_empty() || signers.len() > 32 {
                return Err(AgentdError::Invalid(
                    "plasticity artifact-owner trust requires 1..32 signers per role".to_string(),
                ));
            }
            signers
                .iter()
                .map(|signer| {
                    Ok(TrustedArtifactSignerV1 {
                        signer_id: StableId::new(signer.signer_id.clone())
                            .map_err(|error| AgentdError::Invalid(error.to_string()))?,
                        verifying_key: signer
                            .verifying_key_hex
                            .parse::<Digest32>()
                            .map_err(|error| AgentdError::Invalid(error.to_string()))?
                            .into_array(),
                        minimum_authority_epoch: signer.minimum_authority_epoch,
                        maximum_authority_epoch: signer.maximum_authority_epoch,
                        valid_from: signer.valid_from,
                        expires_at: signer.expires_at,
                        revoked_at: signer.revoked_at,
                    })
                })
                .collect::<Result<Vec<_>, AgentdError>>()
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: StableId::new(self.registry_id.clone())
                .map_err(|error| AgentdError::Invalid(error.to_string()))?,
            withdrawal_scope_digest: self
                .withdrawal_scope_digest
                .parse::<Digest32>()
                .map_err(|error| AgentdError::Invalid(error.to_string()))?,
            minimum_registry_generation: Generation::new(self.minimum_registry_generation)
                .map_err(|error| AgentdError::Invalid(error.to_string()))?,
            genesis_predecessor_head_digest: self
                .genesis_predecessor_head_digest
                .parse::<Digest32>()
                .map_err(|error| AgentdError::Invalid(error.to_string()))?,
            minimum_authority_epoch: self.minimum_authority_epoch,
            writer_signers: parse_signers(&self.writer_signers)?,
            head_signers: parse_signers(&self.head_signers)?,
        };
        Ok(Arc::new(PlasticityCurrentArtifactFilesV1::new(
            snapshot_path,
            self.current_head_path.clone(),
            frozen_receipt,
            trust,
        )?))
    }
}

#[cfg(test)]
#[path = "plasticity_artifact_current_tests.rs"]
mod tests;
