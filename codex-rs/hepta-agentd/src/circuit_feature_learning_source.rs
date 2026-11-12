//! Real ordinary Feature consumption, retaining the original source and Cell.
//! An admission response is not completion. Every handoff and receipt read
//! resolves the private committed decision and the current withdrawal witness.

use std::time::Duration;

use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use tokio::time::Instant;

use crate::client::ObjectiveStartReplyV1;

use super::*;
use crate::AgentdClient;
use crate::AgentdQ24CircuitTaskRuntimeV1;
use crate::AuthBusObjectiveIngress;
use crate::CellQ24DatasetTaskV1;
use crate::ObjectiveStartOutcome;
use crate::OriginalGenerationLearningRoleV1;

/// A completed ordinary successor under the same original publication owners.
/// Cloning retains those owners; callers cannot supply an observation or receipt.
#[derive(Clone)]
pub struct OriginalCircuitFeatureLearningSourcesV1 {
    cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    identity: AgentdIdentity,
    publication: CircuitTaskSourcePublicationV1,
}

impl OriginalCircuitFeatureLearningSourcesV1 {
    pub fn capture(
        cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
        source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
        identity: AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        if !matches!(&cell.task.0.publication, Publication::Update { .. }) {
            return Err(invalid(
                "learning Feature source requires a published successor",
            ));
        }
        let publication = source
            .read_run_publication(&identity, &cell.task.source().scope.run_id)
            .map_err(invalid)?;
        cell.committed(&publication)?;
        let result = Self {
            cell,
            source,
            identity,
            publication,
        };
        result.require_current()?;
        Ok(result)
    }

    fn require_current(&self) -> Result<(), AgentdError> {
        let run = &self.cell.task.source().scope.run_id;
        let before = self
            .source
            .read_run_publication(&self.identity, run)
            .map_err(invalid)?;
        if before != self.publication {
            return Err(invalid("original Feature source publication changed"));
        }
        self.cell.committed(&before)?;
        if self
            .source
            .read_run_publication(&self.identity, run)
            .map_err(invalid)?
            != before
        {
            return Err(invalid("original Feature source changed across Cell read"));
        }
        self.cell.task.require_current()
    }

    fn require_original_admission(
        &self,
        expected: &RunStartAuthenticationV1,
    ) -> Result<(), AgentdError> {
        self.require_current()?;
        if &self.publication.original_record().authentication != expected {
            return Err(invalid(
                "original Feature authentication differs from submitted request",
            ));
        }
        self.require_current()
    }

    /// Feed this actual completed task into a later Dataset preparation while
    /// retaining its original live withdrawal reader. Business outcomes, target
    /// values, freeze authorization and the next learning scope remain separate.
    pub fn original_dataset_task(&self) -> Result<CellQ24DatasetTaskV1, AgentdError> {
        self.require_current()?;
        let task = CellQ24DatasetTaskV1::capture(
            self.source.as_ref().clone(),
            &self.cell,
            self.identity.clone(),
            self.cell.task.source().scope.run_id.clone(),
        )
        .map_err(invalid)?;
        self.require_current()?;
        Ok(task)
    }

    pub(crate) fn require_original_feature_binding(
        &self,
        baseline: Digest32,
    ) -> Result<Digest32, AgentdError> {
        self.require_current()?;
        let Publication::Update { original, previous } = &self.cell.task.0.publication else {
            return Err(invalid("original Feature successor publication"));
        };
        if previous.manifest.bundle_digest != baseline.into_array() {
            return Err(invalid("original Feature predecessor bundle"));
        }
        let binding = Digest32::of_parts(&[
            b"hepta.agentd.original-feature-learning-source.v1\0",
            original.publication_digest()?.as_array(),
            self.publication.publication_digest().as_array(),
            &previous.manifest.digest().map_err(invalid)?,
        ]);
        self.require_current()?;
        Ok(binding)
    }

    pub(crate) fn read_original_feature_observation(
        &self,
        predecessor: &LearningIterationCoordinatorV1,
        role: OriginalGenerationLearningRoleV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        self.require_current()?;
        let observation = match role {
            OriginalGenerationLearningRoleV1::Selection => {
                self.cell.read_learning_selection(predecessor)?
            }
            OriginalGenerationLearningRoleV1::NextUse => {
                self.cell
                    .read_learning_next_use(predecessor, &self.source, &self.identity)?
            }
        };
        self.require_current()?;
        Ok(observation)
    }
}

/// A normal authenticated ObjectiveStart client paired with one original Q24
/// profile. The host starts that profile through its ordinary daemon lifecycle.
/// This handle neither starts a daemon nor creates or signs a task request.
/// The existing client correlates agent/generation responses, not a Root PID.
/// Signed AuthBus admission and the retained source/Cell reads remain required.
pub struct OriginalCircuitFeatureIngressV1 {
    client: AgentdClient,
    cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    identity: AgentdIdentity,
}

impl AgentdQ24CircuitTaskRuntimeV1<FileAnchorWitnessStore, FileAnchorWitnessStore> {
    pub fn original_successor_ingress(
        &self,
    ) -> Result<OriginalCircuitFeatureIngressV1, AgentdError> {
        self.cell.task.require_current()?;
        if !matches!(&self.cell.task.0.publication, Publication::Update { .. }) {
            return Err(invalid(
                "ordinary learning ingress requires the published successor",
            ));
        }
        let identity = self.config.identity().clone();
        let client = AgentdClient::new(
            identity.control_socket.clone(),
            identity.agent_id.clone(),
            identity.spawn_generation,
        )?;
        Ok(OriginalCircuitFeatureIngressV1 {
            client,
            cell: self.cell.clone(),
            source: Arc::clone(&self.source),
            identity,
        })
    }
}

impl crate::OriginalQ24InstalledSuccessorV1 {
    /// Use the same ordinary signed ObjectiveStart/ACK-loss/readback path after
    /// the supervised service installed this actual Root-published successor.
    pub fn original_installed_successor_ingress(
        &self,
    ) -> Result<OriginalCircuitFeatureIngressV1, AgentdError> {
        self.cell.task.require_current()?;
        if !matches!(&self.cell.task.0.publication, Publication::Update { .. }) {
            return Err(invalid(
                "installed successor requires the original update publication",
            ));
        }
        let identity = self.identity.clone();
        let client = AgentdClient::new(
            identity.control_socket.clone(),
            identity.agent_id.clone(),
            identity.spawn_generation,
        )?;
        Ok(OriginalCircuitFeatureIngressV1 {
            client,
            cell: self.cell.clone(),
            source: Arc::clone(&self.source),
            identity,
        })
    }
}

impl OriginalCircuitFeatureIngressV1 {
    /// Submit the host's original signed request once. Only a typed lost ACK
    /// after its complete write enters bounded original-source observation.
    /// Malformed or rejected replies never enter recovery. No receipt at the
    /// observation deadline preserves the original transport uncertainty.
    pub async fn submit(
        &self,
        request: AuthBusObjectiveIngress,
    ) -> Result<OriginalCircuitFeatureLearningSourcesV1, AgentdError> {
        self.cell.task.require_current()?;
        let definition = self.cell.task.definition();
        if request.body.run_id != self.cell.task.source().scope.run_id.as_str()
            || request.body.runtime_body_digest != definition.runtime.runtime_digest.to_string()
            || request.body.model_tuple_digest
                != definition.semantic_digest().map_err(invalid)?.to_string()
        {
            return Err(invalid(
                "signed ordinary request differs from the published Feature task",
            ));
        }
        let claims = crate::authbus_objective_claims(&self.identity, &request)?;
        let expected = RunStartAuthenticationV1 {
            issuer_id: claims.issuer_id,
            key_epoch: claims.key_epoch.get(),
            message_id: claims.message_id,
            sequence: claims.sequence,
            expires_at_ms: claims.expires_at_ms,
            scope_digest: claims.scope_digest,
            signed_body_digest: claims.payload_digest,
            signature: crate::authbus_trust::hex_bytes(&request.signature_hex)?,
        };
        // This is an observation budget, not execution authority. Both bounds
        // come from the sealed original source; a request's claimed deadline
        // cannot extend it. The one-minute cap limits this caller's wait only.
        let source = self.cell.task.source();
        let window = source
            .deadline_micros
            .checked_sub(source.monotonic_micros)
            .ok_or_else(|| invalid("original Feature source time window"))?;
        let budget = Duration::from_micros(window)
            .min(Duration::from_millis(source.lease_duration_ms))
            .min(Duration::from_secs(60));
        let deadline = Instant::now() + budget;
        let outcome = match self.client.objective_start_once(request).await? {
            ObjectiveStartReplyV1::Completed(outcome) => outcome,
            ObjectiveStartReplyV1::AcknowledgementLost(error) => {
                return self
                    .observe_original_after_ack(deadline, expected, error)
                    .await;
            }
        };
        match outcome {
            ObjectiveStartOutcome::Admitted { receipt }
                if receipt.disposition == "circuit_succeeded" =>
            {
                let completed = self.readback()?;
                completed.require_original_admission(&expected)?;
                Ok(completed)
            }
            ObjectiveStartOutcome::Admitted { .. } => Err(invalid(
                "ordinary successor has no completed Circuit admission",
            )),
            ObjectiveStartOutcome::Conflict { .. } => {
                Err(invalid("ordinary successor admission conflict"))
            }
        }
    }

    async fn observe_original_after_ack(
        &self,
        deadline: Instant,
        expected: RunStartAuthenticationV1,
        original_error: AgentdError,
    ) -> Result<OriginalCircuitFeatureLearningSourcesV1, AgentdError> {
        loop {
            if Instant::now() >= deadline {
                return Err(original_error);
            }
            let cell = self.cell.clone();
            let source = Arc::clone(&self.source);
            let identity = self.identity.clone();
            let expected = expected.clone();
            // Journal and CURRENT reads stay off the async reactor. Cancelling
            // this observation never cancels or repeats the original task.
            let observed = tokio::time::timeout_at(
                deadline,
                tokio::task::spawn_blocking(move || {
                    cell.task.require_current()?;
                    match source.read_run_publication(&identity, &cell.task.source().scope.run_id) {
                        Err(crate::CircuitTaskErrorV1::ReconciliationRequired) => Ok(None),
                        Err(error) => Err(invalid(error)),
                        Ok(_) => {
                            let completed = OriginalCircuitFeatureLearningSourcesV1::capture(
                                cell, source, identity,
                            )?;
                            completed.require_original_admission(&expected)?;
                            Ok(Some(completed))
                        }
                    }
                }),
            )
            .await;
            match observed {
                Err(_) => return Err(original_error),
                Ok(Err(error)) => return Err(invalid(error)),
                Ok(Ok(Err(error))) => return Err(error),
                Ok(Ok(Ok(Some(completed)))) => return Ok(completed),
                Ok(Ok(Ok(None))) => {}
            }
            tokio::time::sleep_until((Instant::now() + Duration::from_millis(10)).min(deadline))
                .await;
        }
    }

    /// Read only the still-held source and private Cell; do not retry ingress,
    /// issue a grant, acknowledge output or manufacture a learning receipt.
    pub fn readback(&self) -> Result<OriginalCircuitFeatureLearningSourcesV1, AgentdError> {
        OriginalCircuitFeatureLearningSourcesV1::capture(
            self.cell.clone(),
            Arc::clone(&self.source),
            self.identity.clone(),
        )
    }
}
