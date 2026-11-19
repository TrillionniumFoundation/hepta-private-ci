//! Canonical model data conversion. A decoded model confers no Trainer,
//! Evaluator, Artifact, CURRENT or source capability.

use super::*;

pub(crate) fn require_original_head_data(bytes: &[u8]) -> Result<(), CellGenerationErrorV2> {
    let heads = Matrix::decode(bytes)?;
    if heads.encode() != bytes {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(())
}

impl LoadedCellQ24ModelV1 {
    pub(crate) fn original_head_bytes(&self) -> Vec<u8> {
        self.heads.encode()
    }

    /// Reuse the actual original baseline graph and decode only a supplied
    /// canonical head matrix. The caller must authenticate the complete bundle
    /// separately; this path never optimizes or constructs a learning receipt.
    pub(crate) fn read_single_head_candidate_data(
        &self,
        baseline: &CellCompatibilityBundleV1,
        candidate: &CellCompatibilityBundleV1,
        head: CellQ24PrivateHeadV1,
        bytes: &[u8],
    ) -> Result<Self, CellGenerationErrorV2> {
        baseline
            .digest()
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        candidate
            .digest()
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let heads = Matrix::decode(bytes)?;
        if self.components != baseline.components
            || candidate.components.heads != Digest32::of_bytes(bytes)
            || heads.encode() != bytes
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let mut components = self.components.clone();
        components.heads = Digest32::of_bytes(bytes);
        if components != candidate.components {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        self.validate_single_head_candidate(
            Self {
                components,
                base: self.base.clone(),
                organ: self.organ.clone(),
                cell: self.cell.clone(),
                encoder: self.encoder.clone(),
                heads,
            },
            head,
        )
    }
}
