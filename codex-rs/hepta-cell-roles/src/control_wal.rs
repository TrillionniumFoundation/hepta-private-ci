//! Scope-sharded append-only ControlRole WAL. This is an opt-in owner; it does
//! not rewrite or implicitly migrate the existing V1 snapshot owner.
//!
//! One process holds an OS writer lock for the lifetime of each (cell, scope)
//! lane. All mutations append exactly one bounded, chained frame and fsync
//! before becoming visible. Reopen replays typed mutations, not cached claims.
//! A torn/changed frame fails closed; exceeding the size bound requires a
//! separately fenced generation rollover, never destructive truncation.

use super::*;
use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};

const WAL_MAGIC: &[u8] = b"HEPTA-CONTROL-SCOPE-WAL-V1\0";
const WAL_FRAME_DOMAIN: &[u8] = b"hepta.control.scope-wal.frame.v1";
const WAL_GENESIS_DOMAIN: &[u8] = b"hepta.control.scope-wal.genesis.v1";
const MAX_WAL_BYTES: usize = 64 * 1024 * 1024;
const MAX_WAL_EVENTS: u64 = 65_536;
const MAX_WAL_FRAME_BYTES: usize = 65_536;
const FRAME_FIXED_BYTES: usize = 8 + 32 + 32 + 32;

#[derive(Clone, Debug)]
enum ControlWalEventV1 {
    Prepare(ControlDispatchIntentV1),
    Forward(StableId),
    Terminal(StableId, Digest32),
    Reconcile(StableId),
    Activate(StableId, Generation, Digest32),
    Clock(u64),
}

#[derive(Clone, Debug)]
enum ControlWalOutputV1 {
    Receipt(ControlDispatchReceiptV1),
    Digest(Digest32),
    None,
}

impl ControlWalOutputV1 {
    fn digest(&self) -> Result<Digest32, ControlOwnerErrorV1> {
        match self {
            Self::Receipt(receipt) => receipt.content_digest(),
            Self::Digest(digest) => Ok(*digest),
            Self::None => Ok(Digest32::ZERO),
        }
    }
}

impl ControlWalEventV1 {
    fn apply(
        &self,
        owner: &mut InMemoryControlRoleOwnerV1,
        expected_cell: &StableId,
        expected_scope: Digest32,
    ) -> Result<ControlWalOutputV1, ControlOwnerErrorV1> {
        match self {
            Self::Prepare(intent) => {
                if &intent.cell_id != expected_cell || intent.scope_digest != expected_scope {
                    return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
                }
                Ok(ControlWalOutputV1::Receipt(owner.prepare(intent.clone())?))
            }
            Self::Forward(id) => Ok(ControlWalOutputV1::Receipt(owner.forward(id)?)),
            Self::Terminal(id, digest) => Ok(ControlWalOutputV1::Receipt(
                owner.record_terminal(id, *digest)?,
            )),
            Self::Reconcile(id) => Ok(ControlWalOutputV1::Receipt(owner.reconcile_restart(id)?)),
            Self::Activate(cell, generation, fence) => {
                if cell != expected_cell {
                    return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
                }
                Ok(ControlWalOutputV1::Digest(owner.activate_generation(
                    cell.clone(),
                    *generation,
                    *fence,
                )?))
            }
            Self::Clock(now) => {
                if *now < owner.now_ms {
                    return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
                }
                owner.set_now_ms(*now);
                Ok(ControlWalOutputV1::None)
            }
        }
    }

    fn encode(&self) -> Result<Vec<u8>, ControlOwnerErrorV1> {
        let mut bytes = Vec::new();
        match self {
            Self::Prepare(intent) => {
                bytes.push(0);
                encode_intent(&mut bytes, intent)?;
            }
            Self::Forward(id) => {
                bytes.push(1);
                put_id(&mut bytes, id)?;
            }
            Self::Terminal(id, digest) => {
                bytes.push(2);
                put_id(&mut bytes, id)?;
                put_digest(&mut bytes, *digest);
            }
            Self::Reconcile(id) => {
                bytes.push(3);
                put_id(&mut bytes, id)?;
            }
            Self::Activate(cell, generation, fence) => {
                bytes.push(4);
                put_id(&mut bytes, cell)?;
                put_u64(&mut bytes, generation.get());
                put_digest(&mut bytes, *fence);
            }
            Self::Clock(now) => {
                bytes.push(5);
                put_u64(&mut bytes, *now);
            }
        }
        if bytes.len() + FRAME_FIXED_BYTES > MAX_WAL_FRAME_BYTES {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        Ok(bytes)
    }

    fn decode(bytes: &[u8]) -> Result<Self, ControlOwnerErrorV1> {
        let mut cursor = ControlCursor::new(bytes);
        let event = match cursor.byte()? {
            0 => Self::Prepare(decode_intent(&mut cursor)?),
            1 => Self::Forward(cursor.id()?),
            2 => Self::Terminal(cursor.id()?, cursor.digest()?),
            3 => Self::Reconcile(cursor.id()?),
            4 => Self::Activate(
                cursor.id()?,
                Generation::new(cursor.u64()?)
                    .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?,
                cursor.digest()?,
            ),
            5 => Self::Clock(cursor.u64()?),
            _ => return Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        };
        if !cursor.is_empty() {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        Ok(event)
    }
}

fn wal_header(cell: &StableId, scope: Digest32) -> Result<Vec<u8>, ControlOwnerErrorV1> {
    let mut bytes = WAL_MAGIC.to_vec();
    put_id(&mut bytes, cell)?;
    put_digest(&mut bytes, scope);
    Ok(bytes)
}

fn wal_frame(
    sequence: u64,
    previous: Digest32,
    result_digest: Digest32,
    event: &[u8],
) -> Result<(Vec<u8>, Digest32), ControlOwnerErrorV1> {
    let length = FRAME_FIXED_BYTES
        .checked_add(event.len())
        .ok_or(ControlOwnerErrorV1::InvalidDurableSnapshot)?;
    if length > MAX_WAL_FRAME_BYTES {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let digest = Digest32::of_parts(&[
        WAL_FRAME_DOMAIN,
        &sequence.to_be_bytes(),
        previous.as_array(),
        result_digest.as_array(),
        event,
    ]);
    let mut frame = Vec::with_capacity(4 + length);
    put_u32(&mut frame, length)?;
    put_u64(&mut frame, sequence);
    put_digest(&mut frame, previous);
    put_digest(&mut frame, result_digest);
    frame.extend_from_slice(event);
    put_digest(&mut frame, digest);
    Ok((frame, digest))
}

fn replay_wal(
    bytes: &[u8],
    cell: &StableId,
    scope: Digest32,
) -> Result<(InMemoryControlRoleOwnerV1, Digest32, u64), ControlOwnerErrorV1> {
    if bytes.len() > MAX_WAL_BYTES {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let header = wal_header(cell, scope)?;
    if !bytes.starts_with(&header) {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let mut owner = InMemoryControlRoleOwnerV1::default();
    let mut predecessor = Digest32::of_parts(&[WAL_GENESIS_DOMAIN, &header]);
    let mut sequence = 0_u64;
    let mut cursor = ControlCursor::new(&bytes[header.len()..]);
    while !cursor.is_empty() {
        if sequence >= MAX_WAL_EVENTS {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let length = cursor.u32()? as usize;
        if !(FRAME_FIXED_BYTES..=MAX_WAL_FRAME_BYTES).contains(&length) {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let mut frame = ControlCursor::new(cursor.take(length)?);
        let seen_sequence = frame.u64()?;
        let seen_predecessor = frame.digest()?;
        let expected_output = frame.digest()?;
        let event_length = length - FRAME_FIXED_BYTES;
        let event_bytes = frame.take(event_length)?;
        let recorded_digest = frame.digest()?;
        if seen_sequence != sequence + 1 || seen_predecessor != predecessor || !frame.is_empty() {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let (_, computed) = wal_frame(seen_sequence, predecessor, expected_output, event_bytes)?;
        if computed != recorded_digest {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let event = ControlWalEventV1::decode(event_bytes)?;
        let observed = event
            .apply(&mut owner, cell, scope)
            .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?;
        if observed.digest()? != expected_output {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        sequence = seen_sequence;
        predecessor = computed;
    }
    Ok((owner, predecessor, sequence))
}

/// Independently fenced owner for one cell and one immutable scope. It does
/// not share a global writer lock with other lanes. A full-target production
/// host must still bind the root directory to its trusted storage identity.
#[derive(Debug)]
pub struct ScopedControlWalOwnerV1 {
    cell_id: StableId,
    scope_digest: Digest32,
    path: PathBuf,
    writer: File,
    inner: InMemoryControlRoleOwnerV1,
    head: Digest32,
    sequence: u64,
    bytes: usize,
    poisoned: bool,
}

impl ScopedControlWalOwnerV1 {
    pub fn open(
        directory: impl AsRef<Path>,
        cell_id: StableId,
        scope_digest: Digest32,
    ) -> Result<Self, ControlOwnerErrorV1> {
        if cell_id.as_str().is_empty() || scope_digest.is_zero() {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let directory = directory.as_ref();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            fs::DirBuilder::new()
                .mode(0o700)
                .recursive(true)
                .create(directory)
                .or_else(|error| {
                    if error.kind() == std::io::ErrorKind::AlreadyExists {
                        Ok(())
                    } else {
                        Err(error)
                    }
                })
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            use std::os::unix::fs::MetadataExt;
            let metadata =
                fs::symlink_metadata(directory).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
        }
        #[cfg(not(unix))]
        {
            fs::create_dir_all(directory).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            if !fs::symlink_metadata(directory)
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?
                .is_dir()
            {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
        }
        let lane = Digest32::of_parts(&[
            b"hepta.control.scope-wal-lane.v1",
            cell_id.as_str().as_bytes(),
            scope_digest.as_array(),
        ]);
        let path = directory.join(format!("lane-{lane}.wal"));
        reject_durable_path(&path)?;
        let new_file = !path.exists();
        let mut options = fs::OpenOptions::new();
        options.read(true).append(true).create(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut writer = options
            .open(&path)
            .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        writer
            .try_lock()
            .map_err(|_| ControlOwnerErrorV1::WriterUnavailable)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let metadata = writer
                .metadata()
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            if !metadata.is_file() || metadata.mode() & 0o077 != 0 || metadata.nlink() != 1 {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
        }
        if new_file {
            let header = wal_header(&cell_id, scope_digest)?;
            if writer
                .metadata()
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?
                .len()
                != 0
            {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
            writer
                .write_all(&header)
                .and_then(|()| writer.sync_all())
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            #[cfg(unix)]
            File::open(directory)
                .and_then(|parent| parent.sync_all())
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        }
        let bytes = fs::read(&path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        let (inner, head, sequence) = replay_wal(&bytes, &cell_id, scope_digest)?;
        Ok(Self {
            cell_id,
            scope_digest,
            path,
            writer,
            inner,
            head,
            sequence,
            bytes: bytes.len(),
            poisoned: false,
        })
    }

    fn apply_event(
        &mut self,
        event: ControlWalEventV1,
    ) -> Result<ControlWalOutputV1, ControlOwnerErrorV1> {
        if self.poisoned || self.sequence >= MAX_WAL_EVENTS {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let mut next = self.inner.clone();
        let output = event.apply(&mut next, &self.cell_id, self.scope_digest)?;
        if next == self.inner {
            return Ok(output);
        }
        let next_sequence = self.sequence + 1;
        let (frame, head) =
            wal_frame(next_sequence, self.head, output.digest()?, &event.encode()?)?;
        let len = self
            .bytes
            .checked_add(frame.len())
            .ok_or(ControlOwnerErrorV1::InvalidDurableSnapshot)?;
        if len > MAX_WAL_BYTES {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        // Failure after any partial append poisons this writer. It must be
        // reopened/reconciled; no automatic retry can reissue a downstream effect.
        if self
            .writer
            .write_all(&frame)
            .and_then(|()| self.writer.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(ControlOwnerErrorV1::DurableIo);
        }
        self.bytes = len;
        self.head = head;
        self.sequence = next_sequence;
        self.inner = next;
        Ok(output)
    }

    pub fn cell_id(&self) -> &StableId {
        &self.cell_id
    }

    pub fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn committed_events(&self) -> u64 {
        self.sequence
    }

    pub fn head(&self) -> Digest32 {
        self.head
    }

    pub fn dispatch_receipt(&self, id: &StableId) -> Option<&ControlDispatchReceiptV1> {
        self.inner.dispatch_receipt(id)
    }

    pub fn set_now_ms(&mut self, now: u64) -> Result<(), ControlOwnerErrorV1> {
        match self.apply_event(ControlWalEventV1::Clock(now))? {
            ControlWalOutputV1::None => Ok(()),
            _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        }
    }

    pub fn activate_generation(
        &mut self,
        generation: Generation,
        route_fence_digest: Digest32,
    ) -> Result<Digest32, ControlOwnerErrorV1> {
        match self.apply_event(ControlWalEventV1::Activate(
            self.cell_id.clone(),
            generation,
            route_fence_digest,
        ))? {
            ControlWalOutputV1::Digest(digest) => Ok(digest),
            _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        }
    }
}

impl ControlRoleOwnerV1 for ScopedControlWalOwnerV1 {
    fn prepare(
        &mut self,
        intent: ControlDispatchIntentV1,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        match self.apply_event(ControlWalEventV1::Prepare(intent))? {
            ControlWalOutputV1::Receipt(receipt) => Ok(receipt),
            _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        }
    }

    fn forward(&mut self, id: &StableId) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        match self.apply_event(ControlWalEventV1::Forward(id.clone()))? {
            ControlWalOutputV1::Receipt(receipt) => Ok(receipt),
            _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        }
    }

    fn record_terminal(
        &mut self,
        id: &StableId,
        receipt_digest: Digest32,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        match self.apply_event(ControlWalEventV1::Terminal(id.clone(), receipt_digest))? {
            ControlWalOutputV1::Receipt(receipt) => Ok(receipt),
            _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        }
    }

    fn reconcile_restart(
        &mut self,
        id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        match self.apply_event(ControlWalEventV1::Reconcile(id.clone()))? {
            ControlWalOutputV1::Receipt(receipt) => Ok(receipt),
            _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(name: &str) -> StableId {
        StableId::new(name).expect("id")
    }

    fn digest(name: &str) -> Digest32 {
        Digest32::of_bytes(name.as_bytes())
    }

    fn root() -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "hepta-control-scope-wal-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos(),
        ));
        dir
    }

    fn intent(scope: Digest32) -> ControlDispatchIntentV1 {
        ControlDispatchIntentV1 {
            dispatch_id: id("dispatch-one"),
            cell_id: id("cell-one"),
            generation: Generation::new(3).expect("generation"),
            scope_digest: scope,
            operation: ControlOperationKindV1::Router,
            request_digest: digest("request"),
            route_fence_digest: digest("fence"),
            idempotency_key_digest: digest("idempotency"),
            payload_digest: digest("payload"),
            precondition_digest: digest("precondition"),
            effect_class_digest: digest("effect-class"),
            deadline_ms: 500,
            expiry_ms: 700,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn scope_wal_reopens_exact_committed_terminal_and_rejects_second_writer() {
        let directory = root();
        let scope = digest("scope-one");
        let receipt;
        let path;
        {
            let mut owner =
                ScopedControlWalOwnerV1::open(&directory, id("cell-one"), scope).expect("open");
            path = owner.path().to_path_buf();
            assert!(matches!(
                ScopedControlWalOwnerV1::open(&directory, id("cell-one"), scope),
                Err(ControlOwnerErrorV1::WriterUnavailable)
            ));
            owner
                .activate_generation(Generation::new(3).unwrap(), digest("fence"))
                .unwrap();
            owner.set_now_ms(1).unwrap();
            let prepared = owner.prepare(intent(scope)).unwrap();
            owner.forward(&prepared.dispatch_id).unwrap();
            receipt = owner
                .record_terminal(&prepared.dispatch_id, digest("terminal"))
                .unwrap();
            assert_eq!(owner.committed_events(), 5);
        }
        let mut restored =
            ScopedControlWalOwnerV1::open(&directory, id("cell-one"), scope).expect("reopen");
        assert_eq!(
            restored.dispatch_receipt(&receipt.dispatch_id),
            Some(&receipt)
        );
        assert_eq!(
            restored
                .record_terminal(&receipt.dispatch_id, digest("terminal"))
                .unwrap(),
            receipt
        );
        assert_eq!(restored.committed_events(), 5);
        assert_eq!(
            restored
                .reconcile_restart(&receipt.dispatch_id)
                .unwrap()
                .status,
            ControlDispatchStatusV1::Reconciled
        );
        drop(restored);
        let mut bytes = fs::read(&path).unwrap();
        let tamper_at = bytes.len() / 2;
        bytes[tamper_at] ^= 1;
        fs::write(&path, bytes).unwrap();
        assert!(matches!(
            ScopedControlWalOwnerV1::open(&directory, id("cell-one"), scope),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
        ));
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn scope_wal_isolates_lanes_and_rejects_truncated_tail() {
        let directory = root();
        let first = digest("scope-one");
        let second = digest("scope-two");
        let mut lane_a = ScopedControlWalOwnerV1::open(&directory, id("cell-one"), first).unwrap();
        let mut lane_b = ScopedControlWalOwnerV1::open(&directory, id("cell-one"), second).unwrap();
        lane_a
            .activate_generation(Generation::new(3).unwrap(), digest("fence"))
            .unwrap();
        lane_b
            .activate_generation(Generation::new(3).unwrap(), digest("fence"))
            .unwrap();
        assert!(matches!(
            lane_a.prepare(intent(second)),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
        ));
        assert_eq!(lane_b.prepare(intent(second)).unwrap().sequence, 1);
        let wal = lane_b.path().to_path_buf();
        drop(lane_a);
        drop(lane_b);
        let mut append = fs::OpenOptions::new().append(true).open(&wal).unwrap();
        append.write_all(b"torn").unwrap();
        append.sync_all().unwrap();
        assert!(matches!(
            ScopedControlWalOwnerV1::open(&directory, id("cell-one"), second),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
        ));
        fs::remove_dir_all(directory).unwrap();
    }
}
