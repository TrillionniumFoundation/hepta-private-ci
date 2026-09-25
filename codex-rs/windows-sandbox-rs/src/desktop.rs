use crate::logging;
use crate::token::get_current_token_for_restriction;
use crate::token::get_logon_sid_bytes;
use crate::winutil::format_last_error;
use crate::winutil::to_wide;
use anyhow::Result;
use rand::Rng;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use std::ffi::c_void;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::SE_WINDOW_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::System::StationsAndDesktops::CloseDesktop;
use windows_sys::Win32::System::StationsAndDesktops::CreateDesktopW;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_CREATEMENU;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_CREATEWINDOW;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_DELETE;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_ENUMERATE;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_HOOKCONTROL;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_JOURNALPLAYBACK;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_JOURNALRECORD;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_READ_CONTROL;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_READOBJECTS;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_SWITCHDESKTOP;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_WRITE_DAC;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_WRITE_OWNER;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_WRITEOBJECTS;

const DESKTOP_ALL_ACCESS: u32 = DESKTOP_READOBJECTS
    | DESKTOP_CREATEWINDOW
    | DESKTOP_CREATEMENU
    | DESKTOP_HOOKCONTROL
    | DESKTOP_JOURNALRECORD
    | DESKTOP_JOURNALPLAYBACK
    | DESKTOP_ENUMERATE
    | DESKTOP_WRITEOBJECTS
    | DESKTOP_SWITCHDESKTOP
    | DESKTOP_DELETE
    | DESKTOP_READ_CONTROL
    | DESKTOP_WRITE_DAC
    | DESKTOP_WRITE_OWNER;

pub struct LaunchDesktop {
    _private_desktop: Option<PrivateDesktop>,
    startup_name: Vec<u16>,
}

impl LaunchDesktop {
    pub fn prepare(
        h_token: HANDLE,
        use_private_desktop: bool,
        logs_base_dir: Option<&Path>,
    ) -> Result<Self> {
        let restricting_sids = unsafe { private_desktop_restricting_sids(h_token)? };
        if use_private_desktop {
            let private_desktop = PrivateDesktop::create(restricting_sids, logs_base_dir)?;
            let startup_name = to_wide(format!("Winsta0\\{}", private_desktop.name));
            Ok(Self {
                _private_desktop: Some(private_desktop),
                startup_name,
            })
        } else {
            if !restricting_sids.is_empty() {
                anyhow::bail!("capability-only workspace tokens require a private desktop");
            }
            Ok(Self {
                _private_desktop: None,
                startup_name: to_wide("Winsta0\\Default"),
            })
        }
    }

    pub fn startup_info_desktop(&self) -> *mut u16 {
        self.startup_name.as_ptr() as *mut u16
    }
}

struct PrivateDesktop {
    handle: isize,
    name: String,
}

impl PrivateDesktop {
    fn create(restricting_sids: Vec<Vec<u8>>, logs_base_dir: Option<&Path>) -> Result<Self> {
        let mut rng = SmallRng::from_entropy();
        let name = format!("CodexSandboxDesktop-{:x}", rng.r#gen::<u128>());
        let name_wide = to_wide(&name);
        let handle = unsafe {
            CreateDesktopW(
                name_wide.as_ptr(),
                ptr::null(),
                ptr::null_mut(),
                0,
                DESKTOP_ALL_ACCESS,
                ptr::null_mut(),
            )
        };
        if handle == 0 {
            let err = unsafe { GetLastError() } as i32;
            logging::debug_log(
                &format!(
                    "CreateDesktopW failed for {name}: {} ({})",
                    err,
                    format_last_error(err),
                ),
                logs_base_dir,
            );
            return Err(anyhow::anyhow!("CreateDesktopW failed: {err}"));
        }

        unsafe {
            if let Err(err) = grant_desktop_access(handle, restricting_sids, logs_base_dir) {
                let _ = CloseDesktop(handle);
                return Err(err);
            }
        }

        Ok(Self { handle, name })
    }
}

// Old readonly/elevated tokens can use their own Logon SID for the second access
// check. Only capability-only workspace tokens need additional private-object
// grants. Never copy the old token's World/route identity entries to a desktop.
unsafe fn private_desktop_restricting_sids(h_token: HANDLE) -> Result<Vec<Vec<u8>>> {
    let mut logon_sid = get_logon_sid_bytes(h_token)?;
    let mut needed = 0;
    GetTokenInformation(
        h_token,
        TokenRestrictedSids,
        ptr::null_mut(),
        0,
        &mut needed,
    );
    if needed < std::mem::size_of::<TOKEN_GROUPS>() as u32 {
        anyhow::bail!(
            "GetTokenInformation(TokenRestrictedSids) size query failed: {}",
            GetLastError()
        );
    }
    // TOKEN_GROUPS contains pointers, so its backing buffer must be aligned.
    let mut buffer = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    if GetTokenInformation(
        h_token,
        TokenRestrictedSids,
        buffer.as_mut_ptr().cast(),
        needed,
        &mut needed,
    ) == 0
    {
        anyhow::bail!(
            "GetTokenInformation(TokenRestrictedSids) failed: {}",
            GetLastError()
        );
    }
    let groups = &*buffer.as_ptr().cast::<TOKEN_GROUPS>();
    if groups.GroupCount == 0 {
        anyhow::bail!("sandbox token has no restricting SIDs");
    }
    let entries = std::slice::from_raw_parts(groups.Groups.as_ptr(), groups.GroupCount as usize);
    if entries
        .iter()
        .any(|entry| EqualSid(entry.Sid, logon_sid.as_mut_ptr().cast()) != 0)
    {
        return Ok(Vec::new());
    }
    entries
        .iter()
        .map(|entry| {
            let len = GetLengthSid(entry.Sid);
            let mut sid = vec![0u8; len as usize];
            if len == 0 || CopySid(len, sid.as_mut_ptr().cast(), entry.Sid) == 0 {
                anyhow::bail!("CopySid for private desktop failed: {}", GetLastError());
            }
            Ok(sid)
        })
        .collect()
}

unsafe fn grant_desktop_access(
    handle: isize,
    mut restricting_sids: Vec<Vec<u8>>,
    logs_base_dir: Option<&Path>,
) -> Result<()> {
    let token = get_current_token_for_restriction()?;
    let logon_sid = get_logon_sid_bytes(token);
    CloseHandle(token);
    restricting_sids.push(logon_sid?);

    let entries: Vec<EXPLICIT_ACCESS_W> = restricting_sids
        .iter_mut()
        .map(|sid| EXPLICIT_ACCESS_W {
            grfAccessPermissions: DESKTOP_ALL_ACCESS,
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: 0,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid.as_mut_ptr() as *mut c_void as *mut u16,
            },
        })
        .collect();

    let mut updated_dacl = ptr::null_mut();
    let set_entries_code = SetEntriesInAclW(
        entries.len() as u32,
        entries.as_ptr(),
        ptr::null_mut(),
        &mut updated_dacl,
    );
    if set_entries_code != ERROR_SUCCESS {
        logging::debug_log(
            &format!("SetEntriesInAclW failed for private desktop: {set_entries_code}"),
            logs_base_dir,
        );
        return Err(anyhow::anyhow!(
            "SetEntriesInAclW failed for private desktop: {set_entries_code}"
        ));
    }

    let set_security_code = SetSecurityInfo(
        handle,
        SE_WINDOW_OBJECT,
        DACL_SECURITY_INFORMATION,
        ptr::null_mut(),
        ptr::null_mut(),
        updated_dacl,
        ptr::null_mut(),
    );
    if !updated_dacl.is_null() {
        LocalFree(updated_dacl as HLOCAL);
    }
    if set_security_code != ERROR_SUCCESS {
        logging::debug_log(
            &format!("SetSecurityInfo failed for private desktop: {set_security_code}"),
            logs_base_dir,
        );
        return Err(anyhow::anyhow!(
            "SetSecurityInfo failed for private desktop: {set_security_code}"
        ));
    }

    Ok(())
}

impl Drop for PrivateDesktop {
    fn drop(&mut self) {
        unsafe {
            if self.handle != 0 {
                let _ = CloseDesktop(self.handle);
            }
        }
    }
}

#[cfg(test)]
#[path = "desktop_tests.rs"]
mod tests;
