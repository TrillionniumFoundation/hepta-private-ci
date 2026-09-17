use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn binding(baseline_squared_l2_raw_q64: u128) -> ParameterEvidenceBindingV3 {
    ParameterEvidenceBindingV3 {
        selected_artifact_id: id("artifact:parameters:7"),
        selected_artifact_digest: digest("artifact-content"),
        objective_digest: digest("objective"),
        window: ProposalWindowV2 {
            window_id: id("window:8"),
            window_digest: digest("window"),
        },
        baseline_generation: generation(7),
        candidate_generation: generation(8),
        dataset_digest: digest("dataset"),
        update_rule_digest: digest("update-rule"),
        modulator_digest: digest("modulator"),
        modulator_broadcast_digest: digest("modulator-broadcast"),
        eligibility_digest: digest("eligibility"),
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:a"),
            baseline_squared_l2_raw_q64,
        }],
        opportunities: vec![ParameterOpportunityV3 {
            layer_id: id("layer:a"),
            parameter_id: id("parameter:a"),
            eligibility: FixedQ32::ONE,
            projected_modulator: FixedQ32::ONE,
            lower_bound: FixedQ32::from_raw(-1_000_000),
            upper_bound: FixedQ32::from_raw(1_000_000),
            evidence_digest: digest("parameter-evidence"),
        }],
    }
}

fn policy(learning_rate_raw: i64) -> ParameterGenerationPolicyV3 {
    ParameterGenerationPolicyV3 {
        generator_id: id("learning.plasticity.generator"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: digest("grammar"),
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        learning_rate: FixedQ32::from_raw(learning_rate_raw),
        candidate_scales_ppm: vec![500_000, 1_000_000],
    }
}

#[test]
fn governed_generator_builds_complete_content_addressed_candidate_set() {
    let generated = generate_parameter_candidates_v3(
        &binding(1_000_000_000_000),
        &policy(100),
        digest("state"),
    )
    .expect("generated candidate set");

    assert_eq!(generated.candidates.len(), 3);
    assert_eq!(generated.completeness.candidate_count, 3);
    assert_eq!(generated.completeness.omitted_count_bound, 0);
    assert!(generated.completeness.complete_for_generator);
    assert_eq!(
        generated.completeness.set_id,
        candidate_set_id_v3(generated.candidate_set_digest).expect("content-addressed id")
    );
    assert_eq!(generated.candidates[0].kind, ParameterCandidateKindV2::NoChange);
    assert_eq!(
        generated.candidates[1].candidate_id,
        id("plasticity:update:0500000")
    );
    assert_eq!(
        generated.candidates[2].candidate_id,
        id("plasticity:update:1000000")
    );
    assert_eq!(generated.candidates[1].parameter_deltas[0].delta.raw(), 50);
    assert_eq!(generated.candidates[2].parameter_deltas[0].delta.raw(), 100);
}

#[test]
fn governed_generator_projects_large_updates_into_trust_region() {
    let generated = generate_parameter_candidates_v3(
        &binding(1_000_000_000_000),
        &policy(100_000),
        digest("state"),
    )
    .expect("projected candidate set");

    for candidate in generated
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
    {
        let raw = candidate.parameter_deltas[0].delta.raw().unsigned_abs();
        assert!(
            raw <= 5_000,
            "per-layer trust projection must be conservative"
        );
    }
}

#[test]
fn source_binding_payload_is_order_invariant() {
    let mut left = binding(1_000_000_000_000);
    left.norm_layers.push(LayerNormDenominatorV2 {
        layer_id: id("layer:b"),
        baseline_squared_l2_raw_q64: 2_000_000_000_000,
    });
    left.opportunities.push(ParameterOpportunityV3 {
        layer_id: id("layer:b"),
        parameter_id: id("parameter:b"),
        eligibility: FixedQ32::ONE,
        projected_modulator: FixedQ32::ONE,
        lower_bound: FixedQ32::from_raw(-1_000_000),
        upper_bound: FixedQ32::from_raw(1_000_000),
        evidence_digest: digest("parameter-evidence-b"),
    });
    let mut right = left.clone();
    right.norm_layers.reverse();
    right.opportunities.reverse();

    let left_payload = evidence_binding_signing_payload_v3(
        &left,
        digest("artifact-registry-head"),
        &id("dataset-snapshot"),
    )
    .expect("left payload");
    let right_payload = evidence_binding_signing_payload_v3(
        &right,
        digest("artifact-registry-head"),
        &id("dataset-snapshot"),
    )
    .expect("right payload");
    assert_eq!(left_payload, right_payload);
}

#[test]
fn governed_generator_rejects_duplicate_parameter_opportunities() {
    let mut value = binding(1_000_000_000_000);
    value.opportunities.push(value.opportunities[0].clone());
    assert!(matches!(
        generate_parameter_candidates_v3(&value, &policy(100), digest("state")),
        Err(GovernedProposalError::Generator(
            "duplicate parameter opportunity"
        ))
    ));
}
