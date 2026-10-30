use super::collect_stdout_and_exit;
use super::current_thread_runtime;
use super::helper_bundle::run_in_helper_bundle;
use super::legacy_process_test_guard;
use super::sandbox_cwd;
use super::sandbox_home;
use super::sandbox_log;
use super::workspace_roots_for;
use crate::acl::ensure_allow_mask_aces;
use crate::acl_test_support::trace_acl;
use crate::run_windows_sandbox_capture;
use crate::spawn_windows_sandbox_session_legacy;
use crate::token::LocalSid;
use codex_protocol::models::PermissionProfile;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::fs;
use std::time::Duration;
use tempfile::TempDir;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;

#[test]
fn read_only_public_launches_deny_writes_and_deletes_under_broad_identity_aces() {
    if run_in_helper_bundle("unified_exec::tests::readonly_boundary_tests::read_only_public_launches_deny_writes_and_deletes_under_broad_identity_aces") {
        return;
    }
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    for transport in ["capture", "session"] {
        let fixture = TempDir::new_in(sandbox_cwd())
            .unwrap_or_else(|error| panic!("create read-only boundary fixture: {error}"));
        let codex_home = sandbox_home("readonly-broad-identity");
        let workspace = fixture.path().join("workspace");
        let outside = fixture.path().join("outside");
        let protected = workspace.join(".git");
        let everyone = LocalSid::from_string("S-1-1-0")
            .unwrap_or_else(|error| panic!("parse fixture Everyone SID: {error}"));
        // SAFETY: only this owned fixture is changed. The validated SID remains
        // live until after setup and the real sandbox process have completed.
        unsafe {
            ensure_allow_mask_aces(fixture.path(), &[everyone.as_ptr()], FILE_ALL_ACCESS)
                .unwrap_or_else(|error| panic!("grant adversarial fixture parent access: {error}"));
        }
        for root in [&workspace, &outside] {
            fs::create_dir(root)
                .unwrap_or_else(|error| panic!("create read-only fixture root {root:?}: {error}"));
            fs::write(root.join("keep.txt"), "READ_ONLY_READ_OK")
                .unwrap_or_else(|error| panic!("seed read-only fixture contents: {error}"));
            fs::write(root.join("delete.txt"), "must remain")
                .unwrap_or_else(|error| panic!("seed deletion target: {error}"));
            fs::create_dir(root.join("delete-dir"))
                .unwrap_or_else(|error| panic!("seed directory deletion target: {error}"));
            trace_acl(transport, root, &everyone)
                .unwrap_or_else(|error| panic!("record broad identity parent ACL: {error}"));
        }
        fs::create_dir(&protected)
            .unwrap_or_else(|error| panic!("create protected .git fixture: {error}"));
        let mut commands = format!("@echo off\r\ntype \"{}\"\r\n", outside.join("keep.txt").display());
        for root in [&workspace, &outside] {
            commands.push_str(&format!(
                "echo forbidden>\"{}\"\r\necho forbidden>\"{}\"\r\ndel /f /q \"{}\"\r\nrmdir \"{}\"\r\n",
                root.join("keep.txt").display(),
                root.join("created.txt").display(),
                root.join("delete.txt").display(),
                root.join("delete-dir").display(),
            ));
        }
        commands.push_str(&format!("rmdir \"{}\"\r\nexit /b 0\r\n", protected.display()));
        let script = workspace.join("readonly-boundary.cmd");
        fs::write(&script, commands)
            .unwrap_or_else(|error| panic!("write read-only boundary commands: {error}"));
        let command = vec![
            r"C:\Windows\System32\cmd.exe".to_string(),
            "/d".to_string(),
            "/c".to_string(),
            script.display().to_string(),
        ];
        let profile = PermissionProfile::read_only();
        let roots = workspace_roots_for(&workspace);
        let (stdout, exit_code) = if transport == "capture" {
            let result = run_windows_sandbox_capture(
                &profile,
                &roots,
                codex_home.path(),
                command,
                &workspace,
                HashMap::new(),
                Some(5_000),
                /*cancellation*/ None,
                /*use_private_desktop*/ true,
            )
            .unwrap_or_else(|error| panic!("run read-only capture boundary: {error:#}"));
            assert!(!result.timed_out, "read-only capture boundary timed out");
            eprintln!("read-only capture stderr={}", String::from_utf8_lossy(&result.stderr));
            (result.stdout, result.exit_code)
        } else {
            runtime.block_on(async {
                let spawned = spawn_windows_sandbox_session_legacy(
                    &profile,
                    &roots,
                    codex_home.path(),
                    command,
                    &workspace,
                    HashMap::new(),
                    Some(5_000),
                    &[],
                    &[],
                    /*tty*/ false,
                    /*stdin_open*/ false,
                    /*use_private_desktop*/ true,
                )
                .await
                .unwrap_or_else(|error| panic!("run read-only session boundary: {error:#}"));
                collect_stdout_and_exit(spawned, codex_home.path(), Duration::from_secs(/*secs*/ 10))
                    .await
            })
        };
        let stdout = String::from_utf8_lossy(&stdout);
        let after = [&workspace, &outside].map(|root| {
            (
                fs::read_to_string(root.join("keep.txt")).ok(),
                root.join("created.txt").exists(),
                fs::read_to_string(root.join("delete.txt")).ok(),
                root.join("delete-dir").is_dir(),
            )
        });
        let expected = std::array::from_fn::<_, 2, _>(|_| {
            (Some("READ_ONLY_READ_OK".to_string()), false, Some("must remain".to_string()), true)
        });
        assert_eq!(
            (exit_code, stdout.contains("READ_ONLY_READ_OK"), protected.is_dir(), after),
            (0, true, true, expected),
            "transport={transport}; stdout={stdout:?}\n{}",
            sandbox_log(codex_home.path()),
        );
    }
}
