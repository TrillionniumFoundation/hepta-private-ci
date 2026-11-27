//! Original setup-owner provenance only, not private-namespace or launch authority.
use super::SandboxCreds;
use super::decode_password;
use crate::setup::OFFLINE_USERNAME;
use crate::setup::ONLINE_USERNAME;
use crate::setup::SandboxUsersFile;
use crate::setup::SetupMarker;
use crate::setup::sandbox_users_path;
use crate::setup::setup_marker_path;
use crate::winutil::to_wide;
use anyhow::Result;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Security::LookupAccountNameW;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::System::WindowsProgramming::GetComputerNameW;

const RECORD_BOUND: u64 = 4 * 1024 * 1024;

struct HeldRecord {
    path: PathBuf,
    file: File,
    identity: [u32; 3],
    bytes: Vec<u8>,
}

impl HeldRecord {
    fn open(path: PathBuf) -> Result<Self> {
        let mut file = OpenOptions::new()
            .read(true)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&path)?;
        let identity = file_identity(&file)?;
        let bytes = read_record(&mut file)?;
        anyhow::ensure!(
            file_identity(&file)? == identity,
            "setup record identity changed"
        );
        Ok(Self {
            path,
            file,
            identity,
            bytes,
        })
    }

    fn revalidate(&mut self) -> Result<()> {
        anyhow::ensure!(file_identity(&self.file)? == self.identity);
        anyhow::ensure!(
            read_record(&mut self.file)? == self.bytes,
            "held setup record changed"
        );
        let current = Self::open(self.path.clone())?;
        anyhow::ensure!(
            current.identity == self.identity && current.bytes == self.bytes,
            "setup record path was replaced or changed"
        );
        Ok(())
    }
}

fn file_identity(file: &File) -> Result<[u32; 3]> {
    let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: the original File owns this handle and the native output is complete.
    anyhow::ensure!(
        unsafe { GetFileInformationByHandle(file.as_raw_handle() as _, &mut info) } != 0
    );
    anyhow::ensure!(
        info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT) == 0
    );
    anyhow::ensure!(info.nFileSizeHigh == 0 && u64::from(info.nFileSizeLow) <= RECORD_BOUND);
    Ok([
        info.dwVolumeSerialNumber,
        info.nFileIndexHigh,
        info.nFileIndexLow,
    ])
}

fn read_record(file: &mut File) -> Result<Vec<u8>> {
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.take(RECORD_BOUND + 1).read_to_end(&mut bytes)?;
    anyhow::ensure!(
        bytes.len() as u64 <= RECORD_BOUND,
        "setup record exceeds byte bound"
    );
    Ok(bytes)
}

/// Nonexportable observation from this original owner, never from caller DTO fields alone.
/// Held bytes and path identity are continuous through startup. This does not
/// establish the separate protected-namespace, ACL, funding or launch prerequisites.
pub(crate) struct ManagedAccountSource {
    home: PathBuf,
    requested_home: PathBuf,
    marker: HeldRecord,
    users: HeldRecord,
    username: String,
    user_sid: Vec<u8>,
    group_sid: Vec<u8>,
}

impl ManagedAccountSource {
    pub(crate) fn select(codex_home: &Path, credentials: &SandboxCreds) -> Result<Self> {
        let home = dunce::canonicalize(codex_home)?;
        let marker = HeldRecord::open(setup_marker_path(&home))?;
        let users = HeldRecord::open(sandbox_users_path(&home))?;
        let marker_value: SetupMarker = serde_json::from_slice(&marker.bytes)?;
        let users_value: SandboxUsersFile = serde_json::from_slice(&users.bytes)?;
        anyhow::ensure!(
            marker_value.version_matches() && users_value.version_matches(),
            "stale managed source"
        );
        anyhow::ensure!(
            marker_value.offline_username == OFFLINE_USERNAME
                && marker_value.online_username == ONLINE_USERNAME
                && users_value.offline.username == OFFLINE_USERNAME
                && users_value.online.username == ONLINE_USERNAME,
            "foreign managed source names"
        );
        let selected = match credentials.username.as_str() {
            OFFLINE_USERNAME => &users_value.offline,
            ONLINE_USERNAME => &users_value.online,
            _ => anyhow::bail!("credentials are not an original managed identity"),
        };
        anyhow::ensure!(
            decode_password(selected)? == credentials.password,
            "credentials differ from selected original source"
        );
        let user_sid = local_sid(&selected.username, /*expected_use*/ 1)?;
        let group_sid = local_sid("CodexSandboxUsers", /*expected_use*/ 4)?;
        anyhow::ensure!(
            user_sid[..24] == group_sid[..24] && user_sid != group_sid,
            "managed account domain mismatch"
        );
        let mut source = Self {
            home,
            requested_home: codex_home.to_owned(),
            marker,
            users,
            username: selected.username.clone(),
            user_sid,
            group_sid,
        };
        source.revalidate()?;
        Ok(source)
    }

    pub(crate) fn user_sid(&self) -> &[u8] {
        &self.user_sid
    }
    pub(crate) fn group_sid(&self) -> &[u8] {
        &self.group_sid
    }

    pub(crate) fn revalidate(&mut self) -> Result<()> {
        anyhow::ensure!(
            dunce::canonicalize(&self.requested_home)? == self.home,
            "managed source scope changed"
        );
        self.marker.revalidate()?;
        self.users.revalidate()?;
        anyhow::ensure!(
            local_sid(&self.username, /*expected_use*/ 1)? == self.user_sid
                && local_sid("CodexSandboxUsers", /*expected_use*/ 4)? == self.group_sid,
            "managed account was replaced"
        );
        Ok(())
    }
}

fn local_sid(name: &str, expected_use: i32) -> Result<Vec<u8>> {
    let mut computer = [0u16; 256];
    let mut computer_length = computer.len() as u32;
    anyhow::ensure!(unsafe { GetComputerNameW(computer.as_mut_ptr(), &mut computer_length) } != 0);
    anyhow::ensure!((1..256).contains(&computer_length));
    let computer_name = String::from_utf16(&computer[..computer_length as usize])?;
    let qualified = to_wide(format!("{computer_name}\\{name}"));
    let mut sid = [0u32; 17];
    let mut sid_length = std::mem::size_of_val(&sid) as u32;
    let mut domain = [0u16; 256];
    let mut domain_length = domain.len() as u32;
    let mut use_type = 0;
    // Fixed local qualified name; no domain fallback, resizing loop or caller SID.
    anyhow::ensure!(
        unsafe {
            LookupAccountNameW(
                computer.as_ptr(),
                qualified.as_ptr(),
                sid.as_mut_ptr().cast(),
                &mut sid_length,
                domain.as_mut_ptr(),
                &mut domain_length,
                &mut use_type,
            )
        } != 0
    );
    anyhow::ensure!(use_type == expected_use && sid_length == 28 && domain_length < 256);
    // The domain is a native NUL-terminated name; bound both reported-length conventions.
    let domain = &domain[..domain_length as usize];
    let domain = domain.strip_suffix(&[0]).unwrap_or(domain);
    anyhow::ensure!(
        !domain.contains(&0) && String::from_utf16(domain)?.eq_ignore_ascii_case(&computer_name)
    );
    let bytes =
        unsafe { std::slice::from_raw_parts(sid.as_ptr().cast::<u8>(), sid_length as usize) }
            .to_vec();
    anyhow::ensure!(bytes[..12] == [1, 5, 0, 0, 0, 0, 0, 5, 21, 0, 0, 0]);
    anyhow::ensure!(
        u32::from_le_bytes(bytes[24..28].try_into()?) >= 1000,
        "nonmanaged account RID"
    );
    Ok(bytes)
}

#[cfg(test)]
#[path = "managed_account_source_tests.rs"]
mod tests;
