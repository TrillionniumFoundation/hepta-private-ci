//! Sign and consume the original three Artifact selections, with full E1 scope.
use super::*;
use codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1;
use codex_hepta_agentd::NeuronSelectedArtifactsV1;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::VerifyingKey;
use std::sync::Mutex;

pub fn select_parameter_pre_registered_artifacts_v1(
    path: &Path,
    pin: Digest32,
) -> HostResult<Value> {
    let inputs = RegistrationInputs::read(
        Source {
            path: path.to_owned(),
            digest: pin.to_string(),
        },
        now_ms()?,
    )?;
    let key =
        role::actual_role_for_program(&inputs.config.selector_program, &inputs.config.selector)?;
    for denied in &inputs.config.inaccessible_paths {
        match std::fs::File::open(denied) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => {
                return Err(
                    "independent Root S can read Gold/another role key or denial is not physical"
                        .into(),
                );
            }
        }
    }
    let initial = now_ms()?;
    inputs.revalidate(initial)?;
    let mut body = inputs.body(initial)?;
    let mut signatures = std::array::from_fn(|_| String::new());
    // The actual original payloads, not descriptor echoes, are read by S before
    // signing. Every selection still uses the original Artifact verifier.
    for index in 0..4 {
        let selected = inputs.selection(&body, index, [0; 64])?;
        let bytes = read_root_review_input(
            &inputs.facts.artifact_root().join("payloads").join(format!(
                "{}-{}.bin",
                selected.artifact_id, selected.content_digest
            )),
            16 * 1024 * 1024,
        )?;
        if Digest32::of_bytes(&bytes) != selected.content_digest
            || u64::try_from(bytes.len())? != selected.encoded_size_bytes
        {
            return Err("pre-registration S read a different actual Root payload".into());
        }
    }
    inputs.revalidate(now_ms()?)?;
    let final_now = now_ms()?;
    if final_now < initial || final_now >= body.expires_at_ms {
        return Err(
            "pre-registration S expired or clock rolled back during actual payload reads".into(),
        );
    }
    role::require_actual_program(&inputs.config.selector_program, &inputs.config.selector)?;
    // Rebuild all three signatures at this final observed instant, so they and
    // the complete purpose share one exact expiry/clock/current tuple.
    body.issued_at_ms = final_now;
    for (index, slot) in signatures.iter_mut().enumerate() {
        let mut selected = inputs.selection(&body, index, [0; 64])?;
        selected.signature = key.sign(&selected.signing_bytes()).to_bytes();
        inputs
            .verifier
            .verify(&selected, inputs.facts.current_view(), final_now)?;
        *slot = state::hex(&selected.signature);
    }
    let result = serde_json::to_value(Selection {
        signature_hex: state::hex(&key.sign(&body.signing_bytes()?).to_bytes()),
        body,
        artifact_signatures: signatures,
    })?;
    inputs.facts.revalidate_current(now_ms()?)?;
    if now_ms()? >= inputs.expiry {
        return Err("pre-registration S expired at publication".into());
    }
    Ok(result)
}

pub struct VerifiedParameterPreRegisteredAdmissionV1 {
    inputs: RegistrationInputs,
    selection: Source,
    body: Body,
    material: NeuronGenerationMaterialV2,
    selections: [SignedArtifactSelectionV1; 4],
    clock_floor: std::sync::atomic::AtomicU64,
}
impl VerifiedParameterPreRegisteredAdmissionV1 {
    pub fn material(&self) -> &NeuronGenerationMaterialV2 {
        &self.material
    }
    pub fn round(&self) -> &ParameterPreRegistrationRoundV1 {
        &self.body.original_round
    }
    pub fn purpose(&self) -> ParameterPreRegistrationPurposeV1 {
        self.body.purpose
    }
    pub fn head_selection(&self) -> &SignedArtifactSelectionV1 {
        &self.selections[3]
    }
    pub fn candidate_id(&self) -> &StableId {
        self.inputs.evaluation.candidate_id()
    }
    pub fn selections(&self) -> &[SignedArtifactSelectionV1; 4] {
        &self.selections
    }
    pub fn revalidate_current(&self) -> HostResult<()> {
        let now = now_ms()?;
        if now
            < self
                .clock_floor
                .fetch_max(now, std::sync::atomic::Ordering::AcqRel)
        {
            return Err("pre-registration S retained clock rollback".into());
        }
        let actual = inspect_parameter_pre_registered_admission_v1(
            &self.inputs.source.path,
            digest(&self.inputs.source.digest)?,
            &self.selection.path,
            digest(&self.selection.digest)?,
        )?;
        if actual.body != self.body || actual.selections != self.selections {
            return Err("whole original S material/selection changed".into());
        }
        self.clock_floor.fetch_max(
            actual
                .clock_floor
                .load(std::sync::atomic::Ordering::Acquire),
            std::sync::atomic::Ordering::AcqRel,
        );
        Ok(())
    }
    /// Transfer the actual read-only owner to the original Agentd admission.
    /// This opens no generation store, creates no worker and grants no activation.
    pub fn into_original_admission(
        self,
        clock: Arc<dyn AuthorityClock>,
    ) -> HostResult<(NeuronGenerationMaterialV2, AgentdNeuronArtifactAdmissionV1)> {
        self.revalidate_current()?;
        let now = clock.now_unix_ms()?;
        if now < self.clock_floor.load(std::sync::atomic::Ordering::Acquire)
            || now >= self.body.expires_at_ms
        {
            return Err("original candidate admission clock/expiry".into());
        }
        self.inputs.facts.revalidate_current(now)?;
        let material = self.material().clone();
        let root = self.inputs.facts.artifact_root().to_owned();
        let selected = NeuronSelectedArtifactsV1 {
            model: self.selections[0].clone(),
            calibration: self.selections[1].clone(),
            ood: self.selections[2].clone(),
            model_artifact_manifest: self.inputs.facts.manifests()[0].manifest.clone(),
            calibration_lineage_digest: self.inputs.facts.manifests()[1].manifest_digest,
            ood_lineage_digest: self.inputs.facts.manifests()[2].manifest_digest,
        };
        let admission = AgentdNeuronArtifactAdmissionV1::from_read_only_owner(
            Arc::new(Mutex::new(self.inputs.facts.into_read_only_owner())),
            root,
            self.inputs.verifier,
            selected,
            clock,
            &material.runtime,
        )
        .map_err(|error| format!("original candidate artifact admission: {error:?}"))?;
        Ok((material, admission))
    }
}
pub fn inspect_parameter_pre_registered_admission_v1(
    path: &Path,
    pin: Digest32,
    selection_path: &Path,
    selection_pin: Digest32,
) -> HostResult<VerifiedParameterPreRegisteredAdmissionV1> {
    let now = now_ms()?;
    let inputs = RegistrationInputs::read(
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
    if selection.body != inputs.body(selection.body.issued_at_ms)?
        || selection.body.issued_at_ms < inputs.config.frozen_at_ms
        || selection.body.issued_at_ms > now
        || now >= selection.body.expires_at_ms
    {
        return Err("whole pre-registration S body/actual time/window".into());
    }
    let signature: [u8; 64] = decode_review_payload_hex(&selection.signature_hex)?
        .try_into()
        .map_err(|_| "actual complete S signature width")?;
    VerifyingKey::from_bytes(&public(&inputs.config.selector.public_key_hex)?)?.verify_strict(
        &selection.body.signing_bytes()?,
        &Signature::from_bytes(&signature),
    )?;
    let mut selections = Vec::new();
    for (index, hex) in selection.artifact_signatures.iter().enumerate() {
        let signed = inputs.selection(
            &selection.body,
            index,
            decode_review_payload_hex(hex)?
                .try_into()
                .map_err(|_| "complete original Artifact selection signature")?,
        )?;
        inputs
            .verifier
            .verify(&signed, inputs.facts.current_view(), now)?;
        selections.push(signed);
    }
    inputs.revalidate(now_ms()?)?;
    let settled = now_ms()?;
    inputs.facts.revalidate_current(settled)?;
    if settled < now || settled >= selection.body.expires_at_ms || source.read(64 * 1024)? != bytes
    {
        return Err(
            "pre-registration S expired or protected sources changed during actual validation"
                .into(),
        );
    }
    let material = inputs
        .evaluation
        .material()
        .ok_or("qualified original E1 material")?
        .clone();
    Ok(VerifiedParameterPreRegisteredAdmissionV1 {
        material,
        inputs,
        selection: source,
        body: selection.body,
        selections: selections
            .try_into()
            .map_err(|_| "three operational artifacts and the separate native-head selection")?,
        clock_floor: std::sync::atomic::AtomicU64::new(settled),
    })
}
