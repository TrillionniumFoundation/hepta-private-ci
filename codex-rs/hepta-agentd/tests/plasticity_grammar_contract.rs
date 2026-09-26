use codex_hepta_plasticity::ParameterMutationRuleV1;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::build_parameter_mutation_policy_v1;
use codex_hepta_plasticity::verify_parameter_mutation_policy_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde_json::Value;

fn find_protocol<'a>(value: &'a Value, protocol_id: &str) -> Option<&'a Value> {
    match value {
        Value::Object(object) => {
            if object.get("id").and_then(Value::as_str) == Some(protocol_id) {
                return Some(value);
            }
            object
                .values()
                .find_map(|child| find_protocol(child, protocol_id))
        }
        Value::Array(array) => array
            .iter()
            .find_map(|child| find_protocol(child, protocol_id)),
        _ => None,
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

#[test]
fn control_engineering_grammar_projects_unambiguously_into_plasticity_policy() {
    let registry: Value = serde_json::from_str(include_str!(
        "../../../docs/readiness/PROTOCOLS.json"
    ))
    .expect("protocol registry");
    let grammar = find_protocol(&registry, "MutationGrammarManifestV1")
        .expect("MutationGrammarManifestV1");
    assert_eq!(
        grammar.get("owner").and_then(Value::as_str),
        Some("control.engineering")
    );
    assert_eq!(
        grammar.get("authorityDelta").and_then(Value::as_str),
        Some("none")
    );
    assert!(
        grammar
            .get("consumers")
            .and_then(Value::as_array)
            .is_some_and(|consumers| consumers
                .iter()
                .any(|consumer| consumer.as_str() == Some("learning.plasticity")))
    );

    let grammar_bytes = serde_json::to_vec(grammar).expect("grammar bytes");
    let grammar_digest = Digest32::of_bytes(&grammar_bytes);
    let artifact = Digest32::of_bytes(b"artifact");
    let window = ProposalWindowV2 {
        window_id: id("window:grammar-contract"),
        window_digest: Digest32::of_bytes(b"window"),
    };
    let policy = build_parameter_mutation_policy_v1(
        id("policy:grammar-contract"),
        grammar_digest,
        artifact,
        window.clone(),
        vec![ParameterMutationRuleV1 {
            parameter_id: id("parameter:adapter"),
            layer_id: id("layer:adapter"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-10),
            maximum_delta: FixedQ32::from_raw(10),
        }],
    )
    .expect("projected policy");
    verify_parameter_mutation_policy_v1(&policy).expect("verified policy");
    assert_eq!(policy.mutation_grammar_digest, grammar_digest);

    let mut substituted = grammar.clone();
    substituted["owner"] = Value::String("learning.plasticity".to_string());
    let substituted_digest =
        Digest32::of_bytes(&serde_json::to_vec(&substituted).expect("substituted bytes"));
    assert_ne!(grammar_digest, substituted_digest);

    let substituted_policy = build_parameter_mutation_policy_v1(
        id("policy:grammar-contract"),
        substituted_digest,
        artifact,
        window,
        vec![ParameterMutationRuleV1 {
            parameter_id: id("parameter:adapter"),
            layer_id: id("layer:adapter"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-10),
            maximum_delta: FixedQ32::from_raw(10),
        }],
    )
    .expect("substituted policy");
    assert_ne!(policy.policy_digest, substituted_policy.policy_digest);
}
