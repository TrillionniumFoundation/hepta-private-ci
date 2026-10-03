//! Distinct independent S purpose for a genuinely CURRENT-registered sparse
//! successor. The original three selection signatures remain the load seam.
use super::*;
use codex_hepta_agent_components::intelligence_eval::RegisteredArtifactCurrentFactsV3;
use codex_hepta_agent_components::intelligence_eval::RegisteredOperationalModelBindingV3;
use codex_hepta_agent_components::intelligence_eval::VerifiedRegisteredOperationalEvaluationV3;
use codex_hepta_agent_components::intelligence_eval::inspect_registered_artifact_current_material_v3;
use codex_hepta_agent_components::intelligence_eval::inspect_registered_operational_evaluation_v3;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::VerifyingKey;
use serde::Serialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    subject: String,
    workload_uid: u32,
    evaluation_config: Source,
    independent_report: Source,
    current_material: Source,
    artifact_public_trust: Source,
    selector_program: Source,
    selector: Role,
    authority_epoch: u64,
    frozen_at_ms: u64,
    expires_at_ms: u64,
    inaccessible_paths: Vec<std::path::PathBuf>,
}

/// Read the original pinned configuration's registration Source. This factual
/// projection grants no S authority and does not consume or renew a selection.
pub(crate) fn current_material_source(
    source: &InstalledCpuSourceV1,
    subject: &StableId,
) -> HostResult<(InstalledCpuSourceV1, Vec<u8>)> {
    let bytes = Source {
        path: source.path.clone(),
        digest: source.digest.clone(),
    }.read(64 * 1024)?;
    let config: Configuration = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.cpu-neuron.registered-model-use-config.v3"
        || config.subject != subject.as_str()
        || !config.current_material.path.is_absolute()
        || digest(&config.current_material.digest)?.is_zero()
    {
        return Err("whole original registered configuration or material Source differs".into());
    }
    Ok((InstalledCpuSourceV1 {
        path: config.current_material.path,
        digest: config.current_material.digest,
    }, bytes))
}
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct Body {
    schema: String,
    configuration_digest: String,
    binding: RegisteredOperationalModelBindingV3,
    evaluator_authentication_digest: String,
    selector_id: String,
    selector_controller_id: String,
    selector_credential_digest: String,
    selector_key_digest: String,
    selector_program_digest: String,
    selector_uid: u32,
    selector_gid: u32,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
}
impl Body {
    fn signing_bytes(&self) -> HostResult<Vec<u8>> {
        let mut bytes = b"hepta.cpu-neuron.registered-abstention-model-use.v3\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(self)?);
        if bytes.len() > 32 * 1024 {
            return Err("bounded full registered S signature preimage".into());
        }
        Ok(bytes)
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Selection {
    body: Body,
    signature_hex: String,
    artifact_signatures: [String; 3],
}

fn require_current_binding(
    actual: Option<&RegisteredOperationalModelBindingV3>,
    expected: &RegisteredOperationalModelBindingV3,
) -> HostResult<()> {
    expected.binding_digest()?;
    if actual != Some(expected) {
        return Err(
            "registered S whole CURRENT/material/publication tuple differs from actual E".into(),
        );
    }
    Ok(())
}

struct UseInputs {
    source: Source,
    bytes: Vec<u8>,
    config: Configuration,
    evaluator: VerifiedRegisteredOperationalEvaluationV3,
    facts: RegisteredArtifactCurrentFactsV3,
    verifier: ArtifactSelectionVerifierV1,
    registry_id: StableId,
    selector_key_digest: Digest32,
    selector_controller: StableId,
    selector_expiry: u64,
}
impl UseInputs {
    fn read(source: Source, now: u64) -> HostResult<Self> {
        let bytes = source.read(64 * 1024)?;
        let config: Configuration = serde_json::from_slice(&bytes)?;
        if config.schema != "hepta.cpu-neuron.registered-model-use-config.v3"
            || config.authority_epoch == 0
            || config.frozen_at_ms == 0
            || config.frozen_at_ms > now
            || config.expires_at_ms <= now
            || config.expires_at_ms.saturating_sub(config.frozen_at_ms) > 86_400_000
            || config.inaccessible_paths.len() != 5
            || config.workload_uid == 0
            || config.selector.uid == config.workload_uid
            || config.selector.uid == 0
            || config.selector.gid == 0
        {
            return Err("bounded registered independent S policy".into());
        }
        let evaluator = inspect_registered_operational_evaluation_v3(
            &config.evaluation_config.path,
            digest(&config.evaluation_config.digest)?,
            &config.independent_report.path,
            digest(&config.independent_report.digest)?,
        )?;
        let enrolled = evaluator
            .trusted_selector(&id(&config.selector.id)?)
            .ok_or("original current Root selector roster")?;
        if enrolled.principal.credential_chain_digest != digest(&config.selector.credential_digest)?
            || enrolled.verifying_key != public(&config.selector.public_key_hex)?
            || enrolled.principal.signing_key_digest != Digest32::of_bytes(&enrolled.verifying_key)
            || enrolled.controller_id == *evaluator.evaluator().controller_id()
            || enrolled.principal.authority_epoch != config.authority_epoch
            || now >= enrolled.principal.expires_at
            || enrolled.revoked_at.is_some_and(|at| now >= at)
        {
            return Err(
                "registered S differs from current original roster or independent controller"
                    .into(),
            );
        }
        enrolled.principal.validate(now)?;
        let selector_expiry = enrolled
            .principal
            .expires_at
            .min(enrolled.revoked_at.unwrap_or(u64::MAX));
        let selector_controller = enrolled.controller_id.clone();
        let binding = evaluator.binding();
        if binding.subject != config.subject
            || binding.authority_epoch != config.authority_epoch
            || config.selector.id == evaluator.evaluator().principal().principal_id.as_str()
            || digest(&config.selector.credential_digest)?
                == evaluator.evaluator().principal().credential_chain_digest
            || Digest32::of_bytes(&public(&config.selector.public_key_hex)?)
                == evaluator.evaluator().principal().signing_key_digest
            || config.selector.uid == evaluator.evaluator_uid()
            || config.selector.gid == evaluator.evaluator_gid()
        {
            return Err("registered S is not independent of actual E/full subject".into());
        }
        let facts = inspect_registered_artifact_current_material_v3(
            &config.current_material.path,
            digest(&config.current_material.digest)?,
            evaluator.material(),
            &id(&config.subject)?,
            now,
        )?;
        require_current_binding(facts.operational_binding(), binding)?;
        let owner_trust = decode_artifact_public_trust_v1(
            &config
                .artifact_public_trust
                .read(MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1 as u64)?,
        )?;
        let registry_id = owner_trust.registry_id.clone();
        let selector_key_digest = Digest32::of_bytes(&public(&config.selector.public_key_hex)?);
        let verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: owner_trust.registry_id.clone(),
                withdrawal_scope_digest: owner_trust.withdrawal_scope_digest,
                minimum_authority_epoch: config.authority_epoch,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id(&config.selector.id)?,
                    verifying_key: public(&config.selector.public_key_hex)?,
                    minimum_authority_epoch: config.authority_epoch,
                    maximum_authority_epoch: config.authority_epoch,
                    valid_from: config.frozen_at_ms,
                    expires_at: config.expires_at_ms,
                    revoked_at: None,
                }],
            },
            &owner_trust,
        )?;
        if ArtifactOwnerVerifierV1::new(owner_trust)?.trust_digest()
            != facts.current_view().trust_digest()
        {
            return Err(
                "registered S independent owner public trust differs from actual CURRENT".into(),
            );
        }
        Ok(Self {
            source,
            bytes,
            config,
            evaluator,
            facts,
            verifier,
            registry_id,
            selector_key_digest,
            selector_controller,
            selector_expiry,
        })
    }
    fn body(&self, issued_at: u64) -> Body {
        Body {
            schema: "hepta.cpu-neuron.registered-abstention-model-use.v3".into(),
            configuration_digest: self.source.digest.clone(),
            binding: self.evaluator.binding().clone(),
            evaluator_authentication_digest: self.evaluator.authentication_digest().to_string(),
            selector_id: self.config.selector.id.clone(),
            selector_controller_id: self.selector_controller.to_string(),
            selector_credential_digest: self.config.selector.credential_digest.clone(),
            selector_key_digest: self.selector_key_digest.to_string(),
            selector_program_digest: self.config.selector_program.digest.clone(),
            selector_uid: self.config.selector.uid,
            selector_gid: self.config.selector.gid,
            authority_epoch: self.config.authority_epoch,
            issued_at,
            expires_at: self
                .config
                .expires_at_ms
                .min(self.evaluator.expires_at())
                .min(self.facts.expires_at())
                .min(self.selector_expiry),
        }
    }
    fn selection(
        &self,
        body: &Body,
        index: usize,
        signature: [u8; 64],
    ) -> HostResult<SignedArtifactSelectionV1> {
        let full = &self.facts.manifests()[index];
        let current = self.facts.current_view();
        let manifest = current
            .eligible_manifest(&full.manifest.artifact_id)
            .ok_or("registered original eligible selection material")?;
        Ok(SignedArtifactSelectionV1 {
            selection_id: id(&format!(
                "registered-selected:{index}:{}",
                Digest32::of_bytes(&body.signing_bytes()?)
            ))?,
            artifact_id: manifest.artifact_id.clone(),
            registry_id: self.registry_id.clone(),
            withdrawal_scope_digest: digest(&body.binding.withdrawal_scope)?,
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: manifest.predecessor_id.clone(),
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id(&body.selector_id)?,
            selector_credential_digest: digest(&body.selector_credential_digest)?,
            signing_key_digest: digest(&body.selector_key_digest)?,
            authority_epoch: body.authority_epoch,
            issued_at: body.issued_at,
            expires_at: body.expires_at,
            signature,
        })
    }
    fn revalidate(&self, now: u64) -> HostResult<()> {
        self.evaluator.revalidate_current()?;
        self.facts.revalidate_current(now)?;
        if self.source.read(64 * 1024)? != self.bytes {
            return Err("registered S protected configuration changed".into());
        }
        codex_hepta_agent_components::intelligence_eval::verify_registered_operational_program_v3(
            &self.config.selector_program.path,
            digest(&self.config.selector_program.digest)?,
        )?;
        Ok(())
    }
}

/// Actual fixed independent S process signs the original three Artifact
/// selections and a distinct complete operational purpose using only its key.
pub fn select_cpu_registered_model_use_v3(path: &Path, pin: Digest32) -> HostResult<Value> {
    let now = now_ms()?;
    let inputs = UseInputs::read(
        Source {
            path: path.to_owned(),
            digest: pin.to_string(),
        },
        now,
    )?;
    let key =
        role::actual_role_for_program(&inputs.config.selector_program, &inputs.config.selector)?;
    for denied in &inputs.config.inaccessible_paths {
        match std::fs::File::open(denied) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("registered S can read Gold/another role key".into()),
        }
    }
    let body = inputs.body(now);
    let mut signatures = std::array::from_fn(|_| String::new());
    for (i, slot) in signatures.iter_mut().enumerate() {
        let mut selected = inputs.selection(&body, i, [0; 64])?;
        let payload = read_root_review_input(
            &inputs.facts.artifact_root().join("payloads").join(format!(
                "{}-{}.bin",
                selected.artifact_id, selected.content_digest
            )),
            16 * 1024 * 1024,
        )?;
        if Digest32::of_bytes(&payload) != selected.content_digest
            || u64::try_from(payload.len())? != selected.encoded_size_bytes
        {
            return Err("registered S whole original published payload differs".into());
        }
        inputs.revalidate(now_ms()?)?;
        selected.signature = key.sign(&selected.signing_bytes()).to_bytes();
        inputs
            .verifier
            .verify(&selected, inputs.facts.current_view(), now_ms()?)?;
        *slot = state::hex(&selected.signature);
    }
    let signed = key.sign(&body.signing_bytes()?).to_bytes();
    inputs.revalidate(now_ms()?)?;
    serde_json::to_value(Selection {
        body,
        signature_hex: state::hex(&signed),
        artifact_signatures: signatures,
    })
    .map_err(Into::into)
}

pub struct VerifiedRegisteredCpuModelUseV3 {
    inputs: UseInputs,
    selection: Source,
    body: Body,
    selections: [SignedArtifactSelectionV1; 3],
    clock_floor: std::sync::atomic::AtomicU64,
}
impl VerifiedRegisteredCpuModelUseV3 {
    pub fn material(&self) -> &codex_hepta_neuron::NeuronGenerationMaterialV2 {
        self.inputs.evaluator.material()
    }
    pub fn binding(&self) -> &RegisteredOperationalModelBindingV3 {
        &self.body.binding
    }
    pub fn selections(&self) -> &[SignedArtifactSelectionV1; 3] {
        &self.selections
    }
    pub fn selector_verifier(&self) -> ArtifactSelectionVerifierV1 {
        self.inputs.verifier.clone()
    }
    pub fn facts(&self) -> &RegisteredArtifactCurrentFactsV3 {
        &self.inputs.facts
    }
    pub fn workload_uid(&self) -> u32 {
        self.inputs.config.workload_uid
    }
    pub fn issued_at(&self) -> u64 {
        self.body.issued_at
    }
    pub(super) fn original_artifact_admission(
        &self,
        clock: std::sync::Arc<dyn codex_hepta_contracts::AuthorityClock>,
    ) -> HostResult<codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1> {
        self.revalidate_current()?;
        let facts = inspect_registered_artifact_current_material_v3(
            &self.inputs.config.current_material.path,
            digest(&self.inputs.config.current_material.digest)?,
            self.material(),
            &id(&self.binding().subject)?,
            clock.now_unix_ms()?,
        )?;
        require_current_binding(facts.operational_binding(), self.binding())?;
        let artifact_root = facts.artifact_root().to_path_buf();
        let selected = codex_hepta_agentd::NeuronSelectedArtifactsV1 {
            model: self.selections[0].clone(),
            calibration: self.selections[1].clone(),
            ood: self.selections[2].clone(),
            model_artifact_manifest: facts.manifests()[0].manifest.clone(),
            calibration_lineage_digest: facts.manifests()[1].manifest_digest,
            ood_lineage_digest: facts.manifests()[2].manifest_digest,
        };
        Ok(
            codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1::from_read_only_owner(
                std::sync::Arc::new(std::sync::Mutex::new(facts.into_read_only_owner())),
                artifact_root,
                self.selector_verifier(),
                selected,
                clock,
                &self.material().runtime,
            )
            .map_err(|error| format!("original registered artifact admission: {error:?}"))?,
        )
    }
    pub fn expires_at(&self) -> u64 {
        self.body.expires_at
    }
    pub fn revalidate_current(&self) -> HostResult<()> {
        let now = now_ms()?;
        if now
            < self
                .clock_floor
                .fetch_max(now, std::sync::atomic::Ordering::AcqRel)
        {
            return Err("registered S retained clock rollback".into());
        }
        let current = inspect_cpu_registered_model_use_v3(
            &self.inputs.source.path,
            digest(&self.inputs.source.digest)?,
            &self.selection.path,
            digest(&self.selection.digest)?,
        )?;
        if current.body != self.body || current.selections != self.selections {
            return Err("registered complete S evidence changed".into());
        }
        Ok(())
    }
}
/// Read original public evidence only. Opening a physical worker, complete
/// three stores and each current Goal still requires their original owners.
pub fn inspect_cpu_registered_model_use_v3(
    path: &Path,
    pin: Digest32,
    selection_path: &Path,
    selection_pin: Digest32,
) -> HostResult<VerifiedRegisteredCpuModelUseV3> {
    let now = now_ms()?;
    let inputs = UseInputs::read(
        Source {
            path: path.to_owned(),
            digest: pin.to_string(),
        },
        now,
    )?;
    let source = Source {
        path: selection_path.to_owned(),
        digest: selection_pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let selection: Selection = serde_json::from_slice(&bytes)?;
    if selection.body != inputs.body(selection.body.issued_at)
        || selection.body.issued_at < inputs.config.frozen_at_ms
        || selection.body.issued_at > now
        || now >= selection.body.expires_at
    {
        return Err("registered original S full body/window".into());
    }
    let signature: [u8; 64] = decode_review_payload_hex(&selection.signature_hex)?
        .try_into()
        .map_err(|_| "registered S signature width")?;
    VerifyingKey::from_bytes(&public(&inputs.config.selector.public_key_hex)?)?.verify_strict(
        &selection.body.signing_bytes()?,
        &Signature::from_bytes(&signature),
    )?;
    let mut selections = Vec::new();
    for (i, hex) in selection.artifact_signatures.iter().enumerate() {
        let signature: [u8; 64] = decode_review_payload_hex(hex)?
            .try_into()
            .map_err(|_| "whole original Artifact selection signature width")?;
        let signed = inputs.selection(&selection.body, i, signature)?;
        inputs
            .verifier
            .verify(&signed, inputs.facts.current_view(), now)?;
        selections.push(signed);
    }
    inputs.revalidate(now_ms()?)?;
    if source.read(64 * 1024)? != bytes {
        return Err("whole registered selection changed at use".into());
    }
    Ok(VerifiedRegisteredCpuModelUseV3 {
        inputs,
        selection: source,
        body: selection.body,
        clock_floor: std::sync::atomic::AtomicU64::new(now),
        selections: selections
            .try_into()
            .map_err(|_| "three complete original selections")?,
    })
}

#[cfg(test)]
#[path = "initial_cpu_registered_model_use_v3_tests.rs"]
mod tests;
