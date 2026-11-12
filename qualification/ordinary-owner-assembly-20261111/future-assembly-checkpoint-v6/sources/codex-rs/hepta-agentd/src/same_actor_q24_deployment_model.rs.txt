//! Open actual immutable Q24 files from the approved deployment and retain
//! their inode/hash pins across the original bounded model decoder.

use std::sync::Arc;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use serde::{Deserialize, Serialize};
use crate::{AgentdError, CellQ24ModelFilesV1, LoadedCellQ24ModelV1};
use super::bundle_data::OriginalBundleData;
use super::files::{OriginalDeploymentFiles, PinnedFileData};
use super::learning_data::required_option;
use super::deployment_error;
use super::deployment_refused;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalModelData {
    pub base: PinnedFileData,
    pub encoder: PinnedFileData,
    pub heads: PinnedFileData,
    #[serde(deserialize_with = "required_option")]
    pub organ_adapter: Option<PinnedFileData>,
    #[serde(deserialize_with = "required_option")]
    pub cell_adapter: Option<PinnedFileData>,
    pub bundle: OriginalBundleData,
}

impl OriginalModelData {
    pub(super) fn open_original(
        &self,
        files: &mut OriginalDeploymentFiles,
    ) -> Result<(Arc<LoadedCellQ24ModelV1>, CellCompatibilityBundleV1), AgentdError> {
        files.require_original_context()?;
        let base = files.read_original(&self.base, 16 * 1024 * 1024)?;
        let encoder = files.read_original(&self.encoder, 16 * 1024 * 1024)?;
        let heads = files.read_original(&self.heads, 16 * 1024 * 1024)?;
        let organ = self.organ_adapter.as_ref()
            .map(|file| files.read_original(file, 16 * 1024 * 1024)).transpose()?;
        let cell = self.cell_adapter.as_ref()
            .map(|file| files.read_original(file, 16 * 1024 * 1024)).transpose()?;
        let model = LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
            base: base.clone_original_file()?,
            encoder: encoder.clone_original_file()?,
            heads: heads.clone_original_file()?,
            organ_adapter: organ.as_ref().map(|read| read.clone_original_file()).transpose()?,
            cell_adapter: cell.as_ref().map(|read| read.clone_original_file()).transpose()?,
        }).map_err(deployment_error)?;
        for read in [&base, &encoder, &heads].into_iter().chain(organ.iter()).chain(cell.iter()) {
            read.require_original_pin()?;
        }
        let bundle = self.bundle.original()?;
        bundle.digest().map_err(deployment_error)?;
        if model.components() != &bundle.components {
            return Err(deployment_refused("actual model components differ from the approved bundle"));
        }
        files.require_original_context()?;
        Ok((Arc::new(model), bundle))
    }
}
