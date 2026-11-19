//! Bounded root preparation, never full-disk-read or production launch authority.
use crate::FilesystemCapabilityPlan;
use crate::LocalSid;
use crate::filesystem_read_acl::HeldFilesystemReadAcl;
use crate::read_acl_query;
use crate::token::TokenBytes;
use anyhow::Result;
use anyhow::ensure;
use std::ffi::c_void;
use std::fs::File;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::DuplicateToken;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PRIVILEGE_SET;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

const RX: u32 = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE;
const QUERY: u32 = READ_CONTROL | FILE_READ_ATTRIBUTES | SYNCHRONIZE;
// Directory DELETE_CHILD would bypass a protected child's DELETE denial.
const WRITE: u32 = RX | FILE_GENERIC_WRITE | DELETE;

struct Allocation(*mut c_void);
impl Drop for Allocation {
    fn drop(&mut self) {
        // SAFETY: these allocations come only from security APIs using LocalAlloc.
        unsafe { LocalFree(self.0) };
    }
}

fn descriptor(file: &File) -> Result<(Allocation, Vec<u8>)> {
    let mut raw = std::ptr::null_mut();
    // SAFETY: the exact held object and complete outputs remain owned.
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut raw,
        )
    };
    let allocation = Allocation(raw);
    ensure!(
        code == 0 && !raw.is_null(),
        "root security query failed: {code}"
    );
    ensure!(unsafe { IsValidSecurityDescriptor(raw) } != 0);
    let length = unsafe { GetSecurityDescriptorLength(raw) } as usize;
    ensure!(
        (20..=65_536).contains(&length),
        "root descriptor exceeds bound"
    );
    // SAFETY: the OS returned a validated, initialized self-relative descriptor.
    let bytes = unsafe { std::slice::from_raw_parts(raw.cast::<u8>(), length) }.to_vec();
    Ok((allocation, bytes))
}

fn identity(file: &File) -> Result<(u32, u64)> {
    let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    ensure!(unsafe { GetFileInformationByHandle(file.as_raw_handle() as _, &mut info) } != 0);
    ensure!(info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | 0x40) == 0);
    Ok((
        info.dwVolumeSerialNumber,
        (u64::from(info.nFileIndexHigh) << 32) | u64::from(info.nFileIndexLow),
    ))
}

fn token_version(token: BorrowedHandle<'_>) -> Result<(u32, i32, u32, i32)> {
    let value = TokenBytes::query(token.as_raw_handle() as _, TokenStatistics)?
        .value::<TOKEN_STATISTICS>(/*offset*/ 0)?;
    Ok((
        value.TokenId.LowPart,
        value.TokenId.HighPart,
        value.ModifiedId.LowPart,
        value.ModifiedId.HighPart,
    ))
}

fn require_access(file: &File, token: BorrowedHandle<'_>, desired: u32) -> Result<()> {
    let (descriptor, _) = descriptor(file)?;
    let mut raw = 0;
    ensure!(
        unsafe { DuplicateToken(token.as_raw_handle() as _, SecurityImpersonation, &mut raw) } != 0
    );
    // SAFETY: DuplicateToken transferred exactly one owned handle.
    let impersonation = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut privileges: PRIVILEGE_SET = unsafe { std::mem::zeroed() };
    let mut length = size_of::<PRIVILEGE_SET>() as u32;
    let mut granted = 0;
    let mut allowed = 0;
    // SAFETY: live native descriptor, impersonation token and initialized outputs.
    ensure!(
        unsafe {
            AccessCheck(
                descriptor.0,
                impersonation.as_raw_handle() as _,
                desired,
                &mapping,
                &mut privileges,
                &mut length,
                &mut granted,
                &mut allowed,
            )
        } != 0,
        "root effective access query failed: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        allowed != 0 && granted & desired == desired && privileges.PrivilegeCount == 0,
        "root lacks required unprivileged effective access"
    );
    Ok(())
}

fn grant(file: &File, subject: &LocalSid, mask: u32) -> Result<()> {
    let mut raw_descriptor = std::ptr::null_mut();
    let mut previous = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut previous,
            std::ptr::null_mut(),
            &mut raw_descriptor,
        )
    };
    let _descriptor = Allocation(raw_descriptor);
    ensure!(code == 0 && !previous.is_null(), "refuse absent root DACL");
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: mask,
        grfAccessMode: GRANT_ACCESS,
        grfInheritance: if file.metadata()?.is_dir() {
            OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE
        } else {
            0
        },
        Trustee: TRUSTEE_W {
            TrusteeForm: TRUSTEE_IS_SID,
            ptstrName: subject.as_ptr() as _,
            ..unsafe { std::mem::zeroed() }
        },
    };
    let mut updated = std::ptr::null_mut();
    let code = unsafe {
        SetEntriesInAclW(
            /*ccountofexplicitentries*/ 1,
            &entry,
            previous,
            &mut updated,
        )
    };
    let _updated = Allocation(updated.cast());
    ensure!(
        code == 0 && !updated.is_null(),
        "root capability grant failed: {code}"
    );
    let code = unsafe {
        SetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            updated,
            std::ptr::null_mut(),
        )
    };
    ensure!(code == 0, "root capability ACL write failed: {code}");
    Ok(())
}

fn require_bounded_grant(file: &File, subject: &LocalSid, maximum: u32) -> Result<()> {
    let mut raw_descriptor = std::ptr::null_mut();
    let mut dacl: *mut ACL = std::ptr::null_mut();
    let mut owner = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            std::ptr::null_mut(),
            &mut dacl,
            std::ptr::null_mut(),
            &mut raw_descriptor,
        )
    };
    let _descriptor = Allocation(raw_descriptor);
    ensure!(code == 0 && !dacl.is_null() && !owner.is_null());
    ensure!(
        unsafe { EqualSid(owner, subject.as_ptr()) } == 0,
        "filesystem capability cannot own a prepared root"
    );
    let mut info: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    ensure!(
        unsafe {
            GetAclInformation(
                dacl,
                (&raw mut info).cast(),
                size_of::<ACL_SIZE_INFORMATION>() as _,
                AclSizeInformation,
            )
        } != 0
    );
    ensure!(info.AceCount <= 1024, "prepared root ACL exceeds bound");
    for index in 0..info.AceCount {
        let mut raw = std::ptr::null_mut();
        ensure!(unsafe { GetAce(dacl, index, &mut raw) } != 0 && !raw.is_null());
        let header = unsafe { &*raw.cast::<ACE_HEADER>() };
        ensure!(
            matches!(header.AceType, 0 | 1) && header.AceSize >= 16 && header.AceFlags & !0x1f == 0
        );
        let ace = unsafe { &*raw.cast::<ACCESS_ALLOWED_ACE>() };
        let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast::<c_void>();
        let count = unsafe { *sid.cast::<u8>().add(1) } as usize;
        ensure!(count <= 15 && 8 + 4 * count <= header.AceSize as usize - 8);
        ensure!(
            unsafe { IsValidSid(sid) } != 0
                && unsafe { GetLengthSid(sid) } as usize <= header.AceSize as usize - 8
        );
        if header.AceType == 0 && unsafe { EqualSid(sid, subject.as_ptr()) } != 0 {
            ensure!(
                ace.Mask & !maximum == 0,
                "prepared capability already has excess or generic rights"
            );
        }
    }
    Ok(())
}

struct HeldRoot {
    path: PathBuf,
    file: File,
    identity: (u32, u64),
    descriptor: Vec<u8>,
    access: u32,
}

/// Exact bounded root ACL preparation and normal/restricted effective readback.
///
/// This does not prove descendant ACLs, full-disk read semantics, PE/DLL loading,
/// registry or object namespace confinement. Production launch guards still apply.
pub(crate) struct PreparedFilesystemAclContext {
    home: PathBuf,
    plan: FilesystemCapabilityPlan,
    read: HeldFilesystemReadAcl,
    roots: Vec<HeldRoot>,
    base_version: (u32, i32, u32, i32),
    refused: bool,
}

impl PreparedFilesystemAclContext {
    pub(crate) fn prepare(
        home: &Path,
        plan: &FilesystemCapabilityPlan,
        base: BorrowedHandle<'_>,
    ) -> Result<Self> {
        crate::validate_filesystem_capability_plan(home, plan)?;
        let base_version = token_version(base)?;
        let declarations = plan
            .read_root_sids()
            .map(|(path, sid)| (path, sid, RX))
            .chain(plan.write_root_sids().map(|(path, sid)| (path, sid, WRITE)))
            .collect::<Vec<_>>();
        ensure!(!declarations.is_empty() && declarations.len() <= 128);
        let mut held = Vec::with_capacity(declarations.len());
        for (path, sid, access) in declarations {
            let path = PathBuf::from(path);
            let query = read_acl_query::open(&path)?;
            let before = identity(&query)?;
            require_access(&query, base, access)?;
            let writable = read_acl_query::open_with_access(&path, QUERY | WRITE_DAC)?;
            ensure!(
                identity(&writable)? == before,
                "root rebound before ACL preparation"
            );
            let subject = LocalSid::from_string(sid)?;
            require_bounded_grant(&writable, &subject, access)?;
            grant(&writable, &subject, access)?;
            require_bounded_grant(&writable, &subject, access)?;
            // Retain only query authority. Neither WRITE_DAC nor a root handle is inherited.
            let file = read_acl_query::open(&path)?;
            ensure!(identity(&file)? == before);
            held.push((path, file, before, access));
        }
        let read = crate::observe_filesystem_read_acl(home, plan)?;
        let roots = held
            .into_iter()
            .map(|(path, file, identity, access)| {
                let (_, descriptor) = descriptor(&file)?;
                Ok(HeldRoot {
                    path,
                    file,
                    identity,
                    descriptor,
                    access,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        let mut output = Self {
            home: home.to_owned(),
            plan: plan.clone(),
            read,
            roots,
            base_version,
            refused: false,
        };
        output.validate_for_token(base)?;
        Ok(output)
    }

    pub(crate) fn filesystem_sids(&self) -> Result<Vec<LocalSid>> {
        ensure!(
            !self.refused,
            "bounded filesystem preparation remains refused"
        );
        self.plan
            .read_sids()
            .chain(self.plan.write_sids())
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .map(LocalSid::from_string)
            .collect()
    }

    pub(crate) fn revalidate(&mut self) -> Result<()> {
        ensure!(
            !self.refused,
            "bounded filesystem preparation remains refused"
        );
        self.refused = true;
        self.read.revalidate(&self.home, &self.plan)?;
        for root in &self.roots {
            let named = read_acl_query::open(&root.path)?;
            ensure!(
                identity(&root.file)? == root.identity
                    && identity(&named)? == root.identity
                    && descriptor(&root.file)?.1 == root.descriptor
                    && descriptor(&named)?.1 == root.descriptor,
                "prepared root identity or descriptor changed"
            );
        }
        self.refused = false;
        Ok(())
    }

    pub(crate) fn validate_for_token(&mut self, base: BorrowedHandle<'_>) -> Result<()> {
        self.revalidate()?;
        self.refused = true;
        ensure!(
            token_version(base)? == self.base_version,
            "prepared roots belong to another base token"
        );
        for root in &self.roots {
            require_access(&root.file, base, root.access)?;
        }
        ensure!(
            token_version(base)? == self.base_version,
            "base token changed during access readback"
        );
        self.refused = false;
        Ok(())
    }

    pub(crate) fn require_token_access(&mut self, token: BorrowedHandle<'_>) -> Result<()> {
        self.revalidate()?;
        self.refused = true;
        for root in &self.roots {
            require_access(&root.file, token, root.access)?;
        }
        self.refused = false;
        Ok(())
    }
}

#[path = "prepared_filesystem_existing.rs"]
mod existing;

#[cfg(test)]
#[path = "prepared_filesystem_readback_tests.rs"]
mod readback_tests;
