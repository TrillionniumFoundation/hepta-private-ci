//! Additive Lane F shadow entrypoint with an explicit NDU snapshot reference.
//!
//! V2 remains source-compatible. V3 validates the digest-only NDU reference
//! before delegating to the existing V2 shadow engine and does not grant any
//! execution or selection authority.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;
use crate::LaneFBudgetV1;
use crate::LaneFRunRequestV2;
use crate::LaneFShadowPipelineReceiptV2;
use crate::LaneFShadowPortsV1;
use crate::NduSnapshotRefError;
use crate::NduSnapshotRefV1;
use crate::PipelineErrorV2;
use crate::run_shadow_pipeline_v2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFRunRequestV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub ndu_snapshot: NduSnapshotRefV1,
    pub budget: LaneFBudgetV1,
    pub now_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PipelineErrorV3 {
    NduSnapshot(NduSnapshotRefError),
    Pipeline(PipelineErrorV2),
}

impl fmt::Display for PipelineErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PipelineErrorV3 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFShadowPipelineReceiptV3 {
    trace: LaneFShadowPipelineReceiptV2,
    ndu_snapshot_digest: Digest32,
    receipt_digest: Digest32,
}

impl LaneFShadowPipelineReceiptV3 {
    #[must_use]
    pub fn trace(&self) -> &LaneFShadowPipelineReceiptV2 {
        &self.trace
    }

    #[must_use]
    pub const fn ndu_snapshot_digest(&self) -> Digest32 {
        self.ndu_snapshot_digest
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.receipt_digest
    }
}

pub fn run_shadow_pipeline_v3<P: LaneFShadowPortsV1>(
    request: LaneFRunRequestV3,
    ports: &mut P,
) -> Result<LaneFShadowPipelineReceiptV3, PipelineErrorV3> {
    if request.request_digest.is_zero() {
        return Err(PipelineErrorV3::Pipeline(PipelineErrorV2::Pipeline(
            crate::PipelineErrorV1::EmptyDigest("request"),
        )));
    }
    request
        .ndu_snapshot
        .validate_against_snapshot_digest(request.snapshot.digest(), request.now_unix_ms)
        .map_err(PipelineErrorV3::NduSnapshot)?;
    let ndu_snapshot_digest = request.ndu_snapshot.snapshot_digest;
    let trace = run_shadow_pipeline_v2(
        LaneFRunRequestV2 {
            run_id: request.run_id,
            request_digest: request.request_digest,
            snapshot: request.snapshot,
            budget: request.budget,
        },
        ports,
    )
    .map_err(PipelineErrorV3::Pipeline)?;
    let mut bytes = b"hepta.intelligence.lane-f-pipeline.v3\0".to_vec();
    bytes.extend_from_slice(trace.digest().as_array());
    bytes.extend_from_slice(ndu_snapshot_digest.as_array());
    Ok(LaneFShadowPipelineReceiptV3 {
        trace,
        ndu_snapshot_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
    })
}
