//! The same sole Model writer, reached only through a response from the actual
//! Root factory and a still-live original Training operation. Recovery never
//! initializes Missing or Pending state and never changes original timestamps.

use super::*;
use crate::root_q24_model_factory::OriginalRootModelMaterialV1;

pub(crate) fn original_root_model_key(
    original: &OriginalRootModelMaterialV1<'_, '_>,
) -> Result<Digest32, Error> {
    let observed = admission::validate_original_root_material(original)?;
    Ok(observed.admission.key(observed.binding).binding_digest)
}

impl<W: AnchorWitnessStore> CellQ24ModelProposalOwnerV1<W> {
    pub(crate) fn create_from_original_root(
        file: File,
        witness: W,
        original: &OriginalRootModelMaterialV1<'_, '_>,
    ) -> Result<Self, Error> {
        let observed = admission::validate_original_root_material(original)?;
        let owner = CellQ24ModelProposalOwnerV1::create_bound(
            file,
            witness,
            observed.dataset,
            observed.scope,
            observed.binding,
        )?;
        original.require_current_training_source()?;
        Ok(owner)
    }

    pub(crate) fn recover_from_original_root(
        file: File,
        witness: W,
        original: &OriginalRootModelMaterialV1<'_, '_>,
    ) -> Result<Self, Error> {
        let observed = admission::validate_original_root_material(original)?;
        let owner = CellQ24ModelProposalOwnerV1::recover_bound(
            file,
            witness,
            observed.dataset,
            observed.scope,
            observed.binding,
        )?;
        original.require_current_training_source()?;
        Ok(owner)
    }

    pub(crate) fn commit_original_root(
        &mut self,
        original: &OriginalRootModelMaterialV1<'_, '_>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let admission = self.admit_original_root(original)?;
        let receipt = self.commit_admitted(&admission, self.now()?);
        original.require_current_training_source()?;
        self.require_current()?;
        receipt
    }

    pub(crate) fn read_original_root(
        &mut self,
        original: &OriginalRootModelMaterialV1<'_, '_>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let admission = self.admit_original_root(original)?;
        let receipt = self.read_admitted(&admission);
        original.require_current_training_source()?;
        self.require_current()?;
        receipt
    }

    fn admit_original_root(
        &self,
        original: &OriginalRootModelMaterialV1<'_, '_>,
    ) -> Result<Admission, Error> {
        self.require_current()?;
        let observed = admission::validate_original_root_material(original)?;
        if observed.dataset != self.dataset_cut
            || observed.scope != self.scope
            || observed.binding != self.binding
        {
            return Err(Error::Binding("original Root Model owner differs"));
        }
        self.require_current()?;
        Ok(observed.admission)
    }
}
