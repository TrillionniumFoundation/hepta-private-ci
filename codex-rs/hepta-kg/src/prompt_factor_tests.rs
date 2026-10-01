//! Adapter regressions exercise public durable owners and verified admissions.

use super::*;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_revoke_binding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

type TestResult<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn signed_grant(
    signing_key: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
) -> TestResult<SignedFinalUseGrant> {
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner:kg-fixture".to_owned(),
        authority_epoch: 1,
        grant_id: grant_id.to_owned(),
        nonce: digest(grant_id).into_array(),
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    Ok(SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes()?)
            .to_bytes()
            .to_vec(),
        grant,
    })
}

struct Fixture {
    owner: DurablePromptRegistry,
    authority: FinalUseAuthority,
    signing_key: SigningKey,
    directory: tempfile::TempDir,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let directory = tempfile::tempdir()?;
        let signing_key = SigningKey::from_bytes(&[71; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &directory.path().join("authority"),
            "security-owner:kg-fixture".to_owned(),
            signing_key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        let mut owner = DurablePromptRegistry::open_state_dir(
            &directory.path().join("registry"),
            /*maximum_records*/ 64,
        )?;
        for factor_id in ["factor:a", "factor:b"] {
            let factor = PromptFactor {
                factor_id: id(factor_id)?,
                proposer_id: id("proposer:kg-fixture")?,
                semantic_version: id("v1")?,
                semantic_purpose: "project governed factor evidence".to_owned(),
                authority_class: "registered_prompt_factor".to_owned(),
                eligible_objective_dimensions: vec![id("dimension:truth")?],
                content_digest: digest(factor_id),
                source: FactorSource::GovernedInternal,
                lifecycle: Lifecycle::Draft,
            };
            owner.register_factor(factor.clone())?;
            let scope = digest("scope:kg-fixture");
            let evidence = digest("admission:kg-fixture");
            let binding =
                final_use_admission_binding(&factor, &id("reviewer:kg-fixture")?, scope, evidence)?;
            let signed = signed_grant(&signing_key, binding, &format!("grant:admit:{factor_id}"))?;
            owner.admit_factor_final_use(
                &authority,
                &signed,
                &factor.factor_id,
                scope,
                evidence,
            )?;
        }
        for (label, kind) in [
            ("complement", PromptFactorRelationKind::Complements),
            ("substitute", PromptFactorRelationKind::Substitutes),
            ("conflict", PromptFactorRelationKind::Conflicts),
        ] {
            owner.register_factor_relation(PromptFactorRelation {
                relation_id: id(&format!("relation:a:b:{label}"))?,
                left_factor_id: id("factor:a")?,
                right_factor_id: id("factor:b")?,
                kind,
                evidence_digest: digest(label),
            })?;
        }
        Ok(Self {
            owner,
            authority,
            signing_key,
            directory,
        })
    }
}

#[test]
fn registry_factor_relations_use_the_canonical_generation_and_query_kernel() -> TestResult<()> {
    let fixture = Fixture::new()?;
    let source = fixture.owner.registry()?.factor_graph_source_v1();
    let projection = build_prompt_factor_projection_v1(
        Generation::new(1)?,
        digest("generation-vector"),
        &source,
    )?;
    projection.validate()?;
    assert_eq!(
        projection
            .generation
            .nodes
            .iter()
            .map(|node| node.node_id.clone())
            .collect::<Vec<_>>(),
        vec![id("factor:a")?, id("factor:b")?]
    );
    assert_eq!(
        projection
            .generation
            .edges
            .iter()
            .map(|edge| edge.identity.relation.clone())
            .collect::<Vec<_>>(),
        vec![
            KnowledgeRelationKindV2::PromptComplements,
            KnowledgeRelationKindV2::PromptSubstitutes,
            KnowledgeRelationKindV2::PromptConflicts,
        ]
    );
    let result = crate::query_relations(
        &projection.generation,
        crate::KnowledgeRelationQueryV2 {
            query_id: id("query:prompt-factor-conflict")?,
            generation_digest: projection.generation.generation_digest,
            seed_node_ids: vec![id("factor:a")?, id("factor:b")?],
            relation_kinds: vec![KnowledgeRelationKindV2::PromptConflicts],
            valid_at_unix_seconds: None,
            maximum_edges: 8,
        },
    )?;
    assert_eq!(result.edges, projection.generation.edges[2..]);
    assert_eq!(
        result.edges[0].supports[0].source_id,
        id("relation:a:b:conflict")?
    );
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
    Ok(())
}

#[test]
fn registry_revocation_removes_prompt_relation_on_rebuild_and_reopen() -> TestResult<()> {
    let Fixture {
        mut owner,
        authority,
        signing_key,
        directory,
    } = Fixture::new()?;
    let before = owner.registry()?.factor_graph_source_v1();
    let factor_id = id("factor:b")?;
    let factor = owner
        .registry()?
        .factor(&factor_id)
        .ok_or("fixture factor is missing")?;
    let actor = id("operator:kg-fixture")?;
    let scope = digest("scope:revocation");
    let reason = digest("reason:revocation");
    let binding =
        final_use_revoke_binding(factor, &actor, scope, reason, /*cutoff_unix_ms*/ 7)?;
    let signed = signed_grant(&signing_key, binding, "grant:revoke:factor:b")?;
    owner.revoke_factor_final_use(
        &authority, &signed, &factor_id, &actor, scope, reason, /*cutoff_unix_ms*/ 7,
    )?;
    let after = owner.registry()?.factor_graph_source_v1();
    assert_ne!(before.source_digest(), after.source_digest());
    assert!(after.relations().is_empty());
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(
        &directory.path().join("registry"),
        /*maximum_records*/ 64,
    )?;
    assert_eq!(reopened.registry()?.factor_graph_source_v1(), after);
    let projection = build_prompt_factor_projection_v1(
        Generation::new(2)?,
        digest("generation-vector:2"),
        &after,
    )?;
    assert_eq!(
        projection
            .generation
            .nodes
            .iter()
            .map(|node| node.node_id.clone())
            .collect::<Vec<_>>(),
        vec![id("factor:a")?]
    );
    assert!(projection.generation.edges.is_empty());
    assert_eq!(
        projection.registry_revision,
        reopened.registry()?.revision().get()
    );
    Ok(())
}

#[test]
fn source_revision_is_preserved_as_projection_node_and_relation_support_lineage() -> TestResult<()>
{
    let fixture = Fixture::new()?;
    let source = fixture.owner.registry()?.factor_graph_source_v1();
    let projection = build_prompt_factor_projection_v1(
        Generation::new(1)?,
        digest("generation-vector"),
        &source,
    )?;
    let actual = projection
        .generation
        .nodes
        .iter()
        .flat_map(|node| node.supports.iter())
        .chain(
            projection
                .generation
                .edges
                .iter()
                .flat_map(|edge| edge.supports.iter()),
        )
        .map(|support| {
            (
                support.source_id.clone(),
                support.source_revision,
                support.source_fact_digest,
            )
        })
        .collect::<BTreeSet<_>>();
    let expected = source
        .factors()
        .iter()
        .map(|factor| {
            (
                factor.factor_id.clone(),
                source.registry_revision(),
                factor.content_digest,
            )
        })
        .chain(source.relations().iter().map(|relation| {
            (
                relation.relation_id.clone(),
                source.registry_revision(),
                relation.evidence_digest,
            )
        }))
        .collect::<BTreeSet<_>>();
    assert_eq!(actual, expected);
    assert_eq!(
        projection.generation.source_snapshot_digest,
        source.source_digest()
    );
    Ok(())
}

#[test]
fn empty_generation_vector_is_rejected_before_projection() -> TestResult<()> {
    let fixture = Fixture::new()?;
    let source = fixture.owner.registry()?.factor_graph_source_v1();
    assert_eq!(
        build_prompt_factor_projection_v1(Generation::new(1)?, Digest32::ZERO, &source),
        Err(PromptFactorProjectionErrorV1::InvalidGenerationVector)
    );
    Ok(())
}
