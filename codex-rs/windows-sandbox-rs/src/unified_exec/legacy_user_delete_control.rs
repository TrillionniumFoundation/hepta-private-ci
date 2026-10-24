//! Fixture-only causal controls. Never apply these helpers to production roots.
//! Receipts alias all SIDs locally; no paths or raw identity SIDs are emitted.

use super::legacy_delete_probe::Aliases;
use super::legacy_delete_probe::object_snapshot;
use crate::token::LocalSid;
use crate::token::create_workspace_write_token_with_caps_from;
use crate::token::get_current_token_for_restriction;
use crate::winutil::to_wide;
use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::ffi::c_void;
use std::mem::size_of;
use std::os::windows::fs::MetadataExt;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::DeleteFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::RemoveDirectoryW;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

const RX: u32 = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE;
struct Handle(HANDLE);
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}
struct Local(*mut c_void);
impl Drop for Local {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { LocalFree(self.0) };
        }
    }
}
struct Impersonation;
impl Drop for Impersonation {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            std::process::abort();
        }
    }
}

fn user_sid(token: HANDLE) -> Result<Vec<u8>> {
    let mut n = 0;
    unsafe {
        GetTokenInformation(
            token,
            TokenUser,
            std::ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut n,
        )
    };
    ensure!(
        (size_of::<TOKEN_USER>() as u32..=65536).contains(&n),
        "token user size invalid"
    );
    let capacity = n;
    let mut words = vec![0_usize; (n as usize).div_ceil(size_of::<usize>())];
    ensure!(
        unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                words.as_mut_ptr().cast(),
                capacity,
                &mut n,
            )
        } != 0
            && n <= capacity
            && n as usize >= size_of::<TOKEN_USER>(),
        "token user query failed"
    );
    let sid = unsafe { (*words.as_ptr().cast::<TOKEN_USER>()).User.Sid };
    let length = unsafe { GetLengthSid(sid) };
    ensure!((8..=68).contains(&length), "token user SID size invalid");
    let mut bytes = vec![0; length as usize];
    ensure!(
        unsafe { CopySid(length, bytes.as_mut_ptr().cast(), sid) } != 0,
        "copy token user failed"
    );
    Ok(bytes)
}

fn restricting_aliases(token: HANDLE, aliases: &mut Aliases) -> Result<Vec<String>> {
    let mut n = 0;
    unsafe {
        GetTokenInformation(
            token,
            TokenRestrictedSids,
            std::ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut n,
        )
    };
    ensure!((4..=65536).contains(&n), "restricting SID size invalid");
    let capacity = n;
    let mut words = vec![0_usize; (n as usize).div_ceil(size_of::<usize>())];
    ensure!(
        unsafe {
            GetTokenInformation(
                token,
                TokenRestrictedSids,
                words.as_mut_ptr().cast(),
                capacity,
                &mut n,
            )
        } != 0
            && (4..=capacity).contains(&n),
        "restricting SID query failed"
    );
    let start = words.as_ptr().cast::<u8>();
    let count = unsafe { std::ptr::read_unaligned(start.cast::<u32>()) } as usize;
    let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    ensure!(
        count <= (n as usize).saturating_sub(offset) / size_of::<SID_AND_ATTRIBUTES>(),
        "restricting SID array bounds"
    );
    (0..count)
        .map(|index| {
            let entry = unsafe {
                std::ptr::read_unaligned(start.add(offset).cast::<SID_AND_ATTRIBUTES>().add(index))
            };
            unsafe { aliases.name(entry.Sid) }
        })
        .collect()
}

// Reject all reparse points before inheritable writes, including junctions.
// This test seeds only a small tree; no ambient tree traversal is authorized.
fn check_fixture_tree(root: &Path) -> Result<()> {
    let mut pending = vec![root.to_path_buf()];
    let mut count = 0;
    while let Some(path) = pending.pop() {
        count += 1;
        ensure!(count <= 128, "fixture tree exceeds bounded scope");
        let metadata = std::fs::symlink_metadata(&path)
            .map_err(|_| anyhow::anyhow!("inspect fixture tree failed"))?;
        ensure!(
            metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT == 0,
            "fixture reparse point rejected"
        );
        if metadata.is_dir() {
            for entry in
                std::fs::read_dir(&path).map_err(|_| anyhow::anyhow!("read fixture tree failed"))?
            {
                pending.push(
                    entry
                        .map_err(|_| anyhow::anyhow!("read fixture entry failed"))?
                        .path(),
                );
                ensure!(pending.len() <= 128, "fixture tree exceeds bounded scope");
            }
        }
    }
    Ok(())
}

// GRANT_ACCESS merges allow rights rather than replacing them. Existing deny
// ACEs are retained; only DELETE is requested, never FILE_DELETE_CHILD.
fn grant(path: &Path, sid: *mut c_void, mask: u32, inheritance: u32) -> Result<()> {
    let mut descriptor = Local(std::ptr::null_mut());
    let mut old = std::ptr::null_mut();
    ensure!(
        unsafe {
            GetNamedSecurityInfoW(
                to_wide(path).as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut old,
                std::ptr::null_mut(),
                &mut descriptor.0,
            )
        } == ERROR_SUCCESS
            && !old.is_null(),
        "read fixture DACL failed or null DACL"
    );
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: mask,
        grfAccessMode: GRANT_ACCESS,
        grfInheritance: inheritance,
        Trustee: TRUSTEE_W {
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: sid.cast(),
            ..unsafe { std::mem::zeroed() }
        },
    };
    let mut new = std::ptr::null_mut();
    let status = unsafe {
        SetEntriesInAclW(/*ccountofexplicitentries*/ 1, &entry, old, &mut new)
    };
    let _new_owner = Local(new.cast());
    ensure!(
        status == ERROR_SUCCESS && !new.is_null(),
        "merge fixture DACL failed"
    );
    ensure!(
        unsafe {
            SetNamedSecurityInfoW(
                to_wide(path).as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                new,
                std::ptr::null_mut(),
            )
        } == ERROR_SUCCESS,
        "apply fixture DACL failed"
    );
    Ok(())
}

fn preserved(before: &Value, after: &Value) -> Result<()> {
    let old = before["aces"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("missing old ACEs"))?;
    let new = after["aces"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("missing new ACEs"))?;
    ensure!(
        before["owner_sid_alias"] == after["owner_sid_alias"]
            && before["descriptor_control"]
                .as_u64()
                .zip(after["descriptor_control"].as_u64())
                .is_some_and(|(a, b)| (a ^ b) & u64::from(SE_DACL_PROTECTED) == 0)
            && before["null_dacl"] == false
            && after["null_dacl"] == false,
        "fixture owner or DACL protection changed"
    );
    for ace in old {
        ensure!(
            new.iter().any(|candidate| candidate == ace
                || (ace["kind"] == "allow"
                    && candidate["kind"] == "allow"
                    && ace["flags"] == candidate["flags"]
                    && ace["sid_alias"] == candidate["sid_alias"]
                    && ace["mask"]
                        .as_u64()
                        .zip(candidate["mask"].as_u64())
                        .is_some_and(|(a, b)| a & b == a))),
            "existing fixture ACE lost or narrowed"
        );
    }
    Ok(())
}

pub(super) fn grant_user_delete(owned_root: &Path, allowed_roots: &[&Path]) -> Result<Value> {
    ensure!(
        allowed_roots.len() == 3,
        "exactly three fixture writable roots required"
    );
    let owned = owned_root
        .canonicalize()
        .map_err(|_| anyhow::anyhow!("resolve owned fixture failed"))?;
    let roots = allowed_roots
        .iter()
        .map(|path| {
            let metadata = std::fs::symlink_metadata(path)
                .map_err(|_| anyhow::anyhow!("inspect fixture root failed"))?;
            ensure!(
                metadata.is_dir() && !metadata.file_type().is_symlink(),
                "fixture root must be ordinary directory"
            );
            let canonical = path
                .canonicalize()
                .map_err(|_| anyhow::anyhow!("resolve fixture root failed"))?;
            ensure!(
                canonical != owned && canonical.starts_with(&owned),
                "writable root escapes owned fixture"
            );
            Ok(canonical)
        })
        .collect::<Result<Vec<_>>>()?;
    for (index, root) in roots.iter().enumerate() {
        ensure!(
            roots.iter().enumerate().all(|(other, path)| other == index
                || (!root.starts_with(path) && !path.starts_with(root))),
            "fixture writable roots overlap"
        );
    }
    for root in &roots {
        check_fixture_tree(root)?;
    }
    let base = Handle(unsafe { get_current_token_for_restriction()? });
    let mut user = user_sid(base.0)?;
    let mut aliases = Aliases::default();
    let user_alias = unsafe { aliases.name(user.as_mut_ptr().cast())? };
    let mut receipts = Vec::new();
    for (index, path) in roots.iter().enumerate() {
        let before = object_snapshot(path, &mut aliases)?;
        grant(
            path,
            user.as_mut_ptr().cast(),
            DELETE,
            OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        )?;
        let after = object_snapshot(path, &mut aliases)?;
        preserved(&before, &after)?;
        receipts.push(json!({"root_index": index, "before": before, "after": after}));
    }
    Ok(
        json!({"schema": "hepta.fixture-user-delete-grant.v1", "user_sid_alias": user_alias, "alias_scope": "this_receipt_only", "requested_mask": DELETE, "requested_delete_child": false, "mode": "GRANT_ACCESS", "roots": receipts}),
    )
}

fn protected_rx(path: &Path) -> Result<()> {
    let mut descriptor = Local(std::ptr::null_mut());
    let sddl = to_wide(format!("D:P(A;;0x{RX:x};;;WD)"));
    ensure!(
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                SDDL_REVISION_1,
                &mut descriptor.0,
                std::ptr::null_mut(),
            )
        } != 0,
        "parse fixture RX DACL failed"
    );
    let mut dacl = std::ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    ensure!(
        unsafe { GetSecurityDescriptorDacl(descriptor.0, &mut present, &mut dacl, &mut defaulted) }
            != 0
            && present != 0
            && !dacl.is_null(),
        "fixture RX DACL missing"
    );
    ensure!(
        unsafe {
            SetNamedSecurityInfoW(
                to_wide(path).as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                dacl,
                std::ptr::null_mut(),
            )
        } == ERROR_SUCCESS,
        "set fixture RX DACL failed"
    );
    Ok(())
}

pub(super) fn negative_controls(owned_root: &Path) -> Result<Value> {
    // Own a new, unique subtree, separate from the three legacy writable roots.
    let fixture = tempfile::tempdir_in(owned_root)
        .map_err(|_| anyhow::anyhow!("create negative fixture failed"))?;
    let parent = fixture.path().join("rx-parent");
    std::fs::create_dir(&parent).map_err(|_| anyhow::anyhow!("create negative parent failed"))?;
    let base = Handle(unsafe { get_current_token_for_restriction()? });
    let mut user = user_sid(base.0)?;
    let cap = LocalSid::from_string("S-1-5-21-101-202-303-407")?;
    let wrong_cap = LocalSid::from_string("S-1-5-21-101-202-303-408")?;
    // A valid nonempty capability list in both negatives. No constructor-error shortcut.
    let restricted =
        Handle(unsafe { create_workspace_write_token_with_caps_from(base.0, &[cap.as_ptr()])? });
    let mut aliases = Aliases::default();
    let user_alias = unsafe { aliases.name(user.as_mut_ptr().cast())? };
    let cap_alias = unsafe { aliases.name(cap.as_ptr())? };
    let wrong_alias = unsafe { aliases.name(wrong_cap.as_ptr())? };
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let everyone_alias = unsafe { aliases.name(everyone.as_ptr())? };
    let restricted_aliases = restricting_aliases(restricted.0, &mut aliases)?;
    ensure!(
        restricted_aliases == vec![cap_alias.clone()] && !restricted_aliases.contains(&user_alias),
        "negative token must restrict only to fixture capability"
    );
    let mut restricted_user = user_sid(restricted.0)?;
    ensure!(
        unsafe { aliases.name(restricted_user.as_mut_ptr().cast())? } == user_alias,
        "negative token user changed"
    );
    let roles = ["no_matching_capability", "wrong_root_capability"];
    let files = roles.map(|role| parent.join(format!("{role}.txt")));
    let directories = roles.map(|role| parent.join(format!("{role}-dir")));
    let mut objects = Vec::new();
    for index in 0..roles.len() {
        std::fs::write(&files[index], "fixture")
            .map_err(|_| anyhow::anyhow!("seed negative file failed"))?;
        std::fs::create_dir(&directories[index])
            .map_err(|_| anyhow::anyhow!("seed negative directory failed"))?;
        for (kind, path) in [("file", &files[index]), ("directory", &directories[index])] {
            protected_rx(path)?;
            grant(
                path,
                user.as_mut_ptr().cast(),
                DELETE,
                /*inheritance*/ 0,
            )?;
            if index == 1 {
                grant(
                    path,
                    wrong_cap.as_ptr(),
                    RX | DELETE,
                    /*inheritance*/ 0,
                )?;
            }
            let acl = object_snapshot(path, &mut aliases)?;
            let aces = acl["aces"]
                .as_array()
                .ok_or_else(|| anyhow::anyhow!("negative ACE inventory missing"))?;
            ensure!(
                acl["descriptor_control"]
                    .as_u64()
                    .is_some_and(|control| control & u64::from(SE_DACL_PROTECTED) != 0)
                    && aces.len() == 2 + index
                    && aces
                        .iter()
                        .filter(|ace| ace["sid_alias"] == user_alias && ace["mask"] == DELETE)
                        .count()
                        == 1
                    && aces
                        .iter()
                        .filter(|ace| ace["sid_alias"] == everyone_alias && ace["mask"] == RX)
                        .count()
                        == 1
                    && (index == 0
                        || aces
                            .iter()
                            .filter(|ace| ace["sid_alias"] == wrong_alias
                                && ace["mask"] == (RX | DELETE))
                            .count()
                            == 1)
                    && aces.iter().all(|ace| ace["kind"] == "allow"
                        && ace["flags"] == 0
                        && ace["mask"]
                            .as_u64()
                            .is_some_and(|mask| mask & u64::from(FILE_DELETE_CHILD) == 0)),
                "negative ACL route contaminated"
            );
            objects.push(json!({"role": roles[index], "kind": kind, "acl": acl}));
        }
    }
    protected_rx(&parent)?;
    let parent_acl = object_snapshot(&parent, &mut aliases)?;
    ensure!(
        parent_acl["descriptor_control"]
            .as_u64()
            .is_some_and(|control| control & u64::from(SE_DACL_PROTECTED) != 0),
        "negative parent must be protected"
    );
    let parent_aces = parent_acl["aces"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("negative parent ACEs missing"))?;
    ensure!(
        parent_aces.len() == 1
            && parent_aces[0]["sid_alias"] == everyone_alias
            && parent_aces[0]["mask"] == RX
            && parent_aces[0]["kind"] == "allow"
            && parent_aces[0]["flags"] == 0,
        "negative parent is not exact RX"
    );
    let mut results = Vec::new();
    {
        ensure!(
            unsafe { ImpersonateLoggedOnUser(restricted.0) } != 0,
            "negative impersonation failed"
        );
        let _impersonation = Impersonation;
        let mut effective = 0;
        ensure!(
            unsafe {
                OpenThreadToken(
                    GetCurrentThread(),
                    TOKEN_QUERY,
                    /*openasself*/ 1,
                    &mut effective,
                )
            } != 0,
            "read effective negative token failed"
        );
        let effective = Handle(effective);
        ensure!(
            restricting_aliases(effective.0, &mut aliases)? == restricted_aliases,
            "effective negative restricting SIDs differ"
        );
        let mut effective_user = user_sid(effective.0)?;
        ensure!(
            unsafe { aliases.name(effective_user.as_mut_ptr().cast())? } == user_alias,
            "effective negative user differs"
        );
        for index in 0..roles.len() {
            let file_ok = unsafe { DeleteFileW(to_wide(&files[index]).as_ptr()) } != 0;
            let file_error = if file_ok {
                None
            } else {
                Some(unsafe { GetLastError() })
            };
            let dir_ok = unsafe { RemoveDirectoryW(to_wide(&directories[index]).as_ptr()) } != 0;
            let dir_error = if dir_ok {
                None
            } else {
                Some(unsafe { GetLastError() })
            };
            results.push(json!({"role": roles[index], "file_succeeded": file_ok, "file_win32_error": file_error, "directory_succeeded": dir_ok, "directory_win32_error": dir_error}));
        }
    }
    let retained = files
        .iter()
        .zip(directories.iter())
        .map(|(file, dir)| {
            Ok([
                file.try_exists()
                    .map_err(|_| anyhow::anyhow!("check negative file failed"))?,
                dir.try_exists()
                    .map_err(|_| anyhow::anyhow!("check negative directory failed"))?,
            ])
        })
        .collect::<Result<Vec<_>>>()?;
    let receipt = json!({"schema": "hepta.fixture-user-delete-negatives.v1", "alias_scope": "this_receipt_only", "user_sid_alias": user_alias, "token_capability_sid_alias": cap_alias, "actual_restricting_sid_aliases": restricted_aliases, "user_in_restricting_sids": false, "effective_token_checked": true, "wrong_capability_sid_alias": wrong_alias, "parent_acl": parent_acl, "objects": objects, "results": results, "retained": retained, "execution_context": "impersonated_thread_not_spawned_child", "production_token_modified": false, "sandbox_qualified": false});
    eprintln!("HEPTA_USER_DELETE_NEGATIVES {receipt}");
    for result in &results {
        assert_eq!(
            (
                result["file_succeeded"].as_bool(),
                result["file_win32_error"].as_u64(),
                result["directory_succeeded"].as_bool(),
                result["directory_win32_error"].as_u64()
            ),
            (Some(false), Some(5), Some(false), Some(5))
        );
    }
    assert_eq!(retained, vec![[true; 2]; 2]);
    Ok(receipt)
}
