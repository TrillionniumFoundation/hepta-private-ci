use crate::private_object_capabilities::private_object_capabilities;
use crate::token::get_current_token_for_restriction;
use crate::token::get_logon_sid_bytes;
use anyhow::Result;
use std::marker::PhantomData;
use std::ptr;
use std::rc::Rc;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::InitializeSecurityDescriptor;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SetSecurityDescriptorDacl;
use windows_sys::Win32::System::StationsAndDesktops::CloseWindowStation;
use windows_sys::Win32::System::StationsAndDesktops::CreateWindowStationW;
use windows_sys::Win32::System::StationsAndDesktops::GetProcessWindowStation;
use windows_sys::Win32::System::StationsAndDesktops::GetUserObjectInformationW;
use windows_sys::Win32::System::StationsAndDesktops::SetProcessWindowStation;
use windows_sys::Win32::System::StationsAndDesktops::UOI_NAME;

const STANDARD_RIGHTS_REQUIRED: u32 = 0x000f_0000;
const SECURITY_DESCRIPTOR_REVISION: u32 = 1;
// These winuser.h constants are not exported by windows-sys 0.52.
const CWF_CREATE_ONLY: u32 = 0x0000_0001;
const WINSTA_ALL_ACCESS: u32 = 0x0000_037f;

/// Retains the private station used by one isolated command-runner process.
///
/// This is process-global state and deliberately cannot be sent to another
/// thread. The runner keeps it alive until the child and its private desktop
/// have finished. No access is added to the interactive Winsta0 station.
pub struct RunnerWindowStation {
    previous: isize,
    handle: isize,
    _isolated_runner: PhantomData<Rc<()>>,
}

impl RunnerWindowStation {
    /// Creates a fresh station for a fully restricted workspace child.
    ///
    /// # Safety
    /// Call only in the isolated command-runner process, before starting worker
    /// threads or creating any child. `token` must be a valid queryable token.
    pub unsafe fn prepare(token: HANDLE) -> Result<Option<Self>> {
        let mut sids = unsafe { private_object_capabilities(token)? };
        if sids.is_empty() {
            return Ok(None);
        }
        let base = unsafe { get_current_token_for_restriction()? };
        let logon = unsafe { get_logon_sid_bytes(base) };
        unsafe {
            CloseHandle(base);
        }
        sids.push(logon?);
        let entries: Vec<EXPLICIT_ACCESS_W> = sids
            .iter_mut()
            .map(|sid| EXPLICIT_ACCESS_W {
                grfAccessPermissions: WINSTA_ALL_ACCESS | STANDARD_RIGHTS_REQUIRED,
                grfAccessMode: GRANT_ACCESS,
                grfInheritance: 0,
                Trustee: TRUSTEE_W {
                    pMultipleTrustee: ptr::null_mut(),
                    MultipleTrusteeOperation: 0,
                    TrusteeForm: TRUSTEE_IS_SID,
                    TrusteeType: TRUSTEE_IS_UNKNOWN,
                    ptstrName: sid.as_mut_ptr().cast(),
                },
            })
            .collect();
        let mut acl = ptr::null_mut();
        let status = unsafe {
            SetEntriesInAclW(
                entries.len().try_into()?,
                entries.as_ptr(),
                ptr::null_mut(),
                &mut acl,
            )
        };
        anyhow::ensure!(
            status == ERROR_SUCCESS,
            "private station ACL failed: {status}"
        );
        let create = || -> Result<Self> {
            let previous = unsafe { GetProcessWindowStation() };
            anyhow::ensure!(
                previous != 0,
                "GetProcessWindowStation failed: {}",
                unsafe { GetLastError() }
            );
            let mut descriptor: SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
            anyhow::ensure!(
                unsafe {
                    InitializeSecurityDescriptor(
                        std::ptr::addr_of_mut!(descriptor).cast(),
                        SECURITY_DESCRIPTOR_REVISION,
                    )
                } != 0,
                "InitializeSecurityDescriptor for private station failed: {}",
                unsafe { GetLastError() }
            );
            anyhow::ensure!(
                unsafe {
                    SetSecurityDescriptorDacl(
                        std::ptr::addr_of_mut!(descriptor).cast(),
                        /*bdaclpresent*/ 1,
                        acl,
                        /*bdacldefaulted*/ 0,
                    )
                } != 0,
                "SetSecurityDescriptorDacl for private station failed: {}",
                unsafe { GetLastError() }
            );
            let attributes = SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: std::ptr::addr_of_mut!(descriptor).cast(),
                bInheritHandle: 0,
            };
            // A non-administrator cannot choose a station name. NULL asks Windows
            // to use this runner's logon identity; CREATE_ONLY rejects any existing
            // object rather than trusting or changing its ACL.
            let handle = unsafe {
                CreateWindowStationW(
                    ptr::null(),
                    CWF_CREATE_ONLY,
                    WINSTA_ALL_ACCESS | STANDARD_RIGHTS_REQUIRED,
                    &attributes,
                )
            };
            anyhow::ensure!(
                handle != 0,
                "create fresh private window station failed: {}",
                unsafe { GetLastError() }
            );
            if unsafe { SetProcessWindowStation(handle) } == 0 {
                let error = std::io::Error::last_os_error();
                unsafe {
                    CloseWindowStation(handle);
                }
                return Err(error.into());
            }
            Ok(Self {
                previous,
                handle,
                _isolated_runner: PhantomData,
            })
        };
        let result = create();
        unsafe {
            LocalFree(acl as HLOCAL);
        }
        result.map(Some)
    }
}

impl Drop for RunnerWindowStation {
    fn drop(&mut self) {
        // This isolated runner exits after the child. On an OS cleanup failure,
        // retain the still-associated station rather than closing the wrong object.
        if unsafe { SetProcessWindowStation(self.previous) } != 0 {
            unsafe {
                CloseWindowStation(self.handle);
            }
        } else {
            crate::logging::debug_log(
                &format!(
                    "restore runner window station failed: {}",
                    std::io::Error::last_os_error()
                ),
                /*logs_base_dir*/ None,
            );
        }
    }
}

pub(crate) fn current_window_station_name() -> Result<String> {
    let handle = unsafe { GetProcessWindowStation() };
    anyhow::ensure!(handle != 0, "GetProcessWindowStation failed: {}", unsafe {
        GetLastError()
    });
    let mut needed = 0;
    unsafe {
        GetUserObjectInformationW(
            handle,
            UOI_NAME,
            ptr::null_mut(),
            /*nlength*/ 0,
            &mut needed,
        );
    }
    anyhow::ensure!(
        needed >= 2 && needed % 2 == 0,
        "invalid private window station name size"
    );
    let mut name = vec![0u16; needed as usize / 2];
    anyhow::ensure!(
        unsafe {
            GetUserObjectInformationW(
                handle,
                UOI_NAME,
                name.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } != 0,
        "GetUserObjectInformationW station name failed: {}",
        unsafe { GetLastError() }
    );
    anyhow::ensure!(
        name.last() == Some(&0),
        "window station name is not terminated"
    );
    name.pop();
    Ok(String::from_utf16(&name)?)
}
