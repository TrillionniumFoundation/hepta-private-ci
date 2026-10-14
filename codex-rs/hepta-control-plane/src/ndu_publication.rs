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
use std::path::Component;
use std::path::Path;
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
                && e.read.is_zero()
                && e.tick.is_zero()
                && pending.is_none_or(|prepared| {
                    prepared.successor == e.snapshot
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
    snapshot: NduSnapshotRefV1,
    checkpoint: Digest32,
    sequence: u64,
    head: Digest32,
    bytes: u64,
    poisoned: bool,
}
impl State {
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
        self.sequence = sequence;
        self.head = e.head;
        // A durable Begin is a *fence*, not publication of the successor.
        // Keep the previous checkpoint until the external runtime has
        // executed and a separate final Commit is fsynced.
        if kind != 'B' {
            self.checkpoint = after;
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
        let file = OpenOptions::new()
            .create(true)
            .read(true)
            .append(true)
            .mode(0o600)
            .open(path)?;
        let opened = file.metadata()?;
        let named = fs::symlink_metadata(path)?;
        if !opened.is_file()
            || !named.file_type().is_file()
            || opened.dev() != named.dev()
            || opened.ino() != named.ino()
            || opened.nlink() != 1
            || named.nlink() != 1
            || opened.permissions().mode() & 0o077 != 0
            || named.permissions().mode() & 0o077 != 0
        {
            return Err(NduPublicationErrorV1::UnsafePath);
        }
        file.try_lock()
            .map_err(|_| NduPublicationErrorV1::WriterUnavailable)?;
        let mut reader = BufReader::new(file.try_clone()?);
        let mut row = Vec::new();
        let mut sequence = 0u64;
        let mut head = Digest32::ZERO;
        let mut latest = None;
        let mut checkpoint = Digest32::ZERO;
        let mut pending = None;
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
            snapshot,
            checkpoint,
            sequence,
            head,
            bytes,
            poisoned: false,
        };
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
        let state = self
            .state
            .lock()
            .map_err(|_| NduPublicationErrorV1::Poisoned)?;
        if state.poisoned {
            return Err(NduPublicationErrorV1::Poisoned);
        }
        Ok((state.snapshot.clone(), state.checkpoint))
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
    /// used by Neuron checkpoint CAS. The trusted caller must execute the
    /// real runtime cutover and persist its original receipt in the closure.
    /// Only after that succeeds may this owner append/acknowledge Commit.
    ///
    /// Any failure or crash after Begin permanently quarantines this owner
    /// until an independently witnessed reconciliation; neither route nor
    /// model effects may be automatically retried on restart.
    pub fn publish_cutover_with_external_effect<T, E: std::fmt::Display>(
        &self,
        expected: &NduSnapshotRefV1,
        expected_checkpoint: Digest32,
        next: NduSnapshotRefV1,
        migrated_checkpoint: Digest32,
        apply_original_runtime_once: impl FnOnce() -> Result<T, E>,
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
        if state.snapshot != *expected
            || state.checkpoint != expected_checkpoint
            || next.scope_id != expected.scope_id
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
        let actual = match apply_original_runtime_once() {
            Ok(receipt) => receipt,
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
            Digest32::ZERO,
            Digest32::ZERO,
        ) {
            Ok(receipt) => receipt,
            Err(_) => {
                state.poisoned = true;
                return Err(NduPublicationErrorV1::Indeterminate);
            }
        };
        state.snapshot = next;
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
