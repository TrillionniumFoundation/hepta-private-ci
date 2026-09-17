//! Signature-verified admission for independently retained holdout anchors.
//!
//! The durable journal prevents semantic reuse and detects rollback only as far
//! as the minimum anchor supplied by its host. This layer authenticates that
//! minimum anchor against host-owned trust state and a host-owned freshness
//! watermark. It does not persist the anchor, choose the current witness, or
//! authorize release of confirmatory labels.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableFinalHoldoutJournalV1;
use crate::DurableHoldoutError;
use crate::HoldoutAnchorV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedHoldoutAnchorV1 {
    /// Nonzero host-owned storage/evaluation namespace binding.
    pub binding: Digest32,
    /// Minimum acknowledged journal state retained outside the journal.
    pub anchor: HoldoutAnchorV1,
    /// Independent trusted observer attestation over the exact anchor payload.
    pub observer: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedHoldoutAnchorV1 {
    pub binding: Digest32,
    pub anchor: HoldoutAnchorV1,
    pub observer_principal: StableId,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthenticatedHoldoutError {
    InvalidBinding,
    InvalidAnchor,
    BootstrapAnchor,
    StaleWitness,
    Evidence(SignedEvidenceError),
    Durable(DurableHoldoutError),
}

impl fmt::Display for AuthenticatedHoldoutError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AuthenticatedHoldoutError {}
impl From<SignedEvidenceError> for AuthenticatedHoldoutError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<DurableHoldoutError> for AuthenticatedHoldoutError {
    fn from(value: DurableHoldoutError) -> Self {
        Self::Durable(value)
    }
}

/// Canonical bytes signed by the independent anchor observer.
///
/// Trust scope, objective and authority epoch are bound by
/// `SignedLearningEvidenceV1` and `LearningEvidenceVerifierV1`; these bytes bind
/// the journal namespace and exact minimum acknowledged state.
pub fn holdout_anchor_signing_payload_v1(
    binding: Digest32,
    anchor: HoldoutAnchorV1,
) -> Result<Vec<u8>, AuthenticatedHoldoutError> {
    if binding.is_zero() {
        return Err(AuthenticatedHoldoutError::InvalidBinding);
    }
    if (anchor.sequence == 0) != anchor.head.is_zero() {
        return Err(AuthenticatedHoldoutError::InvalidAnchor);
    }
    let mut bytes = b"hepta.intelligence-eval.durable-holdout-anchor.v1\0".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(anchor.head.as_array());
    Ok(bytes)
}

/// Verify a host-supplied anchor witness against immutable host-owned trust.
///
/// `minimum_issued_at` is a monotonic freshness watermark retained by the host
/// outside the journal and outside the submitted witness. It prevents an older,
/// still-cryptographically-valid anchor attestation from being replayed after a
/// newer witness has been acknowledged. The verifier still enforces signer
/// role, trust digest, objective, authority epoch, validity and revocation.
pub fn authenticate_holdout_anchor_v1(
    witness: &SignedHoldoutAnchorV1,
    verifier: &LearningEvidenceVerifierV1,
    minimum_issued_at: u64,
    now: u64,
) -> Result<AuthenticatedHoldoutAnchorV1, AuthenticatedHoldoutError> {
    if witness.observer.issued_at < minimum_issued_at {
        return Err(AuthenticatedHoldoutError::StaleWitness);
    }
    let payload = holdout_anchor_signing_payload_v1(witness.binding, witness.anchor)?;
    let verified = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &witness.observer,
        &payload,
        now,
    )?;
    let mut authentication = b"hepta.intelligence-eval.authenticated-holdout-anchor.v1\0".to_vec();
    authentication.extend_from_slice(verifier.trust_digest().as_array());
    authentication.extend_from_slice(Digest32::of_bytes(&witness.observer.signing_bytes()).as_array());
    authentication.extend_from_slice(&witness.observer.signature);
    Ok(AuthenticatedHoldoutAnchorV1 {
        binding: witness.binding,
        anchor: witness.anchor,
        observer_principal: verified.principal().principal_id.clone(),
        trust_digest: verifier.trust_digest(),
        authentication_digest: Digest32::of_bytes(&authentication),
    })
}

/// Recover the durable journal only after authenticating its independently
/// retained minimum anchor. A zero anchor is intentionally rejected here:
/// bootstrap must use `DurableFinalHoldoutJournalV1::create`, then persist and
/// attest the first nonzero anchor before any recovery path is trusted.
pub fn recover_with_authenticated_holdout_anchor_v1(
    file: File,
    witness: &SignedHoldoutAnchorV1,
    verifier: &LearningEvidenceVerifierV1,
    minimum_issued_at: u64,
    now: u64,
) -> Result<
    (DurableFinalHoldoutJournalV1, AuthenticatedHoldoutAnchorV1),
    AuthenticatedHoldoutError,
> {
    if witness.anchor.sequence == 0 {
        return Err(AuthenticatedHoldoutError::BootstrapAnchor);
    }
    let authenticated =
        authenticate_holdout_anchor_v1(witness, verifier, minimum_issued_at, now)?;
    let journal = DurableFinalHoldoutJournalV1::recover(
        file,
        authenticated.binding,
        authenticated.anchor,
    )?;
    Ok((journal, authenticated))
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    fn digest(value: u8) -> Digest32 {
        Digest32::from_array([value; 32])
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid test id")
    }

    fn signed_witness(
        anchor: HoldoutAnchorV1,
    ) -> (SignedHoldoutAnchorV1, LearningEvidenceVerifierV1) {
        let key = SigningKey::from_bytes(&[31; 32]);
        let scope = digest(2);
        let objective = digest(3);
        let principal = AuthenticatedPrincipalV1 {
            principal_id: id("holdout-observer"),
            credential_chain_digest: digest(4),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: scope,
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        };
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 7,
            signers: vec![TrustedLearningSignerV1 {
                principal: principal.clone(),
                controller_id: id("holdout-controller"),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Observer],
                revoked_at: None,
            }],
        })
        .expect("valid test trust");
        let binding = digest(8);
        let payload = holdout_anchor_signing_payload_v1(binding, anchor).expect("valid payload");
        let mut observer = SignedLearningEvidenceV1 {
            evidence_id: id("holdout-anchor-evidence"),
            principal_id: principal.principal_id,
            role: LearningEvidenceRoleV1::Observer,
            trust_digest: verifier.trust_digest(),
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(&payload),
            signature: [0; 64],
        };
        observer.signature = key.sign(&observer.signing_bytes()).to_bytes();
        (
            SignedHoldoutAnchorV1 {
                binding,
                anchor,
                observer,
            },
            verifier,
        )
    }

    #[test]
    fn admits_current_observer_signed_anchor() {
        let anchor = HoldoutAnchorV1 {
            sequence: 3,
            head: digest(9),
        };
        let (witness, verifier) = signed_witness(anchor);
        let admitted = authenticate_holdout_anchor_v1(&witness, &verifier, 20, 30)
            .expect("current signed anchor");
        assert_eq!(admitted.anchor, anchor);
        assert_eq!(admitted.binding, witness.binding);
        assert_eq!(admitted.observer_principal, id("holdout-observer"));
        assert!(!admitted.authentication_digest.is_zero());
    }

    #[test]
    fn stale_or_mutated_anchor_witness_is_rejected() {
        let anchor = HoldoutAnchorV1 {
            sequence: 3,
            head: digest(9),
        };
        let (mut witness, verifier) = signed_witness(anchor);
        assert_eq!(
            authenticate_holdout_anchor_v1(&witness, &verifier, 21, 30),
            Err(AuthenticatedHoldoutError::StaleWitness)
        );
        witness.anchor.head = digest(10);
        assert!(matches!(
            authenticate_holdout_anchor_v1(&witness, &verifier, 20, 30),
            Err(AuthenticatedHoldoutError::Evidence(
                SignedEvidenceError::PayloadMismatch
            ))
        ));
    }

    #[test]
    fn bootstrap_and_malformed_anchor_are_not_recovery_witnesses() {
        assert_eq!(
            holdout_anchor_signing_payload_v1(
                digest(8),
                HoldoutAnchorV1 {
                    sequence: 0,
                    head: digest(9),
                },
            ),
            Err(AuthenticatedHoldoutError::InvalidAnchor)
        );
        let zero = HoldoutAnchorV1 {
            sequence: 0,
            head: Digest32::ZERO,
        };
        let (witness, verifier) = signed_witness(zero);
        // Authentication can audit a signed bootstrap statement, but recovery
        // never accepts it as rollback protection for an existing journal.
        assert!(authenticate_holdout_anchor_v1(&witness, &verifier, 20, 30).is_ok());
    }
}
