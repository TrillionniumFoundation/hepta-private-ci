//! Real ordinary Feature consumption, retaining the original source and Cell.
//! An admission response is not completion. Every handoff and receipt read
//! resolves the private committed decision and the current withdrawal witness.

use codex_hepta_neuron::FileAnchorWitnessStore;

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

impl OriginalCircuitFeatureIngressV1 {
    /// Submit the host's original signed request. Timeout or lost ACK is an
    /// error; use explicit readback to resolve the original committed outcome.
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
        match self.client.objective_start(request).await? {
            ObjectiveStartOutcome::Admitted { receipt }
                if receipt.disposition == "circuit_succeeded" =>
            {
                self.readback()
            }
            ObjectiveStartOutcome::Admitted { .. } => Err(invalid(
                "ordinary successor has no completed Circuit admission",
            )),
            ObjectiveStartOutcome::Conflict { .. } => {
                Err(invalid("ordinary successor admission conflict"))
            }
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
