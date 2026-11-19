//! Root-record DATA schedules external inputs. The real process route, exact
//! source exit and final physical C observations are separate obligations.

use std::time::Duration;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_types::Digest32;

use super::post_a_launch::RunningOrdinaryPostA;
use super::source_keeper::OriginalSourceObservation;
use crate::CellQ24PrivateHeadV1;
use crate::LoadedCellQ24ModelV1;
use crate::cell_q24_publication_driver::validation::Decision;
use crate::learning_iteration_checkpoint::ordinary_observer::OriginalCheckpointData;

pub(super) async fn wait_for_original_decision(
    running: &RunningOrdinaryPostA,
) -> anyhow::Result<(OriginalCheckpointData, Decision)> {
    let initial = running.plan.profile.original_initial_data()?;
    let directory = running
        .plan
        .resources
        .original
        .plan
        .root
        .authority
        .join("learning-checkpoint");
    let mut previous = None;
    loop {
        running.require_live()?;
        if let Some(observed) = OriginalCheckpointData::observe_live(&directory, &initial)? {
            if let Some(before) = &previous {
                observed.require_same_or_extended(before)?;
            }
            if let Some(snapshot) = &observed.snapshot {
                anyhow::ensure!(
                    snapshot.training_no_update_v2().is_none(),
                    "TrainingNoUpdate cannot satisfy an independent-B business case"
                );
                let state = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
                if state.next_stage() == Some(LearningIterationStageV1::Selection) {
                    let decision = Decision::new(snapshot.clone())?;
                    decision.require_root_publication()?;
                    anyhow::ensure!(
                        snapshot.receipts.iter().any(|receipt| matches!(
                            receipt.observation,
                            LearningIterationObservationV1::Evaluation { .. }
                        )),
                        "actual independent B evaluation is absent"
                    );
                    running.require_live()?;
                    return Ok((observed, decision));
                }
                anyhow::ensure!(
                    state.next_stage().is_some(),
                    "learning finished before the fixture supplied original C inputs"
                );
            }
            previous = Some(observed);
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

pub(super) async fn wait_for_original_terminal(
    running: &RunningOrdinaryPostA,
    mut previous: OriginalCheckpointData,
) -> anyhow::Result<OriginalCheckpointData> {
    let initial = running.plan.profile.original_initial_data()?;
    let directory = running
        .plan
        .resources
        .original
        .plan
        .root
        .authority
        .join("learning-checkpoint");
    loop {
        running.require_live()?;
        if let Some(observed) = OriginalCheckpointData::observe_live(&directory, &initial)? {
            observed.require_same_or_extended(&previous)?;
            if let Some(snapshot) = &observed.snapshot
                && LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?
                    .next_stage()
                    .is_none()
            {
                anyhow::ensure!(
                    matches!(
                        snapshot.receipts.last().map(|receipt| &receipt.observation),
                        Some(
                            LearningIterationObservationV1::NextUse { .. }
                                | LearningIterationObservationV1::RetainedModelNextUse { .. }
                        )
                    ),
                    "actual terminal original next-task observation required"
                );
                running.require_live()?;
                return Ok(observed);
            }
            previous = observed;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

/// Cross-check data received by the actual independent source against the
/// actual Root Training/Evaluation prefix. No receipt or model owner is made.
pub(super) fn original_candidate_model(
    running: &RunningOrdinaryPostA,
    checkpoint: &OriginalCheckpointData,
    decision: &Decision,
    source: &OriginalSourceObservation,
) -> anyhow::Result<std::sync::Arc<LoadedCellQ24ModelV1>> {
    running.require_live()?;
    let initial = running.plan.profile.original_initial_data()?;
    let training_head = decision
        .snapshot
        .receipts
        .iter()
        .find(|receipt| {
            matches!(
                receipt.observation,
                LearningIterationObservationV1::Evaluation { .. }
            )
        })
        .ok_or_else(|| anyhow::anyhow!("actual Evaluation predecessor absent"))?
        .predecessor;
    let candidate = decision
        .snapshot
        .receipts
        .iter()
        .find_map(|receipt| match &receipt.observation {
            LearningIterationObservationV1::Training { candidate, .. } => Some(candidate.as_ref()),
            _ => None,
        })
        .ok_or_else(|| anyhow::anyhow!("actual Training candidate absent"))?;
    let decode_bundle = |encoded: &str| -> anyhow::Result<CellCompatibilityBundleV1> {
        let bytes = canonical_bytes(encoded, 4096)?;
        Ok(crate::learning_iteration_checkpoint::decode_original_bundle_data(&bytes)?)
    };
    anyhow::ensure!(
        source.initial.parse::<Digest32>()? == initial.head_digest
            && source.binding.parse::<Digest32>()?
                == Digest32::of_parts(&[
                    b"hepta.root.independent-b.custodian.v1\0",
                    initial.head_digest.as_array(),
                ])
            && source.scope.parse::<Digest32>()? == checkpoint.scope_binding
            && source.training_head.parse::<Digest32>()? == training_head
            && source.registered_at_seconds != 0
            && !source.source_digest.parse::<Digest32>()?.is_zero()
            && decode_bundle(&source.candidate_bundle)? == *candidate
            && decode_bundle(&source.baseline_bundle)? == initial.request.selected_bundle,
        "actual source candidate DATA differs from original Root learning history"
    );
    let (baseline, baseline_bundle, _) = super::super::material::load(
        &running
            .plan
            .resources
            .original
            .plan
            .runtime
            .path()
            .join("model"),
    )?;
    anyhow::ensure!(
        baseline_bundle == initial.request.selected_bundle,
        "actual original baseline files changed"
    );
    let model = baseline.read_single_head_candidate_data(
        &baseline_bundle,
        candidate,
        CellQ24PrivateHeadV1::Drive { index: 0 },
        &canonical_bytes(&source.candidate_heads, 65_536)?,
    )?;
    anyhow::ensure!(
        model.components() == &candidate.components && candidate != &baseline_bundle,
        "real trained candidate required for both independent B cases"
    );
    running.require_live()?;
    Ok(std::sync::Arc::new(model))
}

fn canonical_bytes(encoded: &str, bound: usize) -> anyhow::Result<Vec<u8>> {
    anyhow::ensure!(
        !encoded.is_empty() && encoded.len() <= bound.div_ceil(3) * 4,
        "bounded original source DATA encoding"
    );
    let bytes = STANDARD_NO_PAD.decode(encoded)?;
    anyhow::ensure!(
        bytes.len() <= bound && STANDARD_NO_PAD.encode(&bytes) == encoded,
        "original source DATA is not canonical"
    );
    Ok(bytes)
}
