//! Establish ordinary access on an owned fixture without reducing its old ACL.

use pretty_assertions::assert_eq;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::AddAce;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::INHERITED_ACE;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::SE_DACL_AUTO_INHERIT_REQ;
use windows_sys::Win32::Security::SE_DACL_AUTO_INHERITED;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

const MODIFY: u32 = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE;
const INHERIT: u32 = CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE;
const INHERITANCE_CONTROL: u16 =
    SE_DACL_PROTECTED | SE_DACL_AUTO_INHERITED | SE_DACL_AUTO_INHERIT_REQ;

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: each nonnull pointer is the unique LocalAlloc result of an ACL API.
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

struct Snapshot {
    _descriptor: LocalAllocation,
    revision: u8,
    control: u16,
    aces: Vec<Vec<u8>>,
}

fn ace_bytes(acl: *mut ACL) -> Vec<Vec<u8>> {
    assert!(
        !acl.is_null(),
        "a null DACL cannot be narrowed for this fixture"
    );
    // SAFETY: the caller retains the descriptor or allocation owning this ACL.
    assert_ne!(unsafe { IsValidAcl(acl) }, 0, "invalid fixture ACL");
    // SAFETY: the validated ACL header is live for this call.
    (0..unsafe { (*acl).AceCount })
        .map(|index| {
            let mut entry = std::ptr::null_mut();
            // SAFETY: index lies inside the validated ACL and entry is writable.
            assert_ne!(unsafe { GetAce(acl, u32::from(index), &mut entry) }, 0);
            assert!(!entry.is_null());
            // SAFETY: GetAce returned an entry in the retained validated ACL.
            let header = unsafe { &*entry.cast::<ACE_HEADER>() };
            assert!(header.AceSize >= 8);
            // Preserve all bytes; reject exotic ACLs instead of silently changing their semantics.
            assert!(
                matches!(header.AceType, 0 | 1),
                "fixture ACL has a non-basic ACE"
            );
            // SAFETY: the validated entry extends for its declared AceSize bytes.
            unsafe { std::slice::from_raw_parts(entry.cast::<u8>(), usize::from(header.AceSize)) }
                .to_vec()
        })
        .collect()
}

fn snapshot(file: &File) -> Snapshot {
    let mut descriptor = std::ptr::null_mut();
    let mut acl = std::ptr::null_mut();
    // SAFETY: file remains open and all output pointers refer to initialized locals.
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut acl,
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    let owner = LocalAllocation(descriptor);
    assert_eq!(status, ERROR_SUCCESS, "read retained fixture DACL");
    let aces = ace_bytes(acl);
    let mut control = 0;
    let mut revision = 0;
    // SAFETY: descriptor is the successful API result retained in owner.
    assert_ne!(
        unsafe { GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) },
        0
    );
    Snapshot {
        _descriptor: owner,
        // SAFETY: ace_bytes validated the live ACL header.
        revision: unsafe { (*acl).AclRevision },
        control,
        aces,
    }
}

fn mapped_delete_child(ace: &[u8]) -> bool {
    let mut mask = u32::from_le_bytes(ace[4..8].try_into().expect("basic ACE mask"));
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    // SAFETY: both pointers refer to initialized stack values retained for this call.
    unsafe { MapGenericMask(&mut mask, &mapping) };
    ace[0] == 0 && mask & FILE_DELETE_CHILD != 0
}

fn hex_aces(aces: &[Vec<u8>]) -> Vec<String> {
    aces.iter()
        .map(|ace| ace.iter().map(|byte| format!("{byte:02x}")).collect())
        .collect()
}

/// Only this fresh TempDir and its already-created descendants receive ordinary rights.
/// Every inherited outside/protected-path challenge remains present in the original test.
pub(super) fn grant_ordinary_modify(root: &TempDir, descendants: &[&Path]) {
    assert_eq!(MODIFY & FILE_DELETE_CHILD, 0);
    let paths: Vec<&Path> = std::iter::once(root.path())
        .chain(descendants.iter().copied())
        .collect();
    assert!(
        descendants
            .iter()
            .all(|path| path.starts_with(root.path()) && *path != root.path())
    );
    let files: Vec<File> = paths
        .iter()
        .enumerate()
        .map(|(index, path)| {
            let access = READ_CONTROL | if index == 0 { WRITE_DAC } else { 0 };
            let file = OpenOptions::new()
                .access_mode(access)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
                .open(path)
                .expect("retain owned legacy fixture object");
            assert_eq!(
                file.metadata().expect("fixture metadata").file_attributes()
                    & FILE_ATTRIBUTE_REPARSE_POINT,
                0
            );
            file
        })
        .collect();
    let before: Vec<Snapshot> = files.iter().map(snapshot).collect();
    // SAFETY: the returned handle is newly owned and immediately adopted below.
    let base = unsafe { crate::token::get_current_token_for_restriction() }
        .expect("open actual legacy fixture base token");
    // SAFETY: the token factory transfers ownership of this new native handle.
    let base = unsafe { OwnedHandle::from_raw_handle(base as _) };
    // SAFETY: base is retained while the copied logon SID is obtained.
    let mut logon_sid = unsafe { crate::token::get_logon_sid_bytes(base.as_raw_handle() as _) }
        .expect("copy actual base logon SID");
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: MODIFY,
        grfAccessMode: GRANT_ACCESS,
        grfInheritance: INHERIT,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: logon_sid.as_mut_ptr().cast(),
        },
    };
    let mut grant = std::ptr::null_mut();
    // Generate only the new ACE; never merge/rewrite old matching trustee entries.
    // SAFETY: entry/SID stay live and grant is a writable LocalAlloc output pointer.
    let status = unsafe { SetEntriesInAclW(1, &entry, std::ptr::null_mut(), &mut grant) };
    let _grant_owner = LocalAllocation(grant.cast());
    assert_eq!(status, ERROR_SUCCESS, "construct additive ordinary grant");
    let grants = ace_bytes(grant);
    assert_eq!(grants.len(), 1);
    let granted = &grants[0];
    assert_eq!(granted[0], 0);
    assert_eq!(granted[1], INHERIT as u8);
    assert_eq!(
        u32::from_le_bytes(granted[4..8].try_into().expect("grant mask")),
        MODIFY
    );
    // SAFETY: a basic allow ACE stores its valid SID after its eight-byte header/mask.
    assert_ne!(
        unsafe {
            EqualSid(
                granted[8..].as_ptr().cast_mut().cast(),
                logon_sid.as_mut_ptr().cast(),
            )
        },
        0
    );
    let mut root_aces = before[0].aces.clone();
    root_aces.push(granted.clone());
    let length = std::mem::size_of::<ACL>() + root_aces.iter().map(Vec::len).sum::<usize>();
    assert!(length <= usize::from(u16::MAX));
    let mut words = vec![0u32; length.div_ceil(std::mem::size_of::<u32>())];
    let acl = words.as_mut_ptr().cast::<ACL>();
    let revision = u32::from(before[0].revision);
    // SAFETY: words provides aligned storage of at least length bytes until the API returns.
    assert_ne!(unsafe { InitializeAcl(acl, length as u32, revision) }, 0);
    for ace in &root_aces {
        // SAFETY: each ACE is validated, live, and copied into sufficient owned ACL storage.
        assert_ne!(
            unsafe {
                AddAce(
                    acl,
                    revision,
                    u32::MAX,
                    ace.as_ptr().cast(),
                    ace.len() as u32,
                )
            },
            0
        );
    }
    assert_eq!(ace_bytes(acl), root_aces);
    // SAFETY: the same retained root handle and ACL storage remain live throughout the update.
    assert_eq!(
        unsafe {
            SetSecurityInfo(
                files[0].as_raw_handle() as _,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                acl,
                std::ptr::null_mut(),
            )
        },
        ERROR_SUCCESS,
        "append owned ordinary fixture grant"
    );

    for (index, ((path, file), old)) in paths.iter().zip(&files).zip(&before).enumerate() {
        let after = snapshot(file);
        eprintln!(
            "legacy-fixture-acl path={path:?} before-control={} after-control={} before={:?} after={:?}",
            old.control,
            after.control,
            hex_aces(&old.aces),
            hex_aces(&after.aces)
        );
        assert_eq!(
            old.control & INHERITANCE_CONTROL,
            after.control & INHERITANCE_CONTROL,
            "fixture inheritance control changed"
        );
        let mut expected = granted.clone();
        if index != 0 {
            expected[1] = INHERITED_ACE as u8;
            if file.metadata().expect("retained fixture metadata").is_dir() {
                expected[1] |= INHERIT as u8;
            }
        }
        let mut old_index = 0;
        let mut additions = 0;
        for ace in &after.aces {
            if old.aces.get(old_index) == Some(ace) {
                old_index += 1;
            } else {
                assert_eq!(ace, &expected, "unexpected new or rewritten fixture ACE");
                // An added allow may not bypass an old explicit or inherited deny.
                assert!(
                    old.aces[old_index..].iter().all(|old_ace| old_ace[0] != 1),
                    "new fixture grant moved before an old deny"
                );
                additions += 1;
            }
        }
        assert_eq!(
            old_index,
            old.aces.len(),
            "an original ACE was lost or reordered"
        );
        assert_eq!(additions, 1, "fixture must add exactly one ordinary grant");
        assert_eq!(
            old.aces
                .iter()
                .filter(|ace| mapped_delete_child(ace))
                .count(),
            after
                .aces
                .iter()
                .filter(|ace| mapped_delete_child(ace))
                .count(),
            "an original FILE_DELETE_CHILD grant was changed"
        );
    }
}
