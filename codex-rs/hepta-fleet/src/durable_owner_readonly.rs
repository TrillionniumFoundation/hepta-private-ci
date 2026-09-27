//! Inspection never initializes, repairs, chmods, or advances authority state.
use super::*;

#[derive(Clone, Debug)]
pub struct FleetReadOnlySnapshotV1 {
    pub state: DurableFleetStateV1,
    pub metrics: FleetOperationalMetricsV1,
    pub sampled_at_ms: u64,
}

/// A shared owner lock pins this authority cut across one physical effect.
#[derive(Debug)]
pub struct FleetReadOnlyFenceV1 {
    pub snapshot: FleetReadOnlySnapshotV1,
    _lock: File,
}

pub fn read_fleet_snapshot(
    supervisor_state_root: impl AsRef<Path>,
    clock: Arc<dyn FleetClock>,
) -> Result<FleetReadOnlySnapshotV1, DurableFleetError> {
    Ok(lock_fleet_snapshot(supervisor_state_root, clock)?.snapshot)
}

/// Read one coherent, already-sealed snapshot. A live writer or an unsealed
/// descendant is an explicit diagnostic failure; only the real owner recovers.
/// Process-local counters in `metrics` are unavailable, not observed zeros.
pub fn lock_fleet_snapshot(
    supervisor_state_root: impl AsRef<Path>,
    clock: Arc<dyn FleetClock>,
) -> Result<FleetReadOnlyFenceV1, DurableFleetError> {
    let supervisor_state_root = supervisor_state_root.as_ref();
    if !supervisor_state_root.is_absolute() {
        return Err(DurableFleetError::CorruptState);
    }
    let root = supervisor_state_root.join(DURABLE_FLEET_DIRECTORY);
    for path in [supervisor_state_root, root.as_path()] {
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(DurableFleetError::CorruptState);
        }
    }
    let lock_path = root.join(DURABLE_FLEET_LOCK);
    let metadata = std::fs::symlink_metadata(&lock_path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(DurableFleetError::CorruptState);
    }
    let mut options = OpenOptions::new();
    options.read(true);
    let lock = options.open(&lock_path)?;
    // Read-only open cannot create/truncate a target. Before locking or reading
    // authority data, reject replacement between the path check and open.
    let opened = lock.metadata()?;
    let current = std::fs::symlink_metadata(&lock_path)?;
    if !opened.is_file() || !current.is_file() || current.file_type().is_symlink() {
        return Err(DurableFleetError::CorruptState);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if opened.dev() != metadata.dev()
            || opened.ino() != metadata.ino()
            || current.dev() != opened.dev()
            || current.ino() != opened.ino()
        {
            return Err(DurableFleetError::CorruptState);
        }
    }
    lock.try_lock_shared().map_err(std::io::Error::other)?;
    let mut latest = None;
    visit_retained_states(&root, |state| latest = Some(state))?;
    let latest = latest.ok_or(DurableFleetError::MissingState)?;
    let frontier =
        load_frontier(&root.join(LATEST_FRONTIER_FILE))?.ok_or(DurableFleetError::CorruptState)?;
    if frontier.generation != latest.generation
        || frontier.state_sha256 != latest.content_sha256
        || frontier.previous_state_sha256 != latest.previous_state_sha256
    {
        return Err(DurableFleetError::CorruptState);
    }
    let sampled_at_ms = clock.now_unix_ms()?;
    let (state, metrics) =
        core::inspect_validated_state(latest, supervisor_state_root.to_path_buf(), clock)?;
    Ok(FleetReadOnlyFenceV1 {
        snapshot: FleetReadOnlySnapshotV1 {
            state,
            metrics,
            sampled_at_ms,
        },
        _lock: lock,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SystemFleetClock;
    use std::collections::BTreeMap;

    fn image(root: &Path) -> BTreeMap<PathBuf, (Vec<u8>, std::time::SystemTime)> {
        std::fs::read_dir(root)
            .expect("directory")
            .map(|entry| {
                let entry = entry.expect("entry");
                let path = entry.path();
                let metadata = entry.metadata().expect("metadata");
                (
                    path.clone(),
                    (
                        std::fs::read(path).expect("bytes"),
                        metadata.modified().expect("mtime"),
                    ),
                )
            })
            .collect()
    }

    #[test]
    fn inspection_preserves_bytes_mtimes_and_missing_lock_or_frontier() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().join("state");
        std::fs::create_dir(&root).expect("root");
        DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
            .expect("owner");
        let control = root.join(DURABLE_FLEET_DIRECTORY);
        let before = image(&control);
        assert_eq!(
            read_fleet_snapshot(&root, Arc::new(SystemFleetClock))
                .expect("snapshot")
                .state
                .generation,
            0
        );
        assert_eq!(image(&control), before);
        for name in [LATEST_FRONTIER_FILE, DURABLE_FLEET_LOCK] {
            let path = control.join(name);
            let bytes = std::fs::read(&path).expect("bytes");
            std::fs::remove_file(&path).expect("remove");
            let damaged = image(&control);
            assert!(read_fleet_snapshot(&root, Arc::new(SystemFleetClock)).is_err());
            assert_eq!(image(&control), damaged);
            std::fs::write(path, bytes).expect("restore fixture");
        }
    }

    #[test]
    fn missing_state_and_writer_contention_are_not_healthy_empty_snapshots() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().join("absent");
        assert!(read_fleet_snapshot(&root, Arc::new(SystemFleetClock)).is_err());
        assert!(!root.exists());
        std::fs::create_dir(&root).expect("root");
        DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
            .expect("owner");
        let control = root.join(DURABLE_FLEET_DIRECTORY);
        let file = File::open(control.join(DURABLE_FLEET_LOCK)).expect("lock");
        file.lock().expect("writer");
        assert!(read_fleet_snapshot(&root, Arc::new(SystemFleetClock)).is_err());
    }

    #[test]
    fn inspection_does_not_repair_the_publication_crash_window() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().join("state");
        std::fs::create_dir(&root).expect("root");
        DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
            .expect("owner");
        let mut core =
            core::DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("core");
        core.persist_revocation_snapshot("crash-window", FleetRevocationSnapshotV1::empty(1_000))
            .expect("publish unsealed descendant");
        let control = root.join(DURABLE_FLEET_DIRECTORY);
        let before = image(&control);
        assert!(read_fleet_snapshot(&root, Arc::new(SystemFleetClock)).is_err());
        assert_eq!(image(&control), before);
        drop(core);
        DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
            .expect("owner recovery");
        assert_eq!(
            read_fleet_snapshot(&root, Arc::new(SystemFleetClock))
                .expect("sealed")
                .state
                .generation,
            1
        );
    }
}
