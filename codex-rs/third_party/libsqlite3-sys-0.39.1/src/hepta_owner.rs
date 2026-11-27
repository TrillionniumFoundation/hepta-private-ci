//! Explicit creation ownership for the bundled Windows VFS.
//!
//! This does not authenticate a database pathname, a recovery image, or a writer
//! fence. Storage owners must retain their independent identity checks.

use core::ffi::CStr;
use core::ffi::c_int;

#[cfg(hepta_owner_vfs)]
unsafe extern "C" {
    fn sqlite3_hepta_win32_owner_vfs(name: *mut *const core::ffi::c_char) -> c_int;
}

/// Return a non-default VFS bound to the calling thread's effective TokenUser.
///
/// The native implementation retains at most 64 immutable owner policies for
/// the process lifetime. Existing policies are reused, including across pooled
/// connections. Failure must be propagated without selecting a stock VFS.
/// Linked/system SQLite and SQLCipher do not implement this private extension.
pub fn hepta_win32_owner_vfs_name() -> Result<&'static CStr, c_int> {
    #[cfg(hepta_owner_vfs)]
    {
        let mut name = core::ptr::null();
        // SAFETY: The output points to a retained native context. On failure
        // the C function leaves it NULL; no borrowed caller allocation escapes.
        let code = unsafe { sqlite3_hepta_win32_owner_vfs(&mut name) };
        if code != crate::SQLITE_OK {
            return Err(code);
        }
        if name.is_null() {
            return Err(crate::SQLITE_INTERNAL);
        }
        // SAFETY: Successful registration returns a NUL-terminated name whose
        // native storage is retained for the entire process lifetime.
        Ok(unsafe { CStr::from_ptr(name) })
    }
    #[cfg(not(hepta_owner_vfs))]
    {
        Err(crate::SQLITE_NOTFOUND)
    }
}
