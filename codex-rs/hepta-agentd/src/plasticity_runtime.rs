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
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
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
use crate::PlasticityCurrentArtifactsV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::plasticity_artifact_current::FrozenPlasticityArtifactsV1;
use crate::propose_agentd_plasticity_v1;
use crate::propose_agentd_topology_plasticity_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    ArtifactCurrentRequired(AgentdError),
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
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::Parameter {
                request: Box::new(request),
                now,
                response,
            })
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }

    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::Topology {
                request: Box::new(request),
                now,
                response,
            })
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
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
    current_artifacts: Option<FrozenPlasticityArtifactsV1>,
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
            current_artifacts: None,
        })
    }

    /// Attach the independent CURRENT source and receipt for this generation.
    /// Existing construction callers migrate by chaining this method before
    /// attaching the bootstrap. No frozen snapshot is a currentness fallback.
    pub fn with_current_artifacts(
        mut self,
        provider: Arc<dyn PlasticityCurrentArtifactsV1>,
        frozen_receipt: RegistrySnapshotReceipt,
    ) -> Result<Self, AgentdError> {
        self.current_artifacts = Some(FrozenPlasticityArtifactsV1::new(
            provider,
            frozen_receipt,
            &self.artifacts,
        )?);
        Ok(self)
    }

    pub(crate) fn into_channel(
        self,
    ) -> Result<(PlasticityRuntimeHandleV1, PlasticityRuntimeOwnerV1), AgentdError> {
        let current_artifacts = self.current_artifacts.ok_or_else(|| {
            AgentdError::Invalid(
                "plasticity requires an independent CURRENT provider; attach with_current_artifacts before runtime bootstrap"
                    .to_string(),
            )
        })?;
        let (handle, mut owner) = plasticity_runtime_channel_v1(
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
        )?;
        owner.current_artifacts = Some(current_artifacts);
        Ok((handle, owner))
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
    current_artifacts: Option<FrozenPlasticityArtifactsV1>,
    artifact_current_failed: bool,
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
            current_artifacts: None,
            artifact_current_failed: false,
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
    /// Add CURRENT verification to owners constructed through the compatibility
    /// channel API. An owner without this attachment cannot admit proposals.
    pub fn with_current_artifacts(
        mut self,
        provider: Arc<dyn PlasticityCurrentArtifactsV1>,
        frozen_receipt: RegistrySnapshotReceipt,
    ) -> Result<Self, AgentdError> {
        self.current_artifacts = Some(FrozenPlasticityArtifactsV1::new(
            provider,
            frozen_receipt,
            &self.artifacts,
        )?);
        Ok(self)
    }

    fn verify_artifact_current(&mut self, now: u64) -> Result<(), PlasticityRuntimeCallErrorV1> {
        if self.artifact_current_failed {
            return Err(PlasticityRuntimeCallErrorV1::ArtifactCurrentRequired(
                AgentdError::GenerationFenced(
                    "plasticity CURRENT refresh failed; refresh and rebootstrap required"
                        .to_string(),
                ),
            ));
        }
        self.artifact_current_failed = true;
        let current = self.current_artifacts.as_mut().ok_or_else(|| {
            PlasticityRuntimeCallErrorV1::ArtifactCurrentRequired(AgentdError::Invalid(
                "plasticity requires with_current_artifacts with an independent CURRENT provider"
                    .to_string(),
            ))
        })?;
        current
            .verify(now)
            .map_err(PlasticityRuntimeCallErrorV1::ArtifactCurrentRequired)?;
        self.artifact_current_failed = false;
        Ok(())
    }

    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            let command = tokio::select! {
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
                    if !ready {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                        continue;
                    }
                    if let Err(error) = self.verify_artifact_current(now) {
                        let _ = response.send(Err(error));
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
                    if !ready {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                        continue;
                    }
                    if let Err(error) = self.verify_artifact_current(now) {
                        let _ = response.send(Err(error));
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
}
