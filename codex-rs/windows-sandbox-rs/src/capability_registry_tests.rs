use super::*;

fn registry() -> CapSids {
    CapSids {
        version: REGISTRY_VERSION,
        generation: "a".repeat(32),
        workspace: "S-1-5-21-1-2-3-4".into(),
        readonly: "S-1-5-21-2-3-4-5".into(),
        workspace_by_cwd: HashMap::new(),
        writable_root_by_path: HashMap::new(),
    }
}

#[test]
fn registry_capacity_rejects_max_plus_one_without_truncation() {
    let mut caps = registry();
    for index in 0..MAX_REGISTERED_ROOTS {
        caps.writable_root_by_path.insert(
            format!("root-{index}"),
            format!("S-1-5-21-10-11-12-{}", index + 100),
        );
    }
    caps.validate().unwrap();
    caps.writable_root_by_path
        .insert("MAX+1".into(), "S-1-5-21-20-21-22-23".into());
    assert!(caps.validate().is_err());
}

#[test]
fn invalid_generation_version_and_reused_identity_are_refused() {
    let original = registry();
    original.validate().unwrap();
    let mut caps = original.clone();
    caps.generation.clear();
    assert!(caps.validate().is_err());
    let mut caps = original.clone();
    caps.version -= 1;
    assert!(caps.validate().is_err());
    let mut caps = original;
    caps.readonly = caps.workspace.clone();
    assert!(caps.validate().is_err());
    for sid in [
        "S-1-",
        "S-1-5-",
        "S-1-5-4294967296",
        "S-1-281474976710656-1",
    ] {
        assert!(!sid_is_bounded(sid));
    }
}

#[test]
fn serialized_duplicate_roots_and_oversized_paths_are_refused() {
    let value = serde_json::to_string(&registry()).unwrap().replace("\"workspace_by_cwd\":{}", "\"workspace_by_cwd\":{\"same\":\"S-1-5-21-10-11-12-13\",\"same\":\"S-1-5-21-11-12-13-14\"}");
    assert!(serde_json::from_str::<CapSids>(&value).is_err());
    let mut caps = registry();
    caps.workspace_by_cwd.insert(
        "a".repeat(MAX_PATH_BYTES + 1),
        "S-1-5-21-10-11-12-13".into(),
    );
    assert!(caps.validate().is_err());
    assert!(serde_json::from_slice::<CapSids>(&serde_json::to_vec(&caps).unwrap()).is_err());
}
