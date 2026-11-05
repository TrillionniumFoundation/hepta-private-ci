//! Read-only native observations for the two original delete regressions.
//! These probes never grant an ACE, change a token policy, or replace an assertion.

use super::*;
use crate::acl::fetch_dacl_handle;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Storage::FileSystem::*;

#[path = "token_access_check_diagnostics_tests.rs"]
mod access_check;

struct Impersonation;

impl Impersonation {
    fn enter(token: HANDLE) -> Result<Self> {
        // SAFETY: callers retain this token for the entire observation scope.
        if unsafe { ImpersonateLoggedOnUser(token) } == 0 {
            return Err(anyhow!("diagnostic impersonation failed"));
        }
        Ok(Self)
    }
}

impl Drop for Impersonation {
    fn drop(&mut self) {
        // SAFETY: this guard owns the current thread's diagnostic impersonation.
        if unsafe { RevertToSelf() } == 0 {
            std::process::abort();
        }
    }
}

fn owned_token(raw: HANDLE) -> OwnedHandle {
    // SAFETY: only a successful token factory's newly owned handle is passed here.
    unsafe { OwnedHandle::from_raw_handle(raw as _) }
}

fn normal_filtered_token(base: HANDLE) -> Result<OwnedHandle> {
    let mut raw = 0;
    // SAFETY: base is live; all zero-length lists have null pointers. This creates
    // a diagnostic token with the production normal-SID filtering, without the
    // second restricting-SID check. It is used only to open owned fixture objects.
    if unsafe {
        CreateRestrictedToken(
            base,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            0,
            std::ptr::null(),
            0,
            std::ptr::null(),
            0,
            std::ptr::null(),
            &mut raw,
        )
    } == 0
    {
        return Err(anyhow!("diagnostic normal-filter token failed"));
    }
    let token = owned_token(raw);
    // SAFETY: this is the same single privilege used by the production factory.
    unsafe { enable_single_privilege(token.as_raw_handle() as _, "SeChangeNotifyPrivilege")? };
    Ok(token)
}

fn describe_acl(label: &str, path: &Path, known: &[(&str, *mut c_void)]) -> Result<()> {
    // SAFETY: the caller supplies only paths in this test's owned fixture.
    let (acl, descriptor) =
        unsafe { fetch_dacl_handle(path) }.map_err(|_| anyhow!("diagnostic ACL read failed"))?;
    let result = (|| {
        if acl.is_null() || unsafe { IsValidAcl(acl) } == 0 {
            return Err(anyhow!("diagnostic ACL invalid"));
        }
        // SAFETY: the kernel-owned descriptor retains this validated ACL.
        for index in 0..unsafe { (*acl).AceCount } {
            let mut raw = std::ptr::null_mut();
            if unsafe { GetAce(acl, u32::from(index), &mut raw) } == 0 || raw.is_null() {
                return Err(anyhow!("diagnostic ACE read failed"));
            }
            // SAFETY: GetAce returned an ACE in the validated live ACL.
            let header = unsafe { &*raw.cast::<ACE_HEADER>() };
            if header.AceType > 1
                || usize::from(header.AceSize) < std::mem::size_of::<ACCESS_ALLOWED_ACE>()
            {
                eprintln!(
                    "delete-native object={label} ace={index} type={} flags={} mask=unavailable",
                    header.AceType, header.AceFlags
                );
                continue;
            }
            let sid_offset = std::mem::offset_of!(ACCESS_ALLOWED_ACE, SidStart);
            if usize::from(header.AceSize) < sid_offset + 8 {
                return Err(anyhow!("diagnostic ACE SID header truncated"));
            }
            // SAFETY: the complete eight-byte SID header was bounded above.
            let count = unsafe { *raw.cast::<u8>().add(sid_offset + 1) };
            if usize::from(header.AceSize) < sid_offset + 8 + usize::from(count) * 4 {
                return Err(anyhow!("diagnostic ACE SID body truncated"));
            }
            // Allow and deny ACEs use the same header/mask/SID layout.
            let ace = unsafe { &*raw.cast::<ACCESS_ALLOWED_ACE>() };
            let sid = std::ptr::from_ref(&ace.SidStart).cast_mut().cast();
            if unsafe { IsValidSid(sid) } == 0 {
                return Err(anyhow!("diagnostic ACE SID invalid"));
            }
            let matches: Vec<&str> = known
                .iter()
                .filter_map(|(name, candidate)| {
                    // SAFETY: both SIDs are validated and retained by this call.
                    (unsafe { EqualSid(sid, *candidate) } != 0).then_some(*name)
                })
                .collect();
            eprintln!(
                "delete-native object={label} ace={index} type={} flags={} mask={:#x} identities={matches:?}",
                header.AceType, header.AceFlags, ace.Mask
            );
        }
        Ok(())
    })();
    // SAFETY: fetch_dacl_handle transfers this single LocalAlloc descriptor.
    if !descriptor.is_null() {
        unsafe { LocalFree(descriptor as HLOCAL) };
    }
    result
}

pub(crate) fn observe(
    base: HANDLE,
    restricted: HANDLE,
    paths: &[(&str, &Path)],
    caps: &[&LocalSid],
) -> Result<()> {
    // SAFETY: the supplied base token and copied SID buffers stay live below.
    let mut user = unsafe { get_user_sid_bytes(base)? };
    let mut logon = unsafe { get_logon_sid_bytes(base)? };
    let mut everyone = unsafe { world_sid()? };
    let administrators = LocalSid::from_string("S-1-5-32-544")?;
    let system = LocalSid::from_string("S-1-5-18")?;
    let cap_names: Vec<String> = (0..caps.len()).map(|index| format!("cap{index}")).collect();
    let mut known = vec![
        ("user", user.as_mut_ptr().cast()),
        ("logon", logon.as_mut_ptr().cast()),
        ("everyone", everyone.as_mut_ptr().cast()),
        ("administrators", administrators.as_ptr()),
        ("system", system.as_ptr()),
    ];
    known.extend(
        cap_names
            .iter()
            .zip(caps)
            .map(|(name, sid)| (name.as_str(), sid.as_ptr())),
    );
    let mut observations = Vec::new();
    for &(label, path) in paths {
        describe_acl(label, path, &known)?;
        observations.push((label, path, path.is_dir()));
    }
    let normal = normal_filtered_token(base)?;
    for (token_label, token) in [
        ("base", base),
        ("normal-filtered", normal.as_raw_handle() as _),
        ("production-restricted", restricted),
    ] {
        let _impersonation = Impersonation::enter(token)?;
        for &(label, path, is_directory) in &observations {
            for (access_label, mask) in [
                ("read", FILE_READ_DATA),
                ("write", FILE_WRITE_DATA),
                ("delete", DELETE),
                ("delete-child", FILE_DELETE_CHILD),
            ] {
                if access_label == "delete-child" && !is_directory {
                    continue;
                }
                // Existing-object opens only: no write, truncate, disposition,
                // rename, ACL mutation or child process occurs in this probe.
                let result = OpenOptions::new()
                    .access_mode(mask)
                    .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
                    .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
                    .open(path);
                let errno = result.as_ref().err().and_then(std::io::Error::raw_os_error);
                eprintln!(
                    "delete-native token={token_label} object={label} access={access_label} success={} errno={errno:?}",
                    result.is_ok()
                );
            }
        }
    }
    access_check::observe(base, restricted, paths)?;
    Ok(())
}

pub(crate) fn observe_legacy(
    codex_home: &Path,
    workspace: &Path,
    roots: &[&Path],
    paths: &[(&str, &Path)],
) -> Result<()> {
    // Read the exact already-persisted identities; never create or repair one.
    let bytes = std::fs::read(crate::cap::cap_sid_file(codex_home))?;
    let retained: crate::cap::CapSids = serde_json::from_slice(&bytes)?;
    let workspace_key = crate::path_normalization::canonical_path_key(workspace);
    let mut caps = Vec::new();
    for root in roots {
        let key = crate::path_normalization::canonical_path_key(root);
        let source = if key == workspace_key {
            &retained.workspace_by_cwd
        } else {
            &retained.writable_root_by_path
        };
        let sid = source
            .get(&key)
            .ok_or_else(|| anyhow!("diagnostic retained cap missing"))?;
        caps.push(LocalSid::from_string(sid)?);
    }
    let pointers: Vec<_> = caps.iter().map(LocalSid::as_ptr).collect();
    // SAFETY: these owned handles and SIDs are retained through observe. This
    // reconstructs the same factory inputs after the original child has exited;
    // it does not claim to inspect that child's token or execute its command.
    let base = owned_token(unsafe { get_current_token_for_restriction()? });
    let restricted = owned_token(unsafe {
        create_workspace_write_token_with_caps_from(base.as_raw_handle() as _, &pointers)?
    });
    observe(
        base.as_raw_handle() as _,
        restricted.as_raw_handle() as _,
        paths,
        &caps.iter().collect::<Vec<_>>(),
    )
}
