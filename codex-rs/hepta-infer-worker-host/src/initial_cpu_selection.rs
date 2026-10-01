//! The independent selector signs only the complete measured, Root-ACKed
//! first-generation profile. Consumers reconstruct every original signed field.
use super::*;
use codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1;
use codex_hepta_agentd::NeuronSelectedArtifactsV1;
use codex_hepta_contracts::AuthorityClock;
use ed25519_dalek::Signer;
use serde::Serialize;
use std::sync::Arc;
use std::sync::Mutex;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Selections {
    schema: String,
    profile_digest: String,
    evidence_digest: String,
    registry_head: String,
    current_witness: String,
    current_trust: String,
    issued_at: u64,
    expires_at: u64,
    signatures: [String; 3],
}
pub(super) fn select(inputs: Inputs) -> HostResult<Value> {
    let key = role::actual_role(&inputs, &inputs.profile.selector)?;
    let owner = inputs.current()?;
    let now = now_ms()?;
    let current = owner.current_registry_view(now)?;
    let mut wire = Selections {
        schema: schema(&inputs).into(),
        profile_digest: inputs.profile_source.digest.clone(),
        evidence_digest: inputs.evidence.authentication_digest().to_string(),
        registry_head: current.receipt().head_digest.to_string(),
        current_witness: current.witness_digest().to_string(),
        current_trust: current.trust_digest().to_string(),
        issued_at: now,
        expires_at: inputs
            .evidence
            .expires_at()
            .min(inputs.profile.expires_at_ms),
        signatures: std::array::from_fn(|_| String::new()),
    };
    let verifier = inputs.selector_verifier()?;
    for index in 0..3 {
        let mut signed = selection(&inputs, &wire, index, &current)?;
        let payload = read_root_review_input(
            &inputs.profile.owner_root.join("payloads").join(format!(
                "{}-{}.bin",
                signed.artifact_id, signed.content_digest
            )),
            16 * 1024 * 1024,
        )?;
        if payload != inputs.payloads[index] {
            return Err("independent selector read a different actual published payload".into());
        }
        inputs.revalidate()?;
        let latest = owner.current_registry_view(now_ms()?)?;
        if latest.receipt() != current.receipt()
            || latest.witness_digest() != current.witness_digest()
            || latest.trust_digest() != current.trust_digest()
        {
            return Err("CURRENT changed while independent S read exact payloads".into());
        }
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        verifier.verify(&signed, &latest, now_ms()?)?;
        wire.signatures[index] = state::hex(&signed.signature);
    }
    inputs.revalidate()?;
    owner.current_registry_view(now_ms()?)?;
    Ok(serde_json::to_value(wire)?)
}
fn selection(
    inputs: &Inputs,
    wire: &Selections,
    index: usize,
    current: &VerifiedCurrentRegistryViewV1,
) -> HostResult<SignedArtifactSelectionV1> {
    let expected = &inputs.artifacts[index];
    let manifest = current
        .eligible_manifest(&expected.artifact_id)
        .ok_or("initial registered artifact missing")?;
    let full = validate_artifact_manifest_v2(expected.clone(), now_ms()?)?;
    if !current.is_eligible(&expected.artifact_id)
        || manifest.kind != expected.kind
        || manifest.generation != expected.generation
        || manifest.predecessor_id.is_some()
        || manifest.content_digest != expected.bytes_digest
        || manifest.encoded_size_bytes != expected.encoded_size_bytes
        || manifest.objective_digest != expected.objective_class_digest
        || manifest.support_digest != full.manifest_digest
        || manifest.compatibility_digest != expected.compatibility_digest
        || manifest.producer_id != expected.producer_id
    {
        return Err(
            "complete first-generation registered profile differs from independent E".into(),
        );
    }
    let signature = if wire.signatures[index].is_empty() {
        [0; 64]
    } else {
        decode_review_payload_hex(&wire.signatures[index])?
            .try_into()
            .map_err(|_| "independent selection signature width")?
    };
    Ok(SignedArtifactSelectionV1 {
        selection_id: id(&format!(
            "initial-selected:{index}:{}",
            inputs.evidence.authentication_digest()
        ))?,
        artifact_id: manifest.artifact_id.clone(),
        registry_id: id(&inputs.profile.registry_id)?,
        withdrawal_scope_digest: inputs
            .profile
            .withdrawals()?
            .scope_digest()
            .ok_or("scope")?,
        registry_head_digest: digest(&wire.registry_head)?,
        current_witness_digest: digest(&wire.current_witness)?,
        current_trust_digest: digest(&wire.current_trust)?,
        artifact_kind: manifest.kind,
        artifact_generation: manifest.generation,
        predecessor_id: None,
        content_digest: manifest.content_digest,
        objective_digest: manifest.objective_digest,
        support_digest: manifest.support_digest,
        compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
        selector_id: id(&inputs.profile.selector.id)?,
        selector_credential_digest: digest(&inputs.profile.selector.credential_digest)?,
        signing_key_digest: Digest32::of_bytes(&public(&inputs.profile.selector.public_key_hex)?),
        authority_epoch: 1,
        issued_at: wire.issued_at,
        expires_at: wire.expires_at,
        signature,
    })
}
pub(super) fn admission(
    inputs: &Inputs,
    source: &Source,
    clock: Arc<dyn AuthorityClock>,
) -> HostResult<AgentdNeuronArtifactAdmissionV1> {
    let wire: Selections = serde_json::from_slice(&source.read(16 * 1024)?)?;
    if wire.schema != schema(inputs)
        || wire.profile_digest != inputs.profile_source.digest
        || wire.evidence_digest != inputs.evidence.authentication_digest().to_string()
        || wire.issued_at < inputs.profile.frozen_at_ms
        || wire.issued_at > now_ms()?
        || wire.expires_at
            != inputs
                .evidence
                .expires_at()
                .min(inputs.profile.expires_at_ms)
        || wire.signatures.iter().any(String::is_empty)
    {
        return Err("original current independent S output differs".into());
    }
    let owner = inputs.current()?;
    let current = owner.current_registry_view(now_ms()?)?;
    let selections = [
        selection(inputs, &wire, 0, &current)?,
        selection(inputs, &wire, 1, &current)?,
        selection(inputs, &wire, 2, &current)?,
    ];
    let calibration_lineage_digest = selections[1].support_digest;
    let ood_lineage_digest = selections[2].support_digest;
    let [model, calibration, ood] = selections;
    let mut admission = AgentdNeuronArtifactAdmissionV1::from_read_only_owner(
        Arc::new(Mutex::new(owner)),
        &inputs.profile.owner_root,
        inputs.selector_verifier()?,
        NeuronSelectedArtifactsV1 {
            model,
            calibration,
            ood,
            model_artifact_manifest: inputs.artifacts[0].clone(),
            calibration_lineage_digest,
            ood_lineage_digest,
        },
        clock,
        &inputs.runtime,
    )
    .map_err(|error| format!("current initial Neuron admission: {error:?}"))?;
    admission
        .validate_initial_generation(&inputs.runtime)
        .map_err(|error| format!("genuine initial generation admission: {error:?}"))?;
    inputs.revalidate()?;
    source.read(16 * 1024)?;
    Ok(admission)
}

fn schema(inputs: &Inputs) -> &'static str {
    if inputs.renewal.is_some() {
        "hepta.cpu-neuron.fresh-operational-independent-selections.v1"
    } else {
        "hepta.cpu-neuron.initial-independent-selections.v1"
    }
}
