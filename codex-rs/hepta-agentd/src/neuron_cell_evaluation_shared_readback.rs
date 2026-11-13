//! Consume one completed original Evaluator client into sealed local readback.
//! Sharing preserves its single slot, nonce, aggregate limit and expiry.

use std::sync::Arc;

use super::Error;
use super::OriginalCellEvaluationCommandClientV1;
use super::now;
use super::wire;
use crate::OriginalCellEvaluationCommandReceiptV1;

impl OriginalCellEvaluationCommandClientV1 {
    pub(crate) fn seal_original_completed_readback(
        self,
        expected: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Arc<Self>, Error> {
        let retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
        let original = retained.as_ref().ok_or(Error::ReadbackRequired)?;
        if original != expected {
            return Err(Error::Binding(
                "same completed original Evaluator before sharing",
            ));
        }
        let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
        let channel = slot.as_mut().ok_or(Error::Unavailable)?;
        channel.peer.check_peer_lifetime()?;
        let authenticated = wire::authenticate_completed(
            &self.context,
            original.snapshot().clone(),
            original.attestation().clone(),
            now()?,
        )?;
        if &authenticated != original {
            return Err(Error::Binding(
                "full original Evaluator signature before sharing",
            ));
        }
        channel.execution_requested = true;
        drop(slot);
        drop(retained);
        Ok(Arc::new(self))
    }
}
