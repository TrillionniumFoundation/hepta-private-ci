//! Current-use policy carried by the original durable signed intent. Terminal
//! history remains evidence; it does not become a perpetual spawn permission.
use crate::SupervisorError;
use crate::signed_authority::H7H89ProductionGrant;
use crate::signed_authority::H7H89ProductionGrantVerifier;
use crate::signed_authority::PqAuthorityBinding;
use crate::signed_intent::SignedIntentError;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::CurrentReleaseAdmission;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedIntentPqAuthority {
    pub binding: PqAuthorityBinding,
    pub policy_json: String,
    pub grant: H7H89ProductionGrant,
    pub h7_envelope: H7SignedArtifactEnvelope,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
}

impl SignedIntentPqAuthority {
    /// Verify retained original signatures at their signed window. This is
    /// historical integrity only; actual entry separately checks live policy,
    /// trusted time, the current epoch and the external intent owner.
    pub(crate) fn verify_historical_for(
        &self,
        intent: &SignedSupervisorIntent,
    ) -> Result<(), SupervisorError> {
        self.verify_at(intent, self.issued_at_unix_seconds)
    }

    /// Borrow only public-key preparation for the exact retained policy bytes.
    /// The caller's current policy may differ from historical grant authority;
    /// that case reconstructs the original verifier and never substitutes keys.
    pub(crate) fn verify_historical_for_with_prepared(
        &self,
        intent: &SignedSupervisorIntent,
        prepared: &H7H89ProductionGrantVerifier,
    ) -> Result<(), SupervisorError> {
        self.verify_at_with_prepared(intent, self.issued_at_unix_seconds, Some(prepared))
    }

    fn verify_at(&self, intent: &SignedSupervisorIntent, now: u64) -> Result<(), SupervisorError> {
        self.verify_at_with_prepared(intent, now, /*prepared*/ None)
    }

    fn verify_at_with_prepared(
        &self,
        intent: &SignedSupervisorIntent,
        now: u64,
        prepared: Option<&H7H89ProductionGrantVerifier>,
    ) -> Result<(), SupervisorError> {
        self.validate_for(intent)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        // Exact raw bytes include every role, epoch, key pin and encoding. A
        // digest, signer ID or previously successful signature is insufficient.
        // This borrows no permission, clock, frontier or signature observation.
        let reconstructed;
        let verifier = match prepared
            .filter(|verifier| verifier.policy_bytes() == Some(self.policy_json.as_bytes()))
        {
            Some(verifier) => verifier,
            None => {
                reconstructed =
                    H7H89ProductionGrantVerifier::from_pq_policy_bytes(self.policy_json.as_bytes())
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                &reconstructed
            }
        };
        let agent = codex_hepta_contracts::AgentId::parse(intent.agent_id.clone())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        verifier
            .verify(
                &self.grant,
                &self.h7_envelope,
                &agent,
                &intent.source_release,
                &intent.target_release,
                intent.expected_control_revision,
                intent.expected_lifecycle_generation,
                intent.authority_epoch,
                now,
            )
            .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))
    }

    pub(crate) fn validate_for(
        &self,
        intent: &SignedSupervisorIntent,
    ) -> Result<(), SignedIntentError> {
        // Read/rewrite validation checks canonical keys and all bindings. It
        // grants no signature observation; verify_at separately obtains the
        // canonical verifier and checks both real signatures on every call.
        if Sha256Digest::parse(self.binding.policy_sha256.as_str()).is_err()
            || self.issued_at_unix_seconds == 0
            || self.expires_at_unix_seconds <= self.issued_at_unix_seconds
            || self.expires_at_unix_seconds - self.issued_at_unix_seconds
                > crate::signed_authority::SIGNED_AUTHORITY_MAX_LIFETIME_SECONDS
        {
            return Err(SignedIntentError::Invalid(
                "signed intent PQ authority is malformed".to_string(),
            ));
        }
        let policy_sha256 =
            H7H89ProductionGrantVerifier::validate_pq_policy_bytes(self.policy_json.as_bytes())
                .map_err(|error| SignedIntentError::Invalid(error.to_string()))?;
        self.grant
            .validate_shape(&self.h7_envelope)
            .map_err(|error| SignedIntentError::Invalid(error.to_string()))?;
        if policy_sha256 != self.binding.policy_sha256
            || self.grant.pq_authority.as_ref() != Some(&self.binding)
            || self.grant.grant_sha256 != intent.grant_sha256
            || self.grant.agent_id != intent.agent_id
            || self.grant.transition != intent.transition
            || self.grant.source_release != intent.source_release
            || self.grant.target_release != intent.target_release
            || self.grant.expected_control_revision != intent.expected_control_revision
            || self.grant.expected_lifecycle_generation != intent.expected_lifecycle_generation
            || self.grant.authority_epoch != intent.authority_epoch
            || self.issued_at_unix_seconds
                != self
                    .grant
                    .issued_at_unix_seconds
                    .max(self.h7_envelope.issued_at_unix_seconds)
            || self.expires_at_unix_seconds
                != self
                    .grant
                    .expires_at_unix_seconds
                    .min(self.h7_envelope.expires_at_unix_seconds)
        {
            return Err(SignedIntentError::Invalid(
                "retained PQ proof differs from its admitted intent".to_string(),
            ));
        }
        Ok(())
    }
}

impl SignedSupervisorIntent {
    pub(crate) fn bind_authority(
        mut self,
        grant: &H7H89ProductionGrant,
        envelope: &H7SignedArtifactEnvelope,
        verifier: &H7H89ProductionGrantVerifier,
    ) -> Result<Self, SignedIntentError> {
        if let Some(binding) = &grant.pq_authority {
            self.schema_version = 3;
            self.pq_authority = Some(SignedIntentPqAuthority {
                binding: binding.clone(),
                policy_json: std::str::from_utf8(verifier.policy_bytes().ok_or_else(|| {
                    SignedIntentError::Invalid("missing retained PQ policy".to_string())
                })?)
                .map_err(|error| SignedIntentError::Invalid(error.to_string()))?
                .to_string(),
                grant: grant.clone(),
                h7_envelope: envelope.clone(),
                issued_at_unix_seconds: grant
                    .issued_at_unix_seconds
                    .max(envelope.issued_at_unix_seconds),
                expires_at_unix_seconds: grant
                    .expires_at_unix_seconds
                    .min(envelope.expires_at_unix_seconds),
            });
            self.intent_sha256 = self.compute_digest()?;
            self.validate()?;
        }
        Ok(self)
    }
}

#[path = "signed_intent_admission.rs"]
mod admission;
pub(crate) use admission::MutationPolicyAdmission;

pub(crate) fn revalidate_process_admission(
    admission: Option<&CurrentReleaseAdmission>,
    intent: Option<&SignedSupervisorIntent>,
    record: &codex_hepta_fleet::AgentRecord,
    qualification: bool,
) -> Result<(), SupervisorError> {
    if !qualification {
        let guard = admission.ok_or_else(|| {
            SupervisorError::ProductionAuthority(
                "ordinary process entry requires the current release owner".to_string(),
            )
        })?;
        crate::signed_intent_anchor::check_process_entry(guard, record, intent)?;
    }
    let pending = intent.filter(|intent| {
        matches!(
            intent.status,
            SignedIntentStatus::Prepared | SignedIntentStatus::Queued
        )
    });
    if let Some(intent) = pending {
        if let Some(policy) = &intent.pq_authority {
            let guard = admission.ok_or_else(|| {
                SupervisorError::ProductionAuthority(
                    "pending PQ intent requires the current release owner".to_string(),
                )
            })?;
            let digest = digest_bytes(&policy.binding.policy_sha256)?;
            let now = guard.revalidate_with_protocol_configuration(digest)? / 1000;
            let verifier =
                H7H89ProductionGrantVerifier::from_pq_policy_bytes(policy.policy_json.as_bytes())
                    .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;
            verifier
                .verify(
                    &policy.grant,
                    &policy.h7_envelope,
                    &codex_hepta_contracts::AgentId::parse(intent.agent_id.clone())
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
                    &intent.source_release,
                    &intent.target_release,
                    intent.expected_control_revision,
                    intent.expected_lifecycle_generation,
                    intent.authority_epoch,
                    now,
                )
                .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;
            let final_now = guard.revalidate_with_protocol_configuration(digest)? / 1000;
            return current_window(
                final_now,
                policy.issued_at_unix_seconds,
                policy.expires_at_unix_seconds,
            );
        }
        if !qualification {
            return Err(SupervisorError::ProductionAuthority(
                "legacy pending intent cannot become current production permission".to_string(),
            ));
        }
    }
    if let Some(guard) = admission {
        guard.revalidate()?;
    }
    Ok(())
}

fn current_window(now: u64, issued: u64, expires: u64) -> Result<(), SupervisorError> {
    if now < issued || now >= expires {
        return Err(SupervisorError::ProductionAuthority(
            "authority is outside its current trusted-clock validity window".to_string(),
        ));
    }
    Ok(())
}

pub(crate) fn authority_milliseconds(seconds: u64) -> Result<u64, SupervisorError> {
    seconds.checked_mul(1000).ok_or_else(|| {
        SupervisorError::ProductionAuthority(
            "authority validity timestamp overflows milliseconds".to_string(),
        )
    })
}

pub(crate) fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], SupervisorError> {
    Sha256Digest::parse(digest.as_str()).map_err(SupervisorError::Invalid)?;
    let value = digest.as_str();
    if value.len() != 64 {
        return Err(SupervisorError::Invalid(
            "policy digest length is invalid".to_string(),
        ));
    }
    let mut bytes = [0; 32];
    for (index, out) in bytes.iter_mut().enumerate() {
        *out = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).map_err(|_| {
            SupervisorError::Invalid("policy digest contains invalid hexadecimal".to_string())
        })?;
    }
    Ok(bytes)
}

/// A current release name alone is not a completed H7 effect. The original
/// transaction must witness the exact grant/epoch and release-state CAS.
pub(crate) fn terminal_owner_matches(
    intent: &SignedSupervisorIntent,
    transaction: &crate::release_transaction::DurableReleaseTransaction,
    record: &codex_hepta_fleet::AgentRecord,
) -> bool {
    use crate::release_transaction::ReleaseTransactionKind;
    use crate::release_transaction::ReleaseTransactionPhase;
    if transaction.agent_id != intent.agent_id
        || record.release_state.agent_id.as_str() != intent.agent_id
        || transaction.grant_sha256.as_ref() != Some(&intent.grant_sha256)
        || transaction.authority_epoch != Some(intent.authority_epoch)
        || transaction.source_release != intent.source_release
        || transaction.target_release != intent.target_release
        || transaction.expected_lifecycle_generation != intent.expected_lifecycle_generation
    {
        return false;
    }
    let current = record
        .release_state
        .current
        .as_ref()
        .map(codex_hepta_fleet::ReleaseId::as_str);
    let previous = record
        .release_state
        .previous
        .as_ref()
        .map(codex_hepta_fleet::ReleaseId::as_str);
    match (intent.transition, transaction.kind, transaction.phase) {
        (
            crate::H7H89ProductionTransition::Upgrade,
            ReleaseTransactionKind::Upgrade,
            ReleaseTransactionPhase::Committed,
        )
        | (
            crate::H7H89ProductionTransition::Rollback,
            ReleaseTransactionKind::ExplicitRollback,
            ReleaseTransactionPhase::RolledBack,
        ) => {
            current == Some(intent.target_release.as_str())
                && previous == Some(intent.source_release.as_str())
                && transaction.expected_release_state_generation.checked_add(1)
                    == Some(record.release_state.generation)
        }
        (
            crate::H7H89ProductionTransition::Upgrade,
            ReleaseTransactionKind::Upgrade,
            ReleaseTransactionPhase::RolledBack,
        ) => {
            current == Some(intent.source_release.as_str())
                && record.release_state.generation == transaction.expected_release_state_generation
        }
        _ => false,
    }
}

#[cfg(test)]
#[path = "signed_intent_policy_tests.rs"]
mod tests;
