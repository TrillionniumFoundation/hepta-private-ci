//! Native permission-route diagnostics; passing this matrix is not sandbox qualification.
//! All ACL/mandatory-label changes are confined to this test's owned temporary fixture.

use super::*;
use anyhow::Context;
use pretty_assertions::assert_eq;
use serde::Serialize;
use std::path::Path;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetSecurityDescriptorSacl;
use windows_sys::Win32::Security::GetSidSubAuthority;
use windows_sys::Win32::Security::GetSidSubAuthorityCount;
use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

const READ_EXECUTE: u32 = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE;

struct LocalDescriptor(*mut c_void);

impl Drop for LocalDescriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum OutsideLabel {
    Inherited,
    PreexistingLow,
}

#[derive(Debug, PartialEq, Serialize)]
struct Outcome {
    succeeded: bool,
    error_kind: Option<String>,
    win32_error: Option<i32>,
}

impl Outcome {
    fn from_result(result: std::io::Result<()>) -> Self {
        match result {
            Ok(()) => Self {
                succeeded: true,
                error_kind: None,
                win32_error: None,
            },
            Err(error) => Self {
                succeeded: false,
                error_kind: Some(format!("{:?}", error.kind())),
                win32_error: error.raw_os_error(),
            },
        }
    }
}

// Build a protected one-ACE DACL so inherited object DELETE or parent
// DELETE_CHILD cannot accidentally contaminate the route being measured.
fn fixture_acl(path: &Path, mask: u32, label: OutsideLabel) -> Result<String> {
    let suffix = match label {
        OutsideLabel::Inherited => "",
        OutsideLabel::PreexistingLow => "S:(ML;;NW;;;LW)",
    };
    let sddl = to_wide(format!("D:P(A;;0x{mask:x};;;WD){suffix}"));
    let mut descriptor = LocalDescriptor(std::ptr::null_mut());
    unsafe {
        anyhow::ensure!(
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                SDDL_REVISION_1,
                &mut descriptor.0,
                std::ptr::null_mut(),
            ) != 0,
            "parse fixture SDDL: {}",
            GetLastError()
        );
        let mut dacl = std::ptr::null_mut();
        let mut sacl = std::ptr::null_mut();
        let mut present = 0;
        let mut defaulted = 0;
        anyhow::ensure!(
            GetSecurityDescriptorDacl(descriptor.0, &mut present, &mut dacl, &mut defaulted) != 0
                && present != 0
                && !dacl.is_null(),
            "fixture DACL missing"
        );
        let mut information = DACL_SECURITY_INFORMATION;
        if matches!(label, OutsideLabel::PreexistingLow) {
            anyhow::ensure!(
                GetSecurityDescriptorSacl(descriptor.0, &mut present, &mut sacl, &mut defaulted)
                    != 0
                    && present != 0
                    && !sacl.is_null(),
                "fixture mandatory label missing"
            );
            information |= LABEL_SECURITY_INFORMATION;
        }
        let code = SetNamedSecurityInfoW(
            to_wide(path).as_mut_ptr(),
            SE_FILE_OBJECT,
            information | PROTECTED_DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            dacl,
            sacl,
        );
        anyhow::ensure!(code == ERROR_SUCCESS, "set fixture ACL/label: {code}");
        let mut actual = LocalDescriptor(std::ptr::null_mut());
        let code = GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            information,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut dacl,
            &mut sacl,
            &mut actual.0,
        );
        anyhow::ensure!(code == ERROR_SUCCESS, "read fixture ACL/label: {code}");
        let mut control = 0;
        let mut revision = 0;
        anyhow::ensure!(
            GetSecurityDescriptorControl(actual.0, &mut control, &mut revision) != 0
                && control & SE_DACL_PROTECTED != 0
                && !dacl.is_null()
                && (*dacl).AceCount == 1,
            "fixture DACL must be protected with exactly one ACE"
        );
        let mut ace = std::ptr::null_mut();
        anyhow::ensure!(
            GetAce(dacl, /*dwaceindex*/ 0, &mut ace) != 0,
            "read fixture ACE: {}",
            GetLastError()
        );
        let ace = &*ace.cast::<ACCESS_ALLOWED_ACE>();
        let mut everyone = world_sid()?;
        anyhow::ensure!(
            ace.Header.AceType == 0
                && ace.Header.AceFlags == 0
                && ace.Mask == mask
                && EqualSid(
                    std::ptr::addr_of!(ace.SidStart).cast_mut().cast(),
                    everyone.as_mut_ptr().cast(),
                ) != 0,
            "fixture ACE does not match exact Everyone mask"
        );
        let mut text = std::ptr::null_mut();
        let mut length = 0;
        anyhow::ensure!(
            ConvertSecurityDescriptorToStringSecurityDescriptorW(
                actual.0,
                SDDL_REVISION_1,
                information,
                &mut text,
                &mut length,
            ) != 0,
            "serialize actual fixture descriptor: {}",
            GetLastError()
        );
        let text_owner = LocalDescriptor(text.cast());
        anyhow::ensure!(length > 0, "empty fixture descriptor");
        let units = std::slice::from_raw_parts(text_owner.0.cast::<u16>(), length as usize);
        let actual_sddl = String::from_utf16(units.strip_suffix(&[0]).unwrap_or(units))?;
        if matches!(label, OutsideLabel::PreexistingLow) {
            anyhow::ensure!(
                actual_sddl.contains("(ML;;NW;;;LW)"),
                "Low mandatory label was not retained: {actual_sddl}"
            );
        }
        Ok(actual_sddl)
    }
}

fn token_integrity_rid(token: HANDLE) -> Result<u32> {
    unsafe {
        let mut needed = 0;
        GetTokenInformation(
            token,
            TokenIntegrityLevel,
            std::ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut needed,
        );
        anyhow::ensure!(needed > 0, "token integrity size query failed");
        let mut words = vec![0_usize; (needed as usize).div_ceil(size_of::<usize>())];
        anyhow::ensure!(
            GetTokenInformation(
                token,
                TokenIntegrityLevel,
                words.as_mut_ptr().cast(),
                needed,
                &mut needed
            ) != 0,
            "token integrity query: {}",
            GetLastError()
        );
        let label = &*words.as_ptr().cast::<TOKEN_MANDATORY_LABEL>();
        let count = *GetSidSubAuthorityCount(label.Label.Sid);
        anyhow::ensure!(count > 0, "invalid token integrity SID");
        Ok(*GetSidSubAuthority(label.Label.Sid, u32::from(count) - 1))
    }
}

#[test]
fn workspace_delete_permission_routes_diagnostic_matrix() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let cap = LocalSid::from_string("S-1-5-21-101-202-303-405")?;
    let mut everyone = unsafe { world_sid()? };
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?;
    }
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[cap.as_ptr()])?
    });
    let base_integrity = token_integrity_rid(base.0)?;
    // Keep these genuine capability-authorized create/read/nested-delete
    // controls alongside each outside route. No token integrity is changed.
    let allowed = [
        fixture.path().join("workspace"),
        fixture.path().join("temp"),
    ];
    for root in &allowed {
        std::fs::create_dir(root)?;
        unsafe { ensure_allow_write_aces(root, &[cap.as_ptr()])? };
        std::fs::create_dir(root.join("nested"))?;
        std::fs::write(root.join("nested/delete.txt"), "inside")?;
        std::fs::create_dir(root.join("nested/delete-dir"))?;
    }
    {
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        for root in &allowed {
            assert_eq!(
                std::fs::read_to_string(root.join("nested/delete.txt"))?,
                "inside"
            );
            std::fs::write(root.join("created.txt"), "allowed")?;
            std::fs::remove_file(root.join("nested/delete.txt"))?;
            std::fs::remove_dir(root.join("nested/delete-dir"))?;
            std::fs::remove_dir(root.join("nested"))?;
        }
    }
    let routes = [
        ("neither", 0, 0, OutsideLabel::Inherited),
        ("direct_delete_only", 0, DELETE, OutsideLabel::Inherited),
        (
            "parent_delete_child_only",
            FILE_DELETE_CHILD,
            0,
            OutsideLabel::Inherited,
        ),
        ("both", FILE_DELETE_CHILD, DELETE, OutsideLabel::Inherited),
        (
            "preexisting_low_both",
            FILE_DELETE_CHILD,
            DELETE,
            OutsideLabel::PreexistingLow,
        ),
    ];
    // Observe all native routes before evaluating the full matrix. In
    // particular, a privileged base-token control must not prevent collection
    // of the restricted results for the remaining DELETE_CHILD combinations.
    // No failed assertion is ignored: every expectation is checked below.
    let mut denied = Vec::new();
    let mut observed_control = Vec::new();
    let mut expected_control = Vec::new();
    let mut observed_control_denials = Vec::new();
    let mut expected_control_denials = Vec::new();
    let mut outside_reads = Vec::new();
    for (name, parent_right, object_right, label) in routes {
        let outside = fixture.path().join(name);
        std::fs::create_dir(&outside)?;
        let victims = [outside.join("control.txt"), outside.join("restricted.txt")];
        let directories = [outside.join("control-dir"), outside.join("restricted-dir")];
        for path in &victims {
            std::fs::write(path, "outside")?;
        }
        for path in &directories {
            std::fs::create_dir(path)?;
        }
        // Set child labels before replacing parent inheritance, which can remove
        // the WRITE_OWNER access required to set a mandatory label.
        let mut object_sddl = Vec::new();
        for (role, path) in [
            ("control_file", &victims[0]),
            ("restricted_file", &victims[1]),
            ("control_directory", &directories[0]),
            ("restricted_directory", &directories[1]),
        ] {
            object_sddl.push(
                fixture_acl(path, READ_EXECUTE | object_right, label)
                    .with_context(|| format!("prepare {name} {role} ACL/label"))?,
            );
        }
        let parent_sddl = fixture_acl(&outside, READ_EXECUTE | parent_right, label)
            .with_context(|| format!("prepare {name} parent ACL/label"))?;
        // The Low outside label, when selected, exists before this route's
        // restricted token is created by the unchanged production factory.
        let route_token = OwnedToken(unsafe {
            create_workspace_write_token_with_caps_from(base.0, &[cap.as_ptr()])?
        });
        let restricted_integrity = token_integrity_rid(route_token.0)?;
        let control = {
            let _impersonation = unsafe { Impersonation::enter(base.0)? };
            [
                Outcome::from_result(std::fs::remove_file(&victims[0])),
                Outcome::from_result(std::fs::remove_dir(&directories[0])),
            ]
        };
        let (outside_read, restricted) = {
            let _impersonation = unsafe { Impersonation::enter(route_token.0)? };
            let read = std::fs::read_to_string(&victims[1])?;
            let outcomes = [
                Outcome::from_result(std::fs::remove_file(&victims[1])),
                Outcome::from_result(std::fs::remove_dir(&directories[1])),
            ];
            (read, outcomes)
        };
        let expected_control = parent_right != 0 || object_right != 0;
        eprintln!(
            "HEPTA_DELETE_DIAGNOSTIC {}",
            serde_json::json!({
                "schema": "hepta.windows-delete-route.v1", "route": name,
                "sandbox_qualified": false, "production_token_modified": false,
                "label": label, "base_integrity_rid": base_integrity,
                "restricted_integrity_rid": restricted_integrity,
                "parent_sddl": parent_sddl, "object_sddl": object_sddl,
                "control_expected_success": expected_control,
                "control": control, "restricted": restricted,
                "outside_read": outside_read,
                "workspace_and_temp_nested_delete_controls_completed": true,
            })
        );
        // Re-enable ordinary cleanup only after both native observations, while
        // reverted to the original token; never use this ACL for the probe.
        for path in std::iter::once(&outside)
            .chain(victims.iter())
            .chain(&directories)
        {
            if path.try_exists()? {
                unsafe {
                    ensure_allow_mask_aces(path, &[everyone.as_mut_ptr().cast()], FILE_ALL_ACCESS)?;
                }
            }
        }
        observed_control.extend(control.iter().map(|outcome| outcome.succeeded));
        expected_control.extend([expected_control; 2]);
        if !expected_control {
            observed_control_denials.extend(control.iter().map(|outcome| outcome.win32_error));
            expected_control_denials.extend([Some(5); 2]);
        }
        outside_reads.push(outside_read);
        denied.extend(restricted.into_iter().map(|outcome| outcome.win32_error));
    }
    // Keep the original fail-closed assertions, but run them after every
    // native route has produced evidence. A DELETE escape or unexpectedly
    // privileged control still fails this security regression.
    assert_eq!(observed_control, expected_control);
    assert_eq!(observed_control_denials, expected_control_denials);
    assert_eq!(outside_reads, vec!["outside"; routes.len()]);
    assert_eq!(denied, vec![Some(5); routes.len() * 2]);
    Ok(())
}
