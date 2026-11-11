//! Real native files and normal ObjectiveStart plumbing. The AuthBus issuer,
//! calibration profile and CURRENT FileCAS are explicit engineering fixtures.

use std::fs::File;
use std::path::Path;
use std::time::Instant;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_types::Revision;

use super::*;
use crate::AgentdConfig;
use crate::CellQ24FeatureWorkerV1;
use crate::CellQ24GenerationWorkerV1;
use crate::CellQ24ModelFilesV1;
use crate::CircuitQ24TaskFilesV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitQ24TaskProfileV1;
use crate::CircuitTaskSourceInputV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::LoadedCellQ24ModelV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::neuron_generation_current::test_support::Fixture as VersionFixture;
use crate::neuron_generation_current::test_support::config as version_config;
use crate::neuron_generation_initial::PreparedAgentdGenerationInitialV1;

pub(super) const Q: i64 = 1 << 24;
pub(super) type Source = CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>;
pub(super) type Cell = PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>;

pub(super) struct Admission {
    pub runtime: RuntimeFixture,
    config: AgentdConfig,
    pub request: AuthBusObjectiveIngress,
}

pub(super) struct Session {
    pub runtime: RuntimeFixture,
    config: Option<AgentdConfig>,
    pub request: AuthBusObjectiveIngress,
    pub source: Arc<Source>,
    pub cell: Cell,
    pub retirement: PublishedCircuitFeatureTaskV1,
    #[cfg(target_os = "linux")]
    pub ledger: Option<Arc<crate::OriginalCellQ24TaskLedgerProducerV1>>,
    cancellation: CancellationToken,
    worker: Option<tokio::task::JoinHandle<Result<(), crate::AgentdError>>>,
}

impl Session {
    pub(super) fn take_configuration(&mut self) -> AgentdConfig {
        self.config
            .take()
            .expect("original configuration after bootstrap handoff")
    }

    pub async fn stop(&mut self) -> anyhow::Result<()> {
        self.cancellation.cancel();
        if let Some(worker) = self.worker.take() {
            timeout(Duration::from_secs(5), worker).await???;
        }
        Ok(())
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

pub(super) async fn admission(run: &str) -> anyhow::Result<Admission> {
    let runtime = runtime_fixture();
    let i = &runtime.identity;
    let config = AgentdConfig::load(
        i.fleet_root.clone(),
        i.agent_id.clone(),
        i.spawn_generation,
        i.home_root.clone(),
        i.run_root.clone(),
        i.home_root.clone(),
        i.workspace.clone(),
    )?;
    attach_runtime_prerequisites(&runtime).await;
    runtime.registry.compare_and_transition(
        &i.agent_id,
        i.spawn_generation,
        AgentLifecycle::Running,
    )?;
    runtime.state.refresh_generation()?;
    runtime.state.mark_app_server_ready()?;
    let request = signed_ingress_for_run(&runtime.state, run).await?;
    Ok(Admission {
        runtime,
        config,
        request,
    })
}

pub(super) fn source(
    admission: &Admission,
    values: [i64; 2],
) -> anyhow::Result<CircuitTaskSourceInputV1> {
    let source =
        decode_source_envelope_json_v1(admission.request.body.source_envelope_json.as_bytes())?;
    let profile = decode_admission_profile_json_v1(&fs::read(
        admission
            .runtime
            .identity
            .home_root
            .join("circuit-profile.json"),
    )?)?;
    // This deterministic preflight computes the exact prospective semantic
    // identity. The real signed ingress below must still authenticate and
    // publish the immutable RunStart; this preview grants no runtime authority.
    let context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(admission.request.body.objective_revision)?,
        now_unix_micros: crate::authbus_ingress::now_ms()? * 1_000,
        selected_profile_digest: profile.digest()?,
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: StableId::new(ISSUER)?,
            source_digest: source.structured_intent.provenance.source_digest,
        },
    };
    let compiled = admit_and_compile_objective_v1(&source, &profile, &context)?
        .compile_result
        .map_err(|conflict| anyhow::anyhow!("fixture objective conflict: {conflict:?}"))?;
    let mut observation = b"HQ24I001".to_vec();
    observation.extend_from_slice(&2_u16.to_le_bytes());
    for value in values {
        observation.extend_from_slice(&value.to_le_bytes());
    }
    Ok(CircuitTaskSourceInputV1 {
        scope: cell::scope(&admission.request.body.run_id),
        source_frontier: cell::d("original-q24-task-source"),
        objective_digest: compiled.objective.semantic_digest,
        ndu_snapshot_digest: cell::d("original-q24-ndu-snapshot"),
        monotonic_micros: 10,
        deadline_micros: 60_000_010,
        observation,
        candidates: cell::definition()
            .candidates
            .iter()
            .map(|candidate| CellCandidateMaskV1 {
                candidate_id: candidate.candidate_id.clone(),
                allowed: true,
            })
            .collect(),
        lease_duration_ms: 60_000,
    })
}

pub(super) fn model(
    root: &Path,
) -> anyhow::Result<(
    Arc<LoadedCellQ24ModelV1>,
    CellCompatibilityBundleV1,
    CellDefinitionV1,
)> {
    let matrix = |rows: u16, values: &[i64]| {
        let mut bytes = b"HQ24M001".to_vec();
        bytes.extend_from_slice(&rows.to_le_bytes());
        bytes.extend_from_slice(&2_u16.to_le_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes
    };
    let file = |name, bytes| -> anyhow::Result<File> {
        let path = root.join(name);
        fs::write(&path, bytes)?;
        Ok(File::open(path)?)
    };
    let model = Arc::new(LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: file("base", matrix(/*rows*/ 2, &[Q, 0, 0, Q]))?,
        encoder: file("encoder", matrix(/*rows*/ 2, &[Q, 0, 0, Q]))?,
        heads: file(
            "heads",
            matrix(
                /*rows*/ 10,
                &[Q, 0, 0, Q, 0, 0, 0, 0, 0, 0, Q, 0, 0, Q, 0, 0, 0, 0, 0, 0],
            ),
        )?,
        organ_adapter: None,
        cell_adapter: None,
    })?);
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: StableId::new("q24-ordinary-retained-model")?,
        generation: Generation::new(1)?,
        components: model.components().clone(),
        rollback_predecessor: None,
        training_lineage: None,
    };
    let definition = definition(&model, &bundle)?;
    Ok((model, bundle, definition))
}

pub(super) fn definition(
    model: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
) -> anyhow::Result<CellDefinitionV1> {
    let mut definition = cell::definition();
    let c = model.components();
    definition.bundle_digest = bundle.digest()?;
    definition.state_schema_digest = c.state_schema;
    definition.native.model_digest = c.heads;
    definition.native.normalization_digest = c.normalizer;
    definition.native.generation = bundle.generation;
    definition.candidates[1].kind = CellCandidateKindV1::Action;
    let r = &mut definition.runtime;
    r.generation = bundle.generation;
    r.model_id = bundle.artifact_id.clone();
    r.model_manifest_digest = bundle.digest()?;
    r.encoder_digest = c.encoder;
    r.head_digest = c.heads;
    r.weights_digest = model.effective_weights_digest();
    r.tokenizer_digest = c.tokenizer;
    r.preprocessor_digest = c.normalizer;
    r.normalization_digest = c.normalizer;
    r.quantization_digest = c.numeric_profile;
    r.runtime_digest = CellQ24FeatureWorkerV1::runtime_profile_digest();
    r.native_config_digest = definition.native.digest()?;
    r.calibration.generation = bundle.generation;
    r.resource_envelope.p99_latency_micros = 10_000_000;
    definition.max_queue_age_micros = 10_000_000;
    definition.semantic_digest()?;
    Ok(definition)
}

pub(super) fn configuration(
    model: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
    generation: u64,
) -> anyhow::Result<CellGenerationConfigV2> {
    let mut config = version_config()?;
    let m = &mut config.manifest;
    m.profile = CellQ24GenerationWorkerV1::PROFILE.into();
    m.bundle_digest = bundle.digest()?.into_array();
    m.encoder = Some(bundle.components.encoder.into_array());
    m.head = Some(bundle.components.heads.into_array());
    m.input_schema = CellQ24GenerationWorkerV1::input_schema_digest();
    m.state_schema = bundle.components.state_schema.into_array();
    m.output_schema = bundle.components.output_schema.into_array();
    m.runtime_digest = definition.runtime.runtime_digest.into_array();
    m.device_digest = definition.runtime.device_digest.into_array();
    m.learning = CellLearningBindingV2::Frozen {
        weights: model.effective_weights_digest().into_array(),
    };
    m.max_input_bytes = (10 + 8 * model.input_width()) as u32;
    m.max_state_bytes = 1;
    m.max_delta_bytes = (10 + 16 * model.output_width()) as u32;
    m.max_prefix_bytes = m.max_delta_bytes;
    config.initial.scope = CellGenerationScopeV2 {
        principal_digest: source.scope.principal_digest.into_array(),
        agent_id: source.scope.agent_id.to_string(),
        cell_id: source.scope.cell_id.to_string(),
        run_id: source.scope.run_id.to_string(),
    };
    config.initial.manifest_digest = m.digest()?;
    config.initial.generation = generation;
    config.initial.writer_epoch = generation;
    config.initial.state.clear();
    config.source_frontier = source.source_frontier.into_array();
    config.task_digest = crate::circuit_feature_task_digest_v1(definition, source)?.into_array();
    Ok(config)
}

pub(super) fn publish_initial(
    f: &VersionFixture,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
) -> anyhow::Result<PublishedCircuitFeatureTaskV1> {
    let target = f.target_create()?;
    let journal = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        f.current.clone(),
    )?;
    let prepared = PreparedAgentdGenerationInitialV1::from_parts(
        f.current.clone(),
        f.authorities()?,
        f.initial_prepared("ordinary-q24-initial")?,
        journal,
        f.selection()?,
    );
    let signed = f.sign(prepared.final_use_binding())?;
    Ok(prepared
        .publish(&signed)?
        .into_circuit_feature_task(definition, source)?)
}

pub(super) async fn start(
    admission: Admission,
    published_task: PublishedCircuitFeatureTaskV1,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
) -> anyhow::Result<Session> {
    start_profile(
        admission,
        published_task,
        model,
        bundle,
        LearningProfile::None,
    )
    .await
}

enum LearningProfile {
    None,
    #[cfg(target_os = "linux")]
    Original(crate::OriginalCellQ24TaskLedgerInputsV1),
}

#[cfg(target_os = "linux")]
pub(super) async fn start_learning(
    admission: Admission,
    published_task: PublishedCircuitFeatureTaskV1,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
    inputs: crate::OriginalCellQ24TaskLedgerInputsV1,
) -> anyhow::Result<Session> {
    start_profile(
        admission,
        published_task,
        model,
        bundle,
        LearningProfile::Original(inputs),
    )
    .await
}

async fn start_profile(
    admission: Admission,
    published_task: PublishedCircuitFeatureTaskV1,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
    learning: LearningProfile,
) -> anyhow::Result<Session> {
    let Admission {
        runtime,
        config,
        mut request,
    } = admission;
    let definition = published_task.definition().clone();
    let source = published_task.source().clone();
    let retirement = published_task.clone();
    // The explicit fixture issuer signs the actual complete Cell/runtime and
    // bundle identities before the normal ingress authenticates the request.
    request.body.runtime_body_digest = definition.runtime.runtime_digest.to_string();
    request.body.model_tuple_digest = definition.semantic_digest()?.to_string();
    request.body.artifact_set_digest = bundle.digest()?.to_string();
    request.signature_hex = SigningKey::from_bytes(&[91; 32])
        .sign(&crate::authbus_objective_claims(&runtime.identity, &request)?.signing_bytes())
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let file = |name| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(runtime.identity.home_root.join(name))
    };
    let witness = |name, label: &str| {
        FileAnchorWitnessStore::open(
            file(name)?,
            JournalScope {
                scope_digest: cell::d(label),
                objective_digest: source.objective_digest,
            },
            Generation::new(1).expect("generation"),
            /*max_records*/ 64,
        )
    };
    let (mut circuit, mut bindings) = super::super::configuration();
    bindings[0].cell = definition;
    circuit.parameter_bundle_digest =
        Sha256Digest::parse(bundle.digest()?.to_string()).map_err(anyhow::Error::msg)?;
    circuit.route_policy_digest = crate::circuit_cell_route_policy_digest_v1(&bindings)?;
    circuit.limits.work_budget = 20_000_000;
    circuit.limits.max_elapsed_ms = 60_000;
    circuit.programs[0].nodes[0].kind = CircuitNodeKindV2::Decide {
        max_work: 10_000_000,
    };
    let epoch = Instant::now();
    let profile = CircuitQ24TaskProfileV1 {
        files: CircuitQ24TaskFilesV1 {
            source_journal: file("q24-source.journal")?,
            source_witness: witness("q24-source.witness", "original-source-owner")?,
            cell_journal: file("q24-cell.journal")?,
            cell_witness: witness("q24-cell.witness", "original-cell-owner")?,
            inference_control: DurableInferenceControl::open(
                runtime.identity.home_root.join("q24-control.journal"),
                /*capacity*/ 4,
            )?,
        },
        source_mode: CircuitQ24TaskOpenModeV1::Create,
        published_task,
        fence: TaskFlowFence::new(
            runtime.identity.agent_id.clone(),
            "ordinary-q24-owner",
            /*owner_epoch*/ 1,
            runtime.state.current_generation()?,
            "ordinary-q24-fence",
        )?,
        circuit,
        routes: bindings.remove(0).routes,
        bundle,
        model,
        worker_generation: 1,
        maximum_cell_records: 16,
        queue_capacity: 4,
        clock: Arc::new(move || crate::CircuitCellTimeV1 {
            circuit_millis: crate::authbus_ingress::now_ms().expect("live wall clock"),
            cell_micros: 10 + u64::try_from(epoch.elapsed().as_micros()).expect("live Cell clock"),
        }),
    };
    let config = config
        .with_authbus_trust_file(runtime.identity.home_root.join("circuit-trust.json"))
        .with_authbus_checkpoint_file(runtime.identity.run_root.join("circuit-checkpoint.json"))
        .with_objective_profile_file(runtime.identity.home_root.join("circuit-profile.json"));
    #[cfg(target_os = "linux")]
    let mut ledger = None;
    let mut installed = match learning {
        LearningProfile::None => config.with_q24_circuit_task_profile(profile)?,
        #[cfg(target_os = "linux")]
        LearningProfile::Original(inputs) => {
            let installed = config.with_q24_learning_task_profile(profile, inputs)?;
            ledger = Some(installed.ledger);
            installed.task
        }
    };
    let (bootstrap, invocation) = installed
        .config
        .take_circuit_task_bootstrap()?
        .expect("installed ordinary profile");
    runtime
        .state
        .attach_automation_store(AutomationStore::open(&runtime.identity.layout).await?)?;
    assert!(runtime.state.circuit_task.set(bootstrap.handle()).is_ok());
    assert!(
        runtime
            .state
            .circuit_task_invocation
            .set(invocation)
            .is_ok()
    );
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(bootstrap.run(Arc::clone(&runtime.state), cancellation.clone()));
    Ok(Session {
        runtime,
        config: Some(installed.config),
        request,
        source: installed.source,
        cell: installed.cell,
        retirement,
        #[cfg(target_os = "linux")]
        ledger,
        cancellation,
        worker: Some(worker),
    })
}
