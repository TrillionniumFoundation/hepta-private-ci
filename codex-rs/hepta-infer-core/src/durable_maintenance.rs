//! Cooperative, owner-directory maintenance. Inventory is a rebuildable
//! observation, NEVER an admission, deduplication, or retirement authority.
use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct MaintenanceStats {
    pub archive_verified_bytes: u64,
    pub archive_cache_reuses: u64,
    pub inventory_scans: u64,
    pub inventory_entries: u64,
    pub lock_attempts: u64,
    pub lock_acquisitions: u64,
    pub lock_acquire_ns: u64,
    pub lock_held_ns: u64,
    pub lock_max_held_ns: u64,
    pub lock_release_errors: u64,
}

#[derive(Debug, Default)]
pub(super) struct Counters {
    archive_verified_bytes: AtomicU64,
    archive_cache_reuses: AtomicU64,
    inventory_scans: AtomicU64,
    inventory_entries: AtomicU64,
    lock_attempts: AtomicU64,
    lock_acquisitions: AtomicU64,
    lock_acquire_ns: AtomicU64,
    lock_held_ns: AtomicU64,
    lock_max_held_ns: AtomicU64,
    lock_release_errors: AtomicU64,
}

impl Counters {
    pub(super) fn snapshot(&self) -> MaintenanceStats {
        MaintenanceStats {
            archive_verified_bytes: self.archive_verified_bytes.load(Ordering::Relaxed),
            archive_cache_reuses: self.archive_cache_reuses.load(Ordering::Relaxed),
            inventory_scans: self.inventory_scans.load(Ordering::Relaxed),
            inventory_entries: self.inventory_entries.load(Ordering::Relaxed),
            lock_attempts: self.lock_attempts.load(Ordering::Relaxed),
            lock_acquisitions: self.lock_acquisitions.load(Ordering::Relaxed),
            lock_acquire_ns: self.lock_acquire_ns.load(Ordering::Relaxed),
            lock_held_ns: self.lock_held_ns.load(Ordering::Relaxed),
            lock_max_held_ns: self.lock_max_held_ns.load(Ordering::Relaxed),
            lock_release_errors: self.lock_release_errors.load(Ordering::Relaxed),
        }
    }
}

/// Owns the fence, not a borrow of the controller. Drop includes validation,
/// replay, persistence and error paths; model/provider work stays outside it.
#[derive(Debug)]
pub(super) struct WriterFence {
    _file: File,
    acquired: Instant,
    counters: Arc<Counters>,
}

impl WriterFence {
    pub(super) fn acquire(path: &Path, counters: Arc<Counters>) -> Result<Self, Error> {
        counters.lock_attempts.fetch_add(1, Ordering::Relaxed);
        let started = Instant::now();
        let result = acquire_writer_lock(path);
        counters
            .lock_acquire_ns
            .fetch_add(nanos(started), Ordering::Relaxed);
        let file = result?;
        counters.lock_acquisitions.fetch_add(1, Ordering::Relaxed);
        Ok(Self {
            _file: file,
            acquired: Instant::now(),
            counters,
        })
    }
}

impl Drop for WriterFence {
    fn drop(&mut self) {
        // Closing our descriptor alone leaves flock held by any descriptor
        // duplicated during concurrent process creation. End the critical
        // section explicitly; children must never prolong the writer fence.
        // Drop cannot report I/O errors. Preserve a diagnostic counter and
        // still close the descriptor as the fallback release path.
        if self._file.unlock().is_err() {
            self.counters
                .lock_release_errors
                .fetch_add(1, Ordering::Relaxed);
        }
        let held = nanos(self.acquired);
        self.counters
            .lock_held_ns
            .fetch_add(held, Ordering::Relaxed);
        self.counters
            .lock_max_held_ns
            .fetch_max(held, Ordering::Relaxed);
    }
}

fn nanos(start: Instant) -> u64 {
    u64::try_from(start.elapsed().as_nanos()).unwrap_or(u64::MAX)
}

struct CountedReader<'a> {
    file: &'a mut File,
    bytes: &'a AtomicU64,
}

impl Read for CountedReader<'_> {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        let count = self.file.read(buffer)?;
        self.bytes.fetch_add(count as u64, Ordering::Relaxed);
        Ok(count)
    }
}

pub(super) fn verify_archive(
    path: &Path,
    digest: Option<&str>,
    cached: Option<FileStamp>,
    counters: &Counters,
) -> Result<Option<FileStamp>, Error> {
    let Some(digest) = digest else {
        return Ok(None);
    };
    let archive = archive_path(path, digest)?;
    if !fs::symlink_metadata(&archive)?.is_file() {
        return Err(Error::InvalidIdentity("compaction archive must be regular"));
    }
    let mut file = File::open(&archive)?;
    validate_private_file(&file)?;
    let before = file_stamp(&file)?;
    if before.is_some() && before == cached {
        counters
            .archive_cache_reuses
            .fetch_add(1, Ordering::Relaxed);
        return Ok(before);
    }
    // Hash the SAME descriptor whose identity is checked. Missing files,
    // replacement, same-length edits and permission changes cannot reuse it.
    let mut reader = CountedReader {
        file: &mut file,
        bytes: &counters.archive_verified_bytes,
    };
    if digest_hex(Digest32::of_reader(&mut reader, MAX_JOURNAL_BYTES)?) != digest {
        return Err(Error::CorruptJournal("compaction archive digest"));
    }
    let after = file_stamp(&file)?;
    if before != after {
        return Err(Error::CorruptJournal(
            "compaction archive changed during verification",
        ));
    }
    Ok(after)
}

const INVENTORY_LIMIT: u64 = 4096;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Inventory {
    version: u32,
    bytes: u64,
    records: u64,
    directory_stamp: Option<FileStamp>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct InventoryEnvelope {
    data: Inventory,
    digest: String,
}

pub(super) struct ReleasedInventory {
    pub(super) bytes: u64,
    pub(super) records: u64,
}

fn inventory_path(path: &Path) -> PathBuf {
    sibling_temp_path(path, "released.index")
}

fn directory_stamp(path: &Path) -> Result<Option<FileStamp>, Error> {
    let directory = released_archive_dir(path);
    match fs::symlink_metadata(&directory) {
        Ok(meta) if !meta.is_dir() => Err(Error::InvalidIdentity("released directory")),
        Ok(_) => {
            let file = File::open(directory)?;
            file_stamp(&file)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.into()),
    }
}

fn private_bytes(path: &Path, limit: u64) -> Result<Option<Vec<u8>>, Error> {
    match fs::symlink_metadata(path) {
        Ok(meta) if !meta.is_file() => {
            return Err(Error::InvalidIdentity("non-regular archive file"));
        }
        Ok(_) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e.into()),
    }
    let file = File::open(path)?;
    validate_private_file(&file)?;
    if file.metadata()?.len() > limit {
        return Err(Error::CapacityExceeded);
    }
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(Error::CapacityExceeded);
    }
    Ok(Some(bytes))
}

pub(super) fn load_inventory(path: &Path, counters: &Counters) -> Result<ReleasedInventory, Error> {
    let stamp = directory_stamp(path)?;
    if let Some(bytes) = private_bytes(&inventory_path(path), INVENTORY_LIMIT)?
        && let Ok(envelope) = serde_json::from_slice::<InventoryEnvelope>(&bytes)
    {
        let encoded = serde_json::to_vec(&envelope.data)
            .map_err(|_| Error::CorruptJournal("inventory encode"))?;
        if envelope.data.version == 1
            && stamp.is_some()
            && stamp == envelope.data.directory_stamp
            && envelope.digest == digest_hex(Digest32::of_bytes(&encoded))
        {
            return Ok(ReleasedInventory {
                bytes: envelope.data.bytes,
                records: envelope.data.records,
            });
        }
    }
    // First upgrade, invalidated transaction, out-of-band directory change or
    // non-Unix identity: reconstruct ONCE, never trust a guessed byte total.
    let mut inventory = ReleasedInventory {
        bytes: 0,
        records: 0,
    };
    let entries = match fs::read_dir(released_archive_dir(path)) {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(inventory),
        Err(e) => return Err(e.into()),
    };
    counters.inventory_scans.fetch_add(1, Ordering::Relaxed);
    for entry in entries {
        let entry = entry?;
        counters.inventory_entries.fetch_add(1, Ordering::Relaxed);
        if !entry.file_type()?.is_file() {
            return Err(Error::InvalidIdentity(
                "non-regular released inventory entry",
            ));
        }
        let name = entry.file_name();
        let name = name
            .to_str()
            .ok_or(Error::InvalidIdentity("released file name"))?;
        // Interrupted private temporaries never count as published identities.
        if let Some(digest) = name.strip_suffix(".json.tmp") {
            validate_digest(digest, "released temporary name")?;
            continue;
        }
        let digest = name
            .strip_suffix(".json")
            .ok_or(Error::InvalidIdentity("released file name"))?;
        validate_digest(digest, "released file name")?;
        let file = File::open(entry.path())?;
        validate_private_file(&file)?;
        let length = file.metadata()?.len();
        if length > MAX_JOURNAL_LINE_BYTES as u64 {
            return Err(Error::CapacityExceeded);
        }
        inventory.bytes = inventory
            .bytes
            .checked_add(length)
            .ok_or(Error::ArithmeticOverflow)?;
        inventory.records = inventory
            .records
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
    }
    save_inventory(path, &inventory)?;
    Ok(inventory)
}

pub(super) fn invalidate_inventory(path: &Path) -> Result<(), Error> {
    match fs::remove_file(inventory_path(path)) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.into()),
    }
    // The old summary must not survive a crash before any new identity appears.
    sync_parent(path)
}

pub(super) fn save_inventory(path: &Path, inventory: &ReleasedInventory) -> Result<(), Error> {
    let data = Inventory {
        version: 1,
        bytes: inventory.bytes,
        records: inventory.records,
        directory_stamp: directory_stamp(path)?,
    };
    let encoded =
        serde_json::to_vec(&data).map_err(|_| Error::CorruptJournal("inventory encode"))?;
    let envelope = InventoryEnvelope {
        data,
        digest: digest_hex(Digest32::of_bytes(&encoded)),
    };
    let bytes =
        serde_json::to_vec(&envelope).map_err(|_| Error::CorruptJournal("inventory encode"))?;
    if bytes.len() as u64 > INVENTORY_LIMIT {
        return Err(Error::CapacityExceeded);
    }
    let target = inventory_path(path);
    let temporary = sibling_temp_path(&target, "tmp");
    let mut file = fresh_private_temporary(&temporary)?;
    file.write_all(&bytes)?;
    file.flush()?;
    file.sync_all()?;
    fs::rename(&temporary, &target)?;
    sync_parent(path)
}

/// Return newly published bytes, or zero for an exact existing record.
/// Caller holds the owner fence, invalidates inventory BEFORE publication and
/// fsyncs the released directory BEFORE compacting any hot identity away.
pub(super) fn publish_released(path: &Path, bytes: &[u8]) -> Result<u64, Error> {
    let temporary = sibling_temp_path(path, "tmp");
    if let Some(existing) = private_bytes(path, MAX_JOURNAL_LINE_BYTES as u64)? {
        if existing != bytes {
            return Err(Error::Conflict);
        }
        discard_temporary(&temporary)?;
        return Ok(0);
    }
    let mut file = fresh_private_temporary(&temporary)?;
    #[cfg(test)]
    crash_point("temp-created");
    file.write_all(bytes)?;
    #[cfg(test)]
    crash_point("temp-written");
    file.flush()?;
    file.sync_all()?;
    #[cfg(test)]
    crash_point("temp-synced");
    // Unlike rename, create-only publication cannot replace a conflicting
    // identity. Partial data never occupies the authoritative final pathname.
    let published = match fs::hard_link(&temporary, path) {
        Ok(()) => bytes.len() as u64,
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            if private_bytes(path, MAX_JOURNAL_LINE_BYTES as u64)?.as_deref() != Some(bytes) {
                return Err(Error::Conflict);
            }
            0
        }
        Err(e) => return Err(e.into()),
    };
    #[cfg(test)]
    crash_point("linked");
    discard_temporary(&temporary)?;
    Ok(published)
}

fn discard_temporary(path: &Path) -> Result<(), Error> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.is_file() => fs::remove_file(path).map_err(Error::from),
        Ok(_) => Err(Error::InvalidIdentity("non-regular released temporary")),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}

#[cfg(test)]
pub(super) fn crash_point(phase: &str) {
    if std::env::var("HEPTA_TEST_RELEASED_CRASH_PHASE").as_deref() == Ok(phase) {
        // Child-test only; exit deliberately skips Rust destructors. There is
        // no environment-controlled crash path in production artifacts.
        std::process::exit(86);
    }
}

#[cfg(all(test, unix))]
mod fence_tests {
    use super::*;

    #[test]
    fn dropping_fence_releases_lock_even_with_a_duplicated_descriptor() {
        let path = std::env::temp_dir().join(format!(
            "hepta-fence-clone-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
        ));
        fs::create_dir(&path).unwrap();
        let journal = path.join("inference.journal");
        let counters = Arc::new(Counters::default());
        let fence = WriterFence::acquire(&journal, counters.clone()).unwrap();
        let inherited = fence._file.try_clone().unwrap();
        assert!(matches!(
            WriterFence::acquire(&journal, counters.clone()),
            Err(Error::WriterUnavailable)
        ));
        drop(fence);
        // A separate open must succeed while the duplicate remains alive.
        // This deterministically models the fork/exec descriptor lifetime,
        // without relying on timing between otherwise unrelated tests.
        let peer = WriterFence::acquire(&journal, counters.clone()).unwrap();
        assert_eq!(counters.snapshot().lock_release_errors, 0);
        drop(peer);
        drop(inherited);
        fs::remove_dir_all(path).unwrap();
    }
}
