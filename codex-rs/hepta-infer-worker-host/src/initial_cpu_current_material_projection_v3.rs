//! Read complete material selected by the existing protected model index.
//! This is a factual projection; CURRENT and the actual held V2 owner must
//! independently authenticate it before a Round may use these inputs.
use super::*;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::decode_neuron_generation_material_v2;

pub(crate) struct CurrentCpuNeuronMaterialProjectionV3 {
    pub identity: CpuNeuronModelIdentityV3,
    pub material: NeuronGenerationMaterialV2,
    pub material_source: InstalledCpuSourceV1,
    pub registered_use_configuration: Option<InstalledCpuSourceV1>,
    pub current_registration_configuration: Option<InstalledCpuSourceV1>,
    descriptor: Source,
    descriptor_bytes: Vec<u8>,
    registry_path: std::path::PathBuf,
    registry_bytes: Vec<u8>,
    material_bytes: Vec<u8>,
    registered_use_bytes: Option<Vec<u8>>,
}
impl CurrentCpuNeuronMaterialProjectionV3 {
    pub(crate) fn revalidate(&self) -> HostResult<()> {
        if self.descriptor.read(32 * 1024)? != self.descriptor_bytes
            || read_root_review_input(&self.registry_path, 64 * 1024)? != self.registry_bytes
            || (Source {
                path: self.material_source.path.clone(),
                digest: self.material_source.digest.clone(),
            })
            .read(codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?
                != self.material_bytes
        {
            return Err("whole original current material projection changed".into());
        }
        if let Some(source) = &self.registered_use_configuration {
            let (registration, bytes) = crate::initial_cpu_anchor::registered_model_use::current_material_source(
                source, &self.identity.subject,
            )?;
            if self.registered_use_bytes.as_ref() != Some(&bytes)
                || self.current_registration_configuration.as_ref() != Some(&registration)
            {
                return Err("whole indexed registration Source changed".into());
            }
        }
        Ok(())
    }
}

pub(crate) fn read_current_cpu_neuron_material_projection_v3(
    resolver: &InstalledCpuSourceV1,
    initial_material: &InstalledCpuSourceV1,
    subject: &StableId,
) -> HostResult<CurrentCpuNeuronMaterialProjectionV3> {
    let descriptor = Source {
        path: resolver.path.clone(),
        digest: resolver.digest.clone(),
    };
    let descriptor_bytes = descriptor.read(32 * 1024)?;
    let parsed: Descriptor = serde_json::from_slice(&descriptor_bytes)?;
    if parsed.schema != "hepta.cpu-neuron.protected-model-resolver.v3"
        || parsed.subject != subject.as_str()
        || !parsed.registry_head.is_absolute()
    {
        return Err("whole original model-index descriptor/subject differs".into());
    }
    let registry_bytes = read_root_review_input(&parsed.registry_head, 64 * 1024)?;
    let registry: Registry = serde_json::from_slice(&registry_bytes)?;
    let identity = registry.current.typed()?;
    if &identity.subject != subject {
        return Err("actual original current model-index subject differs".into());
    }
    let registration = registry.registration(
        &identity,
        CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
    )?;
    // Generation one uses its original installed descriptor, whereas the
    // original successor entry already pins the complete encoded material.
    let material_source = if identity.generation.get() == 1 {
        initial_material.clone()
    } else {
        InstalledCpuSourceV1 {
            path: registration.installation.path.clone(),
            digest: registration.installation.digest.clone(),
        }
    };
    let material_bytes = Source {
        path: material_source.path.clone(),
        digest: material_source.digest.clone(),
    }
    .read(codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?;
    let material = decode_neuron_generation_material_v2(&material_bytes)?;
    if material.runtime.generation != identity.generation
        || material.runtime.semantic_digest()? != identity.configuration_digest
        || material.body.semantic_digest()? != identity.body_digest
    {
        return Err("whole indexed current material differs from exact model identity".into());
    }
    let registered_use_configuration =
        registration
            .registered_model_use
            .as_ref()
            .map(|sources| InstalledCpuSourceV1 {
                path: sources.configuration.path.clone(),
                digest: sources.configuration.digest.clone(),
            });
    let (current_registration_configuration, registered_use_bytes) = match &registered_use_configuration {
        Some(source) => {
            let (registration, bytes) = crate::initial_cpu_anchor::registered_model_use::current_material_source(
                source, subject,
            )?;
            (Some(registration), Some(bytes))
        }
        None if identity.generation.get() == 1 => (None, None),
        None => return Err("original successor registration Source absent".into()),
    };
    let projection = CurrentCpuNeuronMaterialProjectionV3 {
        identity,
        material,
        material_source,
        registered_use_configuration,
        current_registration_configuration,
        descriptor,
        descriptor_bytes,
        registry_path: parsed.registry_head,
        registry_bytes,
        material_bytes,
        registered_use_bytes,
    };
    projection.revalidate()?;
    Ok(projection)
}
