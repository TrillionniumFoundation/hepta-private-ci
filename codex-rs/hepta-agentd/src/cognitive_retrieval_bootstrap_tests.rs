use super::*;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_types::FixedQ32;
use serde_json::json;

#[test]
fn key_and_signature_decoding_is_fixed_width_and_canonical() {
    assert_eq!(hex_array::<32>(&"02".repeat(32)).expect("key"), [2; 32]);
    assert_eq!(
        hex_array::<64>(&"03".repeat(64)).expect("signature"),
        [3; 64]
    );
    for invalid in [
        "A".repeat(64),
        "0".repeat(63),
        "0".repeat(65),
        "é".repeat(32),
    ] {
        assert!(hex_array::<32>(&invalid).is_err());
    }
}

#[test]
fn bootstrap_descriptor_rejects_duplicate_unknown_and_boolean_fields() {
    let descriptor = json!({
        "schema":"hepta.agentd.retrieval-bootstrap.v1",
        "owner_id":"00000000-0000-4000-8000-000000000731",
        "body_generation":9, "context_public_key_hex":"02".repeat(32),
        "frontier_public_key_hex":"03".repeat(32), "frontier_endpoint":"127.0.0.1:12345",
        "request_timeout_ms":100, "maximum_lease_ms":30000,
        "publication_path":"/opt/hepta/retrieval/publication.json"
    });
    let text = serde_json::to_string(&descriptor).expect("json");
    assert!(serde_json::from_str::<BootstrapDescriptor>(&text).is_ok());
    let duplicate = text.replace(
        "\"body_generation\":9",
        "\"body_generation\":9,\"body_generation\":9",
    );
    assert!(serde_json::from_str::<BootstrapDescriptor>(&duplicate).is_err());
    let mut invalid = descriptor.clone();
    invalid["body_generation"] = json!(true);
    assert!(serde_json::from_value::<BootstrapDescriptor>(invalid).is_err());
    let mut invalid = descriptor;
    invalid["allow_unsigned"] = json!(true);
    assert!(serde_json::from_value::<BootstrapDescriptor>(invalid).is_err());
}

#[test]
fn publication_decoder_does_not_treat_a_signature_string_as_verified_context() {
    assert!(decode_publication(b"{}").is_err());
    assert!(decode_publication(&vec![b' '; MAX_PUBLICATION_BYTES + 1]).is_err());
    let value = json!({
        "schema":"hepta.agentd.retrieval-publication-file.v1",
        "owner_id":"00000000-0000-4000-8000-000000000731", "body_generation":9,
        "sequence":1, "not_before_unix_ms":1, "expires_unix_ms":2,
        "context_json":"{}", "signature_hex":"00".repeat(64)
    });
    assert!(decode_publication(&serde_json::to_vec(&value).expect("json")).is_err());
}

#[test]
fn ordinary_bootstrap_rejects_positive_vector_without_composed_owner() {
    let mut policy = sqlite_owner_retrieval_policy_v1().expect("owner policy");
    assert!(ensure_bootstrap_supported_policy(&policy).is_ok());
    policy.channel_weights.push(RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Vector,
        weight: FixedQ32::ONE,
        maximum_candidates: 32,
    });
    assert_eq!(
        ensure_bootstrap_supported_policy(&policy),
        Err(
            "ordinary retrieval bootstrap cannot enable Vector without an authenticated generation-bound encoder/index owner"
                .to_string()
        )
    );
}

#[cfg(unix)]
#[test]
fn host_reader_enforces_regular_canonical_private_bounded_files() {
    use std::os::unix::fs::PermissionsExt;
    let temp = tempfile::tempdir().expect("temp");
    let root = temp.path().canonicalize().expect("canonical");
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).expect("permissions");
    let file = root.join("descriptor.json");
    std::fs::write(&file, b"{}").expect("write");
    assert_eq!(read_host_file(&file, 2).expect("read"), b"{}");
    assert!(read_host_file(&file, 1).is_err());
    assert!(read_host_file(&root, 1024).is_err());
    assert!(read_host_file(Path::new("relative.json"), 1024).is_err());
    let link = root.join("alias.json");
    std::os::unix::fs::symlink(&file, &link).expect("symlink");
    assert!(read_host_file(&link, 1024).is_err());
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o777)).expect("permissions");
    assert!(read_host_file(&file, 1024).is_err());
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).expect("permissions");
}
