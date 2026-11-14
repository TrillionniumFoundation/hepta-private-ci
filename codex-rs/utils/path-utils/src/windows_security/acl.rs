use std::io;
use std::mem::size_of;
use std::os::windows::io::BorrowedHandle;
use std::ptr;

use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::INHERIT_ONLY_ACE;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;

use super::CurrentIdentity;
use super::LocalDescriptor;
use super::Sid;
use super::invalid_security;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SecuritySnapshot {
    owner: Sid,
    dacl: Vec<u8>,
    control: u16,
}

pub(crate) fn private_security(
    handle: BorrowedHandle<'_>,
    identity: &CurrentIdentity,
) -> io::Result<SecuritySnapshot> {
    let descriptor = LocalDescriptor::from_handle(
        handle,
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
    )?;
    let owner = descriptor.owner()?;
    // An elevated token may legitimately default to a privileged owner group.
    // Other shared-group owners can rewrite their DACL through implicit owner
    // rights, even when no allow ACE grants them access to the current contents.
    if owner != identity.user && (owner != identity.default_owner || !owner.privileged()) {
        return Err(invalid_security("state object has a different owner"));
    }
    let mut dacl = ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    // SAFETY: all outputs borrow this validated, live descriptor allocation.
    if unsafe {
        GetSecurityDescriptorDacl(descriptor.as_ptr(), &mut present, &mut dacl, &mut defaulted)
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if present == 0 || dacl.is_null() {
        return Err(invalid_security("state object has no restrictive DACL"));
    }
    // SAFETY: dacl points inside the live descriptor above.
    if unsafe { IsValidAcl(dacl) } == 0 {
        return Err(invalid_security("state object has an invalid DACL"));
    }
    let mut sizes = ACL_SIZE_INFORMATION::default();
    // SAFETY: the output struct has its declared size and the ACL is valid.
    if unsafe {
        GetAclInformation(
            dacl,
            (&raw mut sizes).cast(),
            size_of::<ACL_SIZE_INFORMATION>() as u32,
            AclSizeInformation,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if !(size_of::<ACL>()..=usize::from(u16::MAX)).contains(&(sizes.AclBytesInUse as usize)) {
        return Err(invalid_security("state DACL exceeds its bounds"));
    }
    // SAFETY: GetAclInformation reported initialized bytes of a valid ACL in
    // the descriptor. Copy them before releasing its OS allocation.
    let bytes = unsafe { std::slice::from_raw_parts(dacl.cast(), sizes.AclBytesInUse as usize) };
    let mut offset = size_of::<ACL>();
    for _ in 0..sizes.AceCount {
        let header = bytes
            .get(offset..offset + 4)
            .ok_or_else(|| invalid_security("truncated state ACE"))?;
        let length = usize::from(u16::from_le_bytes([header[2], header[3]]));
        if length < 8 {
            return Err(invalid_security("state ACE is too short"));
        }
        let ace = bytes
            .get(offset..offset + length)
            .ok_or_else(|| invalid_security("state ACE exceeds its ACL"))?;
        match header[0] {
            // Basic ACCESS_ALLOWED_ACE: the SID follows its header and mask.
            0 => {
                let trustee = Sid::from_bytes(&ace[8..])?;
                // An inherit-only ACE grants nothing on this object. Every
                // child created by this API receives its own protected DACL.
                if u32::from(header[1]) & INHERIT_ONLY_ACE == 0
                    && trustee != identity.user
                    && !trustee.privileged()
                {
                    return Err(invalid_security(
                        "state DACL grants another principal access",
                    ));
                }
            }
            // Deny ACEs cannot widen access; still validate their complete SID.
            1 => {
                Sid::from_bytes(&ace[8..])?;
            }
            _ => return Err(invalid_security("unsupported state DACL ACE")),
        }
        offset += length;
    }
    if offset != bytes.len() {
        return Err(invalid_security("state DACL length is inconsistent"));
    }
    let mut control = 0;
    let mut revision = 0;
    // SAFETY: the descriptor is live and both scalar outputs are writable.
    if unsafe { GetSecurityDescriptorControl(descriptor.as_ptr(), &mut control, &mut revision) }
        == 0
    {
        return Err(io::Error::last_os_error());
    }
    if revision != 1 {
        return Err(invalid_security("unsupported security descriptor revision"));
    }
    Ok(SecuritySnapshot {
        owner,
        dacl: bytes.to_vec(),
        control,
    })
}
