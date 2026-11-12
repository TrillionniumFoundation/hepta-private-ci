//! Root fixes actual baseline assets and a label-free benchmark input before
//! Training. The future candidate manifest is derived only from the actual
//! Training checkpoint and native decoded single-head material.

use std::io;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellLearningBindingV2;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::files::OriginalBFile;
use super::files::OriginalBFileAccess;
use super::files::OriginalBFiles;
use crate::CellQ24ModelFilesV1;
use crate::CellQ24PrivateHeadV1;
use crate::LoadedCellQ24ModelV1;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ModelData {
    base: PathBuf,
    organ_adapter: Option<PathBuf>,
    cell_adapter: Option<PathBuf>,
    encoder: PathBuf,
    heads: PathBuf,
    benchmark_input: PathBuf,
    updated_head: HeadData,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum HeadData {
    Drive { index: u16 },
    Prediction { index: u16 },
}

pub(super) struct OriginalBModelFiles {
    base: OriginalBFile,
    organ: Option<OriginalBFile>,
    cell: Option<OriginalBFile>,
    encoder: OriginalBFile,
    heads: OriginalBFile,
    input: OriginalBFile,
    head: CellQ24PrivateHeadV1,
}

impl ModelData {
    pub(super) fn open(self, tracker: &mut OriginalBFiles) -> io::Result<OriginalBModelFiles> {
        let mut open = |path: &PathBuf| tracker.open(path, OriginalBFileAccess::ReadOnly);
        Ok(OriginalBModelFiles {
            base: open(&self.base)?,
            organ: self.organ_adapter.as_ref().map(&mut open).transpose()?,
            cell: self.cell_adapter.as_ref().map(&mut open).transpose()?,
            encoder: open(&self.encoder)?,
            heads: open(&self.heads)?,
            input: open(&self.benchmark_input)?,
            head: match self.updated_head {
                HeadData::Drive { index } => CellQ24PrivateHeadV1::Drive { index },
                HeadData::Prediction { index } => CellQ24PrivateHeadV1::Prediction { index },
            },
        })
    }
}

impl OriginalBModelFiles {
    pub(super) fn observe_original_training_work(
        &self,
        work: &crate::cell_composed_q24::OriginalQ24TrainingWorkDataV1,
        training: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        heads: &[u8],
    ) -> io::Result<crate::cell_composed_q24::OriginalQ24TrainingWorkObservedV1> {
        let coordinator =
            codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
                training.clone(),
            )
            .map_err(io::Error::other)?;
        let candidate = coordinator
            .candidate()
            .ok_or_else(|| io::Error::other("original Training candidate absent"))?;
        let baseline = &training.request.selected_bundle;
        let original_baseline = self.load_baseline(baseline)?;
        let model = original_baseline
            .read_single_head_candidate_data(baseline, candidate, self.head, heads)
            .map_err(io::Error::other)?;
        let observed =
            crate::cell_composed_q24::OriginalQ24TrainingWorkDataV1::verify_original_training(
                work,
                training,
                &original_baseline,
                &model,
                self.head,
                heads,
            )
            .map_err(io::Error::other)?;
        self.require_baseline(baseline)?;
        Ok(observed)
    }

    pub(super) fn all_files(&self) -> Vec<&OriginalBFile> {
        let mut files = vec![&self.base, &self.encoder, &self.heads, &self.input];
        files.extend(self.organ.iter());
        files.extend(self.cell.iter());
        files
    }

    pub(super) fn input(&self, expected: Digest32) -> io::Result<Vec<u8>> {
        self.input.require_digest(expected, 522)
    }

    pub(super) fn load_baseline(
        &self,
        baseline: &CellCompatibilityBundleV1,
    ) -> io::Result<LoadedCellQ24ModelV1> {
        self.require_baseline(baseline)?;
        let model = LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
            base: self.base.original_readonly()?,
            organ_adapter: self
                .organ
                .as_ref()
                .map(OriginalBFile::original_readonly)
                .transpose()?,
            cell_adapter: self
                .cell
                .as_ref()
                .map(OriginalBFile::original_readonly)
                .transpose()?,
            encoder: self.encoder.original_readonly()?,
            heads: self.heads.original_readonly()?,
        })
        .map_err(io::Error::other)?;
        if model.components() != &baseline.components {
            return Err(io::Error::other("original B baseline components differ"));
        }
        self.require_baseline(baseline)?;
        Ok(model)
    }

    pub(super) fn candidate(
        &self,
        original: &CellGenerationConfigV2,
        baseline: &CellCompatibilityBundleV1,
        candidate: &CellCompatibilityBundleV1,
        heads: &[u8],
    ) -> io::Result<(LoadedCellQ24ModelV1, CellGenerationConfigV2)> {
        crate::cell_composed_q24::validate_manifest(baseline, &original.manifest)
            .map_err(io::Error::other)?;
        let model = self
            .load_baseline(baseline)?
            .read_single_head_candidate_data(baseline, candidate, self.head, heads)
            .map_err(io::Error::other)?;
        let lineage = candidate
            .training_lineage
            .as_ref()
            .ok_or_else(|| io::Error::other("original candidate lineage missing"))?;
        if lineage.source_bundle != baseline.digest().map_err(io::Error::other)? {
            return Err(io::Error::other("original candidate baseline differs"));
        }
        let mut config = original.clone();
        config.manifest.bundle_digest = candidate.digest().map_err(io::Error::other)?.into_array();
        config.manifest.encoder = Some(candidate.components.encoder.into_array());
        config.manifest.head = Some(candidate.components.heads.into_array());
        config.manifest.learning = CellLearningBindingV2::Frozen {
            weights: model.effective_weights_digest().into_array(),
        };
        config.manifest.evolution.lineage = Digest32::of_parts(&[
            b"hepta.root.b.original-training-lineage.v1\0",
            lineage.source_bundle.as_array(),
            lineage.dataset.as_array(),
            lineage.update_rule.as_array(),
            lineage.evaluation_profile.as_array(),
        ])
        .into_array();
        // The original baseline adoption reference is retained as provenance;
        // this unpublished component creates no candidate adoption authority.
        config.initial.manifest_digest = config.manifest.digest().map_err(io::Error::other)?;
        crate::cell_composed_q24::validate_manifest(candidate, &config.manifest)
            .map_err(io::Error::other)?;
        self.require_baseline(baseline)?;
        Ok((model, config))
    }

    pub(super) fn require_baseline(&self, bundle: &CellCompatibilityBundleV1) -> io::Result<()> {
        let c = &bundle.components;
        for (file, expected) in [
            (&self.base, c.base),
            (&self.encoder, c.encoder),
            (&self.heads, c.heads),
        ] {
            file.require_digest(expected, 65_536)?;
        }
        for (file, expected) in [(&self.organ, c.organ_adapter), (&self.cell, c.cell_adapter)] {
            match (file, expected) {
                (Some(file), Some(expected)) => {
                    file.require_digest(expected, 65_536)?;
                }
                (None, None) => {}
                _ => return Err(io::Error::other("original B baseline adapter differs")),
            }
        }
        Ok(())
    }
}
