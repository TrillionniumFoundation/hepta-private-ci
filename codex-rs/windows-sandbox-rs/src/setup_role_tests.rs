use super::*;
use pretty_assertions::assert_eq;

#[test]
fn legal_root_count_cannot_overflow_the_real_setup_commandline() {
    let roots: Vec<_> = (0..64)
        .map(|i| format!("{i}{}", "x".repeat(4000)))
        .collect();
    let encoded = BASE64_STANDARD.encode(serde_json::to_vec(&roots).unwrap());
    assert!(validate_setup_commandline(Path::new("setup.exe"), &encoded).is_err());
    assert!(validate_setup_commandline(Path::new(&"x".repeat(32766)), "e30=").is_err());
    validate_setup_commandline(Path::new("setup.exe"), "e30=").unwrap();
}

#[test]
fn provision_only_or_different_marker_cannot_confirm_a_filesystem_plan() {
    let home = tempfile::tempdir().unwrap();
    let plan = crate::cap::filesystem_capability_plan(home.path(), home.path(), &[], &[]).unwrap();
    let marker_path = setup_marker_path(home.path());
    std::fs::create_dir_all(marker_path.parent().unwrap()).unwrap();
    let mut marker = SetupMarker {
        version: SETUP_VERSION,
        filesystem_roles: None,
        offline_username: OFFLINE_USERNAME.into(),
        online_username: ONLINE_USERNAME.into(),
        created_at: None,
        proxy_ports: vec![],
        allow_local_binding: false,
    };
    let absent = serde_json::to_vec(&marker).unwrap();
    std::fs::write(&marker_path, &absent).unwrap();
    assert!(validate_filesystem_plan_marker(home.path(), &plan).is_err());
    assert_eq!(std::fs::read(&marker_path).unwrap(), absent);
    marker.filesystem_roles = Some(plan.clone());
    let exact = serde_json::to_vec(&marker).unwrap();
    std::fs::write(&marker_path, &exact).unwrap();
    validate_filesystem_plan_marker(home.path(), &plan).unwrap();
    let different = crate::cap::filesystem_capability_plan(
        home.path(),
        &home.path().join("different"),
        &[],
        &[],
    )
    .unwrap();
    assert!(validate_filesystem_plan_marker(home.path(), &different).is_err());
    assert_eq!(std::fs::read(&marker_path).unwrap(), exact);
}
