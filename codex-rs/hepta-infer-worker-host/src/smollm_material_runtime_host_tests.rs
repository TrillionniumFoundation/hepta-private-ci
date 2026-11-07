use super::*;
use pretty_assertions::assert_eq;

fn bridge_input() -> serde_json::Value {
    serde_json::json!({
        "profile": "smollm2-public-v2-material-runtime-bridge-v1",
        "material_plan": std::str::from_utf8(
            include_bytes!("../fixtures/material-runtime-bridge-v1-plan.json")).unwrap(),
    })
}

fn write_input(
    directory: &tempfile::TempDir,
    name: &str,
    value: &serde_json::Value,
) -> (PathBuf, Digest32) {
    let path = directory.path().canonicalize().unwrap().join(name);
    let raw = serde_json::to_vec(value).unwrap();
    protected(&path, &raw);
    (path, Digest32::of_bytes(&raw))
}

#[test]
fn old_owner_and_cell_schemas_reject_bridge_objects_and_explicit_null() {
    for bridge in [bridge_input(), serde_json::Value::Null] {
        let (directory, mut cell) = cell_host_fixture();
        cell["owner"]["worker"]["material_runtime_bridge"] = bridge;
        let (path, pin) = write_input(&directory, "owner.json", &cell["owner"]);
        assert!(load_smollm_cognitive_host_inputs_v2(&path, pin).is_err());
        let (path, pin) = write_input(&directory, "cell.json", &cell);
        assert!(load_smollm_cognitive_cell_host_inputs_v2(&path, pin).is_err());
        assert!(!directory.path().join("journal").exists());
        assert!(!directory.path().join("run").exists());
    }
}

#[test]
fn new_owner_decoder_requires_its_explicit_schema_and_exact_pair() {
    let (directory, mut cell) = cell_host_fixture();
    let owner = &mut cell["owner"];
    owner["schema"] = serde_json::json!("hepta-smollm-cognitive-host-material-bridge-v1");
    owner["worker"]["material_runtime_bridge"] = bridge_input();
    let (path, pin) = write_input(&directory, "owner.json", owner);
    let input = load_smollm_cognitive_host_inputs_material_bridge_v1(&path, pin).unwrap();
    assert!(input.worker.material_runtime_bridge.is_some());
    // The fixture's fake target/source bytes are still refused by actual profile
    // admission. Protected schema decoding does not qualify this fixture.
    assert!(input.worker.execution_profile_digest().is_err());
    assert!(load_smollm_cognitive_host_inputs_v2(&path, pin).is_err());
    assert!(!directory.path().join("journal").exists());
    assert!(!directory.path().join("run").exists());
    owner["worker"]
        .as_object_mut()
        .unwrap()
        .remove("material_runtime_bridge");
    let (path, pin) = write_input(&directory, "missing.json", owner);
    assert!(load_smollm_cognitive_host_inputs_material_bridge_v1(&path, pin).is_err());
    owner["worker"]["material_runtime_bridge"] = bridge_input();
    owner["worker"]["material_runtime_bridge"]["profile"] = serde_json::json!("v11");
    let (path, pin) = write_input(&directory, "wrong-profile.json", owner);
    assert!(load_smollm_cognitive_host_inputs_material_bridge_v1(&path, pin).is_err());
}

#[test]
fn new_cell_mode_keeps_both_schemas_and_original_dependency_bytes() {
    let (directory, mut cell) = cell_host_fixture();
    cell["schema"] = serde_json::json!("hepta-smollm-cognitive-cell-host-material-bridge-v1");
    cell["owner"]["schema"] = serde_json::json!("hepta-smollm-cognitive-host-material-bridge-v1");
    cell["owner"]["worker"]["material_runtime_bridge"] = bridge_input();
    let (path, pin) = write_input(&directory, "cell.json", &cell);
    let input = load_smollm_cognitive_cell_host_inputs_material_bridge_v1(&path, pin).unwrap();
    assert!(input.owner.worker.material_runtime_bridge.is_some());
    assert_eq!(
        input.cell.dependency_wire.as_slice(),
        b"synthetic bytes; not a TCD1 witness"
    );
    assert_eq!(
        input.cell.sidecar.as_slice(),
        b"synthetic declaration; not admitted"
    );
    assert!(load_smollm_cognitive_cell_host_inputs_v2(&path, pin).is_err());
    cell["owner"]["schema"] = serde_json::json!("hepta-smollm-cognitive-host-v2");
    let (path, pin) = write_input(&directory, "mixed.json", &cell);
    assert!(load_smollm_cognitive_cell_host_inputs_material_bridge_v1(&path, pin).is_err());
    assert!(!directory.path().join("journal").exists());
    assert!(!directory.path().join("run").exists());
}

#[test]
fn bridge_host_preserves_original_file_bound_and_current_pin_validation() {
    let (directory, mut cell) = cell_host_fixture();
    cell["owner"]["schema"] = serde_json::json!("hepta-smollm-cognitive-host-material-bridge-v1");
    cell["owner"]["worker"]["material_runtime_bridge"] = bridge_input();
    let (path, pin) = write_input(&directory, "owner.json", &cell["owner"]);
    assert!(
        load_smollm_cognitive_host_inputs_material_bridge_v1(
            &path,
            Digest32::of_bytes(b"wrong file")
        )
        .is_err()
    );
    std::fs::write(&path, vec![b'x'; MAX_HOST_FILE_BYTES as usize + 1]).unwrap();
    assert!(load_smollm_cognitive_host_inputs_material_bridge_v1(&path, pin).is_err());
    assert!(!directory.path().join("journal").exists());
}
