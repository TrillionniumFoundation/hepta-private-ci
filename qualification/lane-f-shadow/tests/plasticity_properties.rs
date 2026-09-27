use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterCandidateRequestV2;
use codex_hepta_plasticity::ParameterGeneratorProfileV3;
use codex_hepta_plasticity::ParameterMutationPolicyV1;
use codex_hepta_plasticity::ParameterMutationRuleV1;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ParameterPlasticitySignalV3;
use codex_hepta_plasticity::ParameterProposalRequestV2;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::build_generator_coverage_receipt_v1;
use codex_hepta_plasticity::build_parameter_mutation_policy_v1;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
use codex_hepta_plasticity::propose_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn window() -> ProposalWindowV2 {
    ProposalWindowV2 {
        window_id: id("window:property"),
        window_digest: digest(b"window:property"),
    }
}

fn rules() -> Vec<ParameterMutationRuleV1> {
    vec![
        ParameterMutationRuleV1 {
            parameter_id: id("parameter:a"),
            layer_id: id("layer:a"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-1_000),
            maximum_delta: FixedQ32::from_raw(1_000),
        },
        ParameterMutationRuleV1 {
            parameter_id: id("parameter:b"),
            layer_id: id("layer:b"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-1_000),
            maximum_delta: FixedQ32::from_raw(1_000),
        },
    ]
}

fn policy(grammar: &[u8], reverse: bool) -> ParameterMutationPolicyV1 {
    let mut rules = rules();
    if reverse {
        rules.reverse();
    }
    build_parameter_mutation_policy_v1(
        id("policy:property"),
        digest(grammar),
        digest(b"artifact:property"),
        window(),
        rules,
    )
    .expect("policy")
}

fn signals() -> Vec<ParameterPlasticitySignalV3> {
    vec![
        ParameterPlasticitySignalV3 {
            layer_id: id("layer:a"),
            parameter_id: id("parameter:a"),
            eligibility: FixedQ32::from_raw(10),
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::ONE,
            lower_bound: FixedQ32::from_raw(-1_000),
            upper_bound: FixedQ32::from_raw(1_000),
            evidence_digest: digest(b"signal:a"),
        },
        ParameterPlasticitySignalV3 {
            layer_id: id("layer:b"),
            parameter_id: id("parameter:b"),
            eligibility: FixedQ32::from_raw(-8),
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::ONE,
            lower_bound: FixedQ32::from_raw(-1_000),
            upper_bound: FixedQ32::from_raw(1_000),
            evidence_digest: digest(b"signal:b"),
        },
    ]
}

fn profile(reverse: bool) -> ParameterGeneratorProfileV3 {
    let mut norm_layers = vec![
        LayerNormDenominatorV2 {
            layer_id: id("layer:a"),
            baseline_squared_l2_raw_q64: 10_000_000_000,
        },
        LayerNormDenominatorV2 {
            layer_id: id("layer:b"),
            baseline_squared_l2_raw_q64: 20_000_000_000,
        },
    ];
    let mut update_scales = vec![
        FixedQ32::ONE,
        FixedQ32::from_raw(FixedQ32::ONE.raw() / 2),
    ];
    let mut signals = signals();
    if reverse {
        norm_layers.reverse();
        update_scales.reverse();
        signals.reverse();
    }
    ParameterGeneratorProfileV3 {
        selected_artifact_digest: digest(b"artifact:property"),
        window: window(),
        norm_layers,
        mutation_policy: policy(b"grammar:property", reverse),
        update_scales,
        signals,
    }
}

fn proposal_request(
    mut norm_layers: Vec<LayerNormDenominatorV2>,
    mut candidates: Vec<ParameterCandidateRequestV2>,
    reverse: bool,
) -> ParameterProposalRequestV2 {
    if reverse {
        norm_layers.reverse();
        candidates.reverse();
        for candidate in &mut candidates {
            candidate.parameter_deltas.reverse();
        }
    }
    ParameterProposalRequestV2 {
        proposal_id: id("proposal:property"),
        proposer_id: id("generator:property"),
        evaluator_id: id("evaluator:property"),
        selected_artifact_digest: digest(b"artifact:property"),
        window: window(),
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        dataset_digest: digest(b"dataset:property"),
        update_rule_digest: digest(b"update-rule:property"),
        modulator_digest: digest(b"modulator:property"),
        modulator_broadcast_digest: digest(b"broadcast:property"),
        eligibility_digest: digest(b"eligibility:property"),
        evaluation_digest: digest(b"evaluation:property"),
        rollback_predecessor_digest: digest(b"artifact:property"),
        norm_layers,
        candidates,
    }
}

#[test]
fn generator_coverage_and_proposal_are_canonical_under_input_permutations() {
    let forward_profile = profile(false);
    let reverse_profile = profile(true);
    let forward = generate_parameter_candidates_v3(forward_profile.clone()).expect("forward");
    let reverse = generate_parameter_candidates_v3(reverse_profile.clone()).expect("reverse");
    assert_eq!(forward, reverse);

    let forward_coverage =
        build_generator_coverage_receipt_v1(&forward_profile, digest(b"owner-frontier"))
            .expect("coverage");
    let reverse_coverage =
        build_generator_coverage_receipt_v1(&reverse_profile, digest(b"owner-frontier"))
            .expect("coverage reverse");
    assert_eq!(forward_coverage, reverse_coverage);
    assert_eq!(
        forward_coverage.disposition,
        GeneratorCoverageDispositionV1::Complete
    );

    let canonical = propose_v2(proposal_request(
        forward.norm_layers.clone(),
        forward.candidates.clone(),
        false,
    ))
    .expect("canonical proposal");
    let permuted = propose_v2(proposal_request(
        forward.norm_layers,
        forward.candidates,
        true,
    ))
    .expect("permuted proposal");
    assert_eq!(canonical, permuted);
}

#[test]
fn every_coverage_fact_changes_the_bound_digest() {
    let base_profile = profile(false);
    let base = build_generator_coverage_receipt_v1(&base_profile, digest(b"owner-frontier"))
        .expect("base");

    let changed_frontier =
        build_generator_coverage_receipt_v1(&base_profile, digest(b"owner-frontier:new"))
            .expect("frontier");
    assert_ne!(base.coverage_digest, changed_frontier.coverage_digest);

    let mut changed_scale = base_profile.clone();
    changed_scale.update_scales[0] = FixedQ32::from_raw(FixedQ32::ONE.raw() / 4);
    let changed_scale =
        build_generator_coverage_receipt_v1(&changed_scale, digest(b"owner-frontier"))
            .expect("scale");
    assert_ne!(base.coverage_digest, changed_scale.coverage_digest);

    let mut changed_signal = base_profile.clone();
    changed_signal.signals[0].evidence_digest = digest(b"signal:a:new");
    let changed_signal =
        build_generator_coverage_receipt_v1(&changed_signal, digest(b"owner-frontier"))
            .expect("signal");
    assert_ne!(base.coverage_digest, changed_signal.coverage_digest);

    let mut changed_eligibility = base_profile.clone();
    changed_eligibility.signals[0].eligibility = FixedQ32::from_raw(11);
    let changed_eligibility =
        build_generator_coverage_receipt_v1(&changed_eligibility, digest(b"owner-frontier"))
            .expect("eligibility");
    assert_ne!(base.coverage_digest, changed_eligibility.coverage_digest);

    let mut changed_bounds = base_profile.clone();
    changed_bounds.signals[0].lower_bound = FixedQ32::from_raw(-999);
    let changed_bounds =
        build_generator_coverage_receipt_v1(&changed_bounds, digest(b"owner-frontier"))
            .expect("bounds");
    assert_ne!(base.coverage_digest, changed_bounds.coverage_digest);

    let mut changed_grammar = base_profile;
    changed_grammar.mutation_policy = policy(b"grammar:property:new", false);
    let changed_grammar =
        build_generator_coverage_receipt_v1(&changed_grammar, digest(b"owner-frontier"))
            .expect("grammar");
    assert_ne!(base.coverage_digest, changed_grammar.coverage_digest);
}

#[test]
fn zero_signal_and_disabled_scale_are_distinct_from_no_admissible_update() {
    let mut zero_signal = profile(false);
    zero_signal.signals.clear();
    let zero = build_generator_coverage_receipt_v1(&zero_signal, digest(b"owner-frontier"))
        .expect("zero signals");
    assert_eq!(
        zero.disposition,
        GeneratorCoverageDispositionV1::ZeroEligibleSignals
    );

    let mut disabled = profile(false);
    disabled.update_scales.clear();
    let disabled =
        build_generator_coverage_receipt_v1(&disabled, digest(b"owner-frontier"))
            .expect("disabled");
    assert_eq!(
        disabled.disposition,
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates
    );
    assert_ne!(zero.coverage_digest, disabled.coverage_digest);
}
