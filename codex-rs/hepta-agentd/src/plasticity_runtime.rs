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
use std::time::Instant;

use codex_hepta_agent_components::intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_agent_components::learning_artifacts::ArtifactRegistry;
use codex_hepta_agent_components::learning_ledger::DurableLedger;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceVerifierV1;
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
use crate::plasticity_host::propose_agentd_plasticity_with_clock_v1;
use crate::topology_plasticity_host::propose_agentd_topology_plasticity_with_clock_v1;

const MAX_PLASTICITY_RUNTIME_QUEUE: usize = 64;
#[path = "plasticity_current_artifacts.rs"]
mod current_artifacts;
use current_artifacts::PlasticityCurrentArtifactsV1;
#[path = "plasticity_runtime_final_admission.rs"]
mod final_admission;
use final_admission::FinalPlasticityAdmissionV1;

#[derive(Debug)]
pub enum PlasticityRuntimeCallErrorV1 {
    Unavailable,
    Closed,
    ClockUnavailable,
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
        response: oneshot::Sender<
            Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1>,
        >,
    },
    ObserveParameter {
        request: Box<ParameterPlasticityProductRequestV1>,
        response: oneshot::Sender<
            Result<Option<ParameterPlasticityProductReceiptV1>, PlasticityRuntimeCallErrorV1>,
        >,
    },
    ObserveProposal {
        proposal_id: codex_hepta_agent_components::types::StableId,
        response: oneshot::Sender<Result<Option<Vec<u8>>, PlasticityRuntimeCallErrorV1>>,
    },
    Topology {
        request: Box<TopologyPlasticityProductRequestV1>,
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
    /// Queue a proposal for validation against the owner's Unix-millisecond
    /// clock when it is processed. `now` is retained for API compatibility and
    /// cannot set the verification time or extend the evidence validity window.
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let _ = now;
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::Parameter {
                request: Box::new(request),
                response,
            })
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }

    /// Queue a topology proposal. The compatibility `now` argument is ignored;
    /// the owner checks evidence against its current Unix-millisecond clock.
    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let _ = now;
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::Topology {
                request: Box::new(request),
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
    current_artifacts: Option<PlasticityCurrentArtifactsV1>,
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
            current_artifacts: None,
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
        owner.current_artifacts = self.current_artifacts;
        Ok((handle, owner))
    }
}

/// Exact mutable owner retained for the lifetime of the Agentd generation.
pub struct PlasticityRuntimeOwnerV1 {
    receiver: mpsc::Receiver<PlasticityRuntimeCommandV1>,
    // The daemon chooses this clock at composition; producers cannot supply or
    // override it. Private injection keeps lifetime/queue tests deterministic.
    clock: Box<dyn FnMut() -> Result<u64, AgentdError> + Send>,
    // Every successful sample advances this owner-lifetime floor, even when
    // the proposal is subsequently rejected. Rollback cannot revive evidence.
    last_observed_unix_ms: Option<u64>,
    // The private real host monotonic reader never invokes external callbacks.
    guard_elapsed_ms: fn(&Instant) -> u128,
    artifacts: ArtifactRegistry,
    current_artifacts: Option<PlasticityCurrentArtifactsV1>,
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
            clock: Box::new(crate::authbus_ingress::now_ms),
            last_observed_unix_ms: None,
            guard_elapsed_ms: monotonic_elapsed_ms,
            artifacts,
            current_artifacts: None,
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

fn observe_plasticity_clock_v1(
    clock: &mut dyn FnMut() -> Result<u64, AgentdError>,
    last_observed_unix_ms: &mut Option<u64>,
) -> Result<u64, AgentdError> {
    let now = clock()?;
    if last_observed_unix_ms.is_some_and(|previous| now < previous) {
        return Err(AgentdError::Protocol(
            "plasticity host clock regressed".to_string(),
        ));
    }
    *last_observed_unix_ms = Some(now);
    Ok(now)
}

fn monotonic_elapsed_ms(start: &Instant) -> u128 {
    start.elapsed().as_millis()
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
        // An owner created while Starting still belongs to its one succeeding
        // Running generation. Never adopt a generation refreshed by a request.
        let owner_generation = state
            .identity()
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| {
                AgentdError::GenerationFenced("plasticity owner generation overflow".to_string())
            })?;
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

            let ready = !cancellation.is_cancelled()
                && state.plasticity_admission_ready()?
                && state.current_generation()? == owner_generation;
            match command {
                PlasticityRuntimeCommandV1::Parameter { request, response } => {
                    if !ready {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                        continue;
                    }
                    let Ok(now) = observe_plasticity_clock_v1(
                        self.clock.as_mut(),
                        &mut self.last_observed_unix_ms,
                    ) else {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::ClockUnavailable));
                        continue;
                    };
                    let result = {
                        let mut admission = FinalPlasticityAdmissionV1 {
                            state: &state,
                            cancellation: &cancellation,
                            generation: owner_generation,
                            guard: None,
                            unavailable: false,
                            current_artifacts: self.current_artifacts.as_ref(),
                            artifacts: &self.artifacts,
                            baseline: request.admission.baseline_id.clone(),
                        };
                        let result = {
                            let mut final_clock = || {
                                admission.observe(
                                    self.clock.as_mut(),
                                    &mut self.last_observed_unix_ms,
                                    self.guard_elapsed_ms,
                                )
                            };
                            propose_agentd_plasticity_with_clock_v1(
                                *request,
                                &self.artifacts,
                                &self.ledger,
                                self.owner_evidence_resolver.as_ref(),
                                &self.owner_evidence_policy,
                                &self.verifier,
                                &mut self.parameter_writer,
                                &mut self.parameter_anchor_store,
                                now,
                                &mut final_clock,
                            )
                        };
                        result.map_err(|error| {
                            if admission.unavailable {
                                PlasticityRuntimeCallErrorV1::Unavailable
                            } else {
                                PlasticityRuntimeCallErrorV1::Parameter(error)
                            }
                        })
                    };
                    let _ = response.send(result);
                }
                PlasticityRuntimeCommandV1::ObserveParameter { request, response } => {
                    let result = self.observe_completed_parameter(
                        &state,
                        &cancellation,
                        owner_generation,
                        ready,
                        &request,
                    );
                    let _ = response.send(result);
                }
                PlasticityRuntimeCommandV1::ObserveProposal {
                    proposal_id,
                    response,
                } => {
                    let result = self.observe_completed_proposal(
                        &state,
                        &cancellation,
                        owner_generation,
                        ready,
                        &proposal_id,
                    );
                    let _ = response.send(result);
                }
                PlasticityRuntimeCommandV1::Topology { request, response } => {
                    if !ready {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable));
                        continue;
                    }
                    let Ok(now) = observe_plasticity_clock_v1(
                        self.clock.as_mut(),
                        &mut self.last_observed_unix_ms,
                    ) else {
                        let _ = response.send(Err(PlasticityRuntimeCallErrorV1::ClockUnavailable));
                        continue;
                    };
                    let result = {
                        let mut admission = FinalPlasticityAdmissionV1 {
                            state: &state,
                            cancellation: &cancellation,
                            generation: owner_generation,
                            guard: None,
                            unavailable: false,
                            current_artifacts: self.current_artifacts.as_ref(),
                            artifacts: &self.artifacts,
                            baseline: request.admission.baseline_id.clone(),
                        };
                        let result = {
                            let mut final_clock = || {
                                admission.observe(
                                    self.clock.as_mut(),
                                    &mut self.last_observed_unix_ms,
                                    self.guard_elapsed_ms,
                                )
                            };
                            propose_agentd_topology_plasticity_with_clock_v1(
                                *request,
                                &self.artifacts,
                                &self.ledger,
                                &self.verifier,
                                &mut self.topology_writer,
                                &mut self.topology_anchor_store,
                                now,
                                &mut final_clock,
                            )
                        };
                        result.map_err(|error| {
                            if admission.unavailable {
                                PlasticityRuntimeCallErrorV1::Unavailable
                            } else {
                                PlasticityRuntimeCallErrorV1::Topology(error)
                            }
                        })
                    };
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
#[path = "plasticity_runtime_queue_tests.rs"]
mod tests;

#[path = "plasticity_runtime_observation.rs"]
mod observation;
