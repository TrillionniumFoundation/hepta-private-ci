//! Rejection order at the durable owner, before decoding or payload I/O.

use super::*;
use crate::TestMust;

#[test]
fn invalid_configuration_does_not_publish_an_owner_marker() {
    let temp = tempfile::tempdir().must("temporary directory");
    let path = temp.path().join("owner");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 0),
        Err(DurableRegistryError::Core(_))
    ));
    assert!(!path.exists());
    DurablePromptRegistry::open_state_dir(&path, 8).must("valid initial open");
}

#[test]
fn v2_record_capacity_is_rejected_before_invalid_record_decoding() {
    let core = PromptRegistry::new(1).must("core");
    let mut stored = stored_metadata(&core);
    for _ in 0..2 {
        stored.realizations.push(StoredRealization {
            realization_id: String::new(),
            factor_id: String::new(),
            model_digest: [0; 32],
            tokenizer_digest: [0; 32],
            content_digest: [0; 32],
            active: false,
        });
    }
    assert!(matches!(
        restore_v2(stored, 1),
        Err(DurableRegistryError::CapacityExceeded)
    ));
}

#[test]
fn legacy_record_capacity_is_rejected_before_invalid_record_decoding() {
    let stored = StoredV1 {
        schema: 1,
        revision: 1,
        lifecycle_frontier: 0,
        revocation_frontier: 0,
        maximum_records: 1,
        factors: Vec::new(),
        realizations: (0..2)
            .map(|_| StoredRealization {
                realization_id: String::new(),
                factor_id: String::new(),
                model_digest: [0; 32],
                tokenizer_digest: [0; 32],
                content_digest: [0; 32],
                active: false,
            })
            .collect(),
        bindings: Vec::new(),
    };
    assert!(matches!(
        migrate_v1(stored, 1),
        Err(DurableRegistryError::CapacityExceeded)
    ));
}

#[test]
fn v3_and_v4_configuration_is_rejected_before_opening_payload_extents() {
    for schema in [3, 4] {
        let temp = tempfile::tempdir().must("temporary directory");
        let path = temp.path().join("owner");
        let root = prepare_directory(&path).must("private directory");
        let core = PromptRegistry::new(16).must("core");
        let state = stored_metadata(&core);
        let bytes = if schema == 3 {
            serde_json::to_vec(&payloads::StoredV3 {
                schema,
                state,
                payload_references: Vec::new(),
            })
        } else {
            serde_json::to_vec(&StoredV4 {
                schema,
                state,
                payload_references: Vec::new(),
                relations: Vec::new(),
            })
        }
        .must("manifest");
        use std::io::Write;
        let mut manifest = open_private(&root, "registry.json", Access::CreateNew)
            .must("private selected metadata");
        manifest.write_all(&bytes).must("selected metadata");
        manifest.sync_all().must("selected metadata durability");
        drop(manifest);
        drop(root);
        assert!(matches!(
            DurablePromptRegistry::open_state_dir(&path, 8),
            Err(DurableRegistryError::ConfigurationMismatch)
        ));
        assert_eq!(
            std::fs::read(path.join("registry.json")).must("manifest"),
            bytes
        );
        assert!(!path.join(payloads::FILE_NAME).exists());
    }
}
