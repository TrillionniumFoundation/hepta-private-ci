//! Durable single-scope Control ledger. NDU route cutover and checkpoint
//! publication share one exclusive owner lock, journal and fsync boundary.
//! A separate CNS route writer bypassing this owner is not atomic.

use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::fs::{self};
#[cfg(unix)]
use std::io::BufRead;
#[cfg(unix)]
use std::io::BufReader;
#[cfg(unix)]
use std::io::Read;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::FileExt;
#[cfg(unix)]
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
#[cfg(unix)]
use std::str::FromStr;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use codex_hepta_types::NduSnapshotRefV1;

const MAX_BYTES: u64 = 64 * 1024 * 1024;
const MAX_ROW: usize = 2048;
const DOMAIN: &[u8] = b"hepta.control.ndu-publication.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduPublicationErrorV1 {
    Invalid,
    Stale,
    /// A durable route Prepare exists but physical runtime effect/Commit is
    /// not conclusively resolved. Never replay or bootstrap a fresh owner.
    Indeterminate,
    UnsafePath,
    Unsupported,
    WriterUnavailable,
    Corrupt,
    Capacity,
    Poisoned,
    Io(std::io::ErrorKind),
}
impl From<std::io::Error> for NduPublicationErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.kind())
    }
}
impl std::fmt::Display for NduPublicationErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for NduPublicationErrorV1 {}

/// Bounded, original-inode, read-only Control WAL observation for an independent
/// Observer. All fields are LOCAL and UNSIGNED; even an exact frontier is not a
/// Final-use token, original CNS runtime receipt, rollback witness, or license
/// to perform a physical Cell Split.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduPublicationLocalFrontierV1 {
    pub snapshot: NduSnapshotRefV1,
    pub checkpoint: Digest32,
    pub sequence: u64,
    pub head: Digest32,
    pub wal_bytes: u64,
    pub wal_device: u64,
    pub wal_inode: u64,
    pub marker_device: u64,
    pub marker_inode: u64,
    pub original_cns_receipt_binding: Option<Digest32>,
}

/// A persistent writer-lock inode is independent of the append-only journal
/// inode. Losing either path must never silently bootstrap a new Control
/// frontier, even when the old writer held a lock on an unlinked WAL inode.
/// This is local durability only; external custody is still mandatory.
#[cfg(unix)]
fn control_owner_file_identity(
    file: &File,
    path: &Path,
) -> Result<(u64, u64), NduPublicationErrorV1> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let opened = file
        .metadata()
        .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
    let named = fs::symlink_metadata(path).map_err(|_| NduPublicationErrorV1::Indeterminate)?;
    if !opened.is_file()
        || !named.file_type().is_file()
        || opened.dev() != named.dev()
        || opened.ino() != named.ino()
        || opened.nlink() != 1
        || named.nlink() != 1
        || opened.permissions().mode() & 0o077 != 0
        || named.permissions().mode() & 0o077 != 0
    {
        return Err(NduPublicationErrorV1::Indeterminate);
    }
    Ok((opened.dev(), opened.ino()))
}

/// Identifies bytes returned by the original CNS owner after its
/// independent signed mutation/readback. This hash is not an authorization
/// token: the caller must verify the original owner signature and live route.
fn original_cns_receipt_binding(
    original_receipt_bytes: &[u8],
) -> Result<Digest32, NduPublicationErrorV1> {
    if !(64..=32 * 1024).contains(&original_receipt_bytes.len()) {
        return Err(NduPublicationErrorV1::Invalid);
    }
    let mut bound = b"hepta.control.ndu-publication.cns-original-receipt.v1\0".to_vec();
    bound.extend_from_slice(&(original_receipt_bytes.len() as u64).to_be_bytes());
    bound.extend_from_slice(original_receipt_bytes);
    Ok(Digest32::of_bytes(&bound))
}

#[derive(Clone, Copy)]
struct Event {
    sequence: u64,
    previous: Digest32,
    head: Digest32,
    kind: char,
    snapshot: Digest32,
    before: Digest32,
    after: Digest32,
    read: Digest32,
    tick: Digest32,
}
fn event_hash(e: &Event) -> Digest32 {
    let mut b = DOMAIN.to_vec();
    b.extend_from_slice(&e.sequence.to_be_bytes());
    b.extend_from_slice(e.previous.as_array());
    b.extend_from_slice(&(e.kind as u32).to_be_bytes());
    for d in [e.snapshot, e.before, e.after, e.read, e.tick] {
        b.extend_from_slice(d.as_array());
    }
    Digest32::of_bytes(&b)
}
#[cfg(unix)]
fn decode(line: &str) -> Result<Event, NduPublicationErrorV1> {
    let p = line.split('|').collect::<Vec<_>>();
    if p.len() != 10 || p[0] != "N1" {
        return Err(NduPublicationErrorV1::Corrupt);
    }
    let digest = |i| Digest32::from_str(p[i]).map_err(|_| NduPublicationErrorV1::Corrupt);
    let kind = match p[4] {
        "G" => 'G',
        "B" => 'B',
        "C" => 'C',
        "P" => 'P',
        _ => return Err(NduPublicationErrorV1::Corrupt),
    };
    Ok(Event {
        sequence: p[1].parse().map_err(|_| NduPublicationErrorV1::Corrupt)?,
        previous: digest(2)?,
        head: digest(3)?,
        kind,
        snapshot: digest(5)?,
        before: digest(6)?,
        after: digest(7)?,
        read: digest(8)?,
        tick: digest(9)?,
    })
}
/// Durable but unresolved CNS handoff. A process crash after Begin is an
/// ambiguous external effect, regardless of which route is currently visible.
#[cfg(unix)]
#[derive(Clone, Copy)]
struct PendingCutover {
    successor: Digest32,
    previous_checkpoint: Digest32,
    migrated_checkpoint: Digest32,
}

#[cfg(unix)]
fn validate_replay(
    e: &Event,
    current: Option<Digest32>,
    checkpoint: Digest32,
    pending: Option<PendingCutover>,
) -> Result<(), NduPublicationErrorV1> {
    if e.snapshot.is_zero() {
        return Err(NduPublicationErrorV1::Corrupt);
    }
    let valid = match e.kind {
        'G' => {
            pending.is_none()
                && current.is_none()
                && e.before.is_zero()
                && e.read.is_zero()
                && e.tick.is_zero()
        }
        'B' => {
            pending.is_none()
                && current.is_some_and(|prev| prev != e.snapshot)
                && e.before == checkpoint
                && !e.after.is_zero()
                && e.read.is_zero()
                && e.tick.is_zero()
        }
        'C' => {
            current.is_some_and(|prev| prev != e.snapshot)
                && e.before == checkpoint
                && !e.after.is_zero()
                && e.tick.is_zero()
                // A replayed Control Commit requires BOTH the exact
                // fsynced Begin and an original CNS receipt binding. Neither
                // a self-consistent legacy C nor a C with only fake receipt
                // bytes can silently publish a physical successor.
                && pending.is_some_and(|prepared| {
                    !e.read.is_zero()
                        && prepared.successor == e.snapshot
                        && prepared.previous_checkpoint == e.before
                        && prepared.migrated_checkpoint == e.after
                })
        }
        'P' => {
            pending.is_none()
                && current == Some(e.snapshot)
                && e.before == checkpoint
                && !e.after.is_zero()
                && e.after != checkpoint
                && !e.read.is_zero()
                && !e.tick.is_zero()
        }
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err(NduPublicationErrorV1::Corrupt)
    }
}
#[derive(Debug)]
struct State {
    file: File,
    // The independent persistent writer lock survives WAL deletion/replacement.
    owner_lock: File,
    journal_path: PathBuf,
    lock_path: PathBuf,
    snapshot: NduSnapshotRefV1,
    checkpoint: Digest32,
    sequence: u64,
    head: Digest32,
    bytes: u64,
    poisoned: bool,
    // Durable B is fsynced, physical effect and original receipt are unresolved.
    // This is a sticky publication fence even while the mutex is released.
    pending_cutover: bool,
    // Hash of latest fsynced original CNS owner receipt bytes, not authority.
    last_cns_original_receipt_binding: Option<Digest32>,
}
impl State {
    #[cfg(unix)]
    fn verify_original_paths(
        &self,
        expected_bytes: u64,
        expected_sequence: u64,
        expected_head: Digest32,
    ) -> Result<(), NduPublicationErrorV1> {
        let (device, inode) = control_owner_file_identity(&self.file, &self.journal_path)?;
        control_owner_file_identity(&self.owner_lock, &self.lock_path)?;
        let expected = format!("NDUW1|{device}|{inode}\n");
        let recorded =
            fs::read(&self.lock_path).map_err(|_| NduPublicationErrorV1::Indeterminate)?;
        if recorded != expected.as_bytes()
            || self
                .file
                .metadata()
                .map_err(|_| NduPublicationErrorV1::Indeterminate)?
                .len()
                != expected_bytes
        {
            return Err(NduPublicationErrorV1::Indeterminate);
        }

        // Same-inode truncation or rewrite can evade an inode-only fence.
        // Check only the fsynced last hash-chain row (at most MAX_ROW bytes).
        if expected_sequence == 0 {
            if expected_bytes != 0 || !expected_head.is_zero() {
                return Err(NduPublicationErrorV1::Indeterminate);
            }
        } else {
            if expected_bytes == 0 || expected_head.is_zero() {
                return Err(NduPublicationErrorV1::Indeterminate);
            }
            let tail_bytes = expected_bytes.min(MAX_ROW as u64) as usize;
            let mut tail = vec![0_u8; tail_bytes];
            self.file
                .read_exact_at(&mut tail, expected_bytes - tail_bytes as u64)
                .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
            if tail.last() != Some(&b'\n') {
                return Err(NduPublicationErrorV1::Indeterminate);
            }
            let start = tail[..tail_bytes - 1]
                .iter()
                .rposition(|byte| *byte == b'\n')
                .map_or(0, |position| position + 1);
            let row = std::str::from_utf8(&tail[start..tail_bytes - 1])
                .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
            let last = decode(row).map_err(|_| NduPublicationErrorV1::Indeterminate)?;
            if last.sequence != expected_sequence
                || last.head != expected_head
                || last.head != event_hash(&last)
            {
                return Err(NduPublicationErrorV1::Indeterminate);
            }
        }
        if self
            .file
            .metadata()
            .map_err(|_| NduPublicationErrorV1::Indeterminate)?
            .len()
            != expected_bytes
        {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        Ok(())
    }

    /// Replay the *entire original locked WAL inode* without cloning its open
    /// file description or changing the serving append cursor. A terminal
    /// hash/size/inode pin by itself cannot detect corruption of an older row.
    /// This bounded scan is for read-only evidence collection, never the hot
    /// Neuron checkpoint publication path.
    #[cfg(unix)]
    fn verify_original_full_history(&self) -> Result<(), NduPublicationErrorV1> {
        if self.bytes == 0 || self.bytes > MAX_BYTES {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        let mut row = Vec::with_capacity(MAX_ROW);
        let mut block = [0_u8; 8192];
        let mut offset = 0_u64;
        let mut sequence = 0_u64;
        let mut head = Digest32::ZERO;
        let mut current = None;
        let mut checkpoint = Digest32::ZERO;
        let mut pending = None;
        let mut original_binding = None;

        while offset < self.bytes {
            let length = (self.bytes - offset).min(block.len() as u64) as usize;
            self.file
                .read_exact_at(&mut block[..length], offset)
                .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
            for &byte in &block[..length] {
                if row.len() == MAX_ROW {
                    return Err(NduPublicationErrorV1::Indeterminate);
                }
                row.push(byte);
                if byte != b'\n' {
                    continue;
                }
                let text = std::str::from_utf8(&row[..row.len() - 1])
                    .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
                let event = decode(text).map_err(|_| NduPublicationErrorV1::Indeterminate)?;
                if event.sequence
                    != sequence
                        .checked_add(1)
                        .ok_or(NduPublicationErrorV1::Indeterminate)?
                    || event.previous != head
                    || event.head != event_hash(&event)
                {
                    return Err(NduPublicationErrorV1::Indeterminate);
                }
                validate_replay(&event, current, checkpoint, pending)
                    .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
                sequence = event.sequence;
                head = event.head;
                match event.kind {
                    'B' => {
                        pending = Some(PendingCutover {
                            successor: event.snapshot,
                            previous_checkpoint: event.before,
                            migrated_checkpoint: event.after,
                        });
                    }
                    'C' => {
                        pending = None;
                        current = Some(event.snapshot);
                        checkpoint = event.after;
                        original_binding = Some(event.read);
                    }
                    _ => {
                        current = Some(event.snapshot);
                        checkpoint = event.after;
                    }
                }
                row.clear();
            }
            offset += length as u64;
        }

        let expected_snapshot = self
            .snapshot
            .semantic_digest()
            .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
        if !row.is_empty()
            || pending.is_some()
            || current != Some(expected_snapshot)
            || checkpoint != self.checkpoint
            || sequence != self.sequence
            || head != self.head
            || original_binding != self.last_cns_original_receipt_binding
        {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        Ok(())
    }

    #[cfg(not(unix))]
    fn verify_original_paths(
        &self,
        _expected_bytes: u64,
        _expected_sequence: u64,
        _expected_head: Digest32,
    ) -> Result<(), NduPublicationErrorV1> {
        Err(NduPublicationErrorV1::Unsupported)
    }

    fn append(
        &mut self,
        kind: char,
        snapshot: Digest32,
        before: Digest32,
        after: Digest32,
        read: Digest32,
        tick: Digest32,
    ) -> Result<Digest32, NduPublicationErrorV1> {
        if self.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        if let Err(error) = self.verify_original_paths(self.bytes, self.sequence, self.head) {
            self.poisoned = true;
            return Err(error);
        }
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or(NduPublicationErrorV1::Capacity)?;
        let mut e = Event {
            sequence,
            previous: self.head,
            head: Digest32::ZERO,
            kind,
            snapshot,
            before,
            after,
            read,
            tick,
        };
        e.head = event_hash(&e);
        let line = format!(
            "N1|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
            e.sequence, e.previous, e.head, e.kind, e.snapshot, e.before, e.after, e.read, e.tick,
        );
        let bytes = self
            .bytes
            .checked_add(line.len() as u64)
            .ok_or(NduPublicationErrorV1::Capacity)?;
        if line.len() > MAX_ROW || bytes > MAX_BYTES {
            return Err(NduPublicationErrorV1::Capacity);
        }
        if let Err(error) = self
            .file
            .write_all(line.as_bytes())
            .and_then(|()| self.file.sync_all())
        {
            self.poisoned = true;
            return Err(error.into());
        }
        if let Err(error) = self.verify_original_paths(bytes, sequence, e.head) {
            self.poisoned = true;
            return Err(error);
        }
        self.sequence = sequence;
        self.head = e.head;
        // A durable Begin is a *fence*, not publication of the successor.
        // Keep the previous checkpoint until the external runtime has
        // executed and a separate final Commit is fsynced.
        if kind != 'B' {
            self.checkpoint = after;
        }
        if kind == 'C' {
            self.last_cns_original_receipt_binding = (!read.is_zero()).then_some(read);
        }
        self.bytes = bytes;
        Ok(e.head)
    }
}

/// Per-scope durable Control owner. A canonical recovered snapshot and
/// checkpoint MUST be independently authenticated before opening this journal.
#[derive(Debug)]
pub struct NduPublicationOwnerV1 {
    state: Mutex<State>,
}

impl NduPublicationOwnerV1 {
    #[cfg(unix)]
    pub fn open_production(
        path: &Path,
        snapshot: NduSnapshotRefV1,
        canonical_checkpoint: Digest32,
    ) -> Result<Self, NduPublicationErrorV1> {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::OpenOptionsExt;
        use std::os::unix::fs::PermissionsExt;
        snapshot
            .validate()
            .map_err(|_| NduPublicationErrorV1::Invalid)?;
        if !path.is_absolute()
            || path.file_name().is_none()
            || path
                .components()
                .any(|c| matches!(c, Component::CurDir | Component::ParentDir))
        {
            return Err(NduPublicationErrorV1::UnsafePath);
        }
        let parent = path.parent().ok_or(NduPublicationErrorV1::UnsafePath)?;
        let dir = fs::symlink_metadata(parent)?;
        if !dir.is_dir() || dir.file_type().is_symlink() || dir.permissions().mode() & 0o077 != 0 {
            return Err(NduPublicationErrorV1::UnsafePath);
        }
        let preexisting = match fs::symlink_metadata(path) {
            Ok(meta)
                if !meta.file_type().is_file()
                    || meta.permissions().mode() & 0o077 != 0
                    || meta.nlink() != 1 =>
            {
                return Err(NduPublicationErrorV1::UnsafePath);
            }
            Ok(_) => true,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        // The marker must either already accompany an existing WAL, or
        // neither path may exist on a first bootstrap. Do not adopt a removed
        // journal, a removed marker, or legacy history lacking identity.
        let mut lock_name = path.as_os_str().to_os_string();
        lock_name.push(".owner-lock");
        let lock_path = PathBuf::from(lock_name);
        let lock_existed = match fs::symlink_metadata(&lock_path) {
            Ok(meta)
                if !meta.file_type().is_file()
                    || meta.permissions().mode() & 0o077 != 0
                    || meta.nlink() != 1 =>
            {
                return Err(NduPublicationErrorV1::UnsafePath);
            }
            Ok(_) => true,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        if preexisting != lock_existed {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        let mut lock_options = OpenOptions::new();
        lock_options.read(true).write(true).mode(0o600);
        if !preexisting {
            lock_options.create_new(true);
        }
        let mut owner_lock = lock_options.open(&lock_path)?;
        control_owner_file_identity(&owner_lock, &lock_path)?;
        owner_lock
            .try_lock()
            .map_err(|_| NduPublicationErrorV1::WriterUnavailable)?;
        if !preexisting {
            // Once the marker exists durably, a crash before genesis must
            // quarantine the half-bootstrapped owner rather than reinitialize.
            fs::File::open(parent)?.sync_all()?;
        }

        let mut journal_options = OpenOptions::new();
        journal_options.read(true).append(true).mode(0o600);
        if !preexisting {
            journal_options.create_new(true);
        }
        let file = journal_options.open(path)?;
        let (journal_device, journal_inode) = control_owner_file_identity(&file, path)?;
        file.try_lock()
            .map_err(|_| NduPublicationErrorV1::WriterUnavailable)?;
        let expected_marker = format!("NDUW1|{journal_device}|{journal_inode}\n");
        if preexisting {
            let mut recorded = Vec::new();
            owner_lock
                .try_clone()?
                .take(256)
                .read_to_end(&mut recorded)?;
            if recorded != expected_marker.as_bytes() {
                return Err(NduPublicationErrorV1::Indeterminate);
            }
        } else {
            owner_lock.write_all(expected_marker.as_bytes())?;
            owner_lock.sync_all()?;
            fs::File::open(parent)?.sync_all()?;
        }
        let mut reader = BufReader::new(file.try_clone()?);
        let mut row = Vec::new();
        let mut sequence = 0u64;
        let mut head = Digest32::ZERO;
        let mut latest = None;
        let mut checkpoint = Digest32::ZERO;
        let mut pending = None;
        let mut last_cns_original_receipt_binding = None;
        let mut bytes = 0u64;
        loop {
            row.clear();
            let read = (&mut reader)
                .take((MAX_ROW + 1) as u64)
                .read_until(b'\n', &mut row)?;
            if read == 0 {
                break;
            }
            bytes = bytes
                .checked_add(read as u64)
                .ok_or(NduPublicationErrorV1::Capacity)?;
            if read > MAX_ROW || bytes > MAX_BYTES || row.pop() != Some(b'\n') {
                return Err(NduPublicationErrorV1::Corrupt);
            }
            let text = std::str::from_utf8(&row).map_err(|_| NduPublicationErrorV1::Corrupt)?;
            let e = decode(text)?;
            if e.sequence
                != sequence
                    .checked_add(1)
                    .ok_or(NduPublicationErrorV1::Corrupt)?
                || e.previous != head
                || e.head != event_hash(&e)
            {
                return Err(NduPublicationErrorV1::Corrupt);
            }
            validate_replay(&e, latest, checkpoint, pending)?;
            sequence = e.sequence;
            head = e.head;
            match e.kind {
                'B' => {
                    pending = Some(PendingCutover {
                        successor: e.snapshot,
                        previous_checkpoint: e.before,
                        migrated_checkpoint: e.after,
                    });
                }
                'C' => {
                    pending = None;
                    latest = Some(e.snapshot);
                    checkpoint = e.after;
                    last_cns_original_receipt_binding = (!e.read.is_zero()).then_some(e.read);
                }
                _ => {
                    latest = Some(e.snapshot);
                    checkpoint = e.after;
                }
            }
        }
        // A Begin without an original committed successor is ambiguous.
        // In particular, do not replay an external effect or trust an old
        // canonical checkpoint to reset this owner's anti-rollback frontier.
        if pending.is_some() {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        // An existing zero-byte file could be a truncated ledger. Never treat
        // it as a first bootstrap or silently erase the rollback evidence.
        if preexisting && latest.is_none() {
            return Err(NduPublicationErrorV1::Corrupt);
        }
        let canonical = snapshot
            .semantic_digest()
            .map_err(|_| NduPublicationErrorV1::Invalid)?;
        if latest.is_some() && (latest != Some(canonical) || checkpoint != canonical_checkpoint) {
            return Err(NduPublicationErrorV1::Stale);
        }
        let mut state = State {
            file,
            owner_lock,
            journal_path: path.to_path_buf(),
            lock_path,
            snapshot,
            checkpoint,
            sequence,
            head,
            bytes,
            poisoned: false,
            pending_cutover: false,
            last_cns_original_receipt_binding,
        };
        // Pin the replayed last durable row before accepting any new G/P/C.
        state.verify_original_paths(state.bytes, state.sequence, state.head)?;
        if latest.is_none() {
            state.append(
                'G',
                canonical,
                Digest32::ZERO,
                canonical_checkpoint,
                Digest32::ZERO,
                Digest32::ZERO,
            )?;
        }
        fs::File::open(parent)?.sync_all()?;
        Ok(Self {
            state: Mutex::new(state),
        })
    }

    #[cfg(not(unix))]
    pub fn open_production(
        _path: &Path,
        _snapshot: NduSnapshotRefV1,
        _checkpoint: Digest32,
    ) -> Result<Self, NduPublicationErrorV1> {
        Err(NduPublicationErrorV1::Unsupported)
    }

    pub fn current(&self) -> Result<(NduSnapshotRefV1, Digest32), NduPublicationErrorV1> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Poisoned)?;
        if state.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        if let Err(error) = state.verify_original_paths(state.bytes, state.sequence, state.head) {
            state.poisoned = true;
            return Err(error);
        }
        if state.pending_cutover {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        Ok((state.snapshot.clone(), state.checkpoint))
    }

    /// Original Control owner Actor readback. Scans and replays only already
    /// fsynced WAL bytes from its pinned file descriptor; does not flush
    /// staging, seek the shared descriptor, issue signatures or mutate CNS.
    /// An unresolved B/C handoff and any earlier-prefix corruption deny.
    #[cfg(unix)]
    pub fn read_original_local_frontier_v1(
        &self,
    ) -> Result<NduPublicationLocalFrontierV1, NduPublicationErrorV1> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Poisoned)?;
        if state.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        if let Err(error) = state.verify_original_paths(state.bytes, state.sequence, state.head) {
            state.poisoned = true;
            return Err(error);
        }
        if state.pending_cutover {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        if let Err(error) = state.verify_original_full_history() {
            state.poisoned = true;
            return Err(error);
        }
        let identities = control_owner_file_identity(&state.file, &state.journal_path)
            .and_then(|wal| {
                control_owner_file_identity(&state.owner_lock, &state.lock_path)
                    .map(|marker| (wal, marker))
            });
        let ((wal_device, wal_inode), (marker_device, marker_inode)) = match identities {
            Ok(identities) => identities,
            Err(error) => {
                state.poisoned = true;
                return Err(error);
            }
        };
        if let Err(error) = state.verify_original_paths(state.bytes, state.sequence, state.head) {
            state.poisoned = true;
            return Err(error);
        }
        Ok(NduPublicationLocalFrontierV1 {
            snapshot: state.snapshot.clone(),
            checkpoint: state.checkpoint,
            sequence: state.sequence,
            head: state.head,
            wal_bytes: state.bytes,
            wal_device,
            wal_inode,
            marker_device,
            marker_inode,
            original_cns_receipt_binding: state.last_cns_original_receipt_binding,
        })
    }

    #[cfg(not(unix))]
    pub fn read_original_local_frontier_v1(
        &self,
    ) -> Result<NduPublicationLocalFrontierV1, NduPublicationErrorV1> {
        Err(NduPublicationErrorV1::Unsupported)
    }

    /// Read-only reference for independent Observer verification of the
    /// original signed CNS commit. This is a digest of exact runtime-owner
    /// receipt bytes, NOT an attestation, capability, or physical state proof.
    /// The Observer still needs original pinned signature and live readback.
    pub fn last_cns_original_receipt_binding(
        &self,
    ) -> Result<Option<Digest32>, NduPublicationErrorV1> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Poisoned)?;
        if state.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        if let Err(error) = state.verify_original_paths(state.bytes, state.sequence, state.head) {
            state.poisoned = true;
            return Err(error);
        }
        if state.pending_cutover {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        Ok(state.last_cns_original_receipt_binding)
    }

    /// Compatibility read-only check. The returned equality is never an
    /// independent signed CNS runtime receipt or a physical cutover grant.
    /// Preserve the original public Result<(), _> API for existing readers.
    pub fn verify_original_cns_receipt_binding(
        &self,
        externally_verified_original_receipt_bytes: &[u8],
    ) -> Result<(), NduPublicationErrorV1> {
        self.verify_original_cns_receipt_frontier_v1(externally_verified_original_receipt_bytes)
            .map(|_| ())
    }

    /// Atomic original Control WAL readback for an independently authenticated
    /// CNS receipt. Signature verification and live route proof are owned by
    /// the external CNS witness; this output itself is LOCAL and UNSIGNED.
    /// Control Commit's immutable WAL evidence link. The caller must have
    /// *already verified* the original runtime key, exact commit identity and
    /// fresh serving-state readback. This byte comparison does none of those
    /// authorizations and cannot itself activate a split.
    #[cfg(unix)]
    pub fn verify_original_cns_receipt_frontier_v1(
        &self,
        externally_verified_original_receipt_bytes: &[u8],
    ) -> Result<NduPublicationLocalFrontierV1, NduPublicationErrorV1> {
        // A separate last_binding() call would release the Control mutex
        // before comparing bytes, allowing a new fsynced C record between
        // the two reads. Compare against exactly one locked live frontier.
        let mut state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Poisoned)?;
        if state.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        if let Err(error) = state.verify_original_paths(state.bytes, state.sequence, state.head) {
            state.poisoned = true;
            return Err(error);
        }
        if state.pending_cutover {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        // A valid terminal row is not proof of an unmodified older prefix.
        // The signed original CNS/Control join must replay the real Control
        // history before accepting the cached Commit receipt binding.
        if let Err(error) = state.verify_original_full_history() {
            state.poisoned = true;
            return Err(error);
        }
        let expected = state
            .last_cns_original_receipt_binding
            .ok_or(NduPublicationErrorV1::Stale)?;
        let observed = original_cns_receipt_binding(externally_verified_original_receipt_bytes)?;
        if expected != observed {
            return Err(NduPublicationErrorV1::Stale);
        }
        // The checksum was computed while holding the Control mutex. A
        // concurrent pathname replacement is still possible; recheck the
        // original WAL and persistent writer lock before reporting equality.
        if let Err(error) = state.verify_original_paths(state.bytes, state.sequence, state.head) {
            state.poisoned = true;
            return Err(error);
        }
        let identities = control_owner_file_identity(&state.file, &state.journal_path)
            .and_then(|wal| {
                control_owner_file_identity(&state.owner_lock, &state.lock_path)
                    .map(|marker| (wal, marker))
            });
        let ((wal_device, wal_inode), (marker_device, marker_inode)) = match identities {
            Ok(identities) => identities,
            Err(error) => {
                state.poisoned = true;
                return Err(error);
            }
        };
        Ok(NduPublicationLocalFrontierV1 {
            snapshot: state.snapshot.clone(),
            checkpoint: state.checkpoint,
            sequence: state.sequence,
            head: state.head,
            wal_bytes: state.bytes,
            wal_device,
            wal_inode,
            marker_device,
            marker_inode,
            original_cns_receipt_binding: state.last_cns_original_receipt_binding,
        })
    }

    #[cfg(not(unix))]
    pub fn verify_original_cns_receipt_frontier_v1(
        &self,
        _externally_verified_original_receipt_bytes: &[u8],
    ) -> Result<NduPublicationLocalFrontierV1, NduPublicationErrorV1> {
        Err(NduPublicationErrorV1::Unsupported)
    }

    /// Compatibility-only name. The old single-phase API could write a
    /// successful route cutover without a durable pre-effect Prepare, which
    /// left an ambiguous crash window and bypassed the Neuron Control lane.
    /// It is permanently non-authorizing; callers must migrate to the
    /// separately reviewed fsynced Begin/physical-effect/Commit protocol.
    #[deprecated(note = "single-phase CNS publication is denied; use guarded durable handoff")]
    pub fn publish_cutover(
        &self,
        _expected: &NduSnapshotRefV1,
        _expected_checkpoint: Digest32,
        _next: NduSnapshotRefV1,
        _migrated_checkpoint: Digest32,
    ) -> Result<Digest32, NduPublicationErrorV1> {
        Err(NduPublicationErrorV1::Unsupported)
    }

    /// Transactional adapter for a *real* external CNS owner. Write a
    /// durable, fsynced Begin first, while holding the SAME Control mutex
    /// used by Neuron checkpoint CAS. A sticky pending fence then allows
    /// releasing that mutex before slow external I/O; all competing Neuron
    /// CAS and Control reads return Indeterminate until Commit is durable.
    /// The trusted caller must execute the real runtime cutover, verify
    /// its ORIGINAL signed receipt against independently pinned runtime
    /// authority, perform a fresh durable readback and return the exact original
    /// receipt bytes in the closure. Control records their domain-separated
    /// digest in C to bind the WAL to that external evidence; this hash is
    /// NOT itself proof of signature validity or production authorization.
    /// An empty, truncated or oversized receipt leaves Begin unresolved.
    ///
    /// Any failure or crash after Begin permanently quarantines this owner
    /// until an independently witnessed reconciliation; neither route nor
    /// model effects may be automatically retried on restart.
    /// Research-only Control WAL exercised with explicit test fixtures. Do
    /// not expose a public closure that can self-assert unsigned CNS success:
    /// real activation requires a separately reviewed original-owner signed
    /// receipt verifier and an atomic Final-use/Control integration.
    #[cfg(test)]
    pub(crate) fn publish_cutover_with_external_effect<T, E: std::fmt::Display>(
        &self,
        expected: &NduSnapshotRefV1,
        expected_checkpoint: Digest32,
        next: NduSnapshotRefV1,
        migrated_checkpoint: Digest32,
        apply_original_runtime_once: impl FnOnce() -> Result<(T, Vec<u8>), E>,
    ) -> Result<(T, Digest32), NduPublicationErrorV1> {
        next.validate()
            .map_err(|_| NduPublicationErrorV1::Invalid)?;
        if migrated_checkpoint.is_zero() {
            return Err(NduPublicationErrorV1::Invalid);
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Poisoned)?;
        if state.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        if state.pending_cutover {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        if state.snapshot != *expected
            || state.checkpoint != expected_checkpoint
            || next.scope_id != expected.scope_id
            // A new NDU owner or policy needs an independently signed
            // handoff protocol. Until then never silently change trust roots.
            || next.owner_id != expected.owner_id
            || next.policy_digest != expected.policy_digest
            || next.generation < expected.generation
            || next.route_fence <= expected.route_fence
            || next.revocation_epoch < expected.revocation_epoch
        {
            return Err(NduPublicationErrorV1::Stale);
        }
        let successor = next
            .semantic_digest()
            .map_err(|_| NduPublicationErrorV1::Invalid)?;
        // Reserve two WAL sequences and the maximum bytes of BOTH Begin and
        // Commit before the original external CNS effect. A known exhausted
        // journal must never accept a Begin it cannot safely resolve.
        if state.sequence.checked_add(2).is_none()
            || state
                .bytes
                .checked_add(2 * MAX_ROW as u64)
                .is_none_or(|total| total > MAX_BYTES)
        {
            return Err(NduPublicationErrorV1::Capacity);
        }
        // A failed fsync makes the business effect inadmissible; do not run
        // the closure until Begin itself has been durably committed.
        state.append(
            'B',
            successor,
            expected_checkpoint,
            migrated_checkpoint,
            Digest32::ZERO,
            Digest32::ZERO,
        )?;
        state.pending_cutover = true;
        // The durable pending flag, not a mutex held over external runtime I/O,
        // fences model CAS and all other cutovers. Callback readback may safely
        // reenter Control and receive Indeterminate instead of deadlocking.
        drop(state);
        let actual_result = apply_original_runtime_once();
        let mut state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
        if !state.pending_cutover {
            state.poisoned = true;
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        let (actual, original_receipt_bytes) = match actual_result {
            Ok(receipt) => receipt,
            Err(_) => {
                state.poisoned = true;
                return Err(NduPublicationErrorV1::Indeterminate);
            }
        };
        // Original CNS attestations include authenticated operation bindings
        // and a runtime signature. Control never treats a short opaque OK or a
        // caller-supplied digest as a physical completion receipt.
        let original_receipt_digest = match original_cns_receipt_binding(&original_receipt_bytes) {
            Ok(digest) => digest,
            Err(_) => {
                state.poisoned = true;
                return Err(NduPublicationErrorV1::Indeterminate);
            }
        };
        // A rejected Commit is indeterminate even if the external runtime
        // succeeded. Never let another model tick or cutover enter this lane.
        let committed = match state.append(
            'C',
            successor,
            expected_checkpoint,
            migrated_checkpoint,
            original_receipt_digest,
            Digest32::ZERO,
        ) {
            Ok(receipt) => receipt,
            Err(_) => {
                state.poisoned = true;
                return Err(NduPublicationErrorV1::Indeterminate);
            }
        };
        state.snapshot = next;
        state.pending_cutover = false;
        Ok((actual, committed))
    }

    pub fn compare_and_publish_checkpoint(
        &self,
        expected: &NduSnapshotRefV1,
        read: Digest32,
        tick: Digest32,
        before: Digest32,
        after: Digest32,
    ) -> Result<Digest32, NduPublicationErrorV1> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Poisoned)?;
        if state.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        if state.pending_cutover {
            return Err(NduPublicationErrorV1::Indeterminate);
        }
        if state.snapshot != *expected || state.checkpoint != before {
            return Err(NduPublicationErrorV1::Stale);
        }
        if read.is_zero() || tick.is_zero() || after.is_zero() || after == before {
            return Err(NduPublicationErrorV1::Invalid);
        }
        let digest = expected
            .semantic_digest()
            .map_err(|_| NduPublicationErrorV1::Invalid)?;
        state.append('P', digest, before, after, read, tick)
    }
}

#[cfg(test)]
#[path = "ndu_publication_tests.rs"]
mod tests;
