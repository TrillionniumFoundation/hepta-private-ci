//! Query-only RX-role observations, not prepared ACLs or sandbox admission.
use crate::FilesystemCapabilityPlan;
use crate::LocalSid;
use crate::read_acl_query;
use crate::read_role_descriptor;
use crate::read_role_descriptor::RootKind;
use anyhow::Result;
use anyhow::ensure;
use std::ffi::c_void;
use std::fs::File;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::System::Memory::LocalSize;

struct LocalDescriptor(*mut c_void);
impl Drop for LocalDescriptor {
    fn drop(&mut self) {
        // SAFETY: GetSecurityInfo transfers one LocalAlloc allocation.
        unsafe { LocalFree(self.0) };
    }
}

fn descriptor(file: &File) -> Result<Vec<u8>> {
    let mut raw = std::ptr::null_mut();
    // SAFETY: the exact held query handle and all outputs remain owned.
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut raw,
        )
    };
    let allocation = LocalDescriptor(raw);
    ensure!(
        code == 0 && !raw.is_null(),
        "read role descriptor query failed: {code}"
    );
    let allocated = unsafe { LocalSize(allocation.0) };
    ensure!(
        (20..=1_048_576).contains(&allocated),
        "read role descriptor allocation exceeds bound"
    );
    let length = unsafe { GetSecurityDescriptorLength(allocation.0) } as usize;
    ensure!(
        (20..=65_536).contains(&length)
            && length <= allocated
            && unsafe { IsValidSecurityDescriptor(allocation.0) } != 0,
        "invalid bounded read role descriptor"
    );
    // SAFETY: copy only the validated initialized extent, never allocator padding.
    Ok(unsafe { std::slice::from_raw_parts(allocation.0.cast::<u8>(), length) }.to_vec())
}

fn identity(file: &File) -> Result<(u32, u64, u32)> {
    let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    ensure!(
        unsafe { GetFileInformationByHandle(file.as_raw_handle() as _, &mut info) } != 0,
        "read role identity unavailable: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | 0x40) == 0,
        "read role root is a reparse point or device"
    );
    Ok((
        info.dwVolumeSerialNumber,
        (u64::from(info.nFileIndexHigh) << 32) | u64::from(info.nFileIndexLow),
        info.dwFileAttributes,
    ))
}

fn role_sid(sid: &str) -> Result<Vec<u8>> {
    let owned = LocalSid::from_string(sid)?;
    let length = unsafe { GetLengthSid(owned.as_ptr()) } as usize;
    ensure!(
        (8..=68).contains(&length),
        "read role SID extent exceeds bound"
    );
    // SAFETY: ConvertStringSidToSidW produced this owned valid SID.
    Ok(unsafe { std::slice::from_raw_parts(owned.as_ptr().cast::<u8>(), length) }.to_vec())
}

struct HeldRoot {
    path: PathBuf,
    file: File,
    identity: (u32, u64, u32),
    descriptor: Vec<u8>,
}

enum ObservationState {
    Live,
    Refused,
}

/// Actual bounded same-plan RX readback on retained query-only root handles.
///
/// This value cannot be deserialized, cloned, or used as a launch grant. It
/// observes root ACLs only: effective normal identities, descendants, trusted
/// namespace/volume, executable loading and fresh-base admission remain separate.
pub struct HeldFilesystemReadAcl {
    plan: FilesystemCapabilityPlan,
    roots: Vec<HeldRoot>,
    state: ObservationState,
}

/// Read the current ReadV3 registry and exact declared roots without repairing,
/// creating, granting access, or accepting a caller readiness assertion.
pub fn observe_filesystem_read_acl(
    codex_home: &Path,
    plan: &FilesystemCapabilityPlan,
) -> Result<HeldFilesystemReadAcl> {
    crate::validate_filesystem_capability_plan(codex_home, plan)?;
    let roles = plan
        .read_root_sids()
        .map(|(_, sid)| role_sid(sid))
        .collect::<Result<Vec<_>>>()?;
    ensure!(
        !roles.is_empty() && roles.len() <= 64,
        "read proof requires a bounded nonempty root cohort"
    );
    let mut roots = Vec::with_capacity(roles.len());
    for ((path, _), role) in plan.read_root_sids().zip(&roles) {
        let path = PathBuf::from(path);
        let file = read_acl_query::open(&path)?;
        let before = identity(&file)?;
        let bytes = descriptor(&file)?;
        let others = roles
            .iter()
            .filter(|sid| *sid != role)
            .cloned()
            .collect::<Vec<_>>();
        let kind = if before.2 & FILE_ATTRIBUTE_DIRECTORY != 0 {
            RootKind::Directory
        } else {
            RootKind::File
        };
        read_role_descriptor::validate(&bytes, role, &others, kind)?;
        ensure!(
            identity(&file)? == before,
            "read role root changed during observation"
        );
        roots.push(HeldRoot {
            path,
            file,
            identity: before,
            descriptor: bytes,
        });
    }
    let mut observed = HeldFilesystemReadAcl {
        plan: plan.clone(),
        roots,
        state: ObservationState::Live,
    };
    observed.revalidate(codex_home, plan)?;
    Ok(observed)
}

impl HeldFilesystemReadAcl {
    /// Recheck the original registry/plan, held identities and complete owner/DACL
    /// bytes, plus the current name-to-object binding. Any failure is sticky.
    pub fn revalidate(&mut self, codex_home: &Path, plan: &FilesystemCapabilityPlan) -> Result<()> {
        ensure!(
            matches!(self.state, ObservationState::Live),
            "read ACL observation remains refused"
        );
        self.state = ObservationState::Refused;
        ensure!(
            plan == &self.plan,
            "read ACL observation belongs to another exact plan"
        );
        crate::validate_filesystem_capability_plan(codex_home, plan)?;
        for root in &self.roots {
            ensure!(
                identity(&root.file)? == root.identity
                    && descriptor(&root.file)? == root.descriptor,
                "held read role identity or descriptor changed"
            );
            let named = read_acl_query::open(&root.path)?;
            ensure!(
                identity(&named)? == root.identity && descriptor(&named)? == root.descriptor,
                "read role root name was rebound"
            );
            ensure!(
                identity(&root.file)? == root.identity
                    && descriptor(&root.file)? == root.descriptor,
                "held read role changed during name readback"
            );
        }
        crate::validate_filesystem_capability_plan(codex_home, plan)?;
        self.state = ObservationState::Live;
        Ok(())
    }
}

#[cfg(test)]
#[path = "filesystem_read_acl_tests.rs"]
mod tests;
