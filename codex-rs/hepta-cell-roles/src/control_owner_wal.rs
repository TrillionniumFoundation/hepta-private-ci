//! Opt-in append-only control-role owner for bounded, constant-size hot writes.
//!
//! This is a SOURCE qualification path, not an attested production witness.
//! It never silently upgrades V1 snapshot bytes, invents downstream terminal
//! receipts, or treats a local hash chain as an independent anti-rollback oracle.

use super::*;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

const MAGIC: &[u8] = b"HEPTA-CONTROL-WAL-V2\0";
const MAX_WAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_FRAME_BYTES: usize = 32 * 1024;

#[derive(Clone, Debug)]
enum Event {
    Clock(u64),
    Generation(StableId, Generation, Digest32),
    Prepare(ControlDispatchIntentV1),
    Forward(StableId),
    Terminal(StableId, Digest32),
    Reconcile(StableId),
}

impl Event {
    /// Construct only the records/fences needed to evaluate this event.
    /// The canonical in-memory state machine remains the validation oracle,
    /// but validation no longer clones up to 65,536 unrelated dispatches.
    fn local_preview(&self, owner: &InMemoryControlRoleOwnerV1) -> InMemoryControlRoleOwnerV1 {
        let mut preview = InMemoryControlRoleOwnerV1 {
            next_sequence: owner.next_sequence,
            now_ms: owner.now_ms,
            ..InMemoryControlRoleOwnerV1::default()
        };
        match self {
            Self::Clock(_) => {}
            Self::Generation(cell_id, _, _) => {
                if let Some(binding) = owner.active_generations.get(cell_id) {
                    preview.active_generations.insert(cell_id.clone(), *binding);
                }
            }
            Self::Prepare(intent) => {
                if let Some(record) = owner.records.get(&intent.dispatch_id) {
                    preview.records.insert(intent.dispatch_id.clone(), record.clone());
                }
                if let Some(id) = owner.idempotency_index.get(&intent.idempotency_key_digest) {
                    preview
                        .idempotency_index
                        .insert(intent.idempotency_key_digest, id.clone());
                }
                if let Some(binding) = owner.active_generations.get(&intent.cell_id) {
                    preview.active_generations.insert(intent.cell_id.clone(), *binding);
                }
            }
            Self::Forward(dispatch_id)
            | Self::Terminal(dispatch_id, _)
            | Self::Reconcile(dispatch_id) => {
                if let Some(record) = owner.records.get(dispatch_id) {
                    if let Some(binding) = owner.active_generations.get(&record.intent.cell_id) {
                        preview
                            .active_generations
                            .insert(record.intent.cell_id.clone(), *binding);
                    }
                    preview.records.insert(dispatch_id.clone(), record.clone());
                }
            }
        }
        preview
    }

    fn encode(&self) -> Result<Vec<u8>, ControlOwnerErrorV1> {
        let mut bytes = Vec::new();
        match self {
            Self::Clock(now) => {
                bytes.push(1);
                put_u64(&mut bytes, *now);
            }
            Self::Generation(id, generation, fence) => {
                bytes.push(2);
                put_id(&mut bytes, id)?;
                put_u64(&mut bytes, generation.get());
                put_digest(&mut bytes, *fence);
            }
            Self::Prepare(intent) => {
                bytes.push(3);
                encode_intent(&mut bytes, intent)?;
            }
            Self::Forward(id) => {
                bytes.push(4);
                put_id(&mut bytes, id)?;
            }
            Self::Terminal(id, receipt) => {
                bytes.push(5);
                put_id(&mut bytes, id)?;
                put_digest(&mut bytes, *receipt);
            }
            Self::Reconcile(id) => {
                bytes.push(6);
                put_id(&mut bytes, id)?;
            }
        }
        if bytes.len() > MAX_FRAME_BYTES {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        Ok(bytes)
    }

    fn decode(bytes: &[u8]) -> Result<Self, ControlOwnerErrorV1> {
        let mut input = ControlCursor::new(bytes);
        let event = match input.byte()? {
            1 => Self::Clock(input.u64()?),
            2 => Self::Generation(
                input.id()?,
                Generation::new(input.u64()?)
                    .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?,
                input.digest()?,
            ),
            3 => Self::Prepare(decode_intent(&mut input)?),
            4 => Self::Forward(input.id()?),
            5 => Self::Terminal(input.id()?, input.digest()?),
            6 => Self::Reconcile(input.id()?),
            _ => return Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
        };
        if !input.is_empty() {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        Ok(event)
    }

    fn apply(
        &self,
        owner: &mut InMemoryControlRoleOwnerV1,
    ) -> Result<Digest32, ControlOwnerErrorV1> {
        match self {
            Self::Clock(now) => {
                if *now < owner.now_ms {
                    return Err(ControlOwnerErrorV1::ClockRegressed);
                }
                owner.set_now_ms(*now);
                Ok(digest_bytes(
                    b"hepta.cell-role.wal-clock.v2",
                    &[&now.to_be_bytes()],
                ))
            }
            Self::Generation(id, generation, fence) => {
                owner.activate_generation(id.clone(), *generation, *fence)
            }
            Self::Prepare(intent) => owner.prepare(intent.clone())?.content_digest(),
            Self::Forward(id) => owner.forward(id)?.content_digest(),
            Self::Terminal(id, digest) => owner.record_terminal(id, *digest)?.content_digest(),
            Self::Reconcile(id) => owner.reconcile_restart(id)?.content_digest(),
        }
    }
}

fn event_head(
    previous: Digest32,
    sequence: u64,
    event: &[u8],
    output: Digest32,
) -> Digest32 {
    digest_bytes(
        b"hepta.cell-role.control-wal-v2.chain",
        &[
            previous.as_array(),
            &sequence.to_be_bytes(),
            event,
            output.as_array(),
        ],
    )
}

/// A single-owner V2 write path. WAL frames contain one state transition,
/// not the growing snapshot. A failed/unknown append poisons the instance.
/// It must not be promoted without an independent retained witness or a
/// qualified checkpoint/compaction migration protocol.
#[derive(Debug)]
pub struct IncrementalControlRoleWalV2 {
    path: PathBuf,
    inner: InMemoryControlRoleOwnerV1,
    sequence: u64,
    head: Digest32,
    size: u64,
    poisoned: bool,
}

impl IncrementalControlRoleWalV2 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ControlOwnerErrorV1> {
        let path = path.as_ref().to_path_buf();
        reject_durable_path(&path)?;
        let _lock = lock_durable_control_writer(&path)?;
        if !path.exists() {
            let mut options = fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options
                .open(&path)
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            file.write_all(MAGIC)
                .and_then(|()| file.sync_all())
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            #[cfg(unix)]
            sync_control_directory(&path)?;
        }
        require_private_wal(&path)?;
        let bytes = fs::read(&path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        if bytes.len() as u64 > MAX_WAL_BYTES || !bytes.starts_with(MAGIC) {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let mut cursor = ControlCursor::new(&bytes[MAGIC.len()..]);
        let mut owner = InMemoryControlRoleOwnerV1::default();
        let mut head = Digest32::ZERO;
        let mut sequence = 0_u64;
        while !cursor.is_empty() {
            let frame_size = cursor.u32()? as usize;
            if !(8 + 32 + 4 + 32 + 32..=MAX_FRAME_BYTES).contains(&frame_size) {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
            let mut frame = ControlCursor::new(cursor.take(frame_size)?);
            let incoming_sequence = frame.u64()?;
            let incoming_head = frame.digest()?;
            let payload_size = frame.u32()? as usize;
            if payload_size > MAX_FRAME_BYTES {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
            let payload = frame.take(payload_size)?;
            let expected_output = frame.digest()?;
            let next_head = frame.digest()?;
            if !frame.is_empty()
                || incoming_sequence != sequence.saturating_add(1)
                || incoming_head != head
                || next_head != event_head(head, incoming_sequence, payload, expected_output)
            {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
            let event = Event::decode(payload)?;
            if event.apply(&mut owner).map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?
                != expected_output
            {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
            if owner.records.len() > DURABLE_CONTROL_MAX_RECORDS_V1 {
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
            head = next_head;
            sequence = incoming_sequence;
        }
        Ok(Self {
            path,
            inner: owner,
            sequence,
            head,
            size: bytes.len() as u64,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn inner(&self) -> &InMemoryControlRoleOwnerV1 {
        &self.inner
    }

    #[must_use]
    pub const fn committed_operations(&self) -> u64 {
        self.sequence
    }

    #[must_use]
    pub const fn committed_head(&self) -> Digest32 {
        self.head
    }

    fn commit(&mut self, operation: Event) -> Result<Digest32, ControlOwnerErrorV1> {
        if self.poisoned {
            return Err(ControlOwnerErrorV1::WriterUnavailable);
        }
        // Successor validation and operation encoding happen outside the OS
        // writer lock; only the bounded append/fsync owns that lock.
        let baseline = operation.local_preview(&self.inner);
        let mut successor = baseline.clone();
        let result = operation.apply(&mut successor)?;
        if self.inner.records.len() > DURABLE_CONTROL_MAX_RECORDS_V1
            || (successor.records.len() > baseline.records.len()
                && self.inner.records.len() >= DURABLE_CONTROL_MAX_RECORDS_V1)
        {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let changed = successor != baseline;
        let payload = operation.encode()?;
        let _lock = lock_durable_control_writer(&self.path)?;
        reject_durable_path(&self.path)?;
        require_private_wal(&self.path)?;
        let mut file = fs::OpenOptions::new()
            .read(true)
            .append(true)
            .open(&self.path)
            .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        if file.metadata().map_err(|_| ControlOwnerErrorV1::DurableIo)?.len() != self.size {
            return Err(ControlOwnerErrorV1::StaleWriter);
        }
        if self.sequence == 0 {
            let mut observed = vec![0_u8; MAGIC.len()];
            file.read_exact(&mut observed)
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            if observed != MAGIC {
                return Err(ControlOwnerErrorV1::StaleWriter);
            }
        } else {
            let mut tail = [0_u8; 32];
            file.seek(SeekFrom::End(-32))
                .and_then(|_| file.read_exact(&mut tail))
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            if tail != *self.head.as_array() {
                return Err(ControlOwnerErrorV1::StaleWriter);
            }
        }
        if !changed {
            return Ok(result);
        }
        let next_sequence = self
            .sequence
            .checked_add(1)
            .ok_or(ControlOwnerErrorV1::InvalidDurableSnapshot)?;
        let next_head = event_head(self.head, next_sequence, &payload, result);
        let mut frame = Vec::with_capacity(8 + 32 + 4 + payload.len() + 64);
        put_u64(&mut frame, next_sequence);
        put_digest(&mut frame, self.head);
        put_u32(&mut frame, payload.len())?;
        frame.extend_from_slice(&payload);
        put_digest(&mut frame, result);
        put_digest(&mut frame, next_head);
        if frame.len() > MAX_FRAME_BYTES {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let next_size = self
            .size
            .checked_add(4 + frame.len() as u64)
            .ok_or(ControlOwnerErrorV1::InvalidDurableSnapshot)?;
        if next_size > MAX_WAL_BYTES {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        if file.write_all(&(frame.len() as u32).to_be_bytes())
            .and_then(|()| file.write_all(&frame))
            .and_then(|()| file.sync_all())
            .is_err()
        {
            // On partial or uncertain writes, neither rollback nor retry is
            // safe without reopening and reconciling the durable prefix.
            self.poisoned = true;
            return Err(ControlOwnerErrorV1::DurableIo);
        }
        // The full owner is mutated only after the WAL fsync succeeds.
        // Preview and committed application use the same checked state machine.
        // If this replay can no longer agree, fence the writer for inspection.
        match operation.apply(&mut self.inner) {
            Ok(committed) if committed == result => {}
            _ => {
                self.poisoned = true;
                return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
            }
        }
        self.sequence = next_sequence;
        self.head = next_head;
        self.size = next_size;
        Ok(result)
    }

    pub fn set_now_ms(&mut self, now_ms: u64) -> Result<(), ControlOwnerErrorV1> {
        self.commit(Event::Clock(now_ms))?;
        Ok(())
    }

    pub fn activate_generation(
        &mut self,
        cell_id: StableId,
        generation: Generation,
        fence: Digest32,
    ) -> Result<Digest32, ControlOwnerErrorV1> {
        self.commit(Event::Generation(cell_id, generation, fence))
    }
}

impl ControlRoleOwnerV1 for IncrementalControlRoleWalV2 {
    fn prepare(
        &mut self,
        intent: ControlDispatchIntentV1,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        let id = intent.dispatch_id.clone();
        self.commit(Event::Prepare(intent))?;
        self.inner.dispatch_receipt(&id).cloned().ok_or(ControlOwnerErrorV1::MissingDispatch)
    }

    fn forward(
        &mut self,
        id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        self.commit(Event::Forward(id.clone()))?;
        self.inner.dispatch_receipt(id).cloned().ok_or(ControlOwnerErrorV1::MissingDispatch)
    }

    fn record_terminal(
        &mut self,
        id: &StableId,
        digest: Digest32,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        self.commit(Event::Terminal(id.clone(), digest))?;
        self.inner.dispatch_receipt(id).cloned().ok_or(ControlOwnerErrorV1::MissingDispatch)
    }

    fn reconcile_restart(
        &mut self,
        id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        self.commit(Event::Reconcile(id.clone()))?;
        self.inner.dispatch_receipt(id).cloned().ok_or(ControlOwnerErrorV1::MissingDispatch)
    }
}

#[cfg(unix)]
fn require_private_wal(path: &Path) -> Result<(), ControlOwnerErrorV1> {
    use std::os::unix::fs::MetadataExt;
    let metadata = fs::symlink_metadata(path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() & 0o077 != 0 {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    Ok(())
}

#[cfg(not(unix))]
fn require_private_wal(path: &Path) -> Result<(), ControlOwnerErrorV1> {
    reject_durable_path(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }
    fn path() -> PathBuf {
        let name = format!(
            "hepta-incremental-wal-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        );
        std::env::temp_dir().join(name)
    }
    fn request(name: &str) -> ControlDispatchIntentV1 {
        ControlDispatchIntentV1 {
            dispatch_id: StableId::new(name).expect("dispatch"),
            cell_id: StableId::new("cell.control").expect("cell"),
            generation: Generation::new(3).expect("generation"),
            scope_digest: digest("scope"),
            operation: ControlOperationKindV1::Router,
            request_digest: digest(name),
            route_fence_digest: digest("fence"),
            idempotency_key_digest: digest(name),
            payload_digest: digest("payload"),
            precondition_digest: digest("precondition"),
            effect_class_digest: digest("effect"),
            deadline_ms: 10,
            expiry_ms: 500,
            authority: AuthorityPosture::DENY_ALL,
        }
    }
    #[test]
    fn local_preview_is_independent_of_unrelated_dispatch_history() {
        let mut owner = InMemoryControlRoleOwnerV1::default();
        owner.set_now_ms(20);
        owner
            .activate_generation(
                StableId::new("cell.control").expect("cell"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("binding");
        for n in 0..4096 {
            owner
                .prepare(request(&format!("historical-{n}")))
                .expect("historical admission");
        }
        let next = Event::Prepare(request("next"));
        let preview = next.local_preview(&owner);
        assert_eq!(owner.records.len(), 4096);
        assert!(preview.records.is_empty());
        assert!(preview.idempotency_index.is_empty());
        assert_eq!(preview.active_generations.len(), 1);
        assert_eq!(preview.next_sequence, owner.next_sequence);
        let mut shadow = preview;
        let expected = next.apply(&mut shadow).expect("preview receipt");
        let actual = next.apply(&mut owner).expect("full oracle receipt");
        assert_eq!(expected, actual);
        assert_eq!(owner.records.len(), 4097);
        let retry = Event::Prepare(request("historical-1"));
        let retry_preview = retry.local_preview(&owner);
        assert_eq!(retry_preview.records.len(), 1);
        assert_eq!(retry_preview.idempotency_index.len(), 1);
        assert_eq!(
            retry.apply(&mut retry_preview.clone()).expect("preview retry"),
            retry.apply(&mut owner).expect("full retry")
        );
    }

    #[test]
    fn append_reopen_terminal_reconcile_and_stale_writer_are_fenced() {
        let path = path();
        let mut writer = IncrementalControlRoleWalV2::open(&path).expect("writer");
        let mut stale = IncrementalControlRoleWalV2::open(&path).expect("other reader");
        writer.set_now_ms(20).expect("clock");
        writer
            .activate_generation(
                StableId::new("cell.control").expect("cell"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("generation");
        assert_eq!(stale.set_now_ms(20), Err(ControlOwnerErrorV1::StaleWriter));
        let prepared = writer.prepare(request("first")).expect("prepare");
        writer.forward(&prepared.dispatch_id).expect("forward");
        writer
            .record_terminal(&prepared.dispatch_id, digest("terminal"))
            .expect("terminal");
        drop(writer);
        let mut reopened = IncrementalControlRoleWalV2::open(&path).expect("recover");
        assert_eq!(reopened.committed_operations(), 5);
        assert_eq!(
            reopened.inner().dispatch_receipt(&prepared.dispatch_id).expect("receipt").status,
            ControlDispatchStatusV1::Terminal
        );
        reopened.reconcile_restart(&prepared.dispatch_id).expect("reconcile");
        let before = fs::read(&path).expect("saved log");
        reopened.reconcile_restart(&prepared.dispatch_id).expect("idempotent");
        assert_eq!(fs::read(&path).expect("same log"), before);
        fs::remove_file(&path).expect("remove log");
        fs::remove_file(path.with_extension("control.writer.lock")).expect("remove lock");
    }
    #[test]
    fn invalid_route_fence_and_conflicting_key_do_not_append_events() {
        let path = path();
        let mut owner = IncrementalControlRoleWalV2::open(&path).expect("owner");
        owner.set_now_ms(20).expect("clock");
        owner
            .activate_generation(
                StableId::new("cell.control").expect("cell"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("binding");
        let saved = fs::read(&path).expect("before rejection");
        let mut wrong = request("invalid");
        wrong.route_fence_digest = digest("stale-fence");
        assert_eq!(
            owner.prepare(wrong),
            Err(ControlOwnerErrorV1::RouteFenceMismatch)
        );
        assert_eq!(fs::read(&path).expect("unchanged after rejection"), saved);
        assert_eq!(owner.committed_operations(), 2);

        owner.prepare(request("valid")).expect("valid");
        let saved = fs::read(&path).expect("before key conflict");
        let mut duplicate_key = request("different-dispatch");
        duplicate_key.idempotency_key_digest = digest("valid");
        assert_eq!(
            owner.prepare(duplicate_key),
            Err(ControlOwnerErrorV1::IdempotencyKeyConflict)
        );
        assert_eq!(fs::read(&path).expect("unchanged after conflict"), saved);
        assert_eq!(owner.committed_operations(), 3);
        drop(owner);
        fs::remove_file(&path).expect("remove WAL");
        fs::remove_file(path.with_extension("control.writer.lock")).expect("remove lock");
    }

    #[test]
    fn partial_wal_frame_is_not_a_recoverable_commit() {
        let path = path();
        let mut owner = IncrementalControlRoleWalV2::open(&path).expect("owner");
        owner.set_now_ms(20).expect("commit");
        drop(owner);
        let previous = fs::read(&path).expect("committed bytes");
        let mut corrupt = fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .expect("raw crash fixture");
        corrupt.write_all(&[0, 0, 0, 100, 42]).expect("partial frame");
        corrupt.sync_all().expect("persist torn tail");
        drop(corrupt);
        assert!(matches!(
            IncrementalControlRoleWalV2::open(&path),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
        ));
        assert_eq!(
            fs::read(&path).expect("rejected tail").len(),
            previous.len() + 5
        );
        fs::remove_file(&path).expect("remove");
        fs::remove_file(path.with_extension("control.writer.lock")).expect("remove lock");
    }

    #[test]
    fn wal_rejects_legacy_snapshot_without_rewriting_its_bytes() {
        let path = path();
        let mut legacy = DurableControlRoleOwnerV1::open(&path).expect("legacy owner");
        legacy.set_now_ms(20).expect("legacy clock");
        let before = fs::read(&path).expect("v1 snapshot");
        drop(legacy);
        assert!(matches!(
            IncrementalControlRoleWalV2::open(&path),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
        ));
        assert_eq!(fs::read(&path).expect("unchanged v1"), before);
        assert_eq!(
            DurableControlRoleOwnerV1::open(&path)
                .expect("v1 remains readable")
                .inner()
                .now_ms,
            20
        );
        fs::remove_file(&path).expect("remove old snapshot");
        fs::remove_file(path.with_extension("control.writer.lock")).expect("remove lock");
    }

    #[test]
    fn wal_exit_child_fixture() {
        let Some(path) = std::env::var_os("HEPTA_CONTROL_WAL_EXIT_PATH") else {
            return;
        };
        let mut owner = IncrementalControlRoleWalV2::open(PathBuf::from(path))
            .expect("isolated child owner");
        owner.set_now_ms(20).expect("committed clock");
        // process::exit skips Drop; it is a process-crash fixture, NOT a
        // physical power-loss or an independent durability attestation.
        std::process::exit(92);
    }

    #[test]
    fn wal_restarts_in_clean_process_after_committed_event() {
        let path = path();
        let status = std::process::Command::new(std::env::current_exe().expect("test binary"))
            .arg("--exact")
            .arg("control_owner::wal::tests::wal_exit_child_fixture")
            .env("HEPTA_CONTROL_WAL_EXIT_PATH", &path)
            .status()
            .expect("child process");
        assert_eq!(status.code(), Some(92));
        let mut reopened = IncrementalControlRoleWalV2::open(&path).expect("reopen");
        assert_eq!(reopened.committed_operations(), 1);
        reopened.set_now_ms(21).expect("post-restart monotonic clock");
        assert_eq!(reopened.committed_operations(), 2);
        drop(reopened);
        fs::remove_file(&path).expect("remove log");
        fs::remove_file(path.with_extension("control.writer.lock")).expect("remove lock");
    }

    #[test]
    fn log_frames_are_bounded_and_corruption_refuses_reopen() {
        let path = path();
        let mut writer = IncrementalControlRoleWalV2::open(&path).expect("writer");
        writer.set_now_ms(20).expect("clock");
        writer
            .activate_generation(
                StableId::new("cell.control").expect("cell"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("generation");
        let mut sizes = Vec::new();
        for n in 0..24 {
            let before = fs::metadata(&path).expect("file").len();
            writer.prepare(request(&format!("operation-{n}"))).expect("prepare");
            sizes.push(fs::metadata(&path).expect("file").len() - before);
        }
        assert!(sizes.iter().all(|size| *size > 0 && *size < 1024));
        drop(writer);
        assert_eq!(
            IncrementalControlRoleWalV2::open(&path).expect("reopen").committed_operations(),
            26
        );
        let mut contents = fs::read(&path).expect("read");
        let last = contents.len() - 1;
        contents[last] ^= 0x80;
        fs::write(&path, contents).expect("tamper");
        assert!(matches!(
            IncrementalControlRoleWalV2::open(&path),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
        ));
        fs::remove_file(&path).expect("remove");
        fs::remove_file(path.with_extension("control.writer.lock")).expect("remove lock");
    }
}
