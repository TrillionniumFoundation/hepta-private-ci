
//! Explicit timing adapter for read-side pinned candidate acquisition.

use std::fs::File;

use crate::ArtifactOwnerOperationalMetricsV1;
use crate::ArtifactOwnerStageV1;
use crate::LoadedPinnedCandidate;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::load_pinned_candidate;

pub fn load_pinned_candidate_measured(
    metrics: &ArtifactOwnerOperationalMetricsV1,
    snapshot_file: File,
    payload_file: File,
    expected: PinnedCandidateSpec,
) -> Result<LoadedPinnedCandidate, PinnedCandidateLoadError> {
    metrics.measure(ArtifactOwnerStageV1::PinnedLoad, || {
        load_pinned_candidate(snapshot_file, payload_file, expected)
    })
}
