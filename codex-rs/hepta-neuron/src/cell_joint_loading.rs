//! Interpret a committed Joint v4 model-loading event under its explicit profile.
//! This is a commitment to the native observation, not an archive of its frame.
//! The actual owner must supply the original exact-intent durable receipt.

use codex_hepta_infer_core::JOINT_V4_LOADING_PROCESS_PROFILE;
use codex_hepta_infer_core::JointV4ComponentDigestsV1;
use codex_hepta_infer_core::joint_v4_loading_commitment_v1;
use codex_hepta_types::Digest32;

use crate::CellBackendManifestV2;
use crate::CellCostAccountingV2;
#[cfg(target_os = "linux")]
use crate::CellCostEntryV2;
#[cfg(target_os = "linux")]
use crate::CellCostMetricsV2;
use crate::CellCostOutcomeV2;
use crate::CellCostStageV2;
use crate::CellGenerationDispositionV2;
use crate::CellGenerationErrorV2;
use crate::CellGenerationReceiptV2;
use crate::CellLearningBindingV2;
use crate::CellTaskCostIdentityV2;
#[cfg(target_os = "linux")]
use crate::CellTaskCostV2;

/// Identity of the existing measured Codec interval after the pinned native
/// process's actual Model projection has matched the held physical assets.
/// The complete manifest also binds source, runtime, device, bundle and schemas.
/// No additional event or invented zero measurement is introduced.
pub(crate) fn loading_codec_event_id(
    manifest: &CellBackendManifestV2,
    request_digest: [u8; 32],
    loading_commitment: [u8; 32],
) -> Result<[u8; 32], CellGenerationErrorV2> {
    if manifest.profile != JOINT_V4_LOADING_PROCESS_PROFILE
        || request_digest == [0; 32]
        || loading_commitment == [0; 32]
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(Digest32::of_parts(&[
        b"hepta.joint.v4.observed-loading-codec-event.v1\0",
        &request_digest,
        &manifest.digest()?,
        &loading_commitment,
    ])
    .into_array())
}

/// Record the original four measured, disjoint child phases. Only the Codec
/// event identity changes when the native loading commitment was verified.
#[cfg(target_os = "linux")]
pub(crate) fn record_child_phases(
    cost: &mut CellTaskCostV2,
    manifest: &CellBackendManifestV2,
    request_digest: [u8; 32],
    loading_commitment: Option<[u8; 32]>,
    phase_micros: [u64; 4],
) -> Result<(), CellGenerationErrorV2> {
    for (index, stage) in [
        CellCostStageV2::Codec,
        CellCostStageV2::Encoder,
        CellCostStageV2::Inference,
        CellCostStageV2::Planning,
    ]
    .into_iter()
    .enumerate()
    {
        let event_id = if index == 0
            && let Some(commitment) = loading_commitment
        {
            loading_codec_event_id(manifest, request_digest, commitment)?
        } else {
            Digest32::of_parts(&[
                b"hepta.joint.child-phase.v1\0",
                &request_digest,
                &[index as u8],
            ])
            .into_array()
        };
        cost.record(CellCostEntryV2 {
            event_id,
            identity: cost.identity(),
            stage,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(phase_micros[index]),
                ..CellCostMetricsV2::default()
            },
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    }
    Ok(())
}

/// Verify all thirteen selected component positions against the original
/// successful model-loading event, retained unchanged by the existing Commit.
/// This authenticates no caller-supplied receipt: the caller must first read
/// the exact intent from its live, authorized generation journal. Cost summaries
/// and old successful Codec entries without this commitment cannot satisfy it.
pub fn verify_joint_v4_loading_receipt_v1(
    manifest: &CellBackendManifestV2,
    components: &JointV4ComponentDigestsV1,
    task_digest: [u8; 32],
    receipt: &CellGenerationReceiptV2,
) -> Result<(), CellGenerationErrorV2> {
    let CellLearningBindingV2::Frozen { weights } = &manifest.learning else {
        return Err(CellGenerationErrorV2::InvalidBinding);
    };
    if task_digest == [0; 32]
        || manifest.encoder != Some(components.encoder.into_array())
        || manifest.state_schema != components.state_schema.into_array()
        || manifest.output_schema != components.output_schema.into_array()
        || !matches!(
            receipt.disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        )
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let loading = joint_v4_loading_commitment_v1(*weights, components)
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    let event_id = loading_codec_event_id(manifest, receipt.request_digest, loading)?;
    receipt
        .cost
        .validate()
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    let identity = CellTaskCostIdentityV2 {
        task_digest,
        source_digest: manifest.source_digest,
    };
    let matching: Vec<_> = receipt
        .cost
        .entries()
        .iter()
        .filter(|entry| entry.event_id == event_id)
        .collect();
    if receipt.cost.identity() != identity
        || matching.len() != 1
        || matching[0].identity != identity
        || matching[0].stage != CellCostStageV2::Codec
        || matching[0].outcome != CellCostOutcomeV2::Succeeded
        || matching[0].accounting != CellCostAccountingV2::Exclusive
        || matching[0].metrics.wall_micros.is_none()
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(())
}
