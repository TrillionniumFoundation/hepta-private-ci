//! Independent native security observations and creation-time owner fixtures.
//! These helpers neither use the production ACL validator nor change tokens or
//! the security of an existing object. Raw SIDs are never logged.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use std::ptr;

use windows_sys::Win32::Foundation::GENERIC_READ;
use windows_sys::Win32::Foundation::GENERIC_WRITE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::INHERITED_ACE;
use windows_sys::Win32::Security::InitializeSecurityDescriptor;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SetSecurityDescriptorOwner;
use windows_sys::Win32::Storage::FileSystem::CREATE_NEW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::System::SystemServices::SECURITY_DESCRIPTOR_REVISION;

pub(super) struct FileSecurity {
    descriptor: *mut c_void,
    owner: PSID,
    acl: *mut ACL,
    control: u16,
}

impl Drop for FileSecurity {
    fn drop(&mut self) {
        // SAFETY: GetSecurityInfo owns all referenced components in this allocation.
        unsafe { LocalFree(self.descriptor) };
    }
}

impl FileSecurity {
    pub(super) fn read(file: &File) -> io::Result<Self> {
        let mut value = Self {
            descriptor: ptr::null_mut(),
            owner: ptr::null_mut(),
            acl: ptr::null_mut(),
            control: 0,
        };
        // SAFETY: The handle and output pointers remain live. The descriptor
        // allocation owns the returned owner and ACL until this value drops.
        let status = unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as _,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut value.owner,
                ptr::null_mut(),
                &mut value.acl,
                ptr::null_mut(),
                &mut value.descriptor,
            )
        };
        if status != 0 {
            return Err(io::Error::from_raw_os_error(status as i32));
        }
        // SAFETY: All non-null components below belong to the live OS allocation.
        if unsafe {
            value.descriptor.is_null()
                || value.owner.is_null()
                || value.acl.is_null()
                || IsValidSid(value.owner) == 0
                || IsValidAcl(value.acl) == 0
        } {
            return Err(io::Error::other("invalid native fixture security"));
        }
        let mut revision = 0;
        // SAFETY: The security descriptor is retained and output storage is live.
        if unsafe {
            GetSecurityDescriptorControl(value.descriptor, &mut value.control, &mut revision)
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(value)
    }

    pub(super) fn same_owner(&self, other: &Self) -> bool {
        // SAFETY: Both SIDs were validated and are retained by their descriptors.
        unsafe { EqualSid(self.owner, other.owner) != 0 }
    }

    pub(super) fn unchanged(&self, after: &Self) -> bool {
        // SAFETY: IsValidAcl checked each live OS-allocated ACL and its length.
        let bytes = |value: &Self| unsafe {
            std::slice::from_raw_parts(value.acl.cast::<u8>(), (*value.acl).AclSize as usize)
        };
        self.same_owner(after) && self.control == after.control && bytes(self) == bytes(after)
    }

    pub(super) fn has_inherited_owner_ace(&self, expected: &Self) -> bool {
        // SAFETY: The ACL is validated and kept alive by this descriptor.
        if self.control & SE_DACL_PROTECTED != 0 || unsafe { (*self.acl).AceCount } != 1 {
            return false;
        }
        let mut raw = ptr::null_mut();
        // SAFETY: The ACL has one entry and the output pointer is live.
        if unsafe { GetAce(self.acl, 0, &mut raw) } == 0 || raw.is_null() {
            return false;
        }
        // SAFETY: GetAce returns a live ACE within the validated ACL.
        unsafe {
            let header = &*raw.cast::<ACE_HEADER>();
            let sid_offset = offset_of!(ACCESS_ALLOWED_ACE, SidStart);
            if header.AceType != 0
                || header.AceFlags != INHERITED_ACE as u8
                || (header.AceSize as usize) < sid_offset + 8
            {
                return false;
            }
            let ace = &*raw.cast::<ACCESS_ALLOWED_ACE>();
            let sid = ptr::addr_of!(ace.SidStart).cast::<u8>();
            let sid_size = 8 + usize::from(*sid.add(1)) * 4;
            sid_offset + sid_size <= header.AceSize as usize
                && IsValidSid(sid.cast_mut().cast()) != 0
                && EqualSid(sid.cast_mut().cast(), expected.owner) != 0
                && ace.Mask == FILE_ALL_ACCESS
        }
    }

    pub(super) fn create_with_inherited_dacl(&self, path: &Path) -> io::Result<File> {
        // An absolute descriptor with an explicit owner but no DACL_PRESENT
        // uses the parent's inheritable DACL. This is not an explicit NULL DACL.
        // SAFETY: Zero is a valid initial representation before initialization.
        let mut descriptor: SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
        let descriptor_ptr = (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast();
        // SAFETY: Storage is correctly sized; the owner SID remains live in self.
        if unsafe { InitializeSecurityDescriptor(descriptor_ptr, SECURITY_DESCRIPTOR_REVISION) }
            == 0
            || unsafe { SetSecurityDescriptorOwner(descriptor_ptr, self.owner, 0) } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let attributes = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: descriptor_ptr,
            bInheritHandle: 0,
        };
        let mut name: Vec<u16> = path.as_os_str().encode_wide().collect();
        if name.contains(&0) {
            return Err(io::Error::other("fixture name contains NUL"));
        }
        name.push(0);
        // SAFETY: Only a new synthetic fixture can be created. The descriptor,
        // referenced owner, attributes, and terminated path live for this call.
        let handle = unsafe {
            CreateFileW(
                name.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                &attributes,
                CREATE_NEW,
                FILE_ATTRIBUTE_NORMAL,
                0,
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: A successful CreateFileW returns a new owned handle.
        Ok(unsafe { File::from_raw_handle(handle as _) })
    }
}
