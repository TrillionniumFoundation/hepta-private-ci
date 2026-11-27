//! Create-time desktop descriptors with exact native readback; no ACL repair.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_WINDOW_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::InitializeSecurityDescriptor;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SetSecurityDescriptorControl;
use windows_sys::Win32::Security::SetSecurityDescriptorDacl;

pub(super) struct DesktopAcl {
    acl: *mut ACL,
    descriptor: SECURITY_DESCRIPTOR,
}

impl DesktopAcl {
    pub(super) fn new(mut subjects: Vec<Vec<u8>>, access: u32) -> Result<Self> {
        let entries: Vec<_> = subjects
            .iter_mut()
            .map(|sid| EXPLICIT_ACCESS_W {
                grfAccessPermissions: access,
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
        let result = unsafe {
            SetEntriesInAclW(
                entries.len() as u32,
                entries.as_ptr(),
                ptr::null_mut(),
                &mut acl,
            )
        };
        ensure!(
            result == ERROR_SUCCESS,
            "create desktop DACL failed: {result}"
        );
        let mut value = Self {
            acl,
            descriptor: unsafe { std::mem::zeroed() },
        };
        let descriptor = ptr::addr_of_mut!(value.descriptor).cast();
        ensure!(
            unsafe {
                InitializeSecurityDescriptor(descriptor, /*dwrevision*/ 1)
            } != 0
        );
        ensure!(
            unsafe {
                SetSecurityDescriptorDacl(
                    descriptor, /*bdaclpresent*/ 1, acl, /*bdacldefaulted*/ 0,
                )
            } != 0
        );
        ensure!(
            unsafe {
                SetSecurityDescriptorControl(descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED)
            } != 0
        );
        Ok(value)
    }

    pub(super) fn attributes(&mut self) -> SECURITY_ATTRIBUTES {
        SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: ptr::addr_of_mut!(self.descriptor).cast(),
            bInheritHandle: 0,
        }
    }

    pub(super) fn verify(&self, desktop: isize) -> Result<()> {
        let mut observed = ptr::null_mut();
        let mut descriptor = ptr::null_mut();
        let code = unsafe {
            GetSecurityInfo(
                desktop,
                SE_WINDOW_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                &mut observed,
                ptr::null_mut(),
                &mut descriptor,
            )
        };
        let allocation = NativeDescriptor(descriptor as HLOCAL);
        ensure!(
            code == ERROR_SUCCESS && !observed.is_null() && !allocation.0.is_null(),
            "read desktop DACL failed: {code}"
        );
        let length = unsafe { GetSecurityDescriptorLength(descriptor) } as usize;
        let mut control = 0;
        let mut revision = 0;
        ensure!(
            unsafe { GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) } != 0
                && control & SE_DACL_PROTECTED != 0,
            "desktop DACL is not protected"
        );
        let offset = (observed as usize)
            .checked_sub(descriptor as usize)
            .context("desktop DACL precedes its retained descriptor")?;
        ensure!(
            length <= 16 * 1024
                && offset <= length
                && std::mem::size_of::<ACL>() <= length - offset,
            "desktop DACL readback is out of bounds"
        );
        let size = unsafe { (*observed).AclSize } as usize;
        ensure!(size >= std::mem::size_of::<ACL>() && size <= length - offset);
        let expected_size = unsafe { (*self.acl).AclSize } as usize;
        ensure!(
            size == expected_size
                && unsafe { std::slice::from_raw_parts(observed.cast::<u8>(), size) }
                    == unsafe { std::slice::from_raw_parts(self.acl.cast::<u8>(), expected_size) },
            "desktop DACL differs from this session; occupied names are never repaired"
        );
        Ok(())
    }
}

impl Drop for DesktopAcl {
    fn drop(&mut self) {
        unsafe { LocalFree(self.acl as HLOCAL) };
    }
}

struct NativeDescriptor(HLOCAL);

impl Drop for NativeDescriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { LocalFree(self.0) };
        }
    }
}
