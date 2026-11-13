//! Same-host delivery of an actually completed original evaluated Selector.
//! No raw receipt/context, transport, new owner or execution request is accepted.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::OriginalCircuitSelectionCommandContextV1;
use super::OriginalCircuitSelectionCommandOwnerV1;
use super::now;
use super::wire;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitSelectionCommandOwnerV1<W> {
    /// Read the same original S owner for a colocated Version/NextUse consumer.
    /// Missing, pending, invalid, withdrawn or expired originals stay errors.
    /// The original profile is preserved; a recovered read cannot become new work.
    ///
    /// Cancelling this await does not cancel a dispatched blocking read. The
    /// permit and owner operation live until its actual terminal; delivery is
    /// then unknown to the dropped caller. No Execute or replacement channel is
    /// made, and this method has no mechanism for restoring Fresh custody.
    pub async fn read_original_evaluated_receipt(
        self: Arc<Self>,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if self.context.evaluated.is_none() {
                return Err(Error::Binding("original evaluated Selector local readback purpose"));
            }
            OriginalCircuitSelectionCommandContextV1::authenticate(&self.context, now()?)?;
            let (receipt, signature) = {
                let mut owner = self.owner.try_lock().map_err(|_| Error::Busy)?;
                let original: &mut OriginalCircuitSelectionReceiptOwnerV1<W> = &mut owner;
                OriginalCircuitSelectionCommandOwnerV1::observe_original(
                    self.as_ref(), original, wire::Action::Readback,
                )?
            };
            // The same wire authenticator used by the existing client/evidence
            // path reconstructs the entire expected cut and checks every full
            // signature, enrolled actor, predecessor and original purpose.
            let original = wire::authenticate_receipt(
                &self.context, receipt, signature, now()?,
            )?;
            let completed = OriginalCircuitEvaluatedSelectionReceiptV1::from_original_command_response(
                &original,
            )?;
            OriginalCircuitSelectionCommandContextV1::authenticate(&self.context, now()?)?;
            Ok(completed)
        }).await.map_err(|_| Error::CommitUncertain)?
    }
}
