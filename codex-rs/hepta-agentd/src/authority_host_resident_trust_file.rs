//! Root-owned learning trust, read separately from deployment and role packets.
//! This file carries already enrolled public credentials, never signing keys.

use std::io;
use std::path::Path;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::authority_host_config::read_root_json;

const PURPOSE: &str = "hepta.host-resident-learning.trusted-evidence.v3";

#[path = "authority_host_task_prefreeze_trust.rs"]
mod original_source;
pub(super) use original_source::{OriginalDistributionPin, OriginalSourceTrust};

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TrustFile {
    schema_version: u32,
    purpose: String,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    signers: Vec<Signer>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Signer {
    principal: Principal,
    controller_id: String,
    verifying_key: [u8; 32],
    roles: Vec<Role>,
    revoked_at: Option<u64>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Principal {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Role {
    Generator,
    Observer,
    Evaluator,
    CreditAllocator,
    UnlearningAuthority,
    Selector,
}

impl From<Role> for LearningEvidenceRoleV1 {
    fn from(value: Role) -> Self {
        match value {
            Role::Generator => Self::Generator,
            Role::Observer => Self::Observer,
            Role::Evaluator => Self::Evaluator,
            Role::CreditAllocator => Self::CreditAllocator,
            Role::UnlearningAuthority => Self::UnlearningAuthority,
            Role::Selector => Self::Selector,
        }
    }
}

/// Root loads this from its independent Root0600 operational trust file. The
/// daemon may reconstruct the same public data only after the private sealed
/// Root enrollment path authenticates its producer and exact recipient.
pub(super) struct OriginalHostTrust {
    pub(super) verifier: LearningEvidenceVerifierV1,
    signers: Vec<TrustedLearningSignerV1>,
    pub(super) encoded: Vec<u8>,
}

impl OriginalHostTrust {
    pub(super) fn read(path: &Path) -> io::Result<Self> {
        let value: TrustFile = read_root_json(path)?;
        Self::from_value(value)
    }

    // Only the private authenticated Root-enrollment receiver calls this.
    pub(super) fn from_root_enrollment(bytes: &[u8]) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND {
            return Err(io::Error::other("original trust exceeds sealed descriptor bound"));
        }
        Self::from_value(serde_json::from_slice(bytes).map_err(io::Error::other)?)
    }

    fn from_value(value: TrustFile) -> io::Result<Self> {
        let encoded = serde_json::to_vec(&value).map_err(io::Error::other)?;
        if value.schema_version != 3
            || value.purpose != PURPOSE
            || value.signers.is_empty()
            || value.signers.len() > 64
        {
            return Err(io::Error::other("original host learning trust profile differs"));
        }
        let signers = value
            .signers
            .into_iter()
            .map(|signer| {
                let principal = signer.principal;
                Ok(TrustedLearningSignerV1 {
                    principal: AuthenticatedPrincipalV1 {
                        principal_id: StableId::new(principal.principal_id)
                            .map_err(io::Error::other)?,
                        credential_chain_digest: digest(&principal.credential_chain_digest)?,
                        signing_key_digest: digest(&principal.signing_key_digest)?,
                        scope_digest: digest(&principal.scope_digest)?,
                        authority_epoch: principal.authority_epoch,
                        authenticated_at: principal.authenticated_at,
                        expires_at: principal.expires_at,
                    },
                    controller_id: StableId::new(signer.controller_id).map_err(io::Error::other)?,
                    verifying_key: signer.verifying_key,
                    roles: signer.roles.into_iter().map(Into::into).collect(),
                    revoked_at: signer.revoked_at,
                })
            })
            .collect::<io::Result<Vec<_>>>()?;
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest(&value.scope_digest)?,
            objective_digest: digest(&value.objective_digest)?,
            authority_epoch: value.authority_epoch,
            signers: signers.clone(),
        })
        .map_err(io::Error::other)?;
        Ok(Self { verifier, signers, encoded })
    }

    pub(super) fn observer(
        &self,
        original_actor: &StableId,
        now: u64,
    ) -> io::Result<TrustedLearningSignerV1> {
        let signer = self
            .signers
            .iter()
            .find(|signer| &signer.principal.principal_id == original_actor)
            .ok_or_else(|| io::Error::other("original Material actor is not enrolled"))?;
        self.verifier
            .require_signer_binding(LearningEvidenceRoleV1::Observer, signer, now)
            .map_err(io::Error::other)?;
        Ok(signer.clone())
    }
}

pub(super) fn digest(value: &str) -> io::Result<Digest32> {
    let digest = value.parse::<Digest32>().map_err(io::Error::other)?;
    if digest.to_string() != value {
        return Err(io::Error::other("noncanonical original digest"));
    }
    Ok(digest)
}
