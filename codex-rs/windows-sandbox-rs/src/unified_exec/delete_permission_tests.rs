use super::*;
use crate::delete_permission_matrix::DeleteMatrix;
use crate::delete_permission_matrix::DeleteOutcome;
use crate::delete_permission_matrix::DeleteRoute;

fn matrix_script(matrix: &DeleteMatrix) -> (String, HashMap<String, String>) {
    let mut script = "@echo off\r\n".to_owned();
    let mut env = HashMap::new();
    for (index, (file, directory)) in matrix.paths().enumerate() {
        env.insert(
            format!("MATRIX_FILE_{index}"),
            file.to_string_lossy().into_owned(),
        );
        env.insert(
            format!("MATRIX_DIR_{index}"),
            directory.to_string_lossy().into_owned(),
        );
        script.push_str(&format!("echo MATRIX_ATTEMPT_{index}\r\n"));
        script.push_str(&format!("del /f /q \"%MATRIX_FILE_{index}%\"\r\n"));
        script.push_str(&format!("echo FILE_RC_{index}=%ERRORLEVEL%\r\n"));
        script.push_str(&format!("rmdir \"%MATRIX_DIR_{index}%\"\r\n"));
        script.push_str(&format!("echo DIR_RC_{index}=%ERRORLEVEL%\r\n"));
    }
    script.push_str("echo MATRIX_DONE\r\nexit /b 0\r\n");
    (script, env)
}

#[test]
fn legacy_delete_routes_require_workspace_capability_in_all_four_cells() {
    let _guard = legacy_process_test_guard();
    current_thread_runtime().block_on(async {
        let fixture = TempDir::new_in(sandbox_cwd()).expect("create delete matrix fixture");
        let codex_home = sandbox_home("legacy-delete-matrix");
        let workspace = fixture.path().join("workspace");
        let temp_root = fixture.path().join("temp");
        let tmp_root = fixture.path().join("tmp");
        for path in [&workspace, &temp_root, &tmp_root] {
            fs::create_dir(path).expect("create allowed root");
        }
        let host = DeleteMatrix::new(&fixture.path().join("host")).expect("host matrix");
        let restricted = DeleteMatrix::new(&fixture.path().join("outside")).expect("outside matrix");
        host.assert_same_acls(&restricted);
        let (script, env) = matrix_script(&host);
        let host_script = workspace.join("host-matrix.cmd");
        fs::write(&host_script, script).expect("write host script");
        let host_log_path = fixture.path().join("host-output.txt");
        let host_log = fs::File::create(&host_log_path).expect("create owned host output");
        let mut child = std::process::Command::new("C:\\Windows\\System32\\cmd.exe")
            .args(["/d", "/c"]).arg(&host_script).envs(env)
            .stdout(host_log.try_clone().expect("clone host output")).stderr(host_log)
            .spawn().expect("spawn ordinary host cmd control");
        // Keep the host comparison bounded to the same five-second child budget.
        // SAFETY: Child owns this process handle until kill/wait below completes.
        let waited = unsafe { WaitForSingleObject(child.as_raw_handle() as _, /*dwmilliseconds*/ 5_000) };
        if waited != WAIT_OBJECT_0 {
            let wait_error = (waited == WAIT_FAILED).then(std::io::Error::last_os_error);
            let killed = child.kill();
            let reaped = child.wait();
            panic!("ordinary host cmd did not finish: wait={waited} error={wait_error:?} kill={killed:?} reap={reaped:?}");
        }
        let status = child.wait().expect("reap ordinary host cmd");
        let host_log = fs::read_to_string(&host_log_path).expect("read owned host output");
        let host_outcomes = host.finish("ordinary-host-cmd-done").expect("host physical readback");
        eprintln!("delete_matrix host_cmd_status={status} output={host_log:?}");
        assert_eq!(status.code(), Some(0));
        assert_eq!(host_log.lines().filter(|line| line.starts_with("MATRIX_")).collect::<Vec<_>>(),
            ["MATRIX_ATTEMPT_0", "MATRIX_ATTEMPT_1", "MATRIX_ATTEMPT_2", "MATRIX_ATTEMPT_3", "MATRIX_DONE"]);
        assert_eq!(host_outcomes, [DeleteRoute::Neither, DeleteRoute::TargetOnly, DeleteRoute::ParentOnly, DeleteRoute::Both]
            .map(|route| DeleteOutcome { route, file_deleted: route != DeleteRoute::Neither,
                directory_deleted: route != DeleteRoute::Neither }));

        let allowed_file = workspace.join("allowed-file");
        let allowed_directory = workspace.join("allowed-directory");
        fs::write(&allowed_file, "allowed").expect("seed allowed file");
        fs::create_dir(&allowed_directory).expect("seed allowed directory");
        let (script, mut env) = matrix_script(&restricted);
        let script = script.replacen("@echo off\r\n", concat!(
            "@echo off\r\n",
            "del /f /q \"%ALLOWED_FILE%\"\r\n",
            "rmdir \"%ALLOWED_DIRECTORY%\"\r\n",
        ), /*count*/ 1);
        let script_path = workspace.join("restricted-matrix.cmd");
        fs::write(&script_path, script).expect("write restricted script");
        env.extend([
            ("TEMP".to_owned(), temp_root.to_string_lossy().into_owned()),
            ("TMP".to_owned(), tmp_root.to_string_lossy().into_owned()),
            ("ALLOWED_FILE".to_owned(), allowed_file.to_string_lossy().into_owned()),
            ("ALLOWED_DIRECTORY".to_owned(), allowed_directory.to_string_lossy().into_owned()),
        ]);
        let permission_profile = PermissionProfile::workspace_write();
        let spawned = spawn_windows_sandbox_session_legacy(
            &permission_profile, workspace_roots_for(&workspace).as_slice(), codex_home.path(),
            vec!["C:\\Windows\\System32\\cmd.exe".to_owned(), "/d".to_owned(),
                "/c".to_owned(), script_path.display().to_string()],
            &workspace, env, /*timeout_ms*/ Some(5_000), &[], &[],
            /*tty*/ false, /*stdin_open*/ false, /*use_private_desktop*/ true,
        ).await.expect("spawn original legacy path");
        let (stdout, exit_code) = collect_stdout_and_exit(
            spawned, codex_home.path(), Duration::from_secs(/*secs*/ 10),
        ).await;
        let stdout = String::from_utf8_lossy(&stdout);
        let outcomes = restricted.finish("legacy-child-done").expect("restricted physical readback");
        eprintln!("delete_matrix legacy_exit={exit_code} stdout={stdout:?}");
        assert_eq!(exit_code, 0);
        assert_eq!(stdout.lines().filter(|line| line.starts_with("MATRIX_")).collect::<Vec<_>>(),
            ["MATRIX_ATTEMPT_0", "MATRIX_ATTEMPT_1", "MATRIX_ATTEMPT_2", "MATRIX_ATTEMPT_3", "MATRIX_DONE"]);
        assert_eq!(fs::symlink_metadata(&allowed_file).unwrap_err().kind(), std::io::ErrorKind::NotFound);
        assert_eq!(fs::symlink_metadata(&allowed_directory).unwrap_err().kind(), std::io::ErrorKind::NotFound);
        assert_eq!(outcomes, [DeleteRoute::Neither, DeleteRoute::TargetOnly, DeleteRoute::ParentOnly, DeleteRoute::Both]
            .map(|route| DeleteOutcome { route, file_deleted: false, directory_deleted: false }));
    });
}
