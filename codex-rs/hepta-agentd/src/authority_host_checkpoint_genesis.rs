//! The original Root installation's retained physical starting point.
//! No Current/token, publisher generation or grant is manufactured here.

use super::*;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::RootStoredObservation;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use serde::Deserialize;
use serde::Serialize;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct GenesisRecord {
    schema_version: u32,
    initial_root: CognitiveCheckpointPeerLifetime,
    initial_cut: CognitiveRecoveryAnchor,
    issuer_id: String,
    verifying_key: [u8; 32],
    policies: Vec<crate::DeploymentGrantPolicy>,
}

/// Private custody of original Root input, not a checkpoint or authority.
/// Every operation still checks actual absence, material and the issuer's
/// canonical state. Serialized fields alone cannot construct this object.
pub(crate) struct RetainedCheckpointGenesis {
    directory: Arc<RootAuthorityDirectory>,
    stored: RootStoredObservation,
    record: GenesisRecord,
}

fn invalid() -> AuthorityTrustError {
    AuthorityTrustError::Invalid
}
fn unavailable(_: impl std::fmt::Display) -> AuthorityTrustError {
    AuthorityTrustError::Unavailable
}
fn identity(owner: &AgentId) -> String {
    format!("checkpoint-genesis-v1.{owner}")
}

impl RetainedCheckpointGenesis {
    pub(crate) fn cut(&self) -> &CognitiveRecoveryAnchor {
        &self.record.initial_cut
    }
    pub(crate) fn initial_root(&self) -> &CognitiveCheckpointPeerLifetime {
        &self.record.initial_root
    }
    pub(crate) fn verifying_key(&self) -> [u8; 32] {
        self.record.verifying_key
    }
    pub(crate) fn issuer_id(&self) -> &str {
        &self.record.issuer_id
    }
    pub(crate) fn initial_policies(&self) -> &[crate::DeploymentGrantPolicy] {
        &self.record.policies
    }
    pub(crate) fn sha256(&self) -> Sha256Digest {
        Sha256Digest::for_bytes(self.stored.payload())
    }

    pub(crate) fn require_material(
        &self,
        material: &VerifiedCognitiveMaterial,
    ) -> Result<(), AuthorityTrustError> {
        if material.anchor() != &self.record.initial_cut {
            return Err(invalid());
        }
        self.stored.verify_durable()?;
        material.verify_unchanged().map_err(unavailable)
    }

    pub(crate) fn with_no_checkpoint<R>(
        &self,
        material: &VerifiedCognitiveMaterial,
        inspect: impl FnOnce() -> R,
    ) -> Result<R, AuthorityTrustError> {
        HostAuthorityFrontierStore::<CognitiveCheckpointHead>::with_absent_initialization(
            self.directory.clone(),
            STORE_OWNER.into(),
            || {
                self.require_material(material)?;
                let result = inspect();
                self.require_material(material)?;
                Ok::<_, AuthorityTrustError>(result)
            },
        )?
    }

    pub(crate) fn require_issuer(
        &self,
        signer: &str,
        key: [u8; 32],
    ) -> Result<(), AuthorityTrustError> {
        if signer != self.record.issuer_id || key != self.record.verifying_key {
            return Err(invalid());
        }
        self.stored.verify_durable()
    }
}

fn validate_record(record: &GenesisRecord, owner: &AgentId) -> Result<(), AuthorityTrustError> {
    let root = &record.initial_root;
    if record.schema_version != 1
        || root.uid != 0
        || root.pid == 0
        || root.pid > i32::MAX as u32
        || root.process_start_ticks == 0
        || root.boot_id.is_empty()
        || record.initial_cut.owner_agent_id != *owner
        || record.issuer_id.is_empty()
        || record.issuer_id.len() > 64
        || record.verifying_key == [0; 32]
        || record.policies.is_empty()
        || record.policies.len() > 16
        || record
            .policies
            .iter()
            .any(|policy| policy.subject_id != owner.as_str())
    {
        return Err(invalid());
    }
    Ok(())
}

impl HostCognitiveCheckpoint {
    /// Explicit original fresh administrator input, captured before any writer
    /// proof and before the Host can alter the live database. A complete private
    /// physical image is mandatory; its hash alone is not accepted.
    pub(crate) fn prepare_original_genesis_for_root(
        directory: Arc<RootAuthorityDirectory>,
        issuer: &crate::DeploymentFinalUseIssuer,
        clock: &HostAuthorityClock,
        material: &VerifiedCognitiveMaterial,
    ) -> Result<RetainedCheckpointGenesis, AuthorityTrustError> {
        let root =
            crate::HostAuthorityService::current_root_lifetime_for_admin().map_err(unavailable)?;
        if clock.refresh_projection()?.projection.boot_id != root.boot_id {
            return Err(invalid());
        }
        material.verify_unchanged().map_err(unavailable)?;
        let owner = &material.anchor().owner_agent_id;
        HostAuthorityFrontierStore::<CognitiveCheckpointHead>::with_absent_initialization(
            directory.clone(),
            STORE_OWNER.into(),
            || {
                issuer
                    .with_original_unused_genesis_for_root(|signer, key, policies| {
                        let record = GenesisRecord {
                            schema_version: 1,
                            initial_root: root.clone(),
                            initial_cut: material.anchor().clone(),
                            issuer_id: signer.to_owned(),
                            verifying_key: key,
                            policies: policies.to_vec(),
                        };
                        validate_record(&record, owner).map_err(std::io::Error::other)?;
                        material.verify_unchanged().map_err(std::io::Error::other)?;
                        let stored = directory
                            .save_observation(
                                &identity(owner),
                                &serde_json::to_vec(&record).map_err(std::io::Error::other)?,
                            )
                            .map_err(std::io::Error::other)?;
                        let result = RetainedCheckpointGenesis {
                            directory: directory.clone(),
                            stored,
                            record,
                        };
                        result
                            .require_material(material)
                            .map_err(std::io::Error::other)?;
                        if crate::HostAuthorityService::current_root_lifetime_for_admin()? != root {
                            return Err(std::io::Error::other(
                                "actual Root changed during genesis capture",
                            ));
                        }
                        Ok(result)
                    })
                    .map_err(unavailable)
            },
        )?
    }

    /// Open the exact existing initial input. This does not assert an unused
    /// issuer, retire a publisher, or authorize a new namespace. Callers must
    /// independently verify the returned cut's retained physical image.
    pub(crate) fn retained_original_genesis_for_root(
        directory: Arc<RootAuthorityDirectory>,
        owner: &AgentId,
        clock: &HostAuthorityClock,
    ) -> Result<RetainedCheckpointGenesis, AuthorityTrustError> {
        let root =
            crate::HostAuthorityService::current_root_lifetime_for_admin().map_err(unavailable)?;
        if clock.refresh_projection()?.projection.boot_id != root.boot_id {
            return Err(invalid());
        }
        let stored = directory.open_observation(&identity(owner))?;
        let record: GenesisRecord =
            serde_json::from_slice(stored.payload()).map_err(|_| invalid())?;
        validate_record(&record, owner)?;
        stored.verify_durable()?;
        Ok(RetainedCheckpointGenesis {
            directory,
            stored,
            record,
        })
    }
}
