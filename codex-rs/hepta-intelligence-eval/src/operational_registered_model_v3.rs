//! Whole factual CURRENT inspection and a distinct registered-successor purpose.
//! Decoding material or authenticating publication never opens a physical worker.
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_neuron::validate_neuron_generation_material_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RegisteredOperationalModelBindingV3 {
    pub purpose: String,
    pub subject: String,
    pub model_generation: u64,
    pub material_digest: String,
    pub runtime_digest: String,
    pub native_digest: String,
    pub body_digest: String,
    pub execution_profile_digest: String,
    pub input_profile_digest: String,
    pub objective_digest: String,
    pub scope_digest: String,
    pub model_artifact_id: String,
    pub predecessor_id: String,
    pub predecessor_manifest_digest: String,
    pub manifest_digests: [String; 3],
    pub payload_digests: [String; 3],
    pub registry_binding: String,
    pub registry_head: String,
    pub current_witness: String,
    pub current_trust: String,
    pub withdrawal_scope: String,
    pub withdrawal_head: String,
    pub publication_operation_id: String,
    pub authority_epoch: u64,
}
impl RegisteredOperationalModelBindingV3 {
    pub fn binding_digest(&self) -> HostResult<Digest32> {
        if self.purpose != "registered-successor-cpu-abstention-only.v3"
            || self.model_generation < 2
            || self.authority_epoch == 0
        {
            return Err("registered successor purpose/generation/epoch".into());
        }
        for id in [
            &self.subject,
            &self.model_artifact_id,
            &self.predecessor_id,
            &self.publication_operation_id,
        ] {
            StableId::new(id.clone())?;
        }
        for pin in [
            &self.material_digest,
            &self.runtime_digest,
            &self.native_digest,
            &self.body_digest,
            &self.execution_profile_digest,
            &self.input_profile_digest,
            &self.objective_digest,
            &self.scope_digest,
            &self.predecessor_manifest_digest,
            &self.registry_binding,
            &self.registry_head,
            &self.current_witness,
            &self.current_trust,
            &self.withdrawal_scope,
            &self.withdrawal_head,
        ]
        .into_iter()
        .chain(self.manifest_digests.iter())
        .chain(self.payload_digests.iter())
        {
            let digest: Digest32 = pin.parse()?;
            if digest.is_zero() || digest.to_string() != *pin {
                return Err("whole registered binding nonzero canonical digest".into());
            }
        }
        let mut bytes =
            b"hepta.intelligence-eval.registered-operational-model-binding.v3\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(self)?);
        Ok(Digest32::of_bytes(&bytes))
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OwnerSources {
    pub root: PathBuf,
    pub trust: Source,
    pub withdrawals: Source,
    pub withdrawal_binding: String,
    pub withdrawal_scope: String,
    pub withdrawal_head: String,
    pub withdrawal_records: usize,
    pub withdrawal_encoded_bytes: usize,
}
impl OwnerSources {
    fn open(&self, now: u64) -> HostResult<ReadOnlyArtifactCurrentOwnerV1> {
        self.trust.read(MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1 as u64)?;
        self.withdrawals.read(8 * 1024 * 1024)?;
        Ok(ReadOnlyArtifactCurrentOwnerV1::from_protected_sources(
            &ArtifactReadOnlyOwnerSourcesV1 {
                root: self.root.clone(),
                trust_path: self.trust.path.clone(),
                trust_digest: self.trust.digest.parse()?,
                withdrawal_path: self.withdrawals.path.clone(),
                withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1 {
                    binding: self.withdrawal_binding.parse()?,
                    scope_digest: self.withdrawal_scope.parse()?,
                    head_digest: self.withdrawal_head.parse()?,
                    file_digest: self.withdrawals.digest.parse()?,
                    records: self.withdrawal_records,
                    encoded_bytes: self.withdrawal_encoded_bytes,
                },
            },
            now,
        )?)
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ManifestSource {
    pub source: Source,
    pub admission_digest: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Registration {
    pub subject: String,
    pub owner: OwnerSources,
    pub manifests: [ManifestSource; 3],
    pub predecessor_id: Option<String>,
    pub predecessor_manifest_digest: Option<String>,
    pub publication_operation_id: String,
}

pub struct RegisteredArtifactCurrentFactsV3 {
    artifact_root: PathBuf,
    owner: ReadOnlyArtifactCurrentOwnerV1,
    view: VerifiedCurrentRegistryViewV1,
    head: SignedCurrentArtifactHeadV1,
    acknowledgement: ArtifactOwnerPublicationCheckpointV1,
    manifests: [ValidatedArtifactManifestV2; 3],
    predecessor: Option<StableId>,
    predecessor_manifest_digest: Option<Digest32>,
    expiry: u64,
    sources: Vec<(Source, u64)>,
    operational_binding: Option<RegisteredOperationalModelBindingV3>,
}
impl RegisteredArtifactCurrentFactsV3 {
    /// The complete successor tuple derived by the same authenticated CURRENT
    /// inspection. Initial generation facts deliberately carry no V3 purpose.
    pub fn operational_binding(&self) -> Option<&RegisteredOperationalModelBindingV3> {
        self.operational_binding.as_ref()
    }
    pub fn artifact_root(&self) -> &Path {
        &self.artifact_root
    }
    pub fn current_head(&self) -> &SignedCurrentArtifactHeadV1 {
        &self.head
    }
    pub fn current_view(&self) -> &VerifiedCurrentRegistryViewV1 {
        &self.view
    }
    pub fn manifests(&self) -> &[ValidatedArtifactManifestV2; 3] {
        &self.manifests
    }
    pub fn acknowledgement(&self) -> &ArtifactOwnerPublicationCheckpointV1 {
        &self.acknowledgement
    }
    pub fn expires_at(&self) -> u64 {
        self.expiry
    }
    pub fn revalidate_current(&self, now: u64) -> HostResult<()> {
        for (source, limit) in &self.sources {
            source.read(*limit)?;
        }
        if now >= self.expiry
            || self.owner.protected_current_head(now)? != self.head
            || self.owner.current_registry_view(now)?.receipt() != self.view.receipt()
            || self
                .owner
                .acknowledged_publication(&self.acknowledgement.operation_id, &self.head, now)?
                .as_ref()
                != Some(&self.acknowledgement)
        {
            return Err("original complete CURRENT material facts changed/expired".into());
        }
        Ok(())
    }
    /// Transfer only the original read-only artifact owner. Execution, selection,
    /// physical stores and each Goal retain their original separate admission.
    pub fn into_read_only_owner(self) -> ReadOnlyArtifactCurrentOwnerV1 {
        self.owner
    }
}

/// Authenticate whole CURRENT and all three full manifests from one protected
/// bounded configuration against independently supplied material and subject.
/// This reads no signing key, creates no writer/worker, and executes no tick.
pub fn inspect_registered_artifact_current_material_v3(
    path: &Path,
    pin: Digest32,
    plan: &NeuronGenerationMaterialV2,
    subject: &StableId,
    now: u64,
) -> HostResult<RegisteredArtifactCurrentFactsV3> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let registration: Registration = serde_json::from_slice(&bytes)?;
    let mut facts = inspect_current_material(&registration, plan, subject, now)?;
    facts.sources.push((source.clone(), 64 * 1024));
    if source.read(64 * 1024)? != bytes {
        return Err("whole protected current material configuration changed".into());
    }
    facts.revalidate_current(now)?;
    Ok(facts)
}
fn inspect_current_material(
    registration: &Registration,
    plan: &NeuronGenerationMaterialV2,
    subject: &StableId,
    now: u64,
) -> HostResult<RegisteredArtifactCurrentFactsV3> {
    validate_neuron_generation_material_v2(plan)?;
    if registration.subject != subject.as_str()
        || NeuronTickInputV1::journal_scope_for_subject(subject, plan.scope.objective_digest)?
            != plan.scope
    {
        return Err("registered actual enrolled subject/runtime scope mismatch".into());
    }
    let owner = registration.owner.open(now)?;
    let view = owner.current_registry_view(now)?;
    let head = owner.protected_current_head(now)?;
    let operation = StableId::new(registration.publication_operation_id.clone())?;
    let acknowledgement = owner
        .acknowledged_publication(&operation, &head, now)?
        .ok_or("registered CURRENT has no complete original publication ACK")?;
    if acknowledgement.registry_receipt != Some(view.receipt()) {
        return Err("registered whole current/ACK mismatch".into());
    }
    let predecessor = registration
        .predecessor_id
        .as_ref()
        .map(|id| StableId::new(id.clone()))
        .transpose()?;
    let predecessor_manifest_digest = registration
        .predecessor_manifest_digest
        .as_ref()
        .map(|pin| pin.parse::<Digest32>())
        .transpose()?;
    match (&predecessor, predecessor_manifest_digest) {
        (None, None) if plan.runtime.generation.get() == 1 => (),
        (Some(id), Some(pin)) if plan.runtime.generation.get() > 1 => {
            let old = view
                .registered_manifest(id)
                .ok_or("registered runtime predecessor missing")?;
            if old.kind != ArtifactKind::Model
                || old.generation.next()? != plan.runtime.generation
                || old.support_digest != pin
            {
                return Err("actual registered selected predecessor tuple".into());
            }
        }
        _ => return Err("complete exact initial/successor predecessor facts".into()),
    }
    let profile = plan.runtime.execution_profile_digest_v1()?;
    let expected = [
        (ArtifactKind::Model, plan.runtime.weights_digest),
        (
            ArtifactKind::Policy,
            plan.runtime.calibration.calibration_artifact_digest,
        ),
        (
            ArtifactKind::Policy,
            plan.runtime.calibration.ood_artifact_digest,
        ),
    ];
    let mut manifests: Vec<ValidatedArtifactManifestV2> = Vec::new();
    let mut expiry = head.witness.expires_at;
    for (source, (kind, payload)) in registration.manifests.iter().zip(expected) {
        source.source.read(128 * 1024)?;
        let admission = read_artifact_admission_by_digest(
            codex_hepta_learning_ledger::open_root_review_input(&source.source.path)?,
            source.admission_digest.parse()?,
        )?;
        let full = validate_artifact_manifest_v2(admission.validated_manifest.manifest, now)?;
        let manifest = &full.manifest;
        let current = view
            .eligible_manifest(&manifest.artifact_id)
            .ok_or("registered three-artifact CURRENT eligibility")?;
        if admission.withdrawal_scope_digest != head.withdrawal_scope_digest
            || manifest.kind != kind
            || manifest.generation != plan.runtime.generation
            || manifest.bytes_digest != payload
            || manifest.runtime_tuple_digest != profile
            || manifest.compatibility_digest != profile
            || manifest.device_profile_digest != plan.runtime.device_digest
            || manifest.normalization_digest != plan.runtime.normalization_digest
            || manifest.objective_class_digest != plan.scope.objective_digest
            || current.kind != kind
            || current.generation != manifest.generation
            || current.content_digest != payload
            || current.encoded_size_bytes != manifest.encoded_size_bytes
            || current.support_digest != full.manifest_digest
            || current.compatibility_digest != profile
            || current.objective_digest != manifest.objective_class_digest
            || current.producer_id != manifest.producer_id
            || current.predecessor_id.as_ref() != manifest.predecessor_ids.first()
            || manifest.predecessor_ids.len() != usize::from(predecessor.is_some())
            || manifests
                .iter()
                .any(|m| m.manifest.artifact_id == manifest.artifact_id)
            || manifest
                .source_dataset_digests
                .iter()
                .any(|dataset| !view.supports_dataset(current, *dataset))
        {
            return Err(
                "full independently current registered manifest/runtime/source tuple".into(),
            );
        }
        if kind == ArtifactKind::Model
            && (manifest.predecessor_ids.first() != predecessor.as_ref()
                || !manifest
                    .lineage_digests
                    .contains(&plan.runtime.model_manifest_digest))
        {
            return Err("actual model predecessor/whole model source".into());
        }
        source.source.read(128 * 1024)?;
        expiry = expiry.min(manifest.expires_at);
        manifests.push(full);
    }
    if owner.protected_current_head(now)? != head
        || owner.current_registry_view(now)?.receipt() != view.receipt()
    {
        return Err("registered original CURRENT changed during inspection".into());
    }
    let mut facts = RegisteredArtifactCurrentFactsV3 {
        operational_binding: None,
        artifact_root: registration.owner.root.clone(),
        owner,
        view,
        head,
        acknowledgement,
        manifests: manifests
            .try_into()
            .map_err(|_| "whole three registered manifests")?,
        predecessor,
        predecessor_manifest_digest,
        expiry,
        sources: std::iter::once((
            registration.owner.trust.clone(),
            MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1 as u64,
        ))
        .chain(std::iter::once((
            registration.owner.withdrawals.clone(),
            8 * 1024 * 1024,
        )))
        .chain(
            registration
                .manifests
                .iter()
                .map(|m| (m.source.clone(), 128 * 1024)),
        )
        .collect(),
    };
    if plan.runtime.generation.get() >= 2 {
        facts.operational_binding = Some(registered_binding(registration, plan, &facts)?);
    }
    Ok(facts)
}

pub(super) fn inspect_registration(
    registration: &Registration,
    plan: &NeuronGenerationMaterialV2,
    now: u64,
) -> HostResult<(RegisteredOperationalModelBindingV3, u64)> {
    let subject = StableId::new(registration.subject.clone())?;
    let facts = inspect_current_material(registration, plan, &subject, now)?;
    let binding = facts
        .operational_binding
        .clone()
        .ok_or("registered successor cannot reinterpret initial generation")?;
    Ok((binding, facts.expiry))
}

fn registered_binding(
    registration: &Registration,
    plan: &NeuronGenerationMaterialV2,
    facts: &RegisteredArtifactCurrentFactsV3,
) -> HostResult<RegisteredOperationalModelBindingV3> {
    let predecessor = facts
        .predecessor
        .as_ref()
        .ok_or("whole actual successor predecessor")?;
    let old_manifest = facts
        .predecessor_manifest_digest
        .ok_or("whole predecessor manifest source")?;
    let binding = RegisteredOperationalModelBindingV3 {
        purpose: "registered-successor-cpu-abstention-only.v3".into(),
        subject: registration.subject.clone(),
        model_generation: plan.runtime.generation.get(),
        material_digest: Digest32::of_bytes(&encode_neuron_generation_material_v2(plan)?)
            .to_string(),
        runtime_digest: plan.runtime.semantic_digest()?.to_string(),
        native_digest: plan.native.digest()?.to_string(),
        body_digest: plan.body.semantic_digest()?.to_string(),
        execution_profile_digest: plan.runtime.execution_profile_digest_v1()?.to_string(),
        input_profile_digest: input_profile_digest(plan)?.to_string(),
        objective_digest: plan.scope.objective_digest.to_string(),
        scope_digest: plan.scope.scope_digest.to_string(),
        model_artifact_id: facts.manifests[0].manifest.artifact_id.to_string(),
        predecessor_id: predecessor.to_string(),
        predecessor_manifest_digest: old_manifest.to_string(),
        manifest_digests: std::array::from_fn(|i| facts.manifests[i].manifest_digest.to_string()),
        payload_digests: std::array::from_fn(|i| {
            facts.manifests[i].manifest.bytes_digest.to_string()
        }),
        registry_binding: facts.view.receipt().binding.to_string(),
        registry_head: facts.view.receipt().head_digest.to_string(),
        current_witness: facts.view.witness_digest().to_string(),
        current_trust: facts.view.trust_digest().to_string(),
        withdrawal_scope: facts.head.withdrawal_scope_digest.to_string(),
        withdrawal_head: registration.owner.withdrawal_head.clone(),
        publication_operation_id: facts.acknowledgement.operation_id.to_string(),
        authority_epoch: facts.head.witness.authority_epoch,
    };
    binding.binding_digest()?;
    Ok(binding)
}
fn input_profile_digest(plan: &NeuronGenerationMaterialV2) -> HostResult<Digest32> {
    validate_neuron_generation_material_v2(plan)?;
    let mut bytes = b"hepta.neuron.registered-input-profile.v3\0".to_vec();
    for digest in [
        plan.runtime.encoder_digest,
        plan.runtime.tokenizer_digest,
        plan.runtime.preprocessor_digest,
        plan.runtime.quantization_digest,
        plan.runtime.normalization_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for dimension in [
        plan.runtime.input_feature_dimension,
        plan.runtime.state_width,
        plan.runtime.modulator_dimension,
    ] {
        bytes.extend_from_slice(&u64::try_from(dimension)?.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}
#[cfg(test)]
#[path = "operational_registered_model_v3_tests.rs"]
mod tests;
