//! Irreversible, purpose-fixed attenuation of one original Dataset command.
//! This consumes the connected client; no caller flag or role tag creates it.
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCellQ24MaterialCommandClientV1;
use super::OriginalCellQ24MaterialCommandReceiptV1;
use super::Role;
use super::now;
use super::wire;
use crate::OriginalCellQ24MaterialReceiptConfigV1;

pub struct OriginalCellQ24DatasetCommandReadbackV1 {
    original: OriginalCellQ24MaterialCommandClientV1,
}

impl OriginalCellQ24MaterialCommandClientV1 {
    /// Consume this exact original Dataset capability and permanently remove
    /// its execution surface. The original channel and deadline are retained.
    pub fn into_original_dataset_readback(
        self,
        expected: &OriginalCellQ24MaterialReceiptConfigV1,
    ) -> Result<OriginalCellQ24DatasetCommandReadbackV1, Error> {
        let started_at = now()?;
        let binding = wire::context_binding(expected, started_at)?;
        if self.role != Role::Dataset || self.binding != binding {
            return Err(Error::Binding("same original Dataset command context"));
        }
        {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
            let channel = slot.as_mut().ok_or(Error::Unavailable)?;
            channel.peer.check_peer_lifetime()?;
            let fresh_now = now()?;
            if fresh_now < started_at
                || wire::context_binding(expected, fresh_now)? != binding
                || wire::context_binding(&self.config, fresh_now)? != binding
            {
                return Err(Error::Binding("Dataset attenuation clock and context"));
            }
            channel.execution_requested = true;
        }
        Ok(OriginalCellQ24DatasetCommandReadbackV1 { original: self })
    }
}

impl OriginalCellQ24DatasetCommandReadbackV1 {
    /// Read the original pair now; neither Missing nor Pending creates work.
    pub async fn readback(&self) -> Result<OriginalCellQ24MaterialCommandReceiptV1, Error> {
        OriginalCellQ24MaterialCommandClientV1::readback(&self.original).await
    }

    pub(crate) fn verify_original_cut(
        &self,
        cut: &OriginalCellQ24MaterialCommandReceiptV1,
    ) -> Result<u64, Error> {
        let at = now()?;
        let retained = self
            .original
            .retained
            .try_lock()
            .map_err(|_| Error::Unavailable)?;
        if retained.as_ref() != Some(cut) {
            return Err(Error::Binding("same originally read Dataset cut"));
        }
        wire::authenticate_cut(&self.original.config, Role::Dataset, cut.clone(), at)?;
        Ok(at)
    }

    pub(crate) fn require_initial_context(
        &self,
        expected: &OriginalCellQ24MaterialReceiptConfigV1,
    ) -> Result<(), Error> {
        let at = now()?;
        if self.original.role != Role::Dataset
            || wire::context_binding(expected, at)? != self.original.binding
            || wire::context_binding(&self.original.config, at)? != self.original.binding
        {
            return Err(Error::Binding("same attenuated Dataset context"));
        }
        Ok(())
    }
}

// These crate-private checks carry the original purpose into the initial
// Trainer connection. Neither accepts a role selector or an uploaded receipt.
impl OriginalCellQ24MaterialReceiptConfigV1 {
    pub(crate) fn require_original_command_initial(&self) -> Result<(Digest32, u64), Error> {
        let at = now()?;
        Ok((wire::context_binding(self, at)?, at))
    }
}

impl OriginalCellQ24MaterialCommandReceiptV1 {
    pub(crate) fn require_original_dataset_context(
        &self,
        expected: &OriginalCellQ24MaterialReceiptConfigV1,
    ) -> Result<u64, Error> {
        let at = now()?;
        let binding = wire::context_binding(expected, at)?;
        if self.original_context != binding {
            return Err(Error::Binding(
                "same originally authenticated Material context",
            ));
        }
        wire::authenticate_cut(expected, Role::Dataset, self.clone(), at)?;
        Ok(at)
    }
}
