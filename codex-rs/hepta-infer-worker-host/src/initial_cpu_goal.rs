//! Read the exact Root-frozen goal through the product compiler before E/S
//! freeze. This preview issues no signature, RunStart or admission capability.
use super::*;
use codex_hepta_agent_components::objective::ObjectiveAdmissionContextV1;
use codex_hepta_agent_components::objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_agent_components::objective::admit_and_compile_objective_v1;
use codex_hepta_agent_components::objective::canonical_native_objective_semantic_bytes_v1;
use codex_hepta_agent_components::objective::decode_admission_profile_json_v1;
use codex_hepta_agent_components::objective::decode_source_envelope_json_v1;
use codex_hepta_agent_components::objective::encode_objective_function_v1;
use codex_hepta_types::Revision;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Goal {
    schema: String,
    source_envelope: Source,
    admission_profile: Source,
    adapter_identity: String,
    objective_revision: u64,
}

pub(super) fn preview(path: &Path, pin: Digest32) -> HostResult<Value> {
    if rustix::process::geteuid().as_raw() != 0 {
        return Err("initial objective preview requires the Root installer".into());
    }
    let descriptor = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = descriptor.read(16 * 1024)?;
    let goal: Goal = serde_json::from_slice(&bytes)?;
    if goal.schema != "hepta.cpu-neuron.root-objective-preview-input.v1" {
        return Err("initial objective preview schema".into());
    }
    let source_bytes = goal.source_envelope.read(32 * 1024)?;
    let profile_bytes = goal.admission_profile.read(262_144)?;
    let source = decode_source_envelope_json_v1(&source_bytes)?;
    let profile = decode_admission_profile_json_v1(&profile_bytes)?;
    let context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(goal.objective_revision)?,
        now_unix_micros: now_ms()?
            .checked_mul(1_000)
            .ok_or("objective clock overflow")?,
        selected_profile_digest: profile.digest()?,
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: id(&goal.adapter_identity)?,
            source_digest: source.structured_intent.provenance.source_digest,
        },
    };
    let outcome = admit_and_compile_objective_v1(&source, &profile, &context)?;
    let compiled = outcome
        .compile_result
        .as_ref()
        .map_err(|_| "Root goal did not compile")?;
    let semantic = canonical_native_objective_semantic_bytes_v1(&compiled.objective);
    if semantic.len() > 32 * 1024
        || Digest32::of_bytes(&semantic) != compiled.objective.semantic_digest
    {
        return Err("actual objective semantic output bounds or digest".into());
    }
    let protocol = encode_objective_function_v1(compiled, &source, &profile, &outcome.receipt)?;
    if descriptor.read(16 * 1024)? != bytes
        || goal.source_envelope.read(32 * 1024)? != source_bytes
        || goal.admission_profile.read(262_144)? != profile_bytes
    {
        return Err("Root goal changed during product compilation".into());
    }
    Ok(serde_json::json!({
        "schema": "hepta.cpu-neuron.root-compiled-objective-preview.v1",
        "source_envelope": goal.source_envelope, "admission_profile": goal.admission_profile,
        "adapter_identity": goal.adapter_identity, "objective_revision": goal.objective_revision,
        "objective_digest": compiled.objective.semantic_digest.to_string(),
        "hard_constraint_digest": compiled.objective.hard_constraint_digest.to_string(),
        "objective_function_v1_digest": protocol.protocol_digest().to_string(),
        "admitted_source_digest": outcome.receipt.admitted_source_digest.to_string(),
        "observed_at_unix_micros": outcome.receipt.observed_at_unix_micros,
        "deadline_unix_micros": outcome.receipt.deadline_unix_micros,
        "runtime_admission_issued": false, "signature_issued": false,
    }))
}
