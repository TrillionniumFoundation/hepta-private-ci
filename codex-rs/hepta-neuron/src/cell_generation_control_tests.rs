//! Real control files and threads; the worker here is a lifecycle fixture,
//! not a selected model or physical inference qualification.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;

use pretty_assertions::assert_eq;

use super::*;
use crate::cell_test_support::checked;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    directory: PathBuf,
    config: ControlledCellGenerationConfigV2,
    request: CellGenerationRequestV2,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let directory =
            std::env::temp_dir().join(format!("hepta-control-{}-{serial}", std::process::id()));
        checked(fs::create_dir(&directory));
        let scope = CellGenerationScopeV2 {
            principal_digest: [1; 32],
            agent_id: "agent".into(),
            cell_id: "cell".into(),
            run_id: "run".into(),
        };
        let manifest = CellBackendManifestV2 {
            profile: "control-fixture".into(),
            source_digest: [2; 32],
            bundle_digest: [3; 32],
            encoder: Some([4; 32]),
            head: None,
            memory: None,
            world_model: None,
            decoder: Some([5; 32]),
            runtime_digest: [6; 32],
            device_digest: [7; 32],
            input_schema: [8; 32],
            state_schema: [9; 32],
            output_schema: [10; 32],
            learning: CellLearningBindingV2::Frozen { weights: [11; 32] },
            evolution: CellEvolutionBindingV2 {
                structure: [12; 32],
                lineage: [13; 32],
                source_dependencies: [14; 32],
                adoption_receipt: [15; 32],
            },
            max_input_bytes: 128,
            max_state_bytes: 128,
            max_delta_bytes: 128,
            max_prefix_bytes: 256,
            max_step_cost_entries: 8,
            max_ack_cost_entries: 2,
        };
        let request = CellGenerationRequestV2 {
            operation_id: "original".into(),
            task_digest: [16; 32],
            source_frontier: [17; 32],
            predecessor: CellRuntimeSnapshotV2 {
                scope: scope.clone(),
                manifest_digest: checked(manifest.digest()),
                generation: 3,
                writer_epoch: 4,
                revision: 0,
                state: vec![5],
                prefix: Vec::new(),
                stopped: false,
            },
            input: vec![6],
            admitted_at_micros: 10,
            deadline_micros: 100,
        };
        Self {
            directory,
            config: ControlledCellGenerationConfigV2 {
                scope,
                manifest,
                worker_generation: 9,
                queue_capacity: 1,
                rpc_timeout: Duration::from_secs(1),
            },
            request,
        }
    }

    fn path(&self) -> PathBuf {
        self.directory.join("control.log")
    }

    fn port(&self, worker: Arc<FixtureWorker>, clock: Clock) -> ControlledCellGenerationPortV2 {
        checked(ControlledCellGenerationPortV2::spawn(
            checked(DurableInferenceControl::open(
                self.path(),
                /*capacity*/ 32,
            )),
            self.config.clone(),
            worker,
            clock,
        ))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

#[derive(Clone, Copy)]
enum WorkerMode {
    Cooperative,
    Held,
    Unknown,
    WrongIdentity,
    Oversized,
}

struct FixtureWorker {
    mode: WorkerMode,
    calls: AtomicUsize,
    release: AtomicBool,
}

impl FixtureWorker {
    fn new(mode: WorkerMode) -> Arc<Self> {
        Arc::new(Self {
            mode,
            calls: AtomicUsize::new(0),
            release: AtomicBool::new(false),
        })
    }
}

impl CellGenerationWorkerV2 for FixtureWorker {
    fn execute(
        &self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
        cancellation: &AtomicBool,
    ) -> WorkerResult {
        let started = Instant::now();
        self.calls.fetch_add(1, Ordering::SeqCst);
        if matches!(self.mode, WorkerMode::Unknown) {
            return Err(CellGenerationErrorV2::Unavailable);
        }
        while !self.release.load(Ordering::Acquire)
            && (matches!(self.mode, WorkerMode::Held) || !cancellation.load(Ordering::Acquire))
        {
            thread::sleep(Duration::from_millis(1));
        }
        let cancelled = cancellation.load(Ordering::Acquire);
        let mut proposal = no_compute(
            manifest,
            request,
            if cancelled {
                CellGenerationDispositionV2::Cancelled
            } else {
                CellGenerationDispositionV2::Advanced
            },
        )?;
        if !cancelled {
            proposal.successor_state.push(7);
            proposal.output_delta = b"observed".to_vec();
        }
        if matches!(self.mode, WorkerMode::WrongIdentity) {
            proposal.bundle_digest = [99; 32];
        }
        if matches!(self.mode, WorkerMode::Oversized) {
            proposal.output_delta = vec![1; manifest.max_delta_bytes as usize + 1];
        }
        proposal
            .cost
            .record(CellCostEntryV2 {
                event_id: Digest32::of_parts(&[b"fixture-compute", &proposal.request_digest])
                    .into_array(),
                identity: proposal.cost.identity(),
                stage: CellCostStageV2::Inference,
                outcome: if cancelled {
                    CellCostOutcomeV2::Cancelled
                } else {
                    CellCostOutcomeV2::Succeeded
                },
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2 {
                    wall_micros: Some(micros(started.elapsed())?),
                    ..CellCostMetricsV2::default()
                },
            })
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        Ok(proposal)
    }
}

fn wait_until(mut condition: impl FnMut() -> bool) {
    let limit = Instant::now() + Duration::from_secs(5);
    while !condition() {
        assert!(Instant::now() < limit, "fixture condition did not complete");
        thread::sleep(Duration::from_millis(1));
    }
}

fn terminal(
    port: &mut ControlledCellGenerationPortV2,
    request: &CellGenerationRequestV2,
) -> CellGenerationProposalV2 {
    let mut result = None;
    wait_until(|| match port.read_generation(request) {
        Ok(Some(proposal)) => {
            result = Some(proposal);
            true
        }
        Ok(None) | Err(CellGenerationErrorV2::Capacity) => false,
        Err(error) => panic!("unexpected readback failure: {error:?}"),
    });
    checked(result.ok_or("terminal proposal"))
}

#[test]
fn independent_worker_does_not_block_durable_cancellation_or_exact_readback() {
    let fixture = Fixture::new();
    let worker = FixtureWorker::new(WorkerMode::Cooperative);
    let mut port = fixture.port(Arc::clone(&worker), Arc::new(|| 20));
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &fixture.request),
        Err(CellGenerationErrorV2::Pending)
    );
    wait_until(|| worker.calls.load(Ordering::Acquire) == 1);
    let started = Instant::now();
    checked(port.cancel_generation(&fixture.request));
    assert!(started.elapsed() < fixture.config.rpc_timeout);
    let proposal = terminal(&mut port, &fixture.request);
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(proposal.successor_state, fixture.request.predecessor.state);
    assert_eq!(proposal.output_delta, Vec::<u8>::new());
    assert_eq!(proposal.cost.entries().len(), 3);
    assert!(
        proposal
            .cost
            .entries()
            .iter()
            .all(|entry| entry.metrics.cpu_micros.is_none())
    );
    let bytes = checked(fs::read(fixture.path()));
    assert_eq!(
        port.read_generation(&fixture.request),
        Ok(Some(proposal.clone()))
    );
    assert_eq!(
        port.read_generation(&fixture.request),
        Ok(Some(proposal.clone()))
    );
    assert_eq!(checked(fs::read(fixture.path())), bytes);
    checked(port.shutdown());
    let control = checked(DurableInferenceControl::open(
        fixture.path(),
        /*capacity*/ 32,
    ));
    let (binding, _) = checked(prepare(&fixture.config, &fixture.request));
    let record = checked(checked(control.generation_record(&binding)).ok_or("record"));
    assert!(record.cancel_requested);
    let result = checked(record.result.as_ref().ok_or("result"));
    assert_eq!(
        checked(serde_json::from_slice::<CellGenerationProposalV2>(
            &result.bytes
        )),
        proposal
    );
}

#[test]
fn terminal_control_reopen_reads_original_bytes_without_running_another_worker() {
    let fixture = Fixture::new();
    let worker = FixtureWorker::new(WorkerMode::Cooperative);
    worker.release.store(true, Ordering::Release);
    let mut port = fixture.port(Arc::clone(&worker), Arc::new(|| 20));
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &fixture.request),
        Err(CellGenerationErrorV2::Pending)
    );
    let proposal = terminal(&mut port, &fixture.request);
    checked(port.shutdown());
    assert!(port.is_closed());
    drop(port);
    let bytes = checked(fs::read(fixture.path()));
    let mut reopened = fixture.port(Arc::clone(&worker), Arc::new(|| 500));
    assert_eq!(
        reopened.read_generation(&fixture.request),
        Ok(Some(proposal.clone()))
    );
    assert_eq!(
        reopened.execute_generation(&fixture.config.manifest, &fixture.request),
        Ok(proposal)
    );
    assert_eq!(worker.calls.load(Ordering::Acquire), 1);
    assert_eq!(checked(fs::read(fixture.path())), bytes);
    checked(reopened.shutdown());
}

#[test]
fn lost_rpc_reply_and_queue_capacity_cannot_duplicate_original_dispatch() {
    let mut fixture = Fixture::new();
    fixture.config.rpc_timeout = Duration::from_millis(30);
    let worker = FixtureWorker::new(WorkerMode::Cooperative);
    worker.release.store(true, Ordering::Release);
    let release = Arc::new(AtomicBool::new(false));
    let calls = Arc::new(AtomicUsize::new(0));
    let clock_release = Arc::clone(&release);
    let clock_calls = Arc::clone(&calls);
    let clock: Clock = Arc::new(move || {
        if clock_calls.fetch_add(1, Ordering::SeqCst) == 1 {
            while !clock_release.load(Ordering::Acquire) {
                thread::sleep(Duration::from_millis(1));
            }
        }
        20
    });
    let mut port = fixture.port(Arc::clone(&worker), clock);
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &fixture.request),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    wait_until(|| calls.load(Ordering::Acquire) >= 2);
    assert_eq!(
        port.read_generation(&fixture.request),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(
        port.cancel_generation(&fixture.request),
        Err(CellGenerationErrorV2::Capacity)
    );
    assert_eq!(worker.calls.load(Ordering::Acquire), 0);
    release.store(true, Ordering::Release);
    let proposal = terminal(&mut port, &fixture.request);
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &fixture.request),
        Ok(proposal)
    );
    let bytes = checked(fs::read(fixture.path()));
    let mut changed = fixture.request.clone();
    changed.input.push(8);
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &changed),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        port.cancel_generation(&changed),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(worker.calls.load(Ordering::Acquire), 1);
    assert_eq!(checked(fs::read(fixture.path())), bytes);
    checked(port.shutdown());
}

#[test]
fn unknown_worker_keeps_the_single_pending_slot_across_reopen() {
    let fixture = Fixture::new();
    let worker = FixtureWorker::new(WorkerMode::Unknown);
    let mut port = fixture.port(Arc::clone(&worker), Arc::new(|| 20));
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &fixture.request),
        Err(CellGenerationErrorV2::Pending)
    );
    wait_until(|| {
        port.read_generation(&fixture.request) == Err(CellGenerationErrorV2::Unavailable)
    });
    let mut next = fixture.request.clone();
    next.operation_id = "second".into();
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &next),
        Err(CellGenerationErrorV2::Capacity)
    );
    checked(port.shutdown());
    drop(port);
    let mut reopened = fixture.port(Arc::clone(&worker), Arc::new(|| 20));
    assert_eq!(reopened.read_generation(&fixture.request), Ok(None));
    assert_eq!(
        reopened.execute_generation(&fixture.config.manifest, &fixture.request),
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(
        reopened.execute_generation(&fixture.config.manifest, &next),
        Err(CellGenerationErrorV2::Capacity)
    );
    assert_eq!(worker.calls.load(Ordering::Acquire), 1);
    checked(reopened.shutdown());
}

#[test]
fn shutdown_timeout_retains_the_real_file_lock_until_the_worker_exits() {
    let mut fixture = Fixture::new();
    fixture.config.rpc_timeout = Duration::from_millis(50);
    let worker = FixtureWorker::new(WorkerMode::Held);
    let mut port = fixture.port(Arc::clone(&worker), Arc::new(|| 20));
    let submitted = port.execute_generation(&fixture.config.manifest, &fixture.request);
    assert!(matches!(
        submitted,
        Err(CellGenerationErrorV2::Pending | CellGenerationErrorV2::CommitUncertain)
    ));
    wait_until(|| worker.calls.load(Ordering::Acquire) == 1);
    assert_eq!(port.shutdown(), Err(CellGenerationErrorV2::CommitUncertain));
    assert!(!port.is_closed());
    assert!(matches!(
        DurableInferenceControl::open(fixture.path(), /*capacity*/ 32),
        Err(ControlError::WriterUnavailable)
    ));
    worker.release.store(true, Ordering::Release);
    wait_until(|| port.is_closed());
    checked(port.shutdown());
    let control = checked(DurableInferenceControl::open(
        fixture.path(),
        /*capacity*/ 32,
    ));
    let (binding, _) = checked(prepare(&fixture.config, &fixture.request));
    let record = checked(checked(control.generation_record(&binding)).ok_or("record"));
    assert!(record.cancel_requested);
    assert!(record.result.is_some());
}

#[test]
fn invalid_scope_and_invalid_worker_proposals_never_become_terminal_records() {
    for mode in [WorkerMode::WrongIdentity, WorkerMode::Oversized] {
        let fixture = Fixture::new();
        let worker = FixtureWorker::new(mode);
        worker.release.store(true, Ordering::Release);
        let mut port = fixture.port(Arc::clone(&worker), Arc::new(|| 20));
        let mut wrong = fixture.request.clone();
        wrong.predecessor.scope.agent_id = "different".into();
        assert_eq!(
            port.execute_generation(&fixture.config.manifest, &wrong),
            Err(CellGenerationErrorV2::InvalidBinding)
        );
        assert_eq!(checked(fs::read(fixture.path())), Vec::<u8>::new());
        assert_eq!(worker.calls.load(Ordering::Acquire), 0);
        assert_eq!(
            port.execute_generation(&fixture.config.manifest, &fixture.request),
            Err(CellGenerationErrorV2::Pending)
        );
        let failure = if matches!(mode, WorkerMode::Oversized) {
            CellGenerationErrorV2::Capacity
        } else {
            CellGenerationErrorV2::InvalidBinding
        };
        wait_until(|| port.read_generation(&fixture.request) == Err(failure.clone()));
        checked(port.shutdown());
        let control = checked(DurableInferenceControl::open(
            fixture.path(),
            /*capacity*/ 32,
        ));
        let (binding, _) = checked(prepare(&fixture.config, &fixture.request));
        assert!(
            checked(checked(control.generation_record(&binding)).ok_or("record"))
                .result
                .is_none()
        );
    }
}

#[test]
fn known_no_contact_observations_abort_without_forging_the_admission_clock() {
    for (admission, dispatch, disposition) in [
        (20, 101, CellGenerationDispositionV2::DeadlineExceeded),
        (101, 101, CellGenerationDispositionV2::DeadlineExceeded),
        (9, 20, CellGenerationDispositionV2::Failed),
    ] {
        let fixture = Fixture::new();
        let worker = FixtureWorker::new(WorkerMode::Cooperative);
        let calls = AtomicUsize::new(0);
        let clock: Clock = Arc::new(move || {
            if calls.fetch_add(1, Ordering::SeqCst) == 0 {
                admission
            } else {
                dispatch
            }
        });
        let mut port = fixture.port(Arc::clone(&worker), clock);
        let proposal = checked(port.execute_generation(&fixture.config.manifest, &fixture.request));
        assert_eq!(proposal.disposition, disposition);
        assert_eq!(proposal.successor_state, fixture.request.predecessor.state);
        assert!(proposal.output_delta.is_empty());
        assert_eq!(proposal.cost.entries().len(), 2);
        assert!(
            proposal
                .cost
                .entries()
                .iter()
                .all(|entry| entry.metrics.wall_micros.is_some()
                    && entry.metrics.cpu_micros.is_none())
        );
        assert_eq!(worker.calls.load(Ordering::Acquire), 0);
        checked(port.shutdown());
        let control = checked(DurableInferenceControl::open(
            fixture.path(),
            /*capacity*/ 32,
        ));
        let (binding, _) = checked(prepare(&fixture.config, &fixture.request));
        let record = checked(checked(control.generation_record(&binding)).ok_or("record"));
        assert_eq!(record.admitted_at_micros, admission);
        assert_eq!(record.dispatched_at_micros, None);
        assert!(record.aborted_before_dispatch);
        assert_eq!(
            checked(serde_json::from_slice::<CellGenerationProposalV2>(
                &checked(record.result.as_ref().ok_or("result")).bytes
            )),
            proposal
        );
    }
}

#[test]
fn actor_loss_closes_the_owner_without_reissuing_an_uncertain_operation() {
    let fixture = Fixture::new();
    let worker = FixtureWorker::new(WorkerMode::Cooperative);
    let calls = AtomicUsize::new(0);
    let clock: Clock = Arc::new(move || {
        assert_eq!(
            calls.fetch_add(1, Ordering::SeqCst),
            0,
            "simulated actor loss after admission"
        );
        20
    });
    let mut port = fixture.port(Arc::clone(&worker), clock);
    assert_eq!(
        port.execute_generation(&fixture.config.manifest, &fixture.request),
        Err(CellGenerationErrorV2::Unavailable)
    );
    wait_until(|| port.is_closed());
    assert_eq!(port.shutdown(), Err(CellGenerationErrorV2::Unavailable));
    drop(port);
    let mut reopened = fixture.port(Arc::clone(&worker), Arc::new(|| 20));
    assert_eq!(reopened.read_generation(&fixture.request), Ok(None));
    assert_eq!(
        reopened.execute_generation(&fixture.config.manifest, &fixture.request),
        Err(CellGenerationErrorV2::Pending)
    );
    let mut next = fixture.request.clone();
    next.operation_id = "second".into();
    assert_eq!(
        reopened.execute_generation(&fixture.config.manifest, &next),
        Err(CellGenerationErrorV2::Capacity)
    );
    assert_eq!(worker.calls.load(Ordering::Acquire), 0);
    checked(reopened.shutdown());
}
