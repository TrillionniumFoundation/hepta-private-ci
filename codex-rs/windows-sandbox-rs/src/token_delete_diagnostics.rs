//! Diagnostic-only decomposition of the broad-identity deletion regression.
//! Every ACL mutation is confined to a fresh owned temporary fixture.
use super::*;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TokenHasRestrictions;
use windows_sys::Win32::Security::TokenIsAppContainer;
use windows_sys::Win32::Storage::FileSystem::DeleteFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
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
    let entries_offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    anyhow::ensure!(
        queried == 0 && query_error == ERROR_INSUFFICIENT_BUFFER,
        "diagnostic restricting-list size query: {query_error}"
    );
    // This diagnostic expects one capability. Bound allocation independently of
    // the returned size and reject malformed/truncated layouts rather than read.
    anyhow::ensure!(
        (entries_offset..=64 * 1024).contains(&(needed as usize)),
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
        needed <= capacity && needed as usize >= entries_offset,
        "diagnostic restricting-list returned invalid length"
    );
    let count = std::ptr::read_unaligned(storage.as_ptr().cast::<u32>());
    let available_entries =
        (needed as usize - entries_offset) / std::mem::size_of::<SID_AND_ATTRIBUTES>();
    anyhow::ensure!(
        count as usize <= available_entries,
        "diagnostic restricting-list entries exceed buffer"
    );
    Ok(count)
}

unsafe fn token_diagnostic_u32(token: HANDLE, class: i32) -> Result<u32> {
    let mut value = 0_u32;
    let mut needed = 0;
    anyhow::ensure!(
        GetTokenInformation(
            token,
            class,
            (&mut value as *mut u32).cast(),
            4,
            &mut needed,
        ) != 0,
        "diagnostic token query class={class}: {}",
        GetLastError()
    );
    anyhow::ensure!(needed == 4, "unexpected diagnostic token query size");
    Ok(value)
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
    let mut fixture = DiagnosticFixture::new()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let allowed = LocalSid::from_string("S-1-5-21-181-282-383-484")?;
    let unrelated = LocalSid::from_string("S-1-5-21-191-292-393-494")?;
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let logon_sid = logon.as_mut_ptr().cast();
    let everyone_sid = fixture.everyone.as_ptr();
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[allowed.as_ptr()])?
    });
    let restricting_count = unsafe { token_restricting_sid_count(token.0)? };
    let (has_restrictions, app_container, has_allowed, has_unrelated, has_world, has_logon) = unsafe {
        (
            token_diagnostic_u32(token.0, TokenHasRestrictions)?,
            token_diagnostic_u32(token.0, TokenIsAppContainer)?,
            token_has_restricting_sid(token.0, allowed.as_ptr())?,
            token_has_restricting_sid(token.0, unrelated.as_ptr())?,
            token_has_restricting_sid(token.0, everyone_sid)?,
            token_has_restricting_sid(token.0, logon_sid)?,
        )
    };
    // Creation flags are source-declared, not an inferred runtime TOKEN flag.
    eprintln!(
        "delete diagnostic object_delete={object_delete} parent_delete_child={parent_delete_child} declared_creation_flags={:#x} has_restrictions={has_restrictions} app_container={app_container} restricting_count={restricting_count} restricting_allowed={has_allowed} restricting_unrelated={has_unrelated} restricting_world={has_world} restricting_logon={has_logon}",
        DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED,
    );
    anyhow::ensure!(
        restricting_count == 1 && has_allowed && !has_unrelated && !has_world && !has_logon,
        "diagnostic capability membership mismatch"
    );
    anyhow::ensure!(
        unsafe { token_diagnostic_u32(base.0, TokenHasRestrictions)? } == 0,
        "base-token control is already restricted"
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
                let wide = to_wide(&child);
                let win32_error = {
                    let selected = if restricted { token.0 } else { base.0 };
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
                    "delete diagnostic capability={} directory={} restricted={} win32_error={} exists_after={} expected_delete={}",
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
