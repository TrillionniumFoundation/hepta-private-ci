//! The selected model's body comes from the original Root materialized closure.
//! E's stable implementation closure must name that same actual worker program.
use super::*;
use codex_hepta_neuron::NeuronBodyBundleIdentityV1;

pub(super) fn verify_body(
    source: &Source,
    implementation: &Source,
    inputs: &Inputs,
    agent: &str,
) -> HostResult<Digest32> {
    let bytes = source.read(32 * 1024)?;
    let compiled: Value = serde_json::from_slice(&bytes)?;
    let text = |key: &str| -> HostResult<&str> {
        Ok(compiled[key].as_str().ok_or("installed body field")?)
    };
    if text("schema")? != "hepta.cpu-neuron.installed-body-manifest.v1"
        || text("agent_id")? != agent
        || !compiled["cell_slot_id"].is_null()
        || !compiled["cell_bundle_digest"].is_null()
        || compiled["resource_authority_issued"] != false
    {
        return Err("installed model-use physical body identity".into());
    }
    let sources: Vec<Source> = serde_json::from_value(compiled["sources"].clone())?;
    if sources.len() != 3 {
        return Err("complete installed body closure".into());
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
            return Err("compiled physical body differs from original manifest".into());
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
        return Err("installed physical body differs from actual runtime tuple".into());
    }
    let base: Value = serde_json::from_slice(&base_bytes)?;
    let organ: Value = serde_json::from_slice(&organ_bytes)?;
    let closure: Value = serde_json::from_slice(&implementation.read(1024 * 1024)?)?;
    let program: Source = serde_json::from_value(base["program"].clone())?;
    let worker: Source = serde_json::from_value(closure["worker_host"].clone())?;
    let provenance: Source = serde_json::from_value(base["source_provenance"].clone())?;
    let provenance_bytes = provenance.read(64 * 1024)?;
    let build: Value = serde_json::from_slice(&provenance_bytes)?;
    if closure["schema"] != "hepta.cpu-neuron.implementation-closure.v2"
        || worker != program
        || Digest32::of_bytes(&provenance_bytes) != body.source_revision_digest
        || build["schema"] != "hepta.cpu-neuron.installed-native-build-provenance.v1"
        || build["qualification_features"] != serde_json::json!([])
        || build["program"] != base["program"]
    {
        return Err("stable E body closure differs from installed normal worker".into());
    }
    for (key, expected) in [
        ("original_profile", &inputs.profile_source),
        ("model", &inputs.profile.model),
        ("weights", &inputs.profile.weights),
    ] {
        let actual: Source = serde_json::from_value(organ[key].clone())?;
        if &actual != expected {
            return Err("body organ differs from original applied profile".into());
        }
    }
    let normalization: Source = serde_json::from_value(organ["preprocessor"].clone())?;
    normalization.read(64 * 1024)?;
    if digest(&normalization.digest)? != inputs.runtime.normalization_digest
        || source.read(32 * 1024)? != bytes
    {
        return Err("installed normalization or body changed".into());
    }
    body.semantic_digest().map_err(Into::into)
}
