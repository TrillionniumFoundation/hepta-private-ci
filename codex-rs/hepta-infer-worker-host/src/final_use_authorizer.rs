//! Trusted-host bridge from an exact runtime.codex turn/start binding to the
//! kernel.authority final-use verifier.
//!
//! The worker never owns a signing key. It asks an independently operated Unix
//! authority endpoint for a signed grant, synchronizes the trusted revocation
//! head supplied by that endpoint, and then verifies/claims the grant locally.

use std::collections::BTreeSet;
use std::error::Error as StdError;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::VerifiedUseToken;
use serde::Deserialize;
use serde::Serialize;
#[cfg(target_os = "linux")]
use sha2::Digest;
#[cfg(target_os = "linux")]
use sha2::Sha256;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;

use crate::native_app_server::TurnStartAuthorityFuture;
use crate::native_app_server::TurnStartAuthorizer;

use codex_hepta_contracts::MODEL_ISSUER_OPERATION as AUTHORITY_PORT_OPERATION;
use codex_hepta_contracts::MODEL_ISSUER_SCHEMA_VERSION as AUTHORITY_PORT_SCHEMA_VERSION;
const MAX_CONFIG_BYTES: usize = 64 * 1024;
use codex_hepta_contracts::MODEL_ISSUER_MAX_REQUEST_BYTES as MAX_REQUEST_BYTES;
use codex_hepta_contracts::MODEL_ISSUER_MAX_RESPONSE_BYTES as MAX_RESPONSE_BYTES;
const MAX_DENIAL_REASON_BYTES: usize = 1024;
const MAX_ISSUER_TIMEOUT: Duration = Duration::from_secs(30);
#[cfg(target_os = "linux")]
const MAX_PROC_TEXT_BYTES: usize = 64 * 1024;
#[cfg(target_os = "linux")]
const MAX_ISSUER_EXECUTABLE_BYTES: u64 = 512 * 1024 * 1024;

type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

/// Linux process identity expected behind the protected authority socket.
///
/// The executable digest binds the exact issuer binary. The cgroup digest binds
/// its service/container placement. The boot-id digest prevents a process from a
/// different host boot from satisfying a stale socket/configuration binding.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IssuerProcessIdentityConfig {
    pub executable_sha256: String,
    pub cgroup_sha256: String,
    pub boot_id_sha256: String,
}

/// Protected host configuration for the independent final-use authority port.
///
/// `verifying_key` is public. The private signing key is intentionally absent.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseAuthorizerConfig {
    pub issuer_socket: PathBuf,
    pub issuer_uid: u32,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub authority_state_dir: PathBuf,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    #[serde(default)]
    pub revoked_grant_ids: BTreeSet<String>,
    pub issuer_timeout_ms: u64,
    #[serde(default)]
    pub issuer_process_identity: Option<IssuerProcessIdentityConfig>,
    /// Root-published identity for peers whose /proc/PID/exe is not readable by the workload.
    #[serde(default)]
    pub issuer_process_attestation: Option<PathBuf>,
}

/// Production runtime.codex authorizer. The independent endpoint decides
/// whether to issue a grant; this process only verifies and consumes it.
pub struct UnixFinalUseAuthorizer {
    issuer_socket: PathBuf,
    issuer_uid: u32,
    issuer_timeout: Duration,
    issuer_process_identity: Option<IssuerProcessIdentityConfig>,
    issuer_process_attestation: Option<PathBuf>,
    authority: FinalUseAuthority,
}

impl UnixFinalUseAuthorizer {
    /// Open production configuration from a protected file.
    ///
    /// Linux production use requires process-instance identity in addition to
    /// pathname ownership and peer UID. Tests may use the explicit `from_test_config` test-support surface.
    pub fn open(config_path: &Path) -> Result<Self> {
        let config: FinalUseAuthorizerConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_config_inner(config, /*require_process_identity*/ true)
    }

    /// Build from an already decoded production configuration. This path has
    /// the same Linux process-identity requirement as `open`; callers cannot
    /// use a decoded config to bypass the production issuer fence.
    pub fn from_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        Self::from_config_inner(config, /*require_process_identity*/ true)
    }

    /// Explicit non-production constructor for unit/product qualification.
    /// It is absent from normal dependency builds unless `test-support` is
    /// selected, preventing product code from acquiring an unchecked issuer.
    #[cfg(any(test, feature = "test-support"))]
    pub fn from_test_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        Self::from_config_inner(config, false)
    }

    fn from_config_inner(
        config: FinalUseAuthorizerConfig,
        require_process_identity: bool,
    ) -> Result<Self> {
        if !config.issuer_socket.is_absolute() || !config.authority_state_dir.is_absolute() {
            return Err("final-use authority socket and state directory must be absolute".into());
        }
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        if let Some(path) = &config.issuer_process_attestation
            && (!path.is_absolute() || config.issuer_uid != 0)
        {
            return Err(
                "root process attestation requires an absolute path and root issuer UID".into(),
            );
        }
        if let Some(expected) = config.issuer_process_identity.as_ref() {
            validate_process_identity_config(expected)?;
        } else if require_process_identity && config.issuer_process_attestation.is_none() {
            return Err(
                "Linux production final-use authority requires issuer process identity".into(),
            );
        }
        #[cfg(not(target_os = "linux"))]
        if config.issuer_process_identity.is_some() || config.issuer_process_attestation.is_some() {
            return Err("issuer process identity is currently supported only on Linux".into());
        }
        let authority = if require_process_identity {
            let trust = Arc::new(
                crate::final_use_trust_port::UnixFinalUseTrustPort::for_production(&config)?,
            );
            let snapshot = trust.load_snapshot()?;
            FinalUseAuthority::open_state_dir_with_trust(
                &config.authority_state_dir,
                config.signer_id,
                config.verifying_key,
                snapshot.revocations,
                trust.clone(),
                trust,
            )?
        } else {
            FinalUseAuthority::open_state_dir(
                &config.authority_state_dir,
                config.signer_id,
                config.verifying_key,
                FinalUseRevocations {
                    authority_epoch: config.authority_epoch,
                    revision: config.revocation_revision,
                    revoked_grant_ids: config.revoked_grant_ids,
                },
            )?
        };
        Ok(Self {
            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_timeout,
            issuer_process_identity: config.issuer_process_identity,
            issuer_process_attestation: config.issuer_process_attestation,
            authority,
        })
    }

    async fn claim_exact(&self, binding: FinalUseBinding) -> Result<VerifiedUseToken> {
        let response = self.request_grant(&binding).await?;
        if response.schema_version != AUTHORITY_PORT_SCHEMA_VERSION {
            return Err("unsupported final-use authority response schema".into());
        }
        sync_revocations(&self.authority, response.revocations)?;
        match (response.grant, response.denial_reason) {
            (Some(grant), None) => Ok(self.authority.claim(&grant, &binding)?),
            (None, Some(reason)) => {
                if reason.is_empty() || reason.len() > MAX_DENIAL_REASON_BYTES {
                    return Err("invalid final-use authority denial reason".into());
                }
                Err(format!("final-use authority denied turn/start: {reason}").into())
            }
            _ => Err("final-use authority response must contain exactly one outcome".into()),
        }
    }

    #[cfg(unix)]
    async fn request_grant(&self, binding: &FinalUseBinding) -> Result<IssuerResponse> {
        validate_issuer_socket(&self.issuer_socket, self.issuer_uid)?;
        #[cfg(not(target_os = "linux"))]
        debug_assert!(self.issuer_process_identity.is_none());
        let request = IssuerRequest {
            schema_version: AUTHORITY_PORT_SCHEMA_VERSION,
            operation: AUTHORITY_PORT_OPERATION.to_string(),
            binding: binding.clone(),
        };
        let request_bytes = serde_json::to_vec(&request)?;
        if request_bytes.is_empty() || request_bytes.len() > MAX_REQUEST_BYTES {
            return Err("final-use authority request exceeds its bound".into());
        }
        let request_len = u32::try_from(request_bytes.len())?;
        let exchange = async {
            let mut stream = tokio::net::UnixStream::connect(&self.issuer_socket).await?;
            let peer = stream.peer_cred()?;
            validate_issuer_peer_uid(peer.uid(), self.issuer_uid)?;
            #[cfg(target_os = "linux")]
            let process_guard = validate_connected_issuer_with_attestation(
                peer.pid().and_then(|pid| u32::try_from(pid).ok()),
                self.issuer_process_identity.as_ref(),
                self.issuer_process_attestation.as_deref(),
            )?;

            stream.write_all(&request_len.to_be_bytes()).await?;
            stream.write_all(&request_bytes).await?;
            stream.flush().await?;

            let mut length = [0_u8; 4];
            stream.read_exact(&mut length).await?;
            let response_len = usize::try_from(u32::from_be_bytes(length))?;
            if response_len == 0 || response_len > MAX_RESPONSE_BYTES {
                return Err::<Vec<u8>, Box<dyn StdError + Send + Sync>>(
                    "final-use authority response exceeds its bound".into(),
                );
            }
            let mut response = vec![0_u8; response_len];
            stream.read_exact(&mut response).await?;
            #[cfg(target_os = "linux")]
            if let Some(process_guard) = process_guard {
                process_guard.revalidate()?;
            }
            Ok(response)
        };
        let response = timeout(self.issuer_timeout, exchange)
            .await
            .map_err(|_| "final-use authority request timed out")??;
        Ok(serde_json::from_slice(&response)?)
    }

    #[cfg(not(unix))]
    async fn request_grant(&self, _binding: &FinalUseBinding) -> Result<IssuerResponse> {
        Err("runtime.codex final-use Unix authority port is unsupported on this platform".into())
    }
}

impl TurnStartAuthorizer for UnixFinalUseAuthorizer {
    fn claim<'a>(&'a self, binding: FinalUseBinding) -> TurnStartAuthorityFuture<'a> {
        Box::pin(async move { self.claim_exact(binding).await })
    }
}

use codex_hepta_contracts::ModelIssuerRequest as IssuerRequest;
use codex_hepta_contracts::ModelIssuerResponse as IssuerResponse;

fn sync_revocations(authority: &FinalUseAuthority, candidate: FinalUseRevocations) -> Result<()> {
    let current = authority.revocation_head()?;
    if current.authority_epoch == candidate.authority_epoch
        && current.revision == candidate.revision
        && current.revoked_grant_ids == candidate.revoked_grant_ids
    {
        return Ok(());
    }
    authority.update_revocations(candidate)?;
    Ok(())
}

fn validate_process_identity_config(expected: &IssuerProcessIdentityConfig) -> Result<()> {
    for (value, field) in [
        (&expected.executable_sha256, "issuer executable"),
        (&expected.cgroup_sha256, "issuer cgroup"),
        (&expected.boot_id_sha256, "host boot id"),
    ] {
        if value.len() != 64
            || value.bytes().all(|byte| byte == b'0')
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(format!("invalid {field} SHA-256 digest").into());
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
#[derive(Clone, Debug, Eq, PartialEq)]
struct IssuerProcessSnapshot {
    pid: u32,
    start_time_ticks: u64,
    executable_sha256: String,
    cgroup_sha256: String,
    boot_id_sha256: String,
}

#[cfg(target_os = "linux")]
pub(crate) struct IssuerProcessGuard {
    initial: IssuerProcessSnapshot,
    expected: IssuerProcessIdentityConfig,
    attestation_path: Option<PathBuf>,
}

#[cfg(target_os = "linux")]
impl IssuerProcessGuard {
    pub(crate) fn revalidate(&self) -> Result<()> {
        let current = if let Some(path) = &self.attestation_path {
            capture_attested_issuer(self.initial.pid, path)?
        } else {
            capture_issuer_process_identity(self.initial.pid)?
        };
        if current != self.initial {
            return Err("final-use authority process identity changed during exchange".into());
        }
        validate_issuer_process_snapshot(&current, &self.expected)
    }
}

#[cfg(target_os = "linux")]
pub(crate) fn validate_connected_issuer_with_attestation(
    pid: Option<u32>,
    expected: Option<&IssuerProcessIdentityConfig>,
    attestation: Option<&Path>,
) -> Result<Option<IssuerProcessGuard>> {
    let Some(path) = attestation else {
        return validate_connected_issuer_process(pid, expected);
    };
    let pid = pid.ok_or("issuer omitted Linux PID")?;
    let initial = capture_attested_issuer(pid, path)?;
    let pinned = IssuerProcessIdentityConfig {
        executable_sha256: initial.executable_sha256.clone(),
        cgroup_sha256: initial.cgroup_sha256.clone(),
        boot_id_sha256: initial.boot_id_sha256.clone(),
    };
    validate_issuer_process_snapshot(&initial, expected.unwrap_or(&pinned))?;
    Ok(Some(IssuerProcessGuard {
        initial,
        expected: expected.cloned().unwrap_or(pinned),
        attestation_path: Some(path.to_path_buf()),
    }))
}

#[cfg(target_os = "linux")]
fn capture_attested_issuer(pid: u32, path: &Path) -> Result<IssuerProcessSnapshot> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    validate_protected_directory_chain(path.parent().ok_or("issuer attestation has no parent")?)?;
    for ancestor in path
        .parent()
        .ok_or("issuer attestation has no parent")?
        .ancestors()
    {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err("issuer attestation directory must remain root protected".into());
        }
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    if !path.is_absolute()
        || !metadata.is_file()
        || metadata.uid() != 0
        || metadata.nlink() != 1
        || metadata.mode() & 0o022 != 0
    {
        return Err("issuer attestation must be a root-protected regular file".into());
    }
    let mut bytes = Vec::new();
    file.take(4097).read_to_end(&mut bytes)?;
    if bytes.len() > 4096 {
        return Err("issuer attestation exceeds its bound".into());
    }
    let record: codex_hepta_contracts::ModelIssuerProcessIdentity = serde_json::from_slice(&bytes)?;
    if record.schema_version != 1 || record.pid != pid || pid == 0 {
        return Err("issuer attestation does not match connected Linux peer".into());
    }
    let proc_root = PathBuf::from(format!("/proc/{pid}"));
    let start_time_ticks = parse_proc_start_time_ticks(std::str::from_utf8(&read_bounded(
        &proc_root.join("stat"),
        MAX_PROC_TEXT_BYTES,
    )?)?)?;
    let cgroup_sha256 = sha256_bytes(&canonical_proc_text(read_bounded(
        &proc_root.join("cgroup"),
        MAX_PROC_TEXT_BYTES,
    )?));
    let boot_id_sha256 = sha256_bytes(&canonical_proc_text(read_bounded(
        Path::new("/proc/sys/kernel/random/boot_id"),
        256,
    )?));
    if record.start_time_ticks != start_time_ticks
        || record.cgroup_sha256 != cgroup_sha256
        || record.boot_id_sha256 != boot_id_sha256
    {
        return Err("issuer attestation is stale or disagrees with its live process".into());
    }
    Ok(IssuerProcessSnapshot {
        pid,
        start_time_ticks,
        executable_sha256: record.executable_sha256,
        cgroup_sha256,
        boot_id_sha256,
    })
}

#[cfg(target_os = "linux")]
fn validate_connected_issuer_process(
    pid: Option<u32>,
    expected: Option<&IssuerProcessIdentityConfig>,
) -> Result<Option<IssuerProcessGuard>> {
    let Some(expected) = expected else {
        return Ok(None);
    };
    let pid = pid.ok_or("connected final-use authority peer omitted its Linux PID")?;
    let initial = capture_issuer_process_identity(pid)?;
    validate_issuer_process_snapshot(&initial, expected)?;
    Ok(Some(IssuerProcessGuard {
        initial,
        expected: expected.clone(),
        attestation_path: None,
    }))
}

#[cfg(target_os = "linux")]
fn validate_issuer_process_snapshot(
    actual: &IssuerProcessSnapshot,
    expected: &IssuerProcessIdentityConfig,
) -> Result<()> {
    validate_process_identity_config(expected)?;
    if actual.executable_sha256 != expected.executable_sha256
        || actual.cgroup_sha256 != expected.cgroup_sha256
        || actual.boot_id_sha256 != expected.boot_id_sha256
    {
        return Err("connected final-use authority process identity mismatch".into());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn capture_issuer_process_identity(pid: u32) -> Result<IssuerProcessSnapshot> {
    if pid == 0 {
        return Err("connected final-use authority peer PID is invalid".into());
    }
    let proc_root = PathBuf::from(format!("/proc/{pid}"));
    let stat = read_bounded(&proc_root.join("stat"), MAX_PROC_TEXT_BYTES)?;
    let stat = std::str::from_utf8(&stat)?;
    let start_time_ticks = parse_proc_start_time_ticks(stat)?;

    let executable = std::fs::File::open(proc_root.join("exe"))?;
    let executable_metadata = executable.metadata()?;
    if !executable_metadata.is_file() || executable_metadata.len() > MAX_ISSUER_EXECUTABLE_BYTES {
        return Err("final-use authority executable is not a bounded regular file".into());
    }
    let executable_sha256 = sha256_reader(executable, MAX_ISSUER_EXECUTABLE_BYTES)?;
    let cgroup_sha256 = sha256_bytes(&canonical_proc_text(read_bounded(
        &proc_root.join("cgroup"),
        MAX_PROC_TEXT_BYTES,
    )?));
    let boot_id_sha256 = sha256_bytes(&canonical_proc_text(read_bounded(
        Path::new("/proc/sys/kernel/random/boot_id"),
        256,
    )?));
    Ok(IssuerProcessSnapshot {
        pid,
        start_time_ticks,
        executable_sha256,
        cgroup_sha256,
        boot_id_sha256,
    })
}

#[cfg(target_os = "linux")]
fn parse_proc_start_time_ticks(stat: &str) -> Result<u64> {
    let close = stat
        .rfind(')')
        .ok_or("issuer /proc stat omitted process command terminator")?;
    let fields: Vec<&str> = stat[close + 1..].split_whitespace().collect();
    // The suffix starts at field 3 (`state`); starttime is field 22.
    let value = fields
        .get(19)
        .ok_or("issuer /proc stat omitted process start time")?
        .parse::<u64>()?;
    if value == 0 {
        return Err("issuer process start time is invalid".into());
    }
    Ok(value)
}

#[cfg(target_os = "linux")]
fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let mut file = std::fs::File::open(path)?;
    let mut value = Vec::new();
    file.by_ref()
        .take(u64::try_from(
            maximum.checked_add(1).ok_or("read bound overflow")?,
        )?)
        .read_to_end(&mut value)?;
    if value.len() > maximum {
        return Err(format!("{} exceeds its identity bound", path.display()).into());
    }
    Ok(value)
}

#[cfg(target_os = "linux")]
fn canonical_proc_text(mut value: Vec<u8>) -> Vec<u8> {
    while value.last().is_some_and(|byte| byte.is_ascii_whitespace()) {
        value.pop();
    }
    value
}

#[cfg(target_os = "linux")]
fn sha256_reader(mut reader: impl Read, maximum: u64) -> Result<String> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        total = total
            .checked_add(u64::try_from(read)?)
            .ok_or("issuer executable length overflow")?;
        if total > maximum {
            return Err("issuer executable exceeds its identity bound".into());
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(target_os = "linux")]
fn sha256_bytes(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

#[cfg(unix)]
fn read_private_config(path: &Path) -> Result<Vec<u8>> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    if !path.is_absolute() {
        return Err("final-use authority config path must be absolute".into());
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    let effective_uid = rustix::process::geteuid().as_raw();
    if !metadata.is_file()
        || metadata.mode() & 0o022 != 0
        || metadata.nlink() != 1
        || (metadata.uid() != 0 && metadata.uid() != effective_uid)
    {
        return Err(
            "final-use authority config must be a protected root/owner regular file".into(),
        );
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(u64::try_from(MAX_CONFIG_BYTES + 1)?)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_CONFIG_BYTES {
        return Err("final-use authority config exceeds 64 KiB".into());
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_config(_path: &Path) -> Result<Vec<u8>> {
    Err("runtime.codex final-use authority configuration requires Unix".into())
}

#[cfg(unix)]
fn validate_issuer_peer_uid(actual_uid: u32, expected_uid: u32) -> Result<()> {
    if actual_uid != expected_uid {
        return Err(
            "connected final-use authority peer UID does not match configured issuer".into(),
        );
    }
    Ok(())
}

#[cfg(unix)]
pub(crate) fn validate_issuer_socket(path: &Path, issuer_uid: u32) -> Result<()> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err("final-use authority socket path must be absolute".into());
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_socket()
        || metadata.uid() != issuer_uid
        || metadata.mode() & 0o007 != 0
    {
        return Err("final-use authority socket identity or permissions are unsafe".into());
    }
    validate_protected_directory_chain(
        path.parent()
            .ok_or("final-use authority socket has no parent directory")?,
    )?;
    Ok(())
}

#[cfg(unix)]
fn validate_protected_directory_chain(path: &Path) -> Result<()> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err("protected socket directory must be absolute".into());
    }
    let mut current = Some(path);
    while let Some(directory) = current {
        let metadata = std::fs::symlink_metadata(directory)?;
        let writable_by_others = metadata.mode() & 0o022 != 0;
        let trusted_sticky_ancestor = metadata.uid() == 0 && metadata.mode() & 0o1000 != 0;
        if !metadata.is_dir() || (writable_by_others && !trusted_sticky_ancestor) {
            return Err(format!(
                "final-use authority socket directory is writable by an unsafe principal: {}",
                directory.display()
            )
            .into());
        }
        current = directory.parent();
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "final_use_authorizer_tests.rs"]
pub(crate) mod tests;
