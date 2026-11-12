//! Initial fixed descriptor admission for the additional readonly Candidate lane.
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Mutex;

use super::CandidateLane;
use super::Error;
use super::Origin;
use super::OriginalCellQ24CandidateStageOwnersV1;
use super::OriginalCellQ24CandidateStageStreamsV1;
use super::OriginalCellQ24NoUpdateStageOwnersV1;
use super::super::auth;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;

pub(super) fn bind(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    streams: OriginalCellQ24CandidateStageStreamsV1,
    protocol: OriginalCellEvaluationPanelRegistrationV1,
    baseline: Arc<LoadedCellQ24ModelV1>,
    origin: Origin,
) -> Result<OriginalCellQ24CandidateStageOwnersV1, Error> {
    let admitted_at = Instant::now();
    let (binding, started_at) =
        OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)
            .map_err(|_| Error::WrongScope)?;
    let peer = &streams.candidate_material;
    if material.initial.request.evaluation_profile != protocol.evaluation_profile()
        || baseline.components() != &material.initial.request.selected_bundle.components
        || peer.peer.actor_id != material.initial.owners.trainer
        || peer.timeout.is_zero()
        || peer.timeout > Duration::from_secs(30)
        || peer.lifetime.is_zero()
        || peer.lifetime > Duration::from_secs(300)
    {
        return Err(Error::WrongScope);
    }
    let end = admitted_at.checked_add(peer.lifetime).ok_or(Error::WrongScope)?;
    let OriginalCellQ24CandidateStageStreamsV1 { common, candidate_material: candidate } = streams;
    let mut common = match origin {
        Origin::Fresh => OriginalCellQ24NoUpdateStageOwnersV1::from_original_streams(
            material.clone(), common,
        ),
        Origin::Recovered => OriginalCellQ24NoUpdateStageOwnersV1::recover_original_streams(
            material.clone(), common,
        ),
    }?;
    let candidate = match origin {
        Origin::Fresh => OriginalCellQ24TrainingCommandConnectionV1::from_original_stream(
            candidate.stream, candidate.peer, candidate.original_owner_pidfd,
            material.clone(), candidate.timeout, candidate.lifetime,
        ),
        Origin::Recovered => OriginalCellQ24TrainingCommandConnectionV1::recover_from_original_stream(
            candidate.stream, candidate.peer, candidate.original_owner_pidfd,
            material.clone(), /*expected*/ None, candidate.timeout, candidate.lifetime,
        ),
    }.map_err(|_| Error::OwnerUnavailable("original Candidate initial connection"))?;
    let end = end.min(common.end);
    // Narrow the shared effect path too; no channel receives a later end.
    common.end = end;
    let fresh = auth::require_material(&material, binding)?;
    auth::require_clock(started_at, fresh)?;
    if Instant::now() >= end {
        return Err(Error::DeadlineExceeded);
    }
    Ok(OriginalCellQ24CandidateStageOwnersV1 {
        common,
        protocol,
        baseline,
        candidate: Mutex::new(CandidateLane::new(candidate)),
        end,
    })
}
