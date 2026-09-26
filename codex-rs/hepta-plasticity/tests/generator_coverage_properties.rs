use codex_hepta_plasticity::GeneratorCoverageMissingParameterV1;
use codex_hepta_plasticity::GeneratorCoverageMissingReasonV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::GeneratorCoverageTerminalV1;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterGeneratorProfileV3;
use codex_hepta_plasticity::ParameterMutationRuleV1;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ParameterPlasticitySignalV3;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::build_generator_coverage_receipt_v1;
use codex_hepta_plasticity::build_parameter_mutation_policy_v1;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn window() -> ProposalWindowV2 {
    ProposalWindowV2 {
        window_id: id("window:coverage-properties"),
        window_digest: digest(b"window"),
    }
}

fn rule(parameter: &str) -> ParameterMutationRuleV1 {
    ParameterMutationRuleV1 {
        parameter_id: id(parameter),
        layer_id: id("layer:adapter"),
        surface: ParameterMutationSurfaceV1::LearnableParameter,
        minimum_delta: FixedQ32::from_raw(-1_000),
        maximum_delta: FixedQ32::from_raw(1_000),
    }
}

fn signal(parameter: &str, value: i64) -> ParameterPlasticitySignalV3 {
    ParameterPlasticitySignalV3 {
        layer_id: id("layer:adapter"),
        parameter_id: id(parameter),
        eligibility: FixedQ32::ONE,
        modulator: FixedQ32::ONE,
        learning_rate: FixedQ32::from_raw(value),
        lower_bound: FixedQ32::from_raw(-1_000),
        upper_bound: FixedQ32::from_raw(1_000),
        evidence_digest: digest(format!("signal:{parameter}:{value}").as_bytes()),
    }
}

fn profile(reverse: bool) -> ParameterGeneratorProfileV3 {
    let artifact = digest(b"artifact");
    let mut rules = vec![rule("parameter:a"), rule("parameter:b")];
    let mut signals = vec![signal("parameter:a", 1), signal("parameter:b", 2)];
    let mut scales = vec![FixedQ32::from_raw(1), FixedQ32::from_raw(2)];
    if reverse {
        rules.reverse();
        signals.reverse();
        scales.reverse();
    }
    ParameterGeneratorProfileV3 {
        selected_artifact_digest: artifact,
        window: window(),
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:adapter"),
            baseline_squared_l2_raw_q64: 10_000_000_000,
        }],
        mutation_policy: build_parameter_mutation_policy_v1(
            id("policy:coverage-properties"),
            digest(b"grammar"),
            artifact,
            window(),
            rules,
        )
        .expect("policy"),
        update_scales: scales,
        signals,
    }
}

#[test]
fn all_input_permutations_have_one_generated_and_coverage_identity() {
    let forward = profile(false);
    let reverse = profile(true);
    assert_eq!(
        generate_parameter_candidates_v3(forward.clone()).expect("forward"),
        generate_parameter_candidates_v3(reverse.clone()).expect("reverse")
    );

    let forward_receipt = build_generator_coverage_receipt_v1(
        &forward,
        vec![id("parameter:b"), id("parameter:a")],
        Vec::new(),
        digest(b"owner-frontier"),
    )
    .expect("forward coverage");
    let reverse_receipt = build_generator_coverage_receipt_v1(
        &reverse,
        vec![id("parameter:a"), id("parameter:b")],
        Vec::new(),
        digest(b"owner-frontier"),
    )
    .expect("reverse coverage");
    assert_eq!(forward_receipt, reverse_receipt);
}

#[test]
fn every_bound_receipt_field_rejects_single_field_substitution() {
    let profile = profile(false);
    let receipt = build_generator_coverage_receipt_v1(
        &profile,
        vec![id("parameter:a"), id("parameter:b")],
        Vec::new(),
        digest(b"owner-frontier"),
    )
    .expect("coverage");

    let mutations: [fn(&mut GeneratorCoverageReceiptV1); 10] = [
        |value| value.selected_artifact_digest = digest(b"other-artifact"),
        |value| value.window.window_digest = digest(b"other-window"),
        |value| value.mutation_grammar_digest = digest(b"other-grammar"),
        |value| value.owner_frontier_digest = digest(b"other-frontier"),
        |value| value.expected_learnable_parameter_set_digest = digest(b"other-expected"),
        |value| value.actual_signal_set_digest = digest(b"other-signals"),
        |value| value.missing_parameter_set_digest = digest(b"other-missing"),
        |value| value.scale_policy_digest = digest(b"other-scales"),
        |value| value.terminal = GeneratorCoverageTerminalV1::ZeroEligibleSignals,
        |value| value.coverage_digest = digest(b"other-coverage"),
    ];
    for mutate in mutations {
        let mut changed = receipt.clone();
        mutate(&mut changed);
        assert!(verify_generator_coverage_receipt_v1(&profile, &changed).is_err());
    }
}

#[test]
fn missing_parameter_reason_and_evidence_are_both_digest_bound() {
    let mut single_signal_profile = profile(false);
    single_signal_profile.signals = vec![signal("parameter:a", 1)];
    let missing = GeneratorCoverageMissingParameterV1 {
        parameter_id: id("parameter:b"),
        reason: GeneratorCoverageMissingReasonV1::MissingEligibility,
        reason_evidence_digest: digest(b"missing-evidence"),
    };
    let receipt = build_generator_coverage_receipt_v1(
        &single_signal_profile,
        vec![id("parameter:a"), id("parameter:b")],
        vec![missing],
        digest(b"owner-frontier"),
    )
    .expect("coverage");

    let mut reason = receipt.clone();
    reason.missing_parameters[0].reason = GeneratorCoverageMissingReasonV1::PolicyDisabled;
    assert!(verify_generator_coverage_receipt_v1(&single_signal_profile, &reason).is_err());

    let mut evidence = receipt;
    evidence.missing_parameters[0].reason_evidence_digest = digest(b"other-evidence");
    assert!(verify_generator_coverage_receipt_v1(&single_signal_profile, &evidence).is_err());
}
