use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_evidence::EvidenceRecoveryFrontierV2;
use codex_hepta_evidence::evidence_recovery_frontier_v2_signing_bytes;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AgentdError;
use crate::authbus_trust::hex_bytes;

const SIGNER_TRUST_SCHEMA_VERSION: u32 = 2;
const MAX_FRONTIER_SIGNERS: usize = 32;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceFrontierSignerV2 {
    principal_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct EvidenceFrontierSignerTrustV2 {
    schema_version: u32,
    policy_generation: u64,
    threshold: usize,
    signers: Vec<EvidenceFrontierSignerV2>,
}

impl EvidenceFrontierSignerTrustV2 {
    pub(crate) fn parse(bytes: &[u8]) -> Result<Self, AgentdError> {
        let trust: Self = serde_json::from_slice(bytes)?;
        trust.validate()?;
        Ok(trust)
    }

    fn validate(&self) -> Result<(), AgentdError> {
        if self.schema_version != SIGNER_TRUST_SCHEMA_VERSION
            || self.policy_generation == 0
            || self.threshold == 0
            || self.signers.is_empty()
            || self.signers.len() > MAX_FRONTIER_SIGNERS
        {
            return Err(recovery_required(
                "frontier signer policy schema, generation, threshold or size is invalid",
            ));
        }
        let mut identities = BTreeSet::new();
        let mut active_principals = BTreeSet::new();
        for signer in &self.signers {
            StableId::new(signer.principal_id.clone()).map_err(|error| {
                recovery_required(&format!("invalid frontier signer principal: {error}"))
            })?;
            Generation::new(signer.key_epoch).map_err(|error| {
                recovery_required(&format!("invalid frontier signer key epoch: {error}"))
            })?;
            if !identities.insert((signer.principal_id.clone(), signer.key_epoch)) {
                return Err(recovery_required(
                    "frontier signer policy contains a duplicate principal/key epoch",
                ));
            }
            if signer.public_key_hex.len() != 64
                || !signer
                    .public_key_hex
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            {
                return Err(recovery_required(
                    "frontier signer policy contains a non-canonical Ed25519 public key",
                ));
            }
            VerifyingKey::from_bytes(&hex_bytes(&signer.public_key_hex)?)
                .map_err(|_| recovery_required("invalid frontier signer Ed25519 public key"))?;
            if !signer.revoked {
                active_principals.insert(signer.principal_id.clone());
            }
        }
        if self.threshold > active_principals.len() {
            return Err(recovery_required(
                "frontier signer threshold exceeds active distinct principals",
            ));
        }
        Ok(())
    }

    pub(crate) fn verify(
        &self,
        frontier: &EvidenceRecoveryFrontierV2,
    ) -> Result<(), AgentdError> {
        self.validate()?;
        if frontier.signer_policy_generation != self.policy_generation {
            return Err(recovery_required(
                "frontier signer policy generation does not match the trusted registry",
            ));
        }
        let registry = self
            .signers
            .iter()
            .map(|signer| {
                (
                    (signer.principal_id.as_str(), signer.key_epoch),
                    signer,
                )
            })
            .collect::<BTreeMap<_, _>>();
        let signing_bytes = evidence_recovery_frontier_v2_signing_bytes(frontier)
            .map_err(|error| recovery_required(&error.to_string()))?;
        let mut verified_principals = BTreeSet::new();
        for binding in &frontier.signatures {
            let signer = registry
                .get(&(
                    binding.signer_principal_id.as_str(),
                    binding.signer_key_epoch,
                ))
                .ok_or_else(|| {
                    recovery_required(
                        "frontier contains a signature outside the trusted signer registry",
                    )
                })?;
            if signer.revoked {
                return Err(recovery_required(
                    "frontier contains a signature from a revoked signer epoch",
                ));
            }
            let verifying_key = VerifyingKey::from_bytes(&hex_bytes(&signer.public_key_hex)?)
                .map_err(|_| recovery_required("invalid frontier signer Ed25519 public key"))?;
            let signature = Signature::from_bytes(&hex_bytes(&binding.signature_hex)?);
            verifying_key
                .verify_strict(&signing_bytes, &signature)
                .map_err(|_| recovery_required("frontier threshold signature verification failed"))?;
            verified_principals.insert(signer.principal_id.as_str());
        }
        if verified_principals.len() < self.threshold {
            return Err(recovery_required(
                "frontier does not satisfy the distinct-principal signature threshold",
            ));
        }
        Ok(())
    }
}

fn recovery_required(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence recovery_required: {message}"))
}

#[cfg(test)]
#[path = "evidence_frontier_signers_tests.rs"]
mod tests;
