use super::*;
use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::intelligence::CanonicalStageV1;
use codex_hepta_agent_components::ndu::evaluate_candidates_with_policy;
use codex_hepta_agent_components::neuron::JournalAnchor;
use std::sync::atomic::AtomicUsize;
use std::time::Duration;

struct Allow;
impl NeuronAdmissionGuard for Allow {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Ok(())
    }
}

type TickHead = (Generation, Option<JournalAnchor>);
type ConcurrentTick = (
    AgentdNeuronHandleV2,
    NeuronTickInputV1,
    CanonicalPortInputV1,
);
struct StageProvider {
    template: NeuronTickInputV1,
    calls: AtomicUsize,
    observed: Mutex<Option<(CanonicalPortInputV1, TickHead)>>,
    advance: Mutex<Option<ConcurrentTick>>,
}
impl AgentdNeuronTickProviderV2 for StageProvider {
    fn build_tick(
        &self,
        _: &crate::AgentdIdentity,
        _: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        _: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, crate::AgentdError> {
        panic!("the early tick builder must not run")
    }
    fn build_tick_for_stage(
        &self,
        _: &crate::AgentdIdentity,
        _: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        _: &crate::AgentdIntelligenceInvocationV1,
        stage: &CanonicalPortInputV1,
        current: TickHead,
    ) -> Result<NeuronTickInputV1, crate::AgentdError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        *self.observed.lock().expect("observation") = Some((stage.clone(), current));
        if let Some((handle, input, canonical)) = self.advance.lock().expect("advance").take() {
            handle
                .prepare(
                    input.tick_id.clone(),
                    handle.body_bundle_digest().expect("body"),
                    input,
                )
                .expect("concurrent prepare")
                .execute(&canonical, &mut Allow)
                .expect("concurrent ACK");
        }
        let mut input = self.template.clone();
        input.tick_id = stage.run_id.clone();
        input.objective_digest = stage.objective_digest;
        input.ndu_snapshot_digest = stage.predecessor_digest;
        input.body_generation = Some(current.0.get());
        input.logical_sequence = current.1.map_or(1, |anchor| anchor.sequence + 1);
        input.monotonic_time_micros = input.logical_sequence * 1_000;
        input.checkpoint_digest = current
            .1
            .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest);
        Ok(input)
    }
}

struct Fixture {
    runtime: lock_metrics_tests::RuntimeFixture,
    provider: Arc<StageProvider>,
    deferred: AgentdDeferredNeuronInvocationV2,
    stage: CanonicalPortInputV1,
}
fn fixture() -> Fixture {
    let mut value = crate::intelligence_product::tests::fixture();
    let generation = value.request.snapshot.body_generation().get();
    let runtime = lock_metrics_tests::runtime_fixture_for_objective(
        generation,
        Duration::ZERO,
        Duration::ZERO,
        value.request.snapshot.objective_digest(),
    );
    let mut record = crate::canonical_abstain_provider::tests::durable_record(&value);
    record.runtime_body_digest = runtime.handle.body_bundle_digest().expect("body");
    let directory = tempfile::tempdir().expect("identity directory");
    let identity =
        crate::canonical_abstain_provider::tests::identity(directory.path(), generation - 1);
    value.inputs.run_identity = Some(
        crate::AgentdIntelligenceRunIdentityV1::from_run_start(&identity, &record)
            .expect("original run identity"),
    );
    let utility = evaluate_candidates_with_policy(
        value.inputs.utility_contributions.clone(),
        value.inputs.utility_profile.clone(),
        value.inputs.utility_scalarization.clone(),
        value.inputs.utility_policy.clone(),
    )
    .expect("actual NDU evaluation");
    let stage = CanonicalPortInputV1 {
        run_id: value.request.run_id.clone(),
        snapshot_digest: value.request.snapshot.digest(),
        objective_digest: value.request.snapshot.objective_digest(),
        candidate_set_digest: codex_hepta_agent_components::intelligence::build_legal_candidates(
            value.request.legal_candidates.clone(),
        )
        .expect("candidates")
        .candidate_set_digest,
        predecessor_digest: utility.evaluation_digest_v2,
        budget_micros: 30_000_000,
        stage: CanonicalStageV1::NeuralSignalCollected,
    };
    let controller =
        AgentdNeuronGenerationControllerV2::new(runtime.handle.clone()).expect("controller");
    controller.start().expect("serving");
    let provider = Arc::new(StageProvider {
        template: runtime.input.clone(),
        calls: AtomicUsize::new(0),
        observed: Mutex::new(None),
        advance: Mutex::new(None),
    });
    let host = Arc::new(AgentdNeuronRuntimeV2Host {
        controller,
        tick_provider: provider.clone(),
        goal_scope_factory: None,
        lifecycle: Mutex::new(()),
        stopped: AtomicBool::new(false),
        iteration_quarantine: AtomicBool::new(false),
    });
    let deferred = host
        .defer(
            identity,
            record,
            crate::AgentdIntelligenceInvocationV1 {
                request: value.request,
                inputs: value.inputs,
            },
        )
        .expect("bounded deferred invocation");
    Fixture {
        runtime,
        provider,
        deferred,
        stage,
    }
}

#[test]
fn deferred_neural_stage_reads_late_actual_ack_and_actual_ndu_before_dispatch() {
    let value = fixture();
    assert_eq!(value.provider.calls.load(Ordering::SeqCst), 0);
    let first = value
        .runtime
        .handle
        .prepare(
            value.runtime.input.tick_id.clone(),
            value.runtime.handle.body_bundle_digest().expect("body"),
            value.runtime.input.clone(),
        )
        .expect("first prepare")
        .execute(&value.runtime.canonical, &mut Allow)
        .expect("first real ACK");
    let committed = value
        .deferred
        .execute(&value.stage, &mut Allow)
        .expect("late actual tick");
    assert_eq!(
        *value.provider.observed.lock().expect("observation"),
        Some((
            value.stage,
            (
                value.deferred.invocation.request.snapshot.body_generation(),
                Some(first.next_anchor)
            )
        ))
    );
    assert_eq!(committed.next_anchor.sequence, 2);
    assert_eq!(value.runtime.calls.load(Ordering::SeqCst), 2);
    assert_eq!(value.provider.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn deferred_neural_stage_denies_foreign_snapshot_missing_ndu_and_quiesce_before_encoding() {
    let value = fixture();
    let mut foreign = value.stage.clone();
    foreign.snapshot_digest = Digest32::of_bytes(b"foreign snapshot");
    assert!(matches!(
        value.deferred.execute(&foreign, &mut Allow),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::BindingMismatch
        ))
    ));
    foreign = value.stage.clone();
    foreign.predecessor_digest = Digest32::ZERO;
    assert!(matches!(
        value.deferred.execute(&foreign, &mut Allow),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::BindingMismatch
        ))
    ));
    value.deferred.host.begin_quiesce().expect("quiesce");
    assert!(matches!(
        value.deferred.execute(&value.stage, &mut Allow),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::BindingMismatch
        ))
    ));
    assert_eq!(value.provider.calls.load(Ordering::SeqCst), 0);
    assert_eq!(value.runtime.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn deferred_neural_stage_preserves_final_owner_cas_when_head_changes_during_encoding() {
    let value = fixture();
    *value.provider.advance.lock().expect("advance") = Some((
        value.runtime.handle.clone(),
        value.runtime.input.clone(),
        value.runtime.canonical.clone(),
    ));
    assert!(matches!(
        value.deferred.execute(&value.stage, &mut Allow),
        Err(NeuronRuntimeV2Error::CheckpointMismatch)
    ));
    assert_eq!(value.runtime.calls.load(Ordering::SeqCst), 1);
    assert_eq!(value.provider.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        value
            .deferred
            .host
            .controller
            .current_tick_anchor()
            .expect("actual head")
            .1
            .expect("ACK")
            .sequence,
        1
    );
}

#[path = "neuron_runtime_v2_goal_factory_tests.rs"]
mod goal_factory_tests;
