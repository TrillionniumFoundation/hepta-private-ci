//! Protected, immutable credentials for the two local sandbox accounts.
//!
//! Machine-scoped DPAPI is not a file access boundary. No encrypted or decrypted
//! credential is accepted before the actual retained directory/file is verified.
use crate::dpapi;
use crate::setup::OFFLINE_USERNAME;
use crate::setup::ONLINE_USERNAME;
use crate::setup::SandboxNetworkIdentity;
use crate::setup::SandboxUsersFile;
use crate::setup::sandbox_secrets_dir;
use crate::setup_error::SetupErrorCode;
use crate::setup_error::SetupFailure;
use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::mem::size_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::path::Prefix;
use std::ptr;
use windows_sys::Win32::Foundation as foundation;
use windows_sys::Win32::NetworkManagement::NetManagement as net;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::Security::Authorization as authorization;
use windows_sys::Win32::Storage::FileSystem as filesystem;
use windows_sys::Win32::System::SystemServices as system_services;
use windows_sys::Win32::System::Threading as threading;

const MAX_SECRET_BYTES: u64 = 65_536;
const MAX_SECURITY_BYTES: u32 = 65_536;
const MAX_SID_BYTES: usize = 68;
const NERR_USER_NOT_FOUND: u32 = 2221;
const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const ACCESS_DENIED_ACE_TYPE: u8 = 1;
const SECURITY_DESCRIPTOR_REVISION: u32 = 1;
const USERS_FILE: &str = "sandbox_users.json";
pub const SANDBOX_USERS_GROUP: &str = "CodexSandboxUsers";

fn check(ok: foundation::BOOL) -> std::io::Result<()> {
    if ok == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn fail(code: SetupErrorCode, message: impl Into<String>) -> anyhow::Error {
    anyhow::Error::new(SetupFailure::new(code, message))
}

fn sid_ptr(sid: &[u32]) -> foundation::PSID {
    sid.as_ptr().cast_mut().cast()
}

fn copy_sid(source: foundation::PSID) -> Result<Vec<u32>> {
    ensure!(
        !source.is_null() && unsafe { security::IsValidSid(source) } != 0,
        "invalid native SID"
    );
    let bytes = unsafe { security::GetLengthSid(source) };
    ensure!(
        (8..=MAX_SID_BYTES as u32).contains(&bytes),
        "native SID length exceeds its bound"
    );
    let mut sid = vec![0u32; (bytes as usize).div_ceil(size_of::<u32>())];
    check(unsafe { security::CopySid(bytes, sid.as_mut_ptr().cast(), source) })?;
    Ok(sid)
}

fn same_sid(left: &[u32], right: &[u32]) -> bool {
    unsafe { security::EqualSid(sid_ptr(left), sid_ptr(right)) != 0 }
}

fn known_sid(kind: security::WELL_KNOWN_SID_TYPE) -> Result<Vec<u32>> {
    let mut value = vec![0u32; MAX_SID_BYTES / size_of::<u32>()];
    let mut bytes = MAX_SID_BYTES as u32;
    check(unsafe {
        security::CreateWellKnownSid(kind, ptr::null_mut(), value.as_mut_ptr().cast(), &mut bytes)
    })?;
    ensure!(
        bytes as usize <= MAX_SID_BYTES,
        "well-known SID exceeds its buffer"
    );
    copy_sid(value.as_mut_ptr().cast())
}

fn token_information(
    token: foundation::HANDLE,
    class: security::TOKEN_INFORMATION_CLASS,
) -> Result<(Vec<usize>, usize)> {
    let mut needed = 0;
    let probe =
        unsafe { security::GetTokenInformation(token, class, ptr::null_mut(), 0, &mut needed) };
    ensure!(
        probe == 0
            && unsafe { foundation::GetLastError() } == foundation::ERROR_INSUFFICIENT_BUFFER
            && needed > 0
            && needed <= MAX_SECURITY_BYTES,
        "token information size query failed"
    );
    let mut words = vec![0usize; (needed as usize).div_ceil(size_of::<usize>())];
    let mut returned = 0;
    check(unsafe {
        security::GetTokenInformation(
            token,
            class,
            words.as_mut_ptr().cast(),
            needed,
            &mut returned,
        )
    })?;
    ensure!(
        returned > 0 && returned <= needed,
        "token information buffer length changed"
    );
    Ok((words, returned as usize))
}

fn token_user(token: foundation::HANDLE) -> Result<Vec<u32>> {
    let (words, length) = token_information(token, security::TokenUser)?;
    ensure!(
        length >= size_of::<security::TOKEN_USER>(),
        "short TokenUser"
    );
    let user = unsafe { &*words.as_ptr().cast::<security::TOKEN_USER>() };
    copy_sid(user.User.Sid)
}

pub(crate) fn primary_user_sid() -> Result<Vec<u32>> {
    let mut token = 0;
    check(unsafe {
        threading::OpenProcessToken(
            threading::GetCurrentProcess(),
            security::TOKEN_QUERY,
            &mut token,
        )
    })?;
    let token = unsafe { OwnedHandle::from_raw_handle(token as _) };
    token_user(token.as_raw_handle() as foundation::HANDLE)
}

fn named_sid(name: &str, expected_kind: security::SID_NAME_USE) -> Result<Vec<u32>> {
    ensure!(
        !name.is_empty() && !name.contains('\0'),
        "invalid requested real user"
    );
    let wide = to_wide(name);
    let mut sid_bytes = 0;
    let mut domain_chars = 0;
    let mut kind = 0;
    let probe = unsafe {
        security::LookupAccountNameW(
            ptr::null(),
            wide.as_ptr(),
            ptr::null_mut(),
            &mut sid_bytes,
            ptr::null_mut(),
            &mut domain_chars,
            &mut kind,
        )
    };
    ensure!(
        probe == 0
            && unsafe { foundation::GetLastError() } == foundation::ERROR_INSUFFICIENT_BUFFER
            && (8..=MAX_SID_BYTES as u32).contains(&sid_bytes)
            && domain_chars <= 32768,
        "real user SID lookup failed or exceeded its bound"
    );
    let mut sid = vec![0u32; (sid_bytes as usize).div_ceil(size_of::<u32>())];
    let mut domain = vec![0u16; domain_chars as usize];
    check(unsafe {
        security::LookupAccountNameW(
            ptr::null(),
            wide.as_ptr(),
            sid.as_mut_ptr().cast(),
            &mut sid_bytes,
            domain.as_mut_ptr(),
            &mut domain_chars,
            &mut kind,
        )
    })?;
    ensure!(
        kind == expected_kind && sid_bytes as usize <= sid.len() * size_of::<u32>(),
        "requested account does not have the required native SID type"
    );
    copy_sid(sid.as_mut_ptr().cast())
}

/// Derive the caller name from its primary token SID; environment variables and
/// the thread impersonation identity are not a credential ownership authority.
pub(crate) fn native_primary_user_name() -> Result<String> {
    let sid = primary_user_sid()?;
    let mut name_chars = 0u32;
    let mut domain_chars = 0u32;
    let mut kind = 0;
    let probe = unsafe {
        security::LookupAccountSidW(
            ptr::null(),
            sid_ptr(&sid),
            ptr::null_mut(),
            &mut name_chars,
            ptr::null_mut(),
            &mut domain_chars,
            &mut kind,
        )
    };
    ensure!(
        probe == 0
            && unsafe { foundation::GetLastError() } == foundation::ERROR_INSUFFICIENT_BUFFER
            && (1..=32768).contains(&name_chars)
            && (1..=32768).contains(&domain_chars),
        "primary TokenUser account name sizing failed"
    );
    let mut name = vec![0u16; name_chars as usize];
    let mut domain = vec![0u16; domain_chars as usize];
    check(unsafe {
        security::LookupAccountSidW(
            ptr::null(),
            sid_ptr(&sid),
            name.as_mut_ptr(),
            &mut name_chars,
            domain.as_mut_ptr(),
            &mut domain_chars,
            &mut kind,
        )
    })?;
    ensure!(
        kind == security::SidTypeUser
            && name_chars > 0
            && domain_chars > 0
            && (name_chars as usize) < name.len()
            && (domain_chars as usize) < domain.len(),
        "primary token is not a bounded named native user"
    );
    let name = String::from_utf16(&name[..name_chars as usize])?;
    let domain = String::from_utf16(&domain[..domain_chars as usize])?;
    ensure!(
        !name.contains(['\\', '/', '\0']) && !domain.contains(['\\', '/', '\0']),
        "native primary user name has an unexpected separator"
    );
    let qualified = format!("{domain}\\{name}");
    ensure!(
        same_sid(&named_sid(&qualified, security::SidTypeUser)?, &sid),
        "native fully qualified caller name does not resolve back to its primary TokenUser"
    );
    Ok(qualified)
}

pub(crate) fn require_primary_user_name(name: &str) -> Result<()> {
    ensure!(
        same_sid(
            &named_sid(name, security::SidTypeUser)?,
            &primary_user_sid()?
        ),
        "explicit credential owner differs from the original caller primary TokenUser"
    );
    Ok(())
}

fn trusted_sids(real_user: Option<&str>) -> Result<[Vec<u32>; 3]> {
    let user = match real_user {
        Some(name) => {
            let supplied = named_sid(name, security::SidTypeUser)?;
            ensure!(
                same_sid(&supplied, &primary_user_sid()?),
                "requested credential owner does not match this process primary TokenUser; alternate-user elevation requires a separate authenticated caller binding"
            );
            supplied
        }
        None => primary_user_sid()?,
    };
    let system = known_sid(security::WinLocalSystemSid)?;
    let administrators = known_sid(security::WinBuiltinAdministratorsSid)?;
    ensure!(
        !same_sid(&user, &system) && !same_sid(&user, &administrators),
        "credential owner must be a distinct actual user"
    );
    Ok([user, system, administrators])
}

struct LocalDescriptor(security::PSECURITY_DESCRIPTOR);
impl Drop for LocalDescriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { foundation::LocalFree(self.0 as _) };
        }
    }
}

fn descriptor(sids: &[Vec<u32>; 3], directory: bool) -> Result<LocalDescriptor> {
    let real_user = crate::winutil::string_from_sid_bytes(unsafe {
        std::slice::from_raw_parts(
            sid_ptr(&sids[0]).cast::<u8>(),
            security::GetLengthSid(sid_ptr(&sids[0])) as usize,
        )
    })
    .map_err(anyhow::Error::msg)?;
    let inheritance = if directory { "OICI" } else { "" };
    // Administrators is an eligible owner during initial elevated provisioning;
    // the real user, SYSTEM and Administrators are the only allowed principals.
    let text = to_wide(format!(
        "O:BAG:BAD:P(A;{inheritance};FA;;;SY)(A;{inheritance};FA;;;BA)(A;{inheritance};FA;;;{real_user})"
    ));
    let mut raw = ptr::null_mut();
    check(unsafe {
        authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text.as_ptr(),
            authorization::SDDL_REVISION_1,
            &mut raw,
            ptr::null_mut(),
        )
    })?;
    Ok(LocalDescriptor(raw))
}

#[derive(Clone, Copy, PartialEq, Eq)]
struct ObjectState {
    identity: [u32; 3],
    attributes: u32,
    links: u32,
    bytes: u64,
    write_time: [u32; 2],
}

fn object_state(file: &File, directory: bool) -> Result<ObjectState> {
    let mut info: filesystem::BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    check(unsafe {
        filesystem::GetFileInformationByHandle(
            file.as_raw_handle() as foundation::HANDLE,
            &mut info,
        )
    })?;
    ensure!(
        info.dwFileAttributes & filesystem::FILE_ATTRIBUTE_REPARSE_POINT == 0
            && (info.dwFileAttributes & filesystem::FILE_ATTRIBUTE_DIRECTORY != 0) == directory
            && (directory || info.nNumberOfLinks == 1),
        "credential object is redirected, has the wrong kind, or has multiple links"
    );
    Ok(ObjectState {
        identity: [
            info.dwVolumeSerialNumber,
            info.nFileIndexHigh,
            info.nFileIndexLow,
        ],
        attributes: info.dwFileAttributes,
        links: info.nNumberOfLinks,
        bytes: (u64::from(info.nFileSizeHigh) << 32) | u64::from(info.nFileSizeLow),
        write_time: [
            info.ftLastWriteTime.dwHighDateTime,
            info.ftLastWriteTime.dwLowDateTime,
        ],
    })
}

fn open_directory(path: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .access_mode(filesystem::READ_CONTROL | filesystem::FILE_READ_ATTRIBUTES)
        .share_mode(filesystem::FILE_SHARE_READ | filesystem::FILE_SHARE_WRITE)
        .custom_flags(
            filesystem::FILE_FLAG_BACKUP_SEMANTICS | filesystem::FILE_FLAG_OPEN_REPARSE_POINT,
        )
        .open(path)?;
    object_state(&file, true)?;
    Ok(file)
}

fn retain_local_home(path: &Path) -> Result<(PathBuf, Vec<File>)> {
    ensure!(
        path.is_absolute()
            && matches!(path.components().next(),
            Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::VerbatimDisk(_)))
            && !path
                .components()
                .any(|part| matches!(part, Component::ParentDir)),
        "credential home must be an absolute local Windows path without parent traversal"
    );
    let mut ancestors = path.ancestors().collect::<Vec<_>>();
    ensure!(
        ancestors.len() <= 256,
        "credential home exceeds the ancestor bound"
    );
    ancestors.reverse();
    let mut handles = Vec::with_capacity(ancestors.len());
    for ancestor in ancestors {
        handles.push(
            open_directory(ancestor)
                .with_context(|| format!("retain credential ancestor {}", ancestor.display()))?,
        );
    }
    let canonical = std::fs::canonicalize(path)?;
    let expected = object_state(
        handles.last().context("credential home handle is absent")?,
        true,
    )?;
    ensure!(
        object_state(&open_directory(&canonical)?, true)?.identity == expected.identity,
        "canonical credential home differs from its retained native handle"
    );
    Ok((canonical, handles))
}

fn verify_security(file: &File, directory: bool, sids: &[Vec<u32>; 3]) -> Result<()> {
    object_state(file, directory)?;
    let mut owner = ptr::null_mut();
    let mut acl = ptr::null_mut();
    let mut raw = ptr::null_mut();
    let status = unsafe {
        authorization::GetSecurityInfo(
            file.as_raw_handle() as foundation::HANDLE,
            authorization::SE_FILE_OBJECT,
            security::OWNER_SECURITY_INFORMATION | security::DACL_SECURITY_INFORMATION,
            &mut owner,
            ptr::null_mut(),
            &mut acl,
            ptr::null_mut(),
            &mut raw,
        )
    };
    let descriptor = LocalDescriptor(raw);
    ensure!(
        status == 0
            && !descriptor.0.is_null()
            && unsafe { security::IsValidSecurityDescriptor(descriptor.0) } != 0
            && unsafe { security::GetSecurityDescriptorLength(descriptor.0) } <= MAX_SECURITY_BYTES,
        "credential handle security read failed: native status {status}"
    );
    ensure!(
        !owner.is_null()
            && sids
                .iter()
                .any(|sid| unsafe { security::EqualSid(owner, sid_ptr(sid)) != 0 }),
        "credential object owner is not a trusted real-user/SYSTEM/Administrators SID"
    );
    let mut present = 0;
    let mut defaulted = 0;
    let mut descriptor_acl = ptr::null_mut();
    check(unsafe {
        security::GetSecurityDescriptorDacl(
            descriptor.0,
            &mut present,
            &mut descriptor_acl,
            &mut defaulted,
        )
    })?;
    ensure!(
        present != 0 && defaulted == 0 && descriptor_acl == acl,
        "credential DACL is absent, defaulted or differs from its handle security descriptor"
    );
    let mut control = 0;
    let mut revision = 0;
    check(unsafe {
        security::GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision)
    })?;
    ensure!(
        revision == SECURITY_DESCRIPTOR_REVISION
            && control & security::SE_DACL_PROTECTED != 0
            && !acl.is_null()
            && unsafe { security::IsValidAcl(acl) } != 0,
        "credential DACL is null, inherited or invalid"
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
        (3..=32).contains(&info.AceCount),
        "credential DACL ACE count is outside its bound"
    );
    let mut allowed = [false; 3];
    for index in 0..info.AceCount {
        let mut raw_ace: *mut c_void = ptr::null_mut();
        check(unsafe { security::GetAce(acl, index, &mut raw_ace) })?;
        ensure!(!raw_ace.is_null(), "credential DACL contains a null ACE");
        let ace = unsafe { &*raw_ace.cast::<security::ACCESS_ALLOWED_ACE>() };
        ensure!(
            usize::from(ace.Header.AceSize) >= size_of::<security::ACCESS_ALLOWED_ACE>()
                && matches!(
                    ace.Header.AceType,
                    ACCESS_ALLOWED_ACE_TYPE | ACCESS_DENIED_ACE_TYPE
                ),
            "credential DACL has an unsupported ACE"
        );
        let sid = ptr::addr_of!(ace.SidStart).cast_mut().cast();
        ensure!(
            unsafe { security::IsValidSid(sid) } != 0
                && usize::from(ace.Header.AceSize)
                    == size_of::<security::ACCESS_ALLOWED_ACE>() - size_of::<u32>()
                        + unsafe { security::GetLengthSid(sid) } as usize,
            "credential ACE has an invalid native SID or size"
        );
        if ace.Header.AceType == ACCESS_ALLOWED_ACE_TYPE {
            let trusted = sids
                .iter()
                .position(|value| unsafe { security::EqualSid(sid, sid_ptr(value)) != 0 })
                .context("credential DACL grants access outside the three trusted principals")?;
            ensure!(
                !allowed[trusted]
                    && u32::from(ace.Header.AceFlags)
                        & !(security::OBJECT_INHERIT_ACE | security::CONTAINER_INHERIT_ACE)
                        == 0
                    && (ace.Mask == foundation::GENERIC_ALL
                        || ace.Mask & !filesystem::FILE_ALL_ACCESS == 0),
                "credential allow ACE is duplicated, inherited or has unsupported access bits"
            );
            allowed[trusted] = true;
        }
    }
    ensure!(
        allowed.into_iter().all(|present| present),
        "credential DACL lacks a required trusted principal"
    );
    Ok(())
}

pub struct ProtectedCredentialStore {
    path: PathBuf,
    directory: File,
    parents: Vec<File>,
    trusted: [Vec<u32>; 3],
}

pub struct ProtectedCredentialFile {
    path: PathBuf,
    file: File,
    store: ProtectedCredentialStore,
    identity: [u32; 3],
    first_write_available: bool,
}

pub enum ProtectedCredentialState {
    Existing(ProtectedCredentialFile),
    Vacant(ProtectedCredentialStore),
}

impl ProtectedCredentialStore {
    fn open(codex_home: &Path, real_user: Option<&str>, create: bool) -> Result<Option<Self>> {
        let legacy = crate::setup::sandbox_dir(codex_home).join(USERS_FILE);
        ensure!(
            !legacy.try_exists()?,
            "legacy sandbox credential evidence is present; automatic deletion or migration is refused"
        );
        let trusted = trusted_sids(real_user)?;
        let (home, parents) = retain_local_home(codex_home)?;
        let path = sandbox_secrets_dir(&home);
        let directory = match open_directory(&path) {
            Ok(file) => file,
            Err(error)
                if error
                    .downcast_ref::<std::io::Error>()
                    .is_some_and(|io| matches!(io.raw_os_error(), Some(2 | 3))) =>
            {
                if !create {
                    return Ok(None);
                }
                let descriptor = descriptor(&trusted, true)?;
                let attributes = security::SECURITY_ATTRIBUTES {
                    nLength: size_of::<security::SECURITY_ATTRIBUTES>() as u32,
                    lpSecurityDescriptor: descriptor.0,
                    bInheritHandle: 0,
                };
                check(unsafe {
                    filesystem::CreateDirectoryW(to_wide(path.as_os_str()).as_ptr(), &attributes)
                })
                .context(
                    "create protected credential directory without adopting an existing object",
                )?;
                open_directory(&path)?
            }
            Err(error) => return Err(error),
        };
        verify_security(&directory, true, &trusted)?;
        let store = Self {
            path,
            directory,
            parents,
            trusted,
        };
        store.verify()?;
        Ok(Some(store))
    }

    fn verify(&self) -> Result<()> {
        ensure!(
            !self.parents.is_empty(),
            "credential ancestor custody was lost"
        );
        let expected = object_state(&self.directory, true)?;
        ensure!(
            object_state(&open_directory(&self.path)?, true)?.identity == expected.identity,
            "credential directory path no longer names the retained object"
        );
        verify_security(&self.directory, true, &self.trusted)
    }

    fn open_existing(self) -> Result<ProtectedCredentialState> {
        self.verify()?;
        let path = self.path.join(USERS_FILE);
        let file = match OpenOptions::new()
            .access_mode(foundation::GENERIC_READ | filesystem::READ_CONTROL)
            .share_mode(filesystem::FILE_SHARE_READ)
            .custom_flags(filesystem::FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&path)
        {
            Ok(file) => file,
            Err(error) if error.raw_os_error() == Some(foundation::ERROR_FILE_NOT_FOUND as i32) => {
                return Ok(ProtectedCredentialState::Vacant(self));
            }
            Err(error) => return Err(error).context("open protected sandbox credentials"),
        };
        let identity = object_state(&file, false)?.identity;
        let value = ProtectedCredentialFile {
            path,
            file,
            store: self,
            identity,
            first_write_available: false,
        };
        value.verify()?;
        Ok(ProtectedCredentialState::Existing(value))
    }

    pub fn create_users_file(self) -> Result<ProtectedCredentialFile> {
        self.verify()?;
        let path = self.path.join(USERS_FILE);
        let descriptor = descriptor(&self.trusted, false)?;
        let attributes = security::SECURITY_ATTRIBUTES {
            nLength: size_of::<security::SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: descriptor.0,
            bInheritHandle: 0,
        };
        let handle = unsafe {
            filesystem::CreateFileW(
                to_wide(path.as_os_str()).as_ptr(),
                foundation::GENERIC_READ | foundation::GENERIC_WRITE | filesystem::READ_CONTROL,
                filesystem::FILE_SHARE_READ,
                &attributes,
                filesystem::CREATE_NEW,
                filesystem::FILE_ATTRIBUTE_NORMAL | filesystem::FILE_FLAG_OPEN_REPARSE_POINT,
                0,
            )
        };
        if handle == foundation::INVALID_HANDLE_VALUE {
            return Err(std::io::Error::last_os_error())
                .context("CREATE_NEW protected sandbox credentials");
        }
        let file = unsafe { File::from_raw_handle(handle as _) };
        let identity = object_state(&file, false)?.identity;
        let value = ProtectedCredentialFile {
            path,
            file,
            store: self,
            identity,
            first_write_available: true,
        };
        value.verify()?;
        ensure!(
            object_state(&value.file, false)?.bytes == 0,
            "new credential file is not empty"
        );
        Ok(value)
    }
}

impl ProtectedCredentialFile {
    fn verify(&self) -> Result<()> {
        self.store.verify()?;
        let state = object_state(&self.file, false)?;
        ensure!(
            state.identity == self.identity && state.bytes <= MAX_SECRET_BYTES,
            "credential object identity or byte bound changed"
        );
        let named = OpenOptions::new()
            .access_mode(filesystem::READ_CONTROL | filesystem::FILE_READ_ATTRIBUTES)
            .share_mode(filesystem::FILE_SHARE_READ | filesystem::FILE_SHARE_WRITE)
            .custom_flags(filesystem::FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&self.path)?;
        ensure!(
            object_state(&named, false)?.identity == self.identity,
            "credential path no longer names the retained file"
        );
        verify_security(&self.file, false, &self.store.trusted)
    }

    fn read_bytes(&mut self) -> Result<Vec<u8>> {
        self.verify()?;
        let before = object_state(&self.file, false)?;
        self.file.seek(SeekFrom::Start(0))?;
        let mut raw = Vec::with_capacity(before.bytes as usize);
        (&mut self.file)
            .take(MAX_SECRET_BYTES + 1)
            .read_to_end(&mut raw)?;
        ensure!(
            raw.len() as u64 == before.bytes && object_state(&self.file, false)? == before,
            "credential bytes changed while the original handle was read"
        );
        self.verify()?;
        Ok(raw)
    }

    pub fn write_new_users(&mut self, raw: &[u8]) -> Result<()> {
        ensure!(
            self.first_write_available && !raw.is_empty() && raw.len() as u64 <= MAX_SECRET_BYTES,
            "credential write is not the original bounded CREATE_NEW operation"
        );
        self.first_write_available = false;
        self.verify()?;
        ensure!(
            object_state(&self.file, false)?.bytes == 0,
            "credential first-write file is not empty"
        );
        self.file.seek(SeekFrom::Start(0))?;
        self.file.write_all(raw)?;
        self.file.sync_all()?;
        ensure!(
            self.read_bytes()?.as_slice() == raw,
            "credential same-handle durable readback differs"
        );
        Ok(())
    }

    pub fn verify_existing_accounts(&mut self) -> Result<()> {
        let users = parse_users(&self.read_bytes()?)?;
        let _offline = validate_record(&users.offline, &self.store.trusted[0])?;
        let _online = validate_record(&users.online, &self.store.trusted[0])?;
        self.verify()
    }
}

pub fn prepare_protected_sandbox_credentials(
    codex_home: &Path,
    real_user: &str,
) -> Result<ProtectedCredentialState> {
    (|| {
        ProtectedCredentialStore::open(codex_home, Some(real_user), true)?
            .context("protected credential directory is absent")?
            .open_existing()
    })()
    .map_err(|error: anyhow::Error| {
        fail(
            SetupErrorCode::HelperCredentialStoreUnsafe,
            format!("protected credential preparation failed: {error:#}"),
        )
    })
}

fn existing_file(codex_home: &Path) -> Result<Option<ProtectedCredentialFile>> {
    // A genuinely absent home has no credential bytes to consume. Permission,
    // redirection and malformed-object failures are not converted into absence.
    if !codex_home.try_exists()? {
        return Ok(None);
    }
    let Some(store) = ProtectedCredentialStore::open(codex_home, None, false)? else {
        return Ok(None);
    };
    match store.open_existing()? {
        ProtectedCredentialState::Existing(file) => Ok(Some(file)),
        ProtectedCredentialState::Vacant(_) => Ok(None),
    }
}

fn parse_users(raw: &[u8]) -> Result<SandboxUsersFile> {
    let users: SandboxUsersFile =
        serde_json::from_slice(raw).context("parse retained sandbox credentials")?;
    ensure!(
        users.version_matches()
            && users.offline.username == OFFLINE_USERNAME
            && users.online.username == ONLINE_USERNAME,
        "credential version or fixed local account names do not match"
    );
    Ok(users)
}

pub(crate) fn read_protected_users(codex_home: &Path) -> Result<Option<SandboxUsersFile>> {
    let Some(mut file) = existing_file(codex_home)? else {
        return Ok(None);
    };
    parse_users(&file.read_bytes()?).map(Some)
}

pub fn verify_protected_sandbox_credentials(codex_home: &Path, real_user: &str) -> Result<()> {
    let store = ProtectedCredentialStore::open(codex_home, Some(real_user), false)?
        .context("protected credential directory is absent")?;
    match store.open_existing()? {
        ProtectedCredentialState::Existing(mut file) => file.verify_existing_accounts(),
        ProtectedCredentialState::Vacant(_) => anyhow::bail!("protected credential file is absent"),
    }
}

struct NetBuffer(*mut u8);
impl Drop for NetBuffer {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { net::NetApiBufferFree(self.0.cast()) };
        }
    }
}

fn local_user_sid(username: &str) -> Result<Option<Vec<u32>>> {
    ensure!(
        matches!(username, OFFLINE_USERNAME | ONLINE_USERNAME),
        "unexpected sandbox account name"
    );
    let mut raw = ptr::null_mut();
    let status =
        unsafe { net::NetUserGetInfo(ptr::null(), to_wide(username).as_ptr(), 23, &mut raw) };
    let buffer = NetBuffer(raw);
    if status == NERR_USER_NOT_FOUND {
        return Ok(None);
    }
    ensure!(
        status == net::NERR_Success && !buffer.0.is_null(),
        "local account lookup failed for {username}: native status {status}"
    );
    let user = unsafe { &*buffer.0.cast::<net::USER_INFO_23>() };
    copy_sid(user.usri23_user_sid).map(Some)
}

fn sid_bytes(sid: &[u32]) -> Vec<u8> {
    unsafe {
        std::slice::from_raw_parts(
            sid_ptr(sid).cast::<u8>(),
            security::GetLengthSid(sid_ptr(sid)) as usize,
        )
        .to_vec()
    }
}

fn local_private_group_sid() -> Result<Vec<u32>> {
    let mut computer = [0u16; 256];
    let mut length = computer.len() as u32;
    check(unsafe {
        windows_sys::Win32::System::WindowsProgramming::GetComputerNameW(
            computer.as_mut_ptr(),
            &mut length,
        )
    })?;
    ensure!(
        length > 0 && length < computer.len() as u32,
        "invalid native local computer name length"
    );
    let computer = String::from_utf16(&computer[..length as usize])?;
    ensure!(
        !computer.contains(['\\', '/', '\0']),
        "invalid native local computer name"
    );
    named_sid(
        &format!("{computer}\\{SANDBOX_USERS_GROUP}"),
        security::SidTypeAlias,
    )
}

pub fn local_private_sandbox_group_sid() -> Result<Vec<u8>> {
    local_private_group_sid().map(|sid| sid_bytes(&sid))
}

pub fn local_private_sandbox_account_sid(username: &str) -> Result<Vec<u8>> {
    local_user_sid(username)?
        .context("fixed local sandbox account is absent")
        .map(|sid| sid_bytes(&sid))
}

pub fn require_private_accounts_absent() -> Result<()> {
    let offline = local_user_sid(OFFLINE_USERNAME)?;
    let online = local_user_sid(ONLINE_USERNAME)?;
    if offline.is_some() || online.is_some() {
        return Err(fail(
            SetupErrorCode::HelperExistingAccountCredentialsMissing,
            format!(
                "this home has no matching protected credentials; local account presence: offline={}, online={}; no account is adopted or reset",
                offline.is_some(),
                online.is_some()
            ),
        ));
    }
    Ok(())
}

struct SecretText(String);
impl Drop for SecretText {
    fn drop(&mut self) {
        for byte in unsafe { self.0.as_bytes_mut() } {
            unsafe { ptr::write_volatile(byte, 0) };
        }
    }
}

struct SecretWide(Vec<u16>);
impl Drop for SecretWide {
    fn drop(&mut self) {
        for value in &mut self.0 {
            unsafe { ptr::write_volatile(value, 0) };
        }
    }
}

fn validate_record(
    record: &crate::setup::SandboxUserRecord,
    host_sid: &[u32],
) -> Result<SecretText> {
    let encrypted = BASE64
        .decode(record.password.as_bytes())
        .context("decode protected credential")?;
    let mut clear = dpapi::unprotect(&encrypted).context("unprotect retained credential")?;
    let decoded = std::str::from_utf8(&clear)
        .map(str::to_owned)
        .context("protected credential password is not UTF8");
    for byte in &mut clear {
        unsafe { ptr::write_volatile(byte, 0) };
    }
    let password = SecretText(decoded?);
    ensure!(
        !password.0.is_empty() && !password.0.contains('\0'),
        "invalid protected password encoding"
    );
    let expected =
        local_user_sid(&record.username)?.context("protected sandbox account is absent")?;
    ensure!(
        !same_sid(&expected, host_sid),
        "sandbox credential resolves to the real host user"
    );
    let wide_password = SecretWide(to_wide(&password.0));
    let mut token = 0;
    let ok = unsafe {
        security::LogonUserW(
            to_wide(&record.username).as_ptr(),
            to_wide(".").as_ptr(),
            wide_password.0.as_ptr(),
            security::LOGON32_LOGON_INTERACTIVE,
            security::LOGON32_PROVIDER_DEFAULT,
            &mut token,
        )
    };
    let logon_error = unsafe { foundation::GetLastError() };
    if ok == 0 {
        return Err(fail(
            SetupErrorCode::HelperCredentialIdentityInvalid,
            format!(
                "local sandbox LogonUserW verification failed for {}: native status {logon_error}",
                record.username
            ),
        ));
    }
    let token = unsafe { OwnedHandle::from_raw_handle(token as _) };
    let user = token_user(token.as_raw_handle() as foundation::HANDLE)?;
    ensure!(
        same_sid(&user, &expected) && !same_sid(&user, host_sid),
        "authenticated sandbox token SID differs from the local account or equals the host"
    );
    let administrators = known_sid(security::WinBuiltinAdministratorsSid)?;
    let system = known_sid(security::WinLocalSystemSid)?;
    ensure!(
        !same_sid(&user, &administrators) && !same_sid(&user, &system),
        "sandbox user is a privileged principal"
    );
    let (words, length) = token_information(
        token.as_raw_handle() as foundation::HANDLE,
        security::TokenGroups,
    )?;
    ensure!(
        length >= size_of::<security::TOKEN_GROUPS>(),
        "short TokenGroups"
    );
    let groups = unsafe { &*words.as_ptr().cast::<security::TOKEN_GROUPS>() };
    let count = groups.GroupCount as usize;
    let offset = std::mem::offset_of!(security::TOKEN_GROUPS, Groups);
    ensure!(
        count <= 1024 && offset + count * size_of::<security::SID_AND_ATTRIBUTES>() <= length,
        "sandbox group list exceeds the native buffer"
    );
    let entries = unsafe { std::slice::from_raw_parts(groups.Groups.as_ptr(), count) };
    // The qualified local alias supplies the actual deny-group SID. An external
    // domain with the same display name must not satisfy the isolation boundary.
    let private_group = local_private_group_sid()?;
    let mut same_local_domain = 0;
    check(unsafe {
        security::EqualDomainSid(
            sid_ptr(&expected),
            sid_ptr(&private_group),
            &mut same_local_domain,
        )
    })?;
    ensure!(
        same_local_domain != 0,
        "sandbox user and isolation alias are not in the same native local account domain"
    );
    let mut private_group_enabled = false;
    for entry in entries {
        ensure!(
            unsafe { security::IsValidSid(entry.Sid) } != 0
                && unsafe { security::EqualSid(entry.Sid, sid_ptr(&administrators)) } == 0,
            "sandbox token contains Administrators, including a disabled or deny-only group"
        );
        if unsafe { security::EqualSid(entry.Sid, sid_ptr(&private_group)) } != 0 {
            ensure!(
                !private_group_enabled
                    && entry.Attributes & system_services::SE_GROUP_ENABLED as u32 != 0
                    && entry.Attributes & system_services::SE_GROUP_USE_FOR_DENY_ONLY as u32 == 0,
                "sandbox local deny-group is duplicated, disabled or deny-only"
            );
            private_group_enabled = true;
        }
    }
    ensure!(
        private_group_enabled,
        "authenticated sandbox token lacks its enabled local isolation group"
    );
    let after = local_user_sid(&record.username)?
        .context("sandbox account disappeared during verification")?;
    ensure!(
        same_sid(&after, &expected),
        "sandbox account SID changed during native authentication"
    );
    Ok(password)
}

pub(crate) fn verified_identity(
    codex_home: &Path,
    identity: SandboxNetworkIdentity,
) -> Result<Option<(String, String)>> {
    let Some(mut file) = existing_file(codex_home)? else {
        return Ok(None);
    };
    let users = parse_users(&file.read_bytes()?)?;
    let offline = validate_record(&users.offline, &file.store.trusted[0])?;
    let online = validate_record(&users.online, &file.store.trusted[0])?;
    file.verify()?;
    let chosen = match identity {
        SandboxNetworkIdentity::Offline => (users.offline.username, offline.0.clone()),
        SandboxNetworkIdentity::Online => (users.online.username, online.0.clone()),
    };
    Ok(Some(chosen))
}

// These helpers are used only by the explicitly owned hosted test lifecycle.
// They reuse the production native object checks; they never grant a sandbox
// capability access to the owner, lock, manifest or historical evidence.
#[cfg(test)]
pub(crate) struct HostedPrivateRoot {
    path: PathBuf,
    handles: Vec<File>,
    trusted: [Vec<u32>; 3],
}

#[cfg(test)]
impl HostedPrivateRoot {
    pub(crate) fn open(path: &Path) -> Result<Self> {
        let (path, handles) = retain_local_home(path)?;
        let trusted = trusted_sids(None)?;
        verify_security(
            handles.last().context("hosted root handle is absent")?,
            true,
            &trusted,
        )?;
        Ok(Self {
            path,
            handles,
            trusted,
        })
    }

    pub(crate) fn path(&self) -> &Path {
        &self.path
    }

    fn path_for(&self, name: &str) -> Result<PathBuf> {
        ensure!(
            !name.is_empty()
                && Path::new(name).components().count() == 1
                && matches!(
                    Path::new(name).components().next(),
                    Some(Component::Normal(_))
                ),
            "hosted evidence requires one normal filename"
        );
        verify_security(
            self.handles
                .last()
                .context("hosted root custody is absent")?,
            true,
            &self.trusted,
        )?;
        Ok(self.path.join(name))
    }

    pub(crate) fn open_file(&self, name: &str, write: bool, shared_write: bool) -> Result<File> {
        let path = self.path_for(name)?;
        let file = OpenOptions::new()
            .access_mode(
                foundation::GENERIC_READ
                    | filesystem::READ_CONTROL
                    | if write { foundation::GENERIC_WRITE } else { 0 },
            )
            .share_mode(
                filesystem::FILE_SHARE_READ
                    | if shared_write {
                        filesystem::FILE_SHARE_WRITE
                    } else {
                        0
                    },
            )
            .custom_flags(filesystem::FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&path)?;
        object_state(&file, false)?;
        verify_security(&file, false, &self.trusted)?;
        Ok(file)
    }

    pub(crate) fn create_file(&self, name: &str, raw: &[u8]) -> Result<File> {
        ensure!(
            raw.len() as u64 <= MAX_SECRET_BYTES,
            "hosted evidence exceeds its fixed byte bound"
        );
        let path = self.path_for(name)?;
        let sd = descriptor(&self.trusted, false)?;
        let attributes = security::SECURITY_ATTRIBUTES {
            nLength: size_of::<security::SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: sd.0,
            bInheritHandle: 0,
        };
        let handle = unsafe {
            filesystem::CreateFileW(
                to_wide(path.as_os_str()).as_ptr(),
                foundation::GENERIC_READ | foundation::GENERIC_WRITE | filesystem::READ_CONTROL,
                filesystem::FILE_SHARE_READ,
                &attributes,
                filesystem::CREATE_NEW,
                filesystem::FILE_ATTRIBUTE_NORMAL | filesystem::FILE_FLAG_OPEN_REPARSE_POINT,
                0,
            )
        };
        if handle == foundation::INVALID_HANDLE_VALUE {
            return Err(std::io::Error::last_os_error())
                .context("CREATE_NEW protected hosted evidence");
        }
        let mut file = unsafe { File::from_raw_handle(handle as _) };
        let identity = object_state(&file, false)?.identity;
        verify_security(&file, false, &self.trusted)?;
        file.write_all(raw)?;
        file.sync_all()?;
        file.seek(SeekFrom::Start(0))?;
        let mut readback = Vec::new();
        (&mut file)
            .take(MAX_SECRET_BYTES + 1)
            .read_to_end(&mut readback)?;
        ensure!(
            readback == raw && object_state(&file, false)?.identity == identity,
            "protected hosted evidence same-handle write/readback differs"
        );
        verify_security(&file, false, &self.trusted)?;
        Ok(file)
    }

    pub(crate) fn read(&self, name: &str) -> Result<Vec<u8>> {
        let mut file = self.open_file(name, false, false)?;
        let before = object_state(&file, false)?;
        ensure!(
            before.bytes <= MAX_SECRET_BYTES,
            "hosted evidence exceeds its fixed byte bound"
        );
        let mut raw = Vec::with_capacity(before.bytes as usize);
        (&mut file)
            .take(MAX_SECRET_BYTES + 1)
            .read_to_end(&mut raw)?;
        ensure!(
            raw.len() as u64 == before.bytes && object_state(&file, false)? == before,
            "hosted evidence changed during its retained read"
        );
        Ok(raw)
    }
}

#[cfg(test)]
pub(crate) fn verify_hosted_owner_token(token: foundation::HANDLE) -> Result<()> {
    ensure!(
        same_sid(&token_user(token)?, &primary_user_sid()?),
        "hosted owner and test have different primary user SIDs"
    );
    Ok(())
}

#[cfg(test)]
pub(crate) fn hosted_credential_bytes(home: &Path) -> Result<Vec<u8>> {
    let mut file = existing_file(home)?.context("owned fixture credentials are absent")?;
    let raw = file.read_bytes()?;
    let _validated_format = parse_users(&raw)?;
    Ok(raw)
}
