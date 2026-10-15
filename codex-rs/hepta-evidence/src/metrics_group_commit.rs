//! Bounded append-only metrics group commit with one fsync per group.
//!
//! This journal is telemetry, not a signed evidence ledger. Its hash chain
//! detects torn/corrupt local lines; it cannot certify an operation or mint
//! authority. The caller must not retry an external effect after a telemetry
//! failure without independently reconciling that effect.

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_types::Digest32;

const MAX_GROUP_ROWS: usize = 256;
const MAX_LINE_BYTES: usize = 65_536;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const DOMAIN: &[u8] = b"hepta.metrics.group.v1";
// One fixed-size append-only local witness per committed WAL group.
// The suffix is a bound frontier, NOT an external or signed rollback witness.
#[cfg(unix)]
const OWNER_FRONTIER_ROW_BYTES: usize = 102;
#[cfg(unix)]
const MAX_OWNER_MARKER_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MetricPhaseV1 {
    Admission = 1,
    Microbatch = 2,
    Cas = 3,
    Signature = 4,
    Cns = 5,
    NeuronFeature = 6,
    Wal = 7,
    NduRead = 8,
    FinalUse = 9,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricSampleV1 {
    pub scope_digest: Digest32,
    pub operation_digest: Digest32,
    pub phase: MetricPhaseV1,
    pub latency_micros: u64,
    pub succeeded: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricsCommitReceiptV1 {
    pub sequence: u64,
    pub head_digest: Digest32,
    pub rows: usize,
    pub sync_latency_micros: u64,
}

/// Original WAL plus local marker state witnessed by this process.
/// This readback is NOT an independent signature, release permit or proof
/// against coordinated rollback of both storage files.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MetricsLocalFrontierV1 {
    pub sequence: u64,
    pub head_digest: Digest32,
    pub committed_rows: u64,
    pub journal_bytes: u64,
    pub wal_device: u64,
    pub wal_inode: u64,
    pub marker_device: u64,
    pub marker_inode: u64,
}

#[derive(Debug)]
pub enum MetricsJournalErrorV1 {
    Io(std::io::Error),
    Capacity,
    EmptyDigest,
    Corrupt,
    WriterUnavailable,
    Poisoned,
    /// A journal must be a regular owner-only file in a non-writable-by-peers directory.
    UnsafePath,
}
impl From<std::io::Error> for MetricsJournalErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}
impl std::fmt::Display for MetricsJournalErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for MetricsJournalErrorV1 {}

/// A read-only view of the original locked WAL descriptor that preserves
/// its shared file offset. File::try_clone + seek changes the underlying
/// open-file-description offset even if all normal writes are O_APPEND.
#[cfg(unix)]
struct OriginalWalPositionalReaderV1<'a> {
    file: &'a File,
    cursor: u64,
    limit: u64,
}

#[cfg(unix)]
impl Read for OriginalWalPositionalReaderV1<'_> {
    fn read(&mut self, destination: &mut [u8]) -> std::io::Result<usize> {
        use std::os::unix::fs::FileExt as _;

        if self.cursor >= self.limit || destination.is_empty() {
            return Ok(0);
        }
        let remaining = self.limit - self.cursor;
        let take = remaining.min(destination.len() as u64) as usize;
        let read = self.file.read_at(&mut destination[..take], self.cursor)?;
        self.cursor += read as u64;
        Ok(read)
    }
}

/// The single writer keeps a bounded group in memory. A torn append poisons
/// the instance until inspection/reopen, never silently skipping a record.
pub struct MetricsGroupCommitV1 {
    file: File,
    journal_path: PathBuf,
    // A distinct original inode survives process restarts and refuses
    // missing/recreated WAL files instead of blessing a fresh history.
    #[cfg(unix)]
    owner_marker_path: PathBuf,
    #[cfg(unix)]
    owner_marker: File,
    #[cfg(unix)]
    owner_marker_bytes: Vec<u8>,
    #[cfg(unix)]
    original_parent_path: PathBuf,
    #[cfg(unix)]
    original_parent: File,
    staged: Vec<MetricSampleV1>,
    sequence: u64,
    head: Digest32,
    committed_rows: u64,
    bytes: u64,
    // Exact last committed row, not a signed evidence claim. The bounded
    // readback prevents live same-inode tail rewrites from earning an ACK.
    last_row_len: usize,
    last_row_digest: Digest32,
    poisoned: bool,
}

impl Drop for MetricsGroupCommitV1 {
    fn drop(&mut self) {
        // An owned writer lock must be released explicitly before the file
        // descriptor is closed. Some runner/file-system combinations can
        // otherwise leave the next owner seeing WriterUnavailable even after
        // the previous writer has left scope. Never flush uncommitted metrics
        // on Drop: after an abrupt exit only previously fsynced groups count.
        let _ = self.file.unlock();
        #[cfg(unix)]
        let _ = self.owner_marker.unlock();
    }
}

impl MetricsGroupCommitV1 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, MetricsJournalErrorV1> {
        let path = path.as_ref();
        // Never provision an untrusted telemetry directory as a side
        // effect of opening the writer. The deployment's own storage
        // administrator must create and protect the parent beforehand.
        check_journal_path(path)?;
        #[cfg(unix)]
        let (original_parent_path, original_parent) = {
            let parent = path
                .parent()
                .filter(|p| !p.as_os_str().is_empty())
                .unwrap_or_else(|| Path::new("."));
            let opened = File::open(parent)?;
            verify_original_parent_path(parent, &opened)?;
            (parent.to_path_buf(), opened)
        };
        // A missing WAL paired with a retained durable marker is a lost
        // history. Equally, a present WAL without its marker cannot be
        // silently adopted. First bootstrap creates and syncs the marker
        // inode before the WAL; half-finished bootstrap fails closed.
        #[cfg(unix)]
        let (owner_marker_path, mut owner_marker, marker_preexisting) = {
            use std::os::unix::fs::OpenOptionsExt as _;
            let mut marker_name = path.as_os_str().to_os_string();
            marker_name.push(".owner-lock");
            let marker_path = PathBuf::from(marker_name);
            let exists = |p: &Path| -> Result<bool, MetricsJournalErrorV1> {
                match fs::symlink_metadata(p) {
                    Ok(_) => Ok(true),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
                    Err(error) => Err(error.into()),
                }
            };
            let wal_exists = exists(path)?;
            let marker_exists = exists(&marker_path)?;
            if wal_exists != marker_exists {
                return Err(MetricsJournalErrorV1::UnsafePath);
            }
            let mut options = OpenOptions::new();
            // O_APPEND is essential on restart: the reopened marker file
            // starts at offset zero and must never overwrite its identity.
            options.read(true).write(true).append(true).mode(0o600);
            if !marker_exists {
                options.create_new(true);
            }
            let marker = options.open(&marker_path)?;
            check_open_file(&marker_path, &marker)?;
            marker
                .try_lock()
                .map_err(|_| MetricsJournalErrorV1::WriterUnavailable)?;
            if !marker_exists {
                original_parent.sync_all()?;
            }
            (marker_path, marker, marker_exists)
        };
        let mut options = OpenOptions::new();
        options.append(true).read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt as _;
            if !marker_preexisting {
                options.create_new(true);
            }
            options.mode(0o600);
        }
        #[cfg(not(unix))]
        options.create(true);
        let file = options.open(path)?;
        check_open_file(path, &file)?;
        file.try_lock()
            .map_err(|_| MetricsJournalErrorV1::WriterUnavailable)?;
        #[cfg(unix)]
        let owner_marker_bytes = {
            use std::os::unix::fs::MetadataExt as _;
            let metadata = file.metadata()?;
            let expected = format!("HEMW1|{}|{}\n", metadata.dev(), metadata.ino()).into_bytes();
            if marker_preexisting {
                verify_original_owner_marker_header(&owner_marker_path, &owner_marker, &expected)?;
            } else {
                owner_marker.write_all(&expected)?;
                owner_marker.sync_all()?;
                original_parent.sync_all()?;
            }
            expected
        };
        let mut reader = BufReader::new(file.try_clone()?);
        let mut line = Vec::new();
        let mut total = 0_u64;
        let mut sequence = 0_u64;
        let mut committed_rows = 0_u64;
        let mut head = Digest32::ZERO;
        let mut last_row_len = 0_usize;
        let mut last_row_digest = Digest32::ZERO;
        loop {
            line.clear();
            let remaining = MAX_JOURNAL_BYTES.saturating_sub(total).saturating_add(1);
            let read = (&mut reader)
                .take(remaining.min(MAX_LINE_BYTES as u64 + 1))
                .read_until(b'\n', &mut line)?;
            if read == 0 {
                break;
            }
            total = total
                .checked_add(read as u64)
                .ok_or(MetricsJournalErrorV1::Capacity)?;
            if read > MAX_LINE_BYTES || total > MAX_JOURNAL_BYTES || line.pop() != Some(b'\n') {
                return Err(MetricsJournalErrorV1::Corrupt);
            }
            let contents =
                std::str::from_utf8(&line).map_err(|_| MetricsJournalErrorV1::Corrupt)?;
            let (next_sequence, next_head, rows) = parse_group(contents, sequence, head)?;
            #[cfg(unix)]
            verify_original_frontier_row(
                &owner_marker,
                owner_marker_bytes.len(),
                next_sequence,
                total,
                next_head,
            )?;
            last_row_len = read;
            last_row_digest = Digest32::of_bytes(&line);
            sequence = next_sequence;
            committed_rows = committed_rows
                .checked_add(rows as u64)
                .ok_or(MetricsJournalErrorV1::Capacity)?;
            head = next_head;
        }
        let owner = Self {
            file,
            journal_path: path.to_path_buf(),
            #[cfg(unix)]
            owner_marker_path,
            #[cfg(unix)]
            owner_marker,
            #[cfg(unix)]
            owner_marker_bytes,
            #[cfg(unix)]
            original_parent_path,
            #[cfg(unix)]
            original_parent,
            staged: Vec::new(),
            sequence,
            head,
            committed_rows,
            bytes: total,
            last_row_len,
            last_row_digest,
            poisoned: false,
        };
        // Recheck after the replay: path replacement or same-inode rewrite
        // during an expensive cold scan cannot be accepted as a fresh writer.
        owner.verify_original_frontier()?;
        Ok(owner)
    }

    /// Verify the OPEN original inode still names the journal, its cached
    /// durable length is exact, and the last fsynced row has not been changed.
    /// Bounded to MAX_LINE_BYTES: older-prefix rewrite and coordinated full
    /// rollback still require independent external custody/Observer.
    fn verify_original_frontier(&self) -> Result<(), MetricsJournalErrorV1> {
        // Protect the original parent DIRECTORY inode too. A directory
        // swap that moves the exact same WAL inode to a new private parent
        // defeats checks of only the WAL file name, size and inode.
        check_journal_path(&self.journal_path)?;
        #[cfg(unix)]
        {
            verify_original_parent_path(&self.original_parent_path, &self.original_parent)?;
            verify_original_owner_marker_frontier(
                &self.owner_marker_path,
                &self.owner_marker,
                &self.owner_marker_bytes,
                self.sequence,
                self.bytes,
                self.head,
            )?;
        }
        check_open_file(&self.journal_path, &self.file)?;
        if self.file.metadata()?.len() != self.bytes {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
        if self.sequence == 0 {
            if self.bytes != 0 || self.last_row_len != 0 || !self.last_row_digest.is_zero() {
                return Err(MetricsJournalErrorV1::Corrupt);
            }
        } else {
            if self.last_row_len == 0
                || self.last_row_len > MAX_LINE_BYTES
                || self.bytes < self.last_row_len as u64
                || self.last_row_digest.is_zero()
            {
                return Err(MetricsJournalErrorV1::Corrupt);
            }
            let mut tail = vec![0_u8; self.last_row_len];
            #[cfg(unix)]
            {
                use std::os::unix::fs::FileExt as _;
                self.file
                    .read_exact_at(&mut tail, self.bytes - self.last_row_len as u64)?;
            }
            #[cfg(not(unix))]
            {
                use std::io::Seek as _;
                use std::io::SeekFrom;
                let mut reader = self.file.try_clone()?;
                reader.seek(SeekFrom::Start(self.bytes - self.last_row_len as u64))?;
                reader.read_exact(&mut tail)?;
            }
            if tail.last() != Some(&b'\n')
                || Digest32::of_bytes(&tail[..tail.len() - 1]) != self.last_row_digest
            {
                return Err(MetricsJournalErrorV1::Corrupt);
            }
        }
        // Reread both protected parent and exact opened inode after the
        // tail check; neither directory drift nor WAL replacement may ACK.
        check_journal_path(&self.journal_path)?;
        #[cfg(unix)]
        {
            verify_original_parent_path(&self.original_parent_path, &self.original_parent)?;
            verify_original_owner_marker_frontier(
                &self.owner_marker_path,
                &self.owner_marker,
                &self.owner_marker_bytes,
                self.sequence,
                self.bytes,
                self.head,
            )?;
        }
        check_open_file(&self.journal_path, &self.file)?;
        if self.file.metadata()?.len() != self.bytes {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
        Ok(())
    }

    /// Re-read the original full history only on explicit Observer request,
    /// never during a Neuron inference tick or a normal metrics group fsync.
    /// A forged earlier marker row with a correct final tail must be rejected.
    #[cfg(unix)]
    fn verify_complete_marker_history(&self) -> Result<(), MetricsJournalErrorV1> {
        // Positional reads remain on the ORIGINAL locked WAL inode. They
        // preserve its shared OS file offset and stop at the frozen committed
        // byte frontier. The final live checks still deny drift or replacement.
        let mut reader = BufReader::new(OriginalWalPositionalReaderV1 {
            file: &self.file,
            cursor: 0,
            limit: self.bytes,
        });
        let mut row = Vec::new();
        let mut bytes = 0_u64;
        let mut sequence = 0_u64;
        let mut head = Digest32::ZERO;
        let mut committed_rows = 0_u64;
        loop {
            row.clear();
            let read = (&mut reader)
                .take((MAX_LINE_BYTES + 1) as u64)
                .read_until(b'\n', &mut row)?;
            if read == 0 {
                break;
            }
            bytes = bytes
                .checked_add(read as u64)
                .ok_or(MetricsJournalErrorV1::Capacity)?;
            if read > MAX_LINE_BYTES || bytes > MAX_JOURNAL_BYTES || row.pop() != Some(b'\n') {
                return Err(MetricsJournalErrorV1::Corrupt);
            }
            let text = std::str::from_utf8(&row).map_err(|_| MetricsJournalErrorV1::Corrupt)?;
            let (next_sequence, next_head, rows) = parse_group(text, sequence, head)?;
            verify_original_frontier_row(
                &self.owner_marker,
                self.owner_marker_bytes.len(),
                next_sequence,
                bytes,
                next_head,
            )?;
            sequence = next_sequence;
            head = next_head;
            committed_rows = committed_rows
                .checked_add(rows as u64)
                .ok_or(MetricsJournalErrorV1::Capacity)?;
        }
        if sequence != self.sequence
            || head != self.head
            || committed_rows != self.committed_rows
            || bytes != self.bytes
        {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
        Ok(())
    }

    /// Local readback for an independent Observer to capture and then
    /// authenticate under its OWN custody. No signer or grant is minted.
    pub fn read_local_frontier(&mut self) -> Result<MetricsLocalFrontierV1, MetricsJournalErrorV1> {
        if self.poisoned {
            return Err(MetricsJournalErrorV1::Poisoned);
        }
        let result = self.read_local_frontier_checked();
        if result.is_err() {
            // A failed original history observation is a sticky owner fence,
            // not a diagnostic that may be ignored before the next fsync ACK.
            self.poisoned = true;
        }
        result
    }

    fn read_local_frontier_checked(&self) -> Result<MetricsLocalFrontierV1, MetricsJournalErrorV1> {
        self.verify_original_frontier()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt as _;
            self.verify_complete_marker_history()?;
            self.verify_original_frontier()?;
            let wal = self.file.metadata()?;
            let marker = self.owner_marker.metadata()?;
            Ok(MetricsLocalFrontierV1 {
                sequence: self.sequence,
                head_digest: self.head,
                committed_rows: self.committed_rows,
                journal_bytes: self.bytes,
                wal_device: wal.dev(),
                wal_inode: wal.ino(),
                marker_device: marker.dev(),
                marker_inode: marker.ino(),
            })
        }
        #[cfg(not(unix))]
        {
            Err(MetricsJournalErrorV1::UnsafePath)
        }
    }

    // The original WAL group is already fsynced when this is called.
    // Persist its independent high-water row BEFORE granting a success ACK.
    // A crash or write failure between these fsyncs leaves an unresolved
    // mismatch; a restarted owner must refuse, never silently repair it.
    #[cfg(unix)]
    fn append_owner_frontier(&mut self) -> Result<(), MetricsJournalErrorV1> {
        let row = owner_frontier_row(self.sequence, self.bytes, self.head);
        if row.len() != OWNER_FRONTIER_ROW_BYTES {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
        let marker_size = self
            .owner_marker_bytes
            .len()
            .try_into()
            .ok()
            .and_then(|base: u64| {
                self.sequence
                    .checked_mul(OWNER_FRONTIER_ROW_BYTES as u64)
                    .and_then(|added| base.checked_add(added))
            })
            .ok_or(MetricsJournalErrorV1::Capacity)?;
        if marker_size > MAX_OWNER_MARKER_BYTES {
            return Err(MetricsJournalErrorV1::Capacity);
        }
        self.owner_marker.write_all(&row)?;
        self.owner_marker.sync_all()?;
        Ok(())
    }

    pub fn stage(&mut self, sample: MetricSampleV1) -> Result<(), MetricsJournalErrorV1> {
        if self.poisoned {
            return Err(MetricsJournalErrorV1::Poisoned);
        }
        if sample.scope_digest.is_zero() || sample.operation_digest.is_zero() {
            return Err(MetricsJournalErrorV1::EmptyDigest);
        }
        if self.staged.len() >= MAX_GROUP_ROWS {
            return Err(MetricsJournalErrorV1::Capacity);
        }
        self.staged.push(sample);
        Ok(())
    }

    pub fn pending(&self) -> usize {
        self.staged.len()
    }

    /// Committed rows recovered from the complete hash-checked journal, plus
    /// groups durably synchronized by this owner. Unflushed staged rows are
    /// intentionally excluded: an abrupt process exit can lose those rows.
    pub fn committed_rows(&self) -> u64 {
        self.committed_rows
    }

    pub fn committed_groups(&self) -> u64 {
        self.sequence
    }

    pub fn committed_head(&self) -> Digest32 {
        self.head
    }

    pub fn flush(&mut self) -> Result<Option<MetricsCommitReceiptV1>, MetricsJournalErrorV1> {
        if self.poisoned {
            return Err(MetricsJournalErrorV1::Poisoned);
        }
        // An empty flush can still be an ACK for a previously committed
        // physical effect. It MUST validate the original journal as well.
        if let Err(error) = self.verify_original_frontier() {
            self.poisoned = true;
            return Err(error);
        }
        if self.staged.is_empty() {
            return Ok(None);
        }
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or(MetricsJournalErrorV1::Capacity)?;
        let payload = self
            .staged
            .iter()
            .map(encode_sample)
            .collect::<Vec<_>>()
            .join(";");
        let next_head = digest_group(sequence, self.head, &payload);
        let encoded = format!(
            "M1|{}|{}|{}|{}|{}\n",
            sequence,
            self.head,
            next_head,
            self.staged.len(),
            payload
        );
        let next_bytes = self
            .bytes
            .checked_add(encoded.len() as u64)
            .ok_or(MetricsJournalErrorV1::Capacity)?;
        let next_rows = self
            .committed_rows
            .checked_add(self.staged.len() as u64)
            .ok_or(MetricsJournalErrorV1::Capacity)?;
        if encoded.len() > MAX_LINE_BYTES || next_bytes > MAX_JOURNAL_BYTES {
            return Err(MetricsJournalErrorV1::Capacity);
        }
        let started = Instant::now();
        if let Err(error) = self
            .file
            .write_all(encoded.as_bytes())
            .and_then(|()| self.file.sync_all())
        {
            self.poisoned = true;
            return Err(MetricsJournalErrorV1::Io(error));
        }
        self.bytes = next_bytes;
        self.sequence = sequence;
        self.committed_rows = next_rows;
        self.head = next_head;
        self.last_row_len = encoded.len();
        self.last_row_digest = Digest32::of_bytes(&encoded.as_bytes()[..encoded.len() - 1]);
        #[cfg(unix)]
        if let Err(error) = self.append_owner_frontier() {
            // The WAL may already be durable, but its independent high-water
            // is not confirmed. Preserve the uncertain original effect;
            // NEVER claim a positive metrics ACK or attempt a second write.
            self.poisoned = true;
            return Err(error);
        }
        if let Err(error) = self.verify_original_frontier() {
            // The fsync may already have happened. Poison and refuse the ACK
            // without trying to append a duplicate group or Split effect.
            self.poisoned = true;
            return Err(error);
        }
        let receipt = MetricsCommitReceiptV1 {
            sequence,
            head_digest: next_head,
            rows: self.staged.len(),
            sync_latency_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
        };
        self.staged.clear();
        Ok(Some(receipt))
    }
}

/// Never open a metrics journal through a symbolic link or a directory
/// other users may modify. The owner must provision the directory before
/// starting its effects; telemetry path rejection is a readiness failure.
fn check_journal_path(path: &Path) -> Result<(), MetricsJournalErrorV1> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        let directory = fs::symlink_metadata(parent)?;
        if !directory.is_dir()
            || directory.file_type().is_symlink()
            || directory.permissions().mode() & 0o022 != 0
        {
            return Err(MetricsJournalErrorV1::UnsafePath);
        }
    }
    match fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.file_type().is_file() {
                return Err(MetricsJournalErrorV1::UnsafePath);
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                use std::os::unix::fs::PermissionsExt;
                if metadata.permissions().mode() & 0o077 != 0 || metadata.nlink() != 1 {
                    return Err(MetricsJournalErrorV1::UnsafePath);
                }
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(MetricsJournalErrorV1::Io(error)),
    }
    Ok(())
}

/// Compare one separately persisted group frontier against the original WAL.
/// Used during cold replay and optional full Observer readback only, not
/// along the ordinary group-flush critical path.
#[cfg(unix)]
fn verify_original_frontier_row(
    opened_marker: &File,
    identity_bytes: usize,
    sequence: u64,
    bytes: u64,
    head: Digest32,
) -> Result<(), MetricsJournalErrorV1> {
    use std::os::unix::fs::FileExt as _;

    let offset = sequence
        .checked_sub(1)
        .and_then(|index| index.checked_mul(OWNER_FRONTIER_ROW_BYTES as u64))
        .and_then(|index| index.checked_add(identity_bytes as u64))
        .ok_or(MetricsJournalErrorV1::Capacity)?;
    let expected = owner_frontier_row(sequence, bytes, head);
    if expected.len() != OWNER_FRONTIER_ROW_BYTES {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let mut observed = [0_u8; OWNER_FRONTIER_ROW_BYTES];
    opened_marker
        .read_exact_at(&mut observed, offset)
        .map_err(|_| MetricsJournalErrorV1::Corrupt)?;
    if observed.as_slice() != expected.as_slice() {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    Ok(())
}

/// The local witness format is fixed-width so every original WAL fsync
/// advances a bounded marker by exactly one immutable frontier row.
#[cfg(unix)]
fn owner_frontier_row(sequence: u64, bytes: u64, head: Digest32) -> Vec<u8> {
    format!("F1|{sequence:016x}|{bytes:016x}|{head}\n").into_bytes()
}

/// Before WAL replay we may authenticate the marker identity prefix, but
/// only the complete replay can identify the expected committed high-water.
#[cfg(unix)]
fn verify_original_owner_marker_header(
    marker_path: &Path,
    opened_marker: &File,
    expected: &[u8],
) -> Result<(), MetricsJournalErrorV1> {
    use std::os::unix::fs::FileExt as _;

    check_open_file(marker_path, opened_marker)?;
    if opened_marker.metadata()?.len() < expected.len() as u64 {
        return Err(MetricsJournalErrorV1::UnsafePath);
    }
    let mut observed = vec![0_u8; expected.len()];
    opened_marker.read_exact_at(&mut observed, 0)?;
    if observed.as_slice() != expected {
        return Err(MetricsJournalErrorV1::UnsafePath);
    }
    check_open_file(marker_path, opened_marker)?;
    Ok(())
}

/// The marker's latest separately fsynced sequence/head/byte frontier
/// must agree with the complete original WAL replay or live owner cache.
/// A locally coordinated rollback of BOTH files still needs external custody.
#[cfg(unix)]
fn verify_original_owner_marker_frontier(
    marker_path: &Path,
    opened_marker: &File,
    identity: &[u8],
    sequence: u64,
    bytes: u64,
    head: Digest32,
) -> Result<(), MetricsJournalErrorV1> {
    use std::os::unix::fs::FileExt as _;

    verify_original_owner_marker_header(marker_path, opened_marker, identity)?;
    if (sequence == 0 && (bytes != 0 || !head.is_zero()))
        || (sequence > 0 && (bytes == 0 || head.is_zero()))
    {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let required = sequence
        .checked_mul(OWNER_FRONTIER_ROW_BYTES as u64)
        .and_then(|total| total.checked_add(identity.len() as u64))
        .ok_or(MetricsJournalErrorV1::Capacity)?;
    if required > MAX_OWNER_MARKER_BYTES {
        return Err(MetricsJournalErrorV1::Capacity);
    }
    if opened_marker.metadata()?.len() != required {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    if sequence > 0 {
        let expected = owner_frontier_row(sequence, bytes, head);
        if expected.len() != OWNER_FRONTIER_ROW_BYTES {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
        let mut last = vec![0_u8; OWNER_FRONTIER_ROW_BYTES];
        opened_marker.read_exact_at(&mut last, required - OWNER_FRONTIER_ROW_BYTES as u64)?;
        if last != expected {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
    }
    check_open_file(marker_path, opened_marker)?;
    if opened_marker.metadata()?.len() != required {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    Ok(())
}

/// A named parent that changes inode is not the original Evidence owner
/// directory, even when an attacker moves the very same WAL file into it.
/// Keep the original directory handle open to prevent inode reuse.
#[cfg(unix)]
fn verify_original_parent_path(
    parent_path: &Path,
    opened_parent: &File,
) -> Result<(), MetricsJournalErrorV1> {
    use std::os::unix::fs::MetadataExt;

    let named = fs::symlink_metadata(parent_path)?;
    let opened = opened_parent.metadata()?;
    if !named.file_type().is_dir()
        || named.file_type().is_symlink()
        || !opened.is_dir()
        || named.dev() != opened.dev()
        || named.ino() != opened.ino()
        || (named.mode() | opened.mode()) & 0o022 != 0
    {
        return Err(MetricsJournalErrorV1::UnsafePath);
    }
    Ok(())
}

/// A second inspection binds the opened file to the protected path. On Unix
/// the inode comparison catches replacement between preflight and open.
fn check_open_file(path: &Path, file: &File) -> Result<(), MetricsJournalErrorV1> {
    let actual = file.metadata()?;
    let on_path = fs::symlink_metadata(path)?;
    if !actual.is_file() || !on_path.file_type().is_file() {
        return Err(MetricsJournalErrorV1::UnsafePath);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if actual.permissions().mode() & 0o077 != 0
            || on_path.permissions().mode() & 0o077 != 0
            || actual.dev() != on_path.dev()
            || actual.ino() != on_path.ino()
            || actual.nlink() != 1
            || on_path.nlink() != 1
        {
            return Err(MetricsJournalErrorV1::UnsafePath);
        }
    }
    Ok(())
}

/// Timed operation and its result stay together. Telemetry is separate so an
/// I/O failure cannot turn a successful CAS/signature/CNS effect into a retry.
pub fn measure_phase_v1<T, E>(
    scope_digest: Digest32,
    operation_digest: Digest32,
    phase: MetricPhaseV1,
    operation: impl FnOnce() -> Result<T, E>,
) -> (Result<T, E>, MetricSampleV1) {
    let start = Instant::now();
    let result = operation();
    let sample = MetricSampleV1 {
        scope_digest,
        operation_digest,
        phase,
        latency_micros: u64::try_from(start.elapsed().as_micros()).unwrap_or(u64::MAX),
        succeeded: result.is_ok(),
    };
    (result, sample)
}

fn encode_sample(sample: &MetricSampleV1) -> String {
    format!(
        "{}:{}:{}:{}:{}",
        sample.scope_digest,
        sample.operation_digest,
        sample.phase as u8,
        sample.latency_micros,
        u8::from(sample.succeeded)
    )
}

fn digest_group(sequence: u64, previous: Digest32, payload: &str) -> Digest32 {
    let mut bytes = DOMAIN.to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(previous.as_array());
    bytes.extend_from_slice(&(payload.len() as u64).to_be_bytes());
    bytes.extend_from_slice(payload.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn parse_group(
    line: &str,
    previous_sequence: u64,
    previous_head: Digest32,
) -> Result<(u64, Digest32, usize), MetricsJournalErrorV1> {
    let mut fields = line.split('|');
    if fields.next() != Some("M1") {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let sequence = fields
        .next()
        .and_then(|s| s.parse::<u64>().ok())
        .ok_or(MetricsJournalErrorV1::Corrupt)?;
    if sequence
        != previous_sequence
            .checked_add(1)
            .ok_or(MetricsJournalErrorV1::Corrupt)?
    {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let predecessor_hex = previous_head.to_string();
    if fields.next() != Some(predecessor_hex.as_str()) {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let head = fields.next().ok_or(MetricsJournalErrorV1::Corrupt)?;
    let count = fields
        .next()
        .and_then(|s| s.parse::<usize>().ok())
        .ok_or(MetricsJournalErrorV1::Corrupt)?;
    let payload = fields.next().ok_or(MetricsJournalErrorV1::Corrupt)?;
    if fields.next().is_some() || count == 0 || count > MAX_GROUP_ROWS {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let rows: Vec<_> = payload.split(';').collect();
    if rows.len() != count {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    for row in rows {
        let columns: Vec<_> = row.split(':').collect();
        if columns.len() != 5
            || !digest_hex(columns[0])
            || !digest_hex(columns[1])
            || !matches!(
                columns[2],
                "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9"
            )
            || columns[3].parse::<u64>().is_err()
            || !matches!(columns[4], "0" | "1")
        {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
    }
    let expected = digest_group(sequence, previous_head, payload);
    if head != expected.to_string() {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    Ok((sequence, expected, count))
}

fn digest_hex(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
#[path = "metrics_group_commit_tests.rs"]
mod tests;
