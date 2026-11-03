use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;

#[test]
fn host_material_requires_original_digest_and_protected_unaliased_file()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let path = root.join("host.json");
    let bytes = b"independently pinned host material";
    let digest = Digest32::of_bytes(bytes);
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)?
        .write_all(bytes)?;
    assert_eq!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES)?, bytes);
    std::fs::write(&path, b"changed host configuration")?;
    assert!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES).is_err());
    std::fs::write(&path, bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))?;
    assert!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    std::os::unix::fs::symlink(&path, root.join("alias"))?;
    assert!(read_pinned_file(&root.join("alias"), digest, MAX_HOST_FILE_BYTES).is_err());
    std::fs::hard_link(&path, root.join("hard-link"))?;
    assert!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES).is_err());
    Ok(())
}

fn protected(path: &Path, bytes: &[u8]) -> serde_json::Value {
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .unwrap()
        .write_all(bytes)
        .unwrap();
    serde_json::json!({"path":path,"sha256":Digest32::of_bytes(bytes).to_string()})
}

fn cell_host_fixture() -> (tempfile::TempDir, serde_json::Value) {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let target = protected(&root.join("target.json"), b"synthetic contract; no model");
    let wrapped = protected(&root.join("wrapped.json"), b"synthetic adapter metadata");
    let sidecar = protected(
        &root.join("sidecar.json"),
        b"synthetic declaration; not admitted",
    );
    let closure = protected(
        &root.join("closure.tcd"),
        b"synthetic bytes; not a TCD1 witness",
    );
    let pin = Digest32::from_array([1; 32]).to_string();
    let owner = serde_json::json!({
        "schema":"hepta-smollm-cognitive-host-v1",
        "descriptor":{"path":root.join("descriptor"),"sha256":pin},
        "worker":{"python":root.join("python"),"script":root.join("worker.py"),
            "materials":root.join("materials"),"run_directory":root.join("run"),
            "source_pins":{},"target_contract":target,"wrapped_adapter":wrapped,
            "contract_digest":pin,"adapter_digest":pin,"backbone_digest":pin,
            "tokenizer_digest":pin,"action_completions":{"native-answer-no":"no","native-answer-yes":"yes"}},
        "worker_id":"cell-host-test","resource_grant":{"grant_id":"decode-only",
            "authority_epoch":1,"generation":1,"expires_at_ms":1000,"revoked":false,
            "maximum_models":1,"maximum_active_requests":1,"maximum_memory_bytes":1024,
            "semantic_digest":"not-an-authorized-grant"},
        "inference_journal":root.join("journal"),"inference_journal_capacity":1,
        "final_use_authorizer_config":root.join("final-use")});
    (
        directory,
        serde_json::json!({"schema":"hepta-smollm-cognitive-cell-host-v2",
        "owner":owner,"sidecar":sidecar,"dependency_closure":closure,
        "dependency_closure_id":pin,"operation_id":"original-owner-operation"}),
    )
}

#[test]
fn protected_v2_decoder_preserves_owned_snapshots_without_opening_inference_owners() {
    let (directory, value) = cell_host_fixture();
    let path = directory.path().canonicalize().unwrap().join("host.json");
    let raw = serde_json::to_vec(&value).unwrap();
    protected(&path, &raw);
    let inputs =
        load_smollm_cognitive_cell_host_inputs_v2(&path, Digest32::of_bytes(&raw)).unwrap();
    assert_eq!(
        (
            inputs.owner.worker_id.as_str(),
            inputs.cell.operation_id.as_str(),
            inputs.cell.sidecar.as_slice()
        ),
        (
            "cell-host-test",
            "original-owner-operation",
            b"synthetic declaration; not admitted".as_slice()
        )
    );
    // This positive is only protected decoding, not the complete Cell factory.
    assert!(!directory.path().join("journal").exists());
    assert!(!directory.path().join("run").exists());
    assert!(load_smollm_cognitive_host_inputs_v1(&path, Digest32::of_bytes(&raw)).is_err());
    let legacy = serde_json::to_vec(&value["owner"]).unwrap();
    let path = directory.path().canonicalize().unwrap().join("legacy.json");
    protected(&path, &legacy);
    assert!(load_smollm_cognitive_host_inputs_v1(&path, Digest32::of_bytes(&legacy)).is_ok());
    assert!(load_smollm_cognitive_cell_host_inputs_v2(&path, Digest32::of_bytes(&legacy)).is_err());
}

#[test]
fn cell_host_rejects_schema_field_pin_operation_and_local_file_rebinding() {
    for change in [
        "schema",
        "missing",
        "extra",
        "sidecar-pin",
        "closure-pin",
        "operation",
        "symlink",
    ] {
        let (directory, mut value) = cell_host_fixture();
        match change {
            "schema" => value["schema"] = serde_json::json!("hepta-smollm-cognitive-host-v1"),
            "missing" => {
                value.as_object_mut().unwrap().remove("dependency_closure");
            }
            "extra" => value["installation_authorized"] = serde_json::json!(true),
            "sidecar-pin" => {
                value["sidecar"]["sha256"] =
                    serde_json::json!(Digest32::from_array([9; 32]).to_string())
            }
            "closure-pin" => {
                value["dependency_closure"]["sha256"] =
                    serde_json::json!(Digest32::from_array([9; 32]).to_string())
            }
            "operation" => value["operation_id"] = serde_json::json!(""),
            "symlink" => {
                let alias = directory.path().join("alias");
                std::os::unix::fs::symlink(
                    value["dependency_closure"]["path"].as_str().unwrap(),
                    &alias,
                )
                .unwrap();
                value["dependency_closure"]["path"] = serde_json::json!(alias);
            }
            _ => unreachable!(),
        }
        let raw = serde_json::to_vec(&value).unwrap();
        let path = directory.path().canonicalize().unwrap().join("host.json");
        protected(&path, &raw);
        assert!(
            load_smollm_cognitive_cell_host_inputs_v2(&path, Digest32::of_bytes(&raw)).is_err(),
            "{change}"
        );
        assert!(!directory.path().join("journal").exists());
    }
}
