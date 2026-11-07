//! Host-supplied population bindings and observations on the existing owner
//! channel. Cross-owner serialization remains with the original scheduler.

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellCapabilityContractV1;
use codex_hepta_neuron::CellFunctionalRoleV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellOwnerPopulationErrorV2;
use codex_hepta_neuron::CellOwnerPopulationObservationV2;
use codex_hepta_neuron::CellPopulationLimitsV1;
use codex_hepta_types::StableId;

use super::GenerationCommand;
use super::NeuronGenerationRuntimeBootstrapV2;
use super::NeuronGenerationRuntimeHandleV2;

impl NeuronGenerationRuntimeBootstrapV2 {
    /// Bind declarations resolved by the host's artifact owner before service
    /// attachment. The original journal owner checks the actual manifest,
    /// generation, schemas, role and reservation; no default is inferred.
    pub fn with_population(
        mut self,
        owner_id: StableId,
        capability: CellCapabilityContractV1,
        artifact: &CellCompatibilityBundleV1,
        task_role: CellFunctionalRoleV1,
        limits: CellPopulationLimitsV1,
    ) -> Result<Self, CellOwnerPopulationErrorV2> {
        self.owner
            .bind_population(owner_id, capability, artifact, task_role, limits)?;
        Ok(self)
    }
}

impl NeuronGenerationRuntimeHandleV2 {
    /// Read this owner's sealed, current population projection. An unbound
    /// bootstrap returns `None` and confers no role or artifact qualification.
    pub async fn population_observation(
        &self,
    ) -> Result<Option<CellOwnerPopulationObservationV2>, CellGenerationErrorV2> {
        self.call(GenerationCommand::PopulationObservation).await
    }

    /// Admit against the supplied current peers. The host must retain its
    /// scheduler exclusion across gathering peer observations and awaiting this
    /// call, including retries after a lost response. Target state is rechecked
    /// inside its owner; this channel cannot establish freshness for peers.
    pub async fn step_with_population(
        &self,
        request: CellGenerationRequestV2,
        other_owners: Vec<CellOwnerPopulationObservationV2>,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        // The existing population ceiling includes this target owner.
        if other_owners.len() >= 4_096 {
            return Err(CellGenerationErrorV2::Capacity);
        }
        self.validate_request(&request)?;
        self.call(|response| GenerationCommand::StepWithPopulation {
            request: Box::new(request),
            other_owners: other_owners.into_boxed_slice(),
            response,
        })
        .await
    }
}
