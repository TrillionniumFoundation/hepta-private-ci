//! Exact-request read-role ACL preparation. No token or launch authority is produced.
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::mem::size_of;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;
use codex_windows_sandbox::FilesystemCapabilityPlan;
use codex_windows_sandbox::LocalSid;
use codex_windows_sandbox::validate_filesystem_capability_plan_roots;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SET_ACCESS;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::CheckTokenMembership;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::INHERIT_ONLY_ACE;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

use super::Payload;
use super::log_line;
use super::read_acl_mutex::ReadAclMutexGuard;
use super::read_acl_mutex::acquire_read_acl_mutex;
use super::sandbox_users::resolve_sandbox_users_group_sid;

const RX: u32 = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE;
const QUERY: u32 = READ_CONTROL | FILE_READ_ATTRIBUTES | SYNCHRONIZE;
const MAX_ACES: u32 = 1024;

struct LocalAllocation(*mut c_void);
impl Drop for LocalAllocation {
    fn drop(&mut self) {
        // SAFETY: successful security APIs return LocalAlloc-owned memory.
        unsafe { LocalFree(self.0 as HLOCAL) };
    }
}

struct ReadAclSubjects {
    normal_identity: LocalSid,
    ambient_rx: [LocalSid; 3],
    restrictive_rx: BTreeMap<String, LocalSid>,
}

/// Root allow-ACE readback only; not effective-token, descendant, namespace,
/// private-owner or executable-launch qualification. Cannot be deserialized.
pub(super) struct PreparedFilesystemAclContext {
    _plan: FilesystemCapabilityPlan,
    _held_roots: Vec<File>,
    _serialization: ReadAclMutexGuard,
}

fn open_root(path: &Path, access: u32) -> Result<File> {
    anyhow::ensure!(
        path.parent().is_some()
            && matches!(path.components().next(), Some(std::path::Component::Prefix(prefix))
                if matches!(prefix.kind(), std::path::Prefix::Disk(_) | std::path::Prefix::VerbatimDisk(_))),
        "read ACL root must be a local non-volume path"
    );
    let file = OpenOptions::new()
        .access_mode(access)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    let metadata = file.metadata()?;
    anyhow::ensure!(
        (metadata.is_dir() || metadata.is_file())
            && metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT == 0,
        "read ACL root is not a plain filesystem object"
    );
    identity(&file)?;
    Ok(file)
}

fn identity(file: &File) -> Result<(u32, u64)> {
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: this live File and the complete initialized native output remain owned.
    anyhow::ensure!(
        unsafe { GetFileInformationByHandle(file.as_raw_handle() as _, &mut information) } != 0,
        "read ACL root identity unavailable: {}",
        std::io::Error::last_os_error()
    );
    Ok((
        information.dwVolumeSerialNumber,
        (u64::from(information.nFileIndexHigh) << 32) | u64::from(information.nFileIndexLow),
    ))
}

fn descriptor(file: &File) -> Result<(LocalAllocation, *mut ACL)> {
    let mut descriptor = std::ptr::null_mut();
    let mut dacl = std::ptr::null_mut();
    // SAFETY: held non-inheritable File and live outputs; ownership is retained below.
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut dacl,
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    let allocation = LocalAllocation(descriptor);
    anyhow::ensure!(
        code == 0 && !dacl.is_null(),
        "read ACL query failed: {code}"
    );
    Ok((allocation, dacl))
}

fn readback(
    file: &File,
    subjects: &ReadAclSubjects,
    restrictive_sid: &LocalSid,
) -> Result<(bool, bool)> {
    let (_descriptor, dacl) = descriptor(file)?;
    let mut information: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: GetSecurityInfo returned a live kernel-validated ACL.
    anyhow::ensure!(
        unsafe {
            GetAclInformation(
                dacl,
                &mut information as *mut _ as _,
                size_of::<ACL_SIZE_INFORMATION>() as _,
                AclSizeInformation,
            )
        } != 0,
        "read ACL size query failed: {}",
        std::io::Error::last_os_error()
    );
    anyhow::ensure!(
        information.AceCount <= MAX_ACES,
        "read ACL ACE bound exceeded"
    );
    let mut normal = false;
    let mut restrictive = false;
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    for index in 0..information.AceCount {
        let mut raw = std::ptr::null_mut();
        // SAFETY: index is bounded by this live ACL's actual ACE count.
        anyhow::ensure!(
            unsafe { GetAce(dacl, index, &mut raw) } != 0 && !raw.is_null(),
            "read ACL ACE query failed: {}",
            std::io::Error::last_os_error()
        );
        let header = unsafe { &*raw.cast::<ACE_HEADER>() };
        anyhow::ensure!(
            header.AceSize as usize >= size_of::<ACCESS_ALLOWED_ACE>() + 4,
            "short read ACL ACE"
        );
        anyhow::ensure!(
            matches!(header.AceType, 0 | 1),
            "unsupported read ACL ACE type"
        );
        anyhow::ensure!(
            header.AceFlags & !0x1f == 0,
            "unsupported read ACL ACE flags"
        );
        if u32::from(header.AceFlags) & INHERIT_ONLY_ACE != 0 {
            continue;
        }
        // Ordinary allow/deny ACEs have the same mask/SID layout. Validate
        // the full SID range before handing it to an OS SID routine.
        let ace = unsafe { &*raw.cast::<ACCESS_ALLOWED_ACE>() };
        let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast::<c_void>();
        let subauthorities = unsafe { *sid.cast::<u8>().add(1) };
        anyhow::ensure!(
            subauthorities <= 15
                && 8 + usize::from(subauthorities) * 4 <= usize::from(header.AceSize) - 8
        );
        anyhow::ensure!(
            unsafe { IsValidSid(sid) } != 0
                && unsafe { GetLengthSid(sid) } as usize <= usize::from(header.AceSize) - 8
        );
        let mut mask = ace.Mask;
        unsafe { MapGenericMask(&mut mask, &mapping) };
        // Conservatively refuse every effective RX deny or unknown ACL form;
        // a matching allow ACE alone is never a readiness success.
        anyhow::ensure!(
            header.AceType != 1 || mask & RX == 0,
            "read ACL has a conflicting deny"
        );
        if header.AceType == 0 && mask & RX == RX {
            normal |= std::iter::once(&subjects.normal_identity)
                .chain(&subjects.ambient_rx)
                .any(|subject| unsafe { EqualSid(sid, subject.as_ptr()) } != 0);
            restrictive |= unsafe { EqualSid(sid, restrictive_sid.as_ptr()) } != 0;
        }
    }
    Ok((normal, restrictive))
}

fn repair(file: &File, subjects: &[*mut c_void]) -> Result<()> {
    let (_descriptor, previous) = descriptor(file)?;
    let inheritance = if file.metadata()?.is_dir() {
        OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE
    } else {
        0
    };
    let entries: Vec<_> = subjects
        .iter()
        .map(|sid| EXPLICIT_ACCESS_W {
            grfAccessPermissions: RX,
            grfAccessMode: SET_ACCESS,
            grfInheritance: inheritance,
            Trustee: TRUSTEE_W {
                TrusteeForm: TRUSTEE_IS_SID,
                ptstrName: *sid as _,
                ..unsafe { std::mem::zeroed() }
            },
        })
        .collect();
    let mut updated = std::ptr::null_mut();
    // SAFETY: all subjects, entries, previous ACL and output are live for this call.
    let code =
        unsafe { SetEntriesInAclW(entries.len() as _, entries.as_ptr(), previous, &mut updated) };
    let _updated = LocalAllocation(updated.cast());
    anyhow::ensure!(
        code == 0 && !updated.is_null(),
        "prepare read ACL failed: {code}"
    );
    // SAFETY: query and mutation use this exact held object, never a reconstructed path.
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
    anyhow::ensure!(code == 0, "write read ACL failed: {code}");
    Ok(())
}

pub(super) fn prepare(
    payload: &Payload,
    log: &mut dyn Write,
) -> Result<PreparedFilesystemAclContext> {
    let plan = payload
        .filesystem_roles
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("missing versioned filesystem role plan"))?;
    validate_filesystem_capability_plan_roots(
        &payload.codex_home,
        &payload.command_cwd,
        &payload.read_roots,
        &payload.write_roots,
        plan,
    )?;
    let group = resolve_sandbox_users_group_sid()?;
    let group = codex_windows_sandbox::string_from_sid_bytes(&group).map_err(anyhow::Error::msg)?;
    let normal_identity = LocalSid::from_string(&group)?;
    let mut restrictive_rx = BTreeMap::new();
    for (root, sid) in plan.read_root_sids() {
        let sid = LocalSid::from_string(sid)?;
        let mut ambient_member = 0;
        // SAFETY: NULL selects the caller's actual effective token; SID/output are owned.
        anyhow::ensure!(
            unsafe { CheckTokenMembership(0, sid.as_ptr(), &mut ambient_member) } != 0,
            "read capability membership query failed: {}",
            std::io::Error::last_os_error()
        );
        anyhow::ensure!(
            ambient_member == 0 && unsafe { EqualSid(sid.as_ptr(), normal_identity.as_ptr()) } == 0,
            "read capability is an ambient identity"
        );
        restrictive_rx.insert(root.to_owned(), sid);
    }
    let subjects = ReadAclSubjects {
        normal_identity,
        ambient_rx: [
            LocalSid::from_string("S-1-5-32-545")?,
            LocalSid::from_string("S-1-5-11")?,
            LocalSid::from_string("S-1-1-0")?,
        ],
        restrictive_rx,
    };
    let context = prepare_roots(plan.clone(), &payload.read_roots, subjects, log)?;
    // A concurrent registry change or missing original checkpoint cannot become success.
    validate_filesystem_capability_plan_roots(
        &payload.codex_home,
        &payload.command_cwd,
        &payload.read_roots,
        &payload.write_roots,
        plan,
    )?;
    Ok(context)
}

fn prepare_roots(
    plan: FilesystemCapabilityPlan,
    roots: &[PathBuf],
    subjects: ReadAclSubjects,
    log: &mut dyn Write,
) -> Result<PreparedFilesystemAclContext> {
    // The declaration's deserializer/registry already enforce MAX_ACTIVE_ROOTS.
    // Do not let duplicate transport paths inflate the retained handle cohort.
    anyhow::ensure!(
        roots.len() == plan.read_sids().count(),
        "read root cohort differs from bounded declaration"
    );
    let serialization = acquire_read_acl_mutex()?
        .ok_or_else(|| anyhow::anyhow!("read ACL setup is busy; no same-plan completion"))?;
    let mut held_roots = Vec::with_capacity(roots.len());
    let mut seen = BTreeSet::new();
    for path in roots {
        anyhow::ensure!(
            dunce::canonicalize(path)? == *path,
            "read ACL root alias changed"
        );
        let key = path
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        anyhow::ensure!(seen.insert(key.clone()), "duplicate prepared read root");
        let restrictive_sid = subjects
            .restrictive_rx
            .get(&key)
            .ok_or_else(|| anyhow::anyhow!("read root has no matching restrictive role"))?;
        let mut held = open_root(path, QUERY)?;
        let (normal, restrictive) = readback(&held, &subjects, restrictive_sid)?;
        let mut missing = Vec::new();
        if !normal {
            missing.push(subjects.normal_identity.as_ptr());
        }
        if !restrictive {
            missing.push(restrictive_sid.as_ptr());
        }
        if !missing.is_empty() {
            let writable = open_root(path, QUERY | WRITE_DAC)?;
            anyhow::ensure!(
                identity(&held)? == identity(&writable)?,
                "read ACL root was replaced"
            );
            repair(&writable, &missing)?;
            held = writable;
        }
        let (normal, restrictive) = readback(&held, &subjects, restrictive_sid)?;
        anyhow::ensure!(
            normal && restrictive,
            "incomplete normal/restrictive read ACL readback"
        );
        held_roots.push(held);
    }
    anyhow::ensure!(
        seen.len() == subjects.restrictive_rx.len(),
        "incomplete prepared read cohort"
    );
    log_line(
        log,
        &format!(
            "same filesystem declaration read ACL completed for {} held roots; no token or launch qualification",
            held_roots.len()
        ),
    )?;
    Ok(PreparedFilesystemAclContext {
        _plan: plan,
        _held_roots: held_roots,
        _serialization: serialization,
    })
}

#[cfg(test)]
#[path = "read_acl_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "read_acl_cross_root_tests.rs"]
mod cross_root_tests;
