//! Root-enrolled complete inputs for the existing per-round preparation route.
//! Each Source retains its original purpose and custody; no request supplies
//! a model, role program, credential, private cut, path grant or new lifetime.
use super::*;
use crate::CpuNeuronRoundMaterialBlueprintV3;
use crate::RootSelfIterationRoleRouteV1;
use codex_hepta_agent_components::intelligence::decode_canonical_port_input_material_v1;
use codex_hepta_neuron::decode_neuron_tick_input_v1;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MaterialBlueprint {
    pub generation_root: PathBuf,
    pub test_plan_digest: String,
    pub canary_tick: InstalledCpuSourceV1,
    pub canary_port: InstalledCpuSourceV1,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Blueprint {
    pub schema: String,
    pub model_resolver: InstalledCpuSourceV1,
    pub initial_material: InstalledCpuSourceV1,
    pub initial_registration: InstalledCpuSourceV1,
    pub plasticity_context_template: InstalledCpuSourceV1,
    pub dataset_producer: InstalledCpuSourceV1,
    pub dataset_plan: InstalledCpuSourceV1,
    pub search_shape: InstalledCpuSourceV1,
    pub ndu_journal: InstalledCpuSourceV1,
    pub material: MaterialBlueprint,
    pub learning_trust: InstalledCpuSourceV1,
    pub reviewer_principal: InstalledCpuSourceV1,
    pub generator: RootSelfIterationRoleRouteV1,
    pub observer: RootSelfIterationRoleRouteV1,
    pub pre_registration_selector: RootSelfIterationRoleRouteV1,
    pub pre_registration_selector_template: InstalledCpuSourceV1,
    pub raw_evaluation_template: InstalledCpuSourceV1,
    pub independent_owners_template: InstalledCpuSourceV1,
    pub independent_client_template: InstalledCpuSourceV1,
    pub worker_program: InstalledCpuSourceV1,
}

impl Blueprint {
    pub(super) fn read(source: &InstalledCpuSourceV1) -> Result<(Self, Vec<u8>)> {
        let bytes = configuration::source(source, 262_144)?;
        let blueprint: Self = serde_json::from_slice(&bytes)?;
        ensure!(
            blueprint.schema == "hepta.root-parameter-round-blueprint.v1",
            "original Root round blueprint purpose"
        );
        for source in [
            &blueprint.model_resolver,
            &blueprint.initial_material,
            &blueprint.initial_registration,
            &blueprint.plasticity_context_template,
            &blueprint.dataset_producer,
            &blueprint.dataset_plan,
            &blueprint.search_shape,
            &blueprint.ndu_journal,
            &blueprint.learning_trust,
            &blueprint.reviewer_principal,
            &blueprint.pre_registration_selector_template,
            &blueprint.raw_evaluation_template,
            &blueprint.independent_owners_template,
            &blueprint.independent_client_template,
            &blueprint.worker_program,
            &blueprint.material.canary_tick,
            &blueprint.material.canary_port,
        ] {
            ensure!(
                source.path.is_absolute() && !source.digest.parse::<Digest32>()?.is_zero(),
                "whole independently enrolled original Source absent"
            );
        }
        ensure!(
            blueprint.material.generation_root.is_absolute()
                && !blueprint
                    .material
                    .generation_root
                    .components()
                    .any(|part| matches!(
                        part,
                        std::path::Component::CurDir | std::path::Component::ParentDir
                    ))
                && !blueprint
                    .material
                    .test_plan_digest
                    .parse::<Digest32>()?
                    .is_zero(),
            "original physical path root and whole test plan pin"
        );
        ensure!(
            blueprint.generator.uid > 0
                && blueprint.generator.gid > 0
                && blueprint.generator.inaccessible_paths.len() == 5
                && blueprint.observer.uid == 0
                && blueprint.observer.gid == 0
                && blueprint.observer.inaccessible_paths.is_empty()
                && blueprint.pre_registration_selector.uid == 0
                && blueprint.pre_registration_selector.gid == 0
                && blueprint.pre_registration_selector.inaccessible_paths.len() == 5,
            "original finite G/O/S process custody"
        );
        for route in [
            &blueprint.generator,
            &blueprint.observer,
            &blueprint.pre_registration_selector,
        ] {
            ensure!(
                route.program.path.is_absolute()
                    && route.configuration_template.path.is_absolute()
                    && !route.program.digest.parse::<Digest32>()?.is_zero()
                    && !route
                        .configuration_template
                        .digest
                        .parse::<Digest32>()?
                        .is_zero(),
                "whole enrolled native role route changed"
            );
        }
        Ok((blueprint, bytes))
    }

    pub(super) fn material(&self) -> Result<CpuNeuronRoundMaterialBlueprintV3> {
        Ok(CpuNeuronRoundMaterialBlueprintV3 {
            generation_root: self.material.generation_root.clone(),
            test_plan_digest: self.material.test_plan_digest.parse()?,
            canary_tick: decode_neuron_tick_input_v1(
                &configuration::source(&self.material.canary_tick, 262_144)?
            ).map_err(|error| anyhow::anyhow!("{error}"))?,
            canary_port: decode_canonical_port_input_material_v1(
                &configuration::source(&self.material.canary_port,
                    codex_hepta_agent_components::intelligence::MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1)?
            ).map_err(|error| anyhow::anyhow!("{error}"))?,
        })
    }
}
