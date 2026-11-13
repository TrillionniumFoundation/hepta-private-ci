//! A purpose-fixed same-host predecessor for the actual original Selector.
//! Construction borrows no caller-supplied receipt, owner callback or socket.
//! All aliases retain one original owner, one permit and one bounded read slot.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_neuron::AnchorWitnessStore;
use tokio::sync::OwnedSemaphorePermit;

use super::Error;
use super::OriginalCircuitSelectionCommandOwnerV1;
use super::OriginalPredecessors;
use super::now;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;

/// Private type erasure for the same concrete original Selector command owner.
/// Only this module implements the adapter; no external implementation or
/// caller-supplied callback is accepted as an original predecessor capability.
trait OriginalSelectionOwner: Send + Sync {
    fn read_original_receipt(&self) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error>;
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalSelectionOwner
    for OriginalCircuitSelectionCommandOwnerV1<W>
{
    fn read_original_receipt(&self) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        OriginalCircuitSelectionCommandOwnerV1::read_original_evaluated_receipt_on_owner(self)
    }
}

struct Slot {
    next_request_id: u64,
    // The same command owner's original four-permit budget is reserved until
    // this slot, including any already-dispatched blocking read, really drops.
    _permit: OwnedSemaphorePermit,
}

struct Original {
    owner: Arc<dyn OriginalSelectionOwner>,
    expected: OriginalCircuitEvaluatedSelectionReceiptV1,
    predecessors: crate::OriginalCircuitPublishedEvidenceReadbackV1,
    slot: Mutex<Option<Slot>>,
    timeout: Duration,
    end: Instant,
    #[cfg(test)]
    fixture: test_support::State,
}

/// A read-only capability exported by the same completed original S owner.
/// Clone shares its request budget, cancellation fence, lifetime and permit.
/// It has no owner/FD getter, command method, reconnect or public constructor.
pub struct OriginalCircuitSelectionLocalReadbackV1 {
    original: Arc<Original>,
}

impl Clone for OriginalCircuitSelectionLocalReadbackV1 {
    fn clone(&self) -> Self {
        Self {
            original: Arc::clone(&self.original),
        }
    }
}

impl OriginalCircuitSelectionLocalReadbackV1 {
    /// Revalidate the actual S and all its original live predecessors. A
    /// cancelled/timed-out/failed read leaves the shared slot absent. Already
    /// dispatched blocking owner I/O may finish; that caller's delivery is
    /// unknown and no alias can start a replacement read on this capability.
    pub async fn read_original_selection(
        &self,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let mut slot = self
            .original
            .slot
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        let started = Instant::now();
        if started >= self.original.end || !(1..=128).contains(&slot.next_request_id) {
            return Err(Error::Unavailable);
        }
        slot.next_request_id = slot.next_request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let deadline = started
            .checked_add(self.original.timeout)
            .ok_or(Error::Unavailable)?
            .min(self.original.end);
        let owner = Arc::clone(&self.original.owner);
        #[cfg(test)]
        let fixture_operation = test_support::take_next(&self.original.fixture);
        let work = tokio::task::spawn_blocking(move || {
            let value = OriginalSelectionOwner::read_original_receipt(owner.as_ref())?;
            #[cfg(test)]
            test_support::after_actual_read(&fixture_operation, deadline);
            Ok::<_, Error>((slot, value))
        });
        let (slot, value) = tokio::time::timeout_at(
            tokio::time::Instant::from_std(deadline),
            work,
        )
        .await
        .map_err(|_| Error::Unavailable)?
        .map_err(|_| Error::CommitUncertain)??;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        OriginalCircuitSelectionLocalReadbackV1::require_original_selection(self, &value)?;
        let mut restore = self.original.slot.try_lock().map_err(|_| Error::Unavailable)?;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        *restore = Some(slot);
        Ok(value)
    }

    pub(crate) fn require_original_shared_predecessors(
        &self,
        shared: &crate::OriginalCircuitPublishedEvidenceReadbackV1,
    ) -> Result<(), Error> {
        crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(
            shared,
            self.original.expected.original_context(),
        ).map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let (original_t, original_e) =
            crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(
                &self.original.predecessors,
            );
        let (current_t, current_e) =
            crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(shared);
        if !std::ptr::eq(original_t, current_t) || !std::ptr::eq(original_e, current_e) {
            return Err(Error::Binding("same original local Selector T/E clients"));
        }
        Ok(())
    }

    pub(crate) fn require_original_selection(
        &self,
        expected: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<(), Error> {
        if Instant::now() >= self.original.end
            || self.original.expected.snapshot() != expected.snapshot()
            || self.original.expected.receipt() != expected.receipt()
            || self.original.expected.attestation() != expected.attestation()
            || self.original.expected.original_receipt_binding()
                != expected.original_receipt_binding()
        {
            return Err(Error::Binding("same original local Selector predecessor"));
        }
        // Full signatures, roles and unchanged original windows are checked,
        // including for recovered custody; no new-work authority is requested.
        let current = now()?;
        self.original.expected.original_receipt_predecessors(current)?;
        expected.original_receipt_predecessors(current)?;
        Ok(())
    }
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitSelectionCommandOwnerV1<W> {
    /// Export from this actual owner only after a fresh, authenticated original
    /// readback succeeds. This requires the same Version-owned local Selection
    /// purpose. A remote socket or an uncompleted/legacy S cannot export it.
    pub async fn open_original_evaluated_local_readback(
        self: Arc<Self>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<OriginalCircuitSelectionLocalReadbackV1, Error> {
        if timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(Error::Binding("bounded original local Selector readback"));
        }
        let started = Instant::now();
        let predecessors = match &self.predecessors {
            OriginalPredecessors::SharedLocalEvaluated(shared) => shared.clone(),
            _ => return Err(Error::Binding("original shared local Selector predecessors")),
        };
        let context = self.context.evaluated.as_ref().ok_or(
            Error::Binding("original evaluated local Selector purpose"),
        )?;
        let original_end =
            OriginalCircuitLearningReadClientV1::require_original_local_evaluated_selection(
                &self.live,
                context,
            )
            .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        OriginalCircuitLearningReadClientV1::require_original_local_shared_readbacks(
            &self.live,
            &predecessors,
        ).map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let end = started.checked_add(lifetime).ok_or(Error::Unavailable)?.min(original_end);
        let deadline = started.checked_add(timeout).ok_or(Error::Unavailable)?.min(end);
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let work = tokio::task::spawn_blocking(move || {
            let expected =
                OriginalCircuitSelectionCommandOwnerV1::read_original_evaluated_receipt_on_owner(
                    self.as_ref(),
                )?;
            Ok::<_, Error>((self, permit, expected))
        });
        let (owner, permit, expected) = tokio::time::timeout_at(
            tokio::time::Instant::from_std(deadline),
            work,
        )
        .await
        .map_err(|_| Error::Unavailable)?
        .map_err(|_| Error::CommitUncertain)??;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        let owner: Arc<dyn OriginalSelectionOwner> = owner;
        let value = OriginalCircuitSelectionLocalReadbackV1 {
            original: Arc::new(Original {
                owner,
                expected,
                predecessors,
                slot: Mutex::new(Some(Slot {
                    next_request_id: 1,
                    _permit: permit,
                })),
                timeout,
                end,
                #[cfg(test)]
                fixture: test_support::State::default(),
            }),
        };
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        Ok(value)
    }
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitSelectionCommandOwnerV1<W> {
    pub(crate) fn from_original_evaluated_local_shared_receipt_owner(
        owner: crate::OriginalCircuitSelectionReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        shared: crate::OriginalCircuitPublishedEvidenceReadbackV1,
    ) -> Result<Self, Error> {
        let context =
            crate::OriginalCircuitSelectionReceiptOwnerV1::original_evaluated_command_context(
                &owner,
            ).ok_or(Error::Binding("original local evaluated Selector custody"))?;
        OriginalCircuitLearningReadClientV1::require_original_local_evaluated_selection(
            &live, context,
        ).map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        OriginalCircuitLearningReadClientV1::require_original_local_shared_readbacks(
            &live, &shared,
        ).map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let mut command =
            OriginalCircuitSelectionCommandOwnerV1::from_original_evaluated_shared_receipt_owner(
                owner, live, shared.clone(),
            )?;
        // The original factory consumed the original custody and authenticated
        // the complete context. This only selects the stricter local source
        // protocol with the same already-sealed Arc pair.
        command.predecessors = OriginalPredecessors::SharedLocalEvaluated(shared);
        Ok(command)
    }
}

#[cfg(test)]
#[path = "circuit_selection_local_readback_support_tests.rs"]
mod test_support;
