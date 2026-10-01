//! Durable source regression tests; fixture admission is not product authority.

use super::*;
use crate::MutationDisposition;
use crate::PromptFactor;
use crate::TestMust;

fn id(value: &str) -> StableId {
    StableId::new(value).must("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn relation() -> PromptFactorRelation {
    PromptFactorRelation {
        relation_id: id("relation:a:b"),
        left_factor_id: id("factor:a"),
        right_factor_id: id("factor:b"),
        kind: PromptFactorRelationKind::Conflicts,
        evidence_digest: digest("governed relation evidence"),
    }
}

fn owner(path: &std::path::Path, maximum: usize) -> DurablePromptRegistry {
    let mut owner = DurablePromptRegistry::open_state_dir(path, maximum).must("owner");
    owner
        .commit(|core| {
            for factor_id in ["factor:a", "factor:b"] {
                core.register_factor(PromptFactor {
                    factor_id: id(factor_id),
                    proposer_id: id("proposer:fixture"),
                    semantic_version: id("v1"),
                    semantic_purpose: "durable relation fixture".to_owned(),
                    authority_class: "registered_prompt_factor".to_owned(),
                    eligible_objective_dimensions: vec![id("dimension:truth")],
                    content_digest: digest(factor_id),
                    source: FactorSource::GovernedInternal,
                    lifecycle: Lifecycle::Draft,
                })?;
                core.admit_factor(&id(factor_id), &id("reviewer:fixture"), digest("admission"))?;
            }
            Ok(core.receipt(MutationDisposition::Inserted))
        })
        .must("fixture factors");
    owner
}

#[test]
fn restart_preserves_complete_graph_source_and_revocation_never_resurrects_relation() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = owner(&path, 64);
    owner.register_factor_relation(relation()).must("relation");
    let expected = owner.registry().must("registry").clone();
    let source = expected.factor_graph_source_v1();
    source.validate().must("complete source");
    assert_eq!(source.relations(), &[relation()]);
    drop(owner);

    let mut reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
    assert_eq!(
        reopened
            .registry()
            .must("registry")
            .factor_graph_source_v1(),
        source
    );
    let manifest = path.join("registry.json");
    let before = std::fs::read(&manifest).must("manifest");
    assert_eq!(
        reopened
            .register_factor_relation(relation())
            .must("idempotent relation")
            .disposition,
        MutationDisposition::Unchanged
    );
    assert_eq!(std::fs::read(&manifest).must("unchanged manifest"), before);
    reopened
        .revoke_factor(
            &id("factor:b"),
            &id("operator:fixture"),
            digest("revocation"),
            7,
        )
        .must("revoke endpoint");
    let revoked = reopened.registry().must("registry").clone();
    drop(reopened);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen revoked");
    assert_eq!(reopened.registry().must("registry"), &revoked);
    let source = reopened
        .registry()
        .must("registry")
        .factor_graph_source_v1();
    source.validate().must("revoked source");
    assert!(source.relations().is_empty());
    assert_eq!(revoked.relations.len(), 1);
}

#[test]
fn missing_optional_relations_reopens_legacy_metadata_without_rewrite() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let owner = owner(&path, 64);
    let expected = owner.registry().must("registry").clone();
    drop(owner);
    let manifest = path.join("registry.json");
    let bytes = std::fs::read(&manifest).must("manifest");
    let value: serde_json::Value = serde_json::from_slice(&bytes).must("manifest json");
    assert!(value["state"].get("relations").is_none());
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("legacy reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
    assert_eq!(std::fs::read(&manifest).must("unchanged manifest"), bytes);
}

#[test]
fn relation_capacity_and_precommit_failure_preserve_predecessor() {
    let temp = tempfile::tempdir().must("temp");
    let full_path = temp.path().join("full");
    let mut full = owner(&full_path, 2);
    let predecessor = full.registry().must("registry").clone();
    assert!(matches!(
        full.register_factor_relation(relation()),
        Err(DurableRegistryError::Core(crate::Error::CapacityExceeded))
    ));
    assert_eq!(full.registry().must("registry"), &predecessor);
    drop(full);
    let reopened = DurablePromptRegistry::open_state_dir(&full_path, 2).must("reopen full");
    assert_eq!(reopened.registry().must("registry"), &predecessor);

    let path = temp.path().join("precommit");
    let mut owner = owner(&path, 64);
    let predecessor = owner.registry().must("registry").clone();
    let manifest = path.join("registry.json");
    let before = std::fs::read(&manifest).must("manifest");
    owner.fail_storage_full_before_rename_once();
    assert!(matches!(
        owner.register_factor_relation(relation()),
        Err(DurableRegistryError::StorageFull)
    ));
    assert!(!owner.requires_reopen());
    assert_eq!(owner.registry().must("registry"), &predecessor);
    assert_eq!(std::fs::read(&manifest).must("manifest"), before);
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen predecessor");
    assert_eq!(reopened.registry().must("registry"), &predecessor);
}

#[test]
fn relation_unknown_commit_requires_reopen_and_reconciles_selected_source() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = owner(&path, 64);
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.register_factor_relation(relation()),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(owner.requires_reopen());
    assert!(matches!(
        owner.registry(),
        Err(DurableRegistryError::ReopenRequired)
    ));
    assert!(matches!(
        owner.register_factor_relation(relation()),
        Err(DurableRegistryError::ReopenRequired)
    ));
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reconcile rename");
    let source = reopened
        .registry()
        .must("registry")
        .factor_graph_source_v1();
    source.validate().must("source");
    assert_eq!(source.relations(), &[relation()]);
}

#[test]
fn restored_relations_reject_invalid_owner_endpoints_evidence_identity_and_capacity() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = owner(&path, 3);
    owner.register_factor_relation(relation()).must("relation");
    let valid = owner.registry().must("registry").clone();
    for fault in [
        "missing",
        "external",
        "draft",
        "reversed",
        "evidence",
        "duplicate",
    ] {
        let mut core = valid.clone();
        match fault {
            "missing" => {
                core.relations
                    .get_mut(&id("relation:a:b"))
                    .must("relation")
                    .right_factor_id = id("factor:missing")
            }
            "external" => {
                core.factors.get_mut(&id("factor:b")).must("factor").source =
                    FactorSource::ExternalUntrusted
            }
            "draft" => {
                core.factors
                    .get_mut(&id("factor:b"))
                    .must("factor")
                    .lifecycle = Lifecycle::Draft
            }
            "reversed" => {
                core.relations
                    .get_mut(&id("relation:a:b"))
                    .must("relation")
                    .left_factor_id = id("factor:b")
            }
            "evidence" => {
                core.relations
                    .get_mut(&id("relation:a:b"))
                    .must("relation")
                    .evidence_digest = Digest32::ZERO
            }
            "duplicate" => {
                let duplicate = PromptFactorRelation {
                    relation_id: id("relation:duplicate"),
                    ..relation()
                };
                core.relations
                    .insert(duplicate.relation_id.clone(), duplicate);
                core.maximum_records = 64;
            }
            _ => unreachable!(),
        }
        let stored = super::super::stored_v2(&core);
        assert!(
            matches!(
                super::super::restore_v2(stored, core.maximum_records),
                Err(DurableRegistryError::Corrupt)
            ),
            "{fault}"
        );
    }
    let mut never_admitted = PromptRegistry::new(3).must("core");
    for factor in valid.factors.values() {
        never_admitted
            .register_factor(PromptFactor {
                lifecycle: Lifecycle::Draft,
                ..factor.clone()
            })
            .must("factor");
    }
    never_admitted
        .admit_factor(
            &id("factor:a"),
            &id("reviewer:fixture"),
            digest("admission"),
        )
        .must("admit one endpoint");
    never_admitted
        .revoke_factor(&id("factor:b"))
        .must("revoke draft endpoint");
    never_admitted
        .relations
        .insert(relation().relation_id, relation());
    assert!(matches!(
        super::super::restore_v2(super::super::stored_v2(&never_admitted), 3),
        Err(DurableRegistryError::Corrupt)
    ));
    let mut stored = super::super::stored_v2(&valid);
    stored.relations.push(encode(&valid).remove(0));
    assert!(matches!(
        super::super::restore_v2(stored, 3),
        Err(DurableRegistryError::Corrupt)
    ));
    let mut stored = super::super::stored_v2(&valid);
    stored.relations[0].kind = 99;
    assert!(matches!(
        super::super::restore_v2(stored, 3),
        Err(DurableRegistryError::Corrupt)
    ));
    let mut too_many = valid;
    too_many.maximum_records = 2;
    assert!(matches!(
        super::super::restore_v2(super::super::stored_v2(&too_many), 2),
        Err(DurableRegistryError::CapacityExceeded)
    ));
}
