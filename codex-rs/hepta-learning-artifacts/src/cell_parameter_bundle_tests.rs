use super::*;
use crate::CellParameterBundleOwnerV1;
use crate::decode_cell_parameter_bundle_owner_snapshot_v1;
use crate::decode_cell_parameter_bundle_wire_v1;
use crate::encode_cell_parameter_bundle_wire_v1;

use codex_hepta_types::Generation;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("non-zero generation")
}

fn artifact(label: &str) -> CasArtifactRefV1 {
    CasArtifactRefV1 {
        artifact_id: id(&format!("artifact:{label}")),
        content_digest: digest(&format!("content:{label}")),
        manifest_digest: digest(&format!("manifest:{label}")),
        compatibility_digest: digest(&format!("compatibility:{label}")),
        encoded_size_bytes: 32,
    }
}

fn component(
    label: &str,
    mode: CellComponentModeV1,
    source: Option<Digest32>,
) -> CellComponentRefV1 {
    let artifact = artifact(label);
    CellComponentRefV1 {
        component_id: id(&format!("component:{label}")),
        mode,
        artifact,
        source_artifact_digest: source,
        compatibility_digest: digest(&format!("component-compatibility:{label}")),
    }
}

fn manifest(
    base: &CasArtifactRefV1,
    adapter: &CellComponentRefV1,
    head: &CellComponentRefV1,
) -> CellArtifactManifestV1 {
    CellArtifactManifestV1::from_entries(
        id("manifest:cell"),
        vec![
            base.clone(),
            adapter.artifact.clone(),
            head.artifact.clone(),
        ],
    )
    .expect("manifest")
}

fn genesis() -> CellParameterBundleV1 {
    let base = artifact("base");
    let adapter = component("adapter-v1", CellComponentModeV1::Reinitialized, None);
    let head = component("head-v1", CellComponentModeV1::Reinitialized, None);
    let mut bundle = CellParameterBundleV1 {
        bundle_id: id("bundle:cell:1"),
        identity: CellIdentityV1 {
            cell_id: id("cell:decision"),
            child_id: id("child:decision:1"),
            generation: generation(1),
            scope_digest: digest("scope:decision"),
            lineage_digest: Digest32::ZERO,
        },
        parent_predecessor: None,
        shared_base: base.clone(),
        adapter: adapter.clone(),
        head: head.clone(),
        state_schema_digest: digest("state-schema:v1"),
        optimizer_lineage_digest: digest("optimizer:v1"),
        artifact_manifest: manifest(&base, &adapter, &head),
        rollback_target: None,
        bundle_digest: Digest32::ZERO,
    };
    bundle.seal().expect("sealed genesis");
    bundle
}

fn successor(parent: &CellParameterBundleV1) -> CellParameterBundleV1 {
    let base = parent.shared_base.clone();
    let adapter = component(
        "adapter-v1",
        CellComponentModeV1::Cloned,
        Some(parent.adapter.artifact.content_digest),
    );
    let head = component("head-v2", CellComponentModeV1::Reinitialized, None);
    let mut bundle = CellParameterBundleV1 {
        bundle_id: id("bundle:cell:2"),
        identity: CellIdentityV1 {
            cell_id: parent.identity.cell_id.clone(),
            child_id: id("child:decision:2"),
            generation: generation(2),
            scope_digest: parent.identity.scope_digest,
            lineage_digest: Digest32::ZERO,
        },
        parent_predecessor: Some(CellBundlePredecessorV1 {
            bundle_id: parent.bundle_id.clone(),
            bundle_digest: parent.bundle_digest,
            generation: parent.identity.generation,
            lineage_digest: parent.identity.lineage_digest,
        }),
        shared_base: base.clone(),
        adapter: adapter.clone(),
        head: head.clone(),
        state_schema_digest: parent.state_schema_digest,
        optimizer_lineage_digest: digest("optimizer:v2"),
        artifact_manifest: manifest(&base, &adapter, &head),
        rollback_target: None,
        bundle_digest: Digest32::ZERO,
    };
    bundle.seal().expect("sealed successor");
    bundle
}

#[test]
fn schema_and_owner_are_static_and_authority_free() {
    assert_eq!(
        CELL_PARAMETER_BUNDLE_SCHEMA_V1,
        "hepta.learning-artifacts.cell-parameter-bundle.v1"
    );
    assert_eq!(CELL_PARAMETER_BUNDLE_OWNER_V1, "learning.artifacts");
    let owner = CellParameterBundleOwnerV1::new(digest("scope:decision")).expect("owner");
    assert_eq!(owner.head_digest(), Digest32::ZERO);
}

#[test]
fn sealed_bundle_round_trip_binds_lineage_manifest_and_bundle_digest() {
    let bundle = genesis();
    bundle.validate().expect("valid bundle");
    assert!(!bundle.identity.lineage_digest.is_zero());
    assert!(!bundle.artifact_manifest.cas_root_digest.is_zero());
    assert!(!bundle.artifact_manifest.manifest_digest.is_zero());
    assert!(!bundle.bundle_digest.is_zero());
}

#[test]
fn malformed_inheritance_fails_closed() {
    let parent = genesis();
    let mut child = successor(&parent);
    child.adapter.source_artifact_digest = Some(digest("wrong-source"));
    assert!(matches!(
        child.seal(),
        Err(CellParameterBundleErrorV1::MalformedInheritance(_))
    ));

    let mut owner = CellParameterBundleOwnerV1::new(parent.identity.scope_digest).expect("owner");
    owner
        .append(Digest32::ZERO, parent)
        .expect("genesis append");
    let mut base_replacement = successor(owner.current().expect("current"));
    base_replacement.shared_base = artifact("replacement-base");
    base_replacement.artifact_manifest = manifest(
        &base_replacement.shared_base,
        &base_replacement.adapter,
        &base_replacement.head,
    );
    base_replacement
        .seal()
        .expect("sealed replacement candidate");
    assert!(matches!(
        owner.append(owner.head_digest(), base_replacement),
        Err(CellParameterBundleErrorV1::MalformedInheritance(_))
    ));
}

#[test]
fn digest_mismatch_and_missing_predecessor_fail_closed() {
    let mut bundle = genesis();
    bundle.artifact_manifest.entries[0].content_digest = digest("tampered");
    assert!(matches!(
        bundle.validate(),
        Err(CellParameterBundleErrorV1::DigestMismatch("CAS root"))
    ));

    let mut missing = genesis();
    missing.identity.generation = generation(2);
    missing.identity.lineage_digest = Digest32::ZERO;
    assert!(matches!(
        missing.seal(),
        Err(CellParameterBundleErrorV1::MissingPredecessor)
    ));
}

#[test]
fn owner_cas_append_receipt_replay_and_predecessor_check() {
    let mut owner = CellParameterBundleOwnerV1::new(digest("scope:decision")).expect("owner");
    let first = genesis();
    let receipt = owner
        .append(Digest32::ZERO, first.clone())
        .expect("genesis append");
    assert_eq!(
        receipt.disposition,
        CellParameterBundleAppendDispositionV1::Appended
    );
    let replay = owner
        .append(Digest32::ZERO, first.clone())
        .expect("idempotent replay");
    assert_eq!(
        replay.disposition,
        CellParameterBundleAppendDispositionV1::IdempotentReplay
    );
    assert!(matches!(
        owner.publish(CellParameterBundlePublishRequestV1 {
            operation_id: id("operation:duplicate-bundle"),
            expected_head_digest: owner.head_digest(),
            bundle: first,
        }),
        Err(CellParameterBundleErrorV1::IdentityConflict(_))
    ));
    assert_eq!(
        owner
            .replay_receipt(&receipt)
            .expect("receipt replay")
            .head_digest,
        receipt.head_digest
    );
    let mut forged_receipt = receipt;
    forged_receipt.sequence += 1;
    assert!(matches!(
        owner.replay_receipt(&forged_receipt),
        Err(CellParameterBundleErrorV1::ReceiptMismatch)
    ));

    let child = successor(owner.current().expect("current"));
    let missing_parent = CellParameterBundleV1 {
        parent_predecessor: Some(CellBundlePredecessorV1 {
            bundle_id: id("bundle:missing"),
            bundle_digest: digest("missing-bundle"),
            generation: generation(1),
            lineage_digest: digest("missing-lineage"),
        }),
        ..child.clone()
    };
    let mut missing_parent = missing_parent;
    missing_parent.identity.lineage_digest = Digest32::ZERO;
    missing_parent.bundle_digest = Digest32::ZERO;
    missing_parent
        .seal()
        .expect("sealed missing-parent candidate");
    assert!(matches!(
        owner.append(owner.head_digest(), missing_parent),
        Err(CellParameterBundleErrorV1::PredecessorNotFound(_))
    ));
    owner
        .append(owner.head_digest(), child)
        .expect("successor append");
}

#[test]
fn rollback_is_a_new_generation_and_conflicts_fail_closed() {
    let mut owner = CellParameterBundleOwnerV1::new(digest("scope:decision")).expect("owner");
    let first = genesis();
    let first_receipt = owner.append(Digest32::ZERO, first).expect("first");
    let second = successor(owner.current().expect("first current"));
    owner.append(owner.head_digest(), second).expect("second");

    assert!(matches!(
        owner.rollback_to_old_bundle(Digest32::ZERO, &id("bundle:cell:1"), id("op:stale")),
        Err(CellParameterBundleErrorV1::CasConflict)
    ));
    let current_id = owner.current().expect("current").bundle_id.clone();
    assert!(matches!(
        owner.rollback_to_old_bundle(owner.head_digest(), &current_id, id("op:current")),
        Err(CellParameterBundleErrorV1::RollbackConflict)
    ));

    let receipt = owner
        .rollback_to_old_bundle(
            owner.head_digest(),
            &id("bundle:cell:1"),
            id("bundle:cell:rollback:3"),
        )
        .expect("rollback");
    assert_eq!(receipt.sequence, 3);
    assert_eq!(
        owner
            .current()
            .expect("rollback current")
            .identity
            .generation,
        generation(3)
    );
    assert_eq!(
        owner
            .replay_receipt(&receipt)
            .expect("rollback receipt replay")
            .bundle_id,
        receipt.bundle_id
    );
    assert_eq!(first_receipt.sequence, 1);
}

#[test]
fn bundle_wire_round_trip_rejects_unknown_fields_and_owner_receipt_drift() {
    let bundle = genesis();
    let encoded = encode_cell_parameter_bundle_wire_v1(&bundle).expect("wire");
    assert_eq!(
        decode_cell_parameter_bundle_wire_v1(&encoded).expect("decode"),
        bundle
    );

    let mut unknown: serde_json::Value = serde_json::from_slice(&encoded).expect("json");
    unknown["critical_unknown"] = serde_json::json!(true);
    assert!(
        decode_cell_parameter_bundle_wire_v1(&serde_json::to_vec(&unknown).expect("unknown wire"))
            .is_err()
    );

    let mut owner = CellParameterBundleOwnerV1::new(bundle.identity.scope_digest).expect("owner");
    let receipt = owner.append(Digest32::ZERO, bundle).expect("append");
    let reopened =
        CellParameterBundleOwnerV1::reopen_wire(&owner.snapshot_wire().expect("snapshot"))
            .expect("reopen");
    assert_eq!(reopened.records(), owner.records());
    assert_eq!(reopened.head_digest(), owner.head_digest());
    let mut snapshot: serde_json::Value =
        serde_json::from_slice(&owner.snapshot_wire().expect("snapshot")).expect("json");
    snapshot["receipts"][0]["head_digest"] =
        serde_json::json!(Digest32::of_bytes(b"drift").to_string());
    let drift = serde_json::to_vec(&snapshot).expect("drift wire");
    assert!(decode_cell_parameter_bundle_owner_snapshot_v1(&drift).is_ok());
    assert!(CellParameterBundleOwnerV1::reopen_wire(&drift).is_err());
    assert_eq!(
        owner.replay_receipt(&receipt).expect("receipt").head_digest,
        receipt.head_digest
    );
}
