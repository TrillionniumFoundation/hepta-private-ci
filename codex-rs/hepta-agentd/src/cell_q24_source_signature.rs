//! Canonical signing and observation helpers for the original Source owner.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use ed25519_dalek::Signer;

use super::*;

pub(super) fn sign_original_source_receipt(
    config: &OriginalCellQ24SourceSigningConfigV1,
    key: &SigningKey,
    receipt: &LearningIterationReceiptV1,
    payload: &[u8],
    identity: Digest32,
) -> Result<SignedLearningEvidenceV1, LearningOriginalOwnerErrorV1> {
    let issued_at = receipt.observed_unix_seconds;
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        issued_at,
    )?;
    let expires_at = issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(LearningOriginalOwnerErrorV1::Binding(
            "signature deadline overflow",
        ))?
        .min(config.signer.principal.expires_at);
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(identity)?,
        principal_id: config.signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: config.verifier.trust_digest(),
        scope_digest: config.verifier.scope_digest(),
        objective_digest: config.verifier.objective_digest(),
        authority_epoch: config.signer.principal.authority_epoch,
        issued_at,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    config.verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &signed,
        payload,
        issued_at,
    )?;
    Ok(signed)
}

pub(super) fn evidence_id(identity: Digest32) -> Result<StableId, LearningOriginalOwnerErrorV1> {
    StableId::new(format!("original-source:{identity}"))
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("source evidence id"))
}

pub(super) fn binding(message: &'static str) -> Error {
    LearningOriginalOwnerErrorV1::Binding(message).into()
}

pub(super) fn source_binding(_: CellQ24LearningPreparationErrorV1) -> LearningOriginalOwnerErrorV1 {
    LearningOriginalOwnerErrorV1::Binding("original task or Dataset changed during signing")
}

pub(super) fn now() -> Result<u64, LearningOriginalOwnerErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original source owner clock"))
}
