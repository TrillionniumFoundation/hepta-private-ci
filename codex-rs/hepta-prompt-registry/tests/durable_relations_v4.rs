#![cfg(unix)]

use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after epoch")
        .as_millis() as u64
}

fn register_admitted(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    key: &SigningKey,
    factor_id: &str,
    nonce_byte: u8,
) {
    let factor = PromptFactor {
        factor_id: id(factor_id),
        proposer_id: id("proposer:durable-v4-test"),
        semantic_version: id("semantic:v1"),
        semantic_purpose: "durable relation V4 qualification".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:relation-safety")],
        content_digest: digest(&format!("content:{factor_id}")),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .expect("register factor");
    let reviewer = id("reviewer:durable-v4-test");
    let scope = digest(&format!("scope:{factor_id}"));
    let evidence = digest(&format!("evidence:{factor_id}"));
    let binding = final_use_admission_binding(&factor, &reviewer, scope, evidence)
        .expect("admission binding");
    let now = now_unix_ms();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner:durable-v4-test".to_owned(),
        authority_epoch: 1,
        grant_id: format!("grant:{factor_id}"),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signed = SignedFinalUseGrant {
        signature: key
            .sign(&grant.signing_bytes().expect("grant signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .admit_factor_final_use(authority, &signed, &factor.factor_id, scope, evidence)
        .expect("admit factor");
}

fn populated_registry(root: &std::path::Path) -> Digest32 {
    let key = SigningKey::from_bytes(&[81; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &root.join("authority"),
        "security-owner:durable-v4-test".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let registry_path = root.join("registry");
    let mut registry =
        DurablePromptRegistry::open_state_dir(&registry_path, 64).expect("registry owner");
    register_admitted(&mut registry, &authority, &key, "factor:left", 1);
    register_admitted(&mut registry, &authority, &key, "factor:right", 2);
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:left-right-conflict"),
            left_factor_id: id("factor:left"),
            right_factor_id: id("factor:right"),
            kind: PromptFactorRelationKind::Conflicts,
            evidence_digest: digest("relation evidence"),
        })
        .expect("durable relation");
    registry
        .registry()
        .expect("authoritative registry")
        .snapshot_digest()
}

#[test]
fn schema_v4_persists_relations_and_reopens_with_exact_digest() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let expected_digest = populated_registry(temporary.path());
    let manifest: serde_json::Value = serde_json::from_slice(
        &std::fs::read(temporary.path().join("registry/registry.json"))
            .expect("read manifest"),
    )
    .expect("parse manifest");
    assert_eq!(manifest["schema"].as_u64(), Some(4));
    assert_eq!(
        manifest["state"]["relations"]
            .as_array()
            .expect("relations")
            .len(),
        1
    );

    let reopened = DurablePromptRegistry::open_state_dir(
        &temporary.path().join("registry"),
        64,
    )
    .expect("reopen V4 registry");
    let current = reopened.registry().expect("authoritative reopened image");
    assert_eq!(current.snapshot_digest(), expected_digest);
    let graph = current.factor_graph_source_v1();
    assert_eq!(graph.relations().len(), 1);
    assert_eq!(
        graph.relations()[0].relation_id,
        id("relation:left-right-conflict")
    );
    assert_eq!(
        graph.relations()[0].kind,
        PromptFactorRelationKind::Conflicts
    );
}

#[test]
fn corrupt_relation_evidence_fails_closed_on_reopen() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let _ = populated_registry(temporary.path());
    let manifest_path = temporary.path().join("registry/registry.json");
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&manifest_path).expect("read manifest"))
            .expect("parse manifest");
    manifest["state"]["relations"][0]["evidence_digest"] =
        serde_json::Value::Array(vec![serde_json::Value::from(0); 32]);
    let bytes = serde_json::to_vec(&manifest).expect("encode corrupt manifest");
    let mut file = OpenOptions::new()
        .write(true)
        .truncate(true)
        .mode(0o600)
        .open(&manifest_path)
        .expect("open corrupt manifest");
    file.write_all(&bytes).expect("write corrupt manifest");
    file.sync_all().expect("sync corrupt manifest");

    let error = DurablePromptRegistry::open_state_dir(
        &temporary.path().join("registry"),
        64,
    )
    .expect_err("corrupt relation must fail closed");
    assert!(matches!(error, DurableRegistryError::Corrupt));
}
