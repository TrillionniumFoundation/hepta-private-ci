//! Physical data observation of an ordinary fully witnessed Ledger.
//!
//! This is neither a learning authorization nor signature/trust verification.
//! The original Root must independently retain the cut, authorize its recipient,
//! and persist refusal before any inspection. This handle's poison alone does
//! not survive a process restart or prevent joint rollback of both input files.

use std::sync::Mutex;

use super::*;
use crate::LedgerWitnessFrontier;
use crate::witness::inspect_ordinary_witness;

#[path = "durable_read_only_file.rs"]
mod physical;

/// A data commitment to both complete files. A caller-supplied value is not
/// evidence that any independent owner retained or authorized this history.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LedgerReadOnlyCutV1 {
    pub binding: Digest32,
    pub frontier: LedgerWitnessFrontier,
    pub ledger_length: u64,
    pub ledger_digest: Digest32,
    pub witness_length: u64,
    pub witness_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerReadOnlyObservationV1 {
    pub cut: LedgerReadOnlyCutV1,
    pub snapshot: LedgerSnapshot,
}

#[derive(Clone, Copy)]
enum ExpectedCut {
    FirstObservation,
    Retained(LedgerReadOnlyCutV1),
}

struct ObservationState {
    expected: ExpectedCut,
    poisoned: bool,
}

/// Two existing O_RDONLY descriptors, locked until this view is dropped. A
/// cooperating live writer on either file refuses the observation. Independently
/// open the original descriptors: inherited, already locked aliases are unsupported.
/// No cached LedgerWriter, witness recovery, writable handle or path opener exists.
pub struct ReadOnlyLedgerViewV1 {
    ledger: physical::ReadOnlyFile,
    witness: physical::ReadOnlyFile,
    binding: Digest32,
    max_records: usize,
    state: Mutex<ObservationState>,
}

impl ReadOnlyLedgerViewV1 {
    /// Observe data after the original owners have released both writer locks.
    /// The Root capture caller must already have armed its independent refusal.
    pub fn observe_closed(
        ledger: File,
        witness: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, DurableLedgerError> {
        Self::open(
            ledger,
            witness,
            binding,
            max_records,
            ExpectedCut::FirstObservation,
        )
    }

    /// Reopen only the exact cut supplied by its separately authenticated owner.
    /// A missing, changed, lagging or unwitnessed suffix never repairs or recaptures.
    pub fn open_at_retained_cut(
        ledger: File,
        witness: File,
        binding: Digest32,
        max_records: usize,
        expected: LedgerReadOnlyCutV1,
    ) -> Result<Self, DurableLedgerError> {
        if expected.binding != binding {
            return Err(DurableLedgerError::BindingMismatch);
        }
        Self::open(
            ledger,
            witness,
            binding,
            max_records,
            ExpectedCut::Retained(expected),
        )
    }

    fn open(
        ledger: File,
        witness: File,
        binding: Digest32,
        max_records: usize,
        expected: ExpectedCut,
    ) -> Result<Self, DurableLedgerError> {
        validate_domain(binding, max_records)?;
        let ledger = physical::ReadOnlyFile::acquire(ledger, MAX_BYTES)?;
        let witness = physical::ReadOnlyFile::acquire(witness, 72 + 88 * max_records as u64)?;
        if ledger.identity() == witness.identity() {
            return Err(DurableLedgerError::BindingMismatch);
        }
        let view = Self {
            ledger,
            witness,
            binding,
            max_records,
            state: Mutex::new(ObservationState {
                expected,
                poisoned: false,
            }),
        };
        view.observe()?;
        Ok(view)
    }

    /// Re-read both complete physical images, replay the writer's canonical
    /// grammar and semantic indexes, compare the exact frontier, then re-read
    /// both images before releasing any result. All returned records are owned.
    pub fn observe(&self) -> Result<LedgerReadOnlyObservationV1, DurableLedgerError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| DurableLedgerError::Poisoned)?;
        if state.poisoned {
            return Err(DurableLedgerError::Poisoned);
        }
        state.poisoned = true;
        let ledger = self.ledger.read_image()?;
        let witness = self.witness.read_image()?;
        let frontier = inspect_ordinary_witness(&witness, self.binding, self.max_records)?;
        let recovery = LedgerRecovery::Acknowledged(frontier.anchor);
        validate_recovery(recovery, self.max_records)?;
        let (core, cursor, length) = replay_reader(
            &mut io::Cursor::new(&ledger),
            self.binding,
            self.max_records,
            recovery,
            ledger.len() as u64,
        )?;
        if cursor != length {
            return Err(DurableLedgerError::IncompleteTail);
        }
        if core.records().len() as u64 != frontier.anchor.sequence {
            return Err(DurableLedgerError::UnwitnessedTail);
        }
        let cut = LedgerReadOnlyCutV1 {
            binding: self.binding,
            frontier,
            ledger_length: ledger.len() as u64,
            ledger_digest: Digest32::of_bytes(&ledger),
            witness_length: witness.len() as u64,
            witness_digest: Digest32::of_bytes(&witness),
        };
        if let ExpectedCut::Retained(expected) = state.expected
            && expected != cut
        {
            return Err(DurableLedgerError::AnchorMismatch);
        }
        let snapshot = core.snapshot();
        if self.ledger.read_image()? != ledger || self.witness.read_image()? != witness {
            return Err(DurableLedgerError::Indeterminate);
        }
        state.expected = ExpectedCut::Retained(cut);
        state.poisoned = false;
        Ok(LedgerReadOnlyObservationV1 { cut, snapshot })
    }
}
