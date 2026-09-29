//! Long-lived Agentd owner for governed plasticity proposal admission.
//!
//! The owner is deliberately internal to Agentd rather than a new public wire API.
//! Callers receive a bounded typed handle; all mutable proposal writers, current
//! artifact/learning frontiers, trust verification and external anchor stores stay
//! inside the daemon task. This is source composition only and grants no selection,
//! model installation, topology application, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdPlasticityHostErrorV1;
use crate::AgentdState;
use crate::AgentdTopologyAnchorStoreV1;
use crate::AgentdTopologyHostErrorV1;
use crate::AgentdTopologyWriterV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    Parameter(AgentdPlasticityHostErrorV1),
    Topology(AgentdTopologyHostErrorV1),
}

impl fmt::Display for PlasticityRuntimeCallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityRuntimeCallErrorV1 {}

enum PlasticityRuntimeCommandV1 {
    Parameter {
        request: Box<ParameterPlasticityProductRequestV1>,
        now: u64,
        response: oneshot::Sender<
            Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
    Topology {
        request: Box<TopologyPlasticityProductRequestV1>,
        now: u64,
        response: oneshot::Sender<
            Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
}

/// Bounded in-process product handle. It contains no writer, store or trust-root
/// material, so dropping/recreating a handle cannot create another owner.
#[derive(Clone)]
pub struct PlasticityRuntimeHandleV1 {
    sender: mpsc::Sender<PlasticityRuntimeCommandV1>,
}

impl PlasticityRuntimeHandleV1 {
    /// Connection liveness is not permission, proposal acceptance or completion.
    pub(crate) fn is_closed(&self) -> bool {
        self.sender.is_closed()
    }

    fn reserve_slot(
        &self,
    ) -> Result<mpsc::Permit<'_, PlasticityRuntimeCommandV1>, PlasticityRuntimeCallErrorV1> {
        if self.is_closed() {
            return Err(PlasticityRuntimeCallErrorV1::Closed);
        }
        self.sender.try_reserve().map_err(|error| match error {
            mpsc::error::TrySendError::Full(_) => PlasticityRuntimeCallErrorV1::Unavailable,
            mpsc::error::TrySendError::Closed(_) => PlasticityRuntimeCallErrorV1::Closed,
        })
    }

    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        // Bound admission itself, not just the queue behind arbitrarily many
        // suspended producers. No wait or retry is hidden in this handle.
        let permit = self.reserve_slot()?;
        let (response, receive) = oneshot::channel();
        permit.send(PlasticityRuntimeCommandV1::Parameter {
            request: Box::new(request),
            now,
            response,
        });
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        // Bound admission itself, not just the queue behind arbitrarily many
        // suspended producers. No wait or retry is hidden in this handle.
        let permit = self.reserve_slot()?;
        let (response, receive) = oneshot::channel();
        permit.send(PlasticityRuntimeCommandV1::Topology {
            request: Box::new(request),
            now,
            response,
        });
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }
}

/// Immutable construction envelope consumed exactly once by Agentd runtime
/// composition. Creating this value does not start a second owner or grant
/// proposal authority; the real daemon creates the bounded channel and retains
/// the resulting owner/handle pair for its generation.
pub struct PlasticityRuntimeBootstrapV1 {
    capacity: usize,
    artifacts: ArtifactRegistry,
    ledger: DurableLedger,
    owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
    verifier: LearningEvidenceVerifierV1,
    parameter_writer: AnchoredPlasticityWriterV1,
    parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
    topology_writer: AgentdTopologyWriterV1,
    topology_anchor_store: AgentdTopologyAnchorStoreV1,
}

impl PlasticityRuntimeBootstrapV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        capacity: usize,
        artifacts: ArtifactRegistry,
        ledger: DurableLedger,
        owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
        owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
        verifier: LearningEvidenceVerifierV1,
        parameter_writer: AnchoredPlasticityWriterV1,
        parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
        topology_writer: AgentdTopologyWriterV1,
        topology_anchor_store: AgentdTopologyAnchorStoreV1,
    ) -> Result<Self, AgentdError> {
        validate_plasticity_runtime_capacity(capacity)?;
        Ok(Self {
            capacity,
            artifacts,
            ledger,
            owner_evidence_resolver,
            owner_evidence_policy,
            verifier,
            parameter_writer,
            parameter_anchor_store,
            topology_writer,
            topology_anchor_store,
        })
    }

    pub(crate) fn into_channel(
        self,
    ) -> Result<(PlasticityRuntimeHandleV1, PlasticityRuntimeOwnerV1), AgentdError> {
        plasticity_runtime_channel_v1(
            self.capacity,
            self.artifacts,
            self.ledger,
            self.owner_evidence_resolver,
            self.owner_evidence_policy,
            self.verifier,
            self.parameter_writer,
            self.parameter_anchor_store,
            self.topology_writer,
            self.topology_anchor_store,
        )
    }
}

/// Exact mutable owner retained for the lifetime of the Agentd generation.
pub struct PlasticityRuntimeOwnerV1 {
    receiver: mpsc::Receiver<PlasticityRuntimeCommandV1>,
    artifacts: ArtifactRegistry,
    ledger: DurableLedger,
    owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
    verifier: LearningEvidenceVerifierV1,
    parameter_writer: AnchoredPlasticityWriterV1,
    parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
    topology_writer: AgentdTopologyWriterV1,
    topology_anchor_store: AgentdTopologyAnchorStoreV1,
}

#[allow(clippy::too_many_arguments)]
pub fn plasticity_runtime_channel_v1(
    capacity: usize,
    artifacts: ArtifactRegistry,
    ledger: DurableLedger,
    owner_evidence_resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    owner_evidence_policy: PlasticityOwnerEvidencePolicyV1,
    verifier: LearningEvidenceVerifierV1,
    parameter_writer: AnchoredPlasticityWriterV1,
    parameter_anchor_store: AgentdPlasticityAnchorStoreV1,
    topology_writer: AgentdTopologyWriterV1,
    topology_anchor_store: AgentdTopologyAnchorStoreV1,
) -> Result<(PlasticityRuntimeHandleV1, PlasticityRuntimeOwnerV1), AgentdError> {
    validate_plasticity_runtime_capacity(capacity)?;
    let (sender, receiver) = mpsc::channel(capacity);
    Ok((
        PlasticityRuntimeHandleV1 { sender },
        PlasticityRuntimeOwnerV1 {
            receiver,
            artifacts,
            ledger,
            owner_evidence_resolver,
            owner_evidence_policy,
            verifier,
            parameter_writer,
            parameter_anchor_store,
            topology_writer,
            topology_anchor_store,
        },
    ))
}

fn validate_plasticity_runtime_capacity(capacity: usize) -> Result<(), AgentdError> {
    if !(1..=MAX_PLASTICITY_RUNTIME_QUEUE).contains(&capacity) {
        return Err(AgentdError::Invalid(format!(
            "plasticity runtime queue capacity must be within 1..={MAX_PLASTICITY_RUNTIME_QUEUE}"
        )));
    }
    Ok(())
}

pub(crate) fn compose_plasticity_runtime_v1(
    state: &Arc<AgentdState>,
    bootstrap: Option<PlasticityRuntimeBootstrapV1>,
) -> Result<Option<PlasticityRuntimeOwnerV1>, AgentdError> {
    match bootstrap {
        Some(bootstrap) => {
            let (handle, owner) = bootstrap.into_channel()?;
            state.attach_plasticity_runtime(handle)?;
            Ok(Some(owner))
        }
        None => Ok(None),
    }
}

#[cfg(test)]
pub(crate) fn spawn_plasticity_runtime_v1(
    state: Arc<AgentdState>,
    owner: Option<PlasticityRuntimeOwnerV1>,
    cancellation: CancellationToken,
) -> tokio::task::JoinHandle<Result<(), AgentdError>> {
    tokio::spawn(async move {
        match owner {
            Some(owner) => owner.run(state, cancellation).await,
            None => {
                // Plasticity is opt-in. The absence of an explicitly composed
                // owner means this generation has no proposal writer.
                cancellation.cancelled().await;
                Ok(())
            }
        }
    })
}

impl PlasticityRuntimeOwnerV1 {
    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            let command = tokio::select! {
                biased;
                _ = cancellation.cancelled() => return Ok(()),
                command = self.receiver.recv() => command,
            };
            let Some(command) = command else {
                // Losing all producer handles is not a daemon failure. Keep the
                // exclusive stores/fences alive until the generation shuts down.
                cancellation.cancelled().await;
                return Ok(());
            };

            let ready = state.plasticity_admission_ready()?;
            match command {
                PlasticityRuntimeCommandV1::Parameter {
                    request,
                    now,
                    response,
                } => {
                    if !proposal_entry_open(ready, &cancellation, &response) {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                        continue;
                    }
                    let result = propose_agentd_plasticity_v1(
                        *request,
                        &self.artifacts,
                        &self.ledger,
                        self.owner_evidence_resolver.as_ref(),
                        &self.owner_evidence_policy,
                        &self.verifier,
                        &mut self.parameter_writer,
                        &mut self.parameter_anchor_store,
                        now,
                    )
                    .map_err(PlasticityRuntimeCallErrorV1::Parameter);
                    let _ = response.send(result);
                }
                PlasticityRuntimeCommandV1::Topology {
                    request,
                    now,
                    response,
                } => {
                    if !proposal_entry_open(ready, &cancellation, &response) {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                        continue;
                    }
                    let result = propose_agentd_topology_plasticity_v1(
                        *request,
                        &self.artifacts,
                        &self.ledger,
                        &self.verifier,
                        &mut self.topology_writer,
                        &mut self.topology_anchor_store,
                        now,
                    )
                    .map_err(PlasticityRuntimeCallErrorV1::Topology);
                    let _ = response.send(result);
                }
            }
        }
    }
}

// Only pre-entry abandonment is skipped. Once the synchronous durable owner
// call begins, its append/anchor/result obligations cannot be cancelled away.
fn proposal_entry_open<T>(
    ready: bool,
    cancellation: &CancellationToken,
    response: &oneshot::Sender<T>,
) -> bool {
    ready && !cancellation.is_cancelled() && !response.is_closed()
}

#[cfg(test)]
#[path = "plasticity_runtime_lifetime_tests.rs"]
mod lifetime_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_queue_capacity_is_bounded() {
        assert!(validate_plasticity_runtime_capacity(1).is_ok());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE).is_ok());
        assert!(validate_plasticity_runtime_capacity(0).is_err());
        assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE + 1).is_err());
    }

    #[test]
    fn proposal_capacity_is_reserved_without_waiting_and_recovers() {
        let (sender, _receiver) = mpsc::channel(1);
        let handle = PlasticityRuntimeHandleV1 { sender };
        let occupied = handle.reserve_slot().expect("first slot");
        assert!(matches!(
            handle.reserve_slot(),
            Err(PlasticityRuntimeCallErrorV1::Unavailable)
        ));
        drop(occupied);
        assert!(handle.reserve_slot().is_ok());
    }

    #[test]
    fn receiver_closure_is_not_an_overload_or_available_producer() {
        let (sender, receiver) = mpsc::channel(1);
        let handle = PlasticityRuntimeHandleV1 { sender };
        assert!(!handle.is_closed());
        drop(receiver);
        assert!(handle.is_closed());
        assert!(matches!(
            handle.reserve_slot(),
            Err(PlasticityRuntimeCallErrorV1::Closed)
        ));
    }

    #[test]
    fn cancelled_or_abandoned_proposals_cannot_enter_the_writer() {
        let cancellation = CancellationToken::new();
        let (response, receive) = oneshot::channel::<()>();
        assert!(proposal_entry_open(true, &cancellation, &response));
        assert!(!proposal_entry_open(false, &cancellation, &response));
        drop(receive);
        assert!(!proposal_entry_open(true, &cancellation, &response));
        let (response, _receive) = oneshot::channel::<()>();
        cancellation.cancel();
        assert!(!proposal_entry_open(true, &cancellation, &response));
    }
}
