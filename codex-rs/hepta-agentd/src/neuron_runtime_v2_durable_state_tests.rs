use super::*;

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::NeuronStorageCapacityV2;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

// The product contract requires a private parent. tempfile's default directory
// mode follows platform defaults/umask; do not relax the owner to accommodate it.
pub(super) fn private_state_directory() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    checked(builder.tempdir())
}

fn id(value: &str) -> StableId {
    checked(StableId::new(value))
}

fn test_input(generation: u64) -> NeuronTickInputV1 {
    let features = vec![1, 2, 3];
    NeuronTickInputV1 {
        tick_id: id(&format!("durable.state.tick.{generation}")),
        subject_id: id("durable.state.subject"),
        logical_sequence: 1,
        monotonic_time_micros: 1,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: codex_hepta_neuron::canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: Digest32::of_bytes(b"durable.state.objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"durable.state.ndu"),
        body_generation: Some(generation),
        modulator_digest: None,
    }
}

fn capacity() -> NeuronRuntimeCapacityV2 {
    let storage = NeuronStorageCapacityV2 {
        records: 0,
        record_limit: 16,
        file_bytes: 128,
        byte_limit: 16 * 1024,
        reserved_bytes: 0,
    };
    NeuronRuntimeCapacityV2 {
        generation: storage,
        index: storage,
        witness_records_remaining: Some(16),
    }
}

struct DurableStateStubOwner {
    generation: u64,
    reconciles: AtomicU64,
}

impl ProductNeuronOwnerV2 for DurableStateStubOwner {
    fn execute(
        &self,
        _input: NeuronTickInputV1,
        _guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
        self.reconciles.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }

    fn query_operation(
        &self,
        _tick_id: &StableId,
        _input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        Ok(NeuronOperationStatusV2::NotRecorded)
    }

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        Ok(capacity())
    }

    fn generation(&self) -> Option<u64> {
        Some(self.generation)
    }

    fn body_bundle_digest(&self) -> Option<Digest32> {
        Some(Digest32::of_bytes(
            format!("durable-state-body-{}", self.generation).as_bytes(),
        ))
    }
}

fn handle(generation: u64) -> (AgentdNeuronHandleV2, Arc<DurableStateStubOwner>) {
    let owner = Arc::new(DurableStateStubOwner {
        generation,
        reconciles: AtomicU64::new(0),
    });
    (
        AgentdNeuronHandleV2 {
            owner: owner.clone(),
            config_digest: Digest32::of_bytes(
                format!("durable-state-config-{generation}").as_bytes(),
            ),
            lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
        },
        owner,
    )
}

#[test]
fn generation_state_round_trips_and_rejects_digest_tampering() {
    let directory = private_state_directory();
    let path = directory.path().join("neuron-generation-state.json");
    let state = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Serving,
        2,
        vec![1],
        None,
    ));
    checked(write_agentd_neuron_generation_state_v2(&path, &state));
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)),
        state
    );

    let encoded = checked(std::fs::read_to_string(&path));
    let tampered = encoded.replacen("\"activeGeneration\": 2", "\"activeGeneration\": 3", 1);
    assert_ne!(encoded, tampered);
    checked(std::fs::write(&path, tampered));
    let error = read_agentd_neuron_generation_state_v2(&path)
        .expect_err("tampered generation state was accepted");
    assert_eq!(error.stable_code(), "control_state_corrupt");
}

#[test]
fn durable_controller_publishes_every_lifecycle_transition() {
    let directory = private_state_directory();
    let path = directory.path().join("neuron-generation-state.json");
    let (active, _) = handle(1);
    let controller = checked(AgentdNeuronGenerationControllerV2::new_with_state_path(
        active, &path,
    ));
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Starting
    );

    checked(controller.start());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Serving
    );
    checked(controller.begin_quiesce());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Quiescing
    );
    checked(controller.seal());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Sealed
    );
    checked(controller.shutdown());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Stopped
    );
}

#[test]
fn interrupted_reload_accepts_only_the_old_or_completed_topology() {
    let directory = private_state_directory();
    let path = directory.path().join("neuron-generation-state.json");
    let interrupted = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Reloading,
        1,
        Vec::new(),
        Some(2),
    ));
    checked(write_agentd_neuron_generation_state_v2(&path, &interrupted));

    let (old_active, _) = handle(1);
    let old_topology = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            old_active,
            std::iter::empty(),
            &path,
        ),
    );
    assert_eq!(
        checked(old_topology.state()),
        AgentdNeuronLifecycleStateV2::Sealed
    );
    let sealed = checked(read_agentd_neuron_generation_state_v2(&path));
    assert_eq!(sealed.lifecycle, AgentdNeuronLifecycleStateV2::Sealed);
    assert_eq!(sealed.active_generation, 1);
    assert_eq!(sealed.reload_target_generation, None);

    checked(write_agentd_neuron_generation_state_v2(&path, &interrupted));
    let (new_active, new_owner) = handle(2);
    let (old_retained, old_owner) = handle(1);
    let completed_topology = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            new_active,
            [old_retained],
            &path,
        ),
    );
    assert_eq!(
        checked(completed_topology.state()),
        AgentdNeuronLifecycleStateV2::Starting
    );
    checked(completed_topology.start());
    assert_eq!(new_owner.reconciles.load(Ordering::SeqCst), 1);
    assert_eq!(old_owner.reconciles.load(Ordering::SeqCst), 1);
    let serving = checked(read_agentd_neuron_generation_state_v2(&path));
    assert_eq!(serving.lifecycle, AgentdNeuronLifecycleStateV2::Serving);
    assert_eq!(serving.active_generation, 2);
    assert_eq!(serving.retained_generations, vec![1]);
    assert_eq!(serving.reload_target_generation, None);

    checked(write_agentd_neuron_generation_state_v2(&path, &interrupted));
    let (ambiguous_active, _) = handle(3);
    let error = match AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
        ambiguous_active,
        std::iter::empty(),
        &path,
    ) {
        Ok(_) => panic!("ambiguous interrupted reload topology was accepted"),
        Err(error) => error,
    };
    assert_eq!(error.stable_code(), "generation_conflict");
}

#[test]
fn corrupt_control_state_reports_the_specific_failure_before_service() {
    let directory = private_state_directory();
    let path = directory.path().join("neuron-generation-state.json");
    let state = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Starting,
        1,
        Vec::new(),
        None,
    ));
    checked(write_agentd_neuron_generation_state_v2(&path, &state));
    checked(std::fs::write(&path, b"not-json"));

    let (active, _) = handle(1);
    let error = match AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
        active,
        std::iter::empty(),
        &path,
    ) {
        Ok(_) => panic!("corrupt control state was accepted"),
        Err(error) => error,
    };
    assert_eq!(error.stable_code(), "control_state_corrupt");
}

#[test]
fn invalid_control_state_parent_fails_before_fencing_the_caller_handle() {
    let directory = private_state_directory();
    let path = directory
        .path()
        .join("missing-parent")
        .join("neuron-generation-state.json");
    let (active, _) = handle(1);
    let active_clone = active.clone();

    let error = match AgentdNeuronGenerationControllerV2::new_with_state_path(active, &path) {
        Ok(_) => panic!("missing control-state parent was accepted"),
        Err(error) => error,
    };
    assert_eq!(error.stable_code(), "control_state_io");

    let input = test_input(1);
    checked(
        active_clone.prepare(
            input.tick_id.clone(),
            active_clone
                .body_bundle_digest()
                .expect("active body digest"),
            input,
        ),
    );
}

#[cfg(unix)]
#[test]
fn non_private_control_state_parent_fails_before_fencing_the_caller_handle() {
    use std::os::unix::fs::PermissionsExt;

    let directory = private_state_directory();
    let parent = directory.path().join("control-state");
    checked(std::fs::create_dir(&parent));
    checked(std::fs::set_permissions(
        &parent,
        std::fs::Permissions::from_mode(0o750),
    ));
    let path = parent.join("neuron-generation-state.json");
    let state = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Starting,
        1,
        Vec::new(),
        None,
    ));
    let write_error = write_agentd_neuron_generation_state_v2(&path, &state)
        .expect_err("non-private control-state parent was accepted for publication");
    assert_eq!(write_error.stable_code(), "control_state_invalid");

    let (active, _) = handle(1);
    let active_clone = active.clone();
    let controller_error =
        match AgentdNeuronGenerationControllerV2::new_with_state_path(active, &path) {
            Ok(_) => panic!("controller accepted a non-private control-state parent"),
            Err(error) => error,
        };
    assert_eq!(controller_error.stable_code(), "control_state_invalid");

    let input = test_input(1);
    checked(
        active_clone.prepare(
            input.tick_id.clone(),
            active_clone
                .body_bundle_digest()
                .expect("active body digest"),
            input,
        ),
    );
}

#[cfg(unix)]
#[test]
fn control_state_rejects_symlinks_hardlinks_and_non_private_permissions() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let directory = private_state_directory();
    let path = directory.path().join("neuron-generation-state.json");
    let state = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Starting,
        1,
        Vec::new(),
        None,
    ));
    checked(write_agentd_neuron_generation_state_v2(&path, &state));

    let symlink_path = directory.path().join("state-symlink.json");
    checked(symlink(&path, &symlink_path));
    let symlink_error = read_agentd_neuron_generation_state_v2(&symlink_path)
        .expect_err("symlinked control state was accepted");
    assert_eq!(symlink_error.stable_code(), "control_state_invalid");

    let hardlink_path = directory.path().join("state-hardlink.json");
    checked(std::fs::hard_link(&path, &hardlink_path));
    let hardlink_error = read_agentd_neuron_generation_state_v2(&path)
        .expect_err("multiply linked control state was accepted");
    assert_eq!(hardlink_error.stable_code(), "control_state_invalid");
    checked(std::fs::remove_file(&hardlink_path));

    checked(std::fs::set_permissions(
        &path,
        std::fs::Permissions::from_mode(0o640),
    ));
    let mode_error = read_agentd_neuron_generation_state_v2(&path)
        .expect_err("non-private control state was accepted");
    assert_eq!(mode_error.stable_code(), "control_state_invalid");

    let (active, _) = handle(1);
    let controller_error =
        match AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            active,
            std::iter::empty(),
            &path,
        ) {
            Ok(_) => panic!("controller accepted non-private state"),
            Err(error) => error,
        };
    assert_eq!(controller_error.stable_code(), "control_state_invalid");
}
