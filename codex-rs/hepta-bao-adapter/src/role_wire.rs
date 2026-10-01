//! Bounded role RPCs used by issuance, external trust and original delivery.

use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::ConsumerPortError;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TimeAttestation {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub wall_time_ms: u64,
    pub source_revision: u64,
    pub source_digest: [u8; 32],
    pub signature: Vec<u8>,
}

impl TimeAttestation {
    pub fn from_signed(attestation: SignedTrustedTimeAttestation) -> Self {
        let claims = attestation.claims;
        Self {
            issuer_id: claims.issuer_id.as_str().to_owned(),
            key_epoch: claims.key_epoch.get(),
            wall_time_ms: claims.wall_time_ms,
            source_revision: claims.source_revision,
            source_digest: claims.source_digest.into_array(),
            signature: attestation.signature.to_vec(),
        }
    }

    pub fn verify(
        self,
        issuer_id: &str,
        epoch: u64,
        key: &[u8; 32],
    ) -> Result<SignedTrustedTimeAttestation, ConsumerPortError> {
        if self.issuer_id != issuer_id
            || self.key_epoch != epoch
            || self.wall_time_ms == 0
            || self.source_revision == 0
            || self.source_digest == [0; 32]
        {
            return Err(ConsumerPortError::Rejected);
        }
        let claims = TrustedTimeAttestationClaims {
            issuer_id: StableId::new(self.issuer_id).map_err(invalid)?,
            key_epoch: Generation::new(self.key_epoch).map_err(invalid)?,
            wall_time_ms: self.wall_time_ms,
            source_revision: self.source_revision,
            source_digest: Digest32::from_array(self.source_digest),
        };
        let signature: [u8; 64] = self.signature.try_into().map_err(invalid)?;
        let key = VerifyingKey::from_bytes(key).map_err(invalid)?;
        if key.is_weak() {
            return Err(ConsumerPortError::Invalid);
        }
        key.verify_strict(&claims.signing_bytes(), &Signature::from_bytes(&signature))
            .map_err(invalid)?;
        Ok(SignedTrustedTimeAttestation { claims, signature })
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum AuthorityRequest {
    Time,
    Frontier {
        owner_id: String,
    },
    CompareAndSet {
        owner_id: String,
        expected: FinalUseFrontier,
        next: FinalUseFrontier,
    },
    ApplyRevocations {
        update: SignedFinalUseRevocationUpdate,
    },
    Issue {
        original_operation_id: String,
    },
    BeginOriginal {
        original_operation_id: String,
        approval: SignedFinalUseApproval,
    },
    OriginalStatus {
        original_operation_id: String,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum AuthorityResponse {
    Time {
        attestation: TimeAttestation,
    },
    Frontier {
        frontier: FinalUseFrontier,
        revocations: FinalUseRevocations,
    },
    Grant {
        grant: SignedFinalUseGrant,
    },
    OriginalAdmitted {
        grant_sha256: [u8; 32],
        approval_sha256: [u8; 32],
    },
    OriginalStarted {
        grant_sha256: [u8; 32],
        approval_sha256: [u8; 32],
    },
    Unknown,
    Rejected,
    Conflict,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum OperatorRequest {
    Approve { grant: Box<SignedFinalUseGrant> },
    Revocations,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum OperatorResponse {
    Approval {
        approval: SignedFinalUseApproval,
    },
    Revocations {
        update: SignedFinalUseRevocationUpdate,
    },
    Unknown,
    Rejected,
    Conflict,
}

fn invalid(_error: impl std::fmt::Debug) -> ConsumerPortError {
    ConsumerPortError::Invalid
}
