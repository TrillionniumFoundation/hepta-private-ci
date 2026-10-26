//! Observation only, injected into the unchanged original native token case.
use serde_json::json;
use serde_json::Value;
use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Security::Authorization::*;
use windows_sys::Win32::Security::*;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::Threading::*;

struct LocalDescriptor(PSECURITY_DESCRIPTOR);
impl Drop for LocalDescriptor {
    fn drop(&mut self) {
        // SAFETY: GetNamedSecurityInfo returned this one owned LocalAlloc buffer.
        unsafe { LocalFree(self.0) };
    }
}

pub(super) fn record(
    allowed: &[PathBuf; 2],
    outside: &Path,
    sids: &[(&str, *mut c_void)],
) -> anyhow::Result<()> {
    let mut handle = 0;
    // SAFETY: only queries the actual active original test impersonation token.
    if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut handle) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let token = super::OwnedToken(handle);
    let memberships = sids
        .iter()
        .map(|(name, sid)| {
            // SAFETY: all supplied SIDs are retained by the unchanged original fixture.
            let present = unsafe { super::token_has_restricting_sid(token.0, *sid) };
            json!({"name":name,"present":present.ok()})
        })
        .collect::<Vec<_>>();
    let nodes = [
        ("outside-parent", outside.to_path_buf(), true),
        ("outside-file", outside.join("keep.txt"), false),
        ("outside-dir", outside.join("keep-dir"), true),
        (
            "fixture-parent",
            outside.parent().unwrap().to_path_buf(),
            true,
        ),
        ("allowed-workspace", allowed[0].clone(), true),
        (
            "allowed-workspace-file",
            allowed[0].join("delete.txt"),
            false,
        ),
        ("allowed-temp", allowed[1].clone(), true),
        ("allowed-temp-file", allowed[1].join("delete.txt"), false),
    ];
    let observed = nodes
        .iter()
        .map(
            |(role, path, directory)| match node(token.0, path, *directory) {
                Ok(value) => json!({"role":role,"observation":value}),
                Err(error) => json!({"role":role,"observationError":error.to_string()}),
            },
        )
        .collect::<Vec<_>>();
    eprintln!(
        "HEPTA_DELETE_FACTS={}",
        json!({
            "schema":"hepta.original-token-delete-observation.v1",
            "status":"OBSERVATION_ONLY",
            "effectiveOriginalThreadToken":true,
            "sourceFlags":"DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED",
            "restrictedSidMembership":memberships,
            "nodes":observed,
            "productionAuthorityGranted":false,
            "securityQualification":false
        })
    );
    Ok(())
}

fn node(token: HANDLE, path: &Path, directory: bool) -> anyhow::Result<Value> {
    let wide = path
        .as_os_str()
        .encode_wide()
        .chain([0])
        .collect::<Vec<_>>();
    let mut raw = std::ptr::null_mut();
    let info = OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    // SAFETY: terminated fixture path and initialized descriptor output remain live.
    let status = unsafe {
        GetNamedSecurityInfoW(
            wide.as_ptr(),
            SE_FILE_OBJECT,
            info,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut raw,
        )
    };
    anyhow::ensure!(
        status == ERROR_SUCCESS && !raw.is_null(),
        "GetNamedSecurityInfoW: {status}"
    );
    let descriptor = LocalDescriptor(raw);
    let sddl = descriptor_text(descriptor.0, info)?;
    let masks = [
        ("read-data/list-directory", FILE_READ_DATA),
        ("write-data/add-file", FILE_WRITE_DATA),
        ("append/add-subdirectory", FILE_APPEND_DATA),
        ("delete", DELETE),
        ("delete-plus-synchronize", DELETE | SYNCHRONIZE),
        ("delete-child", FILE_DELETE_CHILD),
        (
            "delete-child-plus-read-control",
            FILE_DELETE_CHILD | READ_CONTROL,
        ),
        ("generic-read", FILE_GENERIC_READ),
        ("generic-write", FILE_GENERIC_WRITE),
        ("full", FILE_ALL_ACCESS),
    ];
    let matrix = masks
        .iter()
        .map(|(label, mask)| {
            let access = access_check(descriptor.0, token, *mask);
            let flags = FILE_FLAG_OPEN_REPARSE_POINT
                | if directory {
                    FILE_FLAG_BACKUP_SEMANTICS
                } else {
                    0
                };
            // SAFETY: read-only admission probe: OPEN_EXISTING never creates, truncates,
            // marks delete-on-close or writes bytes. Every new successful handle closes.
            let file = unsafe {
                CreateFileW(
                    wide.as_ptr(),
                    *mask,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    std::ptr::null(),
                    OPEN_EXISTING,
                    flags,
                    0,
                )
            };
            let open = if file == INVALID_HANDLE_VALUE {
                json!({"opened":false,"error":std::io::Error::last_os_error().raw_os_error()})
            } else {
                // SAFETY: this one successful CreateFileW call owns the fresh handle.
                unsafe { CloseHandle(file) };
                json!({"opened":true,"error":null})
            };
            // SAFETY: same bounded OPEN_EXISTING admission, differing only in
            // backup-intent spelling used by some native deletion open paths.
            let backup_file = unsafe {
                CreateFileW(
                    wide.as_ptr(),
                    *mask,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    std::ptr::null(),
                    OPEN_EXISTING,
                    flags | FILE_FLAG_BACKUP_SEMANTICS,
                    0,
                )
            };
            let backup_open = if backup_file == INVALID_HANDLE_VALUE {
                json!({"opened":false,"error":std::io::Error::last_os_error().raw_os_error()})
            } else {
                // SAFETY: close exactly this newly opened admission-probe handle.
                unsafe { CloseHandle(backup_file) };
                json!({"opened":true,"error":null})
            };
            json!({"right":label,"requestedMask":mask,"accessCheck":access,
            "actualCreateFile":open,"actualCreateFileWithBackupIntent":backup_open})
        })
        .collect::<Vec<_>>();
    Ok(json!({"path":path,"directory":directory,"securityDescriptor":sddl,"matrix":matrix}))
}

fn access_check(descriptor: PSECURITY_DESCRIPTOR, token: HANDLE, mask: u32) -> Value {
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut privileges = [0u64; 256];
    let mut length = std::mem::size_of_val(&privileges) as u32;
    let mut granted = 0;
    let mut allowed = 0;
    // SAFETY: OS-owned descriptor, actual live impersonation token and aligned
    // bounded output buffers remain live throughout this pure access evaluation.
    let ok = unsafe {
        AccessCheck(
            descriptor,
            token,
            mask,
            &mapping,
            privileges.as_mut_ptr().cast(),
            &mut length,
            &mut granted,
            &mut allowed,
        )
    };
    json!({"apiOk":ok != 0,"allowed":allowed != 0,"grantedMask":granted,
        "error":if ok == 0 {std::io::Error::last_os_error().raw_os_error()} else {None}})
}

fn descriptor_text(descriptor: PSECURITY_DESCRIPTOR, information: u32) -> anyhow::Result<String> {
    let mut text = std::ptr::null_mut();
    let mut length = 0;
    // SAFETY: valid OS descriptor and initialized LocalAlloc string output.
    let ok = unsafe {
        ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            1,
            information,
            &mut text,
            &mut length,
        )
    };
    anyhow::ensure!(
        ok != 0 && !text.is_null() && length <= 65536,
        "convert bounded SDDL"
    );
    // SAFETY: successful API owns length UTF-16 code units in this returned buffer.
    let value =
        unsafe { String::from_utf16_lossy(std::slice::from_raw_parts(text, length as usize)) };
    // SAFETY: release exactly the allocated conversion string.
    unsafe { LocalFree(text.cast()) };
    Ok(value.trim_end_matches('\0').to_owned())
}
