//! Measured input rejection shared by one-shot and resident workers.

use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::CellBackendManifestV2;
use crate::CellCostAccountingV2;
use crate::CellCostEntryV2;
use crate::CellCostMetricsV2;
use crate::CellCostOutcomeV2;
use crate::CellCostStageV2;
use crate::CellGenerationDispositionV2;
use crate::CellGenerationErrorV2;
use crate::CellGenerationProposalV2;
use crate::CellGenerationRequestV2;
use crate::CellTaskCostIdentityV2;
use crate::CellTaskCostV2;
use crate::cell_joint_process;

pub(super) fn rejected_input(
    manifest: &CellBackendManifestV2,
    request: &CellGenerationRequestV2,
    started: Instant,
) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
    let request_digest = request.digest()?;
    let identity = CellTaskCostIdentityV2 {
        task_digest: request.task_digest,
        source_digest: manifest.source_digest,
    };
    let mut cost =
        CellTaskCostV2::new(identity).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    cost.record(CellCostEntryV2 {
        event_id: Digest32::of_parts(&[b"hepta.joint.rejected-input.v1\0", &request_digest])
            .into_array(),
        identity,
        stage: CellCostStageV2::Codec,
        outcome: CellCostOutcomeV2::Rejected,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(cell_joint_process::elapsed_micros(started)?),
            ..CellCostMetricsV2::default()
        },
    })
    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    Ok(CellGenerationProposalV2 {
        request_digest,
        bundle_digest: manifest.bundle_digest,
        runtime_digest: manifest.runtime_digest,
        device_digest: manifest.device_digest,
        successor_state: request.predecessor.state.clone(),
        output_delta: Vec::new(),
        disposition: CellGenerationDispositionV2::Rejected,
        cost,
    })
}
