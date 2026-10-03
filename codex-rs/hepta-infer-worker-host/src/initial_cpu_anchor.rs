//! Fixed initial operational admission, distinct from model improvement and
//! paired promotion. Root publication, independent selection and the installed
//! read-only consumer use the same complete protected CPU profile.
use codex_hepta_agent_components::intelligence_eval::VerifiedInitialOperationalEvidenceV1;
use codex_hepta_agent_components::intelligence_eval::inspect_initial_neuron_operational_evidence;
use codex_hepta_agent_components::learning_artifacts::*;
use codex_hepta_agent_components::learning_ledger::decode_review_payload_hex;
use codex_hepta_agent_components::learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;

type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
#[path = "initial_cpu_profile.rs"]
mod profile;
use profile::Profile;
use profile::Role;
use profile::Source;
#[path = "initial_cpu_evidence.rs"]
mod evidence;
use evidence::InitialEvidence;
#[path = "initial_cpu_current.rs"]
mod current;
#[path = "initial_cpu_goal.rs"]
mod goal;
#[path = "initial_cpu_goal_checkpoint.rs"]
mod goal_checkpoint;
#[path = "initial_cpu_goal_ingress.rs"]
mod goal_ingress;
pub async fn initialize_initial_cpu_authbus_checkpoint(
    path: &Path,
    pin: Digest32,
) -> HostResult<Value> {
    goal_checkpoint::initialize(path, pin).await
}
pub fn sign_initial_cpu_objective(path: &Path, pin: Digest32) -> HostResult<Value> {
    goal_ingress::sign(path, pin)
}
pub async fn deliver_initial_cpu_objective(path: &Path, pin: Digest32) -> HostResult<Value> {
    goal_ingress::deliver(path, pin).await
}
pub async fn inspect_initial_cpu_objective(path: &Path, pin: Digest32) -> HostResult<Value> {
    goal_ingress::inspect(path, pin).await
}
#[path = "initial_cpu_installed_plan.rs"]
mod installed_plan;
pub use installed_plan::InstalledCpuSourceV1;
#[path = "initial_cpu_installed.rs"]
mod installed;
#[path = "initial_cpu_tick.rs"]
mod tick;
pub(crate) use installed::Composition as InstalledCpuComposition;

#[path = "initial_cpu_goal_factory_v3.rs"]
mod goal_factory;
#[path = "initial_cpu_iteration_observation.rs"]
mod iteration_observation;
#[path = "initial_cpu_iteration_selection.rs"]
mod iteration_selection;
#[path = "initial_cpu_model_use_v2.rs"]
mod model_use;
#[path = "initial_cpu_model_use_binding_v2.rs"]
mod model_use_binding;
#[path = "initial_cpu_model_use_body_v2.rs"]
mod model_use_body;
#[path = "initial_cpu_model_use_current_v2.rs"]
mod model_use_current;
#[path = "initial_cpu_model_use_preview_v2.rs"]
mod model_use_preview;
#[path = "initial_cpu_model_use_program_v2.rs"]
mod model_use_program;
#[path = "initial_cpu_publication.rs"]
mod publication;
#[path = "initial_cpu_renewal.rs"]
mod renewal;
#[path = "initial_cpu_role.rs"]
mod role;
#[path = "initial_cpu_selection.rs"]
mod selection;
pub fn select_cpu_self_iteration_stage(path: &Path, pin: Digest32) -> HostResult<Value> {
    iteration_selection::select(path, pin)
}
pub fn observe_cpu_self_iteration_canary(path: &Path, pin: Digest32) -> HostResult<Value> {
    iteration_observation::observe(path, pin)
}
pub use model_use::VerifiedCpuModelUseV2;
pub use model_use::inspect_cpu_model_use_v2;
pub use model_use::select_cpu_model_use_v2;
pub fn preview_operational_model_use_v2(path: &Path, pin: Digest32) -> HostResult<Value> {
    model_use_preview::preview(path, pin)
}
#[path = "initial_cpu_withdrawal.rs"]
mod withdrawal;
pub fn withdraw_initial_cpu_dataset(path: &Path, pin: Digest32) -> HostResult<Value> {
    withdrawal::run(path, pin)
}
pub fn inspect_initial_cpu_withdrawal(path: &Path, pin: Digest32) -> HostResult<Value> {
    withdrawal::inspect(path, pin)
}
#[path = "initial_cpu_state.rs"]
mod state;
pub use current::open_current_cpu_neuron;
pub use current::open_current_cpu_neuron_v2;
pub fn describe_current_cpu_operational(path: &Path, pin: Digest32) -> HostResult<Value> {
    current::describe_current_operational(path, pin)
}
pub fn prepare_initial_cpu_objective_source(path: &Path, pin: Digest32) -> HostResult<Value> {
    goal::prepare(path, pin)
}
pub fn preview_initial_cpu_objective(path: &Path, pin: Digest32) -> HostResult<Value> {
    goal::preview(path, pin)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema: String,
    profile: Source,
    evaluation_config: Source,
    independent_report: Source,
    #[serde(default)]
    renewal: Option<renewal::Renewal>,
    #[serde(default)]
    first_installation_successor: Option<renewal::Renewal>,
    #[serde(default)]
    model_use_continuation: Option<evidence::ModelUseContinuation>,
}
struct Inputs {
    descriptor: Source,
    descriptor_bytes: Vec<u8>,
    profile_source: Source,
    profile: Profile,
    evidence: InitialEvidence,
    runtime: codex_hepta_neuron::NeuronRuntimeConfigV1,
    native: codex_hepta_neuron::SparseConfig,
    artifacts: [LearningArtifactManifestV2; 3],
    payloads: [Vec<u8>; 3],
    renewal: Option<renewal::VerifiedRenewal>,
    first_installation_successor: bool,
}
impl Inputs {
    fn read(path: &Path, pin: Digest32) -> HostResult<Self> {
        let descriptor = Source {
            path: path.to_owned(),
            digest: pin.to_string(),
        };
        let descriptor_bytes = descriptor.read(32 * 1024)?;
        let deployment: Deployment = serde_json::from_slice(&descriptor_bytes)?;
        let first_installation_successor = deployment.first_installation_successor.is_some();
        let model_use_continuation = deployment.model_use_continuation.is_some();
        if !matches!(
            (
                deployment.schema.as_str(),
                deployment.renewal.is_some(),
                first_installation_successor,
                model_use_continuation
            ),
            (
                "hepta.cpu-neuron.initial-product-current-inputs.v1",
                false,
                false,
                false
            ) | (
                "hepta.cpu-neuron.renewed-product-current-inputs.v1",
                true,
                false,
                false
            ) | (
                "hepta.cpu-neuron.first-installed-profile-current-inputs.v1",
                false,
                true,
                false
            ) | (
                "hepta.cpu-neuron.continued-installed-model-current-inputs.v2",
                true,
                false,
                true
            )
        ) {
            return Err("initial deployment schema".into());
        }
        let profile: Profile = serde_json::from_slice(&deployment.profile.read(64 * 1024)?)?;
        let now = now_ms()?;
        profile.validate(now)?;
        let renewal = deployment
            .renewal
            .map(|renewal| renewal.verify(&profile, &deployment.profile))
            .transpose()?
            .or(deployment
                .first_installation_successor
                .map(|history| {
                    history.verify_first_installation_successor(&profile, &deployment.profile)
                })
                .transpose()?);
        let evidence = InitialEvidence::read(
            deployment.model_use_continuation,
            &deployment.evaluation_config,
            &deployment.independent_report,
            &profile,
            &deployment.profile,
        )?;
        let (runtime, native) = profile.runtime(&evidence)?;
        let selector_key = Digest32::of_bytes(&public(&profile.selector.public_key_hex)?);
        let evaluator = evidence.evaluator().principal();
        if u64::from(profile.selector.uid)
            == evidence.current_measurements()["evaluator_uid"]
                .as_u64()
                .ok_or("actual independent E uid")?
            || u64::from(profile.selector.gid)
                == evidence.current_measurements()["evaluator_gid"]
                    .as_u64()
                    .ok_or("actual independent E gid")?
            || profile.selector.id == evaluator.principal_id.as_str()
            || selector_key == evaluator.signing_key_digest
            || digest(&profile.selector.credential_digest)? == evaluator.credential_chain_digest
        {
            return Err("independent selector collides with actual evaluator".into());
        }
        let gates = &evidence.measurements()["initial_product_gates"];
        let c = &profile.calibration;
        for (field, expected) in [
            (
                "zero_confidence_error_q24",
                u64::try_from(c.zero_confidence_error_q24)?,
            ),
            (
                "maximum_in_domain_error_q24",
                u64::try_from(c.maximum_in_domain_error_q24)?,
            ),
            (
                "minimum_confidence_ppm",
                u64::from(c.minimum_confidence_ppm),
            ),
            ("maximum_ood_ppm", u64::from(c.maximum_ood_ppm)),
            ("maximum_ece_ppm", u64::from(c.maximum_ece_ppm)),
            (
                "maximum_false_acceptance_ppm",
                u64::from(c.maximum_false_acceptance_ppm),
            ),
        ] {
            if gates[field].as_u64() != Some(expected) {
                return Err("runtime changed independent frozen confidence/OOD gates".into());
            }
        }
        if gates["maximum_p99_latency_micros"].as_u64()
            != Some(profile.resources.p99_latency_micros)
            || gates["maximum_transient_allocation_bytes"].as_u64()
                != Some(profile.resources.transient_allocation_bytes)
        {
            return Err("runtime changed frozen resource upper bounds".into());
        }
        let payloads = [
            profile.weights.read(16 * 1024 * 1024)?,
            runtime.calibration_evidence_payload_v1()?,
            runtime.ood_evidence_payload_v1()?,
        ];
        let profile_digest = runtime.execution_profile_digest_v1()?;
        let training_code_digest = Digest32::of_bytes(&profile.training_code.read(1024 * 1024)?);
        let created = evidence.current_measurements()["measured_at_ms"]
            .as_u64()
            .ok_or("actual independent measurement instant")?;
        let expires = evidence.expires_at().min(profile.expires_at_ms);
        let artifact_ids = [
            id(&profile.artifact_ids[0])?,
            id(&profile.artifact_ids[1])?,
            id(&profile.artifact_ids[2])?,
        ];
        let datasets = [
            "source_training_digest",
            "calibration_dataset_digest",
            "ood_dataset_digest",
        ]
        .map(|field| {
            evidence.measurements()[field]
                .as_str()
                .ok_or("original independent dataset digest")
                .and_then(|value| digest(value).map_err(|_| "dataset digest"))
        });
        let datasets = [datasets[0]?, datasets[1]?, datasets[2]?];
        let mut lineage = vec![
            evidence.authentication_digest(),
            evidence.model_manifest_digest(),
            digest(&deployment.profile.digest)?,
        ];
        evidence.extend_historical_lineage(&mut lineage)?;
        let producer = id(&profile.owner.id)?;
        let generation = Generation::new(1)?;
        let artifact_subject_digest = evidence.artifact_subject_digest()?;
        let artifacts = std::array::from_fn(|index| LearningArtifactManifestV2 {
            artifact_id: artifact_ids[index].clone(),
            kind: if index == 0 {
                ArtifactKind::Model
            } else {
                ArtifactKind::Policy
            },
            generation,
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![datasets[index]],
            lineage_digests: lineage.clone(),
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: Digest32::of_bytes(&payloads[index]),
            encoded_size_bytes: payloads[index].len() as u64,
            training_code_digest,
            runtime_tuple_digest: profile_digest,
            device_profile_digest: runtime.device_digest,
            objective_class_digest: artifact_subject_digest,
            compatibility_digest: profile_digest,
            schema_profile_digest: Digest32::of_bytes(
                b"hepta.cpu-neuron.initial-operational-artifact.v1",
            ),
            normalization_digest: runtime.normalization_digest,
            producer_id: producer.clone(),
            created_at: created,
            expires_at: expires,
        });
        for manifest in &artifacts {
            validate_artifact_manifest_v2(manifest.clone(), now)?;
        }
        let inputs = Self {
            descriptor,
            descriptor_bytes,
            profile_source: deployment.profile,
            profile,
            evidence,
            runtime,
            native,
            artifacts,
            payloads,
            renewal,
            first_installation_successor,
        };
        if let Some((lease, body_implementation)) = inputs.evidence.current_model_use() {
            model_use_binding::verify(&inputs, lease, body_implementation)?;
        }
        inputs.revalidate()?;
        Ok(inputs)
    }
    fn revalidate(&self) -> HostResult<()> {
        self.profile.validate(now_ms()?)?;
        if self.profile.first_physical_installation.is_some() {
            renewal::verify_first_installation(&self.profile)?;
        }
        self.evidence.revalidate_current()?;
        if let Some((lease, body_implementation)) = self.evidence.current_model_use() {
            model_use_binding::verify(self, lease, body_implementation)?;
        }
        if self.descriptor.read(32 * 1024)? != self.descriptor_bytes {
            return Err("current deployment changed".into());
        }
        self.profile_source.read(64 * 1024)?;
        if let Some(renewal) = &self.renewal {
            renewal.revalidate()?;
        }
        Ok(())
    }
    fn storage_binding(&self) -> Digest32 {
        let profile = self
            .renewal
            .as_ref()
            .map(|renewal| &renewal.original_profile.digest)
            .unwrap_or(&self.profile_source.digest);
        Digest32::of_bytes(
            format!(
                "hepta.cpu-neuron.initial-owner.storage.v1:{}:{profile}",
                self.profile.registry_id
            )
            .as_bytes(),
        )
    }
    fn physical_profile_source(&self) -> &Source {
        self.evidence.physical_profile_source(&self.profile_source)
    }
    fn trust(&self) -> HostResult<ArtifactOwnerTrustV1> {
        self.profile.trust_from(
            self.renewal
                .as_ref()
                .map(|renewal| renewal.historical_start)
                .unwrap_or(self.profile.frozen_at_ms),
        )
    }
    fn selector_verifier(&self) -> HostResult<ArtifactSelectionVerifierV1> {
        self.profile
            .selector_verifier_with_owner_trust(&self.trust()?)
    }
    fn current(&self) -> HostResult<ReadOnlyArtifactCurrentOwnerV1> {
        Ok(ReadOnlyArtifactCurrentOwnerV1::open(
            &self.profile.owner_root,
            self.trust()?,
            self.profile.withdrawals()?,
            now_ms()?,
        )?)
    }
}

fn now_ms() -> HostResult<u64> {
    Ok(u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?)
}
fn digest(value: &str) -> HostResult<Digest32> {
    let digest = value.parse::<Digest32>()?;
    if digest.is_zero() {
        return Err("nonzero original digest required".into());
    }
    Ok(digest)
}
fn id(value: &str) -> HostResult<StableId> {
    Ok(StableId::new(value)?)
}
fn public(value: &str) -> HostResult<[u8; 32]> {
    Ok(decode_review_payload_hex(value)?
        .try_into()
        .map_err(|_| "Ed25519 public key width")?)
}

pub fn publish_initial_cpu_anchor(path: &Path, pin: Digest32) -> HostResult<Value> {
    let inputs = Inputs::read(path, pin)?;
    if inputs.renewal.is_some() {
        return Err("initial publication cannot renew an installed history".into());
    }
    publication::publish(inputs)
}
pub fn select_initial_cpu_anchor(path: &Path, pin: Digest32) -> HostResult<Value> {
    let inputs = Inputs::read(path, pin)?;
    if inputs.renewal.is_some() {
        return Err("initial selection cannot renew an installed history".into());
    }
    selection::select(inputs)
}

pub fn publish_renewed_cpu_operational(path: &Path, pin: Digest32) -> HostResult<Value> {
    let inputs = Inputs::read(path, pin)?;
    if inputs.renewal.is_none()
        || inputs.first_installation_successor
        || inputs.evidence.operational_lease().is_some()
    {
        return Err("renewal requires original protected history and new evidence".into());
    }
    publication::publish(inputs)
}
pub fn select_renewed_cpu_operational(path: &Path, pin: Digest32) -> HostResult<Value> {
    let inputs = Inputs::read(path, pin)?;
    if inputs.renewal.is_none()
        || inputs.first_installation_successor
        || inputs.evidence.operational_lease().is_some()
    {
        return Err("renewal selection requires original protected history".into());
    }
    selection::select(inputs)
}

pub fn publish_installed_model_use_continuation_v2(
    path: &Path,
    pin: Digest32,
) -> HostResult<Value> {
    let inputs = Inputs::read(path, pin)?;
    if inputs.renewal.is_none()
        || inputs.first_installation_successor
        || inputs.evidence.operational_lease().is_none()
    {
        return Err(
            "model-use continuation requires historical installation and current E2".into(),
        );
    }
    publication::publish(inputs)
}

pub fn publish_first_installed_cpu_profile(path: &Path, pin: Digest32) -> HostResult<Value> {
    let inputs = Inputs::read(path, pin)?;
    if !inputs.first_installation_successor {
        return Err("first physical installation requires its explicit Root/E/S domain".into());
    }
    publication::publish(inputs)
}

pub fn select_first_installed_cpu_profile(path: &Path, pin: Digest32) -> HostResult<Value> {
    let inputs = Inputs::read(path, pin)?;
    if !inputs.first_installation_successor {
        return Err("first physical installation selection requires its explicit domain".into());
    }
    selection::select(inputs)
}

/// Protected input locations supplied by the installed product compiler. Paths
/// and checksums grant no admission; all three actors and CURRENT are verified.
pub struct InitialCpuAdmissionSourcesV1 {
    pub deployment: std::path::PathBuf,
    pub deployment_pin: Digest32,
    pub selections: std::path::PathBuf,
    pub selection_pin: Digest32,
}

/// The product compiler supplies actual body/store contexts, physical resource
/// grant and clock. Exact Root/E/S/CURRENT inputs alone construct the admission.
pub fn open_initial_cpu_neuron(
    sources: InitialCpuAdmissionSourcesV1,
    plan: crate::CpuNeuronGenerationPlanV1,
    mode: crate::CpuNeuronGenerationOpenModeV1,
    control: std::sync::Arc<
        std::sync::Mutex<codex_hepta_infer_core::durable_control::DurableInferenceControl>,
    >,
    clock: std::sync::Arc<dyn codex_hepta_contracts::AuthorityClock>,
    worker: crate::CpuNeuronControlConfigV1,
) -> HostResult<codex_hepta_agentd::AgentdNeuronHandleV2> {
    let inputs = Inputs::read(&sources.deployment, sources.deployment_pin)?;
    if plan.runtime != inputs.runtime
        || plan.native != inputs.native
        || plan.model_manifest != inputs.profile.model.path
        || plan.model_manifest_digest != inputs.evidence.model_manifest_digest()
        || plan.scope.objective_digest != inputs.evidence.objective_digest()
    {
        return Err(
            "actual installed CPU generation plan differs from frozen original profile".into(),
        );
    }
    let selected = Source {
        path: sources.selections,
        digest: sources.selection_pin.to_string(),
    };
    let admission = selection::admission(&inputs, &selected, clock.clone())?;
    let handle = crate::open_installed_cpu_neuron_generation_v1(
        plan, mode, control, clock, worker, admission,
    )?;
    inputs.revalidate()?;
    selected.read(16 * 1024)?;
    Ok(handle)
}
