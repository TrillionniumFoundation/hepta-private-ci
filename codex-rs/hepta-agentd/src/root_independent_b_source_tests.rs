//! Actual UID0 handoff/FD components, not B admission or a completed run.
//! Closed notices are fixture data; the separate Root factory supplies the
//! real checkpoint predicate in production. No role key or result is forged.

use std::fs::OpenOptions;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixDatagram;
use std::path::Path;

use pretty_assertions::assert_eq;

use super::*;

fn root() -> io::Result<CognitiveCheckpointPeerLifetime> {
    crate::authority_host_service::generation_initial::original_root()?;
    let stat = std::fs::read_to_string("/proc/self/stat")?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, values)| values.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .ok_or_else(|| io::Error::other("actual start absent"))?;
    Ok(CognitiveCheckpointPeerLifetime {
        uid: 0,
        pid: std::process::id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: start,
    })
}

fn pin() -> io::Result<OwnedFd> {
    // SAFETY: this is the actual running test's PID, zero flags, no pointers.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful pidfd_open transfers one new owned descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(raw as i32) })
}

fn bootstrap(mode: SourceMode, file: Option<&File>) -> io::Result<SourceBootstrap> {
    let root = root()?;
    let initial = Digest32::of_bytes(b"source wire component Initial only");
    let meta = file.map(File::metadata).transpose()?;
    Ok(SourceBootstrap {
        schema: 1,
        purpose: PURPOSE.into(),
        mode,
        root: root.clone(),
        source_peer: CognitiveCheckpointPeerLifetime {
            uid: 60_002,
            pid: i32::MAX as u32,
            boot_id: root.boot_id.clone(),
            process_start_ticks: 1,
        },
        learner: CognitiveCheckpointPeerLifetime {
            uid: 60_001,
            pid: i32::MAX as u32 - 1,
            boot_id: root.boot_id,
            process_start_ticks: 1,
        },
        initial: initial.to_string(),
        binding: Digest32::of_parts(&[
            b"hepta.root.independent-b.custodian.v1\0",
            initial.as_array(),
        ])
        .to_string(),
        socket: Path::new("/run/source-component-not-bound").join(SOCKET),
        socket_gid: 60_001,
        source_device: meta.as_ref().map_or(1, MetadataExt::dev),
        source_inode: meta.as_ref().map_or(1, MetadataExt::ino),
        registered_at_seconds: 1,
        absolute_end_monotonic_ns: seal_original_end(Instant::now() + Duration::from_secs(5))?,
        frame_timeout_ms: 500,
    })
}

fn handoff(
    bootstrap: &SourceBootstrap,
    source: Option<File>,
) -> Result<RootIndependentBSourceHandoffV1, AgentdError> {
    let (sending, receiving) = UnixDatagram::pair()?;
    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(&serde_json::to_vec(bootstrap)?)?;
    crate::send_root_independent_b_source_handoff(
        sending,
        crate::RootIndependentBSourceOfferV1 {
            bootstrap: sealed,
            source,
        },
        &pin()?,
        Duration::from_millis(500),
    )?;
    crate::receive_root_independent_b_source_handoff(receiving, Duration::from_millis(500))
}

fn private_file(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
}

#[test]
#[ignore = "actual UID0 original Root source handoff components"]
fn original_b_source_closed_notices_never_open_input_files() -> Result<(), AgentdError> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    for (mode, expected) in [
        (
            SourceMode::Retained,
            OriginalBSourceIngressStatusV1::AlreadyRetained,
        ),
        (
            SourceMode::NoUpdate,
            OriginalBSourceIngressStatusV1::NoUpdate,
        ),
    ] {
        let original = bootstrap(mode, None)?;
        let received = handoff(&original, None)?;
        let result = runtime.block_on(submit_original_root_b_source(received, || {
            panic!("a closed data-only notice must not open source inputs")
        }))?;
        assert_eq!(result, expected);
    }
    Ok(())
}

#[test]
#[ignore = "actual UID0 original Root source handoff components"]
fn original_b_source_closed_notice_rejects_an_added_writer() -> Result<(), AgentdError> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("source");
    let file = private_file(&path)?;
    let original = bootstrap(SourceMode::Retained, Some(&file))?;
    let received = handoff(&original, Some(file))?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    assert!(
        runtime
            .block_on(submit_original_root_b_source(received, || {
                panic!("a mismatched source right must be rejected before input reads")
            }))
            .is_err()
    );
    assert_eq!(std::fs::read(path)?, b"");
    Ok(())
}

#[test]
#[ignore = "actual UID0 original Root source DATA descriptors"]
fn original_b_source_data_writes_once_and_refuses_readonly_or_replacement() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("source");
    let file = private_file(&path)?;
    let original = bootstrap(SourceMode::FreshInput, Some(&file))?;
    assert!(
        data::write_original_source(
            File::open(&path)?,
            &original,
            b"source data only",
            Instant::now() + Duration::from_secs(1)
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&path)?, b"");
    data::write_original_source(
        file,
        &original,
        b"source data only",
        Instant::now() + Duration::from_secs(1),
    )?;
    assert_eq!(std::fs::read(&path)?, b"source data only");
    assert!(
        data::write_original_source(
            OpenOptions::new().read(true).write(true).open(&path)?,
            &original,
            b"replacement",
            Instant::now() + Duration::from_secs(1)
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&path)?, b"source data only");
    Ok(())
}

#[test]
#[ignore = "actual UID0 original Root source DATA descriptors"]
fn original_b_source_data_expiry_or_foreign_inode_writes_nothing() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("source");
    let other = directory.path().join("other");
    let file = private_file(&path)?;
    let original = bootstrap(SourceMode::FreshInput, Some(&file))?;
    assert!(data::write_original_source(file, &original, b"data", Instant::now()).is_err());
    assert_eq!(std::fs::read(&path)?, b"");
    assert!(
        data::write_original_source(
            private_file(&other)?,
            &original,
            b"data",
            Instant::now() + Duration::from_secs(1)
        )
        .is_err()
    );
    assert_eq!(std::fs::read(path)?, b"");
    assert_eq!(std::fs::read(other)?, b"");
    Ok(())
}
