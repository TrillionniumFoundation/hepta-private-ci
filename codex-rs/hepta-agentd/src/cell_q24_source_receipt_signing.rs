//! Fixed original Observer enrollment and bounded, nonrenewable signing.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::StableId;
use ed25519_dalek::Signer;

use super::*;

pub(super) fn validate_config(
    config: &OriginalCellQ24SourceSigningConfigV1,
    key: &SigningKey,
    original_material: &[u8],
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let cut = config.predecessor.snapshot();
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(cut.clone())?;
    config.scope.validate_snapshot(cut)?;
    if coordinator.next_stage() != Some(config.predecessor.stage())
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || &config.signer.principal.principal_id != cut.owners.owner(config.predecessor.stage())
        || cut.owners.evidence_trust_digest != config.verifier.trust_digest()
        || cut.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(Error::Binding(
            "original Observer capability and predecessor",
        ));
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        now()?,
    )?;
    let predecessor_evidence = match &config.predecessor {
        OriginalCellQ24SourcePredecessorV1::Initial(_) => Vec::new(),
        OriginalCellQ24SourcePredecessorV1::Experience {
            snapshot,
            attestation,
        } => {
            let receipt = snapshot
                .receipts
                .first()
                .ok_or(Error::Binding("original Experience cut"))?;
            learning_owner_evidence::encode(
                &learning_iteration_receipt_signing_bytes_v1(receipt)?,
                attestation,
            )?
        }
    };
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: cut.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-q24-source-receipt.v1\0",
            cut.head_digest.as_array(),
            config.scope.binding().as_array(),
            config.verifier.trust_digest().as_array(),
            config.signer.principal.principal_id.as_str().as_bytes(),
            &config.signer.verifying_key,
            &config.maximum_signature_lifetime_seconds.to_be_bytes(),
            Digest32::of_bytes(original_material).as_array(),
            Digest32::of_bytes(&predecessor_evidence).as_array(),
        ]),
    })
}

pub(super) fn sign_original(
    config: &OriginalCellQ24SourceSigningConfigV1,
    key: &SigningKey,
    original: &OriginalSource,
    binding: Digest32,
) -> Result<Vec<u8>, LearningOriginalOwnerErrorV1> {
    let issued_at = now()?;
    if issued_at
        >= config
            .predecessor
            .snapshot()
            .request
            .envelope
            .expiry_unix_seconds
    {
        return Err(LearningOriginalOwnerErrorV1::Binding(
            "new Observer receipt deadline",
        ));
    }
    let receipt = derivation::receipt(config, original, issued_at)
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original Observer receipt"))?;
    let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original Observer payload"))?;
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        issued_at,
    )?;
    let expires_at = issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(LearningOriginalOwnerErrorV1::Binding(
            "Observer deadline overflow",
        ))?
        .min(config.signer.principal.expires_at);
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(binding)?,
        principal_id: config.signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: config.verifier.trust_digest(),
        scope_digest: config.verifier.scope_digest(),
        objective_digest: config.verifier.objective_digest(),
        authority_epoch: config.signer.principal.authority_epoch,
        issued_at,
        expires_at,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    config.verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &signed,
        &payload,
        issued_at,
    )?;
    learning_owner_evidence::encode(&payload, &signed)
}

pub(super) fn evidence_id(binding: Digest32) -> Result<StableId, LearningOriginalOwnerErrorV1> {
    StableId::new(format!("original-source:{binding}"))
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original source evidence id"))
}
pub(super) fn now() -> Result<u64, LearningOriginalOwnerErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|v| v.as_secs())
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original source clock"))
}
