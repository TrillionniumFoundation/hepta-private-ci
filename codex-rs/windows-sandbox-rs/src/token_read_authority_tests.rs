//! Prepared, owned-fixture experiment. No production token factory is replaced.

#[path = "token_access_request_tests.rs"]
mod access_requests;

use super::*;
use anyhow::Context;
use std::path::Path;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Cryptography::BCRYPT_USE_SYSTEM_PREFERRED_RNG;
use windows_sys::Win32::Security::Cryptography::BCryptGenRandom;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_PRIVILEGE_ENABLED;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_APPEND_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_EA;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;
use windows_sys::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;
use windows_sys::Win32::System::SystemServices::ACCESS_DENIED_ACE_TYPE;
use windows_sys::Win32::System::SystemServices::SE_GROUP_ENABLED;
use windows_sys::Win32::System::SystemServices::SE_GROUP_USE_FOR_DENY_ONLY;

const READ_MASK: u32 = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE;
const MUTATION_MASK: u32 = FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_WRITE_ATTRIBUTES
    | DELETE
    | FILE_DELETE_CHILD
    | WRITE_DAC
    | WRITE_OWNER;

struct ReadAuthority {
    sid: LocalSid,
    text: String,
}

impl ReadAuthority {
    fn issue_for_fixture() -> Result<Self> {
        let mut words = [0_u32; 4];
        // SAFETY: the system RNG writes exactly the live array's byte length.
        let status = unsafe {
            BCryptGenRandom(
                std::ptr::null_mut(),
                words.as_mut_ptr().cast(),
                std::mem::size_of_val(&words) as u32,
                BCRYPT_USE_SYSTEM_PREFERRED_RNG,
            )
        };
        anyhow::ensure!(status >= 0, "FULL_SETUP rng status={status}");
        let [a, b, c, d] = words;
        let text = format!("S-1-5-21-{a}-{b}-{c}-{d}");
        let sid = LocalSid::from_string(&text).map_err(|_| anyhow!("FULL_SETUP read_role_sid"))?;
        Ok(Self { sid, text })
    }
}

struct Descriptor(*mut c_void);

impl Drop for Descriptor {
    fn drop(&mut self) {
        // SAFETY: every instance owns one allocation returned by a security API.
        unsafe { LocalFree(self.0 as HLOCAL) };
    }
}

fn set_fixture_dacl(path: &Path, sddl: &str) -> Result<()> {
    let mut descriptor = std::ptr::null_mut();
    // SAFETY: the terminated descriptor text and output pointer remain live.
    let ok = unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            to_wide(sddl).as_ptr(),
            SDDL_REVISION_1,
            &mut descriptor,
            std::ptr::null_mut(),
        )
    };
    anyhow::ensure!(ok != 0, "FULL_SETUP descriptor os={}", unsafe {
        GetLastError()
    });
    let owner = Descriptor(descriptor);
    let mut acl = std::ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    // SAFETY: this descriptor owns the extracted ACL until the setter copies it.
    let ok = unsafe { GetSecurityDescriptorDacl(owner.0, &mut present, &mut acl, &mut defaulted) };
    anyhow::ensure!(ok != 0 && present != 0 && !acl.is_null(), "FULL_SETUP dacl");
    // SAFETY: only this test's freshly created, owned paths are modified.
    let status = unsafe {
        SetNamedSecurityInfoW(
            to_wide(path).as_mut_ptr(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            acl,
            std::ptr::null_mut(),
        )
    };
    anyhow::ensure!(status == ERROR_SUCCESS, "FULL_SETUP set_dacl os={status}");
    Ok(())
}

fn token_information(token: HANDLE, class: i32, minimum: usize) -> Result<Vec<usize>> {
    let mut needed = 0;
    // SAFETY: the first call obtains size; the token is owned by the caller.
    unsafe {
        GetTokenInformation(
            token,
            class,
            std::ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut needed,
        )
    };
    anyhow::ensure!(
        (minimum..=65536).contains(&(needed as usize)),
        "FULL_SETUP token_size"
    );
    let mut words = vec![0_usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    let capacity = needed;
    // SAFETY: usize storage is aligned and holds at least capacity bytes.
    let ok = unsafe {
        GetTokenInformation(
            token,
            class,
            words.as_mut_ptr().cast(),
            capacity,
            &mut needed,
        )
    };
    anyhow::ensure!(
        ok != 0 && needed <= capacity && needed as usize >= minimum,
        "FULL_SETUP token_query class={class} os={}",
        unsafe { GetLastError() }
    );
    Ok(words)
}

fn audit_acl(
    case: u8,
    object: usize,
    acl: *mut ACL,
    known: &[*mut c_void],
) -> Result<Vec<(u8, u8, u8, u32)>> {
    anyhow::ensure!(!acl.is_null(), "FULL_SETUP missing_acl");
    // SAFETY: callers retain the successful Windows query's owning allocation.
    let count = unsafe { (*acl).AceCount };
    anyhow::ensure!((1..=32).contains(&count), "FULL_SETUP ace_count");
    let mut entries = Vec::new();
    for index in 0..count {
        let mut pointer = std::ptr::null_mut();
        // SAFETY: the index is within the live ACL's reported ACE count.
        anyhow::ensure!(
            unsafe { GetAce(acl, u32::from(index), &mut pointer) } != 0,
            "FULL_SETUP get_ace"
        );
        // SAFETY: GetAce returned a live ACE; allowed and denied share this layout.
        let header = unsafe { &*pointer.cast::<ACE_HEADER>() };
        anyhow::ensure!(
            usize::from(header.AceSize) >= std::mem::size_of::<ACCESS_ALLOWED_ACE>()
                && matches!(
                    u32::from(header.AceType),
                    ACCESS_ALLOWED_ACE_TYPE | ACCESS_DENIED_ACE_TYPE
                ),
            "FULL_SETUP ace_type"
        );
        let ace = unsafe { &*pointer.cast::<ACCESS_ALLOWED_ACE>() };
        let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast();
        anyhow::ensure!(unsafe { IsValidSid(sid) } != 0, "FULL_SETUP ace_sid");
        let role = known
            .iter()
            .position(|known| unsafe { EqualSid(sid, *known) } != 0)
            .context("FULL_SETUP unknown_acl_role")? as u8;
        println!(
            "FULL_DACL case={case} object={object} ace={index} role={role} type={} flags={} mask={}",
            header.AceType, header.AceFlags, ace.Mask
        );
        entries.push((role, header.AceType, header.AceFlags, ace.Mask));
    }
    Ok(entries)
}

fn full_token(
    case: u8,
    base: HANDLE,
    read: &ReadAuthority,
    writes: &[&LocalSid; 2],
) -> Result<OwnedToken> {
    let expected = [read.sid.as_ptr(), writes[0].as_ptr(), writes[1].as_ptr()];
    for (index, sid) in expected.iter().enumerate() {
        anyhow::ensure!(
            expected[..index]
                .iter()
                .all(|other| unsafe { EqualSid(*sid, *other) } == 0),
            "FULL_SETUP duplicate_role"
        );
    }
    let entries = expected.map(|sid| SID_AND_ATTRIBUTES {
        Sid: sid,
        Attributes: 0,
    });
    let mut handle = 0;
    // SAFETY: the owned base token and all restricting SIDs remain live. This
    // private constructor intentionally omits write-only restriction.
    let ok = unsafe {
        CreateRestrictedToken(
            base,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            /*disablesidcount*/ 0,
            std::ptr::null(),
            /*deleteprivilegecount*/ 0,
            std::ptr::null(),
            entries.len() as u32,
            entries.as_ptr(),
            &mut handle,
        )
    };
    anyhow::ensure!(ok != 0, "FULL_SETUP create_token os={}", unsafe {
        GetLastError()
    });
    let token = OwnedToken(handle);
    let mut logon = unsafe { get_logon_sid_bytes(base)? };
    let mut everyone = unsafe { world_sid()? };
    let default_roles = [
        logon.as_mut_ptr().cast(),
        everyone.as_mut_ptr().cast(),
        writes[0].as_ptr(),
        writes[1].as_ptr(),
    ];
    // SAFETY: the owned new token and all SIDs remain live. ReadAuthority is
    // deliberately absent from the helper's GENERIC_ALL grants.
    unsafe {
        set_default_dacl(token.0, &default_roles)?;
        enable_single_privilege(token.0, "SeChangeNotifyPrivilege")?;
    }
    let buffer = token_information(
        token.0,
        TokenRestrictedSids,
        std::mem::offset_of!(TOKEN_GROUPS, Groups),
    )?;
    let start = buffer.as_ptr().cast::<u8>();
    let count = unsafe { std::ptr::read(start.cast::<u32>()) } as usize;
    let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    anyhow::ensure!(
        count == expected.len()
            && offset + count * std::mem::size_of::<SID_AND_ATTRIBUTES>()
                <= std::mem::size_of_val(buffer.as_slice()),
        "FULL_SETUP restricting_count"
    );
    // SAFETY: the bounded, aligned TOKEN_GROUPS array lives inside buffer.
    let restricted = unsafe {
        std::slice::from_raw_parts(start.add(offset).cast::<SID_AND_ATTRIBUTES>(), count)
    };
    let mut roles = Vec::new();
    for entry in restricted {
        anyhow::ensure!(
            unsafe { IsValidSid(entry.Sid) } != 0,
            "FULL_SETUP restricting_sid"
        );
        let role = expected
            .iter()
            .position(|sid| unsafe { EqualSid(*sid, entry.Sid) } != 0)
            .context("FULL_SETUP unexpected_restricting_role")?;
        println!(
            "FULL_RESTRICT case={case} role={role} attributes={}",
            entry.Attributes
        );
        // Check documented effective properties, not a guessed exact bit value.
        anyhow::ensure!(
            entry.Attributes & SE_GROUP_ENABLED as u32 != 0
                && entry.Attributes & SE_GROUP_USE_FOR_DENY_ONLY as u32 == 0,
            "FULL_SETUP restricting_attributes"
        );
        roles.push(role);
    }
    roles.sort_unstable();
    anyhow::ensure!(roles == [0, 1, 2], "FULL_SETUP restricting_set");
    let base_user = unsafe { get_user_sid_bytes(base)? };
    let actual_user = unsafe { get_user_sid_bytes(token.0)? };
    anyhow::ensure!(base_user == actual_user, "FULL_SETUP user_changed");
    anyhow::ensure!(
        unsafe { EqualSid(read.sid.as_ptr(), base_user.as_ptr().cast_mut().cast()) } == 0,
        "FULL_SETUP read_role_is_user"
    );
    let privilege_buffer = token_information(
        token.0,
        TokenPrivileges,
        std::mem::offset_of!(TOKEN_PRIVILEGES, Privileges),
    )?;
    let start = privilege_buffer.as_ptr().cast::<u8>();
    let count = unsafe { std::ptr::read(start.cast::<u32>()) } as usize;
    let offset = std::mem::offset_of!(TOKEN_PRIVILEGES, Privileges);
    anyhow::ensure!(
        count <= 128
            && offset + count * std::mem::size_of::<LUID_AND_ATTRIBUTES>()
                <= std::mem::size_of_val(privilege_buffer.as_slice()),
        "FULL_SETUP privilege_count"
    );
    let privileges = unsafe {
        std::slice::from_raw_parts(start.add(offset).cast::<LUID_AND_ATTRIBUTES>(), count)
    };
    let mut notify = LUID {
        LowPart: 0,
        HighPart: 0,
    };
    anyhow::ensure!(
        unsafe {
            LookupPrivilegeValueW(
                std::ptr::null(),
                to_wide("SeChangeNotifyPrivilege").as_ptr(),
                &mut notify,
            )
        } != 0,
        "FULL_SETUP privilege_name"
    );
    let enabled: Vec<_> = privileges
        .iter()
        .filter(|p| p.Attributes & SE_PRIVILEGE_ENABLED != 0)
        .collect();
    anyhow::ensure!(
        enabled.len() == 1
            && enabled[0].Luid.LowPart == notify.LowPart
            && enabled[0].Luid.HighPart == notify.HighPart,
        "FULL_SETUP enabled_privileges"
    );
    let dacl_buffer = token_information(
        token.0,
        TokenDefaultDacl,
        std::mem::size_of::<TokenDefaultDaclInfo>(),
    )?;
    let info = unsafe { &*dacl_buffer.as_ptr().cast::<TokenDefaultDaclInfo>() };
    let known = [
        everyone.as_mut_ptr().cast(),
        read.sid.as_ptr(),
        writes[0].as_ptr(),
        writes[1].as_ptr(),
        logon.as_mut_ptr().cast(),
    ];
    let rows = audit_acl(case, /*object*/ 11, info.default_dacl, &known)?;
    anyhow::ensure!(
        rows.iter().all(|row| row.0 != 1),
        "FULL_SETUP read_role_in_default_dacl"
    );
    println!(
        "FULL_TOKEN case={case} user_same=true restricting_count=3 notify_only=true read_default_grant=false"
    );
    Ok(token)
}

#[derive(Clone, Copy, Debug)]
struct Operation {
    success: bool,
    denied: bool,
    os: Option<i32>,
}

fn operation(result: std::io::Result<()>) -> Operation {
    match result {
        Ok(()) => Operation {
            success: true,
            denied: false,
            os: None,
        },
        Err(error) => Operation {
            success: false,
            denied: error.kind() == std::io::ErrorKind::PermissionDenied,
            os: error.raw_os_error(),
        },
    }
}

fn permission_open(path: &Path, access: u32) -> Operation {
    // SAFETY: this opens only an owned fixture file, never modifies it, and
    // closes every successful handle before returning the access observation.
    let handle = unsafe {
        CreateFileW(
            to_wide(path).as_ptr(),
            access,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            /*htemplatefile*/ 0,
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        operation(Err(std::io::Error::from_raw_os_error(
            unsafe { GetLastError() } as i32,
        )))
    } else {
        unsafe { CloseHandle(handle) };
        operation(Ok(()))
    }
}

#[derive(Debug)]
struct Observation {
    read: Operation,
    contents_match: bool,
    outside: [Operation; 4],
    inside: [[Operation; 3]; 2],
    permissions: [Operation; 2],
    protected_git: Operation,
    outside_postconditions: bool,
    inside_postconditions: bool,
    protected_git_retained: bool,
}

impl Observation {
    fn original_oracle(&self) -> bool {
        self.read.success
            && self.contents_match
            && self.outside.iter().all(|op| op.denied)
            && self.inside.iter().flatten().all(|op| op.success)
            && self.protected_git.denied
            && self.outside_postconditions
            && self.inside_postconditions
            && self.protected_git_retained
    }
}

fn add_parent_delete_child(parent: &Path, child: &Path, known: &[*mut c_void; 5]) -> Result<()> {
    let writable = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE;
    let snapshot = |path: &Path, object| -> Result<Vec<(u8, u8, u8, u32)>> {
        // SAFETY: both paths and all role pointers belong to the owned fixture.
        let (acl, descriptor) = unsafe { fetch_dacl_handle(path) }
            .map_err(|_| anyhow!("FULL_SETUP parent_addition_query"))?;
        let _owner = Descriptor(descriptor);
        audit_acl(/*case*/ 3, object, acl, known)
    };
    let expected = |rows: &[(u8, u8, u8, u32)], flags| -> Result<Vec<(u8, u8, u8, u32)>> {
        let mut result = rows.to_vec();
        let mut active_allows = 0;
        for row in &mut result {
            if row.0 == 2 && row.1 == 0 {
                anyhow::ensure!(
                    row.2 == flags && row.3 == writable,
                    "FULL_SETUP parent_addition_baseline"
                );
                row.3 |= FILE_DELETE_CHILD;
                active_allows += 1;
            }
        }
        anyhow::ensure!(
            active_allows == 1,
            "FULL_SETUP parent_addition_active_allow"
        );
        Ok(result)
    };
    let before_parent = snapshot(parent, /*object*/ 12)?;
    let before_child = snapshot(child, /*object*/ 13)?;
    let expected_parent = expected(&before_parent, /*flags*/ 3)?;
    let expected_child = expected(&before_child, /*flags*/ 19)?;
    // SET_ACCESS replaces the active allow entry. Preserve every baseline bit
    // and add only FILE_DELETE_CHILD; the fresh complete ACLs must prove it.
    unsafe { ensure_allow_mask_aces(parent, &[known[2]], writable | FILE_DELETE_CHILD)? };
    let after_parent = snapshot(parent, /*object*/ 14)?;
    let after_child = snapshot(child, /*object*/ 15)?;
    anyhow::ensure!(
        after_parent == expected_parent,
        "FULL_SETUP parent_addition_parent_rows"
    );
    anyhow::ensure!(
        after_child == expected_child,
        "FULL_SETUP parent_addition_child_rows"
    );
    Ok(())
}

fn observe(case: u8, root: &Path) -> Result<Observation> {
    let read = ReadAuthority::issue_for_fixture()?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let cap_a = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let stale = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    anyhow::ensure!(
        [&everyone, &cap_a, &cap_b, &stale]
            .iter()
            .all(|role| unsafe { EqualSid(read.sid.as_ptr(), role.as_ptr()) } == 0),
        "FULL_SETUP read_role_collision"
    );
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let mut user = unsafe { get_user_sid_bytes(base.0)? };
    let read_sid = &read.text;
    set_fixture_dacl(
        root,
        &format!("D:P(A;OICI;FA;;;WD)(A;OICI;0x{READ_MASK:x};;;{read_sid})"),
    )?;
    let allowed = [root.join("workspace"), root.join("temp")];
    let outside = root.join("outside");
    for (path, cap) in allowed
        .iter()
        .zip([&cap_a, &cap_b])
        .chain(std::iter::once((&outside, &stale)))
    {
        std::fs::create_dir(path)?;
        if case == 1 && path == &outside {
            set_fixture_dacl(path, "D:P(A;OICI;FA;;;WD)")?;
        }
        // SAFETY: every target and role belongs to this fresh owned fixture.
        unsafe { ensure_allow_write_aces(path, &[cap.as_ptr()])? };
    }
    let git = allowed[0].join(".git");
    std::fs::create_dir(&git)?;
    unsafe { add_deny_write_ace(&git, cap_a.as_ptr())? };
    for path in &allowed {
        std::fs::write(path.join("delete.txt"), "inside")?;
        std::fs::create_dir(path.join("delete-dir"))?;
    }
    let outside_file = outside.join("keep.txt");
    std::fs::write(&outside_file, "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    // SAFETY: the fixture already grants the base token WRITE_OWNER. Assigning
    // its own user makes this control independent of default owner selection.
    let status = unsafe {
        SetNamedSecurityInfoW(
            to_wide(&outside_file).as_mut_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION,
            user.as_mut_ptr().cast(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    anyhow::ensure!(status == ERROR_SUCCESS, "FULL_SETUP owner os={status}");
    let known = [
        everyone.as_ptr(),
        read.sid.as_ptr(),
        cap_a.as_ptr(),
        cap_b.as_ptr(),
        stale.as_ptr(),
    ];
    match case {
        0 | 1 => {}
        2 => {
            unsafe { ensure_allow_mask_aces(&outside_file, &[read.sid.as_ptr()], DELETE)? };
        }
        3 => {
            add_parent_delete_child(&allowed[0], &git, &known)?;
        }
        4 => {
            // SAFETY: only this owned file receives the deliberately null DACL.
            let status = unsafe {
                SetNamedSecurityInfoW(
                    to_wide(&outside_file).as_mut_ptr(),
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                )
            };
            anyhow::ensure!(status == ERROR_SUCCESS, "FULL_SETUP null_dacl os={status}");
        }
        _ => anyhow::bail!("FULL_SETUP unknown_case"),
    }
    let mut objects = vec![root.to_owned(), git.clone()];
    for path in &allowed {
        objects.extend([
            path.clone(),
            path.join("delete.txt"),
            path.join("delete-dir"),
        ]);
    }
    objects.extend([
        outside.clone(),
        outside_file.clone(),
        outside.join("keep-dir"),
    ]);
    for (object, path) in objects.iter().enumerate() {
        let mut descriptor = std::ptr::null_mut();
        let mut owner = std::ptr::null_mut();
        let mut acl = std::ptr::null_mut();
        // SAFETY: the returned descriptor owns the ACL and owner SID until all
        // readback checks have completed. No external path is inspected.
        let status = unsafe {
            GetNamedSecurityInfoW(
                to_wide(path).as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | OWNER_SECURITY_INFORMATION,
                &mut owner,
                std::ptr::null_mut(),
                &mut acl,
                std::ptr::null_mut(),
                &mut descriptor,
            )
        };
        anyhow::ensure!(
            status == ERROR_SUCCESS,
            "FULL_SETUP read_security os={status}"
        );
        let descriptor = Descriptor(descriptor);
        let mut present = 0;
        let mut defaulted = 0;
        anyhow::ensure!(
            unsafe {
                GetSecurityDescriptorDacl(descriptor.0, &mut present, &mut acl, &mut defaulted)
            } != 0
                && present != 0,
            "FULL_SETUP dacl_present"
        );
        anyhow::ensure!(
            !owner.is_null() && unsafe { IsValidSid(owner) } != 0,
            "FULL_SETUP owner_sid"
        );
        let owned_by_user = unsafe { EqualSid(owner, user.as_mut_ptr().cast()) } != 0;
        println!(
            "FULL_OBJECT case={case} object={object} owner_is_user={owned_by_user} null_dacl={}",
            acl.is_null()
        );
        if path == &outside_file {
            anyhow::ensure!(owned_by_user, "FULL_SETUP owner_readback");
        }
        if case == 4 && path == &outside_file {
            anyhow::ensure!(acl.is_null(), "FULL_SETUP null_dacl_readback");
            continue;
        }
        let rows = audit_acl(case, object, acl, &known)?;
        let read_mutation = rows
            .iter()
            .filter(|row| row.0 == 1 && row.1 == 0 && row.2 & 0x08 == 0)
            .fold(0, |mask, row| mask | (row.3 & MUTATION_MASK));
        anyhow::ensure!(
            read_mutation
                == if case == 2 && path == &outside_file {
                    DELETE
                } else {
                    0
                },
            "FULL_SETUP read_role_mutation"
        );
        if path == &allowed[0] {
            let active_child = rows.iter().any(|row| {
                row.0 == 2 && row.1 == 0 && row.2 & 0x08 == 0 && row.3 & FILE_DELETE_CHILD != 0
            });
            anyhow::ensure!(
                active_child == (case == 3),
                "FULL_SETUP active_parent_readback"
            );
        }
        if path == &git {
            anyhow::ensure!(
                rows.iter().any(|row| row.0 == 2
                    && row.1 == 1
                    && row.2 & 0x08 == 0
                    && row.3 & DELETE != 0),
                "FULL_SETUP protected_delete_deny"
            );
        }
    }
    let token = full_token(case, base.0, &read, &[&cap_a, &cap_b])?;
    let (inside, outside_read, contents_match, refused, permissions, protected_git) = {
        // SAFETY: the token stays owned until after this guard reverts the thread.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        access_requests::observe(case, &allowed[0], &git)?;
        let inside = allowed.each_ref().map(|path| {
            [
                operation(std::fs::write(path.join("created.txt"), "allowed")),
                operation(std::fs::remove_file(path.join("delete.txt"))),
                operation(std::fs::remove_dir(path.join("delete-dir"))),
            ]
        });
        let raw_read = std::fs::read_to_string(&outside_file);
        let contents_match = raw_read.as_ref().is_ok_and(|text| text == "outside");
        let outside_read = operation(raw_read.map(|_| ()));
        let permissions = [
            permission_open(&outside_file, WRITE_DAC),
            permission_open(&outside_file, WRITE_OWNER),
        ];
        let refused = [
            operation(std::fs::write(&outside_file, "overwritten")),
            operation(std::fs::write(outside.join("created.txt"), "outside")),
            operation(std::fs::remove_file(&outside_file)),
            operation(std::fs::remove_dir(outside.join("keep-dir"))),
        ];
        let protected_git = operation(std::fs::remove_dir(&git));
        (
            inside,
            outside_read,
            contents_match,
            refused,
            permissions,
            protected_git,
        )
    };
    let result = Observation {
        read: outside_read,
        contents_match,
        outside: refused,
        inside,
        permissions,
        protected_git,
        outside_postconditions: std::fs::read_to_string(&outside_file)
            .is_ok_and(|text| text == "outside")
            && !outside.join("created.txt").exists()
            && outside.join("keep-dir").is_dir(),
        inside_postconditions: allowed.iter().all(|path| {
            std::fs::read_to_string(path.join("created.txt")).is_ok_and(|text| text == "allowed")
                && !path.join("delete.txt").exists()
                && !path.join("delete-dir").exists()
        }),
        protected_git_retained: git.is_dir(),
    };
    println!(
        "FULL_RESULT case={case} read={:?} contents_match={} outside={:?} inside={:?} permissions={:?} git={:?} outside_post={} inside_post={} git_retained={} original_oracle={}",
        (result.read.success, result.read.denied, result.read.os),
        result.contents_match,
        result.outside.map(|op| (op.success, op.denied, op.os)),
        result
            .inside
            .map(|row| row.map(|op| (op.success, op.denied, op.os))),
        result.permissions.map(|op| (op.success, op.denied, op.os)),
        (
            result.protected_git.success,
            result.protected_git.denied,
            result.protected_git.os
        ),
        result.outside_postconditions,
        result.inside_postconditions,
        result.protected_git_retained,
        result.original_oracle()
    );
    Ok(result)
}

#[test]
fn full_restriction_preserves_prepared_read_and_mutation_boundaries() -> Result<()> {
    let mut observations = Vec::new();
    for case in 0..=4 {
        let fixture = tempfile::tempdir()?;
        let result = observe(case, fixture.path());
        println!("FULL_SETUP_RESULT case={case} success={}", result.is_ok());
        // Every ordinary Result path exits impersonation and drops token handles
        // before explicit cleanup. Panic/abort/hard termination are not promised.
        let cleanup = fixture.close();
        println!(
            "FULL_CLEANUP case={case} success={} os={:?}",
            cleanup.is_ok(),
            cleanup
                .as_ref()
                .err()
                .and_then(std::io::Error::raw_os_error)
        );
        cleanup?;
        observations.push(result);
    }
    // First finish all ordinary scenarios. Setup errors remain errors, distinct
    // from observed permission denials; none is a successful operation control.
    let observations: Vec<_> = observations.into_iter().collect::<Result<_>>()?;
    anyhow::ensure!(
        observations[0].original_oracle() && observations[0].permissions.iter().all(|op| op.denied),
        "FULL_HYPOTHESIS prepared_authority_failed"
    );
    anyhow::ensure!(
        observations[1].read.denied && !observations[1].original_oracle(),
        "FULL_CONTROL missing_read_grant"
    );
    anyhow::ensure!(
        observations[2].read.success && observations[2].outside[2].success,
        "FULL_CONTROL contaminated_read_delete"
    );
    anyhow::ensure!(
        observations[3].protected_git.success && !observations[3].protected_git_retained,
        "FULL_CONTROL active_parent_delete_child"
    );
    anyhow::ensure!(
        observations[4].outside[2].success,
        "FULL_CONTROL null_dacl_boundary"
    );
    Ok(())
}
