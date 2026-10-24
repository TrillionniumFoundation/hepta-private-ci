//! Consume actual inherited Session descriptors. The trusted launcher supplies
//! birth identity and a held pidfd, never a renderer-selected PID or endpoint.

use std::fs::File;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::time::Duration;

use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::io::unix::AsyncFd;

use crate::AgentdError;
use crate::notes_literal_adapter::invalid;
use crate::notes_ui_queue::NotesUiQueue;
use crate::notes_ui_wire::*;

const MAX_UI_FRAME_BYTES: u64 = 65_536;
const EXCHANGE_DEADLINE: Duration = Duration::from_millis(75);

/// Root's sealed deployment identity for the one actual Session. The original
/// Desktop bridge requires Session and Agentd to share one dedicated UID.
pub struct AgentdNotesUiPeer {
    pub uid: u32,
    pub pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
}

pub(crate) struct NotesUiEndpoint {
    listener: tokio::net::UnixListener,
    pub(crate) lifetime: AsyncFd<OwnedFd>,
    peer: AgentdNotesUiPeer,
}

impl NotesUiEndpoint {
    pub(crate) fn from_inherited(listener: OwnedFd, session_pidfd: OwnedFd, peer: AgentdNotesUiPeer)
    -> Result<Self, AgentdError> {
        // SAFETY: geteuid only reads this process's current credentials.
        let own_uid = unsafe { libc::geteuid() };
        if peer.uid != own_uid || peer.pid == 0 || peer.pid > i32::MAX as u32
            || peer.process_start_ticks == 0 || peer.boot_id.len() != 36
        { return Err(invalid("Notes UI requires the actual same-UID Session birth identity")); }
        for (option, expected) in [(libc::SO_TYPE, libc::SOCK_STREAM), (libc::SO_DOMAIN, libc::AF_UNIX), (libc::SO_ACCEPTCONN, 1)] {
            let mut value: libc::c_int = 0;
            let mut length = std::mem::size_of_val(&value) as libc::socklen_t;
            // SAFETY: OwnedFd remains held and the integer buffer/length match.
            let result = unsafe { libc::getsockopt(listener.as_raw_fd(), libc::SOL_SOCKET,
                option, std::ptr::from_mut(&mut value).cast(), &mut length) };
            if result != 0 || length as usize != std::mem::size_of_val(&value) || value != expected {
                return Err(invalid("Notes UI needs an inherited listening Unix stream socket"));
            }
        }
        let listener = std::os::unix::net::UnixListener::from(listener);
        let address = listener.local_addr()?;
        let path = address.as_pathname().ok_or_else(|| invalid("Notes UI listener has no filesystem address"))?;
        let node = std::fs::symlink_metadata(path)?;
        if !path.is_absolute() || !node.file_type().is_socket() || node.uid() != own_uid || node.mode() & 0o777 != 0o600 {
            return Err(invalid("Notes UI socket node must be private to the actual Session/Agentd UID"));
        }
        let number = session_pidfd.as_raw_fd();
        if std::fs::read_link(format!("/proc/self/fd/{number}"))? != Path::new("anon_inode:[pidfd]")
            || bounded_text(&format!("/proc/self/fdinfo/{number}"), 4096)?.lines()
                .find_map(|line| line.strip_prefix("Pid:")?.trim().parse::<u32>().ok()) != Some(peer.pid)
            || bounded_text("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id
        { return Err(invalid("Notes UI pidfd or boot identity differs from actual Session")); }
        let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
        if stat.rsplit_once(") ").and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok()) != Some(peer.process_start_ticks)
        { return Err(invalid("Notes UI Session process birth differs")); }
        crate::root_observation_stream::check_lifetime(&session_pidfd)
            .map_err(|_| invalid("Notes UI Session is no longer alive"))?;
        listener.set_nonblocking(true)?;
        let listener = tokio::net::UnixListener::from_std(listener)?;
        // SAFETY: the AsyncFd owns the held pidfd exclusively for its lifetime.
        let lifetime = unsafe { AsyncFd::register_with_interest(session_pidfd, tokio::io::Interest::READABLE) }?;
        let endpoint = Self { listener, lifetime, peer };
        endpoint.check_alive()?;
        Ok(endpoint)
    }

    pub(crate) fn check_alive(&self) -> Result<(), AgentdError> {
        crate::root_observation_stream::check_lifetime(self.lifetime.get_ref())
            .map_err(|_| invalid("original Notes Session lifetime ended"))
    }

    pub(crate) async fn receive(&self, queue: &NotesUiQueue) -> Result<(), AgentdError> {
        loop {
            self.check_alive()?;
            let (mut stream, _) = self.listener.accept().await?;
            self.check_alive()?;
            let credential = stream.peer_cred()?;
            if credential.uid() != self.peer.uid
                || credential.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(self.peer.pid)
            { continue; }
            // The original Session grants only 150 ms to one exchange. Owner
            // work runs independently; only bounded parse/queue/cache I/O occurs.
            let _exchange = tokio::time::timeout(EXCHANGE_DEADLINE, async {
                let mut frame = Vec::new();
                BufReader::new((&mut stream).take(MAX_UI_FRAME_BYTES + 1)).read_until(b'\n', &mut frame).await?;
                self.check_alive()?;
                let command = if frame.is_empty() || frame.len() as u64 > MAX_UI_FRAME_BYTES || !frame.ends_with(b"\n") {
                    None
                } else { serde_json::from_slice::<ObjectiveCommand>(&frame).ok() };
                let view = match command {
                    Some(command) => queue.request(command),
                    None => {
                        let mut view = ObjectiveObservation::new(None, ObjectiveStage::Unavailable);
                        view.issue = Some(ObjectiveHostIssue::InvalidIntent);
                        view
                    }
                };
                let mut reply = serde_json::to_vec(&view)?;
                reply.push(b'\n');
                if reply.len() as u64 > MAX_UI_FRAME_BYTES { return Err(invalid("Notes UI observation exceeds original frame bound")); }
                self.check_alive()?;
                stream.write_all(&reply).await?;
                stream.shutdown().await?;
                Ok::<(), AgentdError>(())
            }).await;
            // A dropped/malformed UI exchange cannot terminate the daemon or
            // rearm an action. Session death is handled by the held pidfd.
            self.check_alive()?;
        }
    }
}

fn bounded_text(path: &str, limit: u64) -> Result<String, AgentdError> {
    let mut text = String::new();
    File::open(path)?.take(limit + 1).read_to_string(&mut text)?;
    if text.len() as u64 > limit { return Err(invalid("Notes UI process metadata exceeds bound")); }
    Ok(text)
}

#[cfg(test)]
#[path = "notes_ui_endpoint_tests.rs"]
mod tests;
