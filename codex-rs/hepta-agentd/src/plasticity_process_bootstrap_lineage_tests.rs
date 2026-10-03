//! A checksum pin does not upgrade the V1 descriptor's authority contract.

use super::*;

fn registry_descriptor() -> serde_json::Value {
    serde_json::json!({
        "mode": "reopen_anchored",
        "registry_path": "registry.journal",
        "anchor_path": "anchor.journal",
        "scope_digest": Digest32::of_bytes(b"scope").to_string(),
        "maximum_records": 8
    })
}

#[test]
fn v1_registry_descriptor_rejects_pinned_but_unimplemented_lineage_fields() {
    serde_json::from_value::<RegistryDescriptorV1>(registry_descriptor())
        .expect("unmodified V1 descriptor parses");
    for field in [
        "lineage_identity",
        "first_admitted_incarnation",
        "acknowledged_lineage_floor",
        "consumption_index_root",
        "envelope_digest",
        "projection_profile",
        "reservation",
    ] {
        let mut descriptor = registry_descriptor();
        descriptor[field] = serde_json::json!(Digest32::of_bytes(field.as_bytes()).to_string());
        let bytes = serde_json::to_vec(&descriptor).expect("descriptor bytes");
        verify_descriptor_bytes(&bytes, Digest32::of_bytes(&bytes)).expect("matching byte pin");
        let error = serde_json::from_slice::<RegistryDescriptorV1>(&bytes)
            .expect_err("V1 cannot silently accept a claimed V2 authority field");
        assert!(
            error.to_string().contains("unknown field"),
            "{field}: {error}"
        );
    }
}

#[test]
fn v1_registry_descriptor_rejects_unimplemented_consumption_rollover_modes() {
    serde_json::from_value::<RegistryDescriptorV1>(registry_descriptor())
        .expect("unmodified V1 descriptor parses");
    for mode in ["rollover", "rollover_conserving", "reopen_lineage"] {
        let mut descriptor = registry_descriptor();
        descriptor["mode"] = serde_json::json!(mode);
        let error = serde_json::from_value::<RegistryDescriptorV1>(descriptor)
            .expect_err("V1 has no lifetime-consumption rollover mode");
        assert!(
            error.to_string().contains("unknown variant"),
            "{mode}: {error}"
        );
    }
}
