use super::*;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_types::StableId;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}
fn original_tuple() -> TestResult<(ArtifactManifest, PlasticityAdmissionEvidenceV1)> {
    let selected = ArtifactManifest {
        artifact_id: StableId::new("parameters.head.generation-two")?,
        kind: ArtifactKind::Parameters,
        generation: Generation::new(2)?,
        predecessor_id: Some(StableId::new("parameters.head.generation-one")?),
        content_digest: digest("actual parameter head, distinct from weights"),
        objective_digest: digest("original training objective"),
        support_digest: digest("original independent support"),
        producer_id: StableId::new("original-parameter-generator")?,
        compatibility_digest: digest("original parameter binding"),
        encoded_size_bytes: 64,
    };
    let admission = PlasticityAdmissionEvidenceV1 {
        baseline_id: selected.artifact_id.clone(),
        objective_digest: selected.objective_digest,
        selected_artifact_digest: selected.content_digest,
        artifact_registry_binding: selected.compatibility_digest,
        artifact_registry_head_digest: digest("original whole current registry head"),
        qualification_evidence_head_digest: digest("original qualification ledger"),
        owner_evidence_set_digest: digest("seven original owner receipts"),
        window: ProposalWindowV2 {
            window_id: StableId::new("original-training-window")?,
            window_digest: digest("original training window"),
        },
        baseline_generation: selected.generation,
        candidate_generation: selected.generation.next()?,
        dataset_digest: digest("original training dataset"),
        update_rule_digest: digest("original update rule"),
        modulator_digest: digest("original modulator"),
        modulator_broadcast_digest: digest("original broadcast"),
        eligibility_digest: digest("original eligibility"),
        generator_digest: digest("original deterministic generator"),
    };
    Ok((selected, admission))
}

#[test]
fn selected_parameter_head_is_independent_from_stable_model_id_and_weight_artifact() -> TestResult {
    let (selected, admission) = original_tuple()?;
    let model_id = StableId::new("stable-operational-model")?;
    assert_ne!(model_id, admission.baseline_id);
    validate_selected_tuple(
        &selected,
        &admission,
        selected.content_digest,
        selected.generation,
        selected.objective_digest,
        admission.artifact_registry_head_digest,
    )?;

    // The registered operational Model is genuinely eligible separately, but
    // its weights are not this generation's original parameter head.
    let mut weights = selected.clone();
    weights.artifact_id = model_id;
    weights.kind = ArtifactKind::Model;
    weights.content_digest = digest("actual independent operational weights");
    let mut claimed = admission.clone();
    claimed.baseline_id = weights.artifact_id.clone();
    claimed.selected_artifact_digest = weights.content_digest;
    assert!(
        validate_selected_tuple(
            &weights,
            &claimed,
            selected.content_digest,
            selected.generation,
            selected.objective_digest,
            admission.artifact_registry_head_digest,
        )
        .is_err()
    );

    // Preserve the original owner contract: a Model whose content actually IS
    // the parameter head is permitted; its kind alone does not mint authority.
    let mut model_head = selected.clone();
    model_head.kind = ArtifactKind::Model;
    validate_selected_tuple(
        &model_head,
        &admission,
        selected.content_digest,
        selected.generation,
        selected.objective_digest,
        admission.artifact_registry_head_digest,
    )?;
    Ok(())
}

#[test]
fn foreign_generation_objective_kind_binding_or_current_head_cannot_reuse_admission() -> TestResult
{
    let (selected, admission) = original_tuple()?;
    let mut foreign = Vec::new();
    let mut changed = selected.clone();
    changed.kind = ArtifactKind::Policy;
    foreign.push(changed);
    let mut changed = selected.clone();
    changed.artifact_id = StableId::new("another-eligible-head")?;
    foreign.push(changed);
    let mut changed = selected.clone();
    changed.generation = Generation::new(1)?;
    foreign.push(changed);
    let mut changed = selected.clone();
    changed.objective_digest = digest("another objective");
    foreign.push(changed);
    let mut changed = selected.clone();
    changed.compatibility_digest = digest("another parameter binding");
    foreign.push(changed);
    for changed in foreign {
        assert!(
            validate_selected_tuple(
                &changed,
                &admission,
                selected.content_digest,
                selected.generation,
                selected.objective_digest,
                admission.artifact_registry_head_digest,
            )
            .is_err()
        );
    }
    assert!(
        validate_selected_tuple(
            &selected,
            &admission,
            selected.content_digest,
            selected.generation,
            selected.objective_digest,
            digest("changed CURRENT after preparation"),
        )
        .is_err()
    );
    Ok(())
}
