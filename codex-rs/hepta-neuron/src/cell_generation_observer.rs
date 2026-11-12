//! Actual read-only descriptors for one original guarded journal and its
//! independent physical witness. A snapshot supplied by a caller is not a cut.

use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;

use codex_hepta_types::Generation;

use super::*;
use crate::JournalScope;

/// Immutable original configuration and independent witness context.
#[derive(Clone, Debug)]
pub struct CellGenerationObserverConfigV1 {
    pub generation: CellGenerationConfigV2,
    pub journal_records: u64,
    pub witness_scope: JournalScope,
    pub witness_generation: Generation,
    pub witness_records: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct FilePin {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

impl FilePin {
    fn read(file: &File) -> Result<Self, CellGenerationErrorV2> {
        let metadata = file.metadata().map_err(unavailable)?;
        if !metadata.is_file() || metadata.nlink() != 1 {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
        })
    }

    fn bytes(&self) -> Vec<u8> {
        [
            self.device.to_be_bytes().as_slice(),
            self.inode.to_be_bytes().as_slice(),
            self.uid.to_be_bytes().as_slice(),
            self.gid.to_be_bytes().as_slice(),
            self.mode.to_be_bytes().as_slice(),
        ]
        .concat()
    }
}

/// No lock, writable descriptor, CURRENT or dispatch authority is exported.
pub struct CellGenerationJournalObserverV1 {
    journal: File,
    witness: File,
    journal_pin: FilePin,
    witness_pin: FilePin,
    config: CellGenerationObserverConfigV1,
    binding: CellGenerationOwnerBindingV1,
    header: Vec<u8>,
}

/// An observed complete physical cut. There is no public constructor or
/// deserializer. This value alone grants no publication or execution right.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationJournalObservedV1 {
    binding: CellGenerationOwnerBindingV1,
    observation: CellGenerationObservationV1,
    drained: bool,
    genesis: bool,
}

impl CellGenerationJournalObservedV1 {
    pub fn owner_binding(&self) -> &CellGenerationOwnerBindingV1 {
        &self.binding
    }
    pub fn observation(&self) -> &CellGenerationObservationV1 {
        &self.observation
    }
    pub fn is_drained(&self) -> bool {
        self.drained
    }
    pub fn is_genesis(&self) -> bool {
        self.genesis
    }
}

impl CellGenerationJournalObserverV1 {
    /// Reopen the supplied original inode read-only without borrowing its
    /// open-file-description lock. An empty future target is only pinned here.
    pub fn from_original_files(
        journal: File,
        witness: File,
        config: CellGenerationObserverConfigV1,
    ) -> Result<Self, CellGenerationErrorV2> {
        let binding =
            CellGenerationOwnerBindingV1::new(&config.generation, config.journal_records)?;
        if !(1..=4096).contains(&config.witness_records)
            || config.witness_scope.scope_digest.is_zero()
            || config.witness_scope.objective_digest.is_zero()
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let (journal, journal_pin) = readonly(journal)?;
        let (witness, witness_pin) = readonly(witness)?;
        if (journal_pin.device, journal_pin.inode) == (witness_pin.device, witness_pin.inode) {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(Self {
            journal,
            witness,
            journal_pin,
            witness_pin,
            config,
            header: binding.header(),
            binding,
        })
    }

    pub fn owner_binding(&self) -> &CellGenerationOwnerBindingV1 {
        &self.binding
    }

    pub fn files_binding(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell.generation-original-observer.v1\0",
            &self.journal_pin.bytes(),
            &self.witness_pin.bytes(),
        ])
    }

    /// A fresh initial reservation requires the same original unwritten file
    /// and initialized empty witness. This read never creates genesis.
    pub fn require_original_unwritten(&self) -> Result<(), CellGenerationErrorV2> {
        let before = self.stamps()?;
        if before.0.0 != 0 || self.witness_head()?.is_some() || self.stamps()? != before {
            return Err(CellGenerationErrorV2::Pending);
        }
        Ok(())
    }

    /// Before preparation the original target may still be empty. A real
    /// initialized witness with no acknowledged frame is nevertheless required.
    /// This method writes no genesis and must never substitute for publish.
    pub fn require_original_unwritten_or_genesis(&self) -> Result<(), CellGenerationErrorV2> {
        let before = self.stamps()?;
        if before.0.0 == 0 {
            if self.witness_head()?.is_some() || self.stamps()? != before {
                return Err(CellGenerationErrorV2::Pending);
            }
            return Ok(());
        }
        if !self.observe()?.is_genesis() {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(())
    }

    pub fn observe(&self) -> Result<CellGenerationJournalObservedV1, CellGenerationErrorV2> {
        let before = self.stamps()?;
        let length = before.0.0;
        if !(HEADER_BYTES as u64..=MAX_BYTES).contains(&length) {
            return Err(CellGenerationErrorV2::Corrupt);
        }
        let expected = self.witness_head()?;
        let mut bytes = vec![0; length as usize];
        self.journal
            .read_exact_at(&mut bytes, 0)
            .map_err(unavailable)?;
        let header = &self.header;
        if &bytes[..HEADER_BYTES] != header.as_slice() {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let mut state = GenerationState::new(&self.config.generation)?;
        let mut head = None;
        let mut offset = HEADER_BYTES;
        while offset < bytes.len() {
            if bytes.len() - offset < 4 {
                return Err(CellGenerationErrorV2::Pending);
            }
            let size = u32::from_be_bytes(
                bytes[offset..offset + 4]
                    .try_into()
                    .map_err(|_| CellGenerationErrorV2::Corrupt)?,
            ) as usize;
            if size == 0 || size > MAX_FRAME {
                return Err(CellGenerationErrorV2::Corrupt);
            }
            let end = offset
                .checked_add(size + 36)
                .ok_or(CellGenerationErrorV2::Capacity)?;
            if end > bytes.len() {
                return Err(CellGenerationErrorV2::Pending);
            }
            let payload = &bytes[offset + 4..end - 32];
            let next = next_anchor(header, head, payload)?;
            if next.sequence > self.config.journal_records
                || next.checkpoint_digest.as_array() != &bytes[end - 32..end]
            {
                return Err(CellGenerationErrorV2::Corrupt);
            }
            let event: GenerationEvent =
                serde_json::from_slice(payload).map_err(|_| CellGenerationErrorV2::Corrupt)?;
            if serde_json::to_vec(&event).map_err(|_| CellGenerationErrorV2::Corrupt)? != payload {
                return Err(CellGenerationErrorV2::Corrupt);
            }
            state.apply(&self.config.generation, &event)?;
            head = Some(next);
            offset = end;
        }
        if head != expected {
            return Err(CellGenerationErrorV2::AcknowledgedHistoryMissing);
        }
        let observation = CellGenerationObservationV1::capture(
            &self.config.generation,
            &state,
            continuity_checkpoint(header, head, length),
        )?;
        if self.witness_head()? != expected || self.stamps()? != before {
            return Err(CellGenerationErrorV2::Pending);
        }
        Ok(CellGenerationJournalObservedV1 {
            binding: self.binding.clone(),
            observation,
            drained: state.draining && state.pending.is_none() && state.outbox.is_none(),
            genesis: head.is_none() && length == HEADER_BYTES as u64,
        })
    }

    fn witness_head(&self) -> Result<Option<JournalAnchor>, CellGenerationErrorV2> {
        crate::witness::read_original_file(
            &self.witness,
            self.config.witness_scope,
            self.config.witness_generation,
            self.config.witness_records,
        )
        .map_err(|_| CellGenerationErrorV2::Unavailable)
    }

    fn stamps(&self) -> Result<(Stamp, Stamp), CellGenerationErrorV2> {
        if FilePin::read(&self.journal)? != self.journal_pin
            || FilePin::read(&self.witness)? != self.witness_pin
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok((stamp(&self.journal)?, stamp(&self.witness)?))
    }
}

type Stamp = (u64, i64, i64, i64, i64);

fn stamp(file: &File) -> Result<Stamp, CellGenerationErrorV2> {
    let metadata = file.metadata().map_err(unavailable)?;
    Ok((
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    ))
}

fn readonly(original: File) -> Result<(File, FilePin), CellGenerationErrorV2> {
    let pin = FilePin::read(&original)?;
    let file =
        File::open(format!("/proc/self/fd/{}", original.as_raw_fd())).map_err(unavailable)?;
    if FilePin::read(&file)? != pin || FilePin::read(&original)? != pin {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok((file, pin))
}

fn unavailable(_: std::io::Error) -> CellGenerationErrorV2 {
    CellGenerationErrorV2::Unavailable
}

#[path = "cell_generation_unpublished_observer.rs"]
mod unpublished;
pub use unpublished::CellGenerationUnpublishedObserverV1;
