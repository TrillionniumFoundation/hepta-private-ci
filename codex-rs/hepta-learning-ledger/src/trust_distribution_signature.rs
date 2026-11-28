//! Signature validation without current-generation or activation authority.
//! Metadata can be copied freely; it is not an independently current frontier.

use super::*;

/// Non-authorizing projection of a complete signature-validated distribution.
/// Constructing or deserializing equivalent metadata cannot activate trust.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningTrustDistributionIdentityV1 {
    pub root_id: StableId,
    pub root_digest: Digest32,
    pub distribution_id: StableId,
    pub generation: u64,
    pub effective_at: u64,
    pub distribution_digest: Digest32,
    pub issued_at: u64,
    pub expires_at: u64,
    pub trust_digest: Digest32,
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
}

/// Valid only for the supplied root and observation time. This has no public
/// constructor, deserializer, verifier accessor or conversion to Activated trust.
/// It does not establish which valid generation an independent owner selects.
#[derive(Debug)]
pub struct SignatureVerifiedLearningTrustV1 {
    pub(super) identity: LearningTrustDistributionIdentityV1,
    pub(super) verifier: LearningEvidenceVerifierV1,
}

impl SignatureVerifiedLearningTrustV1 {
    #[must_use]
    pub fn learning_trust_signature_identity(&self) -> &LearningTrustDistributionIdentityV1 {
        &self.identity
    }
}

/// Verify the entire original signature, root, scope, signer and time contract.
/// Callers still need an independent current owner and their own operation
/// authority. This function performs no I/O, mutation or trust activation.
pub fn verify_learning_trust_distribution_signature(
    root: &LearningTrustRootV1,
    signed: &SignedLearningTrustDistributionV1,
    now: u64,
) -> Result<SignatureVerifiedLearningTrustV1, LearningTrustDistributionError> {
    let root_digest = validate_root(root, now)?;
    if signed.root_id != root.root_id {
        return Err(LearningTrustDistributionError::RootMismatch);
    }
    if signed.issued_at > now
        || signed.issued_at > signed.expires_at
        || signed.issued_at > signed.distribution.effective_at
        || now > signed.expires_at
        || signed.issued_at < root.valid_from
        || signed.expires_at > root.expires_at
    {
        return Err(LearningTrustDistributionError::DistributionWindow);
    }

    let distribution = &signed.distribution;
    if distribution.generation == 0
        || distribution.effective_at > now
        || distribution.trust.scope_digest != root.scope_digest
    {
        return Err(LearningTrustDistributionError::InvalidGeneration);
    }

    let verifier = LearningEvidenceVerifierV1::new(distribution.trust.clone())?;
    let payload = distribution_signing_bytes(
        &signed.root_id,
        distribution,
        signed.issued_at,
        signed.expires_at,
    )?;
    VerifyingKey::from_bytes(&root.verifying_key)
        .map_err(|_| LearningTrustDistributionError::InvalidRoot)?
        .verify_strict(&payload, &Signature::from_bytes(&signed.signature))
        .map_err(|_| LearningTrustDistributionError::InvalidSignature)?;
    let distribution_digest = digest_distribution(
        root_digest,
        &distribution.distribution_id,
        distribution.generation,
        distribution.effective_at,
        signed.issued_at,
        signed.expires_at,
        &verifier,
    );
    Ok(SignatureVerifiedLearningTrustV1 {
        identity: LearningTrustDistributionIdentityV1 {
            root_id: root.root_id.clone(),
            root_digest,
            distribution_id: distribution.distribution_id.clone(),
            generation: distribution.generation,
            effective_at: distribution.effective_at,
            distribution_digest,
            issued_at: signed.issued_at,
            expires_at: signed.expires_at,
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: verifier.authority_epoch(),
        },
        verifier,
    })
}
