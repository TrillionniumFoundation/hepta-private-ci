//! Creation-only Windows security descriptor with an explicit current-user owner.

use std::io;

use super::CurrentUser;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::AddAccessAllowedAceEx;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::InitializeSecurityDescriptor;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SetSecurityDescriptorControl;
use windows_sys::Win32::Security::SetSecurityDescriptorDacl;
use windows_sys::Win32::Security::SetSecurityDescriptorOwner;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;

// The owner SID and ACL storage stay alive through the creation call. An
// explicit owner avoids elevated tokens' Administrators default owner, while
// the protected DACL avoids any initially inherited public-access window.
pub(super) fn with_private_security<T>(
    create: impl FnOnce(&SECURITY_ATTRIBUTES) -> io::Result<T>,
) -> io::Result<T> {
    let current_user = CurrentUser::read()?;
    let sid_length = unsafe { GetLengthSid(current_user.sid()) } as usize;
    if sid_length == 0 {
        return Err(io::Error::last_os_error());
    }
    let acl_bytes = std::mem::size_of::<ACL>() + std::mem::size_of::<ACCESS_ALLOWED_ACE>()
        - std::mem::size_of::<u32>()
        + sid_length;
    let mut storage = vec![0_u32; acl_bytes.div_ceil(std::mem::size_of::<u32>())];
    let dacl = storage.as_mut_ptr().cast::<ACL>();
    if unsafe { InitializeAcl(dacl, acl_bytes as u32, ACL_REVISION) } == 0 {
        return Err(io::Error::last_os_error());
    }
    if unsafe {
        AddAccessAllowedAceEx(
            dacl,
            ACL_REVISION,
            OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
            FILE_ALL_ACCESS,
            current_user.sid(),
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let mut descriptor: SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
    let descriptor_ptr = (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast();
    if unsafe {
        InitializeSecurityDescriptor(descriptor_ptr, /*dwrevision*/ 1)
    } == 0
        || unsafe {
            SetSecurityDescriptorOwner(
                descriptor_ptr,
                current_user.sid(),
                /*bownerdefaulted*/ 0,
            )
        } == 0
        || unsafe {
            SetSecurityDescriptorDacl(
                descriptor_ptr,
                /*bdaclpresent*/ 1,
                dacl,
                /*bdacldefaulted*/ 0,
            )
        } == 0
        || unsafe {
            SetSecurityDescriptorControl(descriptor_ptr, SE_DACL_PROTECTED, SE_DACL_PROTECTED)
        } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor_ptr,
        bInheritHandle: 0,
    };
    create(&attributes)
}
