//! Darwin permission checks on a caller-owned, already-open file descriptor.
use std::ffi::c_int;
use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::os::fd::AsRawFd as _;
use std::ptr::NonNull;

// Apple sys/acl.h declares these as int-sized C enums. ACL objects and entries
// remain opaque; this wrapper never reads their private memory layout.
const ACL_TYPE_EXTENDED: c_int = 0x100;
const ACL_FIRST_ENTRY: c_int = 0;

#[link(name = "System")]
unsafe extern "C" {
    fn acl_get_fd_np(fd: c_int, acl_type: c_int) -> *mut c_void;
    fn acl_valid(acl: *mut c_void) -> c_int;
    fn acl_get_entry(acl: *mut c_void, entry_id: c_int, entry: *mut *mut c_void) -> c_int;
    fn acl_free(acl: *mut c_void) -> c_int;
}

struct Acl(NonNull<c_void>);

impl Drop for Acl {
    fn drop(&mut self) {
        // SAFETY: acl_get_fd_np returned this independently allocated ACL. The
        // owner releases it once; freeing the copy does not alter the inode ACL.
        unsafe { acl_free(self.0.as_ptr()) };
    }
}

/// Reject extended ACLs and mounts that ignore Unix ownership on this exact
/// opened object. Callers must separately enforce their UID, mode, type and
/// hardlink policy; this utility grants no domain or effect authority.
///
/// Any ACL entry, including a deny-only entry, is rejected. Unsupported or
/// failed permission queries fail closed. Existing permissions are not changed.
pub fn verify_private_permissions(file: &File) -> io::Result<()> {
    let filesystem = rustix::fs::fstatfs(file).map_err(io::Error::from)?;
    if filesystem.f_flags & libc::MNT_IGNORE_OWNERSHIP as u32 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private state requires a filesystem that enforces Unix ownership",
        ));
    }
    // SAFETY: File owns a live descriptor for the duration of this call. Apple
    // returns an independent, opaque ACL copy for this descriptor and type.
    let raw = unsafe { acl_get_fd_np(file.as_raw_fd(), ACL_TYPE_EXTENDED) };
    let Some(pointer) = NonNull::new(raw) else {
        let error = io::Error::last_os_error();
        // Darwin fstatx/filesec reports absent FILESEC_ACL as ENOENT. Other
        // errors, including unsupported ACL queries, are not evidence of privacy.
        return if error.raw_os_error() == Some(libc::ENOENT) {
            Ok(())
        } else {
            Err(error)
        };
    };
    let acl = Acl(pointer);
    // SAFETY: The ACL remains owned by this scope and is not concurrently shared.
    if unsafe { acl_valid(acl.0.as_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let mut entry = std::ptr::null_mut();
    // SAFETY: The ACL is valid and entry is a live output pointer. No ACL entry
    // contents are accessed, and the returned pointer is not separately freed.
    match unsafe { acl_get_entry(acl.0.as_ptr(), ACL_FIRST_ENTRY, &mut entry) } {
        0 => Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private state has an extended ACL entry",
        )),
        -1 => {
            let error = io::Error::last_os_error();
            // In Darwin, FIRST_ENTRY on a valid empty ACL returns -1/EINVAL;
            // success is 0, unlike the Linux ACL API's 1/0 convention.
            if error.raw_os_error() == Some(libc::EINVAL) {
                Ok(())
            } else {
                Err(error)
            }
        }
        _ => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Darwin ACL entry query returned an unexpected status",
        )),
    }
}

#[cfg(test)]
#[path = "macos_tests.rs"]
mod tests;
