use super::*;
use codex_hepta_contracts::FinalUseAuthority;
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
use codex_hepta_prompt_registry::final_use_revoke_binding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64
}

fn factor(name: &str) -> PromptFactor {
    PromptFactor {
        factor_id: id(&format!("factor:{name}")),
        proposer_id: id(&format!("proposer:{name}")),
        semantic_version: id("v1"),
        semantic_purpose: "owner-bound prompt relation fixture".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest(&format!("factor-content:{name}")),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

fn signed_grant(
    signing_key: &SigningKey,
    grant_id: &str,
    nonce: u8,
    binding: codex_hepta_contracts::FinalUseBinding,
) -> SignedFinalUseGrant {
    let now = now_ms();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner:prompt-graph".to_owned(),
        authority_epoch: 7,
        grant_id: grant_id.to_owned(),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    }
}

fn authority(root: &Path, signing_key: &SigningKey) -> FinalUseAuthority {
    FinalUseAuthority::open_state_dir(
        root,
        "security-owner:prompt-graph".to_owned(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority")
}

fn admit(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    factor: PromptFactor,
    nonce: u8,
) {
    registry
        .register_factor(factor.clone())
        .expect("register factor");
    let reviewer = id(&format!("reviewer:{}", factor.factor_id.as_str()));
    let scope = digest(&format!("scope:{}", factor.factor_id.as_str()));
    let evidence = digest(&format!("evidence:{}", factor.factor_id.as_str()));
    let binding = final_use_admission_binding(&factor, &reviewer, scope, evidence)
        .expect("admission binding");
    let signed = signed_grant(
        signing_key,
        &format!("grant:admit:{}", factor.factor_id.as_str()),
        nonce,
        binding,
    );
    registry
        .admit_factor_final_use(authority, &signed, &factor.factor_id, scope, evidence)
        .expect("admit factor");
}

fn register_conflict(registry: &mut DurablePromptRegistry) {
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a:b:conflict"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            kind: PromptFactorRelationKind::Conflicts,
            evidence_digest: digest("conflict-evidence"),
        })
        .expect("register durable relation");
}

fn open_populated(
    registry_root: &Path,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
) -> DurablePromptRegistry {
    let mut registry =
        DurablePromptRegistry::open_state_dir(registry_root, 64).expect("open durable registry");
    admit(&mut registry, authority, signing_key, factor("a"), 1);
    admit(&mut registry, authority, signing_key, factor("b"), 2);
    register_conflict(&mut registry);
    registry
}

#[test]
fn durable_owner_relation_reopens_into_canonical_generation_and_query() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let signing_key = SigningKey::from_bytes(&[61; 32]);
    let authority = authority(&temporary.path().join("authority"), &signing_key);
    let registry_root = temporary.path().join("registry");
    let registry = open_populated(&registry_root, &authority, &signing_key);
    let expected_digest = registry.registry().expect("registry").snapshot_digest();
    drop(registry);

    let reopened =
        DurablePromptRegistry::open_state_dir(&registry_root, 64).expect("reopen durable registry");
    let owner = reopened.registry().expect("registry");
    assert_eq!(owner.snapshot_digest(), expected_digest);
    let source = owner.factor_graph_source_v1();
    assert_eq!(source.factors().len(), 2);
    assert_eq!(source.relations().len(), 1);

    let projection = build_prompt_factor_projection_v1(
        Generation::new(1).expect("generation"),
        digest("generation-vector"),
        &source,
    )
    .expect("projection");
    projection.validate().expect("valid projection");
    assert_eq!(projection.generation().nodes.len(), 2);
    assert_eq!(projection.generation().edges.len(), 1);
    assert_eq!(
        projection.generation().edges[0].identity.relation,
        KnowledgeRelationKindV2::PromptConflicts
    );
    assert_eq!(
        projection.generation().edges[0].supports[0].source_revision,
        source.registry_revision()
    );

    let result = crate::query_relations(
        projection.generation(),
        crate::KnowledgeRelationQueryV2 {
            query_id: id("query:prompt-factor-conflict"),
            generation_digest: projection.generation().generation_digest,
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
fn final_use_revocation_filters_relation_and_survives_reopen() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let signing_key = SigningKey::from_bytes(&[62; 32]);
    let authority = authority(&temporary.path().join("authority"), &signing_key);
    let registry_root = temporary.path().join("registry");
    let mut registry = open_populated(&registry_root, &authority, &signing_key);
    let before = registry
        .registry()
        .expect("registry")
        .factor_graph_source_v1();

    let factor_id = id("factor:b");
    let current = registry
        .registry()
        .expect("registry")
        .factor(&factor_id)
        .cloned()
        .expect("factor");
    let actor = id("revoker:prompt-graph");
    let scope = digest("scope:revoke:prompt-graph");
    let reason = digest("reason:revoke:prompt-graph");
    let cutoff = now_ms() + 5_000;
    let binding =
        final_use_revoke_binding(&current, &actor, scope, reason, cutoff).expect("revoke binding");
    let signed = signed_grant(&signing_key, "grant:revoke:prompt-graph", 3, binding);
    registry
        .revoke_factor_final_use(
            &authority, &signed, &factor_id, &actor, scope, reason, cutoff,
        )
        .expect("revoke factor");

    let after = registry
        .registry()
        .expect("registry")
        .factor_graph_source_v1();
    assert_ne!(before.source_digest(), after.source_digest());
    assert_eq!(after.factors().len(), 1);
    assert!(after.relations().is_empty());
    let expected_digest = registry.registry().expect("registry").snapshot_digest();
    drop(registry);

    let reopened =
        DurablePromptRegistry::open_state_dir(&registry_root, 64).expect("reopen after revoke");
    let owner = reopened.registry().expect("registry");
    assert_eq!(owner.snapshot_digest(), expected_digest);
    let source = owner.factor_graph_source_v1();
    assert_eq!(source.factors().len(), 1);
    assert!(source.relations().is_empty());

    let projection = build_prompt_factor_projection_v1(
        Generation::new(2).expect("generation"),
        digest("generation-vector:2"),
        &source,
    )
    .expect("projection");
    assert_eq!(projection.generation().nodes.len(), 1);
    assert!(projection.generation().edges.is_empty());
    assert_eq!(projection.registry_revision(), owner.revision().get());
}
