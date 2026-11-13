//! Actual UID0 datagrams and descriptors. The bootstrap is component DATA;
//! these tests do not enroll a source, sign observations or complete B.

use std::fs::OpenOptions;
use std::os::fd::FromRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::time::Instant;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::*;
use crate::root_independent_b_notice::OriginalBNoticeWriter;
use crate::root_independent_b_source_protocol::*;

struct OriginalRights {
    _directory: tempfile::TempDir,
    _candidate_notice_writer: OriginalBNoticeWriter,
    _finalized_writer: OriginalBNoticeWriter,
    sealed: File,
    pin: OwnedFd,
    source: File,
    candidate: File,
    candidate_writer: File,
    notice: File,
    finalized: File,
}

impl OriginalRights {
    fn new() -> Result<Self, AgentdError> {
        crate::authority_host_service::generation_initial::original_root()?;
        let directory = tempfile::Builder::new()
            .prefix("b-rights-")
            .tempdir_in("/run")?;
        let private = |name| {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .mode(0o600)
                .open(directory.path().join(name))
        };
        let source = private("source")?;
        let candidate_writer = private("candidate")?;
        let candidate = File::open(directory.path().join("candidate"))?;
        let (candidate_notice_writer, notice) = OriginalBNoticeWriter::pair()?;
        let (finalized_writer, finalized) = OriginalBNoticeWriter::pair()?;
        let stat = std::fs::read_to_string("/proc/self/stat")?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, s)| s.split_whitespace().nth(19))
            .and_then(|s| s.parse().ok())
            .ok_or_else(|| io::Error::other("actual start absent"))?;
        let root = CognitiveCheckpointPeerLifetime {
            uid: 0,
            pid: std::process::id(),
            process_start_ticks: start,
            boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                .trim()
                .into(),
        };
        let source_metadata = source.metadata()?;
        let candidate_metadata = candidate.metadata()?;
        let notice_metadata = notice.metadata()?;
        let finalized_metadata = finalized.metadata()?;
        let initial = Digest32::of_bytes(b"component rights only");
        let bootstrap = SourceBootstrap {
            schema: 3,
            purpose: PURPOSE.into(),
            mode: SourceMode::FreshInput,
            root: root.clone(),
            source_peer: root.clone(),
            learner: root,
            initial: initial.to_string(),
            binding: initial.to_string(),
            socket: directory.path().join(SOCKET),
            socket_gid: 0,
            source_device: source_metadata.dev(),
            source_inode: source_metadata.ino(),
            candidate_data_device: candidate_metadata.dev(),
            candidate_data_inode: candidate_metadata.ino(),
            candidate_notice_device: notice_metadata.dev(),
            candidate_notice_inode: notice_metadata.ino(),
            source_finalized_device: finalized_metadata.dev(),
            source_finalized_inode: finalized_metadata.ino(),
            registered_at_seconds: 1,
            absolute_end_monotonic_ns: seal_original_end(Instant::now() + Duration::from_secs(5))?,
            frame_timeout_ms: 500,
        };
        let sealed =
            crate::authority_host_bootstrap_seal::seal_bytes(&serde_json::to_vec(&bootstrap)?)?;
        // SAFETY: pidfd_open observes the running test and returns one owned FD.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
        if raw < 0 {
            return Err(io::Error::last_os_error().into());
        }
        // SAFETY: successful pidfd_open transferred this descriptor exactly once.
        let pin = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        Ok(Self {
            _directory: directory,
            _candidate_notice_writer: candidate_notice_writer,
            _finalized_writer: finalized_writer,
            sealed,
            pin,
            source,
            candidate,
            candidate_writer,
            notice,
            finalized,
        })
    }

    fn receive(&self, positions: &[usize]) -> Result<RootIndependentBSourceHandoffV1, AgentdError> {
        let rights = [
            self.sealed.as_raw_fd(),
            self.pin.as_raw_fd(),
            self.source.as_raw_fd(),
            self.candidate.as_raw_fd(),
            self.notice.as_raw_fd(),
            self.finalized.as_raw_fd(),
            self.candidate_writer.as_raw_fd(),
        ];
        let selected: Vec<_> = positions.iter().map(|&i| rights[i]).collect();
        let (sending, receiving) = UnixDatagram::pair()?;
        send_packet(&sending, FRAME, &selected, Duration::from_millis(500))?;
        receive_root_independent_b_source_handoff(receiving, Duration::from_millis(500))
    }
}

#[test]
#[ignore = "actual UID0 original Root B six-right handoff"]
fn original_b_source_fresh_handoff_requires_six_exact_original_rights() -> Result<(), AgentdError> {
    let original = OriginalRights::new()?;
    let received = original.receive(&[0, 1, 2, 3, 4, 5])?;
    assert_eq!(received.root_pid, std::process::id());
    assert!(
        received.source.is_some()
            && received.candidate_data.is_some()
            && received.candidate_notice.is_some()
            && received.source_finalized.is_some()
    );
    for positions in [
        &[0, 1][..],
        &[0, 1, 2],
        &[0, 1, 2, 3],
        &[0, 1, 2, 3, 4],
        &[0, 1, 2, 3, 4, 5, 6],
    ] {
        assert!(
            original.receive(positions).is_err(),
            "rights: {positions:?}"
        );
    }
    for index in 0..5 {
        let mut positions = [0, 1, 2, 3, 4, 5];
        positions.swap(index, index + 1);
        assert!(
            original.receive(&positions).is_err(),
            "swapped positions: {positions:?}"
        );
    }
    // Same Root peer and socket type do not authorize swapped notification roles.
    assert!(original.receive(&[0, 1, 2, 3, 5, 4]).is_err());
    // The candidate position must be the original independent O_RDONLY FD.
    assert!(original.receive(&[0, 1, 2, 6, 4, 5]).is_err());
    assert_eq!(original.source.metadata()?.len(), 0);
    assert_eq!(original.candidate.metadata()?.len(), 0);
    Ok(())
}
