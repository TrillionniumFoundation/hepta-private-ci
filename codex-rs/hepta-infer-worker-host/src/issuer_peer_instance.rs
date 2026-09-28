//! Linux connected-peer instance continuity, in addition to the issuer UID/key.
//! This does not attest a binary or make two processes under one UID independent.

use std::error::Error as StdError;
#[cfg(target_os = "linux")]
use std::io::Read;
use std::path::Path;

#[cfg(target_os = "linux")]
use tokio::net::UnixStream;

type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

#[cfg(target_os = "linux")]
#[derive(Debug, Eq, PartialEq)]
pub(super) struct PeerInstance {
    pid: i32,
    start_ticks: u64,
    executable_device: u64,
    executable_inode: u64,
    boot_id: String,
}

#[cfg(target_os = "linux")]
impl PeerInstance {
    pub(super) fn capture(stream: &UnixStream) -> Result<Self> {
        use std::os::unix::fs::MetadataExt;

        let pid = stream
            .peer_cred()?
            .pid()
            .filter(|pid| *pid > 0)
            .ok_or("final-use authority has no valid connected peer PID")?;
        let before = read_bounded(&format!("/proc/{pid}/stat"), 8_192)?;
        let executable = std::fs::metadata(format!("/proc/{pid}/exe"))?;
        let after = read_bounded(&format!("/proc/{pid}/stat"), 8_192)?;
        let start_ticks = process_start_ticks(&before)?;
        if start_ticks != process_start_ticks(&after)? {
            return Err("issuer process changed while its instance was sampled".into());
        }
        let boot_id = String::from_utf8(read_bounded("/proc/sys/kernel/random/boot_id", 128)?)?;
        if boot_id.trim().is_empty() {
            return Err("empty issuer boot identity".into());
        }
        Ok(Self {
            pid,
            start_ticks,
            executable_device: executable.dev(),
            executable_inode: executable.ino(),
            boot_id,
        })
    }

    pub(super) fn revalidate(&self, stream: &UnixStream) -> Result<()> {
        if self != &Self::capture(stream)? {
            return Err("final-use authority connected process instance changed".into());
        }
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn read_bounded(path: &str, maximum: u64) -> Result<Vec<u8>> {
    let file = std::fs::File::open(path)?;
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() as u64 > maximum {
        return Err("invalid bounded issuer process metadata".into());
    }
    Ok(bytes)
}

#[cfg(target_os = "linux")]
fn process_start_ticks(bytes: &[u8]) -> Result<u64> {
    let text = std::str::from_utf8(bytes)?;
    // comm (field 2) can itself contain spaces and ')' characters.
    let (_, tail) = text.rsplit_once(')').ok_or("invalid issuer /proc stat")?;
    let start = tail
        .split_whitespace()
        .nth(19)
        .ok_or("short issuer /proc stat")?;
    let ticks = start.parse::<u64>()?;
    if ticks == 0 {
        return Err("zero issuer process start time".into());
    }
    Ok(ticks)
}

#[cfg(unix)]
pub(super) fn require_same_socket(before: &std::fs::Metadata, path: &Path) -> Result<()> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;

    let after = std::fs::symlink_metadata(path)?;
    if !after.file_type().is_socket()
        || (before.dev(), before.ino(), before.uid(), before.mode())
            != (after.dev(), after.ino(), after.uid(), after.mode())
    {
        return Err("final-use authority socket changed during connect/exchange".into());
    }
    Ok(())
}

#[cfg(all(test, target_os = "linux"))]
#[path = "issuer_peer_instance_tests.rs"]
mod tests;
