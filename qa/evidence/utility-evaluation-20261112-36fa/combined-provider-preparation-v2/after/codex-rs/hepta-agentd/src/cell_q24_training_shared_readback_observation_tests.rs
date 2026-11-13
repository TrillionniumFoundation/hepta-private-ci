//! Read-only test observation of the original shared Trainer slot.
//! No counter, channel, lifetime, execution flag or response is modified.

use super::Error;
use super::OriginalCellQ24TrainingCommandClientV1;

impl OriginalCellQ24TrainingCommandClientV1 {
    pub(crate) fn fixture_readback_next_request_id(&self) -> Result<Option<u64>, Error> {
        let slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
        Ok(slot.as_ref().map(|channel| channel.next_request_id))
    }
}
