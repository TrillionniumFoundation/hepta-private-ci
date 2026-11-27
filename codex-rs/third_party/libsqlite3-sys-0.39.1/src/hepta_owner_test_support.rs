//! Native fixture support. Security is observed independently through Windows;
//! synthetic ACL/owner changes are setup for attacks, never a storage repair.

use crate::*;
use std::ffi::CStr;
use std::ffi::CString;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::mem::size_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use windows_sys::Win32::Foundation as foundation;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::Security::Authorization as authorization;
use windows_sys::Win32::Storage::FileSystem as filesystem;
use windows_sys::Win32::System::SystemServices as services;
use windows_sys::Win32::System::Threading as threading;

static NEXT_ROOT: AtomicUsize = AtomicUsize::new(0);

pub(super) struct Root(pub(super) PathBuf);
impl Root {
    pub(super) fn new() -> Self {
        let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-owner-vfs-{}-{ordinal}-{nanos}",
            std::process::id()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Copy)]
pub(super) enum Vfs<'a> {
    Stock,
    Private(&'a CStr),
}
impl Vfs<'_> {
    pub(super) fn name(self) -> *const std::ffi::c_char {
        match self {
            Self::Stock => ptr::null(),
            Self::Private(name) => name.as_ptr(),
        }
    }
    pub(super) fn pointer(self) -> *mut sqlite3_vfs {
        // SAFETY: Names are live terminated strings; registered VFSes are retained.
        let pointer = unsafe { sqlite3_vfs_find(self.name()) };
        assert!(!pointer.is_null(), "registered VFS exists");
        pointer
    }
}

pub(super) struct Database(pub(super) *mut sqlite3);
impl Database {
    pub(super) fn open(path: &Path, vfs: Vfs<'_>, flags: i32) -> Result<Self, i32> {
        let name = CString::new(path.to_str().unwrap()).unwrap();
        let mut db = ptr::null_mut();
        // SAFETY: All strings and output storage live through the synchronous call.
        let status = unsafe { sqlite3_open_v2(name.as_ptr(), &mut db, flags, vfs.name()) };
        if status != SQLITE_OK {
            if !db.is_null() {
                // SAFETY: Failed opens still return a connection requiring close.
                assert_eq!(
                    unsafe { sqlite3_close(db) },
                    SQLITE_OK,
                    "failed-open cleanup"
                );
            }
            return Err(status);
        }
        // SAFETY: Successful open returned a live connection.
        unsafe { sqlite3_extended_result_codes(db, 1) };
        Ok(Self(db))
    }
    pub(super) fn exec(&self, statement: &CStr) -> i32 {
        // SAFETY: Connection and SQL are live; callbacks and error allocation are absent.
        unsafe {
            sqlite3_exec(
                self.0,
                statement.as_ptr(),
                None,
                ptr::null_mut(),
                ptr::null_mut(),
            )
        }
    }
    pub(super) fn execute(&self, statement: &CStr) {
        let status = self.exec(statement);
        // SAFETY: sqlite3_errmsg belongs to this live connection.
        let error = unsafe { CStr::from_ptr(sqlite3_errmsg(self.0)) };
        assert_eq!(status, SQLITE_OK, "{error:?}");
    }
    pub(super) fn handle(&self) -> foundation::HANDLE {
        let mut handle = 0;
        // SAFETY: WIN32_GET_HANDLE writes a borrowed HANDLE into correctly typed storage.
        let status = unsafe {
            sqlite3_file_control(
                self.0,
                c"main".as_ptr(),
                SQLITE_FCNTL_WIN32_GET_HANDLE,
                (&mut handle as *mut foundation::HANDLE).cast(),
            )
        };
        assert_eq!(status, SQLITE_OK);
        handle
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        // SAFETY: This fixture owns the connection; sqlite3_exec retained no statements.
        assert_eq!(
            unsafe { sqlite3_close(self.0) },
            SQLITE_OK,
            "all fixture statements finalized before close"
        );
    }
}

pub(super) enum NativeName<'a> {
    Named(&'a Path),
    Temporary,
}

pub(super) struct NativeFile {
    raw: *mut sqlite3_file,
    // WinVFS borrows this double-NUL filename through xClose.
    _name: Option<Vec<u8>>,
}
impl NativeFile {
    pub(super) fn open(vfs: Vfs<'_>, name: NativeName<'_>, flags: i32) -> Result<Self, i32> {
        let name = match name {
            NativeName::Named(path) => {
                let mut value = CString::new(path.to_str().unwrap())
                    .unwrap()
                    .into_bytes_with_nul();
                value.push(0);
                Some(value)
            }
            NativeName::Temporary => None,
        };
        let name_ptr = name
            .as_ref()
            .map_or(ptr::null(), |value| value.as_ptr().cast());
        let vfs = vfs.pointer();
        // SAFETY: SQLite supplies the allocation size and allocator alignment.
        let bytes = unsafe { (*vfs).szOsFile as usize };
        let raw = unsafe { sqlite3_malloc64(bytes as u64) }.cast::<sqlite3_file>();
        assert!(!raw.is_null());
        // SAFETY: Entire allocation is writable; xOpen must always initialize pMethods.
        unsafe { ptr::write_bytes(raw.cast::<u8>(), 0, bytes) };
        let file = Self { raw, _name: name };
        let mut returned_flags = 0;
        // SAFETY: VFS is registered and all input/output storage is live for this call.
        let status =
            unsafe { (*vfs).xOpen.unwrap()(vfs, name_ptr, raw, flags, &mut returned_flags) };
        if status == SQLITE_OK {
            Ok(file)
        } else {
            Err(status)
        }
    }
    pub(super) fn handle(&self) -> foundation::HANDLE {
        let mut handle = 0;
        // SAFETY: This successfully opened file owns a live methods table.
        let status = unsafe {
            (*(*self.raw).pMethods).xFileControl.unwrap()(
                self.raw,
                SQLITE_FCNTL_WIN32_GET_HANDLE,
                (&mut handle as *mut foundation::HANDLE).cast(),
            )
        };
        assert_eq!(status, SQLITE_OK);
        handle
    }
}
impl Drop for NativeFile {
    fn drop(&mut self) {
        // SAFETY: xOpen failures may also initialize pMethods; SQLite requires close then free.
        unsafe {
            if !(*self.raw).pMethods.is_null() {
                (*(*self.raw).pMethods).xClose.unwrap()(self.raw);
            }
            sqlite3_free(self.raw.cast());
        }
    }
}

struct Descriptor(*mut c_void);
impl Drop for Descriptor {
    fn drop(&mut self) {
        // SAFETY: Each descriptor is an allocation returned by the Windows security API.
        unsafe { foundation::LocalFree(self.0) };
    }
}

#[derive(Eq, PartialEq)]
pub(super) struct Security {
    pub(super) owner: Vec<u8>,
    control: u16,
    acl: Vec<u8>,
}

pub(super) fn snapshot(handle: foundation::HANDLE) -> Security {
    let mut owner = ptr::null_mut();
    let mut acl = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    // SAFETY: All output pointers live; returned owner/ACL are owned by the descriptor.
    let status = unsafe {
        authorization::GetSecurityInfo(
            handle,
            authorization::SE_FILE_OBJECT,
            security::OWNER_SECURITY_INFORMATION | security::DACL_SECURITY_INFORMATION,
            &mut owner,
            ptr::null_mut(),
            &mut acl,
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    assert_eq!(status, 0, "native security query");
    let descriptor = Descriptor(descriptor);
    let mut control = 0;
    let mut revision = 0;
    // SAFETY: Windows owns these bounded buffers until Descriptor drops.
    unsafe {
        assert_ne!(security::IsValidSid(owner), 0);
        assert_ne!(security::IsValidAcl(acl), 0);
        assert_ne!(
            security::GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision),
            0
        );
        Security {
            owner: std::slice::from_raw_parts(owner.cast(), security::GetLengthSid(owner) as usize)
                .to_vec(),
            control,
            acl: std::slice::from_raw_parts(acl.cast(), (*acl).AclSize as usize).to_vec(),
        }
    }
}

pub(super) fn path_security(path: &Path) -> Security {
    let file = File::open(path).unwrap();
    snapshot(file.as_raw_handle() as _)
}

fn token_information(class: security::TOKEN_INFORMATION_CLASS) -> Vec<usize> {
    let mut raw = 0;
    // SAFETY: Token query returns a new owned handle without changing the token.
    assert_ne!(
        unsafe {
            threading::OpenProcessToken(
                threading::GetCurrentProcess(),
                security::TOKEN_QUERY,
                &mut raw,
            )
        },
        0
    );
    let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let mut bytes = 0;
    // SAFETY: First call obtains the required allocation size.
    unsafe {
        security::GetTokenInformation(
            token.as_raw_handle() as _,
            class,
            ptr::null_mut(),
            0,
            &mut bytes,
        )
    };
    assert!(bytes > 0 && bytes <= 65536);
    let mut buffer = vec![0usize; (bytes as usize).div_ceil(size_of::<usize>())];
    // SAFETY: Pointer-aligned buffer is at least the required byte size.
    assert_ne!(
        unsafe {
            security::GetTokenInformation(
                token.as_raw_handle() as _,
                class,
                buffer.as_mut_ptr().cast(),
                bytes,
                &mut bytes,
            )
        },
        0
    );
    buffer
}

pub(super) fn user_sid() -> Vec<u8> {
    let buffer = token_information(security::TokenUser);
    // SAFETY: TokenUser returned a pointer-aligned TOKEN_USER and retained SID.
    unsafe {
        let sid = (*buffer.as_ptr().cast::<security::TOKEN_USER>()).User.Sid;
        std::slice::from_raw_parts(sid.cast(), security::GetLengthSid(sid) as usize).to_vec()
    }
}

pub(super) fn assert_private(handle: foundation::HANDLE) {
    let observed = snapshot(handle);
    assert!(
        observed.owner == user_sid(),
        "created object has effective TokenUser owner"
    );
    assert_ne!(observed.control & security::SE_DACL_PROTECTED, 0);
    // Copy into pointer-aligned storage before independently reading the native ACL.
    let mut acl = vec![0usize; observed.acl.len().div_ceil(size_of::<usize>())];
    unsafe {
        ptr::copy_nonoverlapping(
            observed.acl.as_ptr(),
            acl.as_mut_ptr().cast(),
            observed.acl.len(),
        )
    };
    let acl = acl.as_ptr().cast::<security::ACL>();
    let mut ace = ptr::null_mut();
    // SAFETY: The copied ACL came from a validated live Windows descriptor.
    unsafe {
        assert_eq!((*acl).AceCount, 1);
        assert_ne!(security::GetAce(acl, 0, &mut ace), 0);
        let ace = &*ace.cast::<security::ACCESS_ALLOWED_ACE>();
        assert_eq!(ace.Header.AceType, 0);
        assert_eq!(ace.Header.AceFlags, 0);
        assert_eq!(ace.Mask, filesystem::FILE_ALL_ACCESS);
        let sid = ptr::addr_of!(ace.SidStart).cast::<c_void>();
        let trustee = std::slice::from_raw_parts(
            sid.cast::<u8>(),
            security::GetLengthSid(sid.cast_mut()) as usize,
        );
        assert!(trustee == observed.owner, "owner is the sole ACL trustee");
        let mut flags = 0;
        assert_ne!(foundation::GetHandleInformation(handle, &mut flags), 0);
        assert_eq!(flags & foundation::HANDLE_FLAG_INHERIT, 0);
    }
}

pub(super) enum AttackAcl {
    OwnerOnly,
    WorldReadable,
}

pub(super) fn set_fixture_acl(path: &Path, shape: AttackAcl) {
    let token = token_information(security::TokenUser);
    let mut string_sid = ptr::null_mut();
    // SAFETY: Token buffer retains the SID until the conversion finishes.
    unsafe {
        let sid = (*token.as_ptr().cast::<security::TOKEN_USER>()).User.Sid;
        assert_ne!(
            authorization::ConvertSidToStringSidW(sid, &mut string_sid),
            0
        );
    }
    let allocation = Descriptor(string_sid.cast());
    let mut length = 0;
    unsafe {
        while *string_sid.add(length) != 0 {
            length += 1;
        }
    }
    let sid =
        String::from_utf16(unsafe { std::slice::from_raw_parts(string_sid, length) }).unwrap();
    drop(allocation);
    let extra = match shape {
        AttackAcl::OwnerOnly => "",
        AttackAcl::WorldReadable => "(A;;FR;;;WD)",
    };
    let text: Vec<u16> = format!("D:P(A;;FA;;;{sid}){extra}\0")
        .encode_utf16()
        .collect();
    let mut descriptor = ptr::null_mut();
    unsafe {
        assert_ne!(
            authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW(
                text.as_ptr(),
                1,
                &mut descriptor,
                ptr::null_mut()
            ),
            0
        );
    }
    let descriptor = Descriptor(descriptor);
    let mut acl = ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    unsafe {
        assert_ne!(
            security::GetSecurityDescriptorDacl(
                descriptor.0,
                &mut present,
                &mut acl,
                &mut defaulted
            ),
            0
        );
    }
    assert_ne!(present, 0);
    let file = OpenOptions::new()
        .access_mode(filesystem::WRITE_DAC | filesystem::READ_CONTROL)
        .open(path)
        .unwrap();
    // SAFETY: This only prepares an isolated synthetic attack file, before exercising the VFS.
    let status = unsafe {
        authorization::SetSecurityInfo(
            file.as_raw_handle() as _,
            authorization::SE_FILE_OBJECT,
            security::DACL_SECURITY_INFORMATION | security::PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            acl,
            ptr::null(),
        )
    };
    assert_eq!(status, 0);
}

pub(super) fn require_wrong_owner_fixture(path: &Path) {
    if path_security(path).owner != user_sid() {
        return;
    }
    let buffer = token_information(security::TokenGroups);
    // SAFETY: TokenGroups returned a pointer-aligned variable-length array.
    let groups = unsafe { &*buffer.as_ptr().cast::<security::TOKEN_GROUPS>() };
    let candidates =
        unsafe { std::slice::from_raw_parts(groups.Groups.as_ptr(), groups.GroupCount as usize) };
    for candidate in candidates {
        if candidate.Attributes & services::SE_GROUP_OWNER as u32 != 0
            && candidate.Attributes & services::SE_GROUP_USE_FOR_DENY_ONLY as u32 == 0
        {
            let file = OpenOptions::new()
                .access_mode(filesystem::WRITE_OWNER | filesystem::READ_CONTROL)
                .open(path)
                .unwrap();
            // SAFETY: Windows checks whether this existing token group may own this synthetic file.
            let status = unsafe {
                authorization::SetSecurityInfo(
                    file.as_raw_handle() as _,
                    authorization::SE_FILE_OBJECT,
                    security::OWNER_SECURITY_INFORMATION,
                    candidate.Sid,
                    ptr::null_mut(),
                    ptr::null(),
                    ptr::null(),
                )
            };
            drop(file);
            if status == 0 && path_security(path).owner != user_sid() {
                return;
            }
        }
    }
    panic!(
        "wrong-owner attack fixture unavailable: observed owner equals TokenUser and no OS-authorized owner group could be assigned; qualification is incomplete, not skipped"
    );
}
