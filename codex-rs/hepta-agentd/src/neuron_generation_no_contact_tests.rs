//! Real Fleet, service, file journal and inference-control ownership. The worker
//! deliberately returns an unknown result; no model execution is qualified.

use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_neuron::*;
use pretty_assertions::assert_eq;
use tokio::time::sleep;
use tokio::time::timeout;

use super::support::Fixture;
use super::support::checked;
use super::support::host;
use super::support::request;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::RuntimeTasks;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;

const CONTROL_FILE: &str = "no-contact-control.log";
type Clock = Arc<dyn Fn() -> u64 + Send + Sync>;

#[derive(Default)]
struct UnknownWorker {
    calls: AtomicUsize,
}

impl CellGenerationWorkerV2 for UnknownWorker {
    fn execute(
        &self,
        _manifest: &CellBackendManifestV2,
        _request: &CellGenerationRequestV2,
        _cancellation: &AtomicBool,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Err(CellGenerationErrorV2::Unavailable)
    }
}

struct ObservedPort {
    inner: ControlledCellGenerationPortV2,
    contacts: Arc<AtomicUsize>,
}

impl CellGenerationControlPortV2 for ObservedPort {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.contacts.fetch_add(1, Ordering::SeqCst);
        self.inner.execute_generation(manifest, request)
    }

    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        self.inner.read_generation(request)
    }

    fn cancel_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        self.inner.cancel_generation(request)
    }
}

fn clock() -> Clock {
    let epoch = Instant::now();
    Arc::new(move || checked(u64::try_from(epoch.elapsed().as_micros())) + 20)
}

enum PrecontactBoundary {
    Drain,
    Fence,
}

fn boundary_clock(fixture: &Fixture, clock: Clock, boundary: PrecontactBoundary) -> Clock {
    let state = Arc::clone(fixture.state());
    let registry = fixture.registry.clone();
    let agent_id = fixture.identity.agent_id.clone();
    let samples = AtomicUsize::new(0);
    Arc::new(move || {
        if samples.fetch_add(1, Ordering::SeqCst) == 1 {
            match boundary {
                PrecontactBoundary::Drain => {
                    checked(registry.compare_and_transition(
                        &agent_id,
                        /*expected_generation*/ 2,
                        AgentLifecycle::Draining,
                    ));
                    checked(state.refresh_generation());
                    checked(state.mark_draining());
                }
                PrecontactBoundary::Fence => state.mark_fenced(),
            }
            // An actual bounded wait makes the host wall observation visible;
            // it is not simulated backend computation or a fake CPU charge.
            std::thread::sleep(Duration::from_millis(2));
        }
        clock()
    })
}

async fn open_control(fixture: &Fixture) -> DurableInferenceControl {
    checked(checked(
        timeout(Duration::from_secs(5), async {
            loop {
                match DurableInferenceControl::open(
                    fixture.directory.path().join(CONTROL_FILE),
                    /*capacity*/ 32,
                ) {
                    Ok(control) => return Ok(control),
                    Err(ControlError::WriterUnavailable) => sleep(Duration::from_millis(1)).await,
                    Err(error) => return Err(error),
                }
            }
        })
        .await,
    ))
}

async fn start(
    fixture: &Fixture,
    clock: Clock,
    worker: Arc<UnknownWorker>,
    contacts: Arc<AtomicUsize>,
) -> (NeuronGenerationRuntimeHandleV2, RuntimeTasks) {
    let port = checked(ControlledCellGenerationPortV2::spawn(
        open_control(fixture).await,
        ControlledCellGenerationConfigV2 {
            scope: fixture.config.initial.scope.clone(),
            manifest: fixture.config.manifest.clone(),
            worker_generation: fixture.identity.spawn_generation,
            queue_capacity: 2,
            rpc_timeout: Duration::from_secs(1),
        },
        worker,
        Arc::clone(&clock),
    ));
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        ObservedPort {
            inner: port,
            contacts,
        },
        move || clock(),
        /*capacity*/ 2,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime,
    ));
    (handle, tasks)
}

fn original(fixture: &Fixture, clock: &Clock) -> CellGenerationRequestV2 {
    let mut original = request("precontact-race", fixture.config.initial.clone());
    original.admitted_at_micros = clock();
    original.deadline_micros = original.admitted_at_micros + 10_000_000;
    original
}

fn durable_bytes(fixture: &Fixture) -> [Vec<u8>; 3] {
    ["generation-journal", "generation-witness", CONTROL_FILE]
        .map(|name| checked(fs::read(fixture.directory.path().join(name))))
}

#[tokio::test]
async fn fleet_drain_after_admission_settles_without_contact_and_cold_replays_exact_cost() {
    let mut fixture = Fixture::new().await;
    let clock = clock();
    let changing_clock = boundary_clock(&fixture, Arc::clone(&clock), PrecontactBoundary::Drain);
    let worker = Arc::new(UnknownWorker::default());
    let contacts = Arc::new(AtomicUsize::new(0));
    let (handle, mut tasks) = start(
        &fixture,
        changing_clock,
        Arc::clone(&worker),
        Arc::clone(&contacts),
    )
    .await;
    let control_before = checked(fs::read(fixture.directory.path().join(CONTROL_FILE)));
    let original = original(&fixture, &clock);
    let receipt = checked(handle.step(original.clone()).await);
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Rejected);
    assert_eq!(contacts.load(Ordering::SeqCst), 0);
    assert_eq!(worker.calls.load(Ordering::SeqCst), 0);
    let [entry] = receipt.cost.entries() else {
        panic!("one observed host interval");
    };
    let Some(wall) = entry.metrics.wall_micros else {
        panic!("host wall was measured");
    };
    assert!(wall >= 1_000);
    assert_eq!(entry.stage, CellCostStageV2::Queue);
    assert_eq!(entry.outcome, CellCostOutcomeV2::Rejected);
    assert_eq!(entry.accounting, CellCostAccountingV2::Exclusive);
    assert_eq!(
        entry.metrics,
        CellCostMetricsV2 {
            wall_micros: Some(wall),
            ..CellCostMetricsV2::default()
        }
    );
    assert_eq!(checked(receipt.cost.summary()).complete_metrics(), None);
    assert_eq!(checked(handle.task_cost().await), receipt.cost);
    assert_eq!(checked(handle.pending_request().await), None);
    assert_eq!(checked(handle.pending_output().await), None);
    let mut expected = fixture.config.initial.clone();
    expected.revision = 1;
    assert_eq!(checked(handle.snapshot().await), expected);
    let bytes = durable_bytes(&fixture);
    assert_eq!(checked(handle.step(original.clone()).await), receipt);
    assert_eq!(durable_bytes(&fixture), bytes);
    assert!(checked(handle.drain().await));
    assert_eq!(
        checked(fixture.state().neuron_generation_drain_blockers()),
        0
    );
    checked(checked(
        timeout(
            Duration::from_secs(1),
            crate::runtime::drain_runtime(Arc::clone(fixture.state())),
        )
        .await,
    ));
    let drained_bytes = durable_bytes(&fixture);
    tasks.shutdown().await;
    drop(handle);

    fixture.reopen_state().await;
    let (handle, mut tasks) = start(
        &fixture,
        Arc::clone(&clock),
        Arc::clone(&worker),
        Arc::clone(&contacts),
    )
    .await;
    assert_eq!(checked(handle.step(original).await), receipt);
    assert_eq!(checked(handle.task_cost().await), receipt.cost);
    assert_eq!(checked(handle.snapshot().await), expected);
    assert!(checked(handle.drain().await));
    assert_eq!(durable_bytes(&fixture), drained_bytes);
    assert_eq!(
        checked(fs::read(fixture.directory.path().join(CONTROL_FILE))),
        control_before
    );
    assert_eq!(contacts.load(Ordering::SeqCst), 0);
    assert_eq!(worker.calls.load(Ordering::SeqCst), 0);
    tasks.shutdown().await;
}

#[tokio::test]
async fn fenced_live_stack_and_cold_missing_control_record_remain_pending() {
    let mut fixture = Fixture::new().await;
    let clock = clock();
    let changing_clock = boundary_clock(&fixture, Arc::clone(&clock), PrecontactBoundary::Fence);
    let worker = Arc::new(UnknownWorker::default());
    let contacts = Arc::new(AtomicUsize::new(0));
    let (handle, mut tasks) = start(
        &fixture,
        changing_clock,
        Arc::clone(&worker),
        Arc::clone(&contacts),
    )
    .await;
    let original = original(&fixture, &clock);
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Unavailable)
    );
    assert!(checked(fixture.state().is_fenced()));
    tasks.shutdown().await;
    drop(handle);
    {
        let journal = fixture.journal();
        assert_eq!(checked(journal.pending_request()), Some(&original));
        assert_eq!(checked(journal.snapshot()), &fixture.config.initial);
        assert_eq!(checked(journal.lookup(&original)), None);
        assert!(checked(journal.task_cost()).entries().is_empty());
        let control = open_control(&fixture).await;
        assert!(!checked(control.generation_has_unresolved()));
    }

    fixture.reopen_state().await;
    let (handle, mut tasks) = start(
        &fixture,
        Arc::clone(&clock),
        Arc::clone(&worker),
        Arc::clone(&contacts),
    )
    .await;
    let bytes = durable_bytes(&fixture);
    assert_eq!(
        handle.reconcile(checked(original.digest())).await,
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(durable_bytes(&fixture), bytes);
    assert_eq!(
        handle.cancel(checked(original.digest())).await,
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(checked(handle.pending_request().await), Some(original));
    assert_eq!(checked(handle.snapshot().await), fixture.config.initial);
    assert!(checked(handle.pending_output().await).is_none());
    assert!(!checked(handle.drain().await));
    assert!(checked(fixture.state().neuron_generation_drain_blockers()) > 0);
    assert_eq!(contacts.load(Ordering::SeqCst), 0);
    assert_eq!(worker.calls.load(Ordering::SeqCst), 0);
    tasks.shutdown().await;
}

#[tokio::test]
async fn contacted_unknown_worker_remains_unresolved_through_drain_and_reopen() {
    let mut fixture = Fixture::new().await;
    let clock = clock();
    let worker = Arc::new(UnknownWorker::default());
    let contacts = Arc::new(AtomicUsize::new(0));
    let (handle, mut tasks) = start(
        &fixture,
        Arc::clone(&clock),
        Arc::clone(&worker),
        Arc::clone(&contacts),
    )
    .await;
    let original = original(&fixture, &clock);
    let digest = checked(original.digest());
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Pending)
    );
    checked(
        timeout(Duration::from_secs(5), async {
            loop {
                match handle.reconcile(digest).await {
                    Err(CellGenerationErrorV2::Pending) => sleep(Duration::from_millis(1)).await,
                    Err(CellGenerationErrorV2::Unavailable) => break,
                    other => panic!("original unknown worker outcome: {other:?}"),
                }
            }
        })
        .await,
    );
    fixture.begin_drain();
    assert!(!checked(handle.drain().await));
    assert_eq!(
        checked(handle.pending_request().await),
        Some(original.clone())
    );
    assert_eq!(checked(handle.snapshot().await), fixture.config.initial);
    assert_eq!(contacts.load(Ordering::SeqCst), 1);
    assert_eq!(worker.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
    drop(handle);
    {
        let control = open_control(&fixture).await;
        assert!(checked(control.generation_has_unresolved()));
    }

    fixture.reopen_state().await;
    let (handle, mut tasks) =
        start(&fixture, clock, Arc::clone(&worker), Arc::clone(&contacts)).await;
    let bytes = durable_bytes(&fixture);
    assert_eq!(
        handle.reconcile(digest).await,
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(checked(handle.pending_request().await), Some(original));
    assert!(!checked(handle.drain().await));
    assert_eq!(durable_bytes(&fixture), bytes);
    assert_eq!(contacts.load(Ordering::SeqCst), 1);
    assert_eq!(worker.calls.load(Ordering::SeqCst), 1);
    assert!(checked(handle.pending_output().await).is_none());
    assert_eq!(
        checked(checked(handle.task_cost().await).summary()).complete_metrics(),
        None
    );
    tasks.shutdown().await;
}
