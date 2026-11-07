//! Direct access checks against one retained fixture security descriptor.
//! This diagnostic compares the original token with a full restricting control.
//! It never impersonates the control, mutates an ACL, or performs a deletion.

use super::super::DISABLE_MAX_PRIVILEGE;
use super::super::LUA_TOKEN;
use super::super::enable_single_privilege;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use std::ffi::c_void;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Foundation::SetLastError;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::DuplicateToken;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_SELF_RELATIVE;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::SetTokenInformation;
use windows_sys::Win32::Security::TOKEN_DEFAULT_DACL;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TokenDefaultDacl;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;

const MAX_DIAGNOSTIC_BYTES: usize = 1024 * 1024;

struct TokenInformation {
    words: Vec<u64>,
    bytes: usize,
}

impl TokenInformation {
    fn read(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Self> {
        let mut needed = 0;
        // SAFETY: token is retained by the caller; this is a size-only query.
        unsafe {
            GetTokenInformation(
                token,
                class,
                ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            );
        }
        ensure!(
            needed > 0 && needed as usize <= MAX_DIAGNOSTIC_BYTES,
            "access-check token information size is invalid"
        );
        let mut words = vec![0_u64; (needed as usize).div_ceil(8)];
        let capacity = words.len() * 8;
        // SAFETY: the aligned, initialized buffer covers the supplied capacity.
        if unsafe {
            GetTokenInformation(
                token,
                class,
                words.as_mut_ptr().cast(),
                capacity as u32,
                &mut needed,
            )
        } == 0
        {
            return Err(anyhow!("access-check token query errno={}", unsafe {
                GetLastError()
            }));
        }
        ensure!(needed as usize <= capacity, "access-check token query grew");
        Ok(Self {
            words,
            bytes: needed as usize,
        })
    }

    fn restricting_entries(&self) -> Result<Vec<SID_AND_ATTRIBUTES>> {
        let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
        ensure!(
            self.bytes >= offset,
            "access-check group header is truncated"
        );
        // SAFETY: the complete GroupCount field lies within the returned buffer.
        let count = unsafe { ptr::read_unaligned(self.words.as_ptr().cast::<u32>()) } as usize;
        let size = std::mem::size_of::<SID_AND_ATTRIBUTES>();
        ensure!(
            count > 0 && count <= (self.bytes - offset) / size,
            "access-check group array is truncated"
        );
        let start = self.words.as_ptr() as usize;
        let end = start
            .checked_add(self.bytes)
            .ok_or_else(|| anyhow!("access-check token span overflow"))?;
        let mut entries = Vec::with_capacity(count);
        for index in 0..count {
            // SAFETY: the entire SID_AND_ATTRIBUTES entry was bounded above.
            let entry = unsafe {
                ptr::read_unaligned(
                    self.words
                        .as_ptr()
                        .cast::<u8>()
                        .add(offset + index * size)
                        .cast::<SID_AND_ATTRIBUTES>(),
                )
            };
            let sid = entry.Sid as usize;
            ensure!(
                sid >= start && sid <= end && end - sid >= 8,
                "access-check SID header escapes its allocation"
            );
            // SAFETY: the complete SID header lies within this retained buffer.
            let subauthorities = unsafe { *entry.Sid.cast::<u8>().add(1) } as usize;
            ensure!(
                8 + subauthorities * 4 <= end - sid,
                "access-check SID body escapes its allocation"
            );
            // SAFETY: the complete SID bytes have been bounded before Win32 reads.
            ensure!(
                unsafe { IsValidSid(entry.Sid) } != 0,
                "access-check restricting SID is invalid"
            );
            entries.push(SID_AND_ATTRIBUTES {
                Sid: entry.Sid,
                Attributes: 0,
            });
        }
        Ok(entries)
    }

    fn restricting_values(&self) -> Result<Vec<Vec<u8>>> {
        let mut values = Vec::new();
        for entry in self.restricting_entries()? {
            // SAFETY: restricting_entries bounded each complete, valid SID.
            let bytes = unsafe {
                let count = *entry.Sid.cast::<u8>().add(1) as usize;
                std::slice::from_raw_parts(entry.Sid.cast::<u8>(), 8 + count * 4)
            };
            values.push(bytes.to_vec());
        }
        values.sort();
        Ok(values)
    }
}

fn full_restricting_control(base: HANDLE, original: HANDLE) -> Result<OwnedHandle> {
    // Read the actual restricting list: the caller's diagnostic known-SID list
    // also contains the foreign outside capability and cannot be used here.
    let restrictions = TokenInformation::read(original, TokenRestrictedSids)?;
    let entries = restrictions.restricting_entries()?;
    let mut raw = 0;
    // SAFETY: base and every validated SID allocation remain live through this
    // call. The production flags differ only by omitting WRITE_RESTRICTED.
    if unsafe {
        CreateRestrictedToken(
            base,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            /*disablesidcount*/ 0,
            ptr::null(),
            /*deleteprivilegecount*/ 0,
            ptr::null(),
            entries.len() as u32,
            entries.as_ptr(),
            &mut raw,
        )
    } == 0
    {
        return Err(anyhow!(
            "access-check full control creation errno={}",
            unsafe { GetLastError() }
        ));
    }
    // SAFETY: the successful factory returned one newly owned handle.
    let control = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let default_dacl = TokenInformation::read(original, TokenDefaultDacl)?;
    ensure!(
        default_dacl.bytes >= std::mem::size_of::<TOKEN_DEFAULT_DACL>(),
        "access-check default DACL header is truncated"
    );
    // SAFETY: the original token's returned default-DACL buffer and embedded ACL
    // remain live; SetTokenInformation copies them into the new control only.
    if unsafe {
        SetTokenInformation(
            raw,
            TokenDefaultDacl,
            default_dacl.words.as_ptr().cast(),
            std::mem::size_of::<TOKEN_DEFAULT_DACL>() as u32,
        )
    } == 0
    {
        return Err(anyhow!(
            "access-check control default DACL errno={}",
            unsafe { GetLastError() }
        ));
    }
    // SAFETY: this restores the same single privilege as the production factory.
    unsafe { enable_single_privilege(raw, "SeChangeNotifyPrivilege")? };
    let copied = TokenInformation::read(raw, TokenRestrictedSids)?;
    ensure!(
        restrictions.restricting_values()? == copied.restricting_values()?,
        "access-check full control restricting SIDs differ"
    );
    eprintln!(
        "delete-accesscheck control=full-restricting restricted_sid_count={} exact_original_sids=true flags={:#x}",
        entries.len(),
        DISABLE_MAX_PRIVILEGE | LUA_TOKEN
    );
    Ok(control)
}

fn access_token(token: HANDLE) -> Result<OwnedHandle> {
    let mut raw = 0;
    // SAFETY: token is retained. AccessCheck needs an impersonation token with
    // TOKEN_QUERY; no thread is actually impersonated by this diagnostic.
    if unsafe { DuplicateToken(token, SecurityImpersonation, &mut raw) } == 0 {
        return Err(anyhow!("access-check token duplication errno={}", unsafe {
            GetLastError()
        }));
    }
    // SAFETY: DuplicateToken transferred ownership of this successful handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as _) })
}

struct SecurityDescriptor(*mut c_void);

impl SecurityDescriptor {
    fn read(file: &std::fs::File) -> Result<Self> {
        let mut raw = ptr::null_mut();
        // SAFETY: the retained existing-object handle has READ_CONTROL. Request
        // owner and group as well as DACL: AccessCheck requires all three.
        let status = unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as _,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                &mut raw,
            )
        };
        let descriptor = Self(raw);
        ensure!(
            status == ERROR_SUCCESS && !raw.is_null(),
            "access-check descriptor query errno={status}"
        );
        Ok(descriptor)
    }

    fn bytes(&self) -> Result<Vec<u8>> {
        // SAFETY: GetSecurityInfo owns this live descriptor allocation.
        ensure!(
            unsafe { IsValidSecurityDescriptor(self.0) } != 0,
            "access-check security descriptor is invalid"
        );
        let mut control = 0;
        let mut revision = 0;
        // SAFETY: descriptor validity and allocation lifetime were checked above.
        ensure!(
            unsafe { GetSecurityDescriptorControl(self.0, &mut control, &mut revision) } != 0
                && control & SE_SELF_RELATIVE != 0,
            "access-check descriptor is not self-relative"
        );
        // SAFETY: a valid self-relative descriptor has a contiguous returned span.
        let length = unsafe { GetSecurityDescriptorLength(self.0) } as usize;
        ensure!(
            length > 0 && length <= MAX_DIAGNOSTIC_BYTES,
            "access-check descriptor size is invalid"
        );
        // SAFETY: this is the complete span of the retained self-relative copy.
        Ok(unsafe { std::slice::from_raw_parts(self.0.cast::<u8>(), length) }.to_vec())
    }
}

impl Drop for SecurityDescriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: GetSecurityInfo transferred this single LocalAlloc buffer.
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

fn check(
    descriptor: &SecurityDescriptor,
    token: HANDLE,
    token_label: &str,
    object: &str,
    access: &str,
    mask: u32,
) -> Result<()> {
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut privileges = vec![0_u64; 128];
    // One bounded size negotiation is allowed; an access denial is never retried.
    for sizing in 0..2 {
        let mut length = (privileges.len() * 8) as u32;
        let mut granted = 0;
        let mut allowed = 0;
        // SAFETY: every descriptor/token is retained; the aligned initialized
        // privilege buffer covers length. All masks are already object-specific.
        let (api, errno) = unsafe {
            SetLastError(/*dwerrcode*/ 0);
            let api = AccessCheck(
                descriptor.0,
                token,
                mask,
                &mapping,
                privileges.as_mut_ptr().cast(),
                &mut length,
                &mut granted,
                &mut allowed,
            );
            (api, GetLastError())
        };
        if api == 0
            && errno == ERROR_INSUFFICIENT_BUFFER
            && sizing == 0
            && length as usize > privileges.len() * 8
            && length as usize <= MAX_DIAGNOSTIC_BYTES
        {
            privileges.resize((length as usize).div_ceil(8), /*value*/ 0);
            continue;
        }
        eprintln!(
            "delete-accesscheck token={token_label} object={object} access={access} desired={mask:#x} api_ok={} access_status={} granted={granted:#x} errno={errno}",
            api != 0,
            allowed != 0
        );
        ensure!(api != 0, "access-check API failed errno={errno}");
        return Ok(());
    }
    Err(anyhow!("access-check privilege sizing was not resolved"))
}

pub(super) fn observe(base: HANDLE, original: HANDLE, paths: &[(&str, &Path)]) -> Result<()> {
    let full = full_restricting_control(base, original)?;
    let original = access_token(original)?;
    let full = access_token(full.as_raw_handle() as _)?;
    for &(object, path) in paths {
        // Metadata access only: this opens no data-write/delete handle and does not
        // use the full restricting token to access any filesystem object.
        let file = OpenOptions::new()
            .access_mode(READ_CONTROL | FILE_READ_ATTRIBUTES)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)?;
        let is_directory = file.metadata()?.is_dir();
        let descriptor = SecurityDescriptor::read(&file)?;
        let before = descriptor.bytes()?;
        for (token_label, token) in [
            ("production-write-restricted", original.as_raw_handle()),
            ("full-restricting-control", full.as_raw_handle()),
        ] {
            for (access, mask) in [
                ("read", FILE_READ_DATA),
                ("write", FILE_WRITE_DATA),
                ("delete", DELETE),
                ("delete-child", FILE_DELETE_CHILD),
            ] {
                if access == "delete-child" && !is_directory {
                    continue;
                }
                check(&descriptor, token as _, token_label, object, access, mask)?;
            }
        }
        ensure!(
            before == descriptor.bytes()?,
            "access-check security descriptor copy changed"
        );
        eprintln!("delete-accesscheck object={object} same_descriptor_bytes=true");
    }
    Ok(())
}
