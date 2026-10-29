use super::broker_test_support::spawn_broker_session;
use super::collect_stdout_and_exit;
use super::current_thread_runtime;
use super::sandbox_cwd;
use super::sandbox_home;
use super::sandbox_log;
use super::sandbox_process_test_guard;
use super::workspace_roots_for;
use crate::acl::ensure_allow_mask_aces;
use crate::token::LocalSid;
use crate::winutil::to_wide;
use codex_protocol::models::PermissionProfile;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::ffi::c_void;
use std::fs;
use std::path::Path;
use std::time::Duration;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::AddMandatoryAce;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::SYSTEM_MANDATORY_LABEL_ACE;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::System::SystemServices::SYSTEM_MANDATORY_LABEL_ACE_TYPE;
use windows_sys::Win32::System::SystemServices::SYSTEM_MANDATORY_LABEL_NO_WRITE_UP;

fn grant_broad_low_integrity_access(path: &Path) {
    let everyone = LocalSid::from_string("S-1-1-0").expect("Everyone SID");
    let low = LocalSid::from_string("S-1-16-4096").expect("low mandatory SID");
    // Only this owned outside fixture is changed. Include both direct DELETE
    // and parent DELETE_CHILD so a dedicated account cannot inherit authority
    // from Everyone outside the policy's writable roots.
    unsafe {
        ensure_allow_mask_aces(
            path,
            &[everyone.as_ptr()],
            FILE_GENERIC_READ | DELETE | FILE_DELETE_CHILD,
        )
    }
    .expect("install broad outside delete grants");

    let mut storage = vec![0_u32; 64];
    let acl = storage.as_mut_ptr().cast::<ACL>();
    // SAFETY: storage is DWORD-aligned, owns the complete initialized ACL, and
    // the validated low-label SID remains live through the native calls.
    unsafe {
        assert_ne!(
            InitializeAcl(
                acl,
                (storage.len() * std::mem::size_of::<u32>()) as u32,
                ACL_REVISION
            ),
            0,
            "initialize mandatory label ACL"
        );
        assert_ne!(
            AddMandatoryAce(
                acl,
                ACL_REVISION,
                OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
                SYSTEM_MANDATORY_LABEL_NO_WRITE_UP,
                low.as_ptr(),
            ),
            0,
            "add inheritable low mandatory label"
        );
        assert_eq!(
            SetNamedSecurityInfoW(
                to_wide(path).as_ptr() as *mut u16,
                SE_FILE_OBJECT,
                LABEL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                acl,
            ),
            ERROR_SUCCESS,
            "install low label on owned outside fixture"
        );
    }
}

fn assert_low_integrity_label(path: &Path) {
    let low = LocalSid::from_string("S-1-16-4096").expect("low mandatory SID");
    let mut sacl = std::ptr::null_mut();
    let mut descriptor: *mut c_void = std::ptr::null_mut();
    // SAFETY: the path is an existing owned fixture, all output pointers are
    // writable, and the native descriptor is retained through the ACE query.
    let result = unsafe {
        GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut sacl,
            &mut descriptor,
        )
    };
    let mut found = false;
    let mut label_count = 0;
    if result == ERROR_SUCCESS && !sacl.is_null() {
        // SAFETY: the returned ACL and ACEs remain owned by descriptor until
        // LocalFree below; a mandatory-label ACE has the SID after its mask.
        unsafe {
            for index in 0..u32::from((*sacl).AceCount) {
                let mut ace = std::ptr::null_mut();
                if GetAce(sacl, index, &mut ace) != 0 {
                    let header = &*ace.cast::<ACE_HEADER>();
                    // Inspect the common header before interpreting the
                    // larger mandatory-label ACE.
                    if u32::from(header.AceType) != SYSTEM_MANDATORY_LABEL_ACE_TYPE
                        || usize::from(header.AceSize)
                            < std::mem::size_of::<SYSTEM_MANDATORY_LABEL_ACE>()
                    {
                        continue;
                    }
                    label_count += 1;
                    let label = &*ace.cast::<SYSTEM_MANDATORY_LABEL_ACE>();
                    if label.Mask & SYSTEM_MANDATORY_LABEL_NO_WRITE_UP != 0
                        && EqualSid(
                            (&label.SidStart as *const u32).cast_mut().cast(),
                            low.as_ptr(),
                        ) != 0
                    {
                        found = true;
                    }
                }
            }
        }
    }
    if !descriptor.is_null() {
        // SAFETY: GetNamedSecurityInfoW allocated this descriptor with LocalAlloc.
        unsafe { LocalFree(descriptor as HLOCAL) };
    }
    assert_eq!(
        result,
        ERROR_SUCCESS,
        "read mandatory label at {}",
        path.display()
    );
    assert_eq!(
        label_count, 1,
        "fixture must have exactly one mandatory label"
    );
    assert!(
        found,
        "outside fixture is not low-labeled: {}",
        path.display()
    );
}

#[test]
fn broker_workspace_write_delete_is_limited_to_writable_roots() {
    assert_broker_delete_boundary(/*broad_low_acl*/ false);
}

#[test]
fn broker_cannot_delete_low_integrity_outside_paths_with_broad_everyone_grants() {
    assert_broker_delete_boundary(/*broad_low_acl*/ true);
}

fn assert_broker_delete_boundary(broad_low_acl: bool) {
    let _guard = sandbox_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        // Keep writable roots out of USERPROFILE exclusions such as AppData.
        let test_root = TempDir::new_in(sandbox_cwd()).expect("create broker delete test root");
        let codex_home = sandbox_home("broker-delete-writable-roots");
        let workspace = test_root.path().join("workspace");
        let temp_root = test_root.path().join("temp");
        let tmp_root = test_root.path().join("tmp");
        let outside_root = test_root.path().join("outside");
        for directory in [&workspace, &temp_root, &tmp_root, &outside_root] {
            fs::create_dir_all(directory).expect("create broker delete test directory");
        }
        if broad_low_acl {
            grant_broad_low_integrity_access(&outside_root);
        }
        let outside_dir = outside_root.join("keep-dir");
        fs::create_dir(&outside_dir).expect("create outside directory");
        let protected_git_dir = workspace.join(".git");
        fs::create_dir(&protected_git_dir).expect("create protected .git directory");

        let workspace_file = workspace.join("workspace-delete.txt");
        let temp_file = temp_root.join("temp-delete.txt");
        let tmp_file = tmp_root.join("tmp-delete.txt");
        let outside_file = outside_root.join("outside-delete.txt");
        fs::write(&workspace_file, "workspace").expect("seed workspace file");
        fs::write(&temp_file, "temp").expect("seed TEMP file");
        fs::write(&tmp_file, "tmp").expect("seed TMP file");
        fs::write(&outside_file, "outside").expect("seed outside file");
        if broad_low_acl {
            for path in [&outside_root, &outside_file, &outside_dir] {
                assert_low_integrity_label(path);
            }
        }

        let script = workspace.join("delete-fixtures.cmd");
        fs::write(
            &script,
            concat!(
                "@echo off\r\n",
                "C:\\Windows\\System32\\whoami.exe /groups /fo csv /nh\r\n",
                "del /f /q \"%WORKSPACE_DELETE%\"\r\n",
                "del /f /q \"%TEMP_DELETE%\"\r\n",
                "del /f /q \"%TMP_DELETE%\"\r\n",
                "del /f /q \"%OUTSIDE_DELETE%\"\r\n",
                "rmdir \"%OUTSIDE_DIR%\"\r\n",
                "rmdir \"%PROTECTED_GIT_DIR%\"\r\n",
                "exit /b 0\r\n",
            ),
        )
        .expect("write delete script");

        let env_map = HashMap::from([
            ("TEMP".to_string(), temp_root.to_string_lossy().into_owned()),
            ("TMP".to_string(), tmp_root.to_string_lossy().into_owned()),
            (
                "WORKSPACE_DELETE".to_string(),
                workspace_file.to_string_lossy().into_owned(),
            ),
            (
                "TEMP_DELETE".to_string(),
                temp_file.to_string_lossy().into_owned(),
            ),
            (
                "TMP_DELETE".to_string(),
                tmp_file.to_string_lossy().into_owned(),
            ),
            (
                "OUTSIDE_DELETE".to_string(),
                outside_file.to_string_lossy().into_owned(),
            ),
            (
                "OUTSIDE_DIR".to_string(),
                outside_dir.to_string_lossy().into_owned(),
            ),
            (
                "PROTECTED_GIT_DIR".to_string(),
                protected_git_dir.to_string_lossy().into_owned(),
            ),
        ]);

        let permission_profile = PermissionProfile::workspace_write();
        let spawned = spawn_broker_session(
            &permission_profile,
            workspace_roots_for(workspace.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                script.display().to_string(),
            ],
            workspace.as_path(),
            env_map,
            /*timeout_ms*/ Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await
        .expect("spawn broker delete session");
        let (stdout, exit_code) =
            collect_stdout_and_exit(spawned, codex_home.path(), Duration::from_secs(/*secs*/ 10))
                .await;
        let stdout = String::from_utf8_lossy(&stdout);
        if broad_low_acl {
            let integrity_rid = stdout
                .split("S-1-16-")
                .nth(1)
                .map(|suffix| {
                    suffix
                        .chars()
                        .take_while(char::is_ascii_digit)
                        .collect::<String>()
                })
                .and_then(|rid| rid.parse::<u32>().ok())
                .expect("native child must report its mandatory integrity SID");
            assert!(
                integrity_rid >= 4096,
                "an untrusted child cannot qualify the low-label policy boundary: {stdout:?}"
            );
        }

        assert_eq!(
            (
                exit_code,
                workspace_file.exists(),
                temp_file.exists(),
                tmp_file.exists(),
                fs::read_to_string(&outside_file).ok(),
                protected_git_dir.is_dir(),
                outside_dir.is_dir(),
            ),
            (
                0,
                false,
                false,
                false,
                Some("outside".to_string()),
                true,
                true
            ),
            "stdout={stdout:?}\n{}",
            sandbox_log(codex_home.path())
        );
    });
}
