//! Explicit host composition from already opened assets. Profile selection has
//! no fallback and supplies no stage owner, publication or learning authority.

use std::sync::Arc;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationWorkerV2;

use crate::CellQ24GenerationWorkerV1;
use crate::CellQ24ModelFilesV1;
use crate::CellTemporalQ24GenerationWorkerV1;
use crate::CellTemporalQ24ModelFilesV1;
use crate::LoadedCellQ24ModelV1;
use crate::LoadedCellTemporalQ24ModelV1;

/// The trusted host chooses both the typed asset family and exact manifest
/// profile. Task input cannot select a file, executable or alternate backend.
pub enum CellQ24BackendFilesV1 {
    Composed(CellQ24ModelFilesV1),
    Temporal(CellTemporalQ24ModelFilesV1),
}

/// Validate the original journal's frozen genesis before returning a worker.
/// Reopening still passes the original config; current state is recovered by
/// the journal, never reconstructed or installed by this factory.
pub fn load_cell_q24_backend_v1(
    files: CellQ24BackendFilesV1,
    bundle: &CellCompatibilityBundleV1,
    config: &CellGenerationConfigV2,
    clock: Arc<dyn Fn() -> u64 + Send + Sync>,
) -> Result<Arc<dyn CellGenerationWorkerV2>, CellGenerationErrorV2> {
    config.initial.digest()?;
    if config.initial.manifest_digest != config.manifest.digest()?
        || config.initial.generation != bundle.generation.get()
        || config.initial.revision != 0
        || !config.initial.prefix.is_empty()
        || config.initial.stopped
        || config.source_frontier == [0; 32]
        || config.task_digest == [0; 32]
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    match files {
        CellQ24BackendFilesV1::Composed(files) => {
            if config.manifest.profile != CellQ24GenerationWorkerV1::PROFILE
                || !config.initial.state.is_empty()
            {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            Ok(Arc::new(LoadedCellQ24ModelV1::open_files(files)?.into_worker(
                bundle,
                config.manifest.clone(),
                clock,
            )?))
        }
        CellQ24BackendFilesV1::Temporal(files) => {
            if config.manifest.profile != CellTemporalQ24GenerationWorkerV1::PROFILE {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            let model = LoadedCellTemporalQ24ModelV1::open_files(files)?;
            if config.initial.state != model.initial_state() {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            Ok(Arc::new(model.into_worker(bundle, config.manifest.clone(), clock)?))
        }
    }
}
