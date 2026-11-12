//! Queue/admission components only. The private probe supplies data or Pending,
//! never a published task, signed Outcome, Ready observation or successful task
//! receipt. These components do not qualify Root/A/C owner assembly.

use std::future::poll_fn;
use std::task::Poll;
use std::thread;

use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_automation::CircuitStartV2;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;
use crate::CircuitTaskLearningPendingV1;
use crate::CircuitTaskLearningReadinessV1;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;

const WAIT: Duration = Duration::from_secs(5);

struct Block {
    entered: std::sync::mpsc::Sender<()>,
    release: Mutex<std::sync::mpsc::Receiver<()>>,
}

impl Block {
    fn wait(&self) {
        self.entered.send(()).unwrap();
        self.release.lock().unwrap().recv_timeout(WAIT).unwrap();
    }
}

fn block() -> (
    Block,
    std::sync::mpsc::Receiver<()>,
    std::sync::mpsc::Sender<()>,
) {
    let (entered, notified) = std::sync::mpsc::channel();
    let (release, released) = std::sync::mpsc::channel();
    (
        Block {
            entered,
            release: Mutex::new(released),
        },
        notified,
        release,
    )
}

struct ProbeInvocation {
    builds: AtomicUsize,
    observations: AtomicUsize,
    observed: AtomicUsize,
    build_block: Option<Block>,
    observation_block: Option<Block>,
}

impl AgentdCircuitTaskInvocationProviderV1 for ProbeInvocation {
    fn build(
        &self,
        _identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, AgentdError> {
        self.builds.fetch_add(1, Ordering::AcqRel);
        if let Some(block) = &self.build_block {
            block.wait();
        }
        Ok(request(record))
    }

    fn publish_result(
        &self,
        _identity: &AgentdIdentity,
        _record: &RunStartRecordV1,
        _receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError> {
        Err(AgentdError::Protocol(
            "queue probe never publishes a task result".into(),
        ))
    }

    fn observe_learning(
        &self,
        _identity: &AgentdIdentity,
        _record: &RunStartRecordV1,
        _trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        self.observations.fetch_add(1, Ordering::AcqRel);
        if let Some(block) = &self.observation_block {
            block.wait();
        }
        self.observed.fetch_add(1, Ordering::AcqRel);
        CircuitTaskLearningReadinessV1::Pending(CircuitTaskLearningPendingV1::TerminalOutcome)
    }
}

struct Fixture {
    _directory: tempfile::TempDir,
    identity: AgentdIdentity,
    record: RunStartRecordV1,
    route: Arc<SameActorTaskRoute>,
    provider: Invocation,
    probe: Arc<ProbeInvocation>,
    original: Arc<OriginalTask>,
    receiver: mpsc::Receiver<Command>,
}

impl Fixture {
    fn new(
        active: bool,
        capacity: usize,
        build: Option<Block>,
        observation: Option<Block>,
    ) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let agent_id = AgentId::parse("queue-component").unwrap();
        let fleet_root = directory.path().join("fleet");
        let layout = HeptaFleetRoot::parse(fleet_root.clone())
            .unwrap()
            .layout()
            .agent(&agent_id);
        let identity = AgentdIdentity {
            agent_id,
            home_root: layout.home_root().to_path_buf(),
            run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(),
            app_server_socket: layout.app_server_socket().to_path_buf(),
            layout,
            spawn_generation: 1,
            fleet_root,
            workspace: directory.path().to_path_buf(),
            resources: ResourceBudget::local_default(),
        };
        let record = record();
        let deadline =
            SameActorPhaseDeadline::at_original_service_start(Duration::from_secs(30)).unwrap();
        let gate = SameActorPhaseGate::from_original_deadline(deadline).unwrap();
        let (route, provider) = SameActorTaskRoute::pending_original(&identity, gate).unwrap();
        let probe = Arc::new(ProbeInvocation {
            builds: AtomicUsize::new(0),
            observations: AtomicUsize::new(0),
            observed: AtomicUsize::new(0),
            build_block: build,
            observation_block: observation,
        });
        let (sender, receiver) = mpsc::channel(capacity);
        let invocation: Invocation = probe.clone();
        let original = Arc::new(OriginalTask {
            handle: Arc::new(DirectTaskHandle {
                sender,
                generation: record.snapshot.generation,
                pending: Arc::new(AtomicUsize::new(0)),
            }),
            invocation,
        });
        if active {
            // Only the queue primitive is injected here. This does not call or
            // qualify either sealed owner-parts installer or a Ready C slot.
            route.state.lock().unwrap().phase = Phase::A {
                original: Arc::clone(&original),
            };
        }
        Self {
            _directory: directory,
            identity,
            record,
            route,
            provider,
            probe,
            original,
            receiver,
        }
    }

    fn admission(&self) -> Result<SameActorTaskAdmission, Error> {
        self.route
            .admit_original_task(&self.provider, &self.identity, &self.record)
    }

    fn handle(&self) -> CircuitTaskHandleV1 {
        CircuitTaskHandleV1 {
            route: TaskHandleRoute::SameActor {
                original: Arc::clone(&self.route),
            },
        }
    }

    fn pending(&self) -> usize {
        self.original.handle.pending.load(Ordering::Acquire)
    }
}

fn record() -> RunStartRecordV1 {
    let id = |value| StableId::new(value).unwrap();
    let digest = Digest32::of_bytes(b"explicit-queue-component-data");
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("queue-probe"),
            key_epoch: 1,
            message_id: id("queue-message"),
            sequence: 1,
            expires_at_ms: 9_999_999,
            scope_digest: digest,
            signed_body_digest: digest,
            signature: [7; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("queue-profile"),
            profile_revision: 1,
            profile_digest: digest,
            supplied_source_digest: digest,
            intent_digest: digest,
            admitted_source_digest: digest,
            observed_at_unix_micros: 1_000_000,
            deadline_unix_micros: 2_000_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: id("queue-A"),
            objective_digest: digest,
            hard_constraint_digest: digest,
            preference_state_digest: digest,
            model_tuple_digest: digest,
            prompt_registry_digest: digest,
            artifact_set_digest: digest,
            authority_epoch: 1,
            generation: 2,
            fence_digest: digest,
        },
        runtime_body_digest: digest,
        objective_semantic_bytes: b"explicit-queue-component-data".to_vec(),
        objective_function_v1_digest: digest,
        objective_function_v1_bytes: b"queue-probe-not-an-authenticated-objective".to_vec(),
    }
}

fn request(record: &RunStartRecordV1) -> CircuitTaskRequestV1 {
    CircuitTaskRequestV1 {
        start: CircuitStartV2 {
            run_id: record.snapshot.run_id.to_string(),
            scope_digest: Sha256Digest::for_bytes(b"queue-scope"),
            input_digest: Sha256Digest::for_bytes(b"queue-input"),
            created_at_ms: record.admission.observed_at_unix_micros / 1_000,
            lease_duration_ms: 500,
        },
        objective_digest: record.snapshot.objective_digest,
        deadline_ms: 1_900,
    }
}

async fn poll_pending<F: Future>(mut future: Pin<&mut F>) {
    let result = poll_fn(|cx| Poll::Ready(future.as_mut().poll(cx))).await;
    assert!(matches!(result, Poll::Pending));
}

async fn unresolved_observation_trace(f: &Fixture) -> (AutomationStore, CircuitCommittedTraceV2) {
    let store = AutomationStore::open(&f.identity.layout).await.unwrap();
    let (definition, _) = crate::circuit_cell::tests::configuration();
    let fence = TaskFlowFence::new(
        f.identity.agent_id.clone(),
        "queue-observation-probe",
        1,
        f.record.snapshot.generation,
        "queue-observation-fence",
    )
    .unwrap();
    store
        .create_bounded_circuit_run(&definition, &request(&f.record).start, &fence)
        .await
        .unwrap();
    let trace = store
        .bounded_circuit_committed_trace(f.record.snapshot.run_id.as_str())
        .await
        .unwrap()
        .unwrap();
    assert!(trace.run().outcome().is_none());
    // A real unresolved trace is only the Pending probe's method argument.
    // It is not an Experience, signed Outcome or terminal task result.
    (store, trace)
}

#[tokio::test]
async fn pending_and_bare_phase_paths_cannot_build_or_queue() {
    let mut f = Fixture::new(false, 1, None, None);
    assert!(matches!(f.admission(), Err(Error::Unavailable)));
    assert!(f.provider.build(&f.identity, &f.record).is_err());
    assert_eq!(
        f.handle()
            .submit(request(&f.record), f.record.clone())
            .await,
        Err(Error::Unavailable)
    );
    assert_eq!(
        f.handle()
            .readback(request(&f.record), f.record.clone())
            .await,
        Err(Error::Unavailable)
    );
    assert_eq!(f.probe.builds.load(Ordering::Acquire), 0);
    assert_eq!(f.route.pending_count(), 0);
    assert!(f.receiver.try_recv().is_err());
    assert!(f.route.gate.require_open().is_ok());
}

#[test]
fn wrong_identity_record_or_invocation_closes_without_build() {
    for case in ["identity", "record", "invocation"] {
        let mut f = Fixture::new(true, 1, None, None);
        let mut identity = f.identity.clone();
        let mut record = f.record.clone();
        let mut provider = Arc::clone(&f.provider);
        match case {
            "identity" => identity.resources.turn_queue_capacity += 1,
            "record" => record.snapshot.generation += 1,
            "invocation" => provider = f.probe.clone(),
            _ => unreachable!(),
        }
        assert!(
            matches!(
                f.route.admit_original_task(&provider, &identity, &record),
                Err(Error::InvalidBinding)
            ),
            "{case}"
        );
        assert!(f.route.gate.require_open().is_err(), "{case}");
        assert!(matches!(f.admission(), Err(Error::Unavailable)), "{case}");
        assert_eq!(f.probe.builds.load(Ordering::Acquire), 0);
        assert_eq!(f.pending(), 0);
        assert!(f.receiver.try_recv().is_err());
    }
}

#[test]
fn closing_cut_keeps_an_admitted_build_but_refuses_later_admission() {
    let (blocked, entered, release) = block();
    let mut f = Fixture::new(true, 1, Some(blocked), None);
    let mut ticket = f.admission().unwrap();
    let build = thread::spawn(move || {
        let result = ticket.build_original_task_request();
        (ticket, result)
    });
    entered.recv_timeout(WAIT).unwrap();
    f.route.begin_closing_original_a().unwrap();
    assert!(matches!(f.admission(), Err(Error::Unavailable)));
    assert_eq!(f.route.pending_count(), 1);
    assert_eq!(f.pending(), 0);
    release.send(()).unwrap();
    let (ticket, result) = build.join().unwrap();
    assert_eq!(result.unwrap(), request(&f.record));
    assert_eq!(f.probe.builds.load(Ordering::Acquire), 1);
    assert!(f.receiver.try_recv().is_err());
    // Cancellation after build closes the phase; it cannot leave a deferred
    // request which the subsequent C installation would later execute.
    drop(ticket);
    assert!(f.route.gate.require_open().is_err());
    assert_eq!(f.route.pending_count(), 0);
    assert!(matches!(f.admission(), Err(Error::Unavailable)));
}

#[tokio::test]
async fn closing_a_ticket_queues_once_and_cancelled_work_stays_counted() {
    let mut f = Fixture::new(true, 1, None, None);
    let mut ticket = f.admission().unwrap();
    let request = ticket.build_original_task_request().unwrap();
    f.route.begin_closing_original_a().unwrap();
    let mut submit = Box::pin(ticket.submit_original_task_request(request.clone()));
    poll_pending(submit.as_mut()).await;
    let command = f.receiver.try_recv().unwrap();
    assert_eq!(command.request, request);
    assert_eq!(command.record, f.record);
    command
        .phase
        .as_ref()
        .unwrap()
        .require_original_queue_admission()
        .unwrap();
    assert_eq!(f.pending(), 1);
    assert_eq!(f.route.state.lock().unwrap().tickets, 1);
    assert!(matches!(f.admission(), Err(Error::Unavailable)));
    // The phase mutex is not held while waiting for the original worker.
    assert!(f.route.state.try_lock().is_ok());
    drop(submit);
    assert!(f.route.gate.require_open().is_err());
    drop(ticket);
    assert_eq!(f.route.pending_count(), 2);
    assert_eq!(
        f.handle().readback(request, f.record.clone()).await,
        Err(Error::Unavailable)
    );
    assert!(
        command
            .phase
            .as_ref()
            .unwrap()
            .require_original_queue_admission()
            .is_err()
    );
    drop(command);
    assert_eq!(f.pending(), 0);
    assert_eq!(f.route.pending_count(), 0);
}

#[tokio::test]
async fn full_original_queue_rolls_back_transfer_and_closes_phase() {
    let mut f = Fixture::new(true, 1, None, None);
    let mut first = f.admission().unwrap();
    let first_request = first.build_original_task_request().unwrap();
    let mut waiting = Box::pin(first.submit_original_task_request(first_request));
    poll_pending(waiting.as_mut()).await;
    let mut second = f.admission().unwrap();
    let second_request = second.build_original_task_request().unwrap();
    assert_eq!(
        second.submit_original_task_request(second_request).await,
        Err(Error::QueueFull)
    );
    assert!(f.route.gate.require_open().is_err());
    // The failed send drops only its own pending guard. Original queued work
    // still exists and must be included even after both callers disappear.
    assert_eq!(f.pending(), 1);
    assert_eq!(f.route.state.lock().unwrap().tickets, 2);
    drop(waiting);
    drop(first);
    drop(second);
    assert_eq!(f.route.pending_count(), 2);
    let command = f.receiver.try_recv().unwrap();
    assert!(f.receiver.try_recv().is_err());
    drop(command);
    assert_eq!(f.route.pending_count(), 0);
}

#[tokio::test]
async fn lost_original_ack_closes_before_return_without_readback_or_resend() {
    let mut f = Fixture::new(true, 1, None, None);
    let mut ticket = f.admission().unwrap();
    let request = ticket.build_original_task_request().unwrap();
    let mut waiting = Box::pin(ticket.submit_original_task_request(request.clone()));
    poll_pending(waiting.as_mut()).await;
    let Command {
        response,
        _pending,
        phase,
        ..
    } = f.receiver.try_recv().unwrap();
    // Keep the real queued-work guards; only the original acknowledgement dies.
    drop(response);
    assert_eq!(waiting.await, Err(Error::CommitUncertain));
    assert!(f.route.gate.require_open().is_err());
    assert_eq!(
        ticket.submit_original_task_request(request.clone()).await,
        Err(Error::Unavailable)
    );
    assert_eq!(
        f.handle().readback(request, f.record.clone()).await,
        Err(Error::Unavailable)
    );
    assert_eq!(f.pending(), 1);
    assert!(f.receiver.try_recv().is_err());
    drop(ticket);
    assert_eq!(f.route.pending_count(), 2);
    drop(_pending);
    drop(phase);
    assert_eq!(f.route.pending_count(), 0);
}

#[tokio::test]
async fn queue_quiescence_requires_both_ticket_and_actual_worker_drain() {
    let f = Fixture::new(true, 1, None, None);
    let ticket = f.admission().unwrap();
    f.route.begin_closing_original_a().unwrap();
    let mut waiting = Box::pin(f.route.wait_original_a_quiescent());
    poll_pending(waiting.as_mut()).await;
    assert_eq!(f.pending(), 0);
    assert_eq!(f.route.state.lock().unwrap().tickets, 1);
    // Releasing before the admitted build is gone fails closed, even with an
    // empty mpsc queue. No test marks A complete or fabricates a C owner.
    assert!(f.route.release_original_a().is_err());
    assert!(waiting.await.is_err());
    assert!(matches!(
        f.route.state.lock().unwrap().phase,
        Phase::ClosingA { .. }
    ));
    drop(ticket);
    assert_eq!(f.route.pending_count(), 0);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_observation_remains_counted_until_blocking_callback_finishes() {
    let (blocked, entered, release) = block();
    let f = Fixture::new(true, 1, None, Some(blocked));
    let ticket = f.admission().unwrap();
    let (store, trace) = unresolved_observation_trace(&f).await;
    let observation = tokio::spawn(async move {
        let observed = ticket.observe_original_task_learning(&trace).await;
        (ticket, observed)
    });
    entered.recv_timeout(WAIT).unwrap();
    assert_eq!(f.probe.observations.load(Ordering::Acquire), 1);
    assert_eq!(f.route.pending_count(), 1);
    observation.abort();
    match observation.await {
        Err(error) => assert!(error.is_cancelled()),
        Ok(_) => panic!("cancelled observation unexpectedly returned"),
    }
    assert!(f.route.gate.require_open().is_err());
    assert_eq!(f.pending(), 0);
    assert_eq!(f.route.pending_count(), 1);
    release.send(()).unwrap();
    tokio::time::timeout(WAIT, async {
        while f.route.pending_count() != 0 {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(f.probe.observed.load(Ordering::Acquire), 1);
    assert_eq!(f.route.pending_count(), 0);
    store.close().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stopped_original_observer_closes_phase_instead_of_becoming_outcome_pending() {
    let (blocked, entered, release) = block();
    // The actual spawn_blocking callback enters, then panics on its deliberately
    // disconnected component barrier. No task receipt or owner is fabricated.
    drop(release);
    let f = Fixture::new(true, 1, None, Some(blocked));
    let ticket = f.admission().unwrap();
    let (store, trace) = unresolved_observation_trace(&f).await;
    let observed = ticket.observe_original_task_learning(&trace).await;
    entered.recv_timeout(WAIT).unwrap();
    match observed {
        CircuitTaskLearningReadinessV1::Pending(CircuitTaskLearningPendingV1::Refused(reason)) => {
            assert!(reason.contains("original learning owner observation stopped:"))
        }
        _ => panic!("stopped original callback was not reported as refused"),
    }
    assert!(f.route.gate.require_open().is_err());
    assert!(matches!(f.admission(), Err(Error::Unavailable)));
    assert_eq!(f.probe.observations.load(Ordering::Acquire), 1);
    assert_eq!(f.probe.observed.load(Ordering::Acquire), 0);
    assert_eq!(f.route.pending_count(), 1);
    assert!(ticket.finish_original_task().is_err());
    assert_eq!(f.route.pending_count(), 0);
    store.close().await;
}
