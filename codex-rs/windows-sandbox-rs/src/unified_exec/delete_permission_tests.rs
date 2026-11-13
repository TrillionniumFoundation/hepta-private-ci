use super::*;
use pretty_assertions::assert_eq;

#[test]
fn legacy_workspace_capability_request_refuses_before_native_deletion() {
    let _guard = legacy_process_test_guard();
    current_thread_runtime().block_on(async {
        let fixture = TempDir::new_in(sandbox_cwd()).expect("create legacy admission fixture");
        let codex_home = sandbox_home("legacy-delete-matrix");
        let workspace = fixture.path().join("workspace");
        let outside = fixture.path().join("outside");
        fs::create_dir(&workspace).expect("create workspace");
        fs::create_dir(&outside).expect("create outside fixture");
        let outside_file = outside.join("kept.txt");
        fs::write(&outside_file, "unchanged").expect("seed outside fixture file");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(&workspace).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                "echo ADMISSION-MUST-REFUSE".to_string(),
            ],
            &workspace,
            HashMap::new(),
            /*timeout_ms*/ Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(result);
        assert_eq!(fs::read_to_string(&outside_file).expect("read outside fixture"), "unchanged");
        assert!(outside.is_dir());
        assert_eq!(fs::read_dir(&workspace).expect("read workspace").count(), 0);
        assert_eq!(fs::read_dir(codex_home.path()).expect("read home").count(), 0);
    });
}
