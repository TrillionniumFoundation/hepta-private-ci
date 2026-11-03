//! Observation-only half of the original durable writer handoff.

use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use super::DurableDispatchClaim;
use super::ProductionDispatchReceipt;
use super::ProductionDispatchRequest;
use super::ProductionDurableWriter;
use super::ProductionTargetDisposition;
use super::ProductionTargetOutcome;
use super::ProductionWriterError;
use super::now_unix_ms;
use super::operation_claims;

const PREPARED: u8 = 0;
const ENTERED: u8 = 1;
const CLOSED_BEFORE_ENTRY: u8 = 2;
const CLOSED_AFTER_ENTRY: u8 = 3;

/// In-process cancellation coordination for a single handoff, not durable
/// authority. All durable identity/state remains in the original writer.
#[derive(Default)]
pub(super) struct EffectEntryPhase(AtomicU8);

impl EffectEntryPhase {
    pub(super) fn enter(&self) -> Result<(), ProductionWriterError> {
        self.0
            .compare_exchange(PREPARED, ENTERED, Ordering::AcqRel, Ordering::Acquire)
            .map(|_| ())
            .map_err(|_| ProductionWriterError::StaleReceipt)
    }

    fn started(&self) -> bool {
        matches!(self.0.load(Ordering::Acquire), ENTERED | CLOSED_AFTER_ENTRY)
    }

    fn close(&self) -> bool {
        loop {
            let previous = self.0.load(Ordering::Acquire);
            let started = matches!(previous, ENTERED | CLOSED_AFTER_ENTRY);
            let closed = if started { CLOSED_AFTER_ENTRY } else { CLOSED_BEFORE_ENTRY };
            if self.0.compare_exchange(previous, closed, Ordering::AcqRel, Ordering::Acquire).is_ok() {
                return started;
            }
        }
    }
}

/// A non-cloneable receipt for observing/settling exactly one original claim.
/// Possessing it never authorizes another send, grant, or operation identity.
#[must_use = "dropping this receipt keeps the original operation indeterminate"]
pub struct ProductionEffectObservation {
    pub(super) writer: ProductionDurableWriter,
    pub(super) request: ProductionDispatchRequest,
    pub(super) dispatch_claim_event_id: String,
    pub(super) claim: DurableDispatchClaim,
    pub(super) inherited: bool,
    pub(super) phase: Arc<EffectEntryPhase>,
}

impl ProductionEffectObservation {
    pub fn request(&self) -> &ProductionDispatchRequest {
        &self.request
    }

    /// True means the checked local entry was consumed. It is not proof of
    /// network delivery, process start, completion, or an external effect.
    pub fn started(&self) -> bool {
        self.phase.started()
    }
}

impl Drop for ProductionEffectObservation {
    fn drop(&mut self) {
        self.phase.close();
    }
}

impl ProductionDurableWriter {
    /// Settle only the receipt paired with this writer's original entry.
    ///
    /// `Committed`/`NotApplied` require independent destination terminal
    /// evidence. A transport error is `Indeterminate`; a rejection after entry
    /// is conservatively retained as unknown. The owned task keeps its writer
    /// generation permit through both journal and claim commits if its caller
    /// is canceled.
    pub async fn settle_effect_entry(
        &self,
        observation: ProductionEffectObservation,
        outcome: ProductionTargetOutcome,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        if !Arc::ptr_eq(&self._writer_lock, &observation.writer._writer_lock) {
            return Err(ProductionWriterError::StaleReceipt);
        }
        let started = observation.phase.close();
        let outcome = match outcome {
            ProductionTargetOutcome::Rejected { reason } if started => {
                ProductionTargetOutcome::Indeterminate {
                    reason: format!("rejection after checked entry requires terminal observation: {reason}"),
                }
            }
            outcome => outcome,
        };
        let writer = self.clone();
        tokio::spawn(async move {
            let _lease = writer.acquire_current_lease().await?;
            let request = observation.request.clone();
            let receipt = if observation.inherited {
                writer.settle_inherited_dispatch_outcome(
                    request,
                    &observation.request.occurrence_key,
                    observation.dispatch_claim_event_id.clone(),
                    outcome,
                ).await?
            } else {
                writer.settle_dispatch_outcome(
                    request,
                    &observation.request.occurrence_key,
                    observation.dispatch_claim_event_id.clone(),
                    outcome,
                ).await?
            };
            if receipt.target_disposition != ProductionTargetDisposition::Indeterminate {
                operation_claims::mark_settled(
                    &writer.store,
                    &observation.claim,
                    now_unix_ms()?,
                ).await?;
            }
            Ok(receipt)
        })
        .await
        .map_err(|error| ProductionWriterError::Durability(format!("effect settlement task: {error}")))?
    }
}

