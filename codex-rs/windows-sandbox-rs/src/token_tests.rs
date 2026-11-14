use super::*;
use crate::acl::add_deny_write_ace;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_write_aces;
use crate::acl::fetch_dacl_handle;
use crate::restricted_token_fixture::capability_acl_fixture_token;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::Authorization::DENY_ACCESS;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;

struct OwnedToken(HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

struct Impersonation;

impl Impersonation {
    unsafe fn enter(token: HANDLE) -> Result<Self> {
        if ImpersonateLoggedOnUser(token) == 0 {
            return Err(anyhow!(
                "ImpersonateLoggedOnUser failed: {}",
                GetLastError()
            ));
        }
        Ok(Self)
    }
}

impl Drop for Impersonation {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            // Continuing on a reused test thread with the wrong token is unsafe.
            std::process::abort();
        }
    }
}

unsafe fn token_has_restricting_sid(token: HANDLE, expected_sid: *mut c_void) -> Result<bool> {
    let mut needed = 0;
    GetTokenInformation(
        token,
        TokenRestrictedSids,
        std::ptr::null_mut(),
        0,
        &mut needed,
    );
    if needed == 0 {
        return Err(anyhow!(
            "GetTokenInformation(TokenRestrictedSids) size query failed: {}",
            GetLastError()
        ));
    }

    let mut buffer = vec![0_u8; needed as usize];
    if GetTokenInformation(
        token,
        TokenRestrictedSids,
        buffer.as_mut_ptr().cast(),
        needed,
        &mut needed,
    ) == 0
    {
        return Err(anyhow!(
            "GetTokenInformation(TokenRestrictedSids) failed: {}",
            GetLastError()
        ));
    }

    let group_count = std::ptr::read_unaligned(buffer.as_ptr().cast::<u32>()) as usize;
    let after_count = buffer.as_ptr().add(std::mem::size_of::<u32>()) as usize;
    let align = std::mem::align_of::<SID_AND_ATTRIBUTES>();
    let entries_addr = (after_count + (align - 1)) & !(align - 1);
    let restricting_sids =
        std::slice::from_raw_parts(entries_addr as *const SID_AND_ATTRIBUTES, group_count);
    Ok(restricting_sids
        .iter()
        .any(|entry| EqualSid(entry.Sid, expected_sid) != 0))
}

#[test]
fn elevated_token_includes_network_proxy_restricting_sid() -> Result<()> {
    let capability_sid = LocalSid::from_string("S-1-5-21-10-20-30-40")?;
    let network_proxy_sid = LocalSid::from_string("S-1-5-21-50-60-70-80")?;
    let base_token = unsafe { get_current_token_for_restriction()? };
    let restricted_token = unsafe {
        create_readonly_token_with_caps_and_user_from(
            base_token,
            &[capability_sid.as_ptr()],
            &[network_proxy_sid.as_ptr()],
        )?
    };

    let has_network_proxy_sid =
        unsafe { token_has_restricting_sid(restricted_token, network_proxy_sid.as_ptr()) };
    unsafe {
        CloseHandle(restricted_token);
        CloseHandle(base_token);
    }

    assert!(has_network_proxy_sid?);
    Ok(())
}

#[test]
fn partial_delete_deny_is_repaired_before_native_workspace_writes() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let capability = LocalSid::from_string("S-1-5-21-171-272-373-474")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    // SAFETY: the existing fixture and validated SIDs remain live for both grants.
    unsafe {
        ensure_allow_mask_aces(fixture.path(), &[everyone.as_ptr()], FILE_ALL_ACCESS)?;
        ensure_allow_write_aces(fixture.path(), &[capability.as_ptr()])?;
    }
    let existing = fixture.path().join("existing.txt");
    let created = fixture.path().join("created.txt");
    std::fs::write(&existing, "original")?;
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: DELETE,
        grfAccessMode: DENY_ACCESS,
        grfInheritance: OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: capability.as_ptr().cast(),
        },
    };
    // SAFETY: the fixture exists and all SID/ACL allocations live through their
    // calls. Both returned allocations are freed after the named setter copies.
    let code = unsafe {
        let (dacl, descriptor) = fetch_dacl_handle(fixture.path())?;
        let mut partial_dacl = std::ptr::null_mut();
        let code = SetEntriesInAclW(
            /*ccountofexplicitentries*/ 1,
            &entry,
            dacl,
            &mut partial_dacl,
        );
        let code = if code == ERROR_SUCCESS {
            SetNamedSecurityInfoW(
                to_wide(fixture.path()).as_ptr() as *mut u16,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                partial_dacl,
                std::ptr::null_mut(),
            )
        } else {
            code
        };
        if !partial_dacl.is_null() {
            LocalFree(partial_dacl as HLOCAL);
        }
        LocalFree(descriptor as HLOCAL);
        code
    };
    anyhow::ensure!(code == ERROR_SUCCESS, "seed partial delete deny: {code}");
    // SAFETY: the base token stays owned until restricted-token creation completes.
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    // SAFETY: the owned base token and validated capability SID are live; the
    // resulting token is immediately owned and closed after both impersonations.
    let token =
        OwnedToken(unsafe { capability_acl_fixture_token(base.0, &[capability.as_ptr()])? });
    {
        // SAFETY: token remains owned throughout this impersonation scope.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        std::fs::write(&existing, "before repair")?;
    }
    // SAFETY: the fixture and validated capability SID are live for the repair.
    let repaired = unsafe { add_deny_write_ace(fixture.path(), capability.as_ptr())? };
    // SAFETY: the same objects remain live. Check native directory and file
    // storage retains the constructor's complete mask and inheritance scope.
    let repeated_repairs = unsafe {
        (
            add_deny_write_ace(fixture.path(), capability.as_ptr())?,
            add_deny_write_ace(&existing, capability.as_ptr())?,
            add_deny_write_ace(&existing, capability.as_ptr())?,
        )
    };
    let (read, denied) = {
        // SAFETY: token remains owned throughout this impersonation scope.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let read = std::fs::read_to_string(&existing)?;
        let denied = [
            std::fs::write(&existing, "after repair"),
            std::fs::write(&created, "created"),
        ]
        .map(|result| result.err().map(|error| error.kind()));
        (read, denied)
    };
    assert_eq!(
        (repaired, denied),
        (true, [Some(std::io::ErrorKind::PermissionDenied); 2]),
    );
    assert_eq!(repeated_repairs, (false, true, false));
    assert_eq!(read, "before repair");
    assert_eq!(
        (std::fs::read_to_string(&existing)?, created.exists()),
        ("before repair".to_owned(), false),
    );
    Ok(())
}

#[test]
fn workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let cap_a = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let other_cap = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let mut everyone = unsafe { world_sid()? };
    // Deliberately grant broad inherited DELETE and parent DELETE_CHILD inside
    // this owned fixture. Neither identity may substitute for a workspace cap.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[logon.as_mut_ptr().cast(), everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?;
    }
    let allowed = [
        fixture.path().join("workspace"),
        fixture.path().join("temp"),
    ];
    for (path, cap) in allowed.iter().zip([&cap_a, &cap_b]) {
        std::fs::create_dir(path)?;
        unsafe {
            ensure_allow_write_aces(path, &[cap.as_ptr()])?;
        }
        std::fs::write(path.join("delete.txt"), "inside")?;
        std::fs::create_dir(path.join("delete-dir"))?;
    }
    let outside = fixture.path().join("outside");
    std::fs::create_dir(&outside)?;
    // A stale capability for another root must not authorize this token either.
    unsafe {
        ensure_allow_write_aces(&outside, &[other_cap.as_ptr()])?;
    }
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    // Exercise the public production entry point. Filesystem confinement is a
    // broker contract, not a property this test may infer from a raw token.
    let codex_home = tempfile::tempdir()?;
    let workspace_roots =
        [codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&allowed[0])?];
    let extra_write_roots =
        [codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&allowed[1])?];
    let permission_profile = codex_protocol::models::PermissionProfile::workspace_write_with(
        &extra_write_roots,
        codex_protocol::permissions::NetworkSandboxPolicy::Restricted,
        /*exclude_tmpdir_env_var*/ true,
        /*exclude_slash_tmp*/ true,
    );
    let script = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
foreach ($root in @($env:BOUNDARY_WORKSPACE, $env:BOUNDARY_TEMP)) {
    [IO.File]::WriteAllText((Join-Path $root 'created.txt'), 'allowed')
    [IO.File]::Delete((Join-Path $root 'delete.txt'))
    [IO.Directory]::Delete((Join-Path $root 'delete-dir'))
}
$outsideRead = [IO.File]::ReadAllText((Join-Path $env:BOUNDARY_OUTSIDE 'keep.txt'))
$operations = @(
    { [IO.File]::WriteAllText((Join-Path $env:BOUNDARY_OUTSIDE 'keep.txt'), 'overwritten') },
    { [IO.File]::WriteAllText((Join-Path $env:BOUNDARY_OUTSIDE 'created.txt'), 'outside') },
    { [IO.File]::Delete((Join-Path $env:BOUNDARY_OUTSIDE 'keep.txt')) },
    { [IO.Directory]::Delete((Join-Path $env:BOUNDARY_OUTSIDE 'keep-dir')) }
)
$refused = New-Object 'Object[]' 4
for ($index = 0; $index -lt $operations.Length; $index++) {
    try { & $operations[$index] }
    catch {
        $cause = $_.Exception
        while ($cause.InnerException) { $cause = $cause.InnerException }
        $refused[$index] = $cause.HResult -band 0xFFFF
    }
}
@{ outside_read = $outsideRead; refused = $refused } | ConvertTo-Json -Compress
"#;
    let mut env_map = std::collections::HashMap::from([
        (
            "BOUNDARY_WORKSPACE".to_owned(),
            allowed[0].display().to_string(),
        ),
        ("BOUNDARY_TEMP".to_owned(), allowed[1].display().to_string()),
        ("BOUNDARY_OUTSIDE".to_owned(), outside.display().to_string()),
        ("TEMP".to_owned(), allowed[1].display().to_string()),
        ("TMP".to_owned(), allowed[1].display().to_string()),
    ]);
    let system_root = std::env::var("SystemRoot")?;
    env_map.insert("SystemRoot".to_owned(), system_root.clone());
    let powershell = std::path::Path::new(&system_root)
        .join("System32")
        .join("WindowsPowerShell")
        .join("v1.0")
        .join("powershell.exe");
    let output = crate::run_windows_sandbox_capture(
        &permission_profile,
        &workspace_roots,
        codex_home.path(),
        vec![
            powershell.display().to_string(),
            "-NoLogo".to_owned(),
            "-NoProfile".to_owned(),
            "-NonInteractive".to_owned(),
            "-Command".to_owned(),
            script.to_owned(),
        ],
        &allowed[0],
        env_map,
        Some(5_000),
        /*cancellation*/ None,
        /*use_private_desktop*/ true,
    )?;
    anyhow::ensure!(
        !output.timed_out && output.exit_code == 0,
        "broker fixture failed (exit {}, timeout {}): {}",
        output.exit_code,
        output.timed_out,
        String::from_utf8_lossy(&output.stderr),
    );
    #[derive(serde::Deserialize)]
    struct BoundaryObservation {
        outside_read: String,
        refused: [Option<i32>; 4],
    }
    let observation: BoundaryObservation = serde_json::from_slice(&output.stdout)?;
    let outside_read = observation.outside_read;
    let refused = observation
        .refused
        .map(|code| code.map(|code| std::io::Error::from_raw_os_error(code).kind()));
    assert_eq!(refused, [Some(std::io::ErrorKind::PermissionDenied); 4]);
    assert_eq!(outside_read, "outside");
    assert_eq!(
        (
            std::fs::read_to_string(outside.join("keep.txt"))?,
            outside.join("created.txt").exists(),
            outside.join("keep-dir").is_dir()
        ),
        ("outside".to_owned(), false, true)
    );
    for path in &allowed {
        assert_eq!(
            (
                std::fs::read_to_string(path.join("created.txt"))?,
                path.join("delete.txt").exists(),
                path.join("delete-dir").exists()
            ),
            ("allowed".to_owned(), false, false)
        );
    }
    Ok(())
}

#[test]
fn same_user_workspace_token_requires_the_dedicated_account_backend() -> Result<()> {
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-141-252-363-474")?;
    let error =
        unsafe { create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()]) }
            .expect_err("same-user workspace-write construction must fail closed");
    assert_eq!(
        error.to_string(),
        crate::filesystem_backend::ELEVATED_FILESYSTEM_REQUIRED,
    );
    Ok(())
}
