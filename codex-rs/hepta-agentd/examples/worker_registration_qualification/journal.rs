//! Explicit real-Child journal controls. No provider, grant Sign or claim is
//! exercised; the same-custody journal observations are not effect authority.

use codex_hepta_agentd::WorkerRootJournalBootstrapV1;
use codex_hepta_agentd::receive_root_production_handoff;
use codex_hepta_agentd::receive_worker_root_registration;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::HostConsumerFrontierRequestV1;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

pub(super) fn run(mode: &str, socket: UnixDatagram, agent: &AgentId, generation: u64) -> Result<(), Box<dyn std::error::Error>> {
    let unacknowledged = socket.try_clone()?;
    let registration = receive_worker_root_registration(socket, agent, generation, Duration::from_secs(5))?;
    if mode == "journal-second-offer-no-ack" {
        let (mut sealed, _root) = receive_root_production_handoff(unacknowledged, Duration::from_secs(5))?;
        sealed.rewind()?;
        let mut bytes = Vec::new();
        Read::by_ref(&mut sealed).take(64 * 1024 + 1).read_to_end(&mut bytes)?;
        assert!(bytes.len() <= 64 * 1024);
        let offer: WorkerRootJournalBootstrapV1 = serde_json::from_slice(&bytes)?;
        let journal = &offer.journal.directory;
        assert!(std::fs::read_dir(journal)?.next().is_none(), "Root mkdir/chown is not a journal initialization");
        let mut streams = Vec::new();
        for path in [&offer.lanes.sockets.observation, &offer.lanes.sockets.issuer, &offer.lanes.sockets.consumer_frontier] {
            let stream = UnixStream::connect(path)?;
            stream.set_read_timeout(Some(Duration::from_millis(80)))?;
            streams.push(stream);
        }
        let request = serde_json::to_vec(&HostConsumerFrontierRequestV1::Load { schema_version: 1, request_id: 1 })?;
        let stream = &mut streams[2];
        stream.write_all(&(request.len() as u32).to_be_bytes())?;
        stream.write_all(&request)?;
        let error = stream.read(&mut [0]).expect_err("unacknowledged journal must receive no Root frontier response");
        assert!(matches!(error.kind(), std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock));
        drop(streams);
        drop(registration);
        send(&serde_json::json!({"kind":"journal_offer_without_ack", "offer":offer,
            "actual_connections":3, "frontier_response_bytes":0, "journal_files_created":0, "effect_authorization_available":false}))?;
        stop()?;
        return Ok(());
    }
    drop(unacknowledged);
    let executor = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    if mode == "journal-refuse-before-offer" {
        let error = executor.block_on(registration.receive_worker_journal(Duration::from_secs(5))).err()
            .expect("Root must refuse missing/currentness/partial journal custody");
        executor.shutdown_timeout(Duration::from_secs(1));
        send(&serde_json::json!({"kind":"journal_refused", "error":error.to_string(), "effect_authorization_available":false}))?;
        stop()?;
        return Ok(());
    }
    let mut owner = executor.block_on(registration.receive_worker_journal(Duration::from_secs(5)))?;
    let first = owner.refresh_and_observe()?;
    assert!(!first.effect_authorization_available);
    assert_eq!(first.used_nonces, 0);
    let directory = first.journal.directory.clone();
    let files = ["authority.lock", "authority.json", "authority.claims"].map(|name| {
        let metadata = std::fs::symlink_metadata(directory.join(name)).unwrap();
        assert!(metadata.is_file());
        assert_eq!(metadata.uid(), first.journal.worker_uid);
        assert_eq!(metadata.gid(), first.journal.worker_gid);
        assert_eq!(metadata.mode() & 0o777, 0o600);
        assert_eq!(metadata.nlink(), 1);
        serde_json::json!({"name":name, "uid":metadata.uid(), "gid":metadata.gid(), "mode":metadata.mode()&0o777, "device":metadata.dev(), "inode":metadata.ino(), "bytes":metadata.len()})
    });
    let message = match mode {
        "journal-roundtrip" => {
            owner = owner.reopen_existing()?;
            let second = owner.refresh_and_observe()?;
            assert_eq!(first.frontier, second.frontier);
            assert_eq!(first.journal, second.journal);
            assert_eq!(first.revocations, second.revocations);
            drop(owner);
            serde_json::json!({"kind":"journal_roundtrip", "first":first, "second":second, "actual_files":files})
        }
        "journal-missing-snapshot" => {
            std::fs::remove_file(directory.join("authority.json"))?;
            let error = owner.reopen_existing().err().expect("strict reopen must refuse missing original snapshot");
            assert!(!directory.join("authority.json").exists(), "strict reopen must not repair the missing snapshot");
            serde_json::json!({"kind":"journal_missing_snapshot_refused", "first":first, "error":error.to_string(), "snapshot_recreated":false})
        }
        "journal-replaced-lock" | "journal-copied-claims" => {
            let name = if mode == "journal-replaced-lock" { "authority.lock" } else { "authority.claims" };
            let path = directory.join(name);
            let held = directory.join("held-original-file");
            let original = std::fs::read(&path)?;
            let original_inode = std::fs::metadata(&path)?.ino();
            std::fs::rename(&path, &held)?;
            write_new(&path, &original)?;
            let copied_inode = std::fs::metadata(&path)?.ino();
            assert_ne!(original_inode, copied_inode);
            assert_eq!(std::fs::read(&path)?, original);
            assert!(owner.refresh_and_observe().is_err(), "a byte-identical replacement must fence the retained journal");
            std::fs::remove_file(&path)?;
            std::fs::rename(held, &path)?;
            assert!(owner.refresh_and_observe().is_err(), "restoring old names cannot revive the same fenced owner");
            drop(owner);
            serde_json::json!({"kind":"journal_replacement_refused", "file":name, "first":first,
                "original_inode":original_inode, "copied_inode":copied_inode, "bytes_equal_before_refusal":true, "restored_owner_revived":false})
        }
        "journal-clock-stale" => {
            std::thread::sleep(Duration::from_millis(550));
            assert!(owner.refresh_and_observe().is_err(), "expired original projection must not be reinitialized by refresh");
            assert!(owner.refresh_and_observe().is_err(), "the same clock remains permanently fenced");
            drop(owner);
            serde_json::json!({"kind":"journal_clock_stale_refused", "first":first, "clock_window_ns":500_000_000_u64, "same_owner_revived":false})
        }
        "journal-head-and-rollback" => {
            let initial_snapshot = std::fs::read(directory.join("authority.json"))?;
            send(&serde_json::json!({"kind":"journal_ready_for_original_root_revoke", "first":first, "actual_files":files}))?;
            command(2)?;
            let advanced = owner.refresh_and_observe()?;
            assert_eq!(advanced.revocations.authority_epoch, first.revocations.authority_epoch);
            assert_eq!(advanced.revocations.revision, first.revocations.revision + 1);
            assert!(advanced.revocations.revoked_grant_ids.contains("worker-journal-original-root-revocation"));
            assert_ne!(advanced.frontier, first.frontier);
            send(&serde_json::json!({"kind":"journal_original_head_and_floor_advanced", "advanced":advanced}))?;
            command(3)?;
            let current_snapshot = std::fs::read(directory.join("authority.json"))?;
            assert_ne!(initial_snapshot, current_snapshot);
            std::fs::write(directory.join("authority.json"), &initial_snapshot)?;
            let error = owner.reopen_existing().err().expect("actual Root newer head/floor must reject the copied old journal snapshot");
            assert_eq!(std::fs::read(directory.join("authority.json"))?, initial_snapshot);
            serde_json::json!({"kind":"journal_old_snapshot_refused", "advanced":advanced, "error":error.to_string(), "snapshot_repaired":false, "effect_authorization_available":false})
        }
        _ => return Err("unknown explicit Worker journal qualification mode".into()),
    };
    executor.shutdown_timeout(Duration::from_secs(1));
    send(&message)?;
    stop()?;
    Ok(())
}

fn write_new(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn send(value: &serde_json::Value) -> std::io::Result<()> {
    let bytes = serde_json::to_vec(value).map_err(std::io::Error::other)?;
    assert!(bytes.len() <= 64 * 1024);
    let mut output = std::io::stdout().lock();
    output.write_all(&(bytes.len() as u32).to_be_bytes())?;
    output.write_all(&bytes)?;
    output.flush()
}

fn command(expected: u8) -> std::io::Result<()> {
    let mut command = [0];
    std::io::stdin().read_exact(&mut command)?;
    assert_eq!(command, [expected]);
    Ok(())
}

fn stop() -> std::io::Result<()> { command(1) }
