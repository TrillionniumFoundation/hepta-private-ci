use crate::acl::fetch_dacl_handle;
use crate::token::LocalSid;
use anyhow::Result;
use anyhow::anyhow;
use std::ffi::c_void;
use std::path::Path;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;

/// Record Windows' stored ACE representation without changing the fixture ACL.
pub(super) fn trace_acl(stage: &str, path: &Path, capability: &LocalSid) -> Result<()> {
    // SAFETY: the fixture exists. The security descriptor owns the ACL until
    // LocalFree below; GetAce returns entries inside that live descriptor.
    unsafe {
        let (dacl, descriptor) = fetch_dacl_handle(path)?;
        let result = (|| -> Result<()> {
            let mut control = 0_u16;
            let mut revision = 0_u32;
            if GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) == 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            if dacl.is_null() {
                return Err(anyhow!("{stage}: fixture has a null DACL"));
            }
            let mut info: ACL_SIZE_INFORMATION = std::mem::zeroed();
            if GetAclInformation(
                dacl,
                (&mut info as *mut ACL_SIZE_INFORMATION).cast(),
                std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            ) == 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            eprintln!("acl stage={stage} path={path:?} control={control:#06x} revision={revision} entries={}", info.AceCount);
            let mapping = GENERIC_MAPPING {
                GenericRead: FILE_GENERIC_READ,
                GenericWrite: FILE_GENERIC_WRITE,
                GenericExecute: FILE_GENERIC_EXECUTE,
                GenericAll: FILE_ALL_ACCESS,
            };
            for index in 0..info.AceCount {
                let mut entry: *mut c_void = std::ptr::null_mut();
                if GetAce(dacl, index, &mut entry) == 0 {
                    return Err(std::io::Error::last_os_error().into());
                }
                let header = &*entry.cast::<ACE_HEADER>();
                if matches!(header.AceType, 0 | 1) {
                    // Allow and deny ACEs share this mask/SID layout. Object,
                    // callback, and unknown ACE types are only logged by header.
                    let ace = &*entry.cast::<ACCESS_ALLOWED_ACE>();
                    let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast();
                    let matches_capability = EqualSid(sid, capability.as_ptr()) != 0;
                    let mut mapped = ace.Mask;
                    MapGenericMask(&mut mapped, &mapping);
                    eprintln!("acl stage={stage} index={index} type={} flags={:#04x} size={} mask={:#010x} mapped={mapped:#010x} capability_match={matches_capability}", header.AceType, header.AceFlags, header.AceSize, ace.Mask);
                } else {
                    eprintln!("acl stage={stage} index={index} type={} flags={:#04x} size={} unparsed=true", header.AceType, header.AceFlags, header.AceSize);
                }
            }
            Ok(())
        })();
        LocalFree(descriptor as HLOCAL);
        result
    }
}
