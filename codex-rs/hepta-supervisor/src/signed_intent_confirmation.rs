//! Retained evidence for explicitly confirming an intent publication. These
//! files contain public signed material, never a reusable execution capability.
//! The owner separately requires a fresh policy admission, clock and exact
//! external predecessor before it may publish the corresponding anchor.

use std::path::Path;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::signed_authority::H7H89ProductionGrantVerifier;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::ProductionRecoveryDecision;
use crate::signed_authority::ProductionRecoveryOutcome;
use crate::signed_intent::SignedIntentError;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;

// Each of the two fixed slots retains the original intent journal byte bound.
// Confirmation does not append to, replace, or truncate the 32 Unknown records.
const MAX_CONFIRMATION_BYTES: u64 = 262_144;
const MAX_POLICY_BYTES: usize = 16_384;
const CURRENT_FILE: &str = "supervisor-signed-intent-confirmation.json";
const PREDECESSOR_FILE: &str = "supervisor-signed-intent-confirmation-predecessor.json";
const DOMAIN: &[u8] = b"hepta-supervisor:intent-publication-confirmation:v1\0";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SignedIntentPublicationConfirmation {
    pub(crate) schema_version: u32,
    pub(crate) intent_sha256: Sha256Digest,
    /// Exact original policy bytes as UTF-8, including any signed whitespace.
    pub(crate) policy_json: String,
    pub(crate) decision: ProductionRecoveryDecision,
}

fn invalid(message: impl Into<String>) -> SignedIntentError {
    SignedIntentError::Invalid(message.into())
}

impl SignedIntentPublicationConfirmation {
    pub(crate) fn new(
        intent: &SignedSupervisorIntent,
        policy: &[u8],
        decision: ProductionRecoveryDecision,
    ) -> Result<Self, SignedIntentError> {
        if policy.is_empty() || policy.len() > MAX_POLICY_BYTES {
            return Err(invalid(
                "confirmation policy exceeds its original byte bound",
            ));
        }
        let value = Self {
            schema_version: 1,
            intent_sha256: intent.intent_sha256.clone(),
            policy_json: std::str::from_utf8(policy)
                .map_err(|error| invalid(error.to_string()))?
                .to_string(),
            decision,
        };
        value.validate_for(intent)?;
        value.canonical_bytes()?;
        Ok(value)
    }

    /// Mathematical verification of retained evidence at its own signed issue
    /// time. In particular, this does not authorize an expired decision, an old
    /// daemon epoch, a revoked policy, a process launch or a new external CAS.
    pub(crate) fn validate_for(
        &self,
        intent: &SignedSupervisorIntent,
    ) -> Result<(), SignedIntentError> {
        intent.validate()?;
        self.validate()?;
        let expected_release = match (self.decision.outcome, intent.status, intent.transition) {
            (
                ProductionRecoveryOutcome::ConfirmUnknownPublication,
                SignedIntentStatus::Aborted,
                _,
            ) if intent.unknown_effects.last().is_some_and(|unknown| {
                unknown.decision.outcome == ProductionRecoveryOutcome::AbandonUnknown
                    && unknown.decision.grant_sha256 == intent.grant_sha256
                    && unknown.decision.schema_version == 3
                    && unknown.decision.pq_authority.is_some()
            }) =>
            {
                intent.source_release.as_str()
            }
            (
                ProductionRecoveryOutcome::ConfirmCommittedPublication,
                SignedIntentStatus::Committed,
                H7H89ProductionTransition::Upgrade,
            ) => intent.target_release.as_str(),
            (
                ProductionRecoveryOutcome::ConfirmRolledBackPublication,
                SignedIntentStatus::RolledBack,
                H7H89ProductionTransition::Upgrade,
            ) => intent.source_release.as_str(),
            (
                ProductionRecoveryOutcome::ConfirmRolledBackPublication,
                SignedIntentStatus::RolledBack,
                H7H89ProductionTransition::Rollback,
            ) => intent.target_release.as_str(),
            _ => {
                return Err(invalid(
                    "publication confirmation does not match its retained outcome",
                ));
            }
        };
        // An explicitly PQ-abandoned legacy unresolved intent keeps its real
        // original authority provenance. Confirming that disposition cannot
        // invent a PQ signature for the old grant or permit a legacy completion.
        if (intent.pq_authority.is_none()
            && self.decision.outcome != ProductionRecoveryOutcome::ConfirmUnknownPublication)
            || intent.requires_recovery()
            || self.intent_sha256 != intent.intent_sha256
            || self.decision.grant_sha256 != intent.grant_sha256
            || self.decision.agent_id != intent.agent_id
            || self.decision.observed_release != expected_release
        {
            return Err(invalid("confirmation differs from its retained intent"));
        }
        Ok(())
    }

    pub(crate) fn digest(&self) -> Result<Sha256Digest, SignedIntentError> {
        self.validate()?;
        let bytes = self.canonical_bytes()?;
        let mut digest = Sha256::new();
        digest.update(DOMAIN);
        digest.update((bytes.len() as u64).to_be_bytes());
        digest.update(bytes);
        Ok(Sha256Digest::from_sha256_output(digest.finalize()))
    }

    fn validate(&self) -> Result<(), SignedIntentError> {
        if self.schema_version != 1
            || self.policy_json.is_empty()
            || self.policy_json.len() > MAX_POLICY_BYTES
            || self.decision.schema_version != 3
            || self.decision.pq_authority.is_none()
            || self.decision.intent_sha256 != self.intent_sha256
        {
            return Err(invalid("malformed PQ publication confirmation"));
        }
        match self.decision.outcome {
            ProductionRecoveryOutcome::ConfirmUnknownPublication
                if self.decision.completion_observation.is_none()
                    && self
                        .decision
                        .unknown_observation
                        .as_ref()
                        .and_then(|observed| observed.predecessor.as_ref())
                        .is_some() => {}
            ProductionRecoveryOutcome::ConfirmCommittedPublication
            | ProductionRecoveryOutcome::ConfirmRolledBackPublication
                if self.decision.unknown_observation.is_none()
                    && self.decision.completion_observation.is_some() => {}
            _ => {
                return Err(invalid(
                    "publication confirmation has the wrong observation domain",
                ));
            }
        }
        let verifier =
            H7H89ProductionGrantVerifier::from_pq_policy_bytes(self.policy_json.as_bytes())
                .map_err(|error| invalid(error.to_string()))?;
        let agent = AgentId::parse(self.decision.agent_id.clone())
            .map_err(|error| invalid(error.to_string()))?;
        // Self-described release observations are checked against the actual
        // locked owner by the caller. This checks only the retained signature.
        verifier
            .verify_recovery(
                &self.decision,
                &agent,
                &self.decision.grant_sha256,
                &self.intent_sha256,
                &self.decision.release_transaction_sha256,
                &self.decision.observed_release,
                &self.decision.observed_manifest_sha256,
                &self.decision.observed_agentd_sha256,
                self.decision.observed_matrixd_sha256.as_ref(),
                self.decision.expected_lifecycle_generation,
                self.decision.authority_epoch,
                self.decision.issued_at_unix_seconds,
            )
            .map_err(|error| invalid(error.to_string()))
    }

    fn canonical_bytes(&self) -> Result<Vec<u8>, SignedIntentError> {
        let bytes = serde_json::to_vec(self)?;
        if bytes.len() as u64 > MAX_CONFIRMATION_BYTES {
            return Err(invalid(
                "publication confirmation exceeds its journal byte bound",
            ));
        }
        Ok(bytes)
    }
}

pub(crate) fn read_current(
    run_root: &Path,
) -> Result<Option<SignedIntentPublicationConfirmation>, SignedIntentError> {
    read(run_root, CURRENT_FILE)
}

pub(crate) fn read_predecessor(
    run_root: &Path,
) -> Result<Option<SignedIntentPublicationConfirmation>, SignedIntentError> {
    read(run_root, PREDECESSOR_FILE)
}

/// The caller holds the existing serialized owner and verifies the appropriate
/// external anchor before replacing evidence. An error never permits dispatch.
pub(crate) fn write_current(
    run_root: &Path,
    expected: Option<&SignedIntentPublicationConfirmation>,
    next: Option<&SignedIntentPublicationConfirmation>,
) -> Result<(), SignedIntentError> {
    write(run_root, CURRENT_FILE, expected, next)
}

pub(crate) fn write_predecessor(
    run_root: &Path,
    expected: Option<&SignedIntentPublicationConfirmation>,
    next: Option<&SignedIntentPublicationConfirmation>,
) -> Result<(), SignedIntentError> {
    write(run_root, PREDECESSOR_FILE, expected, next)
}

fn read(
    run_root: &Path,
    name: &str,
) -> Result<Option<SignedIntentPublicationConfirmation>, SignedIntentError> {
    let Some(bytes) =
        crate::bounded_regular_file::read_optional(&run_root.join(name), MAX_CONFIRMATION_BYTES)?
    else {
        return Ok(None);
    };
    let value: Option<SignedIntentPublicationConfirmation> = serde_json::from_slice(&bytes)?;
    if serde_json::to_vec(&value)? != bytes {
        return Err(invalid("confirmation material is not canonical"));
    }
    if let Some(value) = &value {
        value.validate()?;
    }
    Ok(value)
}

fn write(
    run_root: &Path,
    name: &str,
    expected: Option<&SignedIntentPublicationConfirmation>,
    next: Option<&SignedIntentPublicationConfirmation>,
) -> Result<(), SignedIntentError> {
    if read(run_root, name)?.as_ref() != expected {
        return Err(invalid(
            "publication confirmation changed before its owner update",
        ));
    }
    let bytes = match next {
        Some(value) => {
            value.validate()?;
            value.canonical_bytes()?
        }
        // A durable tombstone uses the existing atomic, directory-synced
        // publisher on every platform. A stale file after a failed write still
        // cannot match a different external intent or confirmation digest.
        None => b"null".to_vec(),
    };
    crate::signed_intent::write_atomic_bytes(run_root, name, &bytes)
}

#[cfg(test)]
#[path = "signed_intent_confirmation_tests.rs"]
mod tests;
