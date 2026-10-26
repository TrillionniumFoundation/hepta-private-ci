use crate::logging;
#[path = "desktop_capability.rs"]
mod capability;
use crate::token::get_current_token_for_restriction;
use crate::token::get_logon_sid_bytes;
use crate::winutil::format_last_error;
use crate::winutil::to_wide;
use anyhow::Result;
pub use capability::DesktopCapability;
use rand::RngCore;
use rand::rngs::OsRng;
#[path = "desktop_acl.rs"]
mod native_acl;
use native_acl::DesktopAcl;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::CopySid;
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

const DESKTOP_PROCESS_ACCESS: u32 = DESKTOP_READOBJECTS
    | DESKTOP_CREATEWINDOW
    | DESKTOP_CREATEMENU
    | DESKTOP_ENUMERATE
    | DESKTOP_WRITEOBJECTS
    | DESKTOP_READ_CONTROL;

pub struct LaunchDesktop {
    _private_desktop: Option<PrivateDesktop>,
    startup_name: Vec<u16>,
}

impl LaunchDesktop {
    /// Requires the exact independent session role in the actual restricted
    /// token. Filesystem SIDs are never promoted into desktop authority.
    pub(crate) fn prepare_for_capability(
        h_token: HANDLE,
        capability: &DesktopCapability,
        logs_base_dir: Option<&Path>,
    ) -> Result<Self> {
        let subjects = unsafe { private_desktop_restricting_sids(h_token)? };
        let sid = capability.as_sid();
        let length = unsafe { GetLengthSid(sid.as_ptr()) } as usize;
        let bytes = unsafe { std::slice::from_raw_parts(sid.as_ptr().cast::<u8>(), length) };
        anyhow::ensure!(
            subjects.iter().any(|subject| subject == bytes),
            "token lacks this launch's independent desktop capability"
        );
        let ordinary_logon = unsafe { get_logon_sid_bytes(h_token)? };
        let private_desktop = PrivateDesktop::create_with_subjects(
            vec![bytes.to_vec(), ordinary_logon],
            DESKTOP_PROCESS_ACCESS,
            logs_base_dir,
        )?;
        Ok(Self {
            startup_name: to_wide(format!("Winsta0\\{}", private_desktop.name)),
            _private_desktop: Some(private_desktop),
        })
    }

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
        let token = unsafe { get_current_token_for_restriction()? };
        let logon_sid = unsafe { get_logon_sid_bytes(token) };
        unsafe { CloseHandle(token) };
        let mut subjects = restricting_sids;
        subjects.push(logon_sid?);
        Self::create_with_subjects(subjects, DESKTOP_ALL_ACCESS, logs_base_dir)
    }

    fn create_with_subjects(
        subjects: Vec<Vec<u8>>,
        subject_access: u32,
        logs_base_dir: Option<&Path>,
    ) -> Result<Self> {
        let mut bytes = [0u8; 16];
        OsRng.try_fill_bytes(&mut bytes)?;
        let name = format!("CodexSandboxDesktop-{:032x}", u128::from_le_bytes(bytes));
        let mut acl = DesktopAcl::new(subjects, subject_access)?;
        let attributes = acl.attributes();
        let name_wide = to_wide(&name);
        let handle = unsafe {
            CreateDesktopW(
                name_wide.as_ptr(),
                ptr::null(),
                ptr::null_mut(),
                0,
                subject_access,
                &attributes,
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

        if let Err(error) = acl.verify(handle) {
            unsafe { CloseDesktop(handle) };
            return Err(error);
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
    if needed < std::mem::size_of::<TOKEN_GROUPS>() as u32 || needed > 16 * 1024 {
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
    anyhow::ensure!(
        groups.GroupCount > 0 && groups.GroupCount <= 128,
        "sandbox token restricting SID count exceeds launch bound"
    );
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
