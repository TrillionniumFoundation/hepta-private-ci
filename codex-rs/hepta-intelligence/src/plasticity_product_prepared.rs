//! One original governed preparation shared by append and completed observation.
use super::*;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
pub(super) struct Prepared {
    pub(super) proposal: ParameterProposalV2,
    pub(super) participants: Vec<VerifiedLearningEvidenceV1>,
    pub(super) disposition: ParameterPlasticityDispositionV1,
    pub(super) generator_authentication_digest: Digest32,
    pub(super) admission_authentication_digest: Digest32,
    pub(super) evaluation_digest: Digest32,
}
pub(super) fn prepare(
    request: &ParameterPlasticityProductRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<Prepared, ParameterPlasticityProductErrorV1> {
    use ParameterPlasticityProductErrorV1 as E;
    verify_generated_parameter_candidates_v3(
        request.generator_profile.clone(),
        &request.generated,
    )?;
    validate_admission_binding(request)?;

    let generator_payload = parameter_generator_signing_payload_v3(&request.generated);
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &request.generator_attestation,
            &generator_payload,
            now,
        )
        .map_err(E::GeneratorEvidence)?;
    let admission_payload = plasticity_admission_signing_payload_v1(&request.admission);
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &request.admission_attestation,
            &admission_payload,
            now,
        )
        .map_err(E::AdmissionEvidence)?;
    verify_signed_role_separation(&generator, &observer, now).map_err(E::AdmissionEvidence)?;
    let mut participants = vec![generator.clone(), observer.clone()];

    if request.generator_attestation.objective_digest != request.admission.objective_digest
        || request.admission_attestation.objective_digest != request.admission.objective_digest
    {
        return Err(E::Binding("objective trust context"));
    }

    let update_candidates = request
        .generated
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        .collect::<Vec<_>>();
    let disposition = if update_candidates.is_empty() {
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate
    } else {
        ParameterPlasticityDispositionV1::UpdateCandidates
    };

    let mut evaluations = BTreeMap::new();
    for evaluation in request.evaluations.iter().cloned() {
        let key = evaluation.bundle.candidate_id.clone();
        if evaluations.insert(key.clone(), evaluation).is_some() {
            return Err(E::DuplicateEvaluation(key.to_string()));
        }
    }

    let mut evaluator_id: Option<StableId> = None;
    let mut evaluation_binding = b"hepta.intelligence.plasticity-evaluations.v2\0".to_vec();

    if disposition == ParameterPlasticityDispositionV1::NoAdmissibleUpdate {
        if let Some(unexpected) = evaluations.keys().next() {
            return Err(E::UnexpectedEvaluation(unexpected.to_string()));
        }
        let attestation = request
            .no_change_attestation
            .as_ref()
            .ok_or(E::MissingNoChangeAttestation)?;
        let payload =
            no_change_disposition_signing_payload_v1(&request.generated, &request.admission)?;
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                attestation,
                &payload,
                now,
            )
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        verify_signed_independent_roles_v1(&observer, &evaluator, now)
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        verify_signed_independent_roles_v1(&generator, &evaluator, now)
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        if attestation.objective_digest != request.admission.objective_digest {
            return Err(E::Binding("no-change evaluation trust context"));
        }
        participants.push(evaluator.clone());
        evaluator_id = Some(evaluator.principal().principal_id.clone());
        evaluation_binding.extend_from_slice(&payload);
        evaluation_binding.extend_from_slice(attestation_digest(attestation).as_array());
        evaluation_binding.extend_from_slice(verifier.trust_digest().as_array());
    } else if request.no_change_attestation.is_some() {
        return Err(E::UnexpectedNoChangeAttestation);
    }

    for candidate in update_candidates {
        let candidate_id = candidate.candidate_id.clone();
        let CandidateEvaluationAdmissionV1 {
            bundle,
            metric_roles,
            evidence,
        } = evaluations
            .remove(&candidate_id)
            .ok_or_else(|| E::MissingEvaluation(candidate_id.to_string()))?;
        if bundle.candidate_id != candidate_id
            || bundle.baseline_id != request.admission.baseline_id
            || bundle.objective_digest != request.admission.objective_digest
            || bundle.dataset_digest != request.admission.dataset_digest
            || &bundle.generator != generator.principal()
        {
            return Err(E::Binding("candidate evaluation lineage"));
        }
        let this_evaluator = bundle.evaluator.principal_id.clone();
        if evaluator_id
            .as_ref()
            .is_some_and(|existing| existing != &this_evaluator)
        {
            return Err(E::EvaluatorMismatch);
        }
        evaluator_id.get_or_insert(this_evaluator);

        let evaluator_payload = evaluation_signing_payload_v2(&bundle, &metric_roles)
            .map_err(|error| E::Evaluation(error.into()))?;
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evaluator_bundle,
                &evaluator_payload,
                now,
            )
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        if evaluator.principal() != &bundle.evaluator {
            return Err(E::Evaluation(SignedEvaluationError::IdentityBinding));
        }
        verify_signed_independent_roles_v1(&observer, &evaluator, now)
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        verify_signed_independent_roles_v1(&generator, &evaluator, now)
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;

        let consumer_binding_digest = plasticity_evaluation_consumer_binding_digest(
            &request.proposal_id,
            &candidate_id,
            &request.admission,
            &request.generated,
            &evaluator_payload,
        );
        // Retain the authenticated generator-plan value for final use. The
        // existing V2 admission still checks exact bundle identities and the
        // original consumer binding; this introduces no raw DTO time shortcut.
        let plan_generator = verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &evidence.generator_plan,
                bundle.frozen_plan.plan_digest.as_array(),
                now,
            )
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        participants.push(plan_generator);
        participants.push(evaluator);
        let admission = admit_signed_eligibility_v2(
            bundle,
            metric_roles,
            &evidence,
            verifier,
            consumer_binding_digest,
            now,
        )
        .map_err(E::Admission)?;
        if admission.decision.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(E::Ineligible(admission.decision.decision.disposition));
        }
        push_id(&mut evaluation_binding, &candidate_id);
        evaluation_binding.extend_from_slice(consumer_binding_digest.as_array());
        evaluation_binding.extend_from_slice(admission.evidence_digest.as_array());
        evaluation_binding
            .extend_from_slice(admission.decision.decision.evidence_digest.as_array());
        evaluation_binding.extend_from_slice(admission.decision.authentication_digest.as_array());
        evaluation_binding.extend_from_slice(admission.decision.trust_digest.as_array());
    }
    if let Some(unexpected) = evaluations.keys().next() {
        return Err(E::UnexpectedEvaluation(unexpected.to_string()));
    }
    let evaluator_id = evaluator_id.ok_or(E::NoUpdateCandidate)?;
    let candidate_evaluation_digest = Digest32::of_bytes(&evaluation_binding);
    let generator_authentication_digest = attestation_digest(&request.generator_attestation);
    let admission_authentication_digest = attestation_digest(&request.admission_attestation);
    let mut governed_evaluation = b"hepta.intelligence.plasticity-governed-admission.v2\0".to_vec();
    governed_evaluation.push(match disposition {
        ParameterPlasticityDispositionV1::UpdateCandidates => 0,
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate => 1,
    });
    for digest in [
        candidate_evaluation_digest,
        generator_authentication_digest,
        admission_authentication_digest,
        request.admission.owner_evidence_set_digest,
        request.generated.generator_digest,
        verifier.trust_digest(),
    ] {
        governed_evaluation.extend_from_slice(digest.as_array());
    }
    let evaluation_digest = Digest32::of_bytes(&governed_evaluation);

    let proposal = propose_v2(ParameterProposalRequestV2 {
        proposal_id: request.proposal_id.clone(),
        proposer_id: generator.principal().principal_id.clone(),
        evaluator_id,
        selected_artifact_digest: request.generated.selected_artifact_digest,
        window: request.generated.window.clone(),
        baseline_generation: request.admission.baseline_generation,
        candidate_generation: request.admission.candidate_generation,
        dataset_digest: request.admission.dataset_digest,
        update_rule_digest: request.admission.update_rule_digest,
        modulator_digest: request.admission.modulator_digest,
        modulator_broadcast_digest: request.admission.modulator_broadcast_digest,
        eligibility_digest: request.admission.eligibility_digest,
        evaluation_digest,
        rollback_predecessor_digest: request.admission.selected_artifact_digest,
        norm_layers: request.generated.norm_layers.clone(),
        candidates: request.generated.candidates.clone(),
    })?;

    Ok(Prepared {
        proposal,
        participants,
        disposition,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
    })
}

#[allow(clippy::too_many_arguments)]
pub(super) fn receipt(
    proposal: ParameterProposalV2,
    registry: DurableProposalAppendReceiptV1,
    generator_digest: Digest32,
    generator_authentication_digest: Digest32,
    admission_authentication_digest: Digest32,
    evaluation_digest: Digest32,
    disposition: ParameterPlasticityDispositionV1,
    committed_registry_anchor: DurableRegistryAnchorV1,
) -> ParameterPlasticityProductReceiptV1 {
    let mut composition = b"hepta.intelligence.plasticity-composition.v1\0".to_vec();
    composition.push(match disposition {
        ParameterPlasticityDispositionV1::UpdateCandidates => 0,
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate => 1,
    });
    for digest in [
        proposal.proposal_digest,
        registry.frame_digest,
        committed_registry_anchor.frame_digest,
        generator_digest,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
    ] {
        composition.extend_from_slice(digest.as_array());
    }
    ParameterPlasticityProductReceiptV1 {
        proposal,
        registry,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
        disposition,
        committed_registry_anchor,
        composition_digest: Digest32::of_bytes(&composition),
    }
}
