//! One read-only view of both original completed Material journals.
//! The parent's Dataset authenticator retains the actual Source/Ledger CURRENT
//! rereads, complete predecessor signature comparison and final journal checks.

use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::OriginalCellQ24MaterialCompletionV1;
use super::OriginalCellQ24MaterialReceiptOwnersV1;
use super::OriginalCellQ24MaterialReceiptSourcesV1;
use super::binding;

impl<EW: AnchorWitnessStore, DW: AnchorWitnessStore>
    OriginalCellQ24MaterialReceiptOwnersV1<EW, DW>
{
    pub(crate) fn readback_material_pair(
        &mut self,
        mut sources: OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<
        (
            OriginalCellQ24MaterialCompletionV1,
            OriginalCellQ24MaterialCompletionV1,
        ),
        Error,
    > {
        let started_at = binding::now()?;
        let experience = self.read_experience(&mut sources, started_at)?;
        let saved = binding::dataset_saved(&self.config, self.dataset_binding, &experience)?;
        let bytes = self.dataset.read(&saved)?;
        let dataset =
            self.authenticate_dataset(&mut sources, &experience, &saved, &bytes, started_at)?;
        Ok((experience, dataset))
    }
}
