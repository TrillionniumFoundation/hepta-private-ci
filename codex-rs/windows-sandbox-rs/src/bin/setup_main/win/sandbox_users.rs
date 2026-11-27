use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64;
use rand::RngCore;
use rand::rngs::OsRng;
use serde::Serialize;
use std::ffi::OsStr;
use std::ffi::c_void;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::GENERIC_WRITE;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::NetworkManagement::NetManagement::LOCALGROUP_INFO_1;
use windows_sys::Win32::NetworkManagement::NetManagement::LOCALGROUP_MEMBERS_INFO_0;
use windows_sys::Win32::NetworkManagement::NetManagement::NERR_Success;
use windows_sys::Win32::NetworkManagement::NetManagement::NetLocalGroupAdd;
use windows_sys::Win32::NetworkManagement::NetManagement::NetLocalGroupAddMembers;
use windows_sys::Win32::NetworkManagement::NetManagement::NetUserAdd;
use windows_sys::Win32::NetworkManagement::NetManagement::UF_DONT_EXPIRE_PASSWD;
use windows_sys::Win32::NetworkManagement::NetManagement::UF_SCRIPT;
use windows_sys::Win32::NetworkManagement::NetManagement::USER_INFO_1;
use windows_sys::Win32::NetworkManagement::NetManagement::USER_PRIV_USER;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::ConvertStringSidToSidW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::LookupAccountNameW;
use windows_sys::Win32::Security::LookupAccountSidW;
use windows_sys::Win32::Security::PSECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::SID_NAME_USE;
use windows_sys::Win32::Storage::FileSystem::CREATE_NEW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;

use codex_windows_sandbox::SETUP_VERSION;
use codex_windows_sandbox::SetupErrorCode;
use codex_windows_sandbox::SetupFailure;
use codex_windows_sandbox::dpapi_protect;
use codex_windows_sandbox::sandbox_dir;
use codex_windows_sandbox::string_from_sid_bytes;
use codex_windows_sandbox::to_wide;

use codex_windows_sandbox::ProtectedCredentialFile;
use codex_windows_sandbox::ProtectedCredentialState;
use codex_windows_sandbox::SANDBOX_USERS_GROUP;
use codex_windows_sandbox::prepare_protected_sandbox_credentials;
use codex_windows_sandbox::require_private_accounts_absent;
const SANDBOX_USERS_GROUP_COMMENT: &str = "Codex sandbox internal group (managed)";
const SID_ADMINISTRATORS: &str = "S-1-5-32-544";
const SID_USERS: &str = "S-1-5-32-545";
const SID_AUTHENTICATED_USERS: &str = "S-1-5-11";
const SID_EVERYONE: &str = "S-1-1-0";
const SID_SYSTEM: &str = "S-1-5-18";

pub fn ensure_sandbox_users_group(log: &mut dyn Write) -> Result<()> {
    ensure_local_group(SANDBOX_USERS_GROUP, SANDBOX_USERS_GROUP_COMMENT, log)
}

pub fn resolve_sandbox_users_group_sid() -> Result<Vec<u8>> {
    codex_windows_sandbox::local_private_sandbox_group_sid()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProvisioningOutcome {
    Created,
    Reused,
}

pub fn provision_sandbox_users(
    codex_home: &Path,
    real_user: &str,
    offline_username: &str,
    online_username: &str,
    log: &mut dyn Write,
) -> Result<ProvisioningOutcome> {
    ensure!(
        offline_username == codex_windows_sandbox::OFFLINE_USERNAME
            && online_username == codex_windows_sandbox::ONLINE_USERNAME,
        "provisioning must name the two fixed local sandbox accounts"
    );
    let store = match prepare_protected_sandbox_credentials(codex_home, real_user)? {
        ProtectedCredentialState::Existing(mut file) => {
            file.verify_existing_accounts()
                .context("existing protected sandbox credentials failed native identity verification; no reset attempted")?;
            super::log_line(
                log,
                "reusing verified local sandbox identities; password and ciphertext are unchanged",
            )?;
            return Ok(ProvisioningOutcome::Reused);
        }
        ProtectedCredentialState::Vacant(store) => store,
    };
    // An account without this home's verified credentials is not ours to adopt.
    // A race after this read remains a nonzero NetUserAdd failure, never a reset.
    require_private_accounts_absent()?;
    let mut file = store.create_users_file()?;
    let offline_password = random_password()?;
    let online_password = random_password()?;
    let mut phase = "sandbox-group";
    let result = (|| {
        ensure_sandbox_users_group(log)?;
        phase = "offline-account-create";
        ensure_sandbox_user(offline_username, &offline_password.0, log)?;
        phase = "online-account-create";
        ensure_sandbox_user(online_username, &online_password.0, log)?;
        phase = "same-handle-protected-store-write";
        write_secrets(
            &mut file,
            offline_username,
            &offline_password.0,
            online_username,
            &online_password.0,
        )?;
        phase = "native-credential-readback";
        file.verify_existing_accounts()?;
        Ok::<(), anyhow::Error>(())
    })();
    if let Err(error) = result {
        // Keep partial accounts and the CREATE_NEW file as failure evidence.
        // Neither cleanup nor a later retry rotates a password or deletes the file.
        return Err(error).with_context(|| format!(
            "sandbox provisioning stopped in {phase}; partial account/store state is retained and readiness is not committed"
        ));
    }
    Ok(ProvisioningOutcome::Created)
}

pub fn ensure_sandbox_user(username: &str, password: &str, log: &mut dyn Write) -> Result<()> {
    ensure_local_user(username, password, log)?;
    ensure_local_group_member(SANDBOX_USERS_GROUP, username)?;
    Ok(())
}

pub fn ensure_local_user(name: &str, password: &str, log: &mut dyn Write) -> Result<()> {
    let name_w = to_wide(OsStr::new(name));
    let pwd_w = PasswordWide(to_wide(OsStr::new(password)));
    unsafe {
        let info = USER_INFO_1 {
            usri1_name: name_w.as_ptr() as *mut u16,
            usri1_password: pwd_w.0.as_ptr() as *mut u16,
            usri1_password_age: 0,
            usri1_priv: USER_PRIV_USER,
            usri1_home_dir: std::ptr::null_mut(),
            usri1_comment: std::ptr::null_mut(),
            usri1_flags: UF_SCRIPT | UF_DONT_EXPIRE_PASSWD,
            usri1_script_path: std::ptr::null_mut(),
        };
        let status = NetUserAdd(
            std::ptr::null(),
            1,
            &info as *const _ as *mut u8,
            std::ptr::null_mut(),
        );
        if status != NERR_Success {
            let message = format!(
                "create local sandbox user {name} failed: native status {status}; existing accounts are never adopted or reset"
            );
            let log_error = super::log_line(log, &message).err();
            let message = match log_error {
                Some(error) => format!(
                    "{message}; additionally the failure log could not be written: {error:#}"
                ),
                None => message,
            };
            return Err(anyhow::Error::new(SetupFailure::new(
                SetupErrorCode::HelperUserCreateFailed,
                message,
            )));
        }
        super::log_line(
            log,
            &format!("NetUserAdd created local sandbox user {name}"),
        )?;

        // A regular Users membership is required; an unexpected native error
        // cannot be reported as successful provisioning.
        let group_name = lookup_account_name_for_sid(SID_USERS)
            .context("resolve local Users group for newly created sandbox account")?;
        ensure_local_group_member(&group_name, name)?;
    }
    Ok(())
}

pub fn ensure_local_group(name: &str, comment: &str, log: &mut dyn Write) -> Result<()> {
    const ERROR_ALIAS_EXISTS: u32 = 1379;
    const NERR_GROUP_EXISTS: u32 = 2223;

    let name_w = to_wide(OsStr::new(name));
    let comment_w = to_wide(OsStr::new(comment));
    unsafe {
        let info = LOCALGROUP_INFO_1 {
            lgrpi1_name: name_w.as_ptr() as *mut u16,
            lgrpi1_comment: comment_w.as_ptr() as *mut u16,
        };
        let mut parm_err: u32 = 0;
        let status = NetLocalGroupAdd(
            std::ptr::null(),
            1,
            &info as *const _ as *mut u8,
            &mut parm_err as *mut _,
        );
        if status != NERR_Success && status != ERROR_ALIAS_EXISTS && status != NERR_GROUP_EXISTS {
            super::log_line(
                log,
                &format!("NetLocalGroupAdd failed for {name} code {status} parm_err={parm_err}"),
            )?;
            return Err(anyhow::Error::new(SetupFailure::new(
                SetupErrorCode::HelperUsersGroupCreateFailed,
                format!("failed to create local group {name}, code {status}"),
            )));
        }
    }
    Ok(())
}

pub fn ensure_local_group_member(group_name: &str, member_name: &str) -> Result<()> {
    const ERROR_MEMBER_IN_ALIAS: u32 = 1378;
    let group_w = to_wide(OsStr::new(group_name));
    let mut sid = codex_windows_sandbox::local_private_sandbox_account_sid(member_name)?;
    let member = LOCALGROUP_MEMBERS_INFO_0 {
        lgrmi0_sid: sid.as_mut_ptr().cast(),
    };
    let status = unsafe {
        NetLocalGroupAddMembers(
            std::ptr::null(),
            group_w.as_ptr(),
            0,
            &member as *const _ as *mut u8,
            1,
        )
    };
    if status != NERR_Success && status != ERROR_MEMBER_IN_ALIAS {
        return Err(anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperUserGroupMembershipFailed,
            format!(
                "add local sandbox user {member_name} to group {group_name} failed: native status {status}"
            ),
        )));
    }
    Ok(())
}

pub fn resolve_sid(name: &str) -> Result<Vec<u8>> {
    if let Some(sid_str) = well_known_sid_str(name) {
        return sid_bytes_from_string(sid_str);
    }
    let name_w = to_wide(OsStr::new(name));
    let mut sid_buffer = vec![0u8; 68];
    let mut sid_len: u32 = sid_buffer.len() as u32;
    let mut domain: Vec<u16> = Vec::new();
    let mut domain_len: u32 = 0;
    let mut use_type: SID_NAME_USE = 0;
    loop {
        let ok = unsafe {
            LookupAccountNameW(
                std::ptr::null(),
                name_w.as_ptr(),
                sid_buffer.as_mut_ptr() as *mut c_void,
                &mut sid_len,
                domain.as_mut_ptr(),
                &mut domain_len,
                &mut use_type,
            )
        };
        if ok != 0 {
            sid_buffer.truncate(sid_len as usize);
            return Ok(sid_buffer);
        }
        let err = unsafe { GetLastError() };
        if err == ERROR_INSUFFICIENT_BUFFER {
            sid_buffer.resize(sid_len as usize, 0);
            domain.resize(domain_len as usize, 0);
            continue;
        }
        return Err(anyhow::anyhow!(
            "LookupAccountNameW failed for {name}: {err}"
        ));
    }
}

fn well_known_sid_str(name: &str) -> Option<&'static str> {
    match name {
        "Administrators" => Some(SID_ADMINISTRATORS),
        "Users" => Some(SID_USERS),
        "Authenticated Users" => Some(SID_AUTHENTICATED_USERS),
        "Everyone" => Some(SID_EVERYONE),
        "SYSTEM" => Some(SID_SYSTEM),
        _ => None,
    }
}

fn sid_bytes_from_string(sid_str: &str) -> Result<Vec<u8>> {
    let sid_w = to_wide(OsStr::new(sid_str));
    let mut psid: *mut c_void = std::ptr::null_mut();
    if unsafe { ConvertStringSidToSidW(sid_w.as_ptr(), &mut psid) } == 0 {
        return Err(anyhow::anyhow!(
            "ConvertStringSidToSidW failed for {sid_str}: {}",
            unsafe { GetLastError() }
        ));
    }
    let sid_len = unsafe { GetLengthSid(psid) };
    if sid_len == 0 {
        unsafe {
            LocalFree(psid as _);
        }
        return Err(anyhow::anyhow!("GetLengthSid failed for {sid_str}"));
    }
    let mut out = vec![0u8; sid_len as usize];
    let ok = unsafe { CopySid(sid_len, out.as_mut_ptr() as *mut c_void, psid) };
    unsafe {
        LocalFree(psid as _);
    }
    if ok == 0 {
        return Err(anyhow::anyhow!("CopySid failed for {sid_str}"));
    }
    Ok(out)
}

fn lookup_account_name_for_sid(sid_str: &str) -> Result<String> {
    let sid_w = to_wide(OsStr::new(sid_str));
    let mut psid: *mut c_void = std::ptr::null_mut();
    if unsafe { ConvertStringSidToSidW(sid_w.as_ptr(), &mut psid) } == 0 {
        return Err(anyhow::anyhow!(
            "ConvertStringSidToSidW failed for {sid_str}: {}",
            unsafe { GetLastError() }
        ));
    }
    let mut name_len: u32 = 0;
    let mut domain_len: u32 = 0;
    let mut use_type: SID_NAME_USE = 0;
    let ok = unsafe {
        LookupAccountSidW(
            std::ptr::null(),
            psid,
            std::ptr::null_mut(),
            &mut name_len,
            std::ptr::null_mut(),
            &mut domain_len,
            &mut use_type,
        )
    };
    if ok == 0 {
        let err = unsafe { GetLastError() };
        if err != ERROR_INSUFFICIENT_BUFFER {
            unsafe {
                LocalFree(psid as _);
            }
            return Err(anyhow::anyhow!(
                "LookupAccountSidW preflight failed for {sid_str}: {err}"
            ));
        }
    }
    let mut name_buf: Vec<u16> = vec![0u16; name_len as usize];
    let mut domain_buf: Vec<u16> = vec![0u16; domain_len as usize];
    let ok = unsafe {
        LookupAccountSidW(
            std::ptr::null(),
            psid,
            name_buf.as_mut_ptr(),
            &mut name_len,
            domain_buf.as_mut_ptr(),
            &mut domain_len,
            &mut use_type,
        )
    };
    unsafe {
        LocalFree(psid as _);
    }
    if ok == 0 {
        return Err(anyhow::anyhow!(
            "LookupAccountSidW failed for {sid_str}: {}",
            unsafe { GetLastError() }
        ));
    }
    let name = String::from_utf16_lossy(&name_buf);
    Ok(name.trim_end_matches('\0').to_string())
}

pub fn sid_bytes_to_psid(sid: &[u8]) -> Result<*mut c_void> {
    let sid_str = string_from_sid_bytes(sid).map_err(anyhow::Error::msg)?;
    let sid_w = to_wide(OsStr::new(&sid_str));
    let mut psid: *mut c_void = std::ptr::null_mut();
    if unsafe { ConvertStringSidToSidW(sid_w.as_ptr(), &mut psid) } == 0 {
        return Err(anyhow::anyhow!(
            "ConvertStringSidToSidW failed: {}",
            unsafe { GetLastError() }
        ));
    }
    Ok(psid)
}

struct GeneratedPassword(String);
impl Drop for GeneratedPassword {
    fn drop(&mut self) {
        for byte in unsafe { self.0.as_bytes_mut() } {
            unsafe { ptr::write_volatile(byte, 0) };
        }
    }
}

struct PasswordWide(Vec<u16>);
impl Drop for PasswordWide {
    fn drop(&mut self) {
        for value in &mut self.0 {
            unsafe { ptr::write_volatile(value, 0) };
        }
    }
}

fn random_password() -> Result<GeneratedPassword> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut bytes = [0u8; 16];
    OsRng.try_fill_bytes(&mut bytes).map_err(|error| {
        anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperCredentialRandomFailed,
            format!("operating-system credential entropy failed: {error}"),
        ))
    })?;
    // The four fixed characters satisfy the usual complexity classes; all
    // account entropy comes from 128 bits supplied by the operating system.
    let mut password = String::with_capacity(36);
    password.push_str("Aa1!");
    for byte in &mut bytes {
        password.push(HEX[usize::from(*byte >> 4)] as char);
        password.push(HEX[usize::from(*byte & 15)] as char);
        unsafe { ptr::write_volatile(byte, 0) };
    }
    Ok(GeneratedPassword(password))
}

#[derive(Serialize)]
struct SandboxUserRecord {
    username: String,
    password: String,
}

#[derive(Serialize)]
struct SandboxUsersFile {
    version: u32,
    offline: SandboxUserRecord,
    online: SandboxUserRecord,
}

#[derive(Serialize)]
struct SetupMarker {
    version: u32,
    offline_username: String,
    online_username: String,
    created_at: String,
    proxy_ports: Vec<u16>,
    allow_local_binding: bool,
    read_roots: Vec<PathBuf>,
    write_roots: Vec<PathBuf>,
}

fn write_secrets(
    file: &mut ProtectedCredentialFile,
    offline_user: &str,
    offline_pwd: &str,
    online_user: &str,
    online_pwd: &str,
) -> Result<()> {
    let offline_blob = dpapi_protect(offline_pwd.as_bytes()).map_err(|err| {
        anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperDpapiProtectFailed,
            format!("dpapi protect failed for offline user: {err}"),
        ))
    })?;
    let online_blob = dpapi_protect(online_pwd.as_bytes()).map_err(|err| {
        anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperDpapiProtectFailed,
            format!("dpapi protect failed for online user: {err}"),
        ))
    })?;
    let users = SandboxUsersFile {
        version: SETUP_VERSION,
        offline: SandboxUserRecord {
            username: offline_user.to_string(),
            password: BASE64.encode(offline_blob),
        },
        online: SandboxUserRecord {
            username: online_user.to_string(),
            password: BASE64.encode(online_blob),
        },
    };
    let users_json = serde_json::to_vec_pretty(&users).map_err(|err| {
        anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperUsersFileWriteFailed,
            format!("serialize sandbox users failed: {err}"),
        ))
    })?;
    file.write_new_users(&users_json).map_err(|err| {
        anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperUsersFileWriteFailed,
            format!("write protected sandbox users through the original CREATE_NEW handle failed: {err:#}"),
        ))
    })?;
    Ok(())
}

// Create the final marker path with its protected ACL before provisioning begins. The empty file
// intentionally fails readiness checks while setup is in progress, and sandbox users cannot read,
// modify, or replace it. Once every setup step succeeds, `commit_setup_marker` writes the valid
// marker contents without changing the file's ACL.
pub(super) fn prepare_setup_marker(codex_home: &Path, real_user: &str) -> Result<()> {
    let marker_path = sandbox_dir(codex_home).join("setup_marker.json");
    match std::fs::remove_file(&marker_path) {
        Ok(()) => {}
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
        Err(err) => {
            return Err(anyhow::Error::new(SetupFailure::new(
                SetupErrorCode::HelperSetupMarkerWriteFailed,
                format!(
                    "remove setup marker file {} failed: {err}",
                    marker_path.display()
                ),
            )));
        }
    }

    let real_user_sid = resolve_sid(real_user)
        .and_then(|sid| string_from_sid_bytes(&sid).map_err(anyhow::Error::msg))
        .map_err(|err| {
            anyhow::Error::new(SetupFailure::new(
                SetupErrorCode::HelperSetupMarkerWriteFailed,
                format!("resolve real user SID for setup marker failed: {err}"),
            ))
        })?;
    let sddl = to_wide(format!(
        "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;{real_user_sid})"
    ));
    let mut security_descriptor: PSECURITY_DESCRIPTOR = std::ptr::null_mut();
    let converted = unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl.as_ptr(),
            SDDL_REVISION_1,
            &mut security_descriptor,
            std::ptr::null_mut(),
        )
    };
    if converted == 0 {
        return Err(anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperSetupMarkerWriteFailed,
            format!(
                "create setup marker security descriptor failed: {}",
                unsafe { GetLastError() }
            ),
        )));
    }

    let security_attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: security_descriptor,
        bInheritHandle: 0,
    };
    let marker_path_wide = to_wide(marker_path.as_os_str());
    let marker_handle = unsafe {
        CreateFileW(
            marker_path_wide.as_ptr(),
            GENERIC_WRITE,
            /*dwsharemode*/ 0,
            &security_attributes,
            CREATE_NEW,
            FILE_ATTRIBUTE_NORMAL,
            /*htemplatefile*/ 0,
        )
    };
    let create_error = unsafe { GetLastError() };
    unsafe {
        LocalFree(security_descriptor as _);
    }
    if marker_handle == INVALID_HANDLE_VALUE {
        return Err(anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperSetupMarkerWriteFailed,
            format!(
                "create protected setup marker file {} failed: {}",
                marker_path.display(),
                create_error
            ),
        )));
    }
    unsafe {
        CloseHandle(marker_handle);
    }
    Ok(())
}

pub(super) fn commit_setup_marker(
    codex_home: &Path,
    offline_user: &str,
    online_user: &str,
    proxy_ports: &[u16],
    allow_local_binding: bool,
) -> Result<()> {
    let marker = SetupMarker {
        version: SETUP_VERSION,
        offline_username: offline_user.to_string(),
        online_username: online_user.to_string(),
        created_at: chrono::Utc::now().to_rfc3339(),
        proxy_ports: proxy_ports.to_vec(),
        allow_local_binding,
        read_roots: Vec::new(),
        write_roots: Vec::new(),
    };
    let marker_path = sandbox_dir(codex_home).join("setup_marker.json");
    let marker_json = serde_json::to_vec_pretty(&marker).map_err(|err| {
        anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperSetupMarkerWriteFailed,
            format!("serialize setup marker failed: {err}"),
        ))
    })?;
    std::fs::write(&marker_path, marker_json).map_err(|err| {
        anyhow::Error::new(SetupFailure::new(
            SetupErrorCode::HelperSetupMarkerWriteFailed,
            format!(
                "write setup marker file {} failed: {err}",
                marker_path.display()
            ),
        ))
    })?;
    Ok(())
}
