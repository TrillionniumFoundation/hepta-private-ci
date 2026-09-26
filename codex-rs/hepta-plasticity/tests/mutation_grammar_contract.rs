use std::str::FromStr;

use codex_hepta_plasticity::ParameterMutationRuleV1;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::build_parameter_mutation_policy_v1;
use codex_hepta_plasticity::verify_parameter_mutation_policy_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Fixture {
    selected_artifact_digest: String,
    window: Window,
    rules: Vec<Rule>,
    semantic_digest: String,
    expected_plasticity_policy_id: String,
    expected_plasticity_policy_digest: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Window {
    window_id: String,
    window_digest: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Rule {
    parameter_id: String,
    layer_id: String,
    surface: String,
    minimum_delta_raw_q32: i64,
    maximum_delta_raw_q32: i64,
}

fn fixture() -> Fixture {
    serde_json::from_str(include_str!(
        "../../../qualification/fixtures/learning.plasticity/mutation-grammar-projection-v1.json"
    ))
    .expect("cross-module grammar fixture")
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::from_str(value).expect("fixture digest")
}

fn surface(value: &str) -> ParameterMutationSurfaceV1 {
    match value {
        "learnable_parameter" => ParameterMutationSurfaceV1::LearnableParameter,
        "authority" => ParameterMutationSurfaceV1::Authority,
        "evaluator" => ParameterMutationSurfaceV1::Evaluator,
        "deletion" => ParameterMutationSurfaceV1::Deletion,
        "runtime_topology" => ParameterMutationSurfaceV1::RuntimeTopology,
        "credential" => ParameterMutationSurfaceV1::Credential,
        other => panic!("unsupported fixture surface: {other}"),
    }
}

#[test]
fn control_engineering_manifest_projects_to_exact_rust_policy() {
    let fixture = fixture();
    let rules = fixture
        .rules
        .into_iter()
        .map(|rule| ParameterMutationRuleV1 {
            parameter_id: id(&rule.parameter_id),
            layer_id: id(&rule.layer_id),
            surface: surface(&rule.surface),
            minimum_delta: FixedQ32::from_raw(rule.minimum_delta_raw_q32),
            maximum_delta: FixedQ32::from_raw(rule.maximum_delta_raw_q32),
        })
        .collect();
    let policy = build_parameter_mutation_policy_v1(
        id(&fixture.expected_plasticity_policy_id),
        digest(&fixture.semantic_digest),
        digest(&fixture.selected_artifact_digest),
        ProposalWindowV2 {
            window_id: id(&fixture.window.window_id),
            window_digest: digest(&fixture.window.window_digest),
        },
        rules,
    )
    .expect("projected policy");
    verify_parameter_mutation_policy_v1(&policy).expect("verify projected policy");
    assert_eq!(
        policy.mutation_grammar_digest.to_string(),
        fixture.semantic_digest
    );
    assert_eq!(
        policy.policy_digest.to_string(),
        fixture.expected_plasticity_policy_digest
    );
    assert_eq!(
        policy
            .rules
            .iter()
            .map(|rule| rule.parameter_id.as_str())
            .collect::<Vec<_>>(),
        vec!["parameter:a", "parameter:b"]
    );
}

#[test]
fn projection_is_invariant_to_manifest_rule_order() {
    let mut fixture = fixture();
    let first = fixture
        .rules
        .iter()
        .map(|rule| ParameterMutationRuleV1 {
            parameter_id: id(&rule.parameter_id),
            layer_id: id(&rule.layer_id),
            surface: surface(&rule.surface),
            minimum_delta: FixedQ32::from_raw(rule.minimum_delta_raw_q32),
            maximum_delta: FixedQ32::from_raw(rule.maximum_delta_raw_q32),
        })
        .collect::<Vec<_>>();
    fixture.rules.reverse();
    let reversed = fixture
        .rules
        .iter()
        .map(|rule| ParameterMutationRuleV1 {
            parameter_id: id(&rule.parameter_id),
            layer_id: id(&rule.layer_id),
            surface: surface(&rule.surface),
            minimum_delta: FixedQ32::from_raw(rule.minimum_delta_raw_q32),
            maximum_delta: FixedQ32::from_raw(rule.maximum_delta_raw_q32),
        })
        .collect::<Vec<_>>();
    let make = |rules| {
        build_parameter_mutation_policy_v1(
            id(&fixture.expected_plasticity_policy_id),
            digest(&fixture.semantic_digest),
            digest(&fixture.selected_artifact_digest),
            ProposalWindowV2 {
                window_id: id(&fixture.window.window_id),
                window_digest: digest(&fixture.window.window_digest),
            },
            rules,
        )
        .expect("policy")
    };
    assert_eq!(make(first), make(reversed));
}
