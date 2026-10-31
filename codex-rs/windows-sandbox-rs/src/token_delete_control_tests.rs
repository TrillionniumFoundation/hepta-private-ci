use super::*;
use crate::winutil::string_from_sid_bytes;
use std::io::Write as _;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::LookupPrivilegeNameW;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SE_PRIVILEGE_ENABLED;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TokenPrivileges;

const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;

struct SecurityDescriptor(*mut c_void);

impl Drop for SecurityDescriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

fn sid_string(sid: *mut c_void) -> Result<String> {
    anyhow::ensure!(unsafe { IsValidSid(sid) } != 0, "invalid diagnostic SID");
    let length = unsafe { GetLengthSid(sid) };
    let mut bytes = vec![0u8; length as usize];
    anyhow::ensure!(
        unsafe { CopySid(length, bytes.as_mut_ptr().cast(), sid) } != 0,
        "CopySid for diagnostic failed: {}",
        unsafe { GetLastError() }
    );
    string_from_sid_bytes(&bytes).map_err(anyhow::Error::msg)
}

#[derive(Debug, Eq, Ord, PartialEq, PartialOrd)]
struct Grant {
    sid: String,
    mask: u32,
    flags: u8,
}

// Read back the complete ordinary/capability DACL before any delete operation.
// No inherited ACE, extra trustee, or unexpected DELETE bit is accepted.
pub(super) fn verify_fixture_acl(
    path: &Path,
    expected_grants: &[(*mut c_void, u32)],
) -> Result<String> {
    let mut owner = std::ptr::null_mut();
    let mut acl = std::ptr::null_mut();
    let mut descriptor = std::ptr::null_mut();
    let code = unsafe {
        GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            std::ptr::null_mut(),
            &mut acl,
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    let descriptor = SecurityDescriptor(descriptor);
    anyhow::ensure!(code == ERROR_SUCCESS, "read control fixture ACL: {code}");
    anyhow::ensure!(
        !descriptor.0.is_null(),
        "missing fixture security descriptor"
    );
    anyhow::ensure!(!acl.is_null(), "control fixture has a NULL DACL");
    let mut control = 0;
    let mut revision = 0;
    anyhow::ensure!(
        unsafe { GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision) } != 0,
        "read fixture descriptor control: {}",
        unsafe { GetLastError() }
    );
    let mut grants = Vec::new();
    for index in 0..unsafe { (*acl).AceCount } {
        let mut ace = std::ptr::null_mut();
        anyhow::ensure!(
            unsafe { GetAce(acl, u32::from(index), &mut ace) } != 0,
            "read fixture ACE: {}",
            unsafe { GetLastError() }
        );
        let header = unsafe { &*ace.cast::<ACE_HEADER>() };
        anyhow::ensure!(
            header.AceType == ACCESS_ALLOWED_ACE_TYPE
                && usize::from(header.AceSize) >= std::mem::size_of::<ACCESS_ALLOWED_ACE>(),
            "unexpected fixture ACE type/size"
        );
        let allowed = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
        grants.push(Grant {
            sid: sid_string(std::ptr::addr_of!(allowed.SidStart).cast_mut().cast())?,
            mask: allowed.Mask,
            flags: header.AceFlags,
        });
    }
    grants.sort();
    let mut expected = expected_grants
        .iter()
        .map(|(sid, mask)| {
            Ok(Grant {
                sid: sid_string(*sid)?,
                mask: *mask,
                flags: 0,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    expected.sort();
    let owner = sid_string(owner)?;
    anyhow::ensure!(
        control & SE_DACL_PROTECTED != 0 && grants == expected,
        "fixture ACL mismatch at {}: owner={owner}, control={control:#06x}, actual={grants:?}, expected={expected:?}",
        path.display()
    );
    Ok(format!(
        "owner={owner}, control={control:#06x}, grants={grants:?}"
    ))
}

fn token_information(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<(Vec<usize>, usize)> {
    let mut needed = 0;
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
        needed >= 4,
        "token information size query failed: {}",
        unsafe { GetLastError() }
    );
    let mut buffer = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    anyhow::ensure!(
        unsafe {
            GetTokenInformation(
                token,
                class,
                buffer.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } != 0,
        "read token information failed: {}",
        unsafe { GetLastError() }
    );
    Ok((buffer, needed as usize))
}

fn privilege_name(luid: &LUID) -> Result<String> {
    let mut length = 0;
    unsafe { LookupPrivilegeNameW(std::ptr::null(), luid, std::ptr::null_mut(), &mut length) };
    anyhow::ensure!(length > 0, "privilege name size query failed");
    let mut name = vec![0u16; length as usize + 1];
    length = name.len() as u32;
    anyhow::ensure!(
        unsafe { LookupPrivilegeNameW(std::ptr::null(), luid, name.as_mut_ptr(), &mut length) }
            != 0,
        "read privilege name failed: {}",
        unsafe { GetLastError() }
    );
    Ok(String::from_utf16(&name[..length as usize])?)
}

#[derive(Debug)]
struct TokenSnapshot {
    user: String,
    user_attributes: u32,
    groups: Vec<(String, u32)>,
    privileges: Vec<(String, u32)>,
    restricting_sid_count: u32,
}

fn token_snapshot(token: HANDLE) -> Result<TokenSnapshot> {
    let (user_buffer, length) = token_information(token, TokenUser)?;
    anyhow::ensure!(
        length >= std::mem::size_of::<TOKEN_USER>(),
        "invalid TokenUser buffer"
    );
    let token_user = unsafe { std::ptr::read_unaligned(user_buffer.as_ptr().cast::<TOKEN_USER>()) };
    let user = sid_string(token_user.User.Sid)?;
    let user_attributes = token_user.User.Attributes;
    let (restricted, _) = token_information(token, TokenRestrictedSids)?;
    let restricting_sid_count =
        unsafe { std::ptr::read_unaligned(restricted.as_ptr().cast::<u32>()) };
    let (groups_buffer, length) = token_information(token, TokenGroups)?;
    let count = unsafe { std::ptr::read_unaligned(groups_buffer.as_ptr().cast::<u32>()) } as usize;
    let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    anyhow::ensure!(
        length >= offset && count <= (length - offset) / std::mem::size_of::<SID_AND_ATTRIBUTES>(),
        "invalid TokenGroups buffer"
    );
    let entries = unsafe {
        std::slice::from_raw_parts(
            groups_buffer
                .as_ptr()
                .cast::<u8>()
                .add(offset)
                .cast::<SID_AND_ATTRIBUTES>(),
            count,
        )
    };
    let mut groups = entries
        .iter()
        .map(|entry| Ok((sid_string(entry.Sid)?, entry.Attributes)))
        .collect::<Result<Vec<_>>>()?;
    groups.sort();
    let (privileges_buffer, length) = token_information(token, TokenPrivileges)?;
    let count =
        unsafe { std::ptr::read_unaligned(privileges_buffer.as_ptr().cast::<u32>()) } as usize;
    let offset = std::mem::offset_of!(TOKEN_PRIVILEGES, Privileges);
    anyhow::ensure!(
        length >= offset && count <= (length - offset) / std::mem::size_of::<LUID_AND_ATTRIBUTES>(),
        "invalid TokenPrivileges buffer"
    );
    let entries = unsafe {
        std::slice::from_raw_parts(
            privileges_buffer
                .as_ptr()
                .cast::<u8>()
                .add(offset)
                .cast::<LUID_AND_ATTRIBUTES>(),
            count,
        )
    };
    let mut privileges = entries
        .iter()
        .map(|entry| Ok((privilege_name(&entry.Luid)?, entry.Attributes)))
        .collect::<Result<Vec<_>>>()?;
    privileges.sort();
    Ok(TokenSnapshot {
        user,
        user_attributes,
        groups,
        privileges,
        restricting_sid_count,
    })
}

pub(super) fn observe_reference_deletions(
    base: HANDLE,
    subject: HANDLE,
    outside: &Path,
    mode: TokenMode,
    authority: DeleteAuthority,
    acls: &[(PathBuf, String)],
) -> Result<(NativeResult<()>, NativeResult<()>)> {
    let mut reference = 0;
    let created = unsafe {
        CreateRestrictedToken(
            base,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            /*disablesidcount*/ 0,
            std::ptr::null(),
            /*deleteprivilegecount*/ 0,
            std::ptr::null(),
            /*restrictedsidcount*/ 0,
            std::ptr::null(),
            &mut reference,
        )
    };
    anyhow::ensure!(
        created != 0,
        "create ordinary reference token: {}",
        unsafe { GetLastError() }
    );
    let reference = OwnedToken(reference);
    unsafe { enable_single_privilege(reference.0, "SeChangeNotifyPrivilege")? };
    let host_before = token_snapshot(base)?;
    let subject_state = token_snapshot(subject)?;
    let reference_state = token_snapshot(reference.0)?;
    anyhow::ensure!(
        reference_state.restricting_sid_count == 0
            && reference_state.user == host_before.user
            && reference_state.user == subject_state.user
            && reference_state.user_attributes == subject_state.user_attributes
            && reference_state.groups == subject_state.groups
            && reference_state.privileges == subject_state.privileges
            && reference_state.privileges.iter().all(|(name, attributes)| {
                attributes & SE_PRIVILEGE_ENABLED == 0 || name == "SeChangeNotifyPrivilege"
            }),
        "reference does not isolate the ordinary access check: reference={reference_state:?}, subject={subject_state:?}"
    );
    let raw_host = (
        observe(std::fs::remove_file(outside.join("host-delete.txt"))),
        observe(std::fs::remove_dir(outside.join("host-delete-dir"))),
    );
    let ordinary = {
        let _impersonation = unsafe { Impersonation::enter(reference.0)? };
        (
            observe(std::fs::remove_file(outside.join("reference-delete.txt"))),
            observe(std::fs::remove_dir(outside.join("reference-delete-dir"))),
        )
    };
    let host_after = token_snapshot(base)?;
    writeln!(
        std::io::stderr().lock(),
        "native DELETE controls {mode:?}/{authority:?}: raw_host={raw_host:?}, ordinary={ordinary:?}, host_before={host_before:?}, host_after={host_after:?}, reference={reference_state:?}, subject={subject_state:?}, fixture_acls={acls:?}"
    )?;
    Ok(ordinary)
}
