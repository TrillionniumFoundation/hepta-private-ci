//! Root-local coordinator mechanism fixtures. The CURRENT consumed by the
//! coordinator comes from the public RootAuthorityDirectory factory, never
//! FileCas/from_parts. The existing Artifact/FinalUse fixture also owns an unused
//! test CURRENT; this module never supplies it to the coordinator. FinalUse and
//! AuthBus retain the original explicit engineering issuers, not real deployment
//! authority or useful task evidence.

use super::*;
use std::collections::BTreeMap;
use std::os::unix::fs::PermissionsExt as _;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::SignedFinalUseGrant;
use crate::OriginalRootCircuitTaskInputsV1;
use crate::OriginalRootCircuitTaskRuntimeV1;
use crate::OriginalRootInitialGenerationCustodyV1;
use crate::OriginalRootInitialInstallationErrorV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;
use crate::neuron_generation_initial::prepare_agentd_generation_initial_v1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;

const OPERATION: &str = "root-local-original-initial-publication";
type Custody = OriginalRootInitialGenerationCustodyV1<FileAnchorWitnessStore>;
type Installed = OriginalRootCircuitTaskRuntimeV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

struct RootFixture {
    root: Arc<RootAuthorityDirectory>,
    root_directory: tempfile::TempDir,
    // This existing fixture supplies only actual Artifact/FinalUse owners,
    // selection, target files and its original test issuer. Its test CURRENT
    // field is never passed into prepare, publication, factory or recovery.
    providers: VersionFixture,
    admission: Option<Admission>,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
    _model_directory: tempfile::TempDir,
}

impl RootFixture {
    async fn new(run: &str) -> anyhow::Result<Self> {
        anyhow::ensure!(unsafe { libc::getuid() } == 0 && unsafe { libc::geteuid() } == 0,
                        "this ignored case requires the actual Root process");
        // A writable /tmp ancestor is intentionally not accepted by the original
        // Root factory. There is no alternate UID, chown or test-store fallback.
        let root_directory = tempfile::Builder::new()
            .prefix("hepta-original-initial-custody-")
            .tempdir_in("/root")?;
        fs::set_permissions(root_directory.path(), fs::Permissions::from_mode(0o700))?;
        let root = RootAuthorityDirectory::open(root_directory.path())?;
        let model_directory = tempfile::tempdir()?;
        let (model, bundle, definition) = model(model_directory.path())?;
        let admission = admission(run).await?;
        let source = source(&admission, [Q, Q / 4])?;
        let generation = configuration(&model, &bundle, &definition, &source, 1)?;
        let providers = VersionFixture::new_initial(generation, OPERATION)?;
        Ok(Self { root, root_directory, providers, admission: Some(admission),
                  model, bundle, definition, source, _model_directory: model_directory })
    }

    fn prepare_original(&self) -> anyhow::Result<PreparedAgentdGenerationInitialV1<FileAnchorWitnessStore>> {
        Ok(prepare_agentd_generation_initial_v1(
            Arc::clone(&self.root),
            self.providers.authorities()?,
            self.providers.selection()?,
            self.providers.target_create()?,
            AgentdGenerationUpdateRequestV1 { operation_id: OPERATION.into() },
        )?)
    }

    fn custody(&self) -> anyhow::Result<Custody> {
        Ok(Custody::from_original_prepared(self.prepare_original()?, OPERATION.into())?)
    }

    fn sign(&self, custody: &Custody) -> anyhow::Result<SignedFinalUseGrant> {
        self.providers.sign(custody.original_final_use_binding())
    }

    fn root_bytes(&self) -> anyhow::Result<BTreeMap<String, Vec<u8>>> {
        let mut bytes = BTreeMap::new();
        for entry in fs::read_dir(self.root_directory.path())? {
            let entry = entry?;
            anyhow::ensure!(entry.file_type()?.is_file(), "unexpected authority child entry");
            bytes.insert(entry.file_name().into_string()
                .map_err(|_| anyhow::anyhow!("non-UTF8 authority test file"))?, fs::read(entry.path())?);
        }
        Ok(bytes)
    }

    fn generation_bytes(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([self.providers.bytes("target-journal")?, self.providers.bytes("target-witness")?])
    }

    fn take_task_inputs(&mut self, queue_capacity: usize) -> anyhow::Result<(
        AgentdConfig,
        OriginalRootCircuitTaskInputsV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        RuntimeFixture,
        AuthBusObjectiveIngress,
    )> {
        let Admission { runtime, config, mut request } = self.admission.take()
            .ok_or_else(|| anyhow::anyhow!("the original Admission was already consumed"))?;
        // This is the unchanged original fixture issuer and complete body
        // binding used by super::start, before the real signed ingress below.
        request.body.runtime_body_digest = self.definition.runtime.runtime_digest.to_string();
        request.body.model_tuple_digest = self.definition.semantic_digest()?.to_string();
        request.body.artifact_set_digest = self.bundle.digest()?.to_string();
        request.signature_hex = SigningKey::from_bytes(&[91; 32])
            .sign(&crate::authbus_objective_claims(&runtime.identity, &request)?.signing_bytes())
            .to_bytes().iter().map(|byte| format!("{byte:02x}")).collect();
        let file = |name| OpenOptions::new().read(true).write(true).create(true)
            .truncate(false).open(runtime.identity.home_root.join(name));
        let witness = |name, label: &str| FileAnchorWitnessStore::open(
            file(name)?,
            JournalScope { scope_digest: cell::d(label), objective_digest: self.source.objective_digest },
            Generation::new(1).expect("original constant generation"),
            64,
        );
        let (mut circuit, mut bindings) = super::super::super::configuration();
        bindings[0].cell = self.definition.clone();
        circuit.parameter_bundle_digest = Sha256Digest::parse(self.bundle.digest()?.to_string())
            .map_err(anyhow::Error::msg)?;
        circuit.route_policy_digest = crate::circuit_cell_route_policy_digest_v1(&bindings)?;
        circuit.limits.work_budget = 20_000_000;
        circuit.limits.max_elapsed_ms = 60_000;
        circuit.programs[0].nodes[0].kind = CircuitNodeKindV2::Decide { max_work: 10_000_000 };
        let epoch = Instant::now();
        let inputs = OriginalRootCircuitTaskInputsV1 {
            definition: self.definition.clone(), source: self.source.clone(),
            files: CircuitQ24TaskFilesV1 {
                source_journal: file("q24-source.journal")?,
                source_witness: witness("q24-source.witness", "original-source-owner")?,
                cell_journal: file("q24-cell.journal")?,
                cell_witness: witness("q24-cell.witness", "original-cell-owner")?,
                inference_control: DurableInferenceControl::open(
                    runtime.identity.home_root.join("q24-control.journal"), 4)?,
            },
            source_mode: CircuitQ24TaskOpenModeV1::Create,
            fence: TaskFlowFence::new(runtime.identity.agent_id.clone(), "ordinary-q24-owner", 1,
                                     runtime.state.current_generation()?, "ordinary-q24-fence")?,
            circuit, routes: bindings.remove(0).routes, bundle: self.bundle.clone(),
            model: Arc::clone(&self.model), worker_generation: 1, maximum_cell_records: 16,
            queue_capacity,
            clock: Arc::new(move || crate::CircuitCellTimeV1 {
                circuit_millis: crate::authbus_ingress::now_ms().expect("original live wall clock"),
                cell_micros: 10 + u64::try_from(epoch.elapsed().as_micros()).expect("original live Cell clock"),
            }),
        };
        let config = config
            .with_authbus_trust_file(runtime.identity.home_root.join("circuit-trust.json"))
            .with_authbus_checkpoint_file(runtime.identity.run_root.join("circuit-checkpoint.json"))
            .with_objective_profile_file(runtime.identity.home_root.join("circuit-profile.json"));
        Ok((config, inputs, runtime, request))
    }

    fn install(&mut self, custody: Custody, queue_capacity: usize) -> anyhow::Result<(
        Result<Installed, OriginalRootInitialInstallationErrorV1>, RuntimeFixture, AuthBusObjectiveIngress,
    )> {
        let (config, inputs, runtime, request) = self.take_task_inputs(queue_capacity)?;
        Ok((custody.into_q24_task(config, inputs), runtime, request))
    }

    async fn start(&mut self, custody: Custody) -> anyhow::Result<RootSession> {
        let (installed, runtime, request) = self.install(custody, 4)?;
        let mut installed = installed?;
        let (bootstrap, invocation) = installed.config.take_circuit_task_bootstrap()?
            .ok_or_else(|| anyhow::anyhow!("coordinator did not install the original task profile"))?;
        runtime.state.attach_automation_store(AutomationStore::open(&runtime.identity.layout).await?)?;
        anyhow::ensure!(runtime.state.circuit_task.set(bootstrap.handle()).is_ok(), "one original task handle");
        anyhow::ensure!(runtime.state.circuit_task_invocation.set(invocation).is_ok(), "one original Source invocation");
        let cancellation = CancellationToken::new();
        let worker = tokio::spawn(bootstrap.run(Arc::clone(&runtime.state), cancellation.clone()));
        Ok(RootSession { runtime, request, installed, cancellation, worker: Some(worker) })
    }
}

struct RootSession {
    runtime: RuntimeFixture,
    request: AuthBusObjectiveIngress,
    installed: Installed,
    cancellation: CancellationToken,
    worker: Option<tokio::task::JoinHandle<Result<(), crate::AgentdError>>>,
}

impl RootSession {
    async fn execute(&self) -> anyhow::Result<()> {
        let response = self.runtime.state.response(1, self.runtime.identity.spawn_generation,
            AgentdMethod::ObjectiveStart { request: self.request.clone() }).await?;
        let AgentdPayload::ObjectiveRun(admission) = response.payload else {
            anyhow::bail!("original signed ingress did not return ObjectiveRun");
        };
        anyhow::ensure!(admission.disposition == "circuit_succeeded",
                        "actual original Circuit did not complete: {}", admission.disposition);
        Ok(())
    }

    fn drain(&self) -> Result<PublishedCircuitFeatureCompletionV1, crate::AgentdError> {
        self.installed.custody.drain_completed_task()
    }

    async fn finish(mut self) -> anyhow::Result<()> {
        self.cancellation.cancel();
        if let Some(worker) = self.worker.take() {
            timeout(Duration::from_secs(5), worker).await???;
        }
        Ok(())
    }
}

impl Drop for RootSession {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

#[path = "neuron_generation_initial_root_custody_tests.rs"]
mod tests;

#[path = "neuron_generation_initial_root_cold_tests.rs"]
mod cold_tests;
