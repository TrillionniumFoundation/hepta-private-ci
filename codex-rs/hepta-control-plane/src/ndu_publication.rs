//! Durable single-scope Control ledger. NDU route cutover and checkpoint
//! publication share one exclusive owner lock, journal and fsync boundary.
//! A separate CNS route writer bypassing this owner is not atomic.

use std::fs::File;
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

/// Bind the Control WAL bootstrap to one already-open private directory.
/// This also rejects a parent path rebind after its first canonical check.
/// Calls are read-only: only the independently locked WAL writer may mutate.
#[cfg(unix)]
fn control_parent_dir_identity(
    directory: &File,
    parent: &Path,
) -> Result<(), NduPublicationErrorV1> {
    use std::os::unix::fs::{MetadataExt, PermissionsExt};

    if parent.canonicalize().map_err(|_| NduPublicationErrorV1::UnsafePath)? != parent {
        return Err(NduPublicationErrorV1::UnsafePath);
    }
    let opened = directory
        .metadata()
        .map_err(|_| NduPublicationErrorV1::Indeterminate)?;
    let named = fs::symlink_metadata(parent).map_err(|_| NduPublicationErrorV1::Indeterminate)?;
    if !opened.is_dir()
        || !named.file_type().is_dir()
        || named.file_type().is_symlink()
        || opened.dev() != named.dev()
        || opened.ino() != named.ino()
        || opened.uid() != named.uid()
        || opened.permissions().mode() & 0o077 != 0
        || named.permissions().mode() & 0o077 != 0
    {
        return Err(NduPublicationErrorV1::Indeterminate);
    }
    Ok(())
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
                && match pending {
                    // Every new guarded Commit must identify the exact original
                    // runtime receipt bytes witnessed after durable Begin.
                    Some(prepared) => {
                        !e.read.is_zero()
                            && prepared.successor == e.snapshot
                            && prepared.previous_checkpoint == e.before
                            && prepared.migrated_checkpoint == e.after
                    }
                    // Existing pre-B journals may contain historical C events.
                    // Retain their old representation for honest replay, not
                    // as a new, publicly writable single-phase cutover path.
                    None => e.read.is_zero(),
                }
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
        // Public production entry has no caller-supplied hook. Only test code
        // can inject an exact post-dirfd rebind, never an authorization.
        Self::open_production_with_directory_hook(path, snapshot, canonical_checkpoint, || {})
    }

    #[cfg(unix)]
    fn open_production_with_directory_hook(
        path: &Path,
        snapshot: NduSnapshotRefV1,
        canonical_checkpoint: Digest32,
        after_directory_pinned: impl FnOnce(),
    ) -> Result<Self, NduPublicationErrorV1> {
        use rustix::fs::{self as unixfs, Mode, OFlags};
        use std::os::unix::fs::MetadataExt;
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
        // symlink_metadata(parent) only checks the final path component.
        // A symlink in an EARLIER ancestor can alias the same private WAL
        // and owner-lock under a second, non-canonical name. Refuse such
        // aliases before creating, reading or locking either durable file.
        // This bootstrap check is not a substitute for independent custody
        // or kernel-anchored openat protection against privileged path races.
        if parent.canonicalize().map_err(|_| NduPublicationErrorV1::UnsafePath)? != parent {
            return Err(NduPublicationErrorV1::UnsafePath);
        }
        let dir = fs::symlink_metadata(parent)?;
        if !dir.is_dir() || dir.file_type().is_symlink() || dir.permissions().mode() & 0o077 != 0 {
            return Err(NduPublicationErrorV1::UnsafePath);
        }
        // Pin the actual private directory before resolving either child.
        // Safe rustix::openat uses this FD instead of reopening mutable
        // absolute pathnames, preserving the crate's forbid(unsafe_code).
        let parent_dir = File::from(
            unixfs::open(
                parent,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| NduPublicationErrorV1::UnsafePath)?,
        );
        control_parent_dir_identity(&parent_dir, parent)?;
        // Deterministic fault-injection point for tests: production always
        // supplies an empty closure and still rechecks parent identity.
        after_directory_pinned();
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
        let mut lock_flags = OFlags::RDWR | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        if !preexisting {
            lock_flags |= OFlags::CREATE | OFlags::EXCL;
        }
        let private_mode = Mode::from_bits_truncate(0o600);
        let mut owner_lock = File::from(
            unixfs::openat(
                &parent_dir,
                lock_path.file_name().ok_or(NduPublicationErrorV1::UnsafePath)?,
                lock_flags,
                private_mode,
            )
            .map_err(|_| NduPublicationErrorV1::Indeterminate)?,
        );
        control_owner_file_identity(&owner_lock, &lock_path)?;
        control_parent_dir_identity(&parent_dir, parent)?;
        owner_lock
            .try_lock()
            .map_err(|_| NduPublicationErrorV1::WriterUnavailable)?;
        if !preexisting {
            // A crash after this fsync but before genesis is quarantined
            // by the original marker rather than silently rebootstrapped.
            parent_dir.sync_all()?;
        }

        let mut journal_flags = OFlags::RDWR | OFlags::APPEND | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        if !preexisting {
            journal_flags |= OFlags::CREATE | OFlags::EXCL;
        }
        let file = File::from(
            unixfs::openat(
                &parent_dir,
                path.file_name().ok_or(NduPublicationErrorV1::UnsafePath)?,
                journal_flags,
                private_mode,
            )
            .map_err(|_| NduPublicationErrorV1::Indeterminate)?,
        );
        let (journal_device, journal_inode) = control_owner_file_identity(&file, path)?;
        control_parent_dir_identity(&parent_dir, parent)?;
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
            parent_dir.sync_all()?;
            control_parent_dir_identity(&parent_dir, parent)?;
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
        parent_dir.sync_all()?;
        control_parent_dir_identity(&parent_dir, parent)?;
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

    /// Compare freshly authenticated original CNS receipt bytes against the
    /// Control Commit's immutable WAL evidence link. The caller must have
    /// *already verified* the original runtime key, exact commit identity and
    /// fresh serving-state readback. This byte comparison does none of those
    /// authorizations and cannot itself activate a split.
    pub fn verify_original_cns_receipt_binding(
        &self,
        externally_verified_original_receipt_bytes: &[u8],
    ) -> Result<(), NduPublicationErrorV1> {
        let expected = self
            .last_cns_original_receipt_binding()?
            .ok_or(NduPublicationErrorV1::Stale)?;
        let observed = original_cns_receipt_binding(externally_verified_original_receipt_bytes)?;
        if expected != observed {
            return Err(NduPublicationErrorV1::Stale);
        }
        Ok(())
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
