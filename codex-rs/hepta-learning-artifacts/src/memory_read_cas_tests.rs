use super::*;
use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellCapabilityProfileV1;
use codex_hepta_types::CellPersistenceClassV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellUpdateModeV1;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(seed: u8) -> Digest32 {
    Digest32::from_array([seed; 32])
}

fn definition(
    bundle_digest: Digest32,
    bundle_size: u64,
) -> (CellDefinitionV2, CellParameterBundleManifestV1) {
    let profile = CellCapabilityProfileV1 {
        role: CellRoleV1::MemoryRead,
        observation_schema_digest: digest(1),
        output_schema_digest: digest(2),
        state_schema_digest: digest(3),
        input_port_digest: digest(4),
        output_port_digest: digest(5),
        termination_port_digest: digest(6),
        owner_module: id("hepta-memory-retrieval::retrieve"),
        persistence_class: CellPersistenceClassV1::Checkpointed,
        update_mode: CellUpdateModeV1::OutcomeProposal,
        fallback_role: Some(CellRoleV1::Representation),
        objective_digest: digest(7),
        resource_budget_digest: digest(8),
        evaluation_profile_digest: digest(9),
        authority: AuthorityPosture::DENY_ALL,
    };
    let definition = CellDefinitionV2 {
        cell_id: id("cell.memory-read.cas"),
        generation: Generation::new(2).expect("generation"),
        scope_digest: digest(10),
        lineage_digest: digest(11),
        role: CellRoleV1::MemoryRead,
        state_schema_digest: profile.state_schema_digest,
        parameter_bundle_digest: bundle_digest,
        port_abi_digest: digest(13),
        owner_module: profile.owner_module.clone(),
        objective_digest: profile.objective_digest,
        fallback_role: profile.fallback_role,
        evidence_owner: id("observer.memory-read.cas"),
        capability_profile: profile,
        authority: AuthorityPosture::DENY_ALL,
    };
    let mut manifest = CellParameterBundleManifestV1 {
        artifact_id: definition.cell_id.clone(),
        cell_id: definition.cell_id.clone(),
        parent_artifact_id: id("cell.memory-read.cas.parent"),
        generation: definition.generation,
        parent_bundle_digest: digest(20),
        child_bundle_digest: bundle_digest,
        scope_digest: definition.scope_digest,
        definition_digest: definition.content_digest().expect("definition"),
        lineage_digest: definition.lineage_digest,
        objective_digest: definition.objective_digest,
        compatibility_digest: digest(21),
        inheritance_digest: digest(22),
        split_digest: digest(23),
        producer_id: id("producer.memory-read.cas"),
        encoded_size_bytes: bundle_size,
        manifest_digest: Digest32::ZERO,
    };
    manifest.manifest_digest = manifest.content_digest();
    (definition, manifest)
}

fn registry(
    manifest: &CellParameterBundleManifestV1,
    definition: &CellDefinitionV2,
) -> ArtifactRegistry {
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("event.memory-read.cas.parent"),
            manifest: ArtifactManifest {
                artifact_id: manifest.parent_artifact_id.clone(),
                kind: ArtifactKind::Parameters,
                generation: Generation::new(1).expect("generation"),
                predecessor_id: None,
                content_digest: manifest.parent_bundle_digest,
                objective_digest: definition.objective_digest,
                support_digest: definition.lineage_digest,
                producer_id: id("producer.memory-read.cas.parent"),
                compatibility_digest: manifest.compatibility_digest,
                encoded_size_bytes: 32,
            },
        })
        .expect("parent");
    registry
        .append(ArtifactEvent::Register {
            event_id: id("event.memory-read.cas.child"),
            manifest: manifest.as_registry_manifest(),
        })
        .expect("child");
    registry
}

#[test]
fn materialize_reload_binds_exact_bundle_bytes_and_signed_cas_receipts() {
    let bundle = b"memory-cell-bundle-v1\0weights";
    let bundle_digest = Digest32::of_bytes(bundle);
    let (definition, manifest) = definition(bundle_digest, bundle.len() as u64);
    let registry = registry(&manifest, &definition);
    let owner = MemoryReadArtifactOwnerV1::new(id("owner.memory-read.cas")).expect("owner");
    let cas_owner = ArtifactCasOwnerV1::new(
        id("cas-owner.memory-read"),
        SigningKey::from_bytes(&[41; 32]),
    )
    .expect("cas owner");
    let root = std::env::temp_dir().join(format!("hepta-memory-read-cas-{}", std::process::id()));
    std::fs::create_dir_all(&root).expect("root");
    let relative = std::path::Path::new("bundle.bin");
    let materialized = owner
        .materialize_bundle(
            &cas_owner,
            id("op.memory-read.materialize"),
            &root,
            relative,
            &registry,
            definition.clone(),
            manifest.clone(),
            bundle,
            None,
            None,
        )
        .expect("materialize");
    assert_eq!(materialized.bundle_digest, bundle_digest);
    assert_eq!(materialized.encoded_size_bytes, bundle.len() as u64);
    materialized.artifact.validate().expect("artifact");
    materialized
        .write_receipt
        .verify(&SigningKey::from_bytes(&[41; 32]).verifying_key())
        .expect("write signature");

    let reload = owner
        .reload_bundle(
            &cas_owner,
            id("op.memory-read.reload"),
            std::fs::File::open(root.join(relative)).expect("bundle file"),
            &registry,
            definition,
            manifest,
            &materialized.write_receipt,
            relative,
            None,
            None,
        )
        .expect("reload");
    assert_eq!(reload.payload, bundle);
    assert_eq!(reload.load_receipt.payload_digest, bundle_digest);
    reload.validate().expect("reload witness");
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn materialize_rejects_digest_or_size_substitution_before_cas_write() {
    let bundle = b"memory-cell-bundle-v1";
    let (definition, manifest) = definition(digest(99), bundle.len() as u64);
    let registry = registry(&manifest, &definition);
    let owner = MemoryReadArtifactOwnerV1::new(id("owner.memory-read.cas.reject")).expect("owner");
    let cas_owner = ArtifactCasOwnerV1::new(
        id("cas-owner.memory-read.reject"),
        SigningKey::from_bytes(&[42; 32]),
    )
    .expect("cas owner");
    let root = std::env::temp_dir().join(format!(
        "hepta-memory-read-cas-reject-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&root).expect("root");
    let result = owner.materialize_bundle(
        &cas_owner,
        id("op.memory-read.reject"),
        &root,
        "bundle.bin",
        &registry,
        definition,
        manifest,
        bundle,
        None,
        None,
    );
    assert!(matches!(
        result,
        Err(MemoryReadBundleOwnerErrorV1::Binding("bundle bytes"))
    ));
    assert!(!root.join("bundle.bin").exists());
    std::fs::remove_dir_all(root).expect("cleanup");
}
