//! Population admission at the existing Agentd generation owner. The host
//! supplies an artifact resolved by its current artifact owner; these checks
//! bind that declaration to the selected runtime, without granting authority.

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellCapabilityContractV1;
use codex_hepta_neuron::CellExpertVersionV1;
use codex_hepta_neuron::CellFunctionalRoleV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellOwnerPopulationErrorV2;
use codex_hepta_neuron::CellOwnerPopulationObservationV2;
use codex_hepta_neuron::CellOwnerRegistrationV2;
use codex_hepta_neuron::CellPopulationErrorV1;
use codex_hepta_neuron::CellPopulationLimitsV1;
use codex_hepta_neuron::admit_generation_with_population_v2;
use codex_hepta_neuron::cell_owner_population_census_v2;
use codex_hepta_types::StableId;

pub(super) struct GenerationPopulationPolicy {
    owner_id: StableId,
    registration: CellOwnerRegistrationV2,
    task_role: CellFunctionalRoleV1,
    limits: CellPopulationLimitsV1,
}

impl GenerationPopulationPolicy {
    pub(super) fn from_artifact<W: AnchorWitnessStore>(
        owner: &CellGenerationJournalV2<W>,
        owner_id: StableId,
        capability: CellCapabilityContractV1,
        artifact: &CellCompatibilityBundleV1,
        task_role: CellFunctionalRoleV1,
        limits: CellPopulationLimitsV1,
    ) -> Result<Self, CellOwnerPopulationErrorV2> {
        use CellOwnerPopulationErrorV2 as E;
        let manifest = owner.manifest();
        let artifact_digest = artifact.digest().map_err(|_| E::InvalidBinding)?;
        let snapshot = owner.snapshot().map_err(E::Generation)?;
        if artifact_digest.as_array() != &manifest.bundle_digest
            || artifact.generation.get() != snapshot.generation
            || artifact.components.state_schema.as_array() != &manifest.state_schema
            || artifact.components.output_schema.as_array() != &manifest.output_schema
            || manifest
                .encoder
                .is_some_and(|encoder| artifact.components.encoder.as_array() != &encoder)
            || manifest
                .head
                .is_some_and(|head| artifact.components.heads.as_array() != &head)
        {
            return Err(E::InvalidBinding);
        }
        if capability.role != task_role {
            return Err(E::WrongRole);
        }
        let expert = CellExpertVersionV1 {
            version_id: artifact.artifact_id.clone(),
            type_id: capability.type_id.clone(),
            capability_digest: capability.digest().map_err(|_| E::InvalidBinding)?,
            shared_base_digest: artifact.components.base,
            parameter_bundle_digest: artifact_digest,
        };
        let policy = Self {
            owner_id,
            registration: CellOwnerRegistrationV2 { capability, expert },
            task_role,
            limits,
        };
        let observation = policy.observe(owner)?;
        cell_owner_population_census_v2(&[observation], limits)?;
        Ok(policy)
    }

    pub(super) fn observe<W: AnchorWitnessStore>(
        &self,
        owner: &CellGenerationJournalV2<W>,
    ) -> Result<CellOwnerPopulationObservationV2, CellOwnerPopulationErrorV2> {
        CellOwnerPopulationObservationV2::observe_generation(
            owner,
            self.owner_id.clone(),
            self.registration.clone(),
        )
    }

    pub(super) fn admit<W: AnchorWitnessStore>(
        &self,
        owner: &mut CellGenerationJournalV2<W>,
        other_owners: &[CellOwnerPopulationObservationV2],
        request: CellGenerationRequestV2,
        now_micros: u64,
    ) -> Result<Option<CellGenerationReceiptV2>, CellGenerationErrorV2> {
        let observed = self.observe(owner).map_err(generation_error)?;
        admit_generation_with_population_v2(
            owner,
            &observed,
            other_owners,
            self.limits,
            self.task_role,
            request,
            now_micros,
        )
        .map_err(generation_error)
    }
}

fn generation_error(error: CellOwnerPopulationErrorV2) -> CellGenerationErrorV2 {
    match error {
        CellOwnerPopulationErrorV2::Generation(error) => error,
        CellOwnerPopulationErrorV2::Population(CellPopulationErrorV1::CapacityExceeded(_)) => {
            CellGenerationErrorV2::Capacity
        }
        CellOwnerPopulationErrorV2::StaleOwner => CellGenerationErrorV2::Conflict,
        _ => CellGenerationErrorV2::InvalidBinding,
    }
}
