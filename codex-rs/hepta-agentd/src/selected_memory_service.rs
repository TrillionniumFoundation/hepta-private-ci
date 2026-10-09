//! An already-selected parameter consumer in the existing RuntimeTasks host.
//! These are references to existing owners, never another owner or database.
//! The Supervisor supplies active ABI/cutover and retirement callbacks; each
//! request independently requires final-use authority. No default activation.
use std::collections::BTreeSet;
use std::sync::Arc;

use crate::MemoryServingQualificationV1;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_control_plane::ActiveRuntimeModuleV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_fleet::FleetRevocationCoordinator;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;
use tokio::sync::RwLock;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::*;
use crate::AgentdError;
use crate::MemoryServingProcessV1;
use crate::MemoryServingQueryV1;
use crate::MemoryServingResultV1;
use crate::RuntimeTasks;

#[path = "memory_serving_fleet.rs"]
mod fleet;
use fleet::require_current_memory_fleet_v1;

/// Host-owned wiring. Never populate these from request JSON or model output.
/// Epoch/trust updates must replace the verifier in the SAME shared handle;
/// retaining an old copy is not a trust-refresh protocol. Clock is the existing
/// owners' trusted Unix-microsecond clock, not the request's question timestamp.
#[derive(Clone)]
pub struct MemoryServingOwnerHandlesV1 {
    pub replay: Arc<AgentdSharedReplayHostV1>,
    /// The actual enrolled fleet authority feed; no stale backup/local default.
    pub fleet: Arc<Mutex<FleetRevocationCoordinator>>,
    pub ledger: Arc<Mutex<LedgerWriter>>,
    pub artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub selector: Arc<RwLock<ArtifactSelectionVerifierV1>>,
    pub evidence: Arc<RwLock<LearningEvidenceVerifierV1>>,
    /// Existing source owner's live withdrawal feed for delivered audit excerpts.
    /// Must fail when that owner cannot supply a fresh view; never default empty.
    pub audit_withdrawals:
        Arc<dyn Fn() -> Result<BTreeSet<Digest32>, SharedMemoryTrainingError> + Send + Sync>,
    pub clock: Arc<dyn Fn() -> Result<u64, SharedMemoryTrainingError> + Send + Sync>,
}

enum Invocation {
    Binding(
        MemoryServingQueryV1,
        oneshot::Sender<Result<FinalUseBinding, String>>,
    ),
    Execute(
        MemoryServingQueryV1,
        VerifiedUseToken,
        oneshot::Sender<Result<MemoryServingResultV1, String>>,
    ),
}

/// Bounded typed ingress for the current service generation. Old handles close
/// on retirement. Dropped/full requests are not retried and never grant effects.
#[derive(Clone)]
pub struct MemoryServingHandleV1 {
    sender: mpsc::Sender<Invocation>,
}
impl MemoryServingHandleV1 {
    pub async fn binding(&self, query: MemoryServingQueryV1) -> Result<FinalUseBinding, String> {
        let (send, receive) = oneshot::channel();
        self.sender
            .try_send(Invocation::Binding(query, send))
            .map_err(|_| "memory serving ingress unavailable or full")?;
        receive
            .await
            .map_err(|_| "memory serving generation retired")?
    }

    pub async fn execute(
        &self,
        query: MemoryServingQueryV1,
        token: VerifiedUseToken,
    ) -> Result<MemoryServingResultV1, String> {
        let (send, receive) = oneshot::channel();
        self.sender
            .try_send(Invocation::Execute(query, token, send))
            .map_err(|_| "memory serving ingress unavailable or full")?;
        receive
            .await
            .map_err(|_| "memory serving generation retired")?
    }
}

/// Owns one non-clone selected model within an already-admitted process. It
/// cannot issue selection, hold a writer lease, migrate registry state or sign.
pub struct SelectedMemoryServiceV1 {
    owners: MemoryServingOwnerHandlesV1,
    model: SelectedMemoryTensorModelV1,
    qualification: MemoryServingQualificationV1,
    process: MemoryServingProcessV1,
    node: StableId,
    receiver: mpsc::Receiver<Invocation>,
}
impl SelectedMemoryServiceV1 {
    pub fn new(
        owners: MemoryServingOwnerHandlesV1,
        model: SelectedMemoryTensorModelV1,
        qualification: MemoryServingQualificationV1,
        process: MemoryServingProcessV1,
        node: StableId,
    ) -> (Self, MemoryServingHandleV1) {
        let (sender, receiver) = mpsc::channel(16);
        (
            Self {
                owners,
                model,
                qualification,
                process,
                node,
                receiver,
            },
            MemoryServingHandleV1 { sender },
        )
    }

    /// Attach to the actual task host only after Supervisor selection/handoff.
    /// No alternate routing map or locally writable generation checkpoint exists.
    pub fn spawn<Q, R>(
        self,
        tasks: &mut RuntimeTasks,
        active: &ActiveRuntimeModuleV1,
        implementation: &RuntimeModuleAbiV1,
        quarantine: Q,
        retire: R,
    ) -> Result<(), AgentdError>
    where
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
        R: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        let manifest = self.model.pinned.manifest();
        if self.model.unavailable
            || implementation.state_class != RuntimeModuleStateClassV1::Stateless
            || !implementation.authoritative_domains.is_empty()
            || implementation.implementation_digest != self.process.runtime_digest()
            || implementation.candidate_artifact_digest != manifest.content_digest
            || implementation.generation != self.qualification.route_generation()
            || !self.qualification.matches(manifest)
        {
            return Err(AgentdError::Protocol(
                "selected memory service ABI mismatch".into(),
            ));
        }
        tasks.spawn_bound_optional_service(
            active,
            implementation,
            move |stop| self.run(stop),
            quarantine,
            retire,
        )
    }

    async fn run(mut self, stop: CancellationToken) -> Result<(), AgentdError> {
        loop {
            let request = tokio::select! {
                biased;
                _ = stop.cancelled() => { self.receiver.close(); return Ok(()); }
                value = self.receiver.recv() => match value {
                    Some(value) => value,
                    None => return Ok(()),
                },
            };
            match request {
                Invocation::Binding(query, response) => {
                    let fleet = self.owners.fleet.lock().await;
                    let current = self.owners.evidence.read().await;
                    let result = require_current_memory_fleet_v1(&fleet, self.node.as_str())
                        .and_then(|_| (self.owners.clock)())
                        .and_then(|now| {
                            self.qualification
                                .revalidate_current(
                                    &current,
                                    &(self.owners.audit_withdrawals)()?,
                                    now,
                                )
                                .map_err(|_| {
                                    SharedMemoryTrainingError::Invalid("stale qualification")
                                })
                        })
                        .and_then(|_| {
                            self.owners.replay.selected_memory_serving_binding_v1(
                                &self.model,
                                &self.qualification,
                                &query,
                                &self.process,
                                &self.node,
                            )
                        })
                        .map_err(|error| error.to_string());
                    let _ = response.send(result);
                }
                Invocation::Execute(query, token, response) => {
                    if response.is_closed() {
                        continue;
                    }
                    let request_stop = stop.child_token();
                    let mut response = Some(response);
                    let result = self
                        .execute(query, token, &request_stop, &mut response)
                        .await;
                    let failed = result.is_err();
                    if let Some(response) = response {
                        let message = result.err().map_or_else(
                            || "memory result was not delivered".to_owned(),
                            |error| error.to_string(),
                        );
                        let _ = response.send(Err(message));
                    }
                    if stop.is_cancelled() {
                        self.receiver.close();
                        return Ok(());
                    }
                    if failed {
                        self.receiver.close();
                        return Err(AgentdError::Protocol(
                            "selected memory execution quarantined".into(),
                        ));
                    }
                }
            }
        }
    }

    async fn execute(
        &mut self,
        query: MemoryServingQueryV1,
        token: VerifiedUseToken,
        stop: &CancellationToken,
        response: &mut Option<oneshot::Sender<Result<MemoryServingResultV1, String>>>,
    ) -> Result<(), SharedMemoryTrainingError> {
        // Stable order: fleet, ledger, artifacts, selector, evidence. All
        // guards drop before CPU work, and are reacquired before delivery.
        let (fleet_head, job, payload) = {
            let fleet = self.owners.fleet.lock().await;
            let head = require_current_memory_fleet_v1(&fleet, self.node.as_str())?;
            let ledger = self.owners.ledger.lock().await;
            let artifacts = self.owners.artifacts.lock().await;
            let selector = self.owners.selector.read().await;
            let evidence = self.owners.evidence.read().await;
            let withdrawn_audit_roots = (self.owners.audit_withdrawals)()?;
            let (job, payload) = self
                .owners
                .replay
                .prepare_selected_memory_execution_v1(
                    &mut self.model,
                    &self.qualification,
                    &query,
                    &self.process,
                    &self.node,
                    &ledger,
                    &artifacts,
                    &selector,
                    &evidence,
                    &withdrawn_audit_roots,
                    || (self.owners.clock)(),
                )
                .await?;
            (head, job, payload)
        };
        let process = self.process.clone();
        let cancel = stop.child_token();
        let _cancel_on_drop = cancel.clone().drop_guard();
        // Deliberately AWAIT cancellation completion: retirement must not ack
        // while an unjoined process still computes using the prior generation.
        let worker_cancel = cancel.clone();
        let mut computation = tokio::task::spawn_blocking(move || {
            process.execute(job, payload, token, worker_cancel)
        });
        let sender = response.as_mut().ok_or(SharedMemoryTrainingError::Invalid(
            "missing delivery channel",
        ))?;
        let output = tokio::select! {
            result = &mut computation => result,
            _ = sender.closed() => {
                cancel.cancel();
                computation.await
            },
        }
        .map_err(|_| SharedMemoryTrainingError::Invalid("memory serving worker lost"))?
        .map_err(|_| SharedMemoryTrainingError::Invalid("memory serving worker rejected"))?;
        if stop.is_cancelled() || sender.is_closed() {
            return Err(SharedMemoryTrainingError::Invalid("memory service retired"));
        }
        let fleet = self.owners.fleet.lock().await;
        if require_current_memory_fleet_v1(&fleet, self.node.as_str())? != fleet_head {
            return Err(SharedMemoryTrainingError::Invalid(
                "memory authority changed during execution",
            ));
        }
        let ledger = self.owners.ledger.lock().await;
        let artifacts = self.owners.artifacts.lock().await;
        let selector = self.owners.selector.read().await;
        let evidence = self.owners.evidence.read().await;
        let withdrawn_audit_roots = (self.owners.audit_withdrawals)()?;
        let output = self
            .owners
            .replay
            .finish_selected_memory_execution_v1(
                &mut self.model,
                &self.qualification,
                output,
                &ledger,
                &artifacts,
                &selector,
                &evidence,
                &withdrawn_audit_roots,
                || (self.owners.clock)(),
            )
            .await?;
        if stop.is_cancelled() {
            self.model.unavailable = true;
            return Err(SharedMemoryTrainingError::Invalid(
                "memory service retired before delivery",
            ));
        }
        // Synchronous send is inside the owner critical section: no fleet,
        // artifact or trust mutation can interleave between check and delivery.
        response
            .take()
            .ok_or(SharedMemoryTrainingError::Invalid(
                "missing delivery channel",
            ))?
            .send(Ok(output))
            .map_err(|_| SharedMemoryTrainingError::Invalid("delivery receiver closed"))?;
        Ok(())
    }
}
