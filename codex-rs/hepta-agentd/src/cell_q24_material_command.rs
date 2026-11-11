//! Purpose-fixed original Material commands. Only the original host owns keys,
//! sources and journals; a consumer receives a connected process capability.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::OriginalCellQ24MaterialEvidenceRoleV1 as Role;
use super::wire as evidence_wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationCheckpointErrorV1;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24MaterialReceiptErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "cell_q24_material_command_service.rs"]
mod serving;
#[path = "cell_q24_material_command_wire.rs"]
mod wire;
pub use serving::OriginalCellQ24MaterialCommandOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24MaterialCommandErrorV1 {
    #[error("original Material command binding: {0}")]
    Binding(&'static str),
    #[error("original Material command channel is unavailable")]
    Unavailable,
    #[error("original Material completion is uncertain; read the same pair")]
    CommitUncertain,
    #[error("original Material execution already admitted; readback only")]
    ReadbackRequired,
    #[error("original Material owner or ledger is occupied")]
    Busy,
    #[error("original Material result is missing")]
    Missing,
    #[error("original Material result is pending")]
    Pending,
    #[error("original Material work deadline expired")]
    DeadlineExceeded,
    #[error("original Material transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original Material owner: {0}")]
    Material(#[from] OriginalCellQ24MaterialReceiptErrorV1),
    #[error("original Material source policy: {0}")]
    Dataset(#[from] crate::CellQ24DatasetErrorV1),
    #[error("original Material iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Material evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original Material cut codec: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original Material command encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}

type Error = OriginalCellQ24MaterialCommandErrorV1;

/// A verified original cut and its complete retained signatures. This is not
/// permission to sign, replace source material, or admit another execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellQ24MaterialCommandReceiptV1 {
    snapshot: LearningIterationSnapshotV1,
    evidence: Vec<SignedLearningEvidenceV1>,
}

impl OriginalCellQ24MaterialCommandReceiptV1 {
    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        // The private decoder accepts exactly one or two original receipts.
        &self.snapshot.receipts[self.snapshot.receipts.len() - 1]
    }

    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.evidence[self.evidence.len() - 1]
    }

    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    pub fn attestations(&self) -> &[SignedLearningEvidenceV1] {
        &self.evidence
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
    execution_requested: bool,
}

pub struct OriginalCellQ24MaterialCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    config: OriginalCellQ24MaterialReceiptConfigV1,
    role: Role,
    binding: Digest32,
    retained: Mutex<Option<OriginalCellQ24MaterialCommandReceiptV1>>,
}

impl OriginalCellQ24MaterialCommandClientV1 {
    pub fn from_original_experience_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(stream, peer, original_owner_pidfd, config,
            Role::Experience, timeout, lifetime, /*readback_only*/ false, None)
    }

    pub fn from_original_dataset_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(stream, peer, original_owner_pidfd, config,
            Role::Dataset, timeout, lifetime, /*readback_only*/ false, None)
    }

    /// Reconnection never restores execution. A retained original cut, when
    /// available, pins every receipt and full signature across this recovery.
    pub fn recover_original_experience_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        expected: Option<(LearningIterationSnapshotV1, Vec<SignedLearningEvidenceV1>)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(stream, peer, original_owner_pidfd, config,
            Role::Experience, timeout, lifetime, /*readback_only*/ true,
            expected.map(|(snapshot, evidence)| OriginalCellQ24MaterialCommandReceiptV1 { snapshot, evidence }))
    }

    pub fn recover_original_dataset_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        expected: Option<(LearningIterationSnapshotV1, Vec<SignedLearningEvidenceV1>)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(stream, peer, original_owner_pidfd, config,
            Role::Dataset, timeout, lifetime, /*readback_only*/ true,
            expected.map(|(snapshot, evidence)| OriginalCellQ24MaterialCommandReceiptV1 { snapshot, evidence }))
    }

    fn bind_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        role: Role,
        timeout: Duration,
        lifetime: Duration,
        readback_only: bool,
        expected: Option<OriginalCellQ24MaterialCommandReceiptV1>,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = wire::context_binding(&config, started_at)?;
        if peer.actor_id != *config.initial.owners.owner(role.stage()) {
            return Err(Error::Binding("original role-selected Material process"));
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
        let fresh_now = now()?;
        if fresh_now < started_at || wire::context_binding(&config, fresh_now)? != binding {
            return Err(Error::Binding("Material command bootstrap clock"));
        }
        let retained = expected
            .map(|original| wire::authenticate_cut(&config, role, original, fresh_now))
            .transpose()?;
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                peer: channel,
                next_request_id: 1,
                execution_requested: readback_only,
            })),
            config,
            role,
            binding,
            retained: Mutex::new(retained),
        })
    }

    /// Execute this connection's one fixed stage once. Any admitted error or
    /// lost ACK requires actual readback of the same original pair.
    pub async fn execute(&self) -> Result<OriginalCellQ24MaterialCommandReceiptV1, Error> {
        if now()? >= self.config.initial.request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute).await
    }

    pub async fn readback(&self) -> Result<OriginalCellQ24MaterialCommandReceiptV1, Error> {
        self.exchange(wire::Action::Readback).await
    }

    /// Actual I/O precedes equality with the requested original receipt.
    /// This works for Experience before Dataset has ever been admitted.
    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let original = OriginalCellQ24MaterialCommandClientV1::readback(self).await?;
        if original.receipt() != expected {
            return Err(Error::Binding("exact original Material receipt"));
        }
        Ok(original.attestation().clone())
    }

    async fn exchange(&self, action: wire::Action)
        -> Result<OriginalCellQ24MaterialCommandReceiptV1, Error>
    {
        let started_at = now()?;
        wire::context_binding(&self.config, started_at)?;
        let mut channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
            if action == wire::Action::Execute
                && slot.as_ref().is_some_and(|channel| channel.execution_requested)
            {
                return Err(Error::ReadbackRequired);
            }
            let mut channel = slot.take().ok_or(Error::Unavailable)?;
            if action == wire::Action::Execute {
                channel.execution_requested = true;
            }
            channel
        };
        let request = wire::Request::new(&self.config, self.role, self.binding,
            channel.next_request_id, action);
        channel.next_request_id = channel.next_request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let encoded = serde_json::to_vec(&request)?;
        let (channel, bytes) = tokio::task::spawn_blocking(move || {
            let bytes = channel.peer.request(&encoded).map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((channel, bytes))
        }).await.map_err(|_| Error::CommitUncertain)??;
        let response: wire::Response = serde_json::from_slice(&bytes)?;
        response.require_request(&request)?;
        let fresh_now = now()?;
        if fresh_now < started_at || wire::context_binding(&self.config, fresh_now)? != self.binding {
            return Err(Error::Binding("Material command clock moved backwards"));
        }
        let result = match response.result {
            wire::CommandResult::Completed { snapshot, evidence } => {
                let completed = wire::decode_completed(&self.config, self.role, snapshot,
                    evidence, fresh_now)?;
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained.as_ref().is_some_and(|original| original != &completed) {
                    return Err(Error::Binding("unchanged original Material signatures"));
                }
                *retained = Some(completed.clone());
                Ok(completed)
            }
            wire::CommandResult::Missing => Err(Error::Missing),
            wire::CommandResult::Pending => Err(Error::Pending),
            wire::CommandResult::Busy => Err(Error::Busy),
            wire::CommandResult::Expired => Err(Error::DeadlineExceeded),
            wire::CommandResult::ReadbackRequired => Err(Error::ReadbackRequired),
            wire::CommandResult::Uncertain => return Err(Error::CommitUncertain),
        };
        channel.peer.check_peer_lifetime()?;
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        result
    }
}

fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .map_err(|_| Error::Binding("Material command clock before Unix epoch"))
}
