//! Closed bindings and encoding for the original material receipt pair.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::StableId;
use ed25519_dalek::Signer;

use super::*;

pub(super) fn owner_invalid(message: &'static str) -> LearningOriginalOwnerErrorV1 {
    LearningOriginalOwnerErrorV1::Binding(message)
}

pub(super) fn invalid(message: &'static str) -> Error {
    owner_invalid(message).into()
}

pub(super) fn now() -> Result<u64, LearningOriginalOwnerErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| owner_invalid("original material clock"))
}

pub(super) fn fresh_time(started_at: u64) -> Result<u64, LearningOriginalOwnerErrorV1> {
    let fresh = now()?;
    if fresh < started_at {
        return Err(owner_invalid("original material clock moved backwards"));
    }
    Ok(fresh)
}

pub(super) fn new_work_time(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    started_at: u64,
) -> Result<u64, LearningOriginalOwnerErrorV1> {
    let fresh = fresh_time(started_at)?;
    if fresh >= config.initial.request.envelope.expiry_unix_seconds {
        return Err(owner_invalid("original material work deadline"));
    }
    require_freeze_window(config, fresh)?;
    Ok(fresh)
}

pub(super) fn require_new_work(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    started_at: u64,
) -> Result<(), Error> {
    new_work_time(config, started_at)?;
    Ok(())
}

fn require_freeze_window(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    at: u64,
) -> Result<(), LearningOriginalOwnerErrorV1> {
    if at < config.freeze_evidence.issued_at || at >= config.freeze_evidence.expires_at {
        return Err(owner_invalid("original freeze signature window"));
    }
    Ok(())
}

pub(super) fn validate_config(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    experience_key: &SigningKey,
    dataset_key: &SigningKey,
) -> Result<(ProductEvaluationExecutionKeyV1, Digest32), Error> {
    let initial = LearningIterationCoordinatorV1::from_snapshot(config.initial.clone())?;
    config.scope.validate_snapshot(&config.initial)?;
    let policy = config.rule.inclusion_policy_digest(&config.initial)?;
    if initial.next_stage() != Some(LearningIterationStageV1::Experience)
        || !config.initial.receipts.is_empty()
        || config.initial.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.initial.request.envelope.objective_digest != config.verifier.objective_digest()
        || config.freeze_plan.objective_digest != config.verifier.objective_digest()
        || config.freeze_plan.inclusion_policy_digest != policy
        || config.freeze_evidence.role != LearningEvidenceRoleV1::Evaluator
        || config.freeze_evidence.trust_digest != config.verifier.trust_digest()
        || config.freeze_evidence.scope_digest != config.verifier.scope_digest()
        || config.freeze_evidence.objective_digest != config.verifier.objective_digest()
        || config.experience_signer.principal.principal_id != config.initial.owners.experience
        || config.dataset_signer.principal.principal_id != config.initial.owners.dataset
        || experience_key.verifying_key().to_bytes() != config.experience_signer.verifying_key
        || dataset_key.verifying_key().to_bytes() != config.dataset_signer.verifying_key
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(invalid("original material custody and frozen profile"));
    }
    let at = now()?;
    require_freeze_window(config, at)?;
    for signer in [&config.experience_signer, &config.dataset_signer] {
        config
            .verifier
            .require_signer_binding(LearningEvidenceRoleV1::Observer, signer, at)?;
    }
    // Both complete signer bindings are committed by the trust digest. Preserve
    // the original freeze bytes as well; an otherwise valid re-signature is a
    // different journal binding, not a recovery/renewal capability.
    let mut freeze = config.freeze_evidence.signing_bytes();
    freeze.extend_from_slice(&config.freeze_evidence.signature);
    let common = Digest32::of_parts(&[
        b"hepta.agentd.original-q24-material-receipts.v1\0",
        config.initial.head_digest.as_array(),
        config.scope.binding().as_array(),
        policy.as_array(),
        config.freeze_plan.snapshot_id.as_str().as_bytes(),
        config.freeze_plan.objective_digest.as_array(),
        config.freeze_plan.inclusion_policy_digest.as_array(),
        Digest32::of_bytes(&freeze).as_array(),
        config.verifier.trust_digest().as_array(),
        config
            .experience_signer
            .principal
            .principal_id
            .as_str()
            .as_bytes(),
        config
            .dataset_signer
            .principal
            .principal_id
            .as_str()
            .as_bytes(),
        &config.experience_signer.verifying_key,
        &config.dataset_signer.verifying_key,
        &config.maximum_signature_lifetime_seconds.to_be_bytes(),
    ]);
    Ok((
        ProductEvaluationExecutionKeyV1 {
            plan_id: config.initial.request.operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.agentd.original-q24-experience-journal.v1\0",
                common.as_array(),
            ]),
        },
        Digest32::of_parts(&[
            b"hepta.agentd.original-q24-dataset-journal.v1\0",
            common.as_array(),
        ]),
    ))
}

#[cfg(target_os = "linux")]
pub(super) fn require_panel_initial(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    panel: Option<&OriginalCircuitOnPolicyPanelPolicyV2>,
) -> Result<(), Error> {
    if let Some(panel) = panel {
        OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_initial(panel, &config.initial)
            .map_err(|_| invalid("original material on-policy panel declaration"))?;
    }
    Ok(())
}

pub(super) fn validate_snapshot(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    snapshot: &LearningIterationSnapshotV1,
) -> Result<(), Error> {
    LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    config.scope.validate_snapshot(snapshot)?;
    if snapshot.request != config.initial.request || snapshot.owners != config.initial.owners {
        return Err(invalid("original material operation"));
    }
    Ok(())
}

pub(super) fn require_snapshot_receipt(
    snapshot: &LearningIterationSnapshotV1,
    index: usize,
    receipt: &LearningIterationReceiptV1,
) -> Result<(), Error> {
    if let Some(retained) = snapshot.receipts.get(index)
        && retained != receipt
    {
        return Err(invalid("full CURRENT contains another material receipt"));
    }
    Ok(())
}

pub(super) fn read_material(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    sources: &mut OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    completed_receipt_readback: bool,
) -> Result<OriginalCellQ24DatasetV1, Error> {
    let mut reader = CellQ24DatasetReaderV1::new(sources.source, sources.identity, sources.ledger);
    let material = if completed_receipt_readback {
        reader.read_current_for_original_receipt(
            &config.initial,
            sources.baseline,
            config.rule,
            config.freeze_plan.clone(),
            &config.freeze_evidence,
        )?
    } else {
        reader.read_current(
            &config.initial,
            sources.baseline,
            config.rule,
            config.freeze_plan.clone(),
            &config.freeze_evidence,
        )?
    };
    Ok(material)
}

pub(super) fn verify_freeze(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    ledger: &mut LedgerWriter,
    material: &OriginalCellQ24DatasetV1,
    at: u64,
) -> Result<(), Error> {
    // Logical reauthentication after the preceding physical CURRENT/journal
    // reads keeps the original Evaluator credential window current as well.
    // This derives the same receipt; it appends/reserves/signs nothing.
    let receipt = ledger
        .freeze_dataset(config.freeze_plan.clone(), &config.freeze_evidence, at)
        .map_err(CellQ24DatasetErrorV1::from)?;
    if &receipt != material.receipt() {
        return Err(invalid("original freeze changed during receipt readback"));
    }
    let _ = ledger
        .read_dataset_records(&receipt, at)
        .map_err(CellQ24DatasetErrorV1::from)?;
    Ok(())
}

pub(super) fn require_same_material(
    before: &OriginalCellQ24DatasetV1,
    after: &OriginalCellQ24DatasetV1,
) -> Result<(), Error> {
    if before.provenance_digest() != after.provenance_digest()
        || before.receipt() != after.receipt()
        || before.batch().encoded() != after.batch().encoded()
        || before.experience_observation() != after.experience_observation()
        || before.dataset_observation() != after.dataset_observation()
    {
        return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
    }
    Ok(())
}

pub(super) fn experience_prefix(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    experience: &LearningIterationReceiptV1,
) -> Result<LearningIterationSnapshotV1, Error> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(config.initial.clone())?;
    if experience.observation.stage() != LearningIterationStageV1::Experience {
        return Err(invalid("original Experience predecessor"));
    }
    coordinator.record(experience.clone(), experience.observed_unix_seconds)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(coordinator.snapshot().clone())
}

pub(super) fn receipt(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    experience: Option<&LearningIterationReceiptV1>,
    material: &OriginalCellQ24DatasetV1,
    at: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let (prefix, observation, actor) = match experience {
        None => (
            config.initial.clone(),
            material.experience_observation(),
            &config.initial.owners.experience,
        ),
        Some(experience) => {
            if experience.observation != material.experience_observation()
                || experience.evidence_digest != material.provenance_digest()
            {
                return Err(invalid("same original Experience and Dataset material"));
            }
            (
                experience_prefix(config, experience)?,
                material.dataset_observation(),
                &config.initial.owners.dataset,
            )
        }
    };
    let receipt = LearningIterationReceiptV1 {
        operation_id: config.initial.request.operation_id.clone(),
        predecessor: prefix.head_digest,
        actor_id: actor.clone(),
        evidence_digest: material.provenance_digest(),
        observed_unix_seconds: at,
        observation,
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix)?;
    coordinator.record(receipt.clone(), at)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}

pub(super) fn dataset_saved(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    binding: Digest32,
    experience: &OriginalCellQ24MaterialCompletionV1,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let payload = learning_iteration_receipt_signing_bytes_v1(&experience.receipt)?;
    let mut signature = experience.attestation.signing_bytes();
    signature.extend_from_slice(&experience.attestation.signature);
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: config.initial.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-q24-dataset-receipt.v1\0",
            binding.as_array(),
            Digest32::of_bytes(&payload).as_array(),
            Digest32::of_bytes(&signature).as_array(),
        ]),
    })
}

fn evidence_id(binding: Digest32) -> Result<StableId, LearningOriginalOwnerErrorV1> {
    StableId::new(format!("original-material:{binding}"))
        .map_err(|_| owner_invalid("original material evidence id"))
}

fn expires_at(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    signer: &TrustedLearningSignerV1,
    issued_at: u64,
) -> Result<u64, LearningOriginalOwnerErrorV1> {
    Ok(issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or_else(|| owner_invalid("original material signature deadline overflow"))?
        .min(signer.principal.expires_at)
        .min(config.freeze_evidence.expires_at))
}

pub(super) fn signed_bytes(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    signer: &TrustedLearningSignerV1,
    key: &SigningKey,
    receipt: &LearningIterationReceiptV1,
    binding: Digest32,
) -> Result<Vec<u8>, LearningOriginalOwnerErrorV1> {
    let issued_at = receipt.observed_unix_seconds;
    require_freeze_window(config, issued_at)?;
    config
        .verifier
        .require_signer_binding(LearningEvidenceRoleV1::Observer, signer, issued_at)?;
    let payload = learning_iteration_receipt_signing_bytes_v1(receipt)
        .map_err(|_| owner_invalid("original material receipt bytes"))?;
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(binding)?,
        principal_id: signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: config.verifier.trust_digest(),
        scope_digest: config.verifier.scope_digest(),
        objective_digest: config.verifier.objective_digest(),
        authority_epoch: signer.principal.authority_epoch,
        issued_at,
        expires_at: expires_at(config, signer, issued_at)?,
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

pub(super) fn verify_original(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    signer: &TrustedLearningSignerV1,
    receipt: &LearningIterationReceiptV1,
    signed: &SignedLearningEvidenceV1,
    binding: Digest32,
    at: u64,
) -> Result<(), Error> {
    require_freeze_window(config, at)?;
    let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
    let verified =
        config
            .verifier
            .verify(LearningEvidenceRoleV1::Observer, signed, &payload, at)?;
    if verified.principal() != &signer.principal
        || verified.controller_id() != &signer.controller_id
        || signed.evidence_id != evidence_id(binding)?
        || signed.issued_at != receipt.observed_unix_seconds
        || signed.expires_at != expires_at(config, signer, signed.issued_at)?
        || signed.principal_id != receipt.actor_id
    {
        return Err(invalid("exact original Observer signature and window"));
    }
    Ok(())
}
