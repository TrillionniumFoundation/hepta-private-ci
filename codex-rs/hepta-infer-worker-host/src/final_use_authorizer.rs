//! Trusted-host bridge from an exact runtime.codex turn/start binding to the
//! kernel.authority final-use verifier.
//!
//! The worker never owns a signing key. It asks an independently operated Unix
//! authority endpoint for a signed grant, synchronizes the trusted revocation
//! head supplied by that endpoint, and then verifies/claims the grant locally.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;

use crate::native_app_server::TurnStartAuthorityFuture;
use crate::native_app_server::TurnStartAuthorizer;

const AUTHORITY_PORT_SCHEMA_VERSION: u32 = 1;
const AUTHORITY_PORT_OPERATION: &str = "runtime.codex.turn_start";
const MAX_CONFIG_BYTES: usize = 64 * 1024;
const MAX_REQUEST_BYTES: usize = 16 * 1024;
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_DENIAL_REASON_BYTES: usize = 1024;
const MAX_ISSUER_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_BACKWARD_CLOCK_DRIFT: Duration = Duration::from_secs(2);
const MAX_FORWARD_CLOCK_DRIFT: Duration = Duration::from_secs(300);

type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

/// Protected host configuration for the independent final-use authority port.
///
/// `verifying_key` is public. The private signing key is intentionally absent.
#[derive(Clone, Debug, Deserialize)]
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
}

/// Production runtime.codex authorizer. The independent endpoint decides
/// whether to issue a grant; this process only verifies and consumes it.
pub struct UnixFinalUseAuthorizer {
    issuer_socket: PathBuf,
    issuer_uid: u32,
    issuer_timeout: Duration,
    authority: FinalUseAuthority,
    clock: MonotonicWallClock,
}

#[derive(Debug)]
struct MonotonicWallClock {
    wall_unix_ms_at_open: u128,
    monotonic_at_open: Instant,
}

impl MonotonicWallClock {
    fn capture() -> Result<Self> {
        Ok(Self {
            wall_unix_ms_at_open: wall_unix_ms()?,
            monotonic_at_open: Instant::now(),
        })
    }

    /// Detect material wall-clock rollback or an implausible forward jump
    /// relative to a process-local monotonic anchor. This is a fail-closed
    /// runtime fence, not an independent trusted-time service.
    fn validate(&self) -> Result<()> {
        let elapsed_ms = self.monotonic_at_open.elapsed().as_millis();
        let expected_ms = self
            .wall_unix_ms_at_open
            .checked_add(elapsed_ms)
            .ok_or("final-use monotonic clock projection overflow")?;
        let now_ms = wall_unix_ms()?;
        let backward_allowance = MAX_BACKWARD_CLOCK_DRIFT.as_millis();
        let forward_allowance = MAX_FORWARD_CLOCK_DRIFT.as_millis();
        if now_ms
            .checked_add(backward_allowance)
            .is_none_or(|value| value < expected_ms)
        {
            return Err("wall clock moved backward across the final-use boundary".into());
        }
        if now_ms
            > expected_ms
                .checked_add(forward_allowance)
                .ok_or("final-use forward clock bound overflow")?
        {
            return Err("wall clock jumped forward across the final-use boundary".into());
        }
        Ok(())
    }
}

fn wall_unix_ms() -> Result<u128> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system wall clock precedes the Unix epoch")?
        .as_millis())
}

impl UnixFinalUseAuthorizer {
    pub fn open(config_path: &Path) -> Result<Self> {
        let config: FinalUseAuthorizerConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_config(config)
    }

    pub fn from_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        if !config.issuer_socket.is_absolute() || !config.authority_state_dir.is_absolute() {
            return Err("final-use authority socket and state directory must be absolute".into());
        }
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        let clock = MonotonicWallClock::capture()?;
        let authority = FinalUseAuthority::open_state_dir(
            &config.authority_state_dir,
            config.signer_id,
            config.verifying_key,
            FinalUseRevocations {
                authority_epoch: config.authority_epoch,
                revision: config.revocation_revision,
                revoked_grant_ids: config.revoked_grant_ids,
            },
        )?;
        Ok(Self {
            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_timeout,
            authority,
            clock,
        })
    }

    async fn claim_exact(&self, binding: FinalUseBinding) -> Result<VerifiedUseToken> {
        self.clock.validate()?;
        let response = self.request_grant(&binding).await?;
        self.clock.validate()?;
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
            validate_issuer_peer_process(
                peer.pid()
                    .ok_or("final-use authority peer omitted its process identity")?,
                self.issuer_uid,
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

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct IssuerRequest {
    schema_version: u32,
    operation: String,
    binding: FinalUseBinding,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct IssuerResponse {
    schema_version: u32,
    revocations: FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<String>,
}

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

#[cfg(target_os = "linux")]
fn validate_issuer_peer_process(pid: u32, issuer_uid: u32) -> Result<()> {
    use std::os::unix::fs::MetadataExt;

    if pid == 0 {
        return Err("final-use authority peer process id is invalid".into());
    }
    let process_root = PathBuf::from(format!("/proc/{pid}"));
    let process_metadata = std::fs::metadata(&process_root)?;
    if process_metadata.uid() != issuer_uid {
        return Err("final-use authority process owner differs from its peer credential".into());
    }
    let executable = std::fs::read_link(process_root.join("exe"))?;
    if !executable.is_absolute() {
        return Err("final-use authority executable identity is not absolute".into());
    }
    let executable_metadata = std::fs::metadata(&executable)?;
    if !executable_metadata.is_file()
        || executable_metadata.mode() & 0o022 != 0
        || (executable_metadata.uid() != 0 && executable_metadata.uid() != issuer_uid)
    {
        return Err("final-use authority executable identity or permissions are unsafe".into());
    }
    let stat = std::fs::read_to_string(process_root.join("stat"))?;
    let tail = stat
        .rsplit_once(") ")
        .map(|(_, tail)| tail)
        .ok_or("final-use authority process stat is malformed")?;
    let start_time = tail
        .split_whitespace()
        .nth(19)
        .ok_or("final-use authority process start identity is missing")?
        .parse::<u64>()?;
    if start_time == 0 {
        return Err("final-use authority process start identity is invalid".into());
    }
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
    let boot_id = boot_id.trim();
    if boot_id.len() != 36
        || !boot_id
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() || byte == b'-')
    {
        return Err("target-host boot identity is malformed".into());
    }
    Ok(())
}

#[cfg(unix)]
fn validate_issuer_socket(path: &Path, issuer_uid: u32) -> Result<()> {
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
    let parent = path
        .parent()
        .ok_or("final-use authority socket has no parent directory")?;
    validate_issuer_directory_chain(parent, issuer_uid)
}

#[cfg(unix)]
fn validate_issuer_directory_chain(path: &Path, issuer_uid: u32) -> Result<()> {
    use std::os::unix::fs::MetadataExt;

    let mut current = Some(path);
    let mut direct_parent = true;
    while let Some(directory) = current {
        let metadata = std::fs::symlink_metadata(directory)?;
        if !metadata.is_dir() || (metadata.uid() != 0 && metadata.uid() != issuer_uid) {
            return Err("final-use authority socket directory identity is unsafe".into());
        }
        let writable = metadata.mode() & 0o022 != 0;
        let root_sticky_boundary = !direct_parent
            && metadata.uid() == 0
            && metadata.mode() & 0o002 != 0
            && metadata.mode() & 0o1000 != 0;
        if writable && !root_sticky_boundary {
            return Err(
                "final-use authority socket directory is writable by an unsafe principal".into(),
            );
        }
        if directory == Path::new("/") {
            break;
        }
        current = directory.parent();
        direct_parent = false;
    }
    Ok(())
}

#[cfg(test)]
mod hardening_tests {
    use super::*;

    #[test]
    fn monotonic_wall_clock_accepts_a_fresh_anchor() {
        MonotonicWallClock::capture().unwrap().validate().unwrap();
    }

    #[test]
    fn monotonic_wall_clock_rejects_backward_projection() {
        let clock = MonotonicWallClock {
            wall_unix_ms_at_open: wall_unix_ms().unwrap() + 10_000,
            monotonic_at_open: Instant::now(),
        };
        assert!(clock.validate().is_err());
    }

    #[test]
    fn monotonic_wall_clock_rejects_implausible_forward_projection() {
        let clock = MonotonicWallClock {
            wall_unix_ms_at_open: 0,
            monotonic_at_open: Instant::now(),
        };
        assert!(clock.validate().is_err());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn current_process_has_a_valid_linux_process_identity() {
        let uid = rustix::process::geteuid().as_raw();
        validate_issuer_peer_process(std::process::id(), uid).unwrap();
    }
}

#[cfg(all(test, unix))]
#[path = "final_use_authorizer_tests.rs"]
pub(crate) mod tests;
