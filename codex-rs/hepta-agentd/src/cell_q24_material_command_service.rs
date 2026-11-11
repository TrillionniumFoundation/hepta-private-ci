//! Original dual-role bootstrap consumes the pair exactly once. The shared
//! admission bits belong to this host, never to a connection or read-only view.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::sync::Semaphore;

use super::Error;
use super::OriginalCellQ24MaterialCommandReceiptV1;
use super::OriginalCellQ24MaterialReceiptConfigV1;
use super::Role;
use super::now;
use super::wire;
use crate::AgentdIdentity;
use crate::AgentdRootAuthorityPeer;
use crate::CircuitTaskSourceReadbackV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24MaterialEvidenceErrorV1;
use crate::OriginalCellQ24MaterialEvidenceOwnerV1;
use crate::OriginalCellQ24MaterialReceiptErrorV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::OriginalCellQ24MaterialReceiptSourcesV1;
use crate::OriginalCellQ24MaterialSourceErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

pub struct OriginalCellQ24MaterialCommandOwnerV1<
    EW: AnchorWitnessStore,
    DW: AnchorWitnessStore,
    SW: AnchorWitnessStore,
> {
    original: OriginalCellQ24MaterialEvidenceOwnerV1<EW, DW, SW>,
    binding: Digest32,
    admitted: AtomicU8,
    connections: Semaphore,
}

impl<EW: AnchorWitnessStore, DW: AnchorWitnessStore, SW: AnchorWitnessStore>
    OriginalCellQ24MaterialCommandOwnerV1<EW, DW, SW>
{
    /// Only the consuming original-pair bootstrap may invoke this constructor.
    /// A recovered pair supplies no new-work admission, even for Missing.
    pub(crate) fn from_original_pair(
        owners: OriginalCellQ24MaterialReceiptOwnersV1<EW, DW>,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        source: CircuitTaskSourceReadbackV1<SW>,
        identity: AgentdIdentity,
        ledger: Arc<Mutex<LedgerWriter>>,
        baseline: Arc<LoadedCellQ24ModelV1>,
        allow_new_commands: bool,
    ) -> Result<Self, Error> {
        let binding = wire::context_binding(&config, now()?)?;
        let original = OriginalCellQ24MaterialEvidenceOwnerV1::from_original_owners(
            owners, config, source, identity, ledger, baseline,
        )
        .map_err(|_| Error::Binding("same consumed original Material pair"))?;
        Ok(Self {
            original,
            binding,
            admitted: AtomicU8::new(if allow_new_commands { 0 } else { 3 }),
            connections: Semaphore::new(4),
        })
    }

    pub fn serve_experience_commands(
        &self,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        self.serve_role_commands(
            Role::Experience,
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )
    }

    pub fn serve_dataset_commands(
        &self,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        self.serve_role_commands(
            Role::Dataset,
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )
    }

    fn serve_role_commands(
        &self,
        role: Role,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let _permit = self.connections.try_acquire().map_err(|_| Error::Busy)?;
        let mut channel = original_owner_command_channel_v1(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )?;
        self.serve_command_channel(role, &mut channel)
    }

    fn serve_command_channel(
        &self,
        role: Role,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                self.command_response(role, bytes, request_id)
                    .map_err(|error| {
                        failure = Some(error);
                        HostIssuerTransportError::InvalidRequest
                    })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(request_id - 1),
                Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
            }
        }
        Err(Error::Unavailable)
    }

    fn command_response(
        &self,
        role: Role,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let started_at = now()?;
        let config = &self.original.config;
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_context(config, role, self.binding, request_id)?;
        if wire::context_binding(config, started_at)? != self.binding {
            return Err(Error::Binding("unchanged original Material bootstrap"));
        }
        let result = match request.action {
            wire::Action::Execute => {
                let bit = match role {
                    Role::Experience => 1,
                    Role::Dataset => 2,
                };
                if self.admitted.fetch_or(bit, Ordering::AcqRel) & bit != 0 {
                    Err(Error::ReadbackRequired)
                } else if started_at >= config.initial.request.envelope.expiry_unix_seconds {
                    Err(Error::DeadlineExceeded)
                } else {
                    self.original_cut(role, wire::Action::Execute)
                }
            }
            wire::Action::Readback => self.original_cut(role, wire::Action::Readback),
        };
        let fresh_now = now()?;
        if fresh_now < started_at || wire::context_binding(config, fresh_now)? != self.binding {
            return Err(Error::Binding("Material command clock after original I/O"));
        }
        let result = match result {
            Ok(completed) => wire::encode_completed(config, role, completed, fresh_now)?,
            Err(error) => original_state(error),
        };
        let encoded = serde_json::to_vec(&wire::Response::from_request(&request, result))?;
        if encoded.is_empty() || encoded.len() > 16_384 {
            return Err(Error::Binding("bounded original Material response"));
        }
        Ok(encoded)
    }

    fn original_cut(
        &self,
        role: Role,
        action: wire::Action,
    ) -> Result<OriginalCellQ24MaterialCommandReceiptV1, Error> {
        let mut owners = self.original.owners.try_lock().map_err(|_| Error::Busy)?;
        let mut ledger = self.original.ledger.try_lock().map_err(|_| Error::Busy)?;
        let original: &mut OriginalCellQ24MaterialReceiptOwnersV1<EW, DW> = &mut owners;
        let config = &self.original.config;
        let initial = &config.initial;
        let experience = if role == Role::Experience && action == wire::Action::Execute {
            original.attest_experience(OriginalCellQ24MaterialReceiptSourcesV1 {
                snapshot: initial,
                source: &self.original.source,
                identity: &self.original.identity,
                ledger: &mut ledger,
                baseline: &self.original.baseline,
            })?
        } else {
            // Dataset can only read its predecessor; this never admits Experience.
            original.readback_experience(OriginalCellQ24MaterialReceiptSourcesV1 {
                snapshot: initial,
                source: &self.original.source,
                identity: &self.original.identity,
                ledger: &mut ledger,
                baseline: &self.original.baseline,
            })?
        };
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
        coordinator.record(
            experience.receipt.clone(),
            experience.receipt.observed_unix_seconds,
        )?;
        let mut evidence = vec![experience.attestation.clone()];
        if role == Role::Dataset {
            let prefix = coordinator.snapshot().clone();
            let dataset = match action {
                wire::Action::Execute => {
                    original.attest_dataset(OriginalCellQ24MaterialReceiptSourcesV1 {
                        snapshot: &prefix,
                        source: &self.original.source,
                        identity: &self.original.identity,
                        ledger: &mut ledger,
                        baseline: &self.original.baseline,
                    })?
                }
                wire::Action::Readback => {
                    original.readback_dataset(OriginalCellQ24MaterialReceiptSourcesV1 {
                        snapshot: &prefix,
                        source: &self.original.source,
                        identity: &self.original.identity,
                        ledger: &mut ledger,
                        baseline: &self.original.baseline,
                    })?
                }
            };
            let current = original.readback_dataset(OriginalCellQ24MaterialReceiptSourcesV1 {
                snapshot: &prefix,
                source: &self.original.source,
                identity: &self.original.identity,
                ledger: &mut ledger,
                baseline: &self.original.baseline,
            })?;
            if current.receipt != dataset.receipt || current.attestation != dataset.attestation {
                return Err(Error::CommitUncertain);
            }
            coordinator.record(dataset.receipt, dataset.attestation.issued_at)?;
            evidence.push(dataset.attestation);
        }
        let current = original.readback_experience(OriginalCellQ24MaterialReceiptSourcesV1 {
            snapshot: coordinator.snapshot(),
            source: &self.original.source,
            identity: &self.original.identity,
            ledger: &mut ledger,
            baseline: &self.original.baseline,
        })?;
        if current.receipt != experience.receipt || current.attestation != experience.attestation {
            return Err(Error::CommitUncertain);
        }
        config.scope.validate_snapshot(coordinator.snapshot())?;
        let snapshot = coordinator.snapshot().clone();
        drop(ledger);
        drop(owners);
        Ok(OriginalCellQ24MaterialCommandReceiptV1 { snapshot, evidence })
    }

    /// These fixed-role delegates expose no underlying pair or execution API.
    /// They retain the existing read-only purposes and 500 ms transport policy.
    pub fn serve_experience_readback(
        &self,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        original_consumer_pidfd: OwnedFd,
    ) -> Result<(), OriginalCellQ24MaterialEvidenceErrorV1> {
        OriginalCellQ24MaterialEvidenceOwnerV1::serve_readback(
            &self.original,
            Role::Experience,
            stream,
            policy,
            original_consumer_pidfd,
        )
    }

    pub fn serve_dataset_readback(
        &self,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        original_consumer_pidfd: OwnedFd,
    ) -> Result<(), OriginalCellQ24MaterialEvidenceErrorV1> {
        OriginalCellQ24MaterialEvidenceOwnerV1::serve_readback(
            &self.original,
            Role::Dataset,
            stream,
            policy,
            original_consumer_pidfd,
        )
    }

    pub fn serve_dataset_source(
        &self,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        original_consumer_pidfd: OwnedFd,
    ) -> Result<(), OriginalCellQ24MaterialSourceErrorV1> {
        OriginalCellQ24MaterialEvidenceOwnerV1::serve_material_source(
            &self.original,
            stream,
            policy,
            original_consumer_pidfd,
        )
    }
}

fn original_state(error: Error) -> wire::CommandResult {
    match error {
        Error::Busy => wire::CommandResult::Busy,
        Error::ReadbackRequired => wire::CommandResult::ReadbackRequired,
        Error::DeadlineExceeded => wire::CommandResult::Expired,
        Error::Material(OriginalCellQ24MaterialReceiptErrorV1::Owner(
            LearningOriginalOwnerErrorV1::Pending,
        )) => wire::CommandResult::Pending,
        Error::Material(OriginalCellQ24MaterialReceiptErrorV1::Owner(
            LearningOriginalOwnerErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing),
        )) => wire::CommandResult::Missing,
        // Any other failure may follow a durable claim or signature completion.
        // It is never a fresh Missing, an inferred NoUpdate, or retry permission.
        _ => wire::CommandResult::Uncertain,
    }
}

#[cfg(test)]
#[path = "cell_q24_material_command_tests.rs"]
mod tests;
