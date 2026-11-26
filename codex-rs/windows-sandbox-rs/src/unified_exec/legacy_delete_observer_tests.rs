//! Read-only descriptor observations and bounded legacy child-output capture.

// This separate setup module only changes the newly created, empty fixture root.
#[path = "legacy_delete_fixture_acl_tests.rs"]
pub(super) mod fixture_acl;

use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use codex_utils_pty::SpawnedProcess;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::time::timeout;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_SELF_RELATIVE;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_OWNER;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenOwner;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;

const MAX_BYTES: usize = 64 * 1024;
const MAX_ACES: usize = 64;
const STREAM_BYTES: usize = 4096;

pub(super) struct StreamCapture {
    pub(super) prefix: Vec<u8>,
    pub(super) total_bytes: u64,
}

async fn drain(mut receiver: mpsc::Receiver<Vec<u8>>) -> StreamCapture {
    let mut capture = StreamCapture {
        prefix: Vec::new(),
        total_bytes: 0,
    };
    while let Some(chunk) = receiver.recv().await {
        capture.total_bytes = capture.total_bytes.saturating_add(chunk.len() as u64);
        let remaining = STREAM_BYTES - capture.prefix.len();
        capture
            .prefix
            .extend_from_slice(&chunk[..remaining.min(chunk.len())]);
    }
    capture
}

pub(super) async fn collect_output_and_exit(
    spawned: SpawnedProcess,
    timeout_duration: Duration,
) -> Result<(StreamCapture, StreamCapture, i32)> {
    let SpawnedProcess {
        session: _session,
        stdout_rx,
        stderr_rx,
        exit_rx,
    } = spawned;
    let stdout = tokio::spawn(drain(stdout_rx));
    let stderr = tokio::spawn(drain(stderr_rx));
    let exit_code = timeout(timeout_duration, exit_rx)
        .await
        .context("original exit deadline")?
        .unwrap_or(-1);
    // The old helper has one further drain deadline after exit. Both streams
    // share that same deadline; stderr does not receive another timeout.
    let (stdout, stderr) = timeout(timeout_duration, async { tokio::join!(stdout, stderr) })
        .await
        .context("original output-drain deadline")?;
    Ok((
        stdout.context("stdout reader")?,
        stderr.context("stderr reader")?,
        exit_code,
    ))
}

fn checked_sid(bytes: &[u8], pointer: *mut c_void) -> Result<Vec<u8>> {
    let offset = (pointer as usize)
        .checked_sub(bytes.as_ptr() as usize)
        .ok_or_else(|| anyhow!("SID before allocation"))?;
    let header = bytes
        .get(offset..offset.checked_add(8).context("SID offset overflow")?)
        .context("SID header outside allocation")?;
    let end = offset
        .checked_add(8 + usize::from(header[1]) * 4)
        .context("SID size overflow")?;
    let sid = bytes.get(offset..end).context("SID outside allocation")?;
    ensure!(unsafe { IsValidSid(pointer) } != 0, "invalid SID");
    Ok(sid.to_vec())
}

fn token_sid(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Vec<u8>> {
    let mut words = [0usize; 256];
    let mut returned = 0;
    ensure!(
        unsafe {
            GetTokenInformation(
                token,
                class,
                words.as_mut_ptr().cast(),
                size_of_val(&words) as u32,
                &mut returned,
            )
        } != 0,
        "query caller SID: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        returned as usize <= size_of_val(&words),
        "caller SID buffer exceeded"
    );
    let pointer = if class == TokenUser {
        ensure!(
            returned as usize >= size_of::<TOKEN_USER>(),
            "short TOKEN_USER"
        );
        unsafe { (*words.as_ptr().cast::<TOKEN_USER>()).User.Sid }
    } else {
        ensure!(
            returned as usize >= size_of::<TOKEN_OWNER>(),
            "short TOKEN_OWNER"
        );
        unsafe { (*words.as_ptr().cast::<TOKEN_OWNER>()).Owner }
    };
    let bytes =
        unsafe { std::slice::from_raw_parts(words.as_ptr().cast::<u8>(), returned as usize) };
    checked_sid(bytes, pointer)
}

fn sid_bytes(value: &str) -> Result<Vec<u8>> {
    let sid = crate::token::LocalSid::from_string(value).map_err(|_| anyhow!("invalid SID"))?;
    let size = unsafe { GetLengthSid(sid.as_ptr()) } as usize;
    ensure!(size > 0 && size <= 68, "SID size outside fixed bound");
    Ok(unsafe { std::slice::from_raw_parts(sid.as_ptr().cast::<u8>(), size) }.to_vec())
}

struct Identities {
    user: Vec<u8>,
    owner: Vec<u8>,
    names: Vec<(&'static str, Vec<u8>)>,
}

impl Identities {
    fn capture() -> Result<Self> {
        let mut raw = 0;
        ensure!(
            unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw) } != 0,
            "query parent-process token: {}",
            std::io::Error::last_os_error()
        );
        let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
        let user = token_sid(token.as_raw_handle() as _, TokenUser)?;
        let owner = token_sid(token.as_raw_handle() as _, TokenOwner)?;
        let mut names = vec![("parent_process_user", user.clone())];
        for (name, sid) in [
            ("world", "S-1-1-0"),
            ("system", "S-1-5-18"),
            ("administrators", "S-1-5-32-544"),
            ("users", "S-1-5-32-545"),
            ("authenticated_users", "S-1-5-11"),
            ("creator_owner", "S-1-3-0"),
        ] {
            names.push((name, sid_bytes(sid)?));
        }
        Ok(Self { user, owner, names })
    }

    fn add_existing_capabilities(
        &mut self,
        home: &Path,
        roots: &[(&'static str, PathBuf); 3],
    ) -> Result<()> {
        // Read only: never call load_or_create_cap_sids or a SID-producing helper.
        let mut bytes = Vec::new();
        File::open(crate::cap::cap_sid_file(home))?
            .take(MAX_BYTES as u64 + 1)
            .read_to_end(&mut bytes)?;
        ensure!(bytes.len() <= MAX_BYTES, "capability file exceeds bound");
        let caps: crate::cap::CapSids = serde_json::from_slice(&bytes)?;
        ensure!(
            caps.workspace_by_cwd.len() + caps.writable_root_by_path.len() <= 256,
            "capability map exceeds bound"
        );
        for (name, root) in roots {
            let key = crate::path_normalization::canonical_path_key(root);
            let sid = if *name == "cap_workspace" {
                caps.workspace_by_cwd.get(&key)
            } else {
                caps.writable_root_by_path.get(&key)
            }
            .context("expected existing root capability missing")?;
            self.names.push((name, sid_bytes(sid)?));
        }
        Ok(())
    }

    fn name(&self, sid: &[u8]) -> &'static str {
        self.names
            .iter()
            .find(|(_, known)| known == sid)
            .map_or("other", |(name, _)| *name)
    }
}

struct Descriptor(*mut c_void);
impl Drop for Descriptor {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0 as _) };
    }
}

fn snapshot(path: &Path, identities: Option<&Identities>) -> Result<(Value, Vec<u8>)> {
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | FILE_READ_ATTRIBUTES)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    snapshot_handle(&file, identities)
}

fn snapshot_handle(file: &File, identities: Option<&Identities>) -> Result<(Value, Vec<u8>)> {
    let attributes = file.metadata()?.file_attributes();
    let (mut owner, mut group, mut dacl, mut raw) = (
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        std::ptr::null_mut::<ACL>(),
        std::ptr::null_mut(),
    );
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            &mut group,
            &mut dacl,
            std::ptr::null_mut(),
            &mut raw,
        )
    };
    ensure!(status == 0, "GetSecurityInfo returned {status}");
    let descriptor = Descriptor(raw);
    ensure!(
        unsafe { IsValidSecurityDescriptor(descriptor.0) } != 0,
        "invalid SD"
    );
    let size = unsafe { GetSecurityDescriptorLength(descriptor.0) } as usize;
    ensure!(size > 0 && size <= MAX_BYTES, "SD exceeds bound");
    let (mut control, mut revision) = (0, 0);
    ensure!(
        unsafe { GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision) } != 0
            && control & SE_SELF_RELATIVE != 0,
        "SD is not self-relative"
    );
    let bytes = unsafe { std::slice::from_raw_parts(descriptor.0.cast::<u8>(), size) };
    let owner = checked_sid(bytes, owner)?;
    let group = checked_sid(bytes, group)?;
    let name = |sid: &[u8]| identities.map_or("unknown", |ids| ids.name(sid));
    let mut entries = Vec::new();
    let mut acl_size = None;
    if !dacl.is_null() {
        let offset = (dacl as usize)
            .checked_sub(bytes.as_ptr() as usize)
            .context("ACL before SD")?;
        let header = bytes
            .get(offset..offset.checked_add(8).context("ACL offset overflow")?)
            .context("ACL header outside SD")?;
        let size = usize::from(u16::from_le_bytes([header[2], header[3]]));
        let count = usize::from(u16::from_le_bytes([header[4], header[5]]));
        ensure!(count <= MAX_ACES && size >= 8, "ACL bounds exceeded");
        let acl = bytes
            .get(offset..offset.checked_add(size).context("ACL size overflow")?)
            .context("ACL outside SD")?;
        let mut cursor: usize = 8;
        for _ in 0..count {
            let header = acl
                .get(cursor..cursor.checked_add(4).context("ACE offset overflow")?)
                .context("ACE header outside ACL")?;
            let size = usize::from(u16::from_le_bytes([header[2], header[3]]));
            ensure!(size >= 4, "short ACE");
            let ace = acl
                .get(cursor..cursor.checked_add(size).context("ACE size overflow")?)
                .context("ACE outside ACL")?;
            let (mask, sid) = if matches!(header[0], 0 | 1) {
                ensure!(ace.len() >= 16, "short basic ACE");
                let mask = u32::from_le_bytes([ace[4], ace[5], ace[6], ace[7]]);
                let sid = checked_sid(ace, unsafe { ace.as_ptr().add(8).cast_mut().cast() })?;
                (Some(mask), name(&sid))
            } else {
                (None, "unsupported_ace_type")
            };
            entries.push(json!({"type":header[0],"flags":header[1],"bytes":size,"mask":mask,"sid_class":sid}));
            cursor += size;
        }
        acl_size = Some(size);
    }
    let result = json!({"state":"present","attributes":attributes,"sd_bytes":size,"sd_control":control,
        "dacl_null_pointer":dacl.is_null(),"acl_bytes":acl_size,"aces":entries,
        "owner_class":name(&owner),"group_class":name(&group),
        "owner_is_parent_process_user":identities.map(|ids| ids.user == owner),
        "owner_is_parent_process_default_owner":identities.map(|ids| ids.owner == owner),
        "identity_reference":"parent_process_only_not_child_token"});
    let original = bytes.to_vec();
    drop(descriptor);
    Ok((result, original))
}

pub(super) struct Observer {
    paths: [(&'static str, PathBuf); 9],
    roots: [(&'static str, PathBuf); 3],
    identities: Option<Identities>,
    before: BTreeMap<&'static str, Vec<u8>>,
    remaining: usize,
}

impl Observer {
    pub(super) fn new(
        paths: [(&'static str, PathBuf); 9],
        roots: [(&'static str, PathBuf); 3],
    ) -> Self {
        let identities = Identities::capture();
        let mut this = Self {
            paths,
            roots,
            identities: None,
            before: BTreeMap::new(),
            remaining: MAX_BYTES,
        };
        match identities {
            Ok(identities) => this.identities = Some(identities),
            Err(error) => this.emit(
                json!({"kind":"unknown","phase":"parent_identity","error":bounded_error(&error)}),
            ),
        }
        this
    }

    fn emit(&mut self, value: Value) {
        if let Ok(line) = serde_json::to_string(&value) {
            let size = line.len() + 22;
            if size <= self.remaining {
                self.remaining -= size;
                let _ = writeln!(std::io::stderr().lock(), "HEPTA_LEGACY_DELETE {line}");
            } else {
                const TRUNCATED: &str = "HEPTA_LEGACY_DELETE_UNKNOWN log_budget_exhausted";
                if self.remaining > TRUNCATED.len() {
                    let _ = writeln!(std::io::stderr().lock(), "{TRUNCATED}");
                }
                self.remaining = 0;
            }
        }
    }

    pub(super) fn observe(&mut self, phase: &str, home: &Path) {
        if phase == "after_exit"
            && let Some(identities) = self.identities.as_mut()
            && let Err(error) = identities.add_existing_capabilities(home, &self.roots)
        {
            self.emit(json!({"kind":"unknown","phase":"existing_capabilities","error":bounded_error(&error)}));
        }
        for index in 0..self.paths.len() {
            let (role, path) = &self.paths[index];
            let role = *role;
            let value = match snapshot(path, self.identities.as_ref()) {
                Ok((mut value, bytes)) => {
                    value["same_sd_bytes_as_before_spawn"] =
                        json!(self.before.get(role).map(|before| before == &bytes));
                    if phase == "before_spawn" {
                        self.before.insert(role, bytes);
                    }
                    value
                }
                Err(error) => {
                    let missing = error
                        .downcast_ref::<std::io::Error>()
                        .is_some_and(|error| error.kind() == std::io::ErrorKind::NotFound);
                    json!({"state":if missing {"absent"} else {"unknown"},"error":bounded_error(&error)})
                }
            };
            self.emit(json!({"kind":"descriptor","phase":phase,"role":role,"snapshot":value}));
        }
    }
}

fn bounded_error(error: &anyhow::Error) -> String {
    error.to_string().chars().take(256).collect()
}
