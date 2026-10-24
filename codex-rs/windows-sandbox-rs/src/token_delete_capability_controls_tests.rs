//! Isolate object DELETE from ambient parent DELETE_CHILD without changing production policy.

use super::*;
use crate::acl::ensure_allow_mask_aces_with_inheritance;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Storage::FileSystem::DeleteFileW;
use windows_sys::Win32::Storage::FileSystem::RemoveDirectoryW;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

// Aliases are stable only within this test. Never retain real user, logon, or
// machine SIDs in the diagnostic output.
#[derive(Default)]
struct SidAliases(Vec<(Vec<u8>, String)>);

impl SidAliases {
    unsafe fn name(&mut self, sid: *mut c_void) -> Result<String> {
        let length = GetLengthSid(sid);
        anyhow::ensure!(
            (8..=68).contains(&length),
            "unexpected diagnostic SID length"
        );
        let mut bytes = vec![0; length as usize];
        anyhow::ensure!(
            CopySid(length, bytes.as_mut_ptr().cast(), sid) != 0,
            "copy diagnostic SID: {}",
            GetLastError()
        );
        if let Some((_, name)) = self.0.iter().find(|(known, _)| *known == bytes) {
            return Ok(name.clone());
        }
        let name = format!("opaque_sid_{}", self.0.len());
        self.0.push((bytes, name.clone()));
        Ok(name)
    }
}

fn token_sid_rows(
    token: HANDLE,
    information_class: i32,
    aliases: &mut SidAliases,
) -> Result<Vec<serde_json::Value>> {
    unsafe {
        let mut needed = 0;
        GetTokenInformation(
            token,
            information_class,
            std::ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut needed,
        );
        anyhow::ensure!((4..=65_536).contains(&needed), "token SID data size bound");
        let capacity = needed;
        let mut words = vec![0_usize; (needed as usize).div_ceil(size_of::<usize>())];
        anyhow::ensure!(
            GetTokenInformation(
                token,
                information_class,
                words.as_mut_ptr().cast(),
                capacity,
                &mut needed,
            ) != 0
                && (4..=capacity).contains(&needed),
            "read diagnostic token SID data: {}",
            GetLastError()
        );
        let start = words.as_ptr().cast::<u8>();
        let count = std::ptr::read_unaligned(start.cast::<u32>()) as usize;
        let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
        anyhow::ensure!(
            count <= (needed as usize).saturating_sub(offset) / size_of::<SID_AND_ATTRIBUTES>(),
            "token SID array bounds"
        );
        let entries = start.add(offset).cast::<SID_AND_ATTRIBUTES>();
        (0..count)
            .map(|index| {
                let entry = std::ptr::read_unaligned(entries.add(index));
                Ok(serde_json::json!({
                    "sid_alias": aliases.name(entry.Sid)?,
                    "attributes": entry.Attributes,
                }))
            })
            .collect()
    }
}

fn token_snapshot(token: HANDLE, aliases: &mut SidAliases) -> Result<serde_json::Value> {
    let mut user = unsafe { get_user_sid_bytes(token)? };
    Ok(serde_json::json!({
        "user_sid_alias": unsafe { aliases.name(user.as_mut_ptr().cast())? },
        "ordinary_groups": token_sid_rows(token, TokenGroups, aliases)?,
        "restricting_sids": token_sid_rows(token, TokenRestrictedSids, aliases)?,
        "integrity_rid": token_integrity_rid(token)?,
    }))
}

// Start with the original exact, protected, one-ACE fixture. Add only an
// explicit non-inheriting RX|DELETE capability ACE, then verify both ACEs.
// Neither the ordinary identity nor the capability receives DELETE_CHILD.
fn capability_object_acl(path: &Path, cap: &LocalSid) -> Result<String> {
    fixture_acl(path, READ_EXECUTE | DELETE, OutsideLabel::Inherited)?;
    unsafe {
        ensure_allow_mask_aces_with_inheritance(
            path,
            &[cap.as_ptr()],
            READ_EXECUTE | DELETE,
            /*inheritance*/ 0,
        )?;
        let mut dacl = std::ptr::null_mut();
        let mut descriptor = LocalDescriptor(std::ptr::null_mut());
        anyhow::ensure!(
            GetNamedSecurityInfoW(
                to_wide(path).as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut dacl,
                std::ptr::null_mut(),
                &mut descriptor.0,
            ) == ERROR_SUCCESS,
            "read strict object DACL"
        );
        let mut control = 0;
        let mut revision = 0;
        anyhow::ensure!(
            GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision) != 0
                && control & SE_DACL_PROTECTED != 0
                && !dacl.is_null()
                && (*dacl).AceCount == 2,
            "strict object DACL must remain protected with two ACEs"
        );
        let mut everyone = world_sid()?;
        let mut seen = [false; 2];
        for index in 0..2 {
            let mut entry = std::ptr::null_mut();
            anyhow::ensure!(
                GetAce(dacl, index, &mut entry) != 0,
                "read strict object ACE"
            );
            let ace = &*entry.cast::<ACCESS_ALLOWED_ACE>();
            anyhow::ensure!(
                ace.Header.AceType == 0
                    && ace.Header.AceFlags == 0
                    && ace.Mask == (READ_EXECUTE | DELETE),
                "strict object ACE mask or scope differs"
            );
            let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast();
            let role = if EqualSid(sid, everyone.as_mut_ptr().cast()) != 0 {
                0
            } else {
                anyhow::ensure!(
                    EqualSid(sid, cap.as_ptr()) != 0,
                    "unexpected strict object SID"
                );
                1
            };
            anyhow::ensure!(!seen[role], "duplicate strict object SID");
            seen[role] = true;
        }
        anyhow::ensure!(seen == [true; 2], "strict object SID inventory differs");
        let mut text = std::ptr::null_mut();
        let mut length = 0;
        anyhow::ensure!(
            ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor.0,
                SDDL_REVISION_1,
                DACL_SECURITY_INFORMATION,
                &mut text,
                &mut length,
            ) != 0,
            "serialize strict object DACL"
        );
        let owner = LocalDescriptor(text.cast());
        anyhow::ensure!(length > 0, "empty strict object DACL");
        let units = std::slice::from_raw_parts(owner.0.cast::<u16>(), length as usize);
        Ok(String::from_utf16(
            units.strip_suffix(&[0]).unwrap_or(units),
        )?)
    }
}

fn delete_result(succeeded: i32) -> Outcome {
    Outcome::from_result(if succeeded != 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    })
}

fn native_delete_pair(file: &Path, directory: &Path) -> [Outcome; 2] {
    // Call the real native APIs, retaining each error before the next API call.
    unsafe {
        [
            delete_result(DeleteFileW(to_wide(file).as_ptr())),
            delete_result(RemoveDirectoryW(to_wide(directory).as_ptr())),
        ]
    }
}

#[test]
fn workspace_delete_capability_controls_without_parent_delete_child() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let cap = LocalSid::from_string("S-1-5-21-101-202-303-406")?;
    let mut everyone = unsafe { world_sid()? };
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?;
    }
    let parent = fixture.path().join("strict-parent");
    std::fs::create_dir(&parent)?;
    let roles = [
        "base_control",
        "restricted_without_cap",
        "restricted_with_cap",
    ];
    let files = roles.map(|role| parent.join(format!("{role}.txt")));
    let directories = roles.map(|role| parent.join(format!("{role}-dir")));
    let mut object_sddl = Vec::new();
    for index in 0..roles.len() {
        std::fs::write(&files[index], "inside")?;
        std::fs::create_dir(&directories[index])?;
        for (kind, path) in [("file", &files[index]), ("directory", &directories[index])] {
            let dacl = if index == 2 {
                capability_object_acl(path, &cap)?
            } else {
                fixture_acl(path, READ_EXECUTE | DELETE, OutsideLabel::Inherited)?
            };
            object_sddl.push(serde_json::json!({
                "role": roles[index], "kind": kind, "dacl": dacl,
            }));
        }
    }
    // One explicit protected Everyone RX ACE: no other ordinary identity ACE,
    // no inherited ACE, and no parent DELETE_CHILD route for any test token.
    let parent_sddl = fixture_acl(&parent, READ_EXECUTE, OutsideLabel::Inherited)?;
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[cap.as_ptr()])?
    });
    let mut aliases = SidAliases(vec![
        (everyone, "everyone".to_owned()),
        (unsafe { get_user_sid_bytes(base.0)? }, "user".to_owned()),
        (unsafe { get_logon_sid_bytes(base.0)? }, "logon".to_owned()),
    ]);
    unsafe {
        let name = aliases.name(cap.as_ptr())?;
        let entry = aliases
            .0
            .iter_mut()
            .find(|(_, alias)| *alias == name)
            .ok_or_else(|| anyhow!("fixture capability alias missing"))?;
        entry.1 = "fixture_capability".to_owned();
    }
    let base_snapshot = token_snapshot(base.0, &mut aliases)?;
    let restricted_snapshot = token_snapshot(token.0, &mut aliases)?;
    let control = {
        let _impersonation = unsafe { Impersonation::enter(base.0)? };
        native_delete_pair(&files[0], &directories[0])
    };
    let (effective_snapshot, without_cap, with_cap) = {
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let mut handle = 0;
        anyhow::ensure!(
            unsafe {
                OpenThreadToken(
                    GetCurrentThread(),
                    TOKEN_QUERY,
                    /*openasself*/ 1,
                    &mut handle,
                )
            } != 0,
            "open effective impersonation token: {}",
            unsafe { GetLastError() }
        );
        let effective = OwnedToken(handle);
        let snapshot = token_snapshot(effective.0, &mut aliases)?;
        (
            snapshot,
            native_delete_pair(&files[1], &directories[1]),
            native_delete_pair(&files[2], &directories[2]),
        )
    };
    let retained_without_cap = [files[1].try_exists()?, directories[1].try_exists()?];
    let absent_with_cap = [!files[2].try_exists()?, !directories[2].try_exists()?];
    eprintln!(
        "HEPTA_DELETE_CAPABILITY_CONTROL {}",
        serde_json::json!({
            "schema": "hepta.windows-delete-capability-control.v1",
            "route": "object_delete_without_parent_delete_child",
            "execution_context": "effective_impersonated_thread_not_spawned_child",
            "sandbox_qualified": false, "production_token_modified": false,
            "parent_sddl": parent_sddl, "object_sddl": object_sddl,
            "sid_alias_scope": "this_test_only_no_raw_identity_sids",
            "base_token": base_snapshot, "restricted_token": restricted_snapshot,
            "effective_token": effective_snapshot,
            "base_control": control, "restricted_without_cap": without_cap,
            "restricted_with_cap": with_cap,
            "retained_without_cap": retained_without_cap, "absent_with_cap": absent_with_cap,
        })
    );
    assert_eq!(
        control.each_ref().map(|outcome| outcome.succeeded),
        [true; 2]
    );
    assert_eq!(
        without_cap.each_ref().map(|outcome| outcome.win32_error),
        [Some(5); 2]
    );
    assert_eq!(
        with_cap.each_ref().map(|outcome| outcome.succeeded),
        [true; 2]
    );
    assert_eq!(retained_without_cap, [true; 2]);
    assert_eq!(absent_with_cap, [true; 2]);
    assert_eq!(effective_snapshot, restricted_snapshot);
    Ok(())
}
