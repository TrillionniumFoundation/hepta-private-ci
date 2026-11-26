//! Bounded primary-token facts. Raw SIDs stay in memory and are never serialized.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::ffi::c_void;
use std::mem::offset_of;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::IsWellKnownSid;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
use windows_sys::Win32::Security::TOKEN_MANDATORY_POLICY;
use windows_sys::Win32::Security::TOKEN_OWNER;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_TYPE;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Security::TokenMandatoryPolicy;
use windows_sys::Win32::Security::TokenOwner;
use windows_sys::Win32::Security::TokenPrimary;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenType;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Security::WinAuthenticatedUserSid;
use windows_sys::Win32::Security::WinBuiltinAdministratorsSid;
use windows_sys::Win32::Security::WinBuiltinUsersSid;
use windows_sys::Win32::Security::WinLocalSystemSid;
use windows_sys::Win32::Security::WinWorldSid;

const MAX_BYTES: usize = 64 * 1024;
const MAX_ENTRIES: usize = 64;

struct Buffer {
    words: Vec<usize>,
    length: usize,
}

impl Buffer {
    fn query(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Self> {
        let mut length = 0;
        let success = unsafe {
            GetTokenInformation(
                token,
                class,
                std::ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut length,
            )
        };
        let error = unsafe { GetLastError() };
        ensure!(
            success == 0 && error == ERROR_INSUFFICIENT_BUFFER,
            "token size query class {class}: result {success}, error {error}"
        );
        ensure!(
            length > 0 && length as usize <= MAX_BYTES,
            "token class {class} size outside bound"
        );
        let capacity = length;
        let mut words = vec![0usize; (capacity as usize).div_ceil(size_of::<usize>())];
        ensure!(
            unsafe {
                GetTokenInformation(
                    token,
                    class,
                    words.as_mut_ptr().cast(),
                    capacity,
                    &mut length,
                )
            } != 0,
            "token query class {class}: {}",
            std::io::Error::last_os_error()
        );
        ensure!(
            length <= capacity,
            "token class {class} exceeded allocation"
        );
        Ok(Self {
            words,
            length: length as usize,
        })
    }

    fn bytes(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.words.as_ptr().cast(), self.length) }
    }

    fn header<T: Copy>(&self) -> Result<T> {
        ensure!(
            size_of::<T>() <= self.length && align_of::<T>() <= align_of::<usize>(),
            "token header outside allocation"
        );
        Ok(unsafe { self.words.as_ptr().cast::<T>().read() })
    }

    fn sid(&self, pointer: *mut c_void) -> Result<Vec<u8>> {
        let offset = (pointer as usize)
            .checked_sub(self.bytes().as_ptr() as usize)
            .context("SID before allocation")?;
        let end = offset.checked_add(8).context("SID header overflow")?;
        let header = self
            .bytes()
            .get(offset..end)
            .context("SID header outside allocation")?;
        let end = end
            .checked_add(usize::from(header[1]) * 4)
            .context("SID body overflow")?;
        let sid = self
            .bytes()
            .get(offset..end)
            .context("SID body outside allocation")?;
        ensure!(unsafe { IsValidSid(pointer) } != 0, "invalid returned SID");
        Ok(sid.to_vec())
    }

    fn entries<T: Copy>(&self, offset: usize) -> Result<Vec<T>> {
        let count = self.header::<u32>()? as usize;
        ensure!(count <= MAX_ENTRIES, "token entry count exceeds bound");
        if count == 0 {
            return Ok(Vec::new());
        }
        let extent = count
            .checked_mul(size_of::<T>())
            .and_then(|size| offset.checked_add(size))
            .context("token array extent overflow")?;
        ensure!(extent <= self.length, "token entries outside allocation");
        Ok((0..count)
            .map(|index| unsafe {
                self.bytes()
                    .as_ptr()
                    .add(offset + index * size_of::<T>())
                    .cast::<T>()
                    .read_unaligned()
            })
            .collect())
    }

    fn groups(&self) -> Result<Vec<(Vec<u8>, u32)>> {
        let mut entries = self
            .entries::<SID_AND_ATTRIBUTES>(offset_of!(TOKEN_GROUPS, Groups))?
            .into_iter()
            .map(|entry| Ok((self.sid(entry.Sid)?, entry.Attributes)))
            .collect::<Result<Vec<_>>>()?;
        entries.sort();
        Ok(entries)
    }
}

#[derive(PartialEq, Eq)]
pub(super) struct Facts {
    user: (Vec<u8>, u32),
    owner: Vec<u8>,
    groups: Vec<(Vec<u8>, u32)>,
    restricting: Vec<(Vec<u8>, u32)>,
    privileges: Vec<(i32, u32, u32)>,
    integrity: (u32, u32),
    mandatory_policy: u32,
    token_type: TOKEN_TYPE,
}

impl Facts {
    pub(super) fn capture(token: HANDLE) -> Result<Self> {
        let token_type = Buffer::query(token, TokenType)?.header::<TOKEN_TYPE>()?;
        ensure!(token_type == TokenPrimary, "observed token is not primary");
        let user = Buffer::query(token, TokenUser)?;
        let user_header = user.header::<TOKEN_USER>()?;
        let owner = Buffer::query(token, TokenOwner)?;
        let owner_header = owner.header::<TOKEN_OWNER>()?;
        let groups = Buffer::query(token, TokenGroups)?.groups()?;
        let restricting = Buffer::query(token, TokenRestrictedSids)?.groups()?;
        let mut privileges = Buffer::query(token, TokenPrivileges)?
            .entries::<LUID_AND_ATTRIBUTES>(offset_of!(TOKEN_PRIVILEGES, Privileges))?
            .into_iter()
            .map(|entry| (entry.Luid.HighPart, entry.Luid.LowPart, entry.Attributes))
            .collect::<Vec<_>>();
        privileges.sort();
        let integrity = Buffer::query(token, TokenIntegrityLevel)?;
        let label = integrity.header::<TOKEN_MANDATORY_LABEL>()?.Label;
        let sid = integrity.sid(label.Sid)?;
        ensure!(
            sid.len() == 12 && sid[1] == 1 && sid[2..8] == [0, 0, 0, 0, 0, 16],
            "unexpected integrity SID shape"
        );
        let integrity = (u32::from_le_bytes(sid[8..12].try_into()?), label.Attributes);
        let mandatory_policy = Buffer::query(token, TokenMandatoryPolicy)?
            .header::<TOKEN_MANDATORY_POLICY>()?
            .Policy;
        Ok(Self {
            user: (user.sid(user_header.User.Sid)?, user_header.User.Attributes),
            owner: owner.sid(owner_header.Owner)?,
            groups,
            restricting,
            privileges,
            integrity,
            mandatory_policy,
            token_type,
        })
    }

    fn roles(&self, sid: &[u8]) -> Vec<&'static str> {
        let mut roles = Vec::new();
        if sid == self.user.0.as_slice() {
            roles.push("token_user");
        }
        if sid == self.owner.as_slice() {
            roles.push("token_default_owner");
        }
        for (role, kind) in [
            ("world", WinWorldSid),
            ("administrators", WinBuiltinAdministratorsSid),
            ("users", WinBuiltinUsersSid),
            ("authenticated_users", WinAuthenticatedUserSid),
            ("system", WinLocalSystemSid),
        ] {
            if unsafe { IsWellKnownSid(sid.as_ptr().cast_mut().cast(), kind) } != 0 {
                roles.push(role);
            }
        }
        if roles.is_empty() {
            roles.push("other");
        }
        roles
    }

    fn group_summary(&self, groups: &[(Vec<u8>, u32)]) -> Vec<Value> {
        groups
            .iter()
            .map(|(sid, attributes)| json!({"roles": self.roles(sid), "attributes": attributes}))
            .collect()
    }

    pub(super) fn summary(&self) -> Value {
        json!({
            "token_type": self.token_type,
            "user_roles": self.roles(&self.user.0), "user_attributes": self.user.1,
            "owner_roles": self.roles(&self.owner),
            "group_count": self.groups.len(), "groups": self.group_summary(&self.groups),
            "restricting_count": self.restricting.len(), "restricting": self.group_summary(&self.restricting),
            "privilege_count": self.privileges.len(), "privileges_luid_and_raw_attributes": self.privileges,
            "integrity_rid": self.integrity.0, "integrity_attributes": self.integrity.1,
            "mandatory_policy": self.mandatory_policy,
        })
    }

    pub(super) fn compare(&self, launch: &Self) -> Value {
        json!({"raw_observed_fields_equal": self == launch,
            "user_equal": self.user == launch.user, "owner_equal": self.owner == launch.owner,
            "groups_equal": self.groups == launch.groups, "restricting_equal": self.restricting == launch.restricting,
            "raw_privileges_equal": self.privileges == launch.privileges,
            "integrity_equal": self.integrity == launch.integrity,
            "mandatory_policy_equal": self.mandatory_policy == launch.mandatory_policy,
            "token_type_equal": self.token_type == launch.token_type})
    }
}
