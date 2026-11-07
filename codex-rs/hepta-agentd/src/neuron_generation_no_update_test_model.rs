//! A tiny frozen numeric model for engineering evidence, not a quality trial.
//! It reads actual weight bytes, checks the selected digest and persists the
//! input-dependent result. All issuer keys elsewhere remain explicit fixtures.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;

#[derive(Clone)]
pub(super) struct FrozenModel {
    pub(super) directory: PathBuf,
    pub(super) executions: Arc<AtomicUsize>,
}

impl CellGenerationControlPortV2 for FrozenModel {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        let started = Instant::now();
        let weights = fs::read(self.directory.join("incumbent.f32le"))
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if manifest.learning
            != (CellLearningBindingV2::Frozen {
                weights: Digest32::of_bytes(&weights).into_array(),
            })
            || weights.len() != 8
            || request.input.len() != 2
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let coefficients = weights
            .chunks_exact(4)
            .map(|bytes| f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]));
        let value: f32 = coefficients
            .zip(&request.input)
            .map(|(weight, input)| weight * f32::from(*input))
            .sum();
        self.executions.fetch_add(1, Ordering::SeqCst);
        let mut cost = CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        cost.record(CellCostEntryV2 {
            event_id: request.digest()?,
            identity: cost.identity(),
            stage: CellCostStageV2::Inference,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(
                    started
                        .elapsed()
                        .as_micros()
                        .try_into()
                        .map_err(|_| CellGenerationErrorV2::Capacity)?,
                ),
                ..CellCostMetricsV2::default()
            },
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let result = CellGenerationProposalV2 {
            request_digest: request.digest()?,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: request.input.clone(),
            output_delta: value.to_le_bytes().to_vec(),
            disposition: CellGenerationDispositionV2::Stopped,
            cost,
        };
        let bytes = serde_json::to_vec(&result).map_err(|_| CellGenerationErrorV2::Corrupt)?;
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(self.directory.join("original-model-result.json"))
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        File::open(&self.directory)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        Ok(result)
    }

    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        let bytes = match fs::read(self.directory.join("original-model-result.json")) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(CellGenerationErrorV2::Unavailable),
        };
        let result: CellGenerationProposalV2 =
            serde_json::from_slice(&bytes).map_err(|_| CellGenerationErrorV2::Corrupt)?;
        if result.request_digest != request.digest()? {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(Some(result))
    }

    fn cancel_generation(
        &mut self,
        _: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        Ok(())
    }
}
