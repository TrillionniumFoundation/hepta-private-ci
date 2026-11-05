//! Same-object observations and restoration for this probe's newly created objects only.

use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation as win;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::Security::Authorization as auth;
use windows_sys::Win32::Storage::FileSystem as fswin;

const IDENTITY_INFO: u32 = security::OWNER_SECURITY_INFORMATION
    | security::GROUP_SECURITY_INFORMATION
    | security::DACL_SECURITY_INFORMATION;
const ALL_INFO: u32 = IDENTITY_INFO | security::LABEL_SECURITY_INFORMATION;

pub(super) fn observe(detail: std::fmt::Arguments<'_>) -> std::io::Result<()> {
    // Bypass libtest's successful-test capture without changing launcher arguments.
    writeln!(std::io::stderr().lock(), "\nPROBE_OBSERVATION_ONLY {detail}")
}

pub(super) struct Handle(pub(super) win::HANDLE);

impl Drop for Handle {
    fn drop(&mut self) {
        // SAFETY: this guard owns a successful native handle result.
        unsafe { win::CloseHandle(self.0) };
    }
}

struct Local(*mut c_void);

impl Drop for Local {
    fn drop(&mut self) {
        // SAFETY: only LocalAlloc-family security API results enter this guard.
        unsafe { win::LocalFree(self.0 as win::HLOCAL) };
    }
}

pub(super) struct Descriptor(Local);

impl Descriptor {
    pub(super) fn from_sddl(sddl: &str) -> Result<Self> {
        let mut raw = Local(std::ptr::null_mut());
        // SAFETY: the terminated input lives through the call; raw takes ownership.
        ensure!(unsafe {
            auth::ConvertStringSecurityDescriptorToSecurityDescriptorW(
                crate::winutil::to_wide(sddl).as_ptr(), auth::SDDL_REVISION_1,
                &mut raw.0, std::ptr::null_mut(),
            )
        } != 0, "parse fixture SDDL: {}", std::io::Error::last_os_error());
        Ok(Self(raw))
    }

    fn read(handle: win::HANDLE) -> Result<Self> {
        let mut raw = Local(std::ptr::null_mut());
        // SAFETY: handle is retained; LABEL queries need READ_CONTROL, not whole-SACL access.
        let code = unsafe {
            auth::GetSecurityInfo(handle, auth::SE_FILE_OBJECT, ALL_INFO,
                std::ptr::null_mut(), std::ptr::null_mut(), std::ptr::null_mut(),
                std::ptr::null_mut(), &mut raw.0)
        };
        ensure!(code == 0, "GetSecurityInfo: {code}");
        Ok(Self(raw))
    }

    fn text(&self, parts: u32) -> Result<String> {
        let (mut output, mut length) = (std::ptr::null_mut(), 0);
        // SAFETY: this descriptor is live; the returned UTF-16 allocation is owned below.
        let ok = unsafe {
            auth::ConvertSecurityDescriptorToStringSecurityDescriptorW(
                self.0.0, auth::SDDL_REVISION_1, parts, &mut output, &mut length)
        };
        let _allocation = Local(output.cast());
        ensure!(ok != 0 && length > 0, "format fixture SD: {}", std::io::Error::last_os_error());
        // SAFETY: the successful API returned this many UTF-16 code units, including NUL.
        let text = unsafe { std::slice::from_raw_parts(output, length as usize) };
        let end = text.iter().position(|unit| *unit == 0)
            .ok_or_else(|| anyhow::anyhow!("unterminated fixture SDDL"))?;
        Ok(String::from_utf16(&text[..end])?)
    }

    fn apply_label(&self, handle: win::HANDLE) -> Result<()> {
        let (mut present, mut defaulted, mut acl) = (0, 0, std::ptr::null_mut());
        // SAFETY: both the descriptor and its returned label ACL remain live.
        ensure!(unsafe {
            security::GetSecurityDescriptorSacl(self.0.0, &mut present, &mut acl, &mut defaulted)
        } != 0 && present != 0 && !acl.is_null(), "fixture requires an explicit label");
        let code = unsafe {
            auth::SetSecurityInfo(handle, auth::SE_FILE_OBJECT, security::LABEL_SECURITY_INFORMATION,
                std::ptr::null_mut(), std::ptr::null_mut(), std::ptr::null(), acl)
        };
        ensure!(code == 0, "set owned object label: {code}");
        Ok(())
    }

    pub(super) fn create(&self, path: &Path, kind: ObjectKind) -> Result<()> {
        let attributes = security::SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<security::SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: self.0.0,
            bInheritHandle: 0,
        };
        let path = crate::winutil::to_wide(path);
        // SAFETY: only new paths inside the owned TempDir are passed; explicit Medium
        // at creation avoids depending on an undocumented NULL-label removal operation.
        match kind {
            ObjectKind::Directory => ensure!(unsafe {
                fswin::CreateDirectoryW(path.as_ptr(), &attributes)
            } != 0, "create owned directory: {}", std::io::Error::last_os_error()),
            ObjectKind::File => {
                let handle = unsafe {
                    fswin::CreateFileW(path.as_ptr(), fswin::FILE_WRITE_DATA,
                        fswin::FILE_SHARE_READ | fswin::FILE_SHARE_WRITE | fswin::FILE_SHARE_DELETE,
                        &attributes, fswin::CREATE_NEW, fswin::FILE_ATTRIBUTE_NORMAL,
                        /*htemplatefile*/ 0)
                };
                ensure!(handle != win::INVALID_HANDLE_VALUE, "create owned file: {}", std::io::Error::last_os_error());
                let _created = Handle(handle);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
pub(super) enum ObjectKind { Directory, File }

fn identity(file: &File) -> Result<(u32, u32, u32)> {
    // SAFETY: a successful call initializes this exact native output structure.
    let mut info: fswin::BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    ensure!(unsafe { fswin::GetFileInformationByHandle(file.as_raw_handle() as win::HANDLE, &mut info) } != 0,
        "object identity: {}", std::io::Error::last_os_error());
    ensure!(info.dwFileAttributes & fswin::FILE_ATTRIBUTE_REPARSE_POINT == 0, "reparse point in fixture");
    ensure!(info.dwFileAttributes & fswin::FILE_ATTRIBUTE_DIRECTORY != 0 || info.nNumberOfLinks <= 1,
        "hard-linked file in fixture");
    Ok((info.dwVolumeSerialNumber, info.nFileIndexHigh, info.nFileIndexLow))
}

pub(super) struct LabelledObject {
    path: PathBuf,
    file: File,
    original: Descriptor,
    original_identity: (u32, u32, u32),
    original_access: String,
    expected_label: String,
    restore: bool,
}

impl LabelledObject {
    pub(super) fn prepare(path: &Path, label: &Descriptor, initial_label: &Descriptor) -> Result<Self> {
        // No DELETE right, no inheritable handle, and share-delete remains enabled.
        // Physical operations use fresh path opens; this handle is only for SD/identity.
        let file = OpenOptions::new().read(true)
            .access_mode(fswin::READ_CONTROL | fswin::WRITE_OWNER | fswin::FILE_READ_ATTRIBUTES)
            .share_mode(fswin::FILE_SHARE_READ | fswin::FILE_SHARE_WRITE | fswin::FILE_SHARE_DELETE)
            .custom_flags(fswin::FILE_FLAG_BACKUP_SEMANTICS | fswin::FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)?;
        let handle = file.as_raw_handle() as win::HANDLE;
        let mut flags = 0;
        // SAFETY: handle belongs to the File retained in this object.
        ensure!(unsafe { win::GetHandleInformation(handle, &mut flags) } != 0
            && flags & win::HANDLE_FLAG_INHERIT == 0, "invalid inherited fixture handle");
        let original = Descriptor::read(handle)?;
        let actual_label = original.text(security::LABEL_SECURITY_INFORMATION)?;
        let expected_label = initial_label.text(security::LABEL_SECURITY_INFORMATION)?;
        observe(format_args!(
            "initial_label path={path:?} actual={actual_label:?} expected={expected_label:?}"
        ))?;
        ensure!(actual_label == expected_label,
            "created object did not preserve its explicit initial label");
        let result = Self {
            path: path.to_owned(), original_identity: identity(&file)?,
            original_access: original.text(IDENTITY_INFO)?,
            expected_label: label.text(security::LABEL_SECURITY_INFORMATION)?,
            original, file, restore: true,
        };
        label.apply_label(handle)?;
        let actual = Descriptor::read(handle)?;
        ensure!(actual.text(IDENTITY_INFO)? == result.original_access
            && actual.text(security::LABEL_SECURITY_INFORMATION)? == result.expected_label,
            "label set changed access SD or failed readback");
        ensure!(identity(&result.file)? == result.original_identity, "label set changed object identity");
        Ok(result)
    }

    pub(super) fn access_checks(&self, tokens: &[(&str, win::HANDLE)], desired: u32) -> Result<Value> {
        let descriptor = Descriptor::read(self.file.as_raw_handle() as win::HANDLE)?;
        ensure!(identity(&self.file)? == self.original_identity, "AccessCheck identity changed");
        let mapping = security::GENERIC_MAPPING {
            GenericRead: fswin::FILE_GENERIC_READ, GenericWrite: fswin::FILE_GENERIC_WRITE,
            GenericExecute: fswin::FILE_GENERIC_EXECUTE, GenericAll: fswin::FILE_ALL_ACCESS,
        };
        let mut checks = Vec::new();
        for (name, token) in tokens {
            let mut duplicated = 0;
            // SAFETY: each live primary token is duplicated to the type AccessCheck requires.
            ensure!(unsafe { security::DuplicateToken(*token, security::SecurityImpersonation, &mut duplicated) } != 0,
                "DuplicateToken: {}", std::io::Error::last_os_error());
            let duplicated = Handle(duplicated);
            let mut privileges = [0_u64; 128];
            let mut length = std::mem::size_of_val(&privileges) as u32;
            let (mut granted, mut allowed) = (0, 0);
            // SAFETY: the complete same-object SD and aligned bounded privilege buffer are live.
            let ok = unsafe {
                win::SetLastError(/*dwerrcode*/ 0);
                security::AccessCheck(descriptor.0.0, duplicated.0, desired, &mapping,
                    privileges.as_mut_ptr().cast(), &mut length, &mut granted, &mut allowed)
            };
            let error = unsafe { win::GetLastError() };
            ensure!(ok != 0, "AccessCheck API failed: {error}, required_privilege_bytes={length}");
            checks.push(json!({"subject": name, "allowed": allowed != 0, "granted": granted, "last_error": error}));
        }
        Ok(json!({"path": self.path, "identity": self.original_identity,
            "sd": descriptor.text(ALL_INFO)?, "access_sd": descriptor.text(IDENTITY_INFO)?,
            "desired": desired, "checks": checks}))
    }

    pub(super) fn finish(mut self) -> Result<Value> {
        ensure!(identity(&self.file)? == self.original_identity, "retained identity changed");
        let actual = Descriptor::read(self.file.as_raw_handle() as win::HANDLE)?;
        ensure!(actual.text(IDENTITY_INFO)? == self.original_access
            && actual.text(security::LABEL_SECURITY_INFORMATION)? == self.expected_label,
            "SD changed during physical operations");
        let mut info: fswin::FILE_STANDARD_INFO = unsafe { std::mem::zeroed() };
        // SAFETY: the File owns this handle and the native output has the exact size.
        ensure!(unsafe { fswin::GetFileInformationByHandleEx(self.file.as_raw_handle() as win::HANDLE,
            fswin::FileStandardInfo, (&mut info as *mut fswin::FILE_STANDARD_INFO).cast(),
            std::mem::size_of_val(&info) as u32) } != 0,
            "FileStandardInfo: {}", std::io::Error::last_os_error());
        let deleted = info.DeletePending != 0 || info.NumberOfLinks == 0;
        if !deleted {
            self.original.apply_label(self.file.as_raw_handle() as win::HANDLE)?;
            ensure!(Descriptor::read(self.file.as_raw_handle() as win::HANDLE)?.text(ALL_INFO)? == self.original.text(ALL_INFO)?,
                "original label/access SD restoration failed");
        }
        let result = json!({"path": self.path, "identity": self.original_identity,
            "pending": info.DeletePending, "links": info.NumberOfLinks,
            "label": self.expected_label, "restored_survivor": !deleted});
        let path = self.path.clone();
        let expected_id = self.original_identity;
        self.restore = false;
        drop(self); // Close the share-delete observation handle before checking the name.
        match OpenOptions::new().read(true).custom_flags(fswin::FILE_FLAG_BACKUP_SEMANTICS).open(&path) {
            Ok(file) => ensure!(!deleted && identity(&file)? == expected_id, "deleted/replaced object still named"),
            Err(error) => ensure!(deleted && error.kind() == std::io::ErrorKind::NotFound,
                "post-close fixture path: {error}"),
        }
        Ok(result)
    }
}

impl Drop for LabelledObject {
    fn drop(&mut self) {
        if self.restore {
            // Best-effort unwind cleanup is never counted as successful restoration.
            if let Err(error) = self.original.apply_label(self.file.as_raw_handle() as win::HANDLE) {
                let _ = observe(format_args!("restore_error path={:?}: {error:#}", self.path));
            }
        }
    }
}
