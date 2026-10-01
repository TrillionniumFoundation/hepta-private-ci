//! Adversarial regressions using actual owner-issued and signed inputs.

use super::*;
use super::tests::*;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::build_complete_generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

#[test]
fn sealed_owner_projection_preserves_conflicts_after_bare_graph_rebuild() {
    use codex_hepta_prompt_registry::PromptFactorRelation;
    use codex_hepta_prompt_registry::PromptFactorRelationKind;
    use codex_hepta_prompt_registry::final_use_factor_relation_binding;

    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _, authority, key, now) = registry_fixture(&temp.path().join("registry"), &[1]);
    let (actor, scope) = register_second_realized_factor(&mut registry, &authority, &key, now);
    let relation = PromptFactorRelation {
        relation_id: id("relation:authentic-conflict"),
        left_factor_id: id("factor:a"), right_factor_id: id("factor:b"),
        kind: PromptFactorRelationKind::Conflicts, evidence_digest: digest("authentic-conflict-evidence"),
    };
    let grant = relation_grant(
        final_use_factor_relation_binding(registry.registry().expect("registry"), &actor, scope, &relation).expect("relation binding"),
        &key, now, "insert:authentic-conflict",
    );
    registry.register_factor_relation_final_use(&authority, &grant, &actor, scope, relation).expect("authentic conflict");
    let owner = registry.registry().expect("registry");
    let projection = owner_projection(owner);
    let graph = projection.generation();
    let forged = build_complete_generation(graph.generation, KnowledgeProjectionInputV2 {
        source_snapshot_digest: graph.source_snapshot_digest,
        generation_vector_digest: graph.generation_vector_digest,
        graph_profile_digest: graph.graph_profile_digest,
        complete_source_cut: true, nodes: graph.nodes.clone(), edges: Vec::new(),
    }).expect("public builder can relabel a relation-free graph");
    forged.validate().expect("structurally valid bare graph");
    assert_eq!(forged.source_snapshot_digest, projection.source_digest());
    assert_ne!(forged.generation_digest, graph.generation_digest);
    // The public selector requires the private owner-issued projection type;
    // this valid bare graph cannot be passed or substituted into its contents.
    assert_eq!(owner_projection(owner), projection);
    let priced = current_pair_pricing(owner);
    let selected = select_portfolio_v1(&priced, &projection, Vec::new(), &verifier(), selection_request(), 100).expect("sealed owner selection");
    assert_eq!(selected.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(selected.graph_generation_digest, graph.generation_digest);
    assert_eq!(exercise_v1(owner, &selected, PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"), generation_vector_digest: digest("generation-vector"),
        model_tuple: model_tuple(), now_unix_ms: 200, wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    }).expect("live authentic portfolio").decision, PromptExerciseActionV1::Exercise);
}

