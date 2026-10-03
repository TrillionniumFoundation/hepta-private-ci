//! Strict observation identities for the additive Agentd/inference bridge.
//!
//! These serializable values are not effect authority or live-use tokens. Each
//! owner must independently authorize and durably validate a received mutation.
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;

use crate::AgentId;
use crate::Sha256Digest;

pub const RUN_BRIDGE_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RunBridgeError(pub &'static str);

impl fmt::Display for RunBridgeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0)
    }
}
impl std::error::Error for RunBridgeError {}

/// Complete immutable owner and execution identity, before the nonce commitment.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunBridgeIdentityV1 {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub run_id: String,
    pub request_id: String,
    pub owner_generation: u64,
    pub owner_dispatch_revision: u64,
    pub source_dispatch_revision: u64,
    pub fence_sha256: Sha256Digest,
    pub context_sha256: Sha256Digest,
    pub envelope_sha256: Sha256Digest,
    pub execution_binding_sha256: Sha256Digest,
    pub dispatch_sha256: Sha256Digest,
}

impl RunBridgeIdentityV1 {
    pub fn validate(&self) -> Result<(), RunBridgeError> {
        if self.schema_version != RUN_BRIDGE_SCHEMA_VERSION
            || !identifier(&self.run_id)
            || !identifier(&self.request_id)
            || self.owner_generation == 0
            || self.owner_dispatch_revision == 0
            || self.source_dispatch_revision == 0
        {
            return Err(RunBridgeError("invalid run bridge identity"));
        }
        for value in [
            &self.fence_sha256,
            &self.context_sha256,
            &self.envelope_sha256,
            &self.execution_binding_sha256,
            &self.dispatch_sha256,
        ] {
            digest(value)?;
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, RunBridgeError> {
        self.validate()?;
        hash(b"hepta.run-bridge.identity.v1\0", self)
    }
}

/// A nonce commitment is observation correlation, never a replacement for the
/// source owner's non-cloneable, incarnation-bound pre-effect token.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunBridgeBindingV1 {
    pub identity: RunBridgeIdentityV1,
    pub abort_commitment_sha256: Sha256Digest,
}

impl RunBridgeBindingV1 {
    pub fn validate(&self) -> Result<(), RunBridgeError> {
        self.identity.validate()?;
        digest(&self.abort_commitment_sha256)
    }

    pub fn digest(&self) -> Result<Sha256Digest, RunBridgeError> {
        self.validate()?;
        hash(b"hepta.run-bridge.binding.v1\0", self)
    }

    pub fn abort_commitment(
        identity: &RunBridgeIdentityV1,
        nonce: &[u8; 32],
    ) -> Result<Sha256Digest, RunBridgeError> {
        if *nonce == [0; 32] {
            return Err(RunBridgeError("invalid run bridge abort nonce"));
        }
        hash(
            b"hepta.run-bridge.abort-commitment.v1\0",
            &(identity.digest()?, nonce),
        )
    }
}

/// Persisted only after the actual source owner consumes its live pre-effect
/// token. Replaying this proof cannot create a fresh physical-send permission.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunBridgeAbortProofV1 {
    pub schema_version: u32,
    pub binding_sha256: Sha256Digest,
    pub nonce: [u8; 32],
    pub reason: String,
}

impl RunBridgeAbortProofV1 {
    pub fn validate(&self, binding: &RunBridgeBindingV1) -> Result<(), RunBridgeError> {
        if self.schema_version != RUN_BRIDGE_SCHEMA_VERSION
            || self.binding_sha256 != binding.digest()?
            || self.reason.is_empty()
            || self.reason.len() > 512
            || self.reason.chars().any(char::is_control)
            || RunBridgeBindingV1::abort_commitment(&binding.identity, &self.nonce)?
                != binding.abort_commitment_sha256
        {
            return Err(RunBridgeError("run bridge abort proof mismatch"));
        }
        Ok(())
    }

    pub fn digest(&self, binding: &RunBridgeBindingV1) -> Result<Sha256Digest, RunBridgeError> {
        self.validate(binding)?;
        hash(b"hepta.run-bridge.abort-proof.v1\0", self)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunBridgeProviderOutcomeV1 {
    ProvenNotSent,
    Completed,
    Failed,
    Interrupted,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunBridgeLogicalOutcomeV1 {
    Succeeded,
    Failed,
    Cancelled,
}

/// Immutable primary publication derived after authoritative source settlement.
/// Actual provider outcome is distinct from logical qualification.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunBridgePrimaryV1 {
    pub schema_version: u32,
    pub binding_sha256: Sha256Digest,
    pub source_revision: u64,
    pub provider_outcome: RunBridgeProviderOutcomeV1,
    pub logical_outcome: RunBridgeLogicalOutcomeV1,
    pub qualification_sha256: Sha256Digest,
    pub terminal_correlation_sha256: Option<Sha256Digest>,
    pub abort_proof_sha256: Option<Sha256Digest>,
}

impl RunBridgePrimaryV1 {
    pub fn validate(&self, binding: &RunBridgeBindingV1) -> Result<(), RunBridgeError> {
        use RunBridgeLogicalOutcomeV1 as Logical;
        use RunBridgeProviderOutcomeV1 as Provider;
        if self.schema_version != RUN_BRIDGE_SCHEMA_VERSION
            || self.binding_sha256 != binding.digest()?
            || self.source_revision <= binding.identity.source_dispatch_revision
        {
            return Err(RunBridgeError("invalid run bridge primary identity"));
        }
        digest(&self.qualification_sha256)?;
        let admissible = match self.provider_outcome {
            Provider::ProvenNotSent => {
                self.logical_outcome == Logical::Cancelled
                    && self.terminal_correlation_sha256.is_none()
                    && self.abort_proof_sha256.is_some()
            }
            Provider::Completed => {
                matches!(self.logical_outcome, Logical::Succeeded | Logical::Failed)
                    && self.terminal_correlation_sha256.is_some()
                    && self.abort_proof_sha256.is_none()
            }
            Provider::Failed => {
                self.logical_outcome == Logical::Failed
                    && self.terminal_correlation_sha256.is_some()
                    && self.abort_proof_sha256.is_none()
            }
            Provider::Interrupted => {
                matches!(self.logical_outcome, Logical::Cancelled | Logical::Failed)
                    && self.terminal_correlation_sha256.is_some()
                    && self.abort_proof_sha256.is_none()
            }
        };
        if !admissible {
            return Err(RunBridgeError("run bridge outcome/evidence mismatch"));
        }
        for value in [
            self.terminal_correlation_sha256.as_ref(),
            self.abort_proof_sha256.as_ref(),
        ]
        .into_iter()
        .flatten()
        {
            digest(value)?;
        }
        Ok(())
    }

    pub fn digest(&self, binding: &RunBridgeBindingV1) -> Result<Sha256Digest, RunBridgeError> {
        self.validate(binding)?;
        hash(b"hepta.run-bridge.primary.v1\0", self)
    }
}

/// One sticky denial notice; it cannot rewrite the acknowledged primary or
/// claim a different provider effect. Further corrections remain source facts.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunBridgeQualificationConflictV1 {
    pub schema_version: u32,
    pub binding_sha256: Sha256Digest,
    pub primary_sha256: Sha256Digest,
    pub source_revision: u64,
    pub qualification_sha256: Sha256Digest,
}

impl RunBridgeQualificationConflictV1 {
    pub fn validate(
        &self,
        binding: &RunBridgeBindingV1,
        primary: &RunBridgePrimaryV1,
    ) -> Result<(), RunBridgeError> {
        if self.schema_version != RUN_BRIDGE_SCHEMA_VERSION
            || self.binding_sha256 != binding.digest()?
            || self.primary_sha256 != primary.digest(binding)?
            || self.source_revision <= primary.source_revision
            || self.qualification_sha256 == primary.qualification_sha256
        {
            return Err(RunBridgeError("invalid run bridge qualification conflict"));
        }
        digest(&self.qualification_sha256)
    }

    pub fn digest(
        &self,
        binding: &RunBridgeBindingV1,
        primary: &RunBridgePrimaryV1,
    ) -> Result<Sha256Digest, RunBridgeError> {
        self.validate(binding, primary)?;
        hash(b"hepta.run-bridge.qualification-conflict.v1\0", self)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunBridgePublicationKindV1 {
    Primary,
    QualificationConflict,
}

/// Stable semantic acknowledgement. Delivery-specific idempotence flags do not
/// enter this value, so replay can reproduce the original acknowledgement.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunBridgeAcknowledgementV1 {
    pub schema_version: u32,
    pub binding_sha256: Sha256Digest,
    pub publication_sha256: Sha256Digest,
    pub kind: RunBridgePublicationKindV1,
    pub owner_revision: u64,
}

impl RunBridgeAcknowledgementV1 {
    pub fn validate(
        &self,
        binding: &RunBridgeBindingV1,
        publication: &Sha256Digest,
        kind: RunBridgePublicationKindV1,
    ) -> Result<(), RunBridgeError> {
        digest(publication)?;
        if self.schema_version != RUN_BRIDGE_SCHEMA_VERSION
            || self.binding_sha256 != binding.digest()?
            || self.publication_sha256 != *publication
            || self.kind != kind
            || self.owner_revision <= binding.identity.owner_dispatch_revision
        {
            return Err(RunBridgeError("run bridge acknowledgement mismatch"));
        }
        Ok(())
    }
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}
fn digest(value: &Sha256Digest) -> Result<(), RunBridgeError> {
    if Sha256Digest::parse(value.as_str()).is_err()
        || value.as_str().bytes().all(|byte| byte == b'0')
    {
        Err(RunBridgeError("invalid run bridge digest"))
    } else {
        Ok(())
    }
}
fn hash<T: Serialize>(domain: &[u8], value: &T) -> Result<Sha256Digest, RunBridgeError> {
    let bytes = serde_json::to_vec(value).map_err(|_| RunBridgeError("run bridge encoding"))?;
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update(bytes);
    Ok(Sha256Digest::from_sha256_output(hash.finalize()))
}

#[cfg(test)]
#[path = "run_bridge_tests.rs"]
mod tests;
