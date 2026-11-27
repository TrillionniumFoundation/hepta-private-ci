//! Explicit authorization and owned ACLs for the hosted Windows sandbox fixture.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::path::Prefix;
use std::ptr;
use windows_sys::Win32::Foundation::BOOL;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::Storage::FileSystem as file_system;
use windows_sys::Win32::System::Threading as threading;

// Winnt.h constants; these are not exported by windows-sys 0.52's Security module.
const SECURITY_DESCRIPTOR_REVISION: u32 = 1;
const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const MAX_SID_BYTES: usize = 68;
const MAX_SECURITY_BYTES: u32 = 65_536;
const INHERITANCE: u32 = security::OBJECT_INHERIT_ACE | security::CONTAINER_INHERIT_ACE;

/// Never requests UAC. Unsupported hosts fail before exec-server or setup starts.
pub(super) struct AuthorizedReadOnlySandboxFixture {
    root: Option<PathBuf>,
    workspace: PathBuf,
    _parent_handle: File,
    root_handle: Option<File>,
    workspace_handle: Option<File>,
    workspace_created: bool,
}

impl AuthorizedReadOnlySandboxFixture {
    pub(super) fn new(root_id: [u8; 16]) -> Result<Self> {
        let sids = require_hosted_elevated_authorization()?;
        let runner_temp =
            PathBuf::from(std::env::var_os("RUNNER_TEMP").context("RUNNER_TEMP is required")?);
        ensure!(runner_temp.is_absolute(), "RUNNER_TEMP must be absolute");
        let parent_handle = open_directory(&runner_temp)?;
        let parent_identity = directory_identity(&parent_handle)?;
        let runner_temp = std::fs::canonicalize(&runner_temp)?;
        ensure!(
            matches!(runner_temp.components().next(), Some(Component::Prefix(prefix))
                if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::VerbatimDisk(_))),
            "RUNNER_TEMP must be on a local Windows volume"
        );
        ensure_same_directory(&runner_temp, parent_identity)?;
        let root = runner_temp.join(format!(
            "codex-elevated-fixture-{:032x}",
            u128::from_be_bytes(root_id)
        ));
        let workspace = root.join("workspace");
        create_private_directory(&root, &sids)?;
        // Ownership begins immediately after creation, including later validation errors.
        let mut fixture = Self {
            root: Some(root.clone()),
            workspace,
            _parent_handle: parent_handle,
            root_handle: None,
            workspace_handle: None,
            workspace_created: false,
        };
        let root_handle = open_directory(&root)?;
        verify_directory_security(&root, &root_handle, &sids)?;
        fixture.root_handle = Some(root_handle);
        create_private_directory(&fixture.workspace, &sids)?;
        fixture.workspace_created = true;
        let workspace_handle = open_directory(&fixture.workspace)?;
        verify_directory_security(&fixture.workspace, &workspace_handle, &sids)?;
        fixture.workspace_handle = Some(workspace_handle);

        // The host can write the exact forbidden path. A sandbox denial cannot be
        // explained by an unwritable fixture or a pre-existing file.
        let blocked = fixture.workspace.join("blocked.txt");
        {
            let mut file = OpenOptions::new()
                .write(/*write*/ true)
                .create_new(/*create_new*/ true)
                .open(&blocked)?;
            file.write_all(b"host-positive-control\n")?;
            file.sync_all()?;
        }
        ensure!(
            std::fs::read(&blocked)?.as_slice() == b"host-positive-control\n",
            "host write/read positive control differs"
        );
        std::fs::remove_file(&blocked)?;
        ensure!(
            !blocked.try_exists()?,
            "host delete positive control failed"
        );
        eprintln!(
            "elevated fixture: hosted CI authorized; primary elevated/admin token verified; protected owner/DACL and host write/delete verified"
        );
        Ok(fixture)
    }

    pub(super) fn path(&self) -> &Path {
        &self.workspace
    }

    pub(super) fn close(mut self) -> Result<()> {
        self.remove_owned()
    }

    fn remove_owned(&mut self) -> Result<()> {
        // Take ownership once: a reported cleanup failure is not retried by Drop.
        let Some(root) = self.root.take() else {
            return Ok(());
        };
        drop(self.workspace_handle.take());
        let workspace_result = if self.workspace_created {
            std::fs::remove_dir_all(&self.workspace)
        } else {
            Ok(())
        };
        // Hold the owned parent until its child is gone. The final root operation
        // removes an empty directory only, never a replacement subtree.
        drop(self.root_handle.take());
        let root_result = std::fs::remove_dir(&root);
        workspace_result.context("remove owned elevated workspace")?;
        root_result.context("remove owned elevated fixture root")?;
        Ok(())
    }
}

impl Drop for AuthorizedReadOnlySandboxFixture {
    fn drop(&mut self) {
        if let Err(error) = self.remove_owned() {
            eprintln!("owned elevated fixture cleanup failed: {error}");
        }
    }
}

fn check(success: BOOL) -> std::io::Result<()> {
    if success == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn sid_ptr(sid: &[u32]) -> PSID {
    sid.as_ptr().cast_mut().cast()
}

fn known_sid(kind: security::WELL_KNOWN_SID_TYPE) -> Result<Vec<u32>> {
    let mut sid = vec![0u32; MAX_SID_BYTES / size_of::<u32>()];
    let mut size = MAX_SID_BYTES as u32;
    // The aligned allocation covers SECURITY_MAX_SID_SIZE.
    check(unsafe {
        security::CreateWellKnownSid(kind, ptr::null_mut(), sid.as_mut_ptr().cast(), &mut size)
    })?;
    ensure!(
        size as usize <= MAX_SID_BYTES
            && unsafe { security::IsValidSid(sid.as_mut_ptr().cast()) } != 0,
        "well-known SID is invalid or exceeds its buffer"
    );
    Ok(sid)
}

fn require_hosted_elevated_authorization() -> Result<[Vec<u32>; 4]> {
    for (key, expected) in [
        (
            "CODEX_TEST_WINDOWS_ELEVATED_FIXTURE",
            "github-hosted-admin-v1",
        ),
        ("GITHUB_ACTIONS", "true"),
        ("RUNNER_ENVIRONMENT", "github-hosted"),
        ("RUNNER_OS", "Windows"),
    ] {
        ensure!(
            std::env::var(key).as_deref() == Ok(expected),
            "explicit hosted Windows authorization is absent: {key}"
        );
    }
    let mut raw_token = 0;
    check(unsafe {
        threading::OpenProcessToken(
            threading::GetCurrentProcess(),
            security::TOKEN_QUERY | security::TOKEN_DUPLICATE,
            &mut raw_token,
        )
    })?;
    // OpenProcessToken returns the process primary token, not a thread impersonation token.
    let token = unsafe { OwnedHandle::from_raw_handle(raw_token as _) };
    let mut elevation: security::TOKEN_ELEVATION = unsafe { std::mem::zeroed() };
    let mut returned = 0;
    check(unsafe {
        security::GetTokenInformation(
            token.as_raw_handle() as HANDLE,
            security::TokenElevation,
            (&mut elevation as *mut security::TOKEN_ELEVATION).cast(),
            size_of::<security::TOKEN_ELEVATION>() as u32,
            &mut returned,
        )
    })?;
    ensure!(
        returned as usize == size_of::<security::TOKEN_ELEVATION>()
            && elevation.TokenIsElevated != 0,
        "an already elevated primary token is required; UAC is not requested"
    );
    let administrators = known_sid(security::WinBuiltinAdministratorsSid)?;
    let mut duplicate = 0;
    check(unsafe {
        security::DuplicateToken(
            token.as_raw_handle() as HANDLE,
            security::SecurityImpersonation,
            &mut duplicate,
        )
    })?;
    let membership_token = unsafe { OwnedHandle::from_raw_handle(duplicate as _) };
    let mut member = 0;
    check(unsafe {
        security::CheckTokenMembership(
            membership_token.as_raw_handle() as HANDLE,
            sid_ptr(&administrators),
            &mut member,
        )
    })?;
    ensure!(
        member != 0,
        "Administrators SID must be enabled in the primary token"
    );

    let mut needed = 0;
    let probe = unsafe {
        security::GetTokenInformation(
            token.as_raw_handle() as HANDLE,
            security::TokenUser,
            ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut needed,
        )
    };
    ensure!(
        probe == 0
            && unsafe { GetLastError() } == ERROR_INSUFFICIENT_BUFFER
            && needed as usize >= size_of::<security::TOKEN_USER>()
            && needed <= MAX_SECURITY_BYTES,
        "TokenUser size query failed"
    );
    let mut user = vec![0usize; (needed as usize).div_ceil(size_of::<usize>())];
    check(unsafe {
        security::GetTokenInformation(
            token.as_raw_handle() as HANDLE,
            security::TokenUser,
            user.as_mut_ptr().cast(),
            needed,
            &mut returned,
        )
    })?;
    ensure!(
        returned as usize >= size_of::<security::TOKEN_USER>() && returned <= needed,
        "TokenUser size differs from its allocated buffer"
    );
    let user_sid = unsafe { (*(user.as_ptr().cast::<security::TOKEN_USER>())).User.Sid };
    ensure!(
        unsafe { security::IsValidSid(user_sid) } != 0,
        "invalid TokenUser SID"
    );
    let length = unsafe { security::GetLengthSid(user_sid) };
    ensure!(
        length as usize <= MAX_SID_BYTES,
        "TokenUser SID exceeds its buffer"
    );
    let mut owner = vec![0u32; MAX_SID_BYTES / size_of::<u32>()];
    check(unsafe { security::CopySid(length, owner.as_mut_ptr().cast(), user_sid) })?;
    let sids = [
        owner,
        known_sid(security::WinLocalSystemSid)?,
        administrators,
        known_sid(security::WinAuthenticatedUserSid)?,
    ];
    for other in &sids[1..] {
        ensure!(
            unsafe { security::EqualSid(sid_ptr(&sids[0]), sid_ptr(other)) } == 0,
            "the fixture owner must be a distinct host user"
        );
    }
    Ok(sids)
}

fn wide_path(path: &Path) -> Result<Vec<u16>> {
    let mut wide: Vec<u16> = path.as_os_str().encode_wide().collect();
    ensure!(!wide.contains(&0), "fixture path contains NUL");
    wide.push(0);
    Ok(wide)
}

fn allowed_mask(index: usize) -> u32 {
    if index == 3 {
        file_system::FILE_GENERIC_READ | file_system::FILE_GENERIC_EXECUTE
    } else {
        file_system::FILE_ALL_ACCESS
    }
}

fn create_private_directory(path: &Path, sids: &[Vec<u32>; 4]) -> Result<()> {
    let acl_bytes = size_of::<security::ACL>()
        + sids
            .iter()
            .map(|sid| {
                size_of::<security::ACCESS_ALLOWED_ACE>() - size_of::<u32>()
                    + unsafe { security::GetLengthSid(sid_ptr(sid)) } as usize
            })
            .sum::<usize>();
    let mut acl_words = vec![0u32; acl_bytes.div_ceil(size_of::<u32>())];
    let acl = acl_words.as_mut_ptr().cast::<security::ACL>();
    check(unsafe { security::InitializeAcl(acl, acl_bytes as u32, security::ACL_REVISION) })?;
    for (index, sid) in sids.iter().enumerate() {
        check(unsafe {
            security::AddAccessAllowedAceEx(
                acl,
                security::ACL_REVISION,
                INHERITANCE,
                allowed_mask(index),
                sid_ptr(sid),
            )
        })?;
    }
    let mut descriptor: security::SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
    let descriptor_ptr = (&mut descriptor as *mut security::SECURITY_DESCRIPTOR).cast();
    check(unsafe {
        security::InitializeSecurityDescriptor(descriptor_ptr, SECURITY_DESCRIPTOR_REVISION)
    })?;
    check(unsafe {
        security::SetSecurityDescriptorOwner(
            descriptor_ptr,
            sid_ptr(&sids[0]),
            /*bownerdefaulted*/ 0,
        )
    })?;
    check(unsafe {
        security::SetSecurityDescriptorDacl(
            descriptor_ptr,
            /*bdaclpresent*/ 1,
            acl,
            /*bdacldefaulted*/ 0,
        )
    })?;
    check(unsafe {
        security::SetSecurityDescriptorControl(
            descriptor_ptr,
            security::SE_DACL_PROTECTED,
            security::SE_DACL_PROTECTED,
        )
    })?;
    let attributes = security::SECURITY_ATTRIBUTES {
        nLength: size_of::<security::SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor_ptr,
        bInheritHandle: 0,
    };
    let wide = wide_path(path)?;
    // Unlike creating a TempDir and changing it later, there is no inherited-DACL window.
    check(unsafe { file_system::CreateDirectoryW(wide.as_ptr(), &attributes) })
        .with_context(|| format!("create owned protected directory {}", path.display()))
}

fn open_directory(path: &Path) -> Result<File> {
    let handle = OpenOptions::new()
        .access_mode(file_system::READ_CONTROL | file_system::FILE_READ_ATTRIBUTES)
        .share_mode(file_system::FILE_SHARE_READ | file_system::FILE_SHARE_WRITE)
        .custom_flags(
            file_system::FILE_FLAG_BACKUP_SEMANTICS | file_system::FILE_FLAG_OPEN_REPARSE_POINT,
        )
        .open(path)?;
    directory_identity(&handle)?;
    Ok(handle)
}

fn directory_identity(handle: &File) -> Result<[u32; 3]> {
    let mut info: file_system::BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    check(unsafe {
        file_system::GetFileInformationByHandle(handle.as_raw_handle() as HANDLE, &mut info)
    })?;
    ensure!(
        info.dwFileAttributes & file_system::FILE_ATTRIBUTE_DIRECTORY != 0
            && info.dwFileAttributes & file_system::FILE_ATTRIBUTE_REPARSE_POINT == 0,
        "fixture directory must be a real directory, not a reparse point"
    );
    Ok([
        info.dwVolumeSerialNumber,
        info.nFileIndexHigh,
        info.nFileIndexLow,
    ])
}

fn ensure_same_directory(path: &Path, identity: [u32; 3]) -> Result<()> {
    ensure!(
        directory_identity(&open_directory(path)?)? == identity,
        "fixture path no longer names its retained directory handle"
    );
    Ok(())
}

fn verify_directory_security(path: &Path, handle: &File, sids: &[Vec<u32>; 4]) -> Result<()> {
    let identity = directory_identity(handle)?;
    ensure_same_directory(path, identity)?;
    let wide = wide_path(path)?;
    let requested = security::OWNER_SECURITY_INFORMATION | security::DACL_SECURITY_INFORMATION;
    let mut needed = 0;
    let probe = unsafe {
        security::GetFileSecurityW(
            wide.as_ptr(),
            requested,
            ptr::null_mut(),
            /*nlength*/ 0,
            &mut needed,
        )
    };
    ensure!(
        probe == 0
            && unsafe { GetLastError() } == ERROR_INSUFFICIENT_BUFFER
            && needed > 0
            && needed <= MAX_SECURITY_BYTES,
        "directory security descriptor size query failed"
    );
    let capacity = needed;
    let mut storage = vec![0usize; (capacity as usize).div_ceil(size_of::<usize>())];
    let descriptor = storage.as_mut_ptr().cast();
    check(unsafe {
        security::GetFileSecurityW(wide.as_ptr(), requested, descriptor, capacity, &mut needed)
    })?;
    ensure!(
        needed <= capacity,
        "directory security descriptor exceeded its buffer"
    );
    ensure_same_directory(path, identity)?;
    ensure!(
        unsafe { security::IsValidSecurityDescriptor(descriptor) } != 0,
        "invalid directory security descriptor"
    );
    let mut owner = ptr::null_mut();
    let mut owner_defaulted = 0;
    check(unsafe {
        security::GetSecurityDescriptorOwner(descriptor, &mut owner, &mut owner_defaulted)
    })?;
    ensure!(
        !owner.is_null()
            && owner_defaulted == 0
            && unsafe { security::EqualSid(owner, sid_ptr(&sids[0])) } != 0,
        "directory owner differs from the actual primary token user"
    );
    let mut control = 0;
    let mut revision = 0;
    check(unsafe {
        security::GetSecurityDescriptorControl(descriptor, &mut control, &mut revision)
    })?;
    ensure!(
        revision == SECURITY_DESCRIPTOR_REVISION && control & security::SE_DACL_PROTECTED != 0,
        "directory DACL must be protected from parent inheritance"
    );
    let mut present = 0;
    let mut defaulted = 0;
    let mut acl = ptr::null_mut();
    check(unsafe {
        security::GetSecurityDescriptorDacl(descriptor, &mut present, &mut acl, &mut defaulted)
    })?;
    ensure!(
        present != 0
            && defaulted == 0
            && !acl.is_null()
            && unsafe { security::IsValidAcl(acl) } != 0,
        "directory DACL is missing, defaulted, null or invalid"
    );
    let mut info: security::ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    check(unsafe {
        security::GetAclInformation(
            acl,
            (&mut info as *mut security::ACL_SIZE_INFORMATION).cast(),
            size_of::<security::ACL_SIZE_INFORMATION>() as u32,
            security::AclSizeInformation,
        )
    })?;
    ensure!(
        info.AceCount == sids.len() as u32,
        "unexpected directory ACE count"
    );
    for (index, sid) in sids.iter().enumerate() {
        let mut raw: *mut c_void = ptr::null_mut();
        check(unsafe { security::GetAce(acl, index as u32, &mut raw) })?;
        ensure!(!raw.is_null(), "null directory ACE");
        let header = unsafe { &*raw.cast::<security::ACE_HEADER>() };
        ensure!(
            header.AceType == ACCESS_ALLOWED_ACE_TYPE
                && u32::from(header.AceFlags) == INHERITANCE
                && usize::from(header.AceSize) >= size_of::<security::ACCESS_ALLOWED_ACE>(),
            "directory ACE type, flags or size differs"
        );
        let ace = unsafe { &*raw.cast::<security::ACCESS_ALLOWED_ACE>() };
        let ace_sid = ptr::addr_of!(ace.SidStart).cast_mut().cast();
        ensure!(
            unsafe { security::IsValidSid(ace_sid) } != 0,
            "invalid directory ACE SID"
        );
        ensure!(
            ace.Mask == allowed_mask(index)
                && usize::from(header.AceSize)
                    == size_of::<security::ACCESS_ALLOWED_ACE>() - size_of::<u32>()
                        + unsafe { security::GetLengthSid(ace_sid) } as usize
                && unsafe { security::EqualSid(ace_sid, sid_ptr(sid)) } != 0,
            "directory ACE mask, SID, size or order differs"
        );
    }
    Ok(())
}
