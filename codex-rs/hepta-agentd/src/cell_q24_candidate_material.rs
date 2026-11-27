//! Original Trainer material, with no activation or publication authority.
//! Only the retained SourceBound lane or a complete live read from that lane
//! can construct this value. It has no Clone or Deserialize implementation.
//! The signed compatibility bundle authenticates model bytes, not a future
//! task-specific CellBackendManifest, independent evaluation, or adoption.

use std::sync::Arc;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CellQ24PrivateHeadV1;
use super::CellQ24TrainedCandidateV1;
use super::LoadedCellQ24ModelV1;
use super::codec::Matrix;

/// The existing HQ24M001 maximum is a 64 by 64 matrix with a 12-byte header.
pub(crate) const ORIGINAL_Q24_CANDIDATE_HEAD_BYTES: usize = 12 + 64 * 64 * 8;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24CandidateMaterialErrorV1 {
    #[error("original Training completion has no candidate")]
    NoCandidate,
    #[error("original Candidate material binding: {0}")]
    Binding(&'static str),
    #[error("original Candidate model: {0}")]
    Model(#[from] CellGenerationErrorV2),
}

type Error = OriginalCellQ24CandidateMaterialErrorV1;

pub struct OriginalCellQ24CandidateMaterialV1 {
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
    heads: Vec<u8>,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
}

impl OriginalCellQ24CandidateMaterialV1 {
    pub fn model(&self) -> &Arc<LoadedCellQ24ModelV1> {
        &self.model
    }

    pub fn bundle(&self) -> &CellCompatibilityBundleV1 {
        &self.bundle
    }

    pub fn heads(&self) -> &[u8] {
        &self.heads
    }

    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }

    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Called only inside the original occupied SourceBound trainer lane.
    /// The caller reads the same native/Generator/source owners before and
    /// after this construction and verifies their unchanged full signature.
    pub(crate) fn from_original_candidate(
        dataset: &LearningIterationSnapshotV1,
        candidate: CellQ24TrainedCandidateV1,
        receipt: LearningIterationReceiptV1,
        attestation: SignedLearningEvidenceV1,
    ) -> Result<Self, Error> {
        let (signed, steps, milliseconds, length) = candidate_fields(dataset, &receipt)?;
        if candidate.bundle != *signed
            || candidate.model.components() != &signed.components
            || candidate.metrics.optimizer_steps != steps
            || candidate
                .metrics
                .elapsed_microseconds
                .div_ceil(1_000)
                .max(1)
                != milliseconds
            || candidate.heads.len() != length
        {
            return Err(Error::Binding(
                "same native Candidate and original Training receipt",
            ));
        }
        require_rebuilt_bundle(dataset, signed, &candidate.heads)?;
        Ok(Self {
            model: Arc::new(candidate.model),
            bundle: candidate.bundle,
            heads: candidate.heads,
            receipt,
            attestation,
        })
    }

    /// Private receiver seam after every original page, peer lifetime, complete
    /// original E/D/freeze and Generator signature has been revalidated.
    /// Canonical model bytes are reconstructed from the original loaded baseline
    /// and authenticated heads; no file is reopened or optimizer invoked.
    pub(crate) fn from_verified_readback(
        baseline: &LoadedCellQ24ModelV1,
        dataset: &LearningIterationSnapshotV1,
        heads: Vec<u8>,
        receipt: LearningIterationReceiptV1,
        attestation: SignedLearningEvidenceV1,
    ) -> Result<Self, Error> {
        let (signed, _, _, length) = candidate_fields(dataset, &receipt)?;
        if baseline.components() != &dataset.request.selected_bundle.components
            || heads.len() != length
        {
            return Err(Error::Binding(
                "same complete baseline and signed Candidate length",
            ));
        }
        require_rebuilt_bundle(dataset, signed, &heads)?;
        let matrix = Matrix::decode(&heads)?;
        if matrix.rows != baseline.heads.rows || matrix.cols != baseline.heads.cols {
            return Err(Error::Binding("same original head shape"));
        }
        let mut changed = matrix
            .values
            .chunks_exact(matrix.cols)
            .zip(baseline.heads.values.chunks_exact(baseline.heads.cols))
            .enumerate()
            .filter_map(|(row, (candidate, original))| (candidate != original).then_some(row));
        let row = changed
            .next()
            .ok_or(Error::Binding("retained Candidate changes one head"))?;
        if changed.next().is_some() {
            return Err(Error::Binding("retained Candidate changes only one head"));
        }
        let half = matrix.rows / 2;
        let head = if row < half {
            CellQ24PrivateHeadV1::Drive { index: row as u16 }
        } else {
            CellQ24PrivateHeadV1::Prediction {
                index: (row - half) as u16,
            }
        };
        let candidate = LoadedCellQ24ModelV1 {
            components: signed.components.clone(),
            base: baseline.base.clone(),
            organ: baseline.organ.clone(),
            cell: baseline.cell.clone(),
            encoder: baseline.encoder.clone(),
            heads: matrix,
        };
        let model = baseline.validate_single_head_candidate(candidate, head)?;
        let bundle = signed.clone();
        Ok(Self {
            model: Arc::new(model),
            bundle,
            heads,
            receipt,
            attestation,
        })
    }
}

fn candidate_fields<'a>(
    dataset: &LearningIterationSnapshotV1,
    receipt: &'a LearningIterationReceiptV1,
) -> Result<(&'a CellCompatibilityBundleV1, u64, u64, usize), Error> {
    let LearningIterationObservationV1::Training {
        candidate,
        steps,
        milliseconds,
        artifact_bytes,
    } = &receipt.observation
    else {
        return Err(Error::NoCandidate);
    };
    let length = usize::try_from(*artifact_bytes)
        .map_err(|_| Error::Binding("bounded original Candidate length"))?;
    if receipt.predecessor != dataset.head_digest
        || receipt.operation_id != dataset.request.operation_id
        || receipt.actor_id != dataset.owners.trainer
        || !(12..=ORIGINAL_Q24_CANDIDATE_HEAD_BYTES).contains(&length)
        || *artifact_bytes > dataset.request.budget.maximum_artifact_bytes
    {
        return Err(Error::Binding("original Candidate receipt and budget"));
    }
    Ok((candidate, *steps, *milliseconds, length))
}

fn require_rebuilt_bundle(
    dataset: &LearningIterationSnapshotV1,
    signed: &CellCompatibilityBundleV1,
    heads: &[u8],
) -> Result<(), Error> {
    let baseline = &dataset.request.selected_bundle;
    let source_bundle = baseline
        .digest()
        .map_err(|_| Error::Binding("original baseline bundle"))?;
    let lineage = signed
        .training_lineage
        .as_ref()
        .ok_or(Error::Binding("original Candidate lineage"))?;
    let Some(LearningIterationObservationV1::Dataset {
        snapshot_digest, ..
    }) = dataset.receipts.last().map(|receipt| &receipt.observation)
    else {
        return Err(Error::Binding("original Dataset cut"));
    };
    let head_digest = Digest32::of_bytes(heads);
    let mut components = baseline.components.clone();
    components.heads = head_digest;
    let expected = CellCompatibilityBundleV1 {
        artifact_id: StableId::new(format!(
            "q24-sgd:{}",
            Digest32::of_parts(&[
                b"hepta.cell.q24.trained-candidate.v1\0",
                dataset.head_digest.as_array(),
                lineage.update_rule.as_array(),
                head_digest.as_array(),
            ])
        ))
        .map_err(|_| Error::Binding("original Candidate identity"))?,
        generation: baseline
            .generation
            .next()
            .map_err(|_| Error::Binding("original Candidate generation"))?,
        components,
        rollback_predecessor: Some(source_bundle),
        training_lineage: Some(CellTrainingLineageV1 {
            source_bundle,
            dataset: *snapshot_digest,
            update_rule: lineage.update_rule,
            evaluation_profile: dataset.request.evaluation_profile,
        }),
    };
    if signed != &expected {
        return Err(Error::Binding(
            "complete signed Candidate bundle and original heads",
        ));
    }
    Ok(())
}
