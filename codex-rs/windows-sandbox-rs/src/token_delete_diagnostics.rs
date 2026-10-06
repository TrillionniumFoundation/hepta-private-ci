//! Diagnostic-only decomposition of the broad-identity deletion regression.
//! Every ACL mutation is confined to a fresh owned temporary fixture.
use super::*;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::DuplicateToken;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PRIVILEGE_SET;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TokenHasRestrictions;
use windows_sys::Win32::Security::TokenIsAppContainer;
use windows_sys::Win32::Storage::FileSystem::DeleteFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::RemoveDirectoryW;

// No generic rights, inherited ACEs, owner-specific grant or ambient DACL may
// silently reintroduce one of the two deletion routes under investigation.
const NON_DELETE_ACCESS: u32 = FILE_ALL_ACCESS & !(DELETE | FILE_DELETE_CHILD);

unsafe fn replace_diagnostic_dacl(path: &Path, grants: &[(*mut c_void, u32)]) -> Result<()> {
    let entries: Vec<_> = grants
        .iter()
        .map(|&(sid, mask)| EXPLICIT_ACCESS_W {
            grfAccessPermissions: mask,
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: 0,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: std::ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid.cast(),
            },
        })
        .collect();
    let mut acl = std::ptr::null_mut();
    let code = SetEntriesInAclW(
        entries.len() as u32,
        entries.as_ptr(),
        std::ptr::null(),
        &mut acl,
    );
    if code != ERROR_SUCCESS {
        anyhow::bail!("diagnostic ACL construction: {code}");
    }
    let code = SetNamedSecurityInfoW(
        to_wide(path).as_ptr() as *mut u16,
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        acl,
        std::ptr::null_mut(),
    );
    LocalFree(acl as HLOCAL);
    anyhow::ensure!(code == ERROR_SUCCESS, "diagnostic ACL replacement: {code}");
    Ok(())
}

unsafe fn verify_diagnostic_dacl(path: &Path, grants: &[(*mut c_void, u32)]) -> Result<()> {
    let (acl, descriptor) = fetch_dacl_handle(path)?;
    let verified = (|| -> Result<()> {
        let mut control = 0;
        let mut revision = 0;
        anyhow::ensure!(
            GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) != 0,
            "diagnostic descriptor control: {}",
            GetLastError()
        );
        anyhow::ensure!(
            control & SE_DACL_PROTECTED != 0,
            "diagnostic DACL must be protected"
        );
        anyhow::ensure!(!acl.is_null(), "diagnostic DACL must not be null");
        anyhow::ensure!(
            (*acl).AceCount as usize == grants.len(),
            "unexpected diagnostic ACE count"
        );
        let mut seen = vec![false; grants.len()];
        for index in 0..(*acl).AceCount {
            let mut ace = std::ptr::null_mut();
            anyhow::ensure!(
                GetAce(acl, index as u32, &mut ace) != 0,
                "diagnostic GetAce: {}",
                GetLastError()
            );
            let header = &*ace.cast::<ACE_HEADER>();
            // ACCESS_ALLOWED_ACE_TYPE is zero. Reject every deny/object/generic
            // or inherited variant instead of treating it as an ordinary allow.
            anyhow::ensure!(
                header.AceType == 0 && header.AceFlags == 0,
                "unexpected diagnostic ACE type/flags"
            );
            let allow = &*ace.cast::<ACCESS_ALLOWED_ACE>();
            let sid = std::ptr::addr_of!(allow.SidStart) as *mut c_void;
            let matched = grants
                .iter()
                .enumerate()
                .position(|(slot, &(expected, mask))| {
                    !seen[slot] && EqualSid(sid, expected) != 0 && allow.Mask == mask
                });
            let slot = matched.ok_or_else(|| anyhow!("unexpected diagnostic ACE SID/mask"))?;
            seen[slot] = true;
        }
        anyhow::ensure!(seen.iter().all(|entry| *entry), "missing diagnostic grant");
        Ok(())
    })();
    LocalFree(descriptor as HLOCAL);
    verified
}

// Drop runs after each impersonation guard. Restore cleanup rights on only the
// owned paths, including on an early error; never weaken an external directory.
struct DiagnosticFixture {
    temp: tempfile::TempDir,
    paths: Vec<PathBuf>,
    everyone: LocalSid,
}

impl DiagnosticFixture {
    fn new() -> Result<Self> {
        Ok(Self {
            temp: tempfile::tempdir()?,
            paths: Vec::new(),
            everyone: LocalSid::from_string("S-1-1-0")?,
        })
    }
}

impl Drop for DiagnosticFixture {
    fn drop(&mut self) {
        for path in &self.paths {
            if path.exists() {
                // SAFETY: paths were created inside temp; the SID remains owned.
                if unsafe {
                    replace_diagnostic_dacl(path, &[(self.everyone.as_ptr(), FILE_ALL_ACCESS)])
                }
                .is_err()
                {
                    eprintln!("delete diagnostic: owned fixture cleanup ACL restoration failed");
                }
            }
        }
    }
}

// Validate restricting-list header and entry bounds before using its count.
// The handle is immutable throughout these queries; one entry plus the existing
// allowed-membership check establishes an exact singleton capability set.
unsafe fn token_restricting_sid_count(token: HANDLE) -> Result<u32> {
    let mut needed = 0;
    let queried = GetTokenInformation(
        token,
        TokenRestrictedSids,
        std::ptr::null_mut(),
        0,
        &mut needed,
    );
    let query_error = GetLastError();
    let count_size = std::mem::size_of::<u32>();
    let entries_offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    anyhow::ensure!(
        queried == 0 && query_error == ERROR_INSUFFICIENT_BUFFER,
        "diagnostic restricting-list size query: {query_error}"
    );
    // Expect an empty base list or one capability. Bound allocation independently
    // of the returned size and reject malformed/truncated layouts rather than read.
    anyhow::ensure!(
        (count_size..=64 * 1024).contains(&(needed as usize)),
        "unexpected diagnostic restricting-list size"
    );
    let capacity = needed;
    let mut storage = vec![0_usize; (capacity as usize).div_ceil(std::mem::size_of::<usize>())];
    anyhow::ensure!(
        GetTokenInformation(
            token,
            TokenRestrictedSids,
            storage.as_mut_ptr().cast(),
            capacity,
            &mut needed,
        ) != 0,
        "diagnostic restricting-list query: {}",
        GetLastError()
    );
    anyhow::ensure!(
        needed <= capacity && needed as usize >= count_size,
        "diagnostic restricting-list returned invalid length"
    );
    let count = std::ptr::read_unaligned(storage.as_ptr().cast::<u32>());
    // An empty variable-length TOKEN_GROUPS needs only its count field. Do not
    // require or access the aligned Groups member when no entries are present.
    if count == 0 {
        return Ok(0);
    }
    anyhow::ensure!(
        needed as usize >= entries_offset,
        "diagnostic restricting-list entry offset exceeds buffer"
    );
    let available_entries =
        (needed as usize - entries_offset) / std::mem::size_of::<SID_AND_ATTRIBUTES>();
    anyhow::ensure!(
        count as usize <= available_entries,
        "diagnostic restricting-list entries exceed buffer"
    );
    Ok(count)
}

unsafe fn token_diagnostic_u32(token: HANDLE, role: &str, class: i32) -> Option<u32> {
    // Optional metadata only. Decode a DWORD only under its documented contract;
    // an unsuccessful call or different returned length remains unknown.
    let mut value = 0_u32;
    let capacity = std::mem::size_of_val(&value) as u32;
    let mut needed = 0;
    let queried = GetTokenInformation(
        token,
        class,
        (&mut value as *mut u32).cast(),
        capacity,
        &mut needed,
    );
    let win32_error = if queried == 0 {
        Some(GetLastError())
    } else {
        None
    };
    let decoded = if queried != 0 && needed == capacity {
        Some(value)
    } else {
        None
    };
    eprintln!(
        "delete diagnostic token_query role={role} class={class} capacity={capacity} return_length={needed} api_return={queried} win32_error={win32_error:?} zero_initialized_buffer={:02x?} decoded_dword={decoded:?}",
        value.to_ne_bytes(),
    );
    decoded
}

// This is a test-only ordinary-identity control, not a production token policy.
// Disable maximum privileges without LUA_TOKEN or restricting SIDs. Windows
// retains SeChangeNotifyPrivilege; this isolates privilege differences without
// claiming to strip traversal privilege or change ordinary group membership.
unsafe fn max_privileges_disabled_control(base: HANDLE) -> Result<OwnedToken> {
    let mut token = 0;
    anyhow::ensure!(
        CreateRestrictedToken(
            base,
            DISABLE_MAX_PRIVILEGE,
            0,
            std::ptr::null(),
            0,
            std::ptr::null(),
            0,
            std::ptr::null(),
            &mut token,
        ) != 0,
        "diagnostic max-privileges-disabled control: {}",
        GetLastError()
    );
    let token = OwnedToken(token);
    anyhow::ensure!(
        token_restricting_sid_count(token.0)? == 0,
        "max-privileges-disabled control unexpectedly has restricting SIDs"
    );
    Ok(token)
}

// Observe the ACL check for each right independently of NTFS deletion fallback.
// AccessCheck is supporting evidence only; the native delete plus existence
// assertion below remains the actual boundary test.
unsafe fn observe_delete_right(path: &Path, token: HANDLE, right: u32, role: &str) -> Result<()> {
    let mut descriptor = std::ptr::null_mut();
    let code = GetNamedSecurityInfoW(
        to_wide(path).as_ptr(),
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION | OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut descriptor,
    );
    if code != ERROR_SUCCESS {
        if !descriptor.is_null() {
            LocalFree(descriptor as HLOCAL);
        }
        anyhow::bail!("diagnostic access-check descriptor: {code}");
    }
    let result = (|| -> Result<()> {
        let mut duplicate = 0;
        anyhow::ensure!(
            DuplicateToken(token, SecurityImpersonation, &mut duplicate) != 0,
            "diagnostic impersonation-token duplicate: {}",
            GetLastError()
        );
        let duplicate = OwnedToken(duplicate);
        let mapping = GENERIC_MAPPING {
            GenericRead: FILE_GENERIC_READ,
            GenericWrite: FILE_GENERIC_WRITE,
            GenericExecute: FILE_GENERIC_EXECUTE,
            GenericAll: FILE_ALL_ACCESS,
        };
        // Aligned, fixed bounded output storage. A larger required size is a
        // reported API failure, never an unchecked read or allocation request.
        let mut privileges = [0_usize; 512];
        let mut length = std::mem::size_of_val(&privileges) as u32;
        let mut granted = 0;
        let mut allowed = 0;
        let queried = AccessCheck(
            descriptor,
            duplicate.0,
            right,
            &mapping,
            privileges.as_mut_ptr().cast::<PRIVILEGE_SET>(),
            &mut length,
            &mut granted,
            &mut allowed,
        );
        let error = if queried == 0 || allowed == 0 {
            Some(GetLastError())
        } else {
            None
        };
        eprintln!(
            "delete diagnostic access_check role={role} right={right:#x} api_return={queried} allowed={allowed} granted={granted:#x} privilege_buffer_length={length} win32_error={error:?}"
        );
        anyhow::ensure!(queried != 0, "diagnostic AccessCheck failed: {error:?}");
        Ok(())
    })();
    LocalFree(descriptor as HLOCAL);
    result
}

#[derive(Debug)]
struct DeleteObservation {
    capability: &'static str,
    directory: bool,
    restricted: bool,
    win32_error: u32,
    exists_after: bool,
    expected_delete: bool,
}

fn deletion_permission_matrix(object_delete: bool, parent_delete_child: bool) -> Result<()> {
    deletion_permission_matrix_with_control(object_delete, parent_delete_child, false)
}

fn deletion_permission_matrix_with_control(
    object_delete: bool,
    parent_delete_child: bool,
    disable_control_max_privileges: bool,
) -> Result<()> {
    let mut fixture = DiagnosticFixture::new()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let ordinary_control = if disable_control_max_privileges {
        Some(unsafe { max_privileges_disabled_control(base.0)? })
    } else {
        None
    };
    let control_token = ordinary_control.as_ref().map_or(base.0, |token| token.0);
    let control_role = if disable_control_max_privileges {
        "max-privileges-disabled"
    } else {
        "raw-base"
    };
    let allowed = LocalSid::from_string("S-1-5-21-181-282-383-484")?;
    let unrelated = LocalSid::from_string("S-1-5-21-191-292-393-494")?;
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let logon_sid = logon.as_mut_ptr().cast();
    let everyone_sid = fixture.everyone.as_ptr();
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[allowed.as_ptr()])?
    });
    let base_restricting_count = unsafe { token_restricting_sid_count(base.0)? };
    anyhow::ensure!(
        base_restricting_count == 0,
        "base-token control has restricting SIDs"
    );
    let restricting_count = unsafe { token_restricting_sid_count(token.0)? };
    let base_has_restrictions =
        unsafe { token_diagnostic_u32(base.0, "base", TokenHasRestrictions) };
    let (has_restrictions, app_container, has_allowed, has_unrelated, has_world, has_logon) = unsafe {
        (
            token_diagnostic_u32(token.0, "restricted", TokenHasRestrictions),
            token_diagnostic_u32(token.0, "restricted", TokenIsAppContainer),
            token_has_restricting_sid(token.0, allowed.as_ptr())?,
            token_has_restricting_sid(token.0, unrelated.as_ptr())?,
            token_has_restricting_sid(token.0, everyone_sid)?,
            token_has_restricting_sid(token.0, logon_sid)?,
        )
    };
    // Creation flags are source-declared, not an inferred runtime TOKEN flag.
    eprintln!(
        "delete diagnostic control={control_role} object_delete={object_delete} parent_delete_child={parent_delete_child} declared_creation_flags={:#x} has_restrictions={has_restrictions:?} app_container={app_container:?} base_has_restrictions={base_has_restrictions:?} base_restricting_count={base_restricting_count} restricting_count={restricting_count} restricting_allowed={has_allowed} restricting_unrelated={has_unrelated} restricting_world={has_world} restricting_logon={has_logon}",
        DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED,
    );
    anyhow::ensure!(
        restricting_count == 1 && has_allowed && !has_unrelated && !has_world && !has_logon,
        "diagnostic capability membership mismatch"
    );
    let parent_mask = NON_DELETE_ACCESS
        | if parent_delete_child {
            FILE_DELETE_CHILD
        } else {
            0
        };
    let object_mask = NON_DELETE_ACCESS | if object_delete { DELETE } else { 0 };
    let mut observations = Vec::new();
    for (label, cap) in [
        ("absent", None),
        ("allowed", Some(allowed.as_ptr())),
        ("unrelated", Some(unrelated.as_ptr())),
    ] {
        for directory in [false, true] {
            for restricted in [false, true] {
                let parent = fixture
                    .temp
                    .path()
                    .join(format!("{label}-{directory}-{restricted}"));
                std::fs::create_dir(&parent)?;
                fixture.paths.push(parent.clone());
                let child = parent.join("probe");
                if directory {
                    std::fs::create_dir(&child)?;
                } else {
                    std::fs::write(&child, b"deletion diagnostic")?;
                }
                fixture.paths.push(child.clone());
                let mut parent_grants = vec![(everyone_sid, parent_mask), (logon_sid, parent_mask)];
                let mut child_grants = vec![(everyone_sid, object_mask), (logon_sid, object_mask)];
                if let Some(sid) = cap {
                    parent_grants.push((sid, parent_mask));
                    child_grants.push((sid, object_mask));
                }
                // SAFETY: fixture paths and every SID remain live; protected,
                // explicit DACLs are read back before any impersonated action.
                unsafe {
                    replace_diagnostic_dacl(&parent, &parent_grants)?;
                    replace_diagnostic_dacl(&child, &child_grants)?;
                    verify_diagnostic_dacl(&parent, &parent_grants)?;
                    verify_diagnostic_dacl(&child, &child_grants)?;
                }
                let selected = if restricted { token.0 } else { control_token };
                let role = if restricted {
                    "restricted"
                } else {
                    control_role
                };
                eprintln!(
                    "delete diagnostic rights control={control_role} capability={label} directory={directory} restricted={restricted}"
                );
                for (path, right) in [(&parent, FILE_DELETE_CHILD), (&child, DELETE)] {
                    // Supporting metadata must never suppress a native boundary
                    // observation. API failure stays explicitly unknown.
                    if let Err(error) = unsafe { observe_delete_right(path, selected, right, role) }
                    {
                        eprintln!(
                            "delete diagnostic access_check_unknown role={role} right={right:#x} error={error}"
                        );
                    }
                }
                let wide = to_wide(&child);
                let win32_error = {
                    let _impersonation = unsafe { Impersonation::enter(selected)? };
                    // Record GetLastError immediately, before any other API call.
                    let succeeded = unsafe {
                        if directory {
                            RemoveDirectoryW(wide.as_ptr())
                        } else {
                            DeleteFileW(wide.as_ptr())
                        }
                    };
                    if succeeded != 0 {
                        ERROR_SUCCESS
                    } else {
                        unsafe { GetLastError() }
                    }
                };
                // Check existence only after reverting to the ordinary identity.
                // Errors other than not-found must not masquerade as absence.
                let exists_after = match std::fs::symlink_metadata(&child) {
                    Ok(_) => true,
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
                    Err(error) => return Err(error.into()),
                };
                let observation = DeleteObservation {
                    capability: label,
                    directory,
                    restricted,
                    win32_error,
                    exists_after,
                    expected_delete: (object_delete || parent_delete_child)
                        && (!restricted || label == "allowed"),
                };
                eprintln!(
                    "delete diagnostic control={control_role} capability={} directory={} restricted={} win32_error={} exists_after={} expected_delete={}",
                    observation.capability,
                    observation.directory,
                    observation.restricted,
                    observation.win32_error,
                    observation.exists_after,
                    observation.expected_delete,
                );
                observations.push(observation);
            }
        }
    }
    // Collect every case before asserting so one escape does not hide which
    // independent route, object kind or capability control distinguished it.
    let mismatches: Vec<_> = observations
        .iter()
        .filter(|observation| {
            let expected_code = if observation.expected_delete {
                ERROR_SUCCESS
            } else {
                ERROR_ACCESS_DENIED
            };
            observation.win32_error != expected_code
                || observation.exists_after == observation.expected_delete
        })
        .collect();
    anyhow::ensure!(
        mismatches.is_empty(),
        "deletion isolation mismatches: {mismatches:?}"
    );
    Ok(())
}

#[test]
fn deletion_isolation_with_neither_delete_route() -> Result<()> {
    deletion_permission_matrix(false, false)
}

#[test]
fn deletion_isolation_with_object_delete_only() -> Result<()> {
    deletion_permission_matrix(true, false)
}

#[test]
fn deletion_isolation_with_parent_delete_child_only() -> Result<()> {
    deletion_permission_matrix(false, true)
}

#[test]
fn deletion_isolation_with_both_delete_routes() -> Result<()> {
    deletion_permission_matrix(true, true)
}

// Retain the original raw-base matrices and their assertions. These additional
// matrices change only the ordinary control, never the production restricted token.
#[test]
fn deletion_isolation_max_privileges_disabled_neither_route() -> Result<()> {
    deletion_permission_matrix_with_control(false, false, true)
}

#[test]
fn deletion_isolation_max_privileges_disabled_object_delete_only() -> Result<()> {
    deletion_permission_matrix_with_control(true, false, true)
}

#[test]
fn deletion_isolation_max_privileges_disabled_parent_delete_child_only() -> Result<()> {
    deletion_permission_matrix_with_control(false, true, true)
}

#[test]
fn deletion_isolation_max_privileges_disabled_both_routes() -> Result<()> {
    deletion_permission_matrix_with_control(true, true, true)
}
