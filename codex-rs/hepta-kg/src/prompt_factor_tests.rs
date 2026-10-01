//! The durable prompt owner currently supports Unix private state directories.
#![cfg(unix)]

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
use codex_hepta_prompt_registry::final_use_revoke_binding;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct RegistryFixture {
    owner: DurablePromptRegistry,
    authority: FinalUseAuthority,
    key: SigningKey,
    directory: tempfile::TempDir,
}

impl RegistryFixture {
    fn with_conflict() -> TestResult<Self> {
        let directory = tempfile::tempdir()?;
        let key = SigningKey::from_bytes(&[61; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &directory.path().join("authority"),
            "security-owner:kg".into(),
            key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        let mut fixture = Self {
            owner: DurablePromptRegistry::open_state_dir(&directory.path().join("registry"), 64)?,
            authority,
            key,
            directory,
        };
        let reviewer = id("reviewer:independent")?;
        let scope = digest("kg:admission-scope");
        for (index, (factor_id, proposer)) in
            [("factor:a", "proposer:a"), ("factor:b", "proposer:b")]
                .into_iter()
                .enumerate()
        {
            let factor = PromptFactor {
                factor_id: id(factor_id)?,
                proposer_id: id(proposer)?,
                semantic_version: id("v1")?,
                semantic_purpose: "knowledge graph relation projection".into(),
                authority_class: "registered_prompt_factor".into(),
                eligible_objective_dimensions: vec![id("dimension:quality")?],
                content_digest: digest(factor_id),
                source: FactorSource::GovernedInternal,
                lifecycle: Lifecycle::Draft,
            };
            fixture.owner.register_factor(factor.clone())?;
            let evidence = digest(&format!("kg:admission:{factor_id}"));
            let signed = fixture.sign(
                final_use_admission_binding(&factor, &reviewer, scope, evidence)?,
                &format!("grant:kg-admit:{index}"),
                u8::try_from(index + 1)?,
            )?;
            fixture.owner.admit_factor_final_use(
                &fixture.authority,
                &signed,
                &factor.factor_id,
                scope,
                evidence,
            )?;
        }
        fixture
            .owner
            .register_factor_relation(PromptFactorRelation {
                relation_id: id("relation:a:b:conflict")?,
                left_factor_id: id("factor:a")?,
                right_factor_id: id("factor:b")?,
                kind: PromptFactorRelationKind::Conflicts,
                evidence_digest: digest("conflict-evidence"),
            })?;
        // A graph consumer reads the reopened durable owner, never a raw,
        // unpersisted domain mutation or a manufactured admission token.
        fixture.reopen()
    }

    fn sign(
        &self,
        binding: FinalUseBinding,
        grant_id: &str,
        nonce: u8,
    ) -> TestResult<SignedFinalUseGrant> {
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner:kg".into(),
            authority_epoch: 1,
            grant_id: grant_id.into(),
            nonce: [nonce; 32],
            binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 60_000,
        };
        Ok(SignedFinalUseGrant {
            signature: self.key.sign(&grant.signing_bytes()?).to_bytes().to_vec(),
            grant,
        })
    }

    fn reopen(self) -> TestResult<Self> {
        let Self {
            owner,
            authority,
            key,
            directory,
        } = self;
        let expected = owner.registry()?.clone();
        drop(owner);
        let owner = DurablePromptRegistry::open_state_dir(&directory.path().join("registry"), 64)?;
        assert_eq!(owner.registry()?, &expected);
        Ok(Self {
            owner,
            authority,
            key,
            directory,
        })
    }
}

#[test]
fn registry_factor_relations_use_the_canonical_generation_and_query_kernel() -> TestResult {
    let fixture = RegistryFixture::with_conflict()?;
    let source = fixture.owner.registry()?.factor_graph_source_v1();
    let projection = build_prompt_factor_projection_v1(
        Generation::new(1)?,
        digest("generation-vector"),
        &source,
    )?;
    projection.validate()?;
    assert_eq!(projection.generation().nodes.len(), 2);
    assert_eq!(projection.generation().edges.len(), 1);
    assert_eq!(
        projection.generation().edges[0].identity.relation,
        KnowledgeRelationKindV2::PromptConflicts
    );
    let result = crate::query_relations(
        projection.generation(),
        crate::KnowledgeRelationQueryV2 {
            query_id: id("query:prompt-factor-conflict")?,
            generation_digest: projection.generation().generation_digest,
            seed_node_ids: vec![id("factor:a")?, id("factor:b")?],
            relation_kinds: vec![KnowledgeRelationKindV2::PromptConflicts],
            valid_at_unix_seconds: None,
            maximum_edges: 8,
        },
    )?;
    assert_eq!(result.edges.len(), 1);
    assert_eq!(
        result.edges[0].supports[0].source_id,
        id("relation:a:b:conflict")?
    );
    assert!(!result.authority.grants_any());
    Ok(())
}

#[test]
fn registry_revocation_removes_prompt_relation_on_rebuild() -> TestResult {
    let mut fixture = RegistryFixture::with_conflict()?;
    let before = fixture.owner.registry()?.factor_graph_source_v1();
    let factor_id = id("factor:b")?;
    let factor = fixture
        .owner
        .registry()?
        .factor(&factor_id)
        .ok_or("factor is missing")?
        .clone();
    let actor = id("revoker:independent")?;
    let scope = digest("kg:revoke-scope");
    let reason = digest("kg:revoke-reason");
    let cutoff = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let signed = fixture.sign(
        final_use_revoke_binding(&factor, &actor, scope, reason, cutoff)?,
        "grant:kg-revoke:b",
        3,
    )?;
    fixture.owner.revoke_factor_final_use(
        &fixture.authority,
        &signed,
        &factor_id,
        &actor,
        scope,
        reason,
        cutoff,
    )?;
    fixture = fixture.reopen()?;
    let after = fixture.owner.registry()?.factor_graph_source_v1();
    assert_ne!(before.source_digest(), after.source_digest());
    assert!(after.relations().is_empty());
    let projection = build_prompt_factor_projection_v1(
        Generation::new(2)?,
        digest("generation-vector:2"),
        &after,
    )?;
    assert_eq!(projection.generation().nodes.len(), 1);
    assert!(projection.generation().edges.is_empty());
    assert_eq!(
        projection.registry_revision(),
        fixture.owner.registry()?.revision().get()
    );
    Ok(())
}

#[test]
fn source_revision_is_preserved_as_projection_support_lineage() -> TestResult {
    let fixture = RegistryFixture::with_conflict()?;
    let source = fixture.owner.registry()?.factor_graph_source_v1();
    let projection = build_prompt_factor_projection_v1(
        Generation::new(1)?,
        digest("generation-vector"),
        &source,
    )?;
    let expected = Revision::new(source.registry_revision().get())?;
    assert_eq!(
        projection.generation().edges[0].supports[0].source_revision,
        expected
    );
    Ok(())
}
