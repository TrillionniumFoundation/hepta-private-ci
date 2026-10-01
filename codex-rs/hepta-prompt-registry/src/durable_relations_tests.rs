//! Physical relation-image recovery; fixture admissions are not product authority.
use super::*;
use crate::TestMust;

fn id(value: &str) -> StableId {
    StableId::new(value).must("identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn seed(owner: &mut DurablePromptRegistry) {
    owner
        .commit(|core| {
            for name in ["a", "b"] {
                let factor_id = id(&format!("factor:{name}"));
                core.register_factor(PromptFactor {
                    factor_id: factor_id.clone(),
                    proposer_id: id("proposer:storage"),
                    semantic_version: id("v1"),
                    semantic_purpose: "relation storage fixture".into(),
                    authority_class: "registered_prompt_factor".into(),
                    eligible_objective_dimensions: vec![id("dimension:quality")],
                    content_digest: digest(name),
                    source: FactorSource::GovernedInternal,
                    lifecycle: Lifecycle::Draft,
                })?;
                core.admit_factor(&factor_id, &id("reviewer:storage"), digest("review"))?;
            }
            Ok(core.receipt(crate::MutationDisposition::Inserted))
        })
        .must("fixture factors");
}

fn relation() -> PromptFactorRelation {
    PromptFactorRelation {
        relation_id: id("relation:a:b"),
        left_factor_id: id("factor:a"),
        right_factor_id: id("factor:b"),
        kind: crate::PromptFactorRelationKind::Conflicts,
        evidence_digest: digest("relation-evidence"),
    }
}

#[test]
fn relation_snapshot_reopens_and_retains_revoked_history_without_projecting_it() {
    let temp = tempfile::tempdir().must("temporary directory");
    let root = temp.path().join("registry");
    let mut owner = DurablePromptRegistry::open_state_dir(&root, 64).must("owner");
    seed(&mut owner);
    owner.register_factor_relation(relation()).must("relation");
    let expected = owner.registry().must("registry").clone();
    drop(owner);
    let mut reopened = DurablePromptRegistry::open_state_dir(&root, 64).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
    reopened
        .commit(|core| {
            core.revoke_factor_governed(
                &id("factor:b"),
                &id("revoker:storage"),
                digest("reason"),
                1,
            )
        })
        .must("fixture revocation");
    let revoked = reopened.registry().must("registry").clone();
    assert_eq!(revoked.relations.len(), 1);
    assert!(revoked.factor_graph_source_v1().relations().is_empty());
    drop(reopened);
    let reopened = DurablePromptRegistry::open_state_dir(&root, 64).must("reopen revoked owner");
    assert_eq!(reopened.registry().must("registry"), &revoked);
    assert!(
        reopened
            .registry()
            .must("registry")
            .factor_graph_source_v1()
            .relations()
            .is_empty()
    );
}

#[test]
fn old_v2_and_v3_images_keep_their_digest_and_upgrade_with_the_next_relation() {
    for schema in [2, 3] {
        let temp = tempfile::tempdir().must("temporary directory");
        let root = temp.path().join("registry");
        let mut owner = DurablePromptRegistry::open_state_dir(&root, 64).must("owner");
        seed(&mut owner);
        let expected = owner.registry().must("registry").clone();
        let bytes = if schema == 2 {
            serde_json::to_vec(&stored_v2(&expected)).must("original V2 semantic image")
        } else {
            serde_json::to_vec(&payloads::StoredV3 {
                schema: 3,
                state: stored_metadata(&expected),
                payload_references: owner.store.payloads.references(),
            })
            .must("original V3 extent image")
        };
        drop(owner);
        let manifest = root.join("registry.json");
        std::fs::write(&manifest, &bytes).must("legacy image");
        let mut reopened = DurablePromptRegistry::open_state_dir(&root, 64).must("legacy reopen");
        assert_eq!(reopened.registry().must("registry"), &expected);
        if schema == 3 {
            assert_eq!(std::fs::read(&manifest).must("unchanged V3"), bytes);
        }
        reopened
            .register_factor_relation(relation())
            .must("upgrade through original owner");
        let upgraded = reopened.registry().must("registry").clone();
        drop(reopened);
        let reopened = DurablePromptRegistry::open_state_dir(&root, 64).must("V4 reopen");
        assert_eq!(reopened.registry().must("registry"), &upgraded);
    }
}

#[test]
fn invalid_relation_images_never_rewrite_snapshot_or_trim_payload_history() {
    for fault in [
        "duplicate",
        "reversed",
        "missing",
        "zero-evidence",
        "changed-evidence",
    ] {
        let temp = tempfile::tempdir().must("temporary directory");
        let root = temp.path().join("registry");
        let mut owner = DurablePromptRegistry::open_state_dir(&root, 64).must("owner");
        seed(&mut owner);
        owner.register_factor_relation(relation()).must("relation");
        drop(owner);
        let manifest = root.join("registry.json");
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&manifest).must("manifest")).must("JSON");
        match fault {
            "duplicate" => {
                let repeated = value["relations"][0].clone();
                value["relations"]
                    .as_array_mut()
                    .must("relations")
                    .push(repeated);
            }
            "reversed" => value["relations"][0]["left_factor_id"] = "factor:b".into(),
            "missing" => value["relations"][0]["right_factor_id"] = "factor:missing".into(),
            "zero-evidence" => {
                value["relations"][0]["evidence_digest"] = serde_json::json!(vec![0; 32])
            }
            "changed-evidence" => {
                value["relations"][0]["evidence_digest"] =
                    serde_json::json!(digest("forged").into_array())
            }
            _ => unreachable!(),
        }
        let corrupt = serde_json::to_vec(&value).must("corrupt image");
        std::fs::write(&manifest, &corrupt).must("write fault");
        let payload_path = root.join(payloads::FILE_NAME);
        let before = std::fs::read(&payload_path).must("payload history");
        assert!(
            matches!(
                DurablePromptRegistry::open_state_dir(&root, 64),
                Err(DurableRegistryError::Corrupt)
            ),
            "{fault}"
        );
        assert_eq!(std::fs::read(&manifest).must("unchanged manifest"), corrupt);
        assert_eq!(
            std::fs::read(&payload_path).must("unchanged payload history"),
            before
        );
    }
}

#[test]
fn relations_use_the_original_owner_lock_and_record_capacity() {
    let temp = tempfile::tempdir().must("temporary directory");
    let root = temp.path().join("registry");
    let mut owner = DurablePromptRegistry::open_state_dir(&root, 3).must("owner");
    seed(&mut owner);
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&root, 3),
        Err(DurableRegistryError::StateLocked)
    ));
    owner
        .register_factor_relation(relation())
        .must("last reserved relation");
    let before = (
        owner.registry().must("registry").clone(),
        std::fs::read(root.join("registry.json")).must("manifest"),
    );
    let mut extra = relation();
    extra.relation_id = id("relation:a:b:second");
    extra.kind = crate::PromptFactorRelationKind::Complements;
    assert!(matches!(
        owner.register_factor_relation(extra),
        Err(DurableRegistryError::Core(Error::CapacityExceeded))
    ));
    assert_eq!(
        (
            owner.registry().must("registry").clone(),
            std::fs::read(root.join("registry.json")).must("manifest")
        ),
        before
    );
}
