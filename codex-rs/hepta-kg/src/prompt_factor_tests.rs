use super::*;
use crate::KnowledgePhysicalQueryErrorV2;
use crate::KnowledgeResourceErrorCodeV2;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::fixture::PromptRegistryFixture;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn registry_with_conflict() -> PromptRegistryFixture {
    let mut registry = PromptRegistryFixture::new(64).expect("registry");
    for (factor_id, proposer) in [("factor:a", "proposer:a"), ("factor:b", "proposer:b")] {
        registry
            .register_factor(PromptFactor {
                factor_id: id(factor_id),
                proposer_id: id(proposer),
                semantic_version: id("v1"),
                semantic_purpose: "verify before mutating".to_owned(),
                authority_class: "registered_prompt_factor".to_owned(),
                eligible_objective_dimensions: vec![id("dimension:truth")],
                content_digest: digest(factor_id),
                source: FactorSource::GovernedInternal,
                lifecycle: Lifecycle::Draft,
            })
            .expect("factor");
        registry
            .admit_factor(
                &id(factor_id),
                &id("reviewer:independent"),
                digest("admission"),
            )
            .expect("admit");
    }
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a:b:conflict"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            kind: PromptFactorRelationKind::Conflicts,
            evidence_digest: digest("conflict-evidence"),
        })
        .expect("relation");
    registry
}

fn projection() -> PromptFactorProjectionV1 {
    let registry = registry_with_conflict();
    let source = registry.factor_graph_source_v1();
    build_prompt_factor_projection_v1(
        Generation::new(1).expect("generation"),
        digest("generation-vector"),
        &source,
    )
    .expect("projection")
}

fn conflict_query(projection: &PromptFactorProjectionV1, name: &str) -> KnowledgeRelationQueryV2 {
    KnowledgeRelationQueryV2 {
        query_id: id(name),
        generation_digest: projection.generation().generation_digest,
        seed_node_ids: vec![id("factor:a"), id("factor:b")],
        relation_kinds: vec![KnowledgeRelationKindV2::PromptConflicts],
        valid_at_unix_seconds: None,
        maximum_edges: 8,
    }
}

#[test]
fn registry_factor_relations_use_the_physical_query_contract() {
    let projection = projection();
    projection.validate().expect("valid projection");
    assert_eq!(projection.generation().nodes.len(), 2);
    assert_eq!(projection.generation().edges.len(), 1);
    assert_eq!(
        projection.generation().edges[0].identity.relation,
        KnowledgeRelationKindV2::PromptConflicts
    );

    let (result, observation) = projection
        .query_relations_external(
            conflict_query(&projection, "query:prompt-factor-conflict"),
            None,
        )
        .expect("physically bounded query");
    assert_eq!(result.edges.len(), 1);
    assert_eq!(
        result.edges[0].supports[0].source_id,
        id("relation:a:b:conflict")
    );
    assert!(observation.output_bytes > 0);
    assert_eq!(observation.generation_usage, projection.generation_usage());
    assert!(observation.work.relation_edges_scanned > 0);
    assert!(!result.authority.grants_any());
}

#[test]
fn registry_revocation_removes_prompt_relation_on_rebuild() {
    let mut registry = registry_with_conflict();
    let before = registry.factor_graph_source_v1();
    registry.revoke_factor(&id("factor:b")).expect("revoke");
    let after = registry.factor_graph_source_v1();
    assert_ne!(before.source_digest(), after.source_digest());
    assert!(after.relations().is_empty());

    let projection = build_prompt_factor_projection_v1(
        Generation::new(2).expect("generation"),
        digest("generation-vector:2"),
        &after,
    )
    .expect("projection");
    assert_eq!(projection.generation().nodes.len(), 1);
    assert!(projection.generation().edges.is_empty());
    assert_eq!(projection.registry_revision(), registry.revision().get());
}

#[test]
fn source_revision_is_preserved_as_projection_support_lineage() {
    let registry = registry_with_conflict();
    let source = registry.factor_graph_source_v1();
    let projection = build_prompt_factor_projection_v1(
        Generation::new(1).expect("generation"),
        digest("generation-vector"),
        &source,
    )
    .expect("projection");
    let expected = Revision::new(source.registry_revision().get()).expect("revision");
    assert_eq!(
        projection.generation().edges[0].supports[0].source_revision,
        expected
    );
}

#[test]
fn caller_cancellation_fails_before_factor_query_execution() {
    let projection = projection();
    let cancellation = KnowledgeCancellationV2::default();
    let guard = KnowledgeOperationGuardV2::unbounded(cancellation.clone());
    cancellation.cancel();

    let result = projection.query_relations_external_guarded(
        conflict_query(&projection, "query:prompt-factor-cancelled"),
        None,
        &guard,
    );
    let Err(KnowledgePhysicalQueryErrorV2::Resource(error)) = result else {
        panic!("cancelled factor query must fail closed");
    };
    assert_eq!(error.code, KnowledgeResourceErrorCodeV2::Cancelled);
}
