//! Derive the physical plan from the same full E/S/CURRENT input set and the
//! Root materialized base/organ/body closure. No descriptor issues authority.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_neuron::*;
use std::path::PathBuf;
use std::sync::Arc;

#[derive(Clone, Debug, Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct InstalledCpuSourceV1 {
    pub path: PathBuf,
    pub digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Installed {
    pub schema: String,
    pub agent_id: String,
    pub current_pointer: PathBuf,
    #[serde(default)]
    pub model_use_pointer: Option<PathBuf>,
    pub compiled_body: Source,
    pub tick_provider: Source,
    #[serde(default)]
    pub fleet_manifest_digest: Option<String>,
    #[serde(default)]
    pub fleet_execution_binding: Option<FleetExecutionBindingV1>,
    pub control_state_path: PathBuf,
    pub authority_file: PathBuf,
    pub authority_signer_id: String,
    pub authority_verifying_key_hex: String,
    pub maximum_request_duration_ms: u64,
}

#[derive(Deserialize)]
pub(super) enum FleetExecutionBindingV1 {
    CurrentRootFleetExecutionV1,
}

impl Installed {
    pub(super) fn launch_digest(&self, root_launch_fact: Option<&str>) -> HostResult<Digest32> {
        match (
            self.schema.as_str(),
            &self.model_use_pointer,
            &self.fleet_manifest_digest,
            &self.fleet_execution_binding,
        ) {
            ("hepta.cpu-neuron.installed-owner-composition.v2", None, Some(pin), None)
            | ("hepta.cpu-neuron.installed-owner-composition.v3", Some(_), Some(pin), None) => {
                digest(pin)
            }
            (
                "hepta.cpu-neuron.installed-owner-composition.v4",
                Some(_),
                None,
                Some(FleetExecutionBindingV1::CurrentRootFleetExecutionV1),
            ) => digest(root_launch_fact.ok_or("missing original Root Fleet launch fact")?),
            _ => Err("installed CPU Fleet binding mode or schema".into()),
        }
    }
}

pub(super) fn load(
    source: &InstalledCpuSourceV1,
    identity: &codex_hepta_agentd::AgentdIdentity,
    clock: Arc<dyn AuthorityClock>,
) -> HostResult<(
    Installed,
    crate::CpuNeuronGenerationPlanV1,
    crate::CpuNeuronGenerationOpenModeV1,
    Digest32,
)> {
    let pinned = Source {
        path: source.path.clone(),
        digest: source.digest.clone(),
    };
    let bytes = pinned.read(32 * 1024)?;
    let installed: Installed = serde_json::from_slice(&bytes)?;
    let root_launch_fact = std::env::var("HEPTA_FLEET_LAUNCH_DIGEST").ok();
    let launch_digest = installed.launch_digest(root_launch_fact.as_deref())?;
    if installed.agent_id != identity.agent_id.to_string()
        || !(1..=60_000).contains(&installed.maximum_request_duration_ms)
    {
        return Err("installed CPU composition identity or duration".into());
    }
    let inputs = match &installed.model_use_pointer {
        Some(pointer) => model_use_current::read_installed_inputs(pointer, clock.clone())?,
        None => current::read_installed_inputs(&installed.current_pointer, clock.clone())?,
    };
    let declaration = renewal::verify_first_installation(&inputs.profile)?;
    if declaration.agent_id != identity.agent_id.to_string()
        || declaration.workload_uid != rustix::process::geteuid().as_raw()
        || declaration.workload_gid != rustix::process::getegid().as_raw()
    {
        return Err("installed CPU owner differs from original Root statement".into());
    }
    let body = read_body(&installed.compiled_body, identity, &inputs)?;
    let scope = NeuronTickInputV1::journal_scope_for_subject(
        &id(identity.agent_id.as_str())?,
        inputs.evidence.objective_digest(),
    )?;
    let generation = inputs.runtime.generation;
    let config_digest = inputs.runtime.semantic_digest()?;
    let body_digest = body.semantic_digest()?;
    let paths = [
        &declaration.generation_store,
        &declaration.runtime_index,
        &declaration.witness,
        &installed.control_state_path,
    ];
    for path in paths {
        if !path.is_absolute()
            || !path.starts_with(&identity.home_root)
            || path.file_name().is_none()
        {
            return Err("installed CPU state escaped the original private Agent home".into());
        }
        crate::evolving_agentd::private_parent(path)?;
    }
    let mut present = 0;
    for path in paths.into_iter().take(3) {
        match std::fs::symlink_metadata(path) {
            Ok(meta) if meta.is_file() && !meta.file_type().is_symlink() => present += 1,
            Ok(_) => return Err("non-regular original CPU store".into()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
    }
    let mode = match present {
        0 => crate::CpuNeuronGenerationOpenModeV1::Create,
        3 => crate::CpuNeuronGenerationOpenModeV1::Recover,
        _ => return Err("partial original CPU generation needs owner recovery".into()),
    };
    if matches!(mode, crate::CpuNeuronGenerationOpenModeV1::Create)
        && installed.model_use_pointer.is_some()
    {
        let admission = current::read_installed_inputs(&installed.current_pointer, clock)?;
        if &admission.profile_source != inputs.physical_profile_source()
            || admission.runtime != inputs.runtime
            || admission.native != inputs.native
        {
            return Err(
                "first creation requires the original current installation admission".into(),
            );
        }
    }
    let plan = crate::CpuNeuronGenerationPlanV1 {
        model_manifest: inputs.profile.model.path.clone(),
        model_manifest_digest: inputs.evidence.model_manifest_digest(),
        generation_store: declaration.generation_store,
        runtime_index: declaration.runtime_index,
        witness: declaration.witness,
        native: inputs.native,
        scope,
        runtime: inputs.runtime,
        body,
        store_context: NeuronGenerationStoreContextV2 {
            generation,
            scope,
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 4_096,
            max_pending_witness: 64,
            max_checkpoint_bytes: 1024 * 1024,
            max_full_receipt_bytes: 1024 * 1024,
            max_file_bytes: 64 * 1024 * 1024,
            max_startup_replay_bytes: 64 * 1024 * 1024,
        },
        index_context: NeuronRuntimeIndexContextV2 {
            generation,
            scope,
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 4_096,
            max_file_bytes: 64 * 1024 * 1024,
            max_startup_replay_bytes: 64 * 1024 * 1024,
        },
        witness_context: NeuronWitnessContextV2 {
            generation,
            scope,
            key_epoch: 1,
            deletion_epoch: 1,
            max_records: 4_096,
        },
    };
    if pinned.read(32 * 1024)? != bytes {
        return Err("installed CPU source changed".into());
    }
    Ok((installed, plan, mode, launch_digest))
}

#[cfg(test)]
#[path = "initial_cpu_fleet_launch_binding_tests.rs"]
mod tests;

fn read_body(
    source: &Source,
    identity: &codex_hepta_agentd::AgentdIdentity,
    inputs: &Inputs,
) -> HostResult<NeuronBodyBundleIdentityV1> {
    let bytes = source.read(32 * 1024)?;
    let compiled: Value = serde_json::from_slice(&bytes)?;
    let text = |key: &str| -> HostResult<&str> {
        Ok(compiled[key].as_str().ok_or("compiled body field")?)
    };
    if text("schema")? != "hepta.cpu-neuron.installed-body-manifest.v1"
        || text("agent_id")? != identity.agent_id.as_str()
        || compiled["resource_authority_issued"] != false
        || compiled["actual_neuron_tick"] != false
        || !compiled["cell_slot_id"].is_null()
        || !compiled["cell_bundle_digest"].is_null()
    {
        return Err("initial physical body metadata".into());
    }
    let sources: Vec<Source> = serde_json::from_value(compiled["sources"].clone())?;
    if sources.len() != 3 {
        return Err("complete installed body closure required".into());
    }
    let base_bytes = sources[0].read(32 * 1024)?;
    let organ_bytes = sources[1].read(32 * 1024)?;
    let manifest_bytes = sources[2].read(32 * 1024)?;
    let manifest: Value = serde_json::from_slice(&manifest_bytes)?;
    for key in [
        "schema",
        "agent_id",
        "body_generation",
        "base_bundle_digest",
        "organ_id",
        "organ_bundle_digest",
        "cell_slot_id",
        "cell_bundle_digest",
        "effective_parameter_digest",
        "source_revision_digest",
    ] {
        if manifest[key] != compiled[key] {
            return Err("compiled body differs from actual manifest bytes".into());
        }
    }
    let body = NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest(text("body_manifest_digest")?)?,
        body_generation: Generation::new(
            compiled["body_generation"]
                .as_u64()
                .ok_or("body generation")?,
        )?,
        base_bundle_digest: digest(text("base_bundle_digest")?)?,
        organ_id: id(text("organ_id")?)?,
        organ_bundle_digest: digest(text("organ_bundle_digest")?)?,
        cell_slot_id: None,
        cell_bundle_digest: None,
        effective_parameter_digest: digest(text("effective_parameter_digest")?)?,
        source_revision_digest: digest(text("source_revision_digest")?)?,
    };
    if body.body_generation != inputs.runtime.generation
        || body.effective_parameter_digest != inputs.runtime.execution_profile_digest_v1()?
        || body.semantic_digest()? != digest(text("runtime_body_digest")?)?
        || Digest32::of_bytes(&base_bytes) != body.base_bundle_digest
        || Digest32::of_bytes(&organ_bytes) != body.organ_bundle_digest
        || Digest32::of_bytes(&manifest_bytes) != body.body_manifest_digest
    {
        return Err("installed body differs from verified physical runtime".into());
    }
    let base: Value = serde_json::from_slice(&base_bytes)?;
    let organ: Value = serde_json::from_slice(&organ_bytes)?;
    let program: Source = serde_json::from_value(base["program"].clone())?;
    let provenance: Source = serde_json::from_value(base["source_provenance"].clone())?;
    let program_bytes = program.read(512 * 1024 * 1024)?;
    let provenance_bytes = provenance.read(64 * 1024)?;
    let build: Value = serde_json::from_slice(&provenance_bytes)?;
    let current_exe = std::fs::File::open("/proc/self/exe")?;
    if current_exe.metadata()?.len() > 512 * 1024 * 1024 {
        return Err("actual WorkerHost ELF bounds".into());
    }
    use std::io::Read;
    let mut actual = Vec::new();
    current_exe
        .take(512 * 1024 * 1024 + 1)
        .read_to_end(&mut actual)?;
    if !program_bytes.starts_with(b"\x7fELF")
        || program_bytes != actual
        || Digest32::of_bytes(&provenance_bytes) != body.source_revision_digest
        || build["schema"] != "hepta.cpu-neuron.installed-native-build-provenance.v1"
        || build["qualification_features"] != serde_json::json!([])
        || build["program"] != base["program"]
    {
        return Err("Root body does not bind this actual normal WorkerHost ELF".into());
    }
    for (key, expected) in [
        ("original_profile", inputs.physical_profile_source()),
        ("model", &inputs.profile.model),
        ("weights", &inputs.profile.weights),
    ] {
        let item: Source = serde_json::from_value(organ[key].clone())?;
        if &item != expected {
            return Err("body organ source differs from verified profile".into());
        }
        item.read(16 * 1024 * 1024)?;
    }
    let preprocessor: Source = serde_json::from_value(organ["preprocessor"].clone())?;
    preprocessor.read(64 * 1024)?;
    if digest(&preprocessor.digest)? != inputs.runtime.normalization_digest
        || source.read(32 * 1024)? != bytes
    {
        return Err("body normalization or source changed".into());
    }
    Ok(body)
}
