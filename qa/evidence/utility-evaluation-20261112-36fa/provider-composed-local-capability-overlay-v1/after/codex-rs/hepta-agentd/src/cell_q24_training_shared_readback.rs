//! Consume one completed original Trainer client into sealed local readback.
//! The original channel, request counter and absolute lifetime stay in place.

use std::sync::Arc;

use super::Error;
use super::OriginalCellQ24TrainingCommandClientV1;
use super::OriginalCellQ24TrainingCommandReceiptV1;
use super::now;
use super::wire;

impl OriginalCellQ24TrainingCommandClientV1 {
    pub(crate) fn seal_original_completed_readback(
        self,
        expected: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<Arc<Self>, Error> {
        let retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
        let original = retained.as_ref().ok_or(Error::ReadbackRequired)?;
        if original != expected {
            return Err(Error::Binding("same completed original Trainer before sharing"));
        }
        let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
        let channel = slot.as_mut().ok_or(Error::Unavailable)?;
        channel.peer.check_peer_lifetime()?;
        let authenticated = wire::authenticate_receipt(
            &self.context,
            original.receipt().clone(),
            original.attestation().clone(),
            now()?,
        )?;
        if &authenticated != original {
            return Err(Error::Binding("full original Trainer signature before sharing"));
        }
        // This is a one-way attenuation of the same client, not a new channel.
        channel.execution_requested = true;
        drop(slot);
        drop(retained);
        Ok(Arc::new(self))
    }
}

#[cfg(test)]
#[path = "cell_q24_training_shared_readback_observation_tests.rs"]
mod observation_tests;
