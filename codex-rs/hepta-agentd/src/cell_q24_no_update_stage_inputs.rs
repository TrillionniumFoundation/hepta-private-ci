//! Original descriptor custody. All limits start during initial admission;
//! a later opaque predecessor never recreates a channel or resets its end.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use tokio::sync::Mutex;

use super::Error;
use super::Origin;
use super::OriginalCellQ24NoUpdateStageOwnersV1;
use super::auth;
use super::state::Continuation;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellQ24MaterialCommandClientV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

pub struct OriginalCellQ24NoUpdatePeerStreamV1 {
    pub stream: UnixStream,
    pub peer: LearningIterationEvidencePeerV1,
    pub original_owner_pidfd: OwnedFd,
    pub timeout: Duration,
    pub lifetime: Duration,
}

pub struct OriginalCellQ24NoUpdateTaskStreamV1 {
    pub stream: UnixStream,
    pub peer: AgentdRootAuthorityPeer,
    pub uid: u32,
    pub original_task_pidfd: OwnedFd,
    pub timeout: Duration,
    pub lifetime: Duration,
}

/// Every field is an original host-supplied connected capability, not a path
/// or an address to discover/reconnect. There is no future receipt field.
pub struct OriginalCellQ24NoUpdateStageStreamsV1 {
    pub experience: OriginalCellQ24NoUpdatePeerStreamV1,
    pub dataset: OriginalCellQ24NoUpdatePeerStreamV1,
    pub trainer: OriginalCellQ24NoUpdatePeerStreamV1,
    pub selector: OriginalCellQ24NoUpdatePeerStreamV1,
    pub version: OriginalCellQ24NoUpdateTaskStreamV1,
    pub next_use: OriginalCellQ24NoUpdatePeerStreamV1,
    pub completion: OriginalCellQ24NoUpdateTaskStreamV1,
}

pub(super) fn bind(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    streams: OriginalCellQ24NoUpdateStageStreamsV1,
    origin: Origin,
) -> Result<OriginalCellQ24NoUpdateStageOwnersV1, Error> {
    let admitted_at = Instant::now();
    let (initial_binding, started_at) =
        OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)
            .map_err(|_| Error::WrongScope)?;
    for input in [
        &streams.experience,
        &streams.dataset,
        &streams.trainer,
        &streams.selector,
        &streams.next_use,
    ] {
        require_timing(input.timeout, input.lifetime, Duration::from_secs(30))?;
    }
    require_timing(
        streams.version.timeout,
        streams.version.lifetime,
        Duration::from_secs(30),
    )?;
    require_timing(
        streams.completion.timeout,
        streams.completion.lifetime,
        Duration::from_millis(500),
    )?;
    for (input, stage) in [
        (&streams.experience, LearningIterationStageV1::Experience),
        (&streams.dataset, LearningIterationStageV1::Dataset),
        (&streams.trainer, LearningIterationStageV1::Training),
        (&streams.selector, LearningIterationStageV1::Selection),
        (&streams.next_use, LearningIterationStageV1::NextUse),
    ] {
        if &input.peer.actor_id != material.initial.owners.owner(stage) {
            return Err(Error::WrongScope);
        }
    }
    let lifetime = [
        streams.experience.lifetime,
        streams.dataset.lifetime,
        streams.trainer.lifetime,
        streams.selector.lifetime,
        streams.version.lifetime,
        streams.next_use.lifetime,
        streams.completion.lifetime,
    ]
    .into_iter()
    .min()
    .ok_or(Error::WrongScope)?;
    let end = admitted_at.checked_add(lifetime).ok_or(Error::WrongScope)?;
    let OriginalCellQ24NoUpdateStageStreamsV1 {
        experience: e,
        dataset: d,
        trainer: t,
        selector: s,
        version: v,
        next_use: c,
        completion: p,
    } = streams;
    let experience = match origin {
        Origin::Fresh => OriginalCellQ24MaterialCommandClientV1::from_original_experience_stream(
            e.stream,
            e.peer,
            e.original_owner_pidfd,
            material.clone(),
            e.timeout,
            e.lifetime,
        ),
        Origin::Recovered => {
            OriginalCellQ24MaterialCommandClientV1::recover_original_experience_stream(
                e.stream,
                e.peer,
                e.original_owner_pidfd,
                material.clone(),
                /*expected*/ None,
                e.timeout,
                e.lifetime,
            )
        }
    }
    .map_err(|_| Error::OwnerUnavailable("original Experience channel"))?;
    let dataset = match origin {
        Origin::Fresh => OriginalCellQ24MaterialCommandClientV1::from_original_dataset_stream(
            d.stream,
            d.peer,
            d.original_owner_pidfd,
            material.clone(),
            d.timeout,
            d.lifetime,
        ),
        Origin::Recovered => {
            OriginalCellQ24MaterialCommandClientV1::recover_original_dataset_stream(
                d.stream,
                d.peer,
                d.original_owner_pidfd,
                material.clone(),
                /*expected*/ None,
                d.timeout,
                d.lifetime,
            )
        }
    }
    .map_err(|_| Error::OwnerUnavailable("original Dataset channel"))?;
    let trainer = match origin {
        Origin::Fresh => OriginalCellQ24TrainingCommandConnectionV1::from_original_stream(
            t.stream,
            t.peer,
            t.original_owner_pidfd,
            material.clone(),
            t.timeout,
            t.lifetime,
        ),
        Origin::Recovered => {
            OriginalCellQ24TrainingCommandConnectionV1::recover_from_original_stream(
                t.stream,
                t.peer,
                t.original_owner_pidfd,
                material.clone(),
                /*expected*/ None,
                t.timeout,
                t.lifetime,
            )
        }
    }
    .map_err(|_| Error::OwnerUnavailable("original Trainer initial channel"))?;
    let version = original_owner_command_channel_v1(
        v.stream,
        v.peer,
        v.uid,
        v.original_task_pidfd,
        v.timeout,
        v.lifetime,
    )
    .map_err(|_| Error::OwnerUnavailable("original independent Version channel"))?;
    version
        .check_peer_lifetime()
        .map_err(|_| Error::OwnerUnavailable("original independent Version peer"))?;
    let selector = role_channel(s)?;
    let next_use = role_channel(c)?;
    let completion = original_owner_command_channel_v1(
        p.stream,
        p.peer,
        p.uid,
        p.original_task_pidfd,
        p.timeout,
        p.lifetime,
    )
    .map_err(|_| Error::OwnerUnavailable("original C readiness channel"))?;
    completion
        .check_peer_lifetime()
        .map_err(|_| Error::OwnerUnavailable("original C readiness peer"))?;
    let fresh = auth::require_material(&material, initial_binding)?;
    auth::require_clock(started_at, fresh)?;
    if Instant::now() >= end {
        return Err(Error::DeadlineExceeded);
    }
    Ok(OriginalCellQ24NoUpdateStageOwnersV1 {
        material,
        initial_binding,
        origin,
        end,
        continuation: Mutex::new(Continuation::new(
            experience, dataset, trainer, selector, version, next_use, completion,
        )),
        root: None,
    })
}

fn role_channel(
    input: OriginalCellQ24NoUpdatePeerStreamV1,
) -> Result<HostAuthorityPeerChannel, Error> {
    let peer = input.peer;
    let channel = original_owner_command_channel_v1(
        input.stream,
        AgentdRootAuthorityPeer {
            pid: peer.pid,
            boot_id: peer.boot_id,
            process_start_ticks: peer.process_start_ticks,
        },
        peer.uid,
        input.original_owner_pidfd,
        input.timeout,
        input.lifetime,
    )
    .map_err(|_| Error::OwnerUnavailable("original fixed role channel"))?;
    channel
        .check_peer_lifetime()
        .map_err(|_| Error::OwnerUnavailable("original fixed role peer"))?;
    Ok(channel)
}

fn require_timing(timeout: Duration, lifetime: Duration, limit: Duration) -> Result<(), Error> {
    if timeout.is_zero()
        || timeout > limit
        || lifetime.is_zero()
        || lifetime > Duration::from_secs(300)
    {
        return Err(Error::WrongScope);
    }
    Ok(())
}
