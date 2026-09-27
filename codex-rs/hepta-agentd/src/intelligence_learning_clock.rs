//! Agentd learning uses Unix milliseconds for event and verification clocks.
//! An immutable event timestamp is never a substitute for the host's current
//! verification time. Already-applied observation does not call this module.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::ProductionLedgerError;

pub(super) const CLOCK_UNAVAILABLE: &str = "current learning clock unavailable";
pub(super) const CLOCK_BEHIND_EVENT: &str = "learning clock behind event time";

pub(super) fn verification_time(event_time_ms: u64) -> Result<u64, ProductionLedgerError> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .ok_or(ProductionLedgerError::Binding(CLOCK_UNAVAILABLE))?;
    validate_times(event_time_ms, now)
}

fn validate_times(event_time_ms: u64, current_time_ms: u64) -> Result<u64, ProductionLedgerError> {
    if current_time_ms < event_time_ms {
        // A clock rollback is not proof of NotApplied. Keep the operation open.
        return Err(ProductionLedgerError::Binding(CLOCK_BEHIND_EVENT));
    }
    Ok(current_time_ms)
}

#[cfg(test)]
mod tests {
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
    use codex_hepta_learning_ledger::SignedEvidenceError;
    use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    #[test]
    fn replay_verification_uses_current_time_not_frozen_event_time() {
        let signing_key = SigningKey::from_bytes(&[27; 32]);
        let key = signing_key.verifying_key().to_bytes();
        let scope = Digest32::of_bytes(b"scope");
        let objective = Digest32::of_bytes(b"objective");
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 1,
            signers: vec![TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id("generator"),
                    credential_chain_digest: Digest32::of_bytes(b"credentials"),
                    signing_key_digest: Digest32::of_bytes(&key),
                    scope_digest: scope,
                    authority_epoch: 1,
                    authenticated_at: 1,
                    expires_at: 1_000,
                },
                controller_id: id("controller"),
                verifying_key: key,
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            }],
        })
        .expect("verifier");
        let payload = b"exact immutable event";
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id("evidence"),
            principal_id: id("generator"),
            role: LearningEvidenceRoleV1::Generator,
            trust_digest: verifier.trust_digest(),
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 1,
            issued_at: 100,
            expires_at: 200,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = signing_key.sign(&evidence.signing_bytes()).to_bytes();
        verifier
            .verify(LearningEvidenceRoleV1::Generator, &evidence, payload, 150)
            .expect("historically valid evidence");
        let frozen_event_time = 150;
        let current_time = validate_times(frozen_event_time, 201).expect("current time");
        assert!(matches!(
            verifier.verify(
                LearningEvidenceRoleV1::Generator,
                &evidence,
                payload,
                current_time,
            ),
            Err(SignedEvidenceError::ValidityWindow)
        ));
        assert_eq!(frozen_event_time, 150);
    }

    #[test]
    fn learning_clock_rollback_is_not_normalized_into_old_time() {
        assert!(validate_times(150, 149).is_err());
        assert_eq!(validate_times(150, 150).expect("same instant"), 150);
        assert_eq!(validate_times(150, 250).expect("current instant"), 250);
    }
}
