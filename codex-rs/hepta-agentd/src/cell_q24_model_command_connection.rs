//! Initial fixed Model peer capability, consumed only after actual D/T/E.
//! Neither late binding nor recovery restarts its original process deadline.
use super::Error;
use super::OriginalCellQ24ModelCommandClientV1;
use super::client::Channel;
use super::context::Context;
use super::now;
use super::require_clock;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

enum Origin {
    Fresh,
    Recovered(Option<Box<(LearningIterationSnapshotV1, Digest32)>>),
}
pub struct OriginalCellQ24ModelCommandConnectionV1 {
    peer: HostAuthorityPeerChannel,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    registration: OriginalCellEvaluationPanelRegistrationV1,
    initial_binding: Digest32,
    observed_at: u64,
    origin: Origin,
}
impl OriginalCellQ24ModelCommandConnectionV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            crate::OriginalCellQ24NoUpdatePeerStreamV1 {
                stream,
                peer,
                original_owner_pidfd,
                timeout,
                lifetime,
            },
            material,
            registration,
            Origin::Fresh,
        )
    }
    /// A checkpoint can pin the original record. It never grants Execute and
    /// is authenticated only after the actual original D/T/E have been read.
    #[expect(
        clippy::too_many_arguments,
        reason = "The public V1 peer constructor retains its original positional signature"
    )]
    pub fn recover_from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        expected: Option<(LearningIterationSnapshotV1, Digest32)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            crate::OriginalCellQ24NoUpdatePeerStreamV1 {
                stream,
                peer,
                original_owner_pidfd,
                timeout,
                lifetime,
            },
            material,
            registration,
            Origin::Recovered(expected.map(Box::new)),
        )
    }

    /// Recover the original Model peer against its optional pinned checkpoint.
    pub fn recover_from_original_peer_stream(
        input: crate::OriginalCellQ24NoUpdatePeerStreamV1,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        expected: Option<(LearningIterationSnapshotV1, Digest32)>,
    ) -> Result<Self, Error> {
        Self::recover_from_original_stream(
            input.stream,
            input.peer,
            input.original_owner_pidfd,
            material,
            registration,
            expected,
            input.timeout,
            input.lifetime,
        )
    }
    fn bind_original_stream(
        transport: crate::OriginalCellQ24NoUpdatePeerStreamV1,

        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,

        origin: Origin,
    ) -> Result<Self, Error> {
        let crate::OriginalCellQ24NoUpdatePeerStreamV1 {
            stream,
            peer,
            original_owner_pidfd,
            timeout,
            lifetime,
        } = transport;

        let (initial_binding, started) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        if peer.actor_id != material.initial.owners.proposal
            || material.initial.request.evaluation_profile != registration.evaluation_profile()
        {
            return Err(Error::Binding(
                "original Model actor and pre-registered panel",
            ));
        }
        let channel = original_owner_command_channel_v1(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            peer.uid,
            original_owner_pidfd,
            timeout,
            lifetime,
        )?;
        channel.check_peer_lifetime()?;
        let (current_binding, observed_at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        require_clock(started, observed_at)?;
        if current_binding != initial_binding {
            return Err(Error::Binding("same original Model initial context"));
        }
        Ok(Self {
            peer: channel,
            material,
            registration,
            initial_binding,
            observed_at,
            origin,
        })
    }
    pub fn bind_original_evaluation(
        self,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<OriginalCellQ24ModelCommandClientV1, Error> {
        let started = now()?;
        let context = Context::from_original(
            self.material,
            self.registration,
            dataset,
            training,
            evaluation,
        )?;
        context.require_qualified()?;
        self.peer.check_peer_lifetime()?;
        let current = context.authenticate(started)?;
        require_clock(self.observed_at, current)?;
        let (initial, verified) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &context.material,
            )?;
        require_clock(current, verified)?;
        if initial != self.initial_binding {
            return Err(Error::Binding("same original Model initial connection"));
        }
        let (execution_requested, retained) = match self.origin {
            Origin::Fresh => (false, None),
            Origin::Recovered(expected) => {
                let retained = expected
                    .map(|original| {
                        let (snapshot, material) = *original;
                        let original = snapshot
                            .receipts
                            .last()
                            .ok_or(Error::Binding("original Model checkpoint"))?;
                        let bytes =
                            wire::record_bytes(&context, material, original.observed_unix_seconds)?;
                        use base64::Engine;
                        let record = base64::engine::general_purpose::STANDARD_NO_PAD.encode(bytes);
                        let checked = wire::decode_completed(&context, &record, verified)?;
                        if checked.snapshot() != &snapshot {
                            return Err(Error::Binding("exact original Model checkpoint"));
                        }
                        Ok(checked)
                    })
                    .transpose()?;
                (true, retained)
            }
        };
        let binding = context.binding()?;
        Ok(OriginalCellQ24ModelCommandClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: self.peer,
                next: 1,
                execution_requested,
            })),
            context,
            binding,
            retained: Mutex::new(retained),
            observed_at: verified,
        })
    }
}
