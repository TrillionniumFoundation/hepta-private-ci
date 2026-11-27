//! Exact original source/Cell projection and a separate witnessed signing
//! namespace. Historical accepted evidence never authorizes a fresh append.

use codex_hepta_neuron::CellDecisionReceiptV1;
use ed25519_dalek::Signer;

use super::*;

pub(super) fn require_original_signers(
    ledger: &LedgerWriter,
    config: &OriginalCellQ24TaskLedgerConfigV1,
) -> Result<(), Error> {
    let observed = now()?;
    for (role, signer) in [
        (LearningEvidenceRoleV1::Generator, &config.generator),
        (LearningEvidenceRoleV1::Observer, &config.observer),
    ] {
        // Historical enrollment equality never renews a role's validity.
        // Current expiry is rechecked by each new original ledger append.
        ledger.verifier().require_signer_binding(
            role,
            signer,
            signer.principal.authenticated_at,
        )?;
        if signer.revoked_at.is_some_and(|at| observed >= at) {
            return Err(SignedEvidenceError::Revoked.into());
        }
    }
    Ok(())
}

pub(super) fn configuration(
    inputs: &OriginalCellQ24TaskLedgerInputsV1,
    ledger: &LedgerWriter,
    published: &PublishedCircuitFeatureTaskV1,
    identity: &AgentdIdentity,
) -> Result<Digest32, Error> {
    let config = &inputs.config;
    if inputs.generator_key.verifying_key().to_bytes() != config.generator.verifying_key
        || ledger.verifier().objective_digest() != published.source().objective_digest
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
        || config.outcome_record_id == published.source().scope.run_id
    {
        return Err(Error::Binding(
            "original Generator, outcome or source configuration",
        ));
    }
    require_original_signers(ledger, config)?;
    if inputs.open_mode == CircuitQ24TaskOpenModeV1::Create {
        ledger.verifier().require_signer_binding(
            LearningEvidenceRoleV1::Generator,
            &config.generator,
            now()?,
        )?;
        if now()? >= config.claim_deadline_unix_seconds {
            return Err(Error::Binding("new original Generator claim deadline"));
        }
    }
    let task = crate::circuit_feature_task_digest_v1(published.definition(), published.source())
        .map_err(|_| Error::Binding("original published task"))?;
    super::projection::configuration_digest(
        config,
        task,
        ledger.binding_digest(),
        ledger.verifier().trust_digest(),
        identity,
    )
}

pub(super) fn decision(
    config: &OriginalCellQ24TaskLedgerConfigV1,
    published: &PublishedCircuitFeatureTaskV1,
    publication: &CircuitTaskSourcePublicationV1,
    original: &CellDecisionReceiptV1,
) -> Result<ProductionDecisionV2, Error> {
    super::projection::decision(
        config,
        published.definition(),
        published.source(),
        publication,
        original,
    )
}

pub(super) fn sign(
    owner: &OriginalCellQ24TaskLedgerProducerV1,
    ledger: &LedgerWriter,
    key: &SigningKey,
    payload: &[u8],
) -> Result<SignedLearningEvidenceV1, Error> {
    let observed = now()?;
    if observed >= owner.config.claim_deadline_unix_seconds {
        return Err(Error::Binding("original Generator claim deadline"));
    }
    let verifier = ledger.verifier();
    verifier.require_signer_binding(
        LearningEvidenceRoleV1::Generator,
        &owner.config.generator,
        observed,
    )?;
    let expires_at = observed
        .checked_add(owner.config.maximum_signature_lifetime_seconds)
        .ok_or(Error::Binding("original Generator signature lifetime"))?
        .min(owner.config.generator.principal.expires_at);
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: owner.decision_key.plan_id.clone(),
        principal_id: owner.config.generator.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: observed,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &signed,
        payload,
        observed,
    )?;
    Ok(signed)
}

pub(super) fn decision_event(
    request: &ProductionDecisionV2,
    evidence: &SignedLearningEvidenceV1,
    generator: &TrustedLearningSignerV1,
) -> Result<LedgerEvent, Error> {
    // Reuse canonical completeness checks before constructing a comparison.
    decision_signing_payload_v2(request)?;
    let principal = &generator.principal;
    Ok(LedgerEvent::AuthenticatedDecisionV2(
        AuthenticatedDecisionRecordV2 {
            record_id: request.record_id.clone(),
            episode_id: request.episode_id.clone(),
            run_snapshot_digest: request.run_snapshot_digest,
            objective_digest: request.objective_digest,
            policy_digest: request.policy_digest,
            generator_id: principal.principal_id.clone(),
            generator_controller_id: generator.controller_id.clone(),
            generator_credential_chain_digest: principal.credential_chain_digest,
            generator_signing_key_digest: principal.signing_key_digest,
            generator_scope_digest: principal.scope_digest,
            generator_authority_epoch: principal.authority_epoch,
            candidate_ids: request.candidate_ids.clone(),
            selected_candidate_id: request.selected_candidate_id.clone(),
            selected_propensity: request.selected_propensity,
            candidate_completeness_digest: validate_candidate_set_completeness(
                &request.completeness,
            )?,
            support_digest: request.support_digest,
            authentication_digest: authentication_digest(evidence),
        },
    ))
}

pub(super) fn authentication_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    Digest32::of_parts(&[&evidence.signing_bytes(), &evidence.signature])
}

pub(super) fn encode(
    predecessor: Digest32,
    payload: &[u8],
    signed: &SignedLearningEvidenceV1,
) -> Result<Vec<u8>, LearningOriginalOwnerErrorV1> {
    let mut bytes = b"HQ24L001".to_vec();
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&learning_owner_evidence::encode(payload, signed)?);
    Ok(bytes)
}

pub(super) fn decode(bytes: &[u8]) -> Result<(Digest32, Vec<u8>, SignedLearningEvidenceV1), Error> {
    if bytes.len() < 40 || &bytes[..8] != b"HQ24L001" {
        return Err(Error::Binding("original task ledger signature namespace"));
    }
    let predecessor = Digest32::from_array(
        bytes[8..40]
            .try_into()
            .map_err(|_| Error::Binding("original task ledger predecessor"))?,
    );
    let (payload, signed) = learning_owner_evidence::decode(&bytes[40..])?;
    Ok((predecessor, payload, signed))
}
