//! Consume an actual separate ordinary C admission, without creating RunStart.
use super::*;

/// Test-only handoff of the already installed C bootstrap. It consumes the
/// same configuration returned by actual Version FinalUse; it never calls a
/// task factory again or reconstructs a PublishedTask/RunStart from metadata.
pub(in super::super) async fn start_installed_retained_version(
    runtime: RuntimeFixture,
    mut request: AuthBusObjectiveIngress,
    mut config: AgentdConfig,
    cell: Cell,
    source: Arc<Source>,
    retirement: PublishedCircuitFeatureTaskV1,
    bundle: &CellCompatibilityBundleV1,
) -> anyhow::Result<Session> {
    let identity = config.identity();
    anyhow::ensure!(
        identity.agent_id == runtime.identity.agent_id
            && identity.spawn_generation == runtime.identity.spawn_generation
            && identity.home_root == runtime.identity.home_root
            && identity.run_root == runtime.identity.run_root,
        "same admitted C runtime"
    );
    let definition = retirement.definition();
    request.body.runtime_body_digest = definition.runtime.runtime_digest.to_string();
    request.body.model_tuple_digest = definition.semantic_digest()?.to_string();
    request.body.artifact_set_digest = bundle.digest()?.to_string();
    // This is the existing explicit AuthBus fixture issuer, applied to the
    // real original admission request and actual installed publication.
    request.signature_hex = SigningKey::from_bytes(&[91; 32])
        .sign(&crate::authbus_objective_claims(&runtime.identity, &request)?.signing_bytes())
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let (bootstrap, invocation) = config
        .take_circuit_task_bootstrap()?
        .ok_or_else(|| anyhow::anyhow!("same installed Version bootstrap once"))?;
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
        config: Some(config),
        request,
        source,
        cell,
        retirement,
        cancellation,
        worker: Some(worker),
    })
}

pub(in super::super) fn retained_version_task_inputs(
    admission: Admission,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
    original_a: crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    original_a_identity: crate::AgentdIdentity,
) -> anyhow::Result<(crate::OriginalCircuitRetainedTaskInputsV1, RuntimeFixture)> {
    let Admission {
        runtime,
        config,
        request: _original_run_start,
    } = admission;
    let file = |name| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
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
            64,
        )
    };
    let (mut circuit, mut bindings) = super::super::super::configuration();
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
    let files = CircuitQ24TaskFilesV1 {
        source_journal: file("q24-source.journal")?,
        source_witness: witness("q24-source.witness", "original-source-owner")?,
        cell_journal: file("q24-cell.journal")?,
        cell_witness: witness("q24-cell.witness", "original-cell-owner")?,
        inference_control: DurableInferenceControl::open(
            runtime.identity.home_root.join("q24-control.journal"),
            4,
        )?,
    };
    let fence = TaskFlowFence::new(
        runtime.identity.agent_id.clone(),
        "ordinary-q24-owner",
        1,
        runtime.state.current_generation()?,
        "ordinary-q24-fence",
    )?;
    let config = config
        .with_authbus_trust_file(runtime.identity.home_root.join("circuit-trust.json"))
        .with_authbus_checkpoint_file(runtime.identity.run_root.join("circuit-checkpoint.json"))
        .with_objective_profile_file(runtime.identity.home_root.join("circuit-profile.json"));
    Ok((
        crate::OriginalCircuitRetainedTaskInputsV1 {
            config,
            files,
            fence,
            circuit,
            routes: bindings.remove(0).routes,
            model,
            worker_generation: 1,
            maximum_cell_records: 16,
            queue_capacity: 4,
            clock: Arc::new(move || crate::CircuitCellTimeV1 {
                circuit_millis: crate::authbus_ingress::now_ms().expect("live wall clock"),
                cell_micros: 10
                    + u64::try_from(epoch.elapsed().as_micros()).expect("live Cell clock"),
            }),
            original_a,
            original_a_identity,
        },
        runtime,
    ))
}
