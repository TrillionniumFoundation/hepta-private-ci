use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_factor_relation_binding;
use codex_hepta_prompt_registry::final_use_revoke_binding;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn signed_grant(binding: FinalUseBinding, key: &SigningKey, grant_id: &str) -> SignedFinalUseGrant {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("time");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:kg".to_owned(),
        authority_epoch: 1,
        grant_id: grant_id.to_owned(),
        nonce: digest(grant_id).into_array(),
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    SignedFinalUseGrant {
        signature: key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    }
}

fn registry_with_conflict() -> (
    tempfile::TempDir,
    DurablePromptRegistry,
    FinalUseAuthority,
    SigningKey,
) {
    let temp = tempfile::tempdir().expect("temp");
    let mut registry =
        DurablePromptRegistry::open_state_dir(&temp.path().join("registry"), 64).expect("registry");
    let key = SigningKey::from_bytes(&[31; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temp.path().join("authority"),
        "review-authority:kg".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    for (factor_id, proposer) in [("factor:a", "proposer:a"), ("factor:b", "proposer:b")] {
        let factor = PromptFactor {
            factor_id: id(factor_id),
            proposer_id: id(proposer),
            semantic_version: id("v1"),
            semantic_purpose: "verify prompt relation evidence".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest(factor_id),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        registry.register_factor(factor.clone()).expect("factor");
        let scope = digest("admission-scope");
        let evidence = digest("admission");
        let signed = signed_grant(
            final_use_admission_binding(&factor, &id("reviewer:independent"), scope, evidence)
                .expect("binding"),
            &key,
            &format!("admission:{factor_id}"),
        );
        registry
            .admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence)
            .expect("admit");
    }
    let relation = PromptFactorRelation {
        relation_id: id("relation:a:b:conflict"),
        left_factor_id: id("factor:a"),
        right_factor_id: id("factor:b"),
        kind: PromptFactorRelationKind::Conflicts,
        evidence_digest: digest("conflict-evidence"),
    };
    let actor = id("reviewer:relation");
    let scope = digest("relation-scope");
    let signed = signed_grant(
        final_use_factor_relation_binding(
            registry.registry().expect("owner view"),
            &actor,
            scope,
            &relation,
        )
        .expect("binding"),
        &key,
        "relation:a:b:conflict",
    );
    registry
        .register_factor_relation_final_use(&authority, &signed, &actor, scope, relation)
        .expect("relation");
    (temp, registry, authority, key)
}

#[test]
fn registry_factor_relations_use_the_canonical_generation_and_query_kernel() {
    let (_temp, registry, _authority, _key) = registry_with_conflict();
    let source = registry
        .registry()
        .expect("owner view")
        .factor_graph_source_v1();
    let projection = build_prompt_factor_projection_v1(
        Generation::new(1).expect("generation"),
        digest("generation-vector"),
        &source,
    )
    .expect("projection");
    projection.validate().expect("valid projection");
    assert_eq!(projection.generation.nodes.len(), 2);
    assert_eq!(projection.generation.edges.len(), 1);
    assert_eq!(
        projection.generation.edges[0].identity.relation,
        KnowledgeRelationKindV2::PromptConflicts
    );

    let result = crate::query_relations(
        &projection.generation,
        crate::KnowledgeRelationQueryV2 {
            query_id: id("query:prompt-factor-conflict"),
            generation_digest: projection.generation.generation_digest,
            seed_node_ids: vec![id("factor:a"), id("factor:b")],
            relation_kinds: vec![KnowledgeRelationKindV2::PromptConflicts],
            valid_at_unix_seconds: None,
            maximum_edges: 8,
        },
    )
    .expect("query");
    assert_eq!(result.edges.len(), 1);
    assert_eq!(
        result.edges[0].supports[0].source_id,
        id("relation:a:b:conflict")
    );
    assert!(!result.authority.grants_any());
}

#[test]
fn registry_revocation_removes_prompt_relation_on_rebuild() {
    let (_temp, mut registry, authority, key) = registry_with_conflict();
    let before = registry
        .registry()
        .expect("owner view")
        .factor_graph_source_v1();
    let factor = registry
        .registry()
        .expect("owner view")
        .factor(&id("factor:b"))
        .expect("factor")
        .clone();
    let actor = id("revoker:test");
    let scope = digest("revoke-scope");
    let reason = digest("revoke-reason");
    let cutoff = 1;
    let signed = signed_grant(
        final_use_revoke_binding(&factor, &actor, scope, reason, cutoff).expect("revoke binding"),
        &key,
        "revoke:factor:b",
    );
    registry
        .revoke_factor_final_use(
            &authority,
            &signed,
            &factor.factor_id,
            &actor,
            scope,
            reason,
            cutoff,
        )
        .expect("revoke");
    let after = registry
        .registry()
        .expect("owner view")
        .factor_graph_source_v1();
    assert_ne!(before.source_digest(), after.source_digest());
    assert!(after.relations().is_empty());

    let projection = build_prompt_factor_projection_v1(
        Generation::new(2).expect("generation"),
        digest("generation-vector:2"),
        &after,
    )
    .expect("projection");
    assert_eq!(projection.generation.nodes.len(), 1);
    assert!(projection.generation.edges.is_empty());
    assert_eq!(
        projection.registry_revision,
        registry.registry().expect("owner view").revision().get()
    );
}

#[test]
fn source_revision_is_preserved_as_projection_support_lineage() {
    let (_temp, registry, _authority, _key) = registry_with_conflict();
    let source = registry
        .registry()
        .expect("owner view")
        .factor_graph_source_v1();
    let projection = build_prompt_factor_projection_v1(
        Generation::new(1).expect("generation"),
        digest("generation-vector"),
        &source,
    )
    .expect("projection");
    let expected = Revision::new(source.registry_revision().get()).expect("revision");
    assert_eq!(
        projection.generation.edges[0].supports[0].source_revision,
        expected
    );
}
