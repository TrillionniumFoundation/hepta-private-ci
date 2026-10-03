//! Public synthetic evidence exercises the original verifier, never role custody.
use super::*;
use crate::paired_supervised_test_support::{SigningFixture, digest, id};
use codex_hepta_types::{FixedQ32, Generation};

fn profile() -> ParameterGeneratorProfileV3 {
    let artifact = digest("artifact");
    let window = ProposalWindowV2 {
        window_id: id("window"),
        window_digest: digest("window"),
    };
    ParameterGeneratorProfileV3 {
        selected_artifact_digest: artifact,
        window: window.clone(),
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer"),
            baseline_squared_l2_raw_q64: 1_u128 << 64,
        }],
        mutation_policy: build_parameter_mutation_policy_v1(
            id("policy"),
            digest("grammar"),
            artifact,
            window,
            vec![ParameterMutationRuleV1 {
                parameter_id: id("parameter"),
                layer_id: id("layer"),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
                maximum_delta: FixedQ32::from_raw(1_i64 << 24),
            }],
        )
        .unwrap(),
        update_scales: vec![FixedQ32::ONE],
        signals: vec![ParameterPlasticitySignalV3 {
            layer_id: id("layer"),
            parameter_id: id("parameter"),
            eligibility: FixedQ32::ZERO,
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::from_raw(1_i64 << 20),
            lower_bound: FixedQ32::from_raw(-(1_i64 << 24)),
            upper_bound: FixedQ32::from_raw(1_i64 << 24),
            evidence_digest: digest("eligibility"),
        }],
    }
}

#[test]
fn request_codec_preserves_the_actual_round_and_refuses_no_change_for_update() {
    let fixture = SigningFixture::new(false);
    let mut profile = profile();
    let admission = admission(&profile);
    let generated = no_change(&profile, &admission).unwrap();
    let g = fixture.sign(0, &parameter_generator_signing_payload_v3(&generated), 50);
    let o = fixture.sign(1, &plasticity_admission_signing_payload_v1(&admission), 50);
    let round = ParameterEvaluationRoundBindingV1 {
        round_identity_digest: digest("actual.round"),
        round_payload_digest: digest("actual.full.round"),
        canonical_policy_digest: digest("installed.window"),
        execution_envelope_digest: digest("exact.execution"),
        admitted_at_ms: 10,
        deadline_ms: 950,
    };
    let bytes =
        encode_fixed_parameter_role_inputs_v1(&round, &profile, &admission, &g, &o, None).unwrap();
    let decoded: crate::fixed_parameter_no_change_host::Inputs =
        serde_json::from_slice(&bytes).unwrap();
    assert_eq!(
        decoded.round_payload_digest,
        round.round_payload_digest.to_string()
    );
    assert_eq!(decoded.generator_evidence.native().unwrap(), g);
    assert_eq!(decoded.observer_evidence.native().unwrap(), o);
    assert_eq!(
        decode_untrusted_parameter_generator_profile_v3(
            &unhex(&decoded.profile_hex, MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1).unwrap()
        )
        .unwrap(),
        profile
    );
    let mut wrong = round.clone();
    wrong.round_payload_digest = Digest32::from_array([0; 32]);
    assert!(
        encode_fixed_parameter_role_inputs_v1(&wrong, &profile, &admission, &g, &o, None).is_err()
    );
    profile.signals[0].eligibility = codex_hepta_types::FixedQ32::ONE;
    let generated = generate_parameter_candidates_v3(profile.clone()).unwrap();
    let mut admission = admission;
    admission.generator_digest = generated.generator_digest;
    let g = fixture.sign(0, &parameter_generator_signing_payload_v3(&generated), 50);
    let o = fixture.sign(1, &plasticity_admission_signing_payload_v1(&admission), 50);
    assert!(
        encode_fixed_parameter_role_inputs_v1(&round, &profile, &admission, &g, &o, None).is_err()
    );
    let candidate = &generated
        .candidates
        .iter()
        .find(|c| c.kind == ParameterCandidateKindV2::Update)
        .unwrap()
        .candidate_id;
    let bytes = encode_fixed_parameter_role_inputs_v1(
        &round,
        &profile,
        &admission,
        &g,
        &o,
        Some(candidate),
    )
    .unwrap();
    let decoded: crate::fixed_parameter_no_change_host::Inputs =
        serde_json::from_slice(&bytes).unwrap();
    assert_eq!(decoded.candidate_id.as_deref(), Some(candidate.as_str()));
    assert!(
        encode_fixed_parameter_role_inputs_v1(
            &round,
            &profile,
            &admission,
            &g,
            &o,
            Some(&id("unmeasured.foreign.candidate"))
        )
        .is_err()
    );
}

fn admission(profile: &ParameterGeneratorProfileV3) -> PlasticityAdmissionEvidenceV1 {
    PlasticityAdmissionEvidenceV1 {
        baseline_id: id("baseline"),
        objective_digest: digest("paired-objective"),
        selected_artifact_digest: profile.selected_artifact_digest,
        artifact_registry_binding: digest("actual.registry.binding"),
        artifact_registry_head_digest: digest("actual.registry.head"),
        qualification_evidence_head_digest: digest("actual.evidence.head"),
        owner_evidence_set_digest: digest("actual.seven.owner.inputs"),
        window: profile.window.clone(),
        baseline_generation: Generation::new(1).unwrap(),
        candidate_generation: Generation::new(2).unwrap(),
        dataset_digest: digest("dataset"),
        update_rule_digest: digest("rule"),
        modulator_digest: digest("modulator"),
        modulator_broadcast_digest: digest("broadcast"),
        eligibility_digest: digest("eligibility"),
        generator_digest: generate_parameter_candidates_v3(profile.clone())
            .unwrap()
            .generator_digest,
    }
}
fn output(
    fixture: &SigningFixture,
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    observer: &SignedLearningEvidenceV1,
) -> Vec<u8> {
    let generated = no_change(profile, admission).unwrap();
    let e = fixture.sign(
        2,
        &no_change_disposition_signing_payload_v1(&generated, admission).unwrap(),
        90,
    );
    let publication = serde_json::to_vec(&Publication {
        schema: "hepta.parameter.no-admissible-update.v1".to_owned(),
        profile_digest: Digest32::of_bytes(
            &encode_untrusted_parameter_generator_profile_v3(profile).unwrap(),
        )
        .to_string(),
        generator_digest: generated.generator_digest.to_string(),
        admission_digest: Digest32::of_bytes(&plasticity_admission_signing_payload_v1(admission))
            .to_string(),
        evaluator_evidence: ReviewEvidenceWireV1::from_native(&e),
    })
    .unwrap();
    let facts = SelfIterationPreparationFactsV1 {
        disposition: SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
        round_identity_digest: digest("original.round.identity"),
        round_payload_digest: digest("original.round.whole"),
        canonical_policy_digest: digest("installed.canonical"),
        execution_envelope_digest: digest("execution.envelope"),
        enrolled_inputs_digest: digest("immutable.inputs"),
        generated_digest: generated.generator_digest,
        admission_digest: Digest32::of_bytes(&plasticity_admission_signing_payload_v1(admission)),
        generator_evidence_digest: evidence_digest(generator),
        observer_evidence_digest: evidence_digest(observer),
        evaluation_publication_digest: Digest32::of_bytes(&publication),
        admitted_at_ms: 10,
        deadline_ms: 950,
        observed_at_ms: 100,
    };
    let signed = fixture.sign(
        2,
        &self_iteration_preparation_terminal_signing_payload_v1(&facts).unwrap(),
        100,
    );
    let terminal = encode_self_iteration_preparation_terminal_v1(&facts, &signed).unwrap();
    serde_json::to_vec(&Output {
        schema: "hepta.parameter.no-change-output.v1".to_owned(),
        publication_hex: hex(&publication),
        preparation_terminal_hex: hex(&terminal),
    })
    .unwrap()
}
#[test]
fn actual_complete_frontier_and_both_original_e_purposes_are_required() {
    let fixture = SigningFixture::new(false);
    let profile = profile();
    let admission = admission(&profile);
    let generated = no_change(&profile, &admission).unwrap();
    let g = fixture.sign(0, &parameter_generator_signing_payload_v3(&generated), 50);
    let o = fixture.sign(1, &plasticity_admission_signing_payload_v1(&admission), 50);
    let bytes = output(&fixture, &profile, &admission, &g, &o);
    let result = decode_fixed_parameter_no_change_output_v1(
        &bytes,
        &profile,
        &admission,
        &g,
        &o,
        &fixture.trust,
        100,
    )
    .unwrap();
    assert_eq!(
        result.preparation_facts.generated_digest,
        generated.generator_digest
    );
    assert_eq!(
        result.preparation_facts.evaluation_publication_digest,
        Digest32::of_bytes(&result.publication_bytes)
    );
    assert_eq!(
        result.no_change_attestation.payload_digest,
        Digest32::of_bytes(
            &no_change_disposition_signing_payload_v1(&generated, &admission).unwrap()
        )
    );
    let mut changed = profile.clone();
    changed.signals[0].eligibility = FixedQ32::ONE;
    assert!(
        generate_parameter_candidates_v3(changed.clone())
            .unwrap()
            .candidates
            .iter()
            .any(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
    );
    assert!(no_change(&changed, &admission).is_err());
    let mut foreign = admission.clone();
    foreign.eligibility_digest = digest("other physical eligibility");
    assert!(
        decode_fixed_parameter_no_change_output_v1(
            &bytes,
            &profile,
            &foreign,
            &g,
            &o,
            &fixture.trust,
            100
        )
        .is_err()
    );
    let mut wrong_g = g.clone();
    wrong_g.signature[0] ^= 1;
    assert!(
        decode_fixed_parameter_no_change_output_v1(
            &bytes,
            &profile,
            &admission,
            &wrong_g,
            &o,
            &fixture.trust,
            100
        )
        .is_err()
    );
    assert!(
        decode_fixed_parameter_no_change_output_v1(
            &bytes,
            &profile,
            &admission,
            &g,
            &o,
            &fixture.trust,
            901
        )
        .is_err()
    );
    let mut outer: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    outer["publication_hex"] = serde_json::Value::String(hex(b"partial original E report"));
    assert!(
        decode_fixed_parameter_no_change_output_v1(
            &serde_json::to_vec(&outer).unwrap(),
            &profile,
            &admission,
            &g,
            &o,
            &fixture.trust,
            100
        )
        .is_err()
    );
    let oversized = vec![b' '; MAX_NO_CHANGE_OUTPUT_BYTES + 1];
    assert!(
        decode_fixed_parameter_no_change_output_v1(
            &oversized,
            &profile,
            &admission,
            &g,
            &o,
            &fixture.trust,
            100
        )
        .is_err()
    );
}
#[test]
fn shared_actual_controller_cannot_issue_independent_no_change() {
    let fixture = SigningFixture::new(true);
    let profile = profile();
    let admission = admission(&profile);
    let generated = no_change(&profile, &admission).unwrap();
    let g = fixture.sign(0, &parameter_generator_signing_payload_v3(&generated), 50);
    let o = fixture.sign(1, &plasticity_admission_signing_payload_v1(&admission), 50);
    let bytes = output(&fixture, &profile, &admission, &g, &o);
    assert!(
        decode_fixed_parameter_no_change_output_v1(
            &bytes,
            &profile,
            &admission,
            &g,
            &o,
            &fixture.trust,
            100
        )
        .is_err()
    );
}
