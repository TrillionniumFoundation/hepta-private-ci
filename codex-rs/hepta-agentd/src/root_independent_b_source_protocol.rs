//! Separate, bounded ingress for already signed independent B observations.
//! These bytes never decode an evaluation receipt or release a holdout label.

use std::io;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use serde::Deserialize;
use serde::Serialize;

pub(crate) const PURPOSE: &str = "runtime.learning.independent-b-source.v1";
pub(crate) const SOCKET: &str = "independent-b-source-v1.sock";
pub(crate) const SOURCE_BOUND: usize = 1_048_576;
pub(crate) const FRAME_BOUND: usize = 16_384;
pub(crate) const POLICY_DOMAIN: &[u8] = b"hepta.root.independent-b.original-policies.v1\0";
pub(crate) const OBSERVATION_DOMAIN: &[u8] = b"hepta.root.independent-b.observed-source.v1\0";

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceBootstrap {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) mode: SourceMode,
    pub(crate) root: CognitiveCheckpointPeerLifetime,
    pub(crate) source_peer: CognitiveCheckpointPeerLifetime,
    pub(crate) learner: CognitiveCheckpointPeerLifetime,
    pub(crate) initial: String,
    pub(crate) binding: String,
    pub(crate) socket: PathBuf,
    pub(crate) socket_gid: u32,
    pub(crate) source_device: u64,
    pub(crate) source_inode: u64,
    pub(crate) candidate_data_device: u64,
    pub(crate) candidate_data_inode: u64,
    pub(crate) registered_at_seconds: u64,
    pub(crate) absolute_end_monotonic_ns: u64,
    pub(crate) frame_timeout_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum SourceMode {
    FreshInput,
    Retained,
    NoUpdate,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceRequest {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) binding: String,
    pub(crate) source_digest: String,
    pub(crate) observed_statement: Vec<u8>,
    pub(crate) policy_statement: Vec<u8>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceAcknowledgement {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) binding: String,
    pub(crate) source_digest: String,
    pub(crate) observed_digest: String,
    pub(crate) policy_digest: String,
}

/// Transfer an existing end between same-boot processes conservatively. The
/// receiver never starts a new lifetime from a supplied duration.
pub(crate) fn seal_original_end(end: Instant) -> io::Result<u64> {
    let sampled = monotonic_ns()?;
    let remaining = end
        .checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero() && *left <= Duration::from_secs(300))
        .ok_or_else(|| io::Error::other("original B source end unavailable"))?;
    sampled
        .checked_add(u64::try_from(remaining.as_nanos()).map_err(io::Error::other)?)
        .ok_or_else(|| io::Error::other("original B source end overflow"))
}

pub(crate) fn receive_original_end(sealed: u64) -> io::Result<Instant> {
    let before = Instant::now();
    let left = sealed
        .checked_sub(monotonic_ns()?)
        .map(Duration::from_nanos)
        .filter(|left| !left.is_zero() && *left <= Duration::from_secs(300))
        .ok_or_else(|| io::Error::other("original B source end elapsed"))?;
    before
        .checked_add(left)
        .ok_or_else(|| io::Error::other("original B source end overflow"))
}

fn monotonic_ns() -> io::Result<u64> {
    let mut sample = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: the kernel writes exactly one live initialized timespec.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut sample) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let seconds = u64::try_from(sample.tv_sec).map_err(io::Error::other)?;
    let nanos = u64::try_from(sample.tv_nsec).map_err(io::Error::other)?;
    if nanos >= 1_000_000_000 {
        return Err(io::Error::other("invalid original monotonic sample"));
    }
    seconds
        .checked_mul(1_000_000_000)
        .and_then(|value| value.checked_add(nanos))
        .ok_or_else(|| io::Error::other("original monotonic sample overflow"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn original_b_source_end_transfer_never_renews_the_original_end() -> io::Result<()> {
        let original = Instant::now() + Duration::from_millis(250);
        let sealed = seal_original_end(original)?;
        let received = receive_original_end(sealed)?;
        assert!(received <= original);
        assert!(received > Instant::now());
        Ok(())
    }

    #[test]
    fn original_b_source_end_rejects_expiry_and_a_new_oversized_lifetime() -> io::Result<()> {
        assert!(seal_original_end(Instant::now()).is_err());
        assert!(seal_original_end(Instant::now() + Duration::from_secs(301)).is_err());
        assert!(receive_original_end(0).is_err());
        assert!(receive_original_end(monotonic_ns()? + 301_000_000_000).is_err());
        Ok(())
    }
}
