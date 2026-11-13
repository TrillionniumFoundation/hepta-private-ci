//! Public Root handoff and original process admission over actual dedicated-UID
//! sockets. These idle peers supply no role result; a role request fails them.
//! Complete original NoUpdate/B/Version/S/C work has a separate provider fixture.

use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

use super::support::ResidentRootFixture;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellEvaluationPanelRegistrationV1 as Registration;
use crate::OriginalCellEvaluationPanelTaskV1 as Task;
use crate::OriginalCellQ24CandidateStageOwnersV1;
use crate::OriginalCellQ24CandidateStageStreamsV1;
use crate::OriginalCellQ24NoUpdatePeerStreamV1 as PeerStream;
use crate::OriginalCellQ24NoUpdateStageStreamsV1;
use crate::OriginalCellQ24NoUpdateTaskStreamV1 as TaskStream;
use crate::RootCandidateStageHandoffV1;
use crate::RootResidentCandidateInputsV1;
use crate::RootResidentLearningConsumerV3;
use crate::RootResidentLearningProfileV3;
use crate::cell_q24_material_receipt_owner::MaterialCommandFixture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

#[path = "authority_host_learning_resident_provider_lifecycle_tests.rs"]
mod lifecycle;
#[path = "authority_host_learning_resident_provider_process_tests.rs"]
mod process;

fn registration() -> anyhow::Result<Registration> {
    Ok(Registration::new(
        Task {
            plan_id: StableId::new("resident-idle-primary-B")?,
            task_digest: Digest32::of_bytes(b"explicit idle primary task"),
            cohort_rule_digest: Digest32::of_bytes(b"explicit idle primary rule"),
        },
        vec![Task {
            plan_id: StableId::new("resident-idle-retention-B")?,
            task_digest: Digest32::of_bytes(b"explicit idle retention task"),
            cohort_rule_digest: Digest32::of_bytes(b"explicit idle retention rule"),
        }],
    )?)
}

async fn material() -> anyhow::Result<(MaterialCommandFixture, Registration)> {
    let protocol = registration()?;
    let fixture = Box::pin(
        MaterialCommandFixture::candidate_pages_for_evaluation_profile(
            protocol.evaluation_profile(),
        ),
    )
    .await?;
    Ok((fixture, protocol))
}

fn root(fixture: &MaterialCommandFixture) -> anyhow::Result<ResidentRootFixture> {
    ResidentRootFixture::for_original_evaluation_window(
        fixture.config.initial.clone(),
        fixture.config.scope.clone(),
        &fixture.config.verifier,
    )
}

fn input(
    fixture: &MaterialCommandFixture,
    protocol: Registration,
) -> RootResidentCandidateInputsV1 {
    RootResidentCandidateInputsV1 {
        material: fixture.config.clone(),
        protocol,
        baseline: fixture.training_baseline(),
        verifier: fixture.config.verifier.clone(),
    }
}

fn role_streams(
    process: &process::PeerProcess,
    streams: [UnixStream; 10],
    profile: &RootResidentLearningProfileV3,
    lifetime: Duration,
) -> anyhow::Result<OriginalCellQ24CandidateStageStreamsV1> {
    let peer = |stream: UnixStream, actor: &StableId| -> anyhow::Result<PeerStream> {
        Ok(PeerStream {
            stream,
            peer: LearningIterationEvidencePeerV1 {
                uid: process::PEER_UID,
                pid: process.peer.pid,
                boot_id: process.peer.boot_id.clone(),
                process_start_ticks: process.peer.process_start_ticks,
                actor_id: actor.clone(),
            },
            original_owner_pidfd: process::pin(process.peer.pid)?,
            timeout: Duration::from_millis(100),
            lifetime,
        })
    };
    let task = |stream: UnixStream| -> anyhow::Result<TaskStream> {
        Ok(TaskStream {
            stream,
            peer: crate::AgentdRootAuthorityPeer {
                pid: process.peer.pid,
                boot_id: process.peer.boot_id.clone(),
                process_start_ticks: process.peer.process_start_ticks,
            },
            uid: process::PEER_UID,
            original_task_pidfd: process::pin(process.peer.pid)?,
            timeout: Duration::from_millis(100),
            lifetime,
        })
    };
    let [
        experience,
        dataset,
        trainer,
        selector,
        version,
        next_use,
        completion,
        candidate,
        evaluator,
        model,
    ] = streams;
    let owners = &profile.initial().owners;
    Ok(OriginalCellQ24CandidateStageStreamsV1 {
        common: OriginalCellQ24NoUpdateStageStreamsV1 {
            experience: peer(experience, &owners.experience)?,
            dataset: peer(dataset, &owners.dataset)?,
            trainer: peer(trainer, &owners.trainer)?,
            selector: peer(selector, &owners.selector)?,
            version: task(version)?,
            next_use: peer(next_use, &owners.next_use_observer)?,
            completion: task(completion)?,
        },
        candidate_material: peer(candidate, &owners.trainer)?,
        evaluator: peer(evaluator, &owners.evaluator)?,
        model: peer(model, &owners.proposal)?,
    })
}

fn transfer(
    profile: &RootResidentLearningProfileV3,
    streams: OriginalCellQ24CandidateStageStreamsV1,
) -> anyhow::Result<(RootCandidateStageHandoffV1, Instant)> {
    let (send, receive) = UnixDatagram::pair()?;
    let root = process::process(std::process::id())?;
    let sender = process::pin(root.pid)?;
    let recipient = process::pin(root.pid)?;
    crate::send_root_candidate_stage_handoff(
        send,
        &sender,
        root,
        &recipient,
        profile,
        streams,
        Duration::from_secs(1),
    )?;
    let after_send = Instant::now();
    let received =
        crate::receive_root_candidate_stage_handoff(receive, profile, Duration::from_secs(1))?;
    Ok((received, after_send))
}

fn consumer(
    process: &process::PeerProcess,
    stream: UnixStream,
    lifetime: Duration,
) -> anyhow::Result<RootResidentLearningConsumerV3> {
    Ok(RootResidentLearningConsumerV3 {
        stream,
        peer: crate::AgentdRootAuthorityPeer {
            pid: process.peer.pid,
            boot_id: process.peer.boot_id.clone(),
            process_start_ticks: process.peer.process_start_ticks,
        },
        uid: process::PEER_UID,
        original_consumer_pidfd: process::pin(process.peer.pid)?,
        timeout: Duration::from_millis(100),
        lifetime,
    })
}

fn lifetimes(streams: &OriginalCellQ24CandidateStageStreamsV1) -> [Duration; 10] {
    let common = &streams.common;
    [
        common.experience.lifetime,
        common.dataset.lifetime,
        common.trainer.lifetime,
        common.selector.lifetime,
        common.version.lifetime,
        common.next_use.lifetime,
        common.completion.lifetime,
        streams.candidate_material.lifetime,
        streams.evaluator.lifetime,
        streams.model.lifetime,
    ]
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_role_handoff_elapsed_real_time_cannot_renew_any_original_deadline()
-> anyhow::Result<()> {
    let (fixture, _) = material().await?;
    let root = root(&fixture)?;
    let mut peer = process::PeerProcess::start()?;
    let (streams, a) = peer.take_streams()?;
    drop(a);
    let original = Duration::from_secs(1);
    let (handoff, after_send) = transfer(
        &root.profile,
        role_streams(&peer, streams, &root.profile, original)?,
    )?;
    tokio::time::sleep(Duration::from_millis(100)).await;
    let (streams, end) = handoff.into_original_streams(&root.profile)?;
    assert!(
        end <= after_send + original,
        "the same absolute end must survive delivery delay"
    );
    assert!(
        lifetimes(&streams)
            .into_iter()
            .all(|remaining| remaining < original - Duration::from_millis(80))
    );
    // Every returned real socket still pins the same dedicated process. This
    // does not make these deliberately idle endpoints into original role owners.
    assert_eq!(streams.common.trainer.peer.pid, peer.peer.pid);
    drop(streams);
    peer.finish()?;

    let mut peer = process::PeerProcess::start()?;
    let (streams, a) = peer.take_streams()?;
    drop(a);
    let (handoff, _) = transfer(
        &root.profile,
        role_streams(&peer, streams, &root.profile, Duration::from_millis(50))?,
    )?;
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert!(handoff.into_original_streams(&root.profile).is_err());
    peer.finish()?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_role_admission_rejects_actual_uid_pidfd_and_process_start_mismatch()
-> anyhow::Result<()> {
    let (fixture, protocol) = material().await?;
    let original = fixture.bytes()?;
    let root = root(&fixture)?;
    for attack in ["uid", "pidfd", "process-start"] {
        let mut peer = process::PeerProcess::start()?;
        let (streams, a) = peer.take_streams()?;
        drop(a);
        let mut streams = role_streams(&peer, streams, &root.profile, Duration::from_secs(2))?;
        match attack {
            "uid" => streams.model.peer.uid = 60002,
            "pidfd" => streams.model.original_owner_pidfd = process::pin(std::process::id())?,
            "process-start" => {
                streams.model.peer.process_start_ticks = streams
                    .model
                    .peer
                    .process_start_ticks
                    .checked_add(1)
                    .ok_or_else(|| anyhow::anyhow!("fixture process start overflow"))?
            }
            _ => unreachable!(),
        }
        let (handoff, _) = transfer(&root.profile, streams)?;
        let (streams, _) = handoff.into_original_streams(&root.profile)?;
        // Use the unmodified public factory, including actual SO_PEERCRED and
        // pidfd validation. No same-UID test channel or mocked return is admitted.
        assert!(
            OriginalCellQ24CandidateStageOwnersV1::from_original_streams(
                fixture.config.clone(),
                streams,
                protocol.clone(),
                fixture.training_baseline(),
            )
            .is_err(),
            "{attack}"
        );
        peer.finish()?;
        assert_eq!(fixture.bytes()?, original);
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_role_receiver_refuses_another_real_recipient_or_registered_profile()
-> anyhow::Result<()> {
    let (fixture, _) = material().await?;
    let original = root(&fixture)?;
    let other = root(&fixture)?;
    assert_ne!(original.profile.binding(), other.profile.binding());
    for wrong_recipient in [true, false] {
        let mut peer = process::PeerProcess::start()?;
        let (streams, a) = peer.take_streams()?;
        drop(a);
        let streams = role_streams(&peer, streams, &original.profile, Duration::from_secs(2))?;
        let (send, receive) = UnixDatagram::pair()?;
        let creator = process::pin(std::process::id())?;
        let recipient = if wrong_recipient {
            crate::AgentdRootAuthorityPeer {
                pid: peer.peer.pid,
                boot_id: peer.peer.boot_id.clone(),
                process_start_ticks: peer.peer.process_start_ticks,
            }
        } else {
            process::process(std::process::id())?
        };
        let recipient_pin = process::pin(recipient.pid)?;
        crate::send_root_candidate_stage_handoff(
            send,
            &creator,
            recipient,
            &recipient_pin,
            &original.profile,
            streams,
            Duration::from_secs(1),
        )?;
        let expected = if wrong_recipient {
            &original.profile
        } else {
            &other.profile
        };
        assert!(
            crate::receive_root_candidate_stage_handoff(receive, expected, Duration::from_secs(1))
                .is_err()
        );
        peer.finish()?;
    }
    Ok(())
}
