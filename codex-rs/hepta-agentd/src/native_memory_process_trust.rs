//! Explicit local-process compatibility trust. OS time and private files are
//! observable capabilities, not protected time or an external rollback oracle.

use std::fs::File;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdIdentity;
use crate::NativeMemoryClockObservationV1;
use crate::NativeMemoryError;
use crate::NativeMemoryTickClockV1;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FilePin {
    pub path: PathBuf,
    pub sha256: String,
}

impl FilePin {
    pub fn read(&self, identity: &AgentdIdentity, limit: u64) -> Result<Vec<u8>, String> {
        let path = &self.path;
        let parent = path.parent().ok_or("pinned file has no parent")?;
        let directory = std::fs::symlink_metadata(parent).map_err(string)?;
        let home = std::fs::metadata(&identity.home_root).map_err(string)?;
        let before = std::fs::symlink_metadata(path).map_err(string)?;
        if !path.is_absolute()
            || parent.canonicalize().map_err(string)? != parent
            || !directory.is_dir()
            || directory.uid() != home.uid()
            || directory.mode() & 0o077 != 0
            || !before.is_file()
            || before.uid() != home.uid()
            || before.nlink() != 1
            || before.mode() & 0o077 != 0
            || before.len() > limit
        {
            return Err("pinned file must be private, bounded and owner-controlled".into());
        }
        let stamp = |m: &std::fs::Metadata| {
            (
                m.dev(),
                m.ino(),
                m.len(),
                m.mtime(),
                m.mtime_nsec(),
                m.ctime(),
                m.ctime_nsec(),
            )
        };
        let mut file = File::open(path).map_err(string)?;
        if stamp(&file.metadata().map_err(string)?) != stamp(&before) {
            return Err("pinned file changed while opening".into());
        }
        let mut bytes = Vec::new();
        file.by_ref()
            .take(limit + 1)
            .read_to_end(&mut bytes)
            .map_err(string)?;
        if bytes.len() as u64 > limit
            || stamp(&file.metadata().map_err(string)?) != stamp(&before)
            || stamp(&std::fs::symlink_metadata(path).map_err(string)?) != stamp(&before)
            || Digest32::of_bytes(&bytes).to_string() != self.sha256
        {
            return Err("pinned file drift".into());
        }
        Ok(bytes)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceLeasePayload {
    pub schema: String,
    pub signer_id: String,
    pub agent_id: AgentId,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub expires_at_unix_seconds: u64,
    pub opaque_token: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SignedSourceLease {
    pub payload: SourceLeasePayload,
    pub signature: Vec<u8>,
}

pub(crate) struct ProcessSourceVerifier {
    pub identity: AgentdIdentity,
    pub grant: FilePin,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub poisoned: AtomicBool,
}

impl ProcessSourceVerifier {
    pub fn current(&self) -> Result<ProductionAuthorityLease, String> {
        if self.poisoned.load(Ordering::SeqCst) {
            return Err("source authority continuity lost".into());
        }
        let result = self.read_verified();
        if result.is_err() {
            self.poisoned.store(true, Ordering::SeqCst);
        }
        result
    }

    fn read_verified(&self) -> Result<ProductionAuthorityLease, String> {
        let bytes = self.grant.read(&self.identity, /*limit*/ 32_768)?;
        let signed: SignedSourceLease = serde_json::from_slice(&bytes).map_err(string)?;
        let payload = &signed.payload;
        let signing_bytes = serde_json::to_vec(payload).map_err(string)?;
        let key = VerifyingKey::from_bytes(&self.verifying_key).map_err(string)?;
        if key.is_weak()
            || payload.schema != "hepta.memory-cell.source-lease.v1"
            || payload.signer_id != self.signer_id
            || payload.agent_id != self.identity.agent_id
            || SystemAuthorityClock.now_unix_ms().map_err(string)? / 1000
                >= payload.expires_at_unix_seconds
        {
            return Err("source lease identity or time rejected".into());
        }
        key.verify_strict(
            &signing_bytes,
            &Signature::from_slice(&signed.signature).map_err(string)?,
        )
        .map_err(string)?;
        ProductionAuthorityLease::from_verified_parts(
            payload.agent_id.clone(),
            Sha256Digest::for_bytes(&signing_bytes),
            payload.authority_epoch,
            payload.owner_epoch,
            payload.expires_at_unix_seconds,
            ProductionAuthorityToken::from_verified_bytes(payload.opaque_token.as_bytes().to_vec())
                .map_err(string)?,
        )
        .map_err(string)
    }
}

impl ProductionAuthorityVerifier for ProcessSourceVerifier {
    fn verify(&self, lease: &ProductionAuthorityLease, owner: &AgentId) -> Result<(), String> {
        if &self.identity.agent_id != owner || &self.current()? != lease {
            return Err("source authority differs from the signed host lease".into());
        }
        Ok(())
    }
}

/// Linux boot identity plus kernel uptime; restart continuity is conditional on
/// the same boot and retained private files. Never presented as attested time.
pub(crate) struct ProcessClock {
    pub identity: AgentdIdentity,
    pub feed: FilePin,
    pub boot_id: String,
    pub last_wall: Mutex<u64>,
    pub poisoned: AtomicBool,
}

impl ProcessClock {
    fn check(&self) -> Result<(u64, u64), String> {
        if self.poisoned.load(Ordering::SeqCst) {
            return Err("process clock continuity lost".into());
        }
        let checked = (|| {
            self.feed.read(&self.identity, /*limit*/ 1_048_576)?;
            let boot = kernel_text("/proc/sys/kernel/random/boot_id")?;
            if self.boot_id.len() != 36 || boot.trim() != self.boot_id {
                return Err("Linux boot identity changed".into());
            }
            let wall = SystemAuthorityClock.now_unix_ms().map_err(string)?;
            let mut previous = self.last_wall.lock().map_err(string)?;
            if wall < *previous {
                return Err("system authority clock moved backwards".into());
            }
            *previous = wall;
            Ok((wall, parse_uptime(&kernel_text("/proc/uptime")?)?))
        })();
        if checked.is_err() {
            self.poisoned.store(true, Ordering::SeqCst);
        }
        checked
    }
}

impl AuthorityClock for ProcessClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.check()
            .map(|(wall, _)| wall)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
}

impl NativeMemoryTickClockV1 for ProcessClock {
    fn observe(&self) -> Result<NativeMemoryClockObservationV1, NativeMemoryError> {
        let (_, monotonic_micros) = self.check().map_err(NativeMemoryError::Rejected)?;
        Ok(NativeMemoryClockObservationV1 {
            domain: Digest32::of_parts(&[
                b"hepta.memory-cell.linux-boot-uptime.v1",
                self.boot_id.as_bytes(),
            ]),
            monotonic_micros,
        })
    }
}

fn kernel_text(path: &str) -> Result<String, String> {
    let mut text = String::new();
    File::open(path)
        .map_err(string)?
        .take(257)
        .read_to_string(&mut text)
        .map_err(string)?;
    if text.len() > 256 {
        return Err("kernel clock input exceeds bound".into());
    }
    Ok(text)
}

fn parse_uptime(text: &str) -> Result<u64, String> {
    let value = text
        .split_whitespace()
        .next()
        .ok_or("kernel uptime absent")?;
    let (seconds, fraction) = value.split_once('.').ok_or("kernel uptime malformed")?;
    if fraction.len() > 6
        || fraction.is_empty()
        || !seconds
            .bytes()
            .chain(fraction.bytes())
            .all(|b| b.is_ascii_digit())
    {
        return Err("kernel uptime precision rejected".into());
    }
    seconds
        .parse::<u64>()
        .map_err(string)?
        .checked_mul(1_000_000)
        .and_then(|whole| {
            whole.checked_add(fraction.parse::<u64>().ok()? * 10_u64.pow(6 - fraction.len() as u32))
        })
        .filter(|value| *value > 0)
        .ok_or_else(|| "kernel uptime out of range".into())
}

pub(crate) fn string(value: impl std::fmt::Display) -> String {
    value.to_string()
}

#[cfg(test)]
#[path = "native_memory_process_trust_tests.rs"]
mod tests;
