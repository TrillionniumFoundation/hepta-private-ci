use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

fn fixture() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    registry.compare_and_transition(
        &state.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    Ok((temp, registry, state))
}

#[tokio::test]
async fn serving_agent_survives_unrelated_registry_corruption() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let peer = registry
        .layout()
        .agents_root()
        .join("019153a4-3088-7e03-a56a-9b1964f75dd3");
    fs::create_dir(peer).expect("incomplete peer");
    assert!(registry.load().is_err());
    state
        .refresh_generation()
        .expect("local generation remains valid");
    let response = state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::Lifecycle,
        )
        .await
        .expect("serving control response");
    assert_eq!(
        serde_json::to_value(response.payload).expect("serialize actual lifecycle"),
        serde_json::to_value(AgentdPayload::Lifecycle(LifecycleSnapshot {
            lifecycle: AgentLifecycle::Running,
            app_server_ready: true,
            fenced: false,
        }))
        .expect("serialize expected lifecycle")
    );
}

#[test]
fn missing_local_record_immediately_fences_the_serving_agent() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    fs::remove_file(state.identity.layout.agent_config()).expect("remove local manifest");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(state.is_fenced().expect("fenced state"));
}

#[test]
fn targeted_read_preserves_lifecycle_and_resource_fences() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let mut identity = state.identity.clone();
    identity.resources.turn_queue_capacity += 1;
    let changed = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)
        .expect("changed launch identity");
    assert!(matches!(
        changed.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("draining");
    state.refresh_generation().expect("drain remains valid");
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 3,
            AgentLifecycle::Stopped,
        )
        .expect("stopped");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
}


struct FakeNeuronRuntimePort {
    calls: Arc<AtomicU64>,
}

impl codex_hepta_intelligence::NeuronRuntimeProductPort for FakeNeuronRuntimePort {
    fn consume(
        &self,
        input: codex_hepta_intelligence::NeuronTickInputV1,
        _observation: codex_hepta_intelligence::RuntimeTickObservationV1,
    ) -> Result<
        codex_hepta_intelligence::NeuronConsumerReceiptV1,
        codex_hepta_intelligence::NeuronConsumerErrorV1,
    > {
        self.calls.fetch_add(1, Ordering::Relaxed);
        let checkpoint = codex_hepta_types::Digest32::of_bytes(b"agentd-neuron-checkpoint");
        Ok(codex_hepta_intelligence::NeuronConsumerReceiptV1 {
            tick_id: input.tick_id,
            checkpoint_digest: checkpoint,
            neuron_signal_digest: codex_hepta_types::Digest32::of_bytes(b"agentd-neuron-signal"),
            confidence_ppm: 900_000,
            ood_ppm: 10_000,
            disposition: codex_hepta_intelligence::NeuronConsumerDispositionV1::AdvisorySignal,
            receipt_digest: codex_hepta_types::Digest32::of_bytes(b"agentd-neuron-receipt"),
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        })
    }
}

fn neuron_tick_input() -> codex_hepta_intelligence::NeuronTickInputV1 {
    let features = vec![1_i64];
    codex_hepta_intelligence::NeuronTickInputV1 {
        tick_id: codex_hepta_types::StableId::new("agentd.neuron.tick.1")
            .expect("valid neuron tick id"),
        subject_id: codex_hepta_types::StableId::new("agentd.neuron.subject.1")
            .expect("valid neuron subject id"),
        logical_sequence: 1,
        monotonic_time_micros: 1,
        checkpoint_digest: codex_hepta_types::Digest32::ZERO,
        input_feature_digest: codex_hepta_types::Digest32::of_bytes(b"feature"),
        feature_vector_q24: features,
        objective_digest: codex_hepta_types::Digest32::of_bytes(b"objective"),
        ndu_snapshot_digest: codex_hepta_types::Digest32::of_bytes(b"ndu"),
        body_generation: None,
        modulator_digest: None,
    }
}

#[test]
fn real_agentd_state_holds_calls_and_generation_fences_neuron_owner_port() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let calls = Arc::new(AtomicU64::new(0));
    state
        .attach_neuron_runtime_port(Arc::new(FakeNeuronRuntimePort {
            calls: Arc::clone(&calls),
        }))
        .expect("attach neuron runtime port");

    let receipt = state
        .consume_neuron_tick(
            neuron_tick_input(),
            codex_hepta_intelligence::RuntimeTickObservationV1 {
                now_unix_micros: 2,
                queue_age_micros: 0,
            },
        )
        .expect("consume neuron tick");
    assert_eq!(receipt.tick_id.as_str(), "agentd.neuron.tick.1");
    assert!(!receipt.authority.grants_any());
    assert_eq!(calls.load(Ordering::Relaxed), 1);

    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("draining");
    assert!(matches!(
        state.consume_neuron_tick(
            neuron_tick_input(),
            codex_hepta_intelligence::RuntimeTickObservationV1 {
                now_unix_micros: 3,
                queue_age_micros: 0,
            },
        ),
        Err(AgentdError::GenerationFenced(_))
    ));
    assert_eq!(calls.load(Ordering::Relaxed), 1);
}
