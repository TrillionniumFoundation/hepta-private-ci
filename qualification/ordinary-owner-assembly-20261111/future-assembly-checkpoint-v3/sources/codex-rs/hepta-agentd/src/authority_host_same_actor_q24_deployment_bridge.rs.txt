//! Convert authenticated progress plus independent Root-approved files into
//! actual one-shot host commands. No peer payload approves a Root scope.

use super::*;
use super::files::OriginalFile;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentProgress;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentRequest;

pub(super) fn apply_original_progress(
    files: &DeploymentFiles,
    request: &OriginalDeploymentRequest,
    commands: &mpsc::SyncSender<RootSameActorHostCommandV1>,
    acknowledgements: &mpsc::Receiver<RootSameActorHostAcknowledgementV1>,
    gate: &Arc<SameActorPhaseGate>,
    dispatched: &mut bool,
) -> io::Result<Option<String>> {
    let mut closing = CloseSameActorPhaseOnDrop::new(gate);
    files.require_deployment_files()?;
    gate.require_open()?;
    let result = match &request.progress {
        OriginalDeploymentProgress::InputsOpened => {
            let (initial, artifacts) =
                files.initial.original_phase_initial_inputs(files.consumer_uid)?;
            files.require_deployment_files()?;
            require_artifact_files(&artifacts)?;
            send_original_command(
                commands, RootSameActorHostCommandV1::Initial(initial), gate, dispatched,
            )?;
            (|| {
                let binding = require_original_acknowledgement(
                    receive_original_acknowledgement(acknowledgements, gate)?,
                    DeploymentStage::Initial,
                )?;
                files.require_deployment_files()?;
                require_artifact_files(&artifacts)?;
                gate.require_open()?;
                Ok(binding)
            })().map_err(|error| deployment_uncertain("original Initial host command", error))
        }
        OriginalDeploymentProgress::OriginalAPrepared { profile: observed } => {
            // The daemon supplies its actual Prepared observation, never Root
            // approval. Missing or unequal Root0600 material refuses this
            // request immediately; it is not a wait with a renewed deadline.
            let (profile_file, bytes) = MetadataFile::open_metadata(&files.data.learning_profile)?;
            let profile: crate::HostAuthorityLearningProfileV1 =
                serde_json::from_slice(&bytes).map_err(io::Error::other)?;
            if serde_json::to_vec(&profile).map_err(io::Error::other)?
                != serde_json::to_vec(observed).map_err(io::Error::other)?
            {
                return Err(io::Error::other("actual Prepared differs from the Root-approved profile"));
            }
            files.require_deployment_files()?;
            profile_file.require_metadata_unchanged()?;
            send_original_command(
                commands, RootSameActorHostCommandV1::Scoped(profile), gate, dispatched,
            )?;
            (|| {
                let binding = require_original_acknowledgement(
                    receive_original_acknowledgement(acknowledgements, gate)?,
                    DeploymentStage::Scoped,
                )?;
                files.require_deployment_files()?;
                profile_file.require_metadata_unchanged()?;
                gate.require_open()?;
                Ok(binding)
            })().map_err(|error| deployment_uncertain("original scoped host command", error))
        }
        OriginalDeploymentProgress::OriginalSelectionReady { canonical_material } => {
            let bytes = canonical_material.as_bytes();
            let (current, observation) = files.current.original_current_phase_inputs(
                &files.current_directory, files.consumer_uid,
                Digest32::of_bytes(bytes), bytes,
            )?;
            files.require_deployment_files()?;
            files.current.require_current_phase_observation(&observation)?;
            send_original_command(
                commands, RootSameActorHostCommandV1::Current(current), gate, dispatched,
            )?;
            (|| {
                let binding = require_original_acknowledgement(
                    receive_original_acknowledgement(acknowledgements, gate)?,
                    DeploymentStage::Current,
                )?;
                files.require_deployment_files()?;
                files.current.require_current_phase_observation(&observation)?;
                gate.require_open()?;
                Ok(binding)
            })().map_err(|error| deployment_uncertain("original Current host command", error))
        }
    }?;
    gate.require_open()?;
    closing.disarm();
    Ok(result)
}

fn send_original_command(
    sender: &mpsc::SyncSender<RootSameActorHostCommandV1>,
    command: RootSameActorHostCommandV1,
    gate: &Arc<SameActorPhaseGate>,
    dispatched: &mut bool,
) -> io::Result<()> {
    gate.require_open()?;
    sender.try_send(command)
        .map_err(|_| io::Error::other("original phase command queue is full or closed"))?;
    // Set only after the actual transfer. A lost response now remains uncertain
    // and cannot cause this command or its capability to be sent again.
    *dispatched = true;
    gate.notify_original_waiters();
    gate.require_open()
        .map(|_| ())
        .map_err(|error| deployment_uncertain("original Root command handoff", error))
}

pub(super) fn receive_original_acknowledgement(
    receiver: &mpsc::Receiver<RootSameActorHostAcknowledgementV1>,
    gate: &Arc<SameActorPhaseGate>,
) -> io::Result<RootSameActorHostAcknowledgementV1> {
    let mut closing = CloseSameActorPhaseOnDrop::new(gate);
    loop {
        let epoch = gate.original_wait_epoch()?;
        match receiver.try_recv() {
            Ok(value) => {
                gate.require_open()?;
                closing.disarm();
                return Ok(value);
            }
            Err(mpsc::TryRecvError::Empty) => gate.wait_original_change(epoch)?,
            Err(mpsc::TryRecvError::Disconnected) => {
                return Err(io::Error::other("original phase acknowledgement channel closed"));
            }
        }
    }
}

pub(super) fn require_original_acknowledgement(
    acknowledgement: RootSameActorHostAcknowledgementV1,
    stage: DeploymentStage,
) -> io::Result<Option<String>> {
    match (stage, acknowledgement) {
        (DeploymentStage::Initial, RootSameActorHostAcknowledgementV1::InitialRegistered { binding })
        | (DeploymentStage::Current, RootSameActorHostAcknowledgementV1::CurrentRegistered { binding }) => {
            let digest = binding.parse::<Digest32>().map_err(io::Error::other)?;
            if digest.is_zero() {
                return Err(io::Error::other("original registration acknowledgement binding missing"));
            }
            Ok(Some(binding))
        }
        (DeploymentStage::Scoped, RootSameActorHostAcknowledgementV1::ScopedRightsSent) => Ok(None),
        _ => Err(io::Error::other("original phase acknowledgement arrived out of order")),
    }
}

fn require_artifact_files(files: &[OriginalFile]) -> io::Result<()> {
    for file in files {
        file.require_original_file()?;
    }
    Ok(())
}
