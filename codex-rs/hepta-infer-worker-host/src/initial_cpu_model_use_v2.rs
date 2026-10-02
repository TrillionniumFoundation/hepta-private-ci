//! Independent S grants bounded use of the already installed model only. The
//! Goal, final use, installation and promotion authorities remain separate.
use super::*;
use codex_hepta_agent_components::intelligence_eval::OperationalModelLeaseBindingV2;
use codex_hepta_agent_components::intelligence_eval::OperationalModelUseV2;
use codex_hepta_agent_components::intelligence_eval::VerifiedOperationalModelLeaseV2;
use codex_hepta_agent_components::intelligence_eval::inspect_operational_model_lease_v2;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use serde::Serialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    installed_deployment: Source,
    evaluation_config: Source,
    independent_report: Source,
    body_implementation: Source,
    compiled_body: Source,
    selector_program: Source,
}

#[derive(Clone, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct Body {
    schema: String,
    configuration_digest: String,
    model_binding: Value,
    evaluator_authentication_digest: String,
    installed_identity_digest: String,
    installed_body_digest: String,
    runtime_body_digest: String,
    registry_head: String,
    current_witness: String,
    current_trust: String,
    withdrawal_scope: String,
    withdrawal_head: String,
    authority_epoch: u64,
    payload_digests: [String; 3],
    selector_id: String,
    selector_credential_digest: String,
    selector_key_digest: String,
    selector_program_digest: String,
    issued_at: u64,
    expires_at: u64,
}
impl Body {
    fn signing_bytes(&self) -> HostResult<Vec<u8>> {
        let mut bytes = b"hepta.cpu-neuron.installed-abstention-model-use.v2\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(self)?);
        if bytes.len() > 32 * 1024 {
            return Err("bounded stable model-use signature preimage".into());
        }
        Ok(bytes)
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Selection {
    body: Body,
    signature_hex: String,
}

struct UseInputs {
    source: Source,
    bytes: Vec<u8>,
    configuration: Configuration,
    installed: Inputs,
    lease: VerifiedOperationalModelLeaseV2,
    body_digest: Digest32,
    selector_program: super::model_use_program::Program,
}
impl UseInputs {
    fn read(source: Source) -> HostResult<Self> {
        let bytes = source.read(32 * 1024)?;
        let configuration: Configuration = serde_json::from_slice(&bytes)?;
        if configuration.schema != "hepta.cpu-neuron.installed-model-use-config.v2" {
            return Err("installed model-use configuration schema".into());
        }
        let selector_program =
            super::model_use_program::Program::open(configuration.selector_program.clone())?;
        let installed = Inputs::read(
            &configuration.installed_deployment.path,
            digest(&configuration.installed_deployment.digest)?,
        )?;
        let lease = inspect_operational_model_lease_v2(
            &configuration.evaluation_config.path,
            digest(&configuration.evaluation_config.digest)?,
            &configuration.independent_report.path,
            digest(&configuration.independent_report.digest)?,
        )?;
        let binding = lease.binding();
        let profile = lease.runtime_profile();
        let runtime = &installed.runtime;
        if binding.purpose != OperationalModelUseV2::ConservativeCpuAbstentionOnlyV1
            || binding.model_generation != runtime.generation.get()
            || binding.model_generation != 1
            || binding.model_manifest_digest != digest(&installed.profile.model.digest)?
            || binding.weights_digest != digest(&installed.profile.weights.digest)?
            || binding.training_code_digest != digest(&installed.profile.training_code.digest)?
            || binding.source_training_digest
                != digest(
                    installed.evidence.measurements()["source_training_digest"]
                        .as_str()
                        .ok_or("original installed training source")?,
                )?
            || binding.normalization_digest != runtime.normalization_digest
            || binding.body_implementation_digest
                != digest(&configuration.body_implementation.digest)?
            || profile.input_feature_dimension as usize != runtime.input_feature_dimension
            || profile.state_width as usize != runtime.state_width
            || profile.modulator_dimension as usize != runtime.modulator_dimension
            || profile.p95_latency_micros != runtime.resource_envelope.p95_latency_micros
            || profile.p99_latency_micros != runtime.resource_envelope.p99_latency_micros
            || profile.transient_allocation_bytes
                != runtime.resource_envelope.transient_allocation_bytes
            || profile.checkpoint_bytes != runtime.resource_envelope.checkpoint_bytes
            || profile.write_amplification_ppm != runtime.resource_envelope.write_amplification_ppm
            || serde_json::to_value(&profile.calibration_gates)?
                != installed.evidence.measurements()["initial_product_gates"]
        {
            return Err("stable E model use differs from the current installed CPU tuple".into());
        }
        let role = &installed.profile.selector;
        let evaluator = lease.evaluator().principal();
        let declaration = renewal::verify_first_installation(&installed.profile)?;
        if u64::from(role.uid)
            == lease.measurements()["evaluator_uid"]
                .as_u64()
                .ok_or("actual E uid")?
            || u64::from(role.gid)
                == lease.measurements()["evaluator_gid"]
                    .as_u64()
                    .ok_or("actual E gid")?
            || role.uid == declaration.workload_uid
            || role.id == evaluator.principal_id.as_str()
            || digest(&role.credential_digest)? == evaluator.credential_chain_digest
            || Digest32::of_bytes(&public(&role.public_key_hex)?) == evaluator.signing_key_digest
        {
            return Err("stable model-use S is not independent of actual E/workload".into());
        }
        let body_digest = super::model_use_body::verify_body(
            &configuration.compiled_body,
            &configuration.body_implementation,
            &installed,
            &declaration.agent_id,
        )?;
        let result = Self {
            source,
            bytes,
            configuration,
            installed,
            lease,
            body_digest,
            selector_program,
        };
        result.revalidate()?;
        Ok(result)
    }

    fn revalidate(&self) -> HostResult<()> {
        self.installed.revalidate()?;
        self.lease.revalidate_current()?;
        self.configuration.body_implementation.read(1024 * 1024)?;
        self.configuration.compiled_body.read(32 * 1024)?;
        self.selector_program.revalidate()?;
        let declaration = renewal::verify_first_installation(&self.installed.profile)?;
        if super::model_use_body::verify_body(
            &self.configuration.compiled_body,
            &self.configuration.body_implementation,
            &self.installed,
            &declaration.agent_id,
        )? != self.body_digest
        {
            return Err("installed physical body closure changed at use".into());
        }
        if self.source.read(32 * 1024)? != self.bytes {
            return Err("stable model-use configuration changed".into());
        }
        Ok(())
    }

    fn body(&self, issued_at: u64) -> HostResult<Body> {
        self.revalidate()?;
        let owner = self.installed.current()?;
        let now = now_ms()?;
        let current = owner.current_registry_view(now)?;
        let head = owner.protected_current_head(now)?;
        let profile = &self.installed.profile;
        let mut payload_digests = std::array::from_fn(|_| String::new());
        let mut expires_at = self
            .lease
            .expires_at()
            .min(profile.expires_at_ms)
            .min(head.witness.expires_at);
        for (index, expected) in self.installed.artifacts.iter().enumerate() {
            let manifest = current
                .eligible_manifest(&expected.artifact_id)
                .ok_or("installed artifact not CURRENT eligible")?;
            let full = validate_artifact_manifest_v2(expected.clone(), now)?;
            if manifest.kind != expected.kind
                || manifest.generation != expected.generation
                || manifest.predecessor_id.is_some()
                || manifest.content_digest != expected.bytes_digest
                || manifest.encoded_size_bytes != expected.encoded_size_bytes
                || manifest.objective_digest != expected.objective_class_digest
                || manifest.support_digest != full.manifest_digest
                || manifest.compatibility_digest != expected.compatibility_digest
                || manifest.producer_id != expected.producer_id
            {
                return Err("complete installed three-artifact CURRENT differs".into());
            }
            let path = profile.owner_root.join("payloads").join(format!(
                "{}-{}.bin",
                manifest.artifact_id, manifest.content_digest
            ));
            let payload = read_root_review_input(&path, 16 * 1024 * 1024)?;
            if payload != self.installed.payloads[index] {
                return Err("installed original artifact bytes differ".into());
            }
            payload_digests[index] = manifest.content_digest.to_string();
            expires_at = expires_at.min(expected.expires_at);
        }
        if issued_at < profile.frozen_at_ms
            || issued_at > now
            || expires_at <= now
            || issued_at > expires_at
        {
            return Err("stable S/model/CURRENT/source window expired or not issued".into());
        }
        let withdrawals = profile.withdrawals()?;
        Ok(Body {
            schema: "hepta.cpu-neuron.installed-abstention-model-use.v2".into(),
            configuration_digest: self.source.digest.clone(),
            model_binding: binding_value(self.lease.binding()),
            evaluator_authentication_digest: self.lease.authentication_digest().to_string(),
            installed_identity_digest: profile
                .first_physical_installation
                .as_ref()
                .ok_or("installed statement")?
                .digest
                .clone(),
            installed_body_digest: self.configuration.compiled_body.digest.clone(),
            runtime_body_digest: self.body_digest.to_string(),
            registry_head: current.receipt().head_digest.to_string(),
            current_witness: current.witness_digest().to_string(),
            current_trust: current.trust_digest().to_string(),
            withdrawal_scope: withdrawals
                .scope_digest()
                .ok_or("withdrawal scope")?
                .to_string(),
            withdrawal_head: withdrawals.head_digest().to_string(),
            authority_epoch: head.witness.authority_epoch,
            payload_digests,
            selector_id: profile.selector.id.clone(),
            selector_credential_digest: profile.selector.credential_digest.clone(),
            selector_key_digest: Digest32::of_bytes(&public(&profile.selector.public_key_hex)?)
                .to_string(),
            selector_program_digest: self.configuration.selector_program.digest.clone(),
            issued_at,
            expires_at,
        })
    }
}

fn binding_value(b: &OperationalModelLeaseBindingV2) -> Value {
    serde_json::json!({"model_generation":b.model_generation,"model_manifest_digest":b.model_manifest_digest.to_string(),
        "weights_digest":b.weights_digest.to_string(),"normalization_digest":b.normalization_digest.to_string(),
        "encoder_manifest_digest":b.encoder_manifest_digest.to_string(),"tokenizer_digest":b.tokenizer_digest.to_string(),
        "training_code_digest":b.training_code_digest.to_string(),"source_training_digest":b.source_training_digest.to_string(),
        "preregistration_digest":b.preregistration_digest.to_string(),"body_implementation_digest":b.body_implementation_digest.to_string(),
        "model_runtime_profile_digest":b.model_runtime_profile_digest.to_string(),"purpose":b.purpose})
}

pub struct VerifiedCpuModelUseV2 {
    inputs: UseInputs,
    selection: Source,
    original_body: Body,
}
impl VerifiedCpuModelUseV2 {
    pub fn binding(&self) -> &OperationalModelLeaseBindingV2 {
        self.inputs.lease.binding()
    }
    pub fn expires_at(&self) -> u64 {
        self.original_body.expires_at
    }
    pub fn runtime_configuration(&self) -> &codex_hepta_neuron::NeuronRuntimeConfigV1 {
        &self.inputs.installed.runtime
    }
    pub fn native_configuration(&self) -> &codex_hepta_neuron::SparseConfig {
        &self.inputs.installed.native
    }
    pub fn runtime_body_digest(&self) -> Digest32 {
        self.inputs.body_digest
    }
    pub fn revalidate_current(&self) -> HostResult<()> {
        if self.inputs.body(self.original_body.issued_at)? != self.original_body {
            return Err("stable model-use current tuple changed".into());
        }
        verify_selection(&self.inputs, &self.selection)?;
        Ok(())
    }
}
fn verify_selection(inputs: &UseInputs, source: &Source) -> HostResult<Body> {
    let wire: Selection = serde_json::from_slice(&source.read(32 * 1024)?)?;
    if inputs.body(wire.body.issued_at)? != wire.body {
        return Err("independent stable S selection differs".into());
    }
    let signature: [u8; 64] = decode_review_payload_hex(&wire.signature_hex)?
        .try_into()
        .map_err(|_| "stable S signature width")?;
    ed25519_dalek::VerifyingKey::from_bytes(&public(
        &inputs.installed.profile.selector.public_key_hex,
    )?)?
    .verify_strict(
        &wire.body.signing_bytes()?,
        &Signature::from_bytes(&signature),
    )?;
    inputs.revalidate()?;
    Ok(wire.body)
}
pub fn inspect_cpu_model_use_v2(
    path: &Path,
    pin: Digest32,
    selection: &Path,
    selection_pin: Digest32,
) -> HostResult<VerifiedCpuModelUseV2> {
    let inputs = UseInputs::read(Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    })?;
    let selection = Source {
        path: selection.to_owned(),
        digest: selection_pin.to_string(),
    };
    let original_body = verify_selection(&inputs, &selection)?;
    Ok(VerifiedCpuModelUseV2 {
        inputs,
        selection,
        original_body,
    })
}
pub fn select_cpu_model_use_v2(path: &Path, pin: Digest32) -> HostResult<Value> {
    let inputs = UseInputs::read(Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    })?;
    let key = role::actual_role_for_program(
        &inputs.configuration.selector_program,
        &inputs.installed.profile.selector,
    )?;
    let body = inputs.body(now_ms()?)?;
    let signature = key.sign(&body.signing_bytes()?).to_bytes();
    inputs.revalidate()?;
    if inputs.body(body.issued_at)? != body {
        return Err("stable S CURRENT changed during signing".into());
    }
    Ok(serde_json::to_value(Selection {
        body,
        signature_hex: state::hex(&signature),
    })?)
}

#[cfg(test)]
#[path = "initial_cpu_model_use_v2_tests.rs"]
mod tests;
