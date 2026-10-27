//! Manual diagnostic facts for the original two failing signature fixtures.
//! These metadata reads grant no authority and never inspect private-key bytes.

use codex_utils_path::PrivateFile;
use codex_utils_path::PrivateFileIdentity;
use codex_utils_path::PrivateFileKind;
use codex_utils_path::PrivateSecurityIdentity;
use codex_utils_path::WindowsFileId;
use serde_json::Value;
use serde_json::json;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetKernelObjectSecurity;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_OWNER;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenOwner;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

/// Same effective-token precedence as the canonical predicate, with raw errors.
pub(crate) fn effective_token() -> Value {
    let mut handle = 0;
    // SAFETY: pseudohandle borrowed; success creates one owned token handle.
    let thread = unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut handle) };
    let thread_error = (thread == 0).then(|| unsafe { GetLastError() });
    if let Some(error) = thread_error {
        if error != ERROR_NO_TOKEN {
            return json!({"ok": false, "operation": "OpenThreadToken", "raw_win32_error": error});
        }
        // SAFETY: the thread has no impersonation token, so inspect the process.
        if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut handle) } == 0 {
            return json!({"ok": false, "operation": "OpenProcessToken",
                "raw_win32_error": io::Error::last_os_error().raw_os_error()});
        }
    }
    if handle == 0 {
        return json!({"ok": false, "error": "successful token API returned null"});
    }
    // SAFETY: exactly one successful token API supplied this owned handle.
    let token = unsafe { OwnedHandle::from_raw_handle(handle as _) };
    json!({"ok": true, "source": if thread != 0 {"thread"} else {"process"},
        "OpenThreadToken_raw_error": thread_error,
        "user_sid": result(token_sid(&token, TokenUser)),
        "owner_sid": result(token_sid(&token, TokenOwner))})
}

fn token_sid(token: &OwnedHandle, class: TOKEN_INFORMATION_CLASS) -> io::Result<String> {
    let mut length = 0;
    // SAFETY: first call asks for the size; token remains owned during both reads.
    unsafe {
        GetTokenInformation(
            token.as_raw_handle() as _,
            class,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    };
    if length == 0 || length > 128 * 1024 {
        return Err(io::Error::last_os_error());
    }
    let mut bytes = vec![0usize; (length as usize).div_ceil(std::mem::size_of::<usize>())];
    // SAFETY: allocation is bounded, aligned, and covers length bytes.
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle() as _,
            class,
            bytes.as_mut_ptr().cast(),
            length,
            &mut length,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: only the matching two fixed classes are requested above.
    let sid = unsafe {
        match class {
            value if value == TokenUser => (*bytes.as_ptr().cast::<TOKEN_USER>()).User.Sid,
            value if value == TokenOwner => (*bytes.as_ptr().cast::<TOKEN_OWNER>()).Owner,
            _ => return Err(io::Error::other("unexpected token information class")),
        }
    };
    if sid.is_null() || unsafe { IsValidSid(sid) } == 0 {
        return Err(io::Error::other("OS returned an invalid token SID"));
    }
    let mut text = std::ptr::null_mut();
    // SAFETY: SID is OS-owned within the still-live token-information buffer.
    if unsafe { ConvertSidToStringSidW(sid, &mut text) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let converted = if text.is_null() {
        Err(io::Error::other("SID conversion returned null"))
    } else {
        // SAFETY: successful conversion yields a terminated allocated SID string.
        let count = (0..256).find(|offset| unsafe { *text.add(*offset) } == 0);
        count
            .map(|count| {
                String::from_utf16_lossy(unsafe { std::slice::from_raw_parts(text, count) })
            })
            .ok_or_else(|| io::Error::other("SID conversion exceeds diagnostic bound"))
    };
    if !text.is_null() {
        unsafe { LocalFree(text as _) };
    }
    converted
}

fn result<T: std::fmt::Debug>(value: io::Result<T>) -> Value {
    match value {
        Ok(value) => json!({"ok": true, "facts": format!("{value:?}")}),
        Err(error) => json!({"ok": false, "kind": format!("{:?}", error.kind()),
            "raw_win32_error": error.raw_os_error(), "message": error.to_string()}),
    }
}

fn query<T>(file: &File, class: FILE_INFO_BY_HANDLE_CLASS) -> io::Result<T> {
    // SAFETY: only the matching fixed-size FILE_* types below call this helper.
    let mut value: T = unsafe { std::mem::zeroed() };
    if unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle() as _,
            class,
            (&mut value as *mut T).cast(),
            std::mem::size_of::<T>() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(value)
}

fn id(file: &File) -> Value {
    match query::<FILE_ID_INFO>(file, FileIdInfo) {
        Ok(value) => json!({"ok": true, "operation": "GetFileInformationByHandleEx(FileIdInfo)",
            "volume_serial_hex": format!("{:016x}", value.VolumeSerialNumber),
            "file_id_16_bytes": value.FileId.Identifier}),
        Err(error) => result::<()>(Err(error)),
    }
}

fn security(file: &File) -> Value {
    let flags = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    let mut length = 0;
    // SAFETY: query the required descriptor size on this same held object.
    unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            flags,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    };
    if length == 0 || length > 128 * 1024 {
        return json!({"ok": false, "operation": "GetKernelObjectSecurity(size)",
            "required_bytes": length, "raw_win32_error": io::Error::last_os_error().raw_os_error()});
    }
    let mut storage = vec![0usize; (length as usize).div_ceil(std::mem::size_of::<usize>())];
    // SAFETY: bounded aligned allocation covers the declared descriptor buffer.
    let descriptor = storage.as_mut_ptr().cast();
    if unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            flags,
            descriptor,
            length,
            &mut length,
        )
    } == 0
    {
        return json!({"ok": false, "operation": "GetKernelObjectSecurity(data)",
            "raw_win32_error": io::Error::last_os_error().raw_os_error()});
    }
    // SAFETY: the successful kernel call initialized length bytes in storage.
    let raw = unsafe { std::slice::from_raw_parts(storage.as_ptr().cast::<u8>(), length as usize) };
    let valid = unsafe { IsValidSecurityDescriptor(descriptor) } != 0;
    let mut text = std::ptr::null_mut();
    let mut chars = 0;
    // SDDL includes the complete original owner and DACL/ACE masks/flags/SIDs.
    // This is a diagnostic read, not a replacement private-security predicate.
    let converted = valid
        && unsafe {
            ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, flags, &mut text, &mut chars,
            )
        } != 0;
    let conversion_error = if converted {
        None
    } else {
        io::Error::last_os_error().raw_os_error()
    };
    let sddl = if converted && !text.is_null() && chars > 0 && chars <= 128 * 1024 {
        // SAFETY: successful Win32 conversion owns chars UTF-16 units.
        Some(String::from_utf16_lossy(unsafe {
            std::slice::from_raw_parts(text, chars as usize - 1)
        }))
    } else {
        None
    };
    if !text.is_null() {
        unsafe { LocalFree(text as _) };
    }
    json!({"ok": true, "operation": "GetKernelObjectSecurity(OWNER|DACL) on retained File",
        "descriptor_valid": valid, "descriptor_bytes": raw, "owner_and_dacl_sddl": sddl,
        "sddl_conversion_win32_error": conversion_error})
}

/// Read only one explicitly selected, generated fixture file; never a key file.
pub(crate) fn inspect(path: &Path) -> Value {
    let file = match OpenOptions::new()
        .read(true)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
    {
        Ok(file) => file,
        Err(error) => return json!({"path": path, "open": result::<()>(Err(error))}),
    };
    let before = id(&file);
    let mut facts = json!({"path": path, "open": {"ok": true,
        "operation": "read-only OpenOptions + OPEN_REPARSE_POINT"}, "id_before": before,
        "canonical_held_id": result(WindowsFileId::inspect(&file)),
        "canonical_private_security": result(PrivateSecurityIdentity::inspect(&file)),
        "canonical_full_snapshot": result(PrivateFileIdentity::inspect(&file, PrivateFileKind::RegularFile)),
        "canonical_current_path": result(PrivateFile::open_existing(path).map(|file| format!("{:?}", file.identity())))});
    facts["owner_dacl"] = security(&file);
    facts["attribute_tag"] = match query::<FILE_ATTRIBUTE_TAG_INFO>(&file, FileAttributeTagInfo) {
        Ok(v) => json!({"ok": true, "attributes": v.FileAttributes, "reparse_tag": v.ReparseTag}),
        Err(error) => result::<()>(Err(error)),
    };
    facts["basic"] = match query::<FILE_BASIC_INFO>(&file, FileBasicInfo) {
        Ok(v) => json!({"ok": true, "creation": v.CreationTime.to_string(),
            "last_write": v.LastWriteTime.to_string(), "change": v.ChangeTime.to_string(),
            "attributes": v.FileAttributes}),
        Err(error) => result::<()>(Err(error)),
    };
    facts["standard"] = match query::<FILE_STANDARD_INFO>(&file, FileStandardInfo) {
        Ok(v) => {
            json!({"ok": true, "length": v.EndOfFile.to_string(), "allocation": v.AllocationSize.to_string(),
            "links": v.NumberOfLinks, "delete_pending": v.DeletePending, "directory": v.Directory})
        }
        Err(error) => result::<()>(Err(error)),
    };
    facts["id_after"] = id(&file);
    facts["retained_full_id_unchanged"] = json!(facts["id_before"] == facts["id_after"]);
    facts["current_path_id"] = match OpenOptions::new()
        .read(true)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
    {
        Ok(current) => id(&current),
        Err(error) => result::<()>(Err(error)),
    };
    facts["current_path_matches_retained_full_id"] =
        json!(facts["id_before"] == facts["current_path_id"]);
    facts
}

/// Exclusive diagnostic output outside the source checkout; no functional pass.
pub(crate) fn save(name: &str, facts: Value) -> io::Result<()> {
    let root = std::env::var_os("HEPTA_WINDOWS_SIGNATURE_TRACE_DIR")
        .ok_or_else(|| io::Error::other("explicit native diagnostic directory is required"))?;
    let root = Path::new(&root);
    if !root.is_absolute()
        || !root.is_dir()
        || !matches!(
            name,
            "trust-signature-original.json"
                | "g5-signature-original.json"
                | "openssh-native-contract.json"
        )
    {
        return Err(io::Error::other("invalid dedicated diagnostic output"));
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(name))?;
    file.write_all(&serde_json::to_vec_pretty(&facts)?)?;
    file.sync_all()
}
