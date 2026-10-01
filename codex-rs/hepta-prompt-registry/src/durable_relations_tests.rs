use super::*;
use crate::PromptFactor;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fixture(root: &std::path::Path) -> DurablePromptRegistry {
    let mut owner = DurablePromptRegistry::open_state_dir(root, 64).expect("owner");
    for name in ["factor:a", "factor:b"] {
        owner
            .register_factor(PromptFactor {
                factor_id: id(name),
                proposer_id: id("proposer:test"),
                semantic_version: id("v1"),
                semantic_purpose: "verify relation evidence".to_owned(),
                authority_class: "registered_prompt_factor".to_owned(),
                eligible_objective_dimensions: vec![id("dimension:truth")],
                content_digest: digest(name),
                source: FactorSource::GovernedInternal,
                lifecycle: Lifecycle::Draft,
            })
            .expect("factor");
        owner
            .commit(|registry| {
                registry.admit_factor(&id(name), &id("reviewer:test"), digest("admission"))
            })
            .expect("admission");
    }
    owner
}

fn relation() -> PromptFactorRelation {
    PromptFactorRelation {
        relation_id: id("relation:a:b"),
        left_factor_id: id("factor:a"),
        right_factor_id: id("factor:b"),
        kind: PromptFactorRelationKind::Conflicts,
        evidence_digest: digest("relation-evidence"),
    }
}

fn sign(binding: FinalUseBinding, key: &SigningKey, grant_id: &str) -> SignedFinalUseGrant {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("time");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "relation-authority:test".to_owned(),
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

#[test]
fn governed_relation_survives_reopen_and_revocation_filters_rebuilt_source() {
    let temp = tempfile::tempdir().expect("temp");
    let registry_root = temp.path().join("registry");
    let mut owner = fixture(&registry_root);
    let key = SigningKey::from_bytes(&[42; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temp.path().join("authority"),
        "relation-authority:test".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let actor = id("reviewer:relation");
    let scope = digest("relation-scope");
    let relation = relation();
    let signed = sign(
        final_use_factor_relation_binding(
            owner.registry().expect("registry"),
            &actor,
            scope,
            &relation,
        )
        .expect("binding"),
        &key,
        "relation-grant:test",
    );
    let receipt = owner
        .register_factor_relation_final_use(&authority, &signed, &actor, scope, relation.clone())
        .expect("relation");
    assert!(!receipt.authority.grants_any());
    let before = owner.registry().expect("registry").factor_graph_source_v1();
    drop(owner);
    let mut reopened = DurablePromptRegistry::open_state_dir(&registry_root, 64).expect("reopen");
    assert_eq!(
        reopened
            .registry()
            .expect("registry")
            .factor_graph_source_v1(),
        before
    );
    reopened
        .commit(|registry| registry.revoke_factor(&id("factor:b")))
        .expect("revoke");
    drop(reopened);
    let revoked =
        DurablePromptRegistry::open_state_dir(&registry_root, 64).expect("reopen after revocation");
    assert!(
        revoked
            .registry()
            .expect("registry")
            .factor_graph_source_v1()
            .relations()
            .is_empty()
    );
    assert_eq!(
        revoked
            .registry()
            .expect("registry")
            .relations
            .get(&relation.relation_id),
        Some(&relation)
    );
}

#[test]
fn relation_grant_rejects_kind_scope_and_owner_snapshot_drift() {
    let temp = tempfile::tempdir().expect("temp");
    let mut owner = fixture(&temp.path().join("registry"));
    let key = SigningKey::from_bytes(&[42; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temp.path().join("authority"),
        "relation-authority:test".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let actor = id("reviewer:relation");
    let scope = digest("relation-scope");
    let relation = relation();
    let signed = sign(
        final_use_factor_relation_binding(
            owner.registry().expect("registry"),
            &actor,
            scope,
            &relation,
        )
        .expect("binding"),
        &key,
        "relation-grant:test",
    );
    let mut changed = relation.clone();
    changed.kind = PromptFactorRelationKind::Complements;
    for (supplied_scope, supplied_relation) in
        [(scope, changed), (digest("wrong-scope"), relation.clone())]
    {
        assert!(matches!(
            owner.register_factor_relation_final_use(
                &authority,
                &signed,
                &actor,
                supplied_scope,
                supplied_relation
            ),
            Err(DurableRegistryError::Admission(
                AdmissionError::FactorBindingMismatch
            ))
        ));
    }
    assert!(
        owner
            .registry()
            .expect("registry")
            .factor_graph_source_v1()
            .relations()
            .is_empty()
    );
    let mut unrelated = owner
        .registry()
        .expect("registry")
        .factor(&id("factor:a"))
        .expect("factor")
        .clone();
    unrelated.factor_id = id("factor:unrelated");
    unrelated.lifecycle = Lifecycle::Draft;
    owner
        .register_factor(unrelated)
        .expect("unrelated mutation");
    assert!(matches!(
        owner.register_factor_relation_final_use(&authority, &signed, &actor, scope, relation),
        Err(DurableRegistryError::Admission(
            AdmissionError::FactorBindingMismatch
        ))
    ));
}

#[test]
fn persisted_relations_enforce_identity_endpoints_and_legacy_absence() {
    let temp = tempfile::tempdir().expect("temp");
    let mut owner = fixture(&temp.path().join("registry"));
    let legacy_bytes = serde_json::to_vec(&super::super::stored_v2(
        owner.registry().expect("registry"),
    ))
    .expect("legacy encode");
    assert!(!String::from_utf8_lossy(&legacy_bytes).contains("\"relations\""));
    let legacy = serde_json::from_slice(&legacy_bytes).expect("legacy decode");
    assert_eq!(
        super::super::restore_v2(legacy, 64).expect("legacy restore"),
        owner.registry().expect("registry").clone()
    );
    owner
        .commit(|registry| registry.register_factor_relation(relation()))
        .expect("relation");
    let mut stored = super::super::stored_v2(owner.registry().expect("registry"));
    stored.relations.push(StoredRelation::encode(&relation()));
    assert!(matches!(
        super::super::restore_v2(stored, 64),
        Err(DurableRegistryError::Corrupt)
    ));
    let mut stored = super::super::stored_v2(owner.registry().expect("registry"));
    stored.relations[0].right_factor_id = "factor:missing".to_owned();
    assert!(matches!(
        super::super::restore_v2(stored, 64),
        Err(DurableRegistryError::Corrupt)
    ));
}

#[test]
fn relation_withdrawal_is_durable_terminal_and_allows_fresh_fact_identity() {
    let temp = tempfile::tempdir().expect("temp");
    let root = temp.path().join("registry");
    let mut owner = fixture(&root);
    let key = SigningKey::from_bytes(&[42; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temp.path().join("authority"),
        "relation-authority:test".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let actor = id("reviewer:relation");
    let scope = digest("relation-scope");
    let original = relation();
    let insertion = sign(
        final_use_factor_relation_binding(
            owner.registry().expect("registry"),
            &actor,
            scope,
            &original,
        )
        .expect("binding"),
        &key,
        "insert:original",
    );
    owner
        .register_factor_relation_final_use(&authority, &insertion, &actor, scope, original.clone())
        .expect("insert");
    let before = owner.registry().expect("registry").factor_graph_source_v1();
    let reason = digest("withdrawn-evidence");
    let signed = sign(
        final_use_factor_relation_revocation_binding(
            owner.registry().expect("registry"),
            &actor,
            scope,
            &original.relation_id,
            reason,
        )
        .expect("withdrawal binding"),
        &key,
        "withdraw:original",
    );
    assert!(matches!(
        owner.revoke_factor_relation_final_use(
            &authority,
            &signed,
            &actor,
            scope,
            &original.relation_id,
            digest("wrong-reason")
        ),
        Err(DurableRegistryError::Admission(
            AdmissionError::FactorBindingMismatch
        ))
    ));
    owner
        .revoke_factor_relation_final_use(
            &authority,
            &signed,
            &actor,
            scope,
            &original.relation_id,
            reason,
        )
        .expect("withdraw");
    let after = owner.registry().expect("registry").factor_graph_source_v1();
    assert_eq!(after.factors(), before.factors());
    assert!(after.relations().is_empty());
    assert_ne!(after.source_digest(), before.source_digest());
    assert_eq!(
        after.registry_revision().get(),
        before.registry_revision().get() + 1
    );
    assert_eq!(
        owner.registry().expect("registry").revocation_frontier(),
        after.registry_revision().get()
    );
    drop(owner);
    let mut owner = DurablePromptRegistry::open_state_dir(&root, 64).expect("reopen");
    assert_eq!(
        owner.registry().expect("registry").factor_graph_source_v1(),
        after
    );
    assert_eq!(
        owner
            .registry()
            .expect("registry")
            .relations
            .get(&original.relation_id),
        Some(&original)
    );
    assert!(matches!(
        owner.commit(|registry| registry.register_factor_relation(original.clone())),
        Err(DurableRegistryError::Core(crate::Error::InvalidTransition))
    ));
    let mut replacement = original.clone();
    replacement.relation_id = id("relation:a:b:corrected");
    replacement.evidence_digest = digest("corrected-evidence");
    let signed = sign(
        final_use_factor_relation_binding(
            owner.registry().expect("registry"),
            &actor,
            scope,
            &replacement,
        )
        .expect("replacement binding"),
        &key,
        "insert:replacement",
    );
    owner
        .register_factor_relation_final_use(&authority, &signed, &actor, scope, replacement.clone())
        .expect("corrected relation");
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&root, 64).expect("reopen corrected");
    assert_eq!(
        reopened
            .registry()
            .expect("registry")
            .factor_graph_source_v1()
            .relations(),
        &[replacement]
    );
    assert!(
        reopened
            .registry()
            .expect("registry")
            .relation_withdrawals
            .contains_key(&original.relation_id)
    );
}

#[test]
fn relation_withdrawal_rejects_stale_owner_cut_and_corrupt_persisted_lineage() {
    let temp = tempfile::tempdir().expect("temp");
    let mut owner = fixture(&temp.path().join("registry"));
    owner
        .commit(|registry| registry.register_factor_relation(relation()))
        .expect("relation");
    let key = SigningKey::from_bytes(&[42; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temp.path().join("authority"),
        "relation-authority:test".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let actor = id("reviewer:relation");
    let scope = digest("relation-scope");
    let reason = digest("reason");
    let signed = sign(
        final_use_factor_relation_revocation_binding(
            owner.registry().expect("registry"),
            &actor,
            scope,
            &relation().relation_id,
            reason,
        )
        .expect("binding"),
        &key,
        "withdraw:stale",
    );
    owner
        .commit(|registry| registry.retire_factor(&id("factor:b")))
        .expect("unrelated frontier mutation");
    assert!(matches!(
        owner.revoke_factor_relation_final_use(
            &authority,
            &signed,
            &actor,
            scope,
            &relation().relation_id,
            reason
        ),
        Err(DurableRegistryError::Admission(
            AdmissionError::FactorBindingMismatch
        ))
    ));
    let signed = sign(
        final_use_factor_relation_revocation_binding(
            owner.registry().expect("registry"),
            &actor,
            scope,
            &relation().relation_id,
            reason,
        )
        .expect("fresh binding"),
        &key,
        "withdraw:fresh",
    );
    owner
        .revoke_factor_relation_final_use(
            &authority,
            &signed,
            &actor,
            scope,
            &relation().relation_id,
            reason,
        )
        .expect("withdraw after endpoint retirement");
    let mut stored = super::super::stored_v2(owner.registry().expect("registry"));
    stored.relation_withdrawals[0].reason_digest = digest("corrupt").into_array();
    assert!(matches!(
        super::super::restore_v2(stored, 64),
        Err(DurableRegistryError::Corrupt)
    ));
}
