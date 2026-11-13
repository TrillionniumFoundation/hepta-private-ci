//! Consume the actual pair and the already-authorized pre-freeze Source lane.
//! The original pair factory keeps all signing, freeze, ledger and four-permit
//! checks; no Source connection, writer, counter or deadline is recreated.

use std::sync::Arc;
use codex_hepta_neuron::FileAnchorWitnessStore;
use super::*;
use crate::{OriginalCircuitPrefreezeSourceV1, OriginalCellQ24MaterialCommandErrorV1,
    OriginalCellQ24MaterialCommandOwnerV1};

impl<EW: AnchorWitnessStore, DW: AnchorWitnessStore> OriginalCellQ24MaterialReceiptOwnersV1<EW, DW> {
    pub fn into_original_prefreeze_source_command_owner(
        self, source: OriginalCircuitPrefreezeSourceV1, baseline: Arc<LoadedCellQ24ModelV1>,
    ) -> Result<OriginalCellQ24MaterialCommandOwnerV1<EW, DW, FileAnchorWitnessStore>,
        OriginalCellQ24MaterialCommandErrorV1>
    {
        let (source, identity, ledger) = source.into_original_material_parts(&self.config)
            .map_err(|error| OriginalCellQ24MaterialCommandErrorV1::Dataset(
                CellQ24DatasetErrorV1::Source(error)))?;
        OriginalCellQ24MaterialReceiptOwnersV1::into_command_owner(
            self, source, identity, ledger, baseline,
        )
    }
}
