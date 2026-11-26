use super::*;
use codex_hepta_agent_components::plasticity::*;
fn shape(f: &DynamicFixture) -> crate::AgentdPlasticityAdmissionInputV1 {
    let q = dynamic_query(
        f,
        PlasticityOwnerEvidenceKindV1::Eligibility,
        f.eligibility_digest,
    );
    let profile = ParameterGeneratorProfileV3 {
        selected_artifact_digest: q.selected_artifact_digest,
        window: q.window.clone(),
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:dynamic"),
            baseline_squared_l2_raw_q64: 1_u128 << 64,
        }],
        mutation_policy: build_parameter_mutation_policy_v1(
            id("policy:prepare"),
            digest("grammar"),
            q.selected_artifact_digest,
            q.window,
            vec![ParameterMutationRuleV1 {
                parameter_id: id("parameter:dynamic"),
                layer_id: id("layer:dynamic"),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: f.lower_bound,
                maximum_delta: f.upper_bound,
            }],
        )
        .expect("original declared search policy"),
        update_scales: vec![FixedQ32::ONE],
        signals: vec![ParameterPlasticitySignalV3 {
            layer_id: id("layer:dynamic"),
            parameter_id: id("parameter:dynamic"),
            eligibility: FixedQ32::ZERO,
            modulator: FixedQ32::ZERO,
            learning_rate: f.learning_rate,
            lower_bound: f.lower_bound,
            upper_bound: f.upper_bound,
            evidence_digest: digest("caller placeholder"),
        }],
    };
    crate::AgentdPlasticityAdmissionInputV1 {
        baseline_id: id("baseline"),
        objective_digest: digest("objective"),
        generated: generate_parameter_candidates_v3(profile.clone()).expect("unsigned shape"),
        generator_profile: profile,
        baseline_generation: Generation::new(1).expect("generation"),
        candidate_generation: Generation::new(2).expect("generation"),
        dataset_digest: f.dataset_digest,
        update_rule_digest: digest("update"),
        modulator_digest: Digest32::ZERO,
        modulator_broadcast_digest: Digest32::ZERO,
        eligibility_digest: Digest32::ZERO,
    }
}
#[test]
fn actual_ndu_and_acknowledged_checkpoint_replace_unsigned_shape_signal_values() {
    let f = dynamic_fixture();
    let shape = shape(&f);
    let before_ndu = f.ndu.read().expect("owner").entries().len();
    let before_checkpoint = f
        .neuron
        .lock()
        .expect("owner")
        .current()
        .expect("current")
        .expect("actual checkpoint")
        .digest();
    let result = f
        .resolver
        .prepare_parameter_input(shape.clone(), 50)
        .expect("actual owner input");
    let signal = &result.generator_profile.signals[0];
    assert_eq!(signal.eligibility, f.eligibility);
    assert_eq!(signal.modulator, f.modulator);
    assert_eq!(signal.evidence_digest, f.signal_digest);
    assert_eq!(result.modulator_digest, f.modulator_digest);
    assert_eq!(result.modulator_broadcast_digest, f.broadcast_digest);
    assert_eq!(result.eligibility_digest, f.eligibility_digest);
    assert_eq!(
        signal.learning_rate,
        shape.generator_profile.signals[0].learning_rate
    );
    assert_ne!(
        result.generated.generator_digest,
        shape.generated.generator_digest
    );
    assert_eq!(f.ndu.read().expect("owner").entries().len(), before_ndu);
    assert_eq!(
        f.neuron
            .lock()
            .expect("owner")
            .current()
            .expect("current")
            .expect("checkpoint")
            .digest(),
        before_checkpoint
    );
}
#[test]
fn expired_or_foreign_objective_current_input_is_not_prepared() {
    let f = dynamic_fixture();
    let shape = shape(&f);
    assert!(
        f.resolver
            .prepare_parameter_input(shape.clone(), 60)
            .is_err()
    );
    let mut foreign = shape;
    foreign.objective_digest = digest("other training objective");
    assert_eq!(
        f.resolver.prepare_parameter_input(foreign, 50),
        Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
    );
}
#[test]
fn changed_actual_ndu_selection_cannot_be_replaced_by_shape_claims() {
    let f = dynamic_fixture();
    let shape = shape(&f);
    let mut journal = f.ndu.write().expect("actual NDU owner");
    let other = digest("other selected actual modulator");
    journal
        .append_projection(
            NduProjectionKindV1::Utility,
            digest("fresh projection"),
            digest("objective"),
            digest("agent:subject"),
            other,
        )
        .expect("original append");
    journal
        .select_projection(
            digest("fresh selection"),
            digest("objective"),
            digest("agent:subject"),
            other,
        )
        .expect("original selection");
    drop(journal);
    assert_eq!(
        f.resolver.prepare_parameter_input(shape, 50),
        Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
    );
}
