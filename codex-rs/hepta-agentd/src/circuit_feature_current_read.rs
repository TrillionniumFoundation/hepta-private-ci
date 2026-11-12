//! One synchronous original Published read, with the actual CURRENT checks in
//! its first and last original slots. All Source, Version and Cell reads still
//! run in between. This borrowed state is not a transferable Current receipt.

use std::marker::PhantomData;
use std::mem;
use std::rc::Rc;
use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;

use super::PublishedCircuitCellOwnerV1;
use super::invalid;
use crate::AgentdError;

pub(super) enum OriginalPublishedReadPurpose {
    Selection,
    NextUse,
}

impl OriginalPublishedReadPurpose {
    fn slots(&self) -> u8 {
        match self {
            Self::Selection => 6,
            Self::NextUse => 9,
        }
    }
}

enum State {
    Individual,
    BeforePurpose {
        slots: u8,
    },
    Reading {
        purpose: OriginalPublishedReadPurpose,
        slots: u8,
    },
    Complete,
    Refused,
}

/// Holds the actual original Cell and Task allocations alive for one stack
/// call. It cannot be cloned, serialized, sent to another lane, or saved by a
/// receipt owner. The wire response contains only the usual original read.
pub(super) struct OriginalPublishedReadCurrent<'a, W: AnchorWitnessStore> {
    original: &'a PublishedCircuitCellOwnerV1<W>,
    state: State,
    _single_thread: PhantomData<Rc<()>>,
}

impl<'a, W: AnchorWitnessStore> OriginalPublishedReadCurrent<'a, W> {
    /// Every existing public Cell entry keeps every physical CURRENT read.
    pub(super) fn individual(original: &'a PublishedCircuitCellOwnerV1<W>) -> Self {
        Self {
            original,
            state: State::Individual,
            _single_thread: PhantomData,
        }
    }

    /// Only the actual read service starts this private, synchronous call.
    /// No current fact is minted until its first original require slot runs.
    pub(super) fn for_original_read(original: &'a PublishedCircuitCellOwnerV1<W>) -> Self {
        Self {
            original,
            state: State::BeforePurpose { slots: 0 },
            _single_thread: PhantomData,
        }
    }

    /// The original authenticated mode fixes the path after the first actual
    /// CURRENT and Source input reads, before its native Selection/NextUse read.
    /// It fixes the remaining exact path; it cannot reset or extend a call.
    pub(super) fn select_purpose(
        &mut self,
        purpose: OriginalPublishedReadPurpose,
    ) -> Result<(), AgentdError> {
        let prior = mem::replace(&mut self.state, State::Refused);
        match prior {
            State::BeforePurpose { slots: 1 } => {
                self.state = State::Reading { purpose, slots: 1 };
                Ok(())
            }
            State::Individual
            | State::BeforePurpose { .. }
            | State::Reading { .. }
            | State::Complete
            | State::Refused => Err(invalid("original published read purpose order")),
        }
    }

    /// Retain the precise old slot at every nested call site. In the single
    /// read, slot 1 and slot 6/9 perform the original full CURRENT I/O; the
    /// intervening slots require the same still-borrowed original allocations.
    pub(super) fn require(
        &mut self,
        cell: &PublishedCircuitCellOwnerV1<W>,
    ) -> Result<(), AgentdError> {
        let prior = mem::replace(&mut self.state, State::Refused);
        if !Arc::ptr_eq(&self.original.original, &cell.original)
            || !Arc::ptr_eq(&self.original.task.0, &cell.task.0)
        {
            return Err(invalid("same original published Cell and Task read"));
        }
        match prior {
            State::Individual => {
                cell.task.require_current()?;
                self.state = State::Individual;
            }
            State::BeforePurpose { slots } => {
                if slots >= 1 {
                    return Err(invalid("original published read purpose is required"));
                }
                if slots == 0 {
                    cell.task.require_current()?;
                }
                self.state = State::BeforePurpose { slots: slots + 1 };
            }
            State::Reading { purpose, slots } => {
                if !(1..purpose.slots()).contains(&slots) {
                    return Err(invalid("original published read slot bound"));
                }
                let slots = slots + 1;
                if slots == purpose.slots() {
                    cell.task.require_current()?;
                    self.state = State::Complete;
                } else {
                    self.state = State::Reading { purpose, slots };
                }
            }
            State::Complete | State::Refused => {
                return Err(invalid("original published read cannot be reused"));
            }
        }
        Ok(())
    }

    /// Consume the call only after its final physical CURRENT read succeeded.
    /// An error, extra slot or partial path cannot return an original response.
    pub(super) fn finish(self) -> Result<(), AgentdError> {
        if !matches!(self.state, State::Complete) {
            return Err(invalid("original published read did not complete"));
        }
        Ok(())
    }
}
