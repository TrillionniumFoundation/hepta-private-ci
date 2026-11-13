//! Actual original control journals; the worker is an explicit lifecycle
//! fixture. Native numerical/measurement coverage lives with the Q24 worker.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;
use crate::CellStateOwnerV1;
use crate::cell_test_support::Encoder;
use crate::cell_test_support::checked;
use crate::cell_test_support::definition;
use crate::cell_test_support::input;
use crate::cell_test_support::owner;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    directory: PathBuf,
    binding: NeuronFeatureControlBindingV1,
    admission: CellInferenceAdmissionV1,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let directory = std::env::temp_dir().join(format!(
            "hepta-feature-control-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&directory));
        let input = input("ordinary");
        let snapshot = checked(owner(&["ordinary"]).snapshot(&input.scope));
        let admission = admission(&input, snapshot);
        let binding = checked(NeuronFeatureControlBindingV1::from_admission(
            &definition(),
            &admission,
            /*worker_generation*/ 1,
        ));
        Self {
            directory,
            binding,
            admission,
        }
    }

    fn path(&self) -> PathBuf {
        self.directory.join("original-control.log")
    }

    fn port(
        &self,
        mode: Mode,
        calls: Arc<AtomicUsize>,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> ControlledNeuronFeaturePortV1<Worker> {
        let mut port = checked(ControlledNeuronFeaturePortV1::new(
            checked(DurableInferenceControl::open(
                self.path(),
                /*capacity*/ 4,
            )),
            definition(),
            /*worker_generation*/ 1,
            Worker {
                runtime: self.binding.runtime.clone(),
                mode,
                calls,
            },
            clock,
        ));
        checked(port.bind_cell_inference(&self.admission));
        port
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn admission(
    input: &crate::CellStepInputV1,
    snapshot: crate::CellOwnerSnapshotV1,
) -> CellInferenceAdmissionV1 {
    let prepared = checked(crate::cell::prepare_from_snapshot(
        &definition(),
        snapshot,
        &Encoder,
        input.clone(),
        input.monotonic_micros,
        crate::cell::CellPreparationModeV1::AdmittedRecovery,
    ));
    checked(crate::cell_inference::admission_for_step(
        &prepared,
        input.monotonic_micros,
    ))
}

#[derive(Clone, Copy)]
enum Mode {
    Success,
    Unknown,
}

struct Worker {
    runtime: NeuronModelRuntimeTupleV1,
    mode: Mode,
    calls: Arc<AtomicUsize>,
}

impl NeuronFeatureWorkerV1 for Worker {
    fn runtime_tuple(&self) -> &NeuronModelRuntimeTupleV1 {
        &self.runtime
    }

    fn execute(
        &self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureObservationV1, NeuronModelError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if matches!(self.mode, Mode::Unknown) {
            return Err(NeuronModelError::Indeterminate);
        }
        Ok(NeuronFeatureObservationV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            drive_q24: vec![1; request.expected_output_width],
            prediction_q24: vec![2; request.expected_output_width],
            observed_memory_bytes: 13,
            transient_allocation_bytes: 17,
            queue_age_micros: 19,
            latency_micros: 23,
            status: NeuronFeatureTerminalStatusV1::Succeeded,
        })
    }
}

#[test]
fn feature_control_exact_readback_reopens_without_work_clock_or_write() {
    let fixture = Fixture::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let request = fixture.binding.expected.clone();
    let mut port = fixture.port(Mode::Success, Arc::clone(&calls), Arc::new(|| 11));
    assert_eq!(checked(port.read_feature(&request)), None);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(checked(fs::metadata(fixture.path())).len(), 0);
    let receipt = checked(port.execute_feature(&request));
    assert_eq!(checked(port.execute_feature(&request)), receipt);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(port);
    let original_bytes = checked(fs::read(fixture.path()));
    let mut recovered = fixture.port(
        Mode::Unknown,
        Arc::clone(&calls),
        Arc::new(|| panic!("recovery sampled the live clock")),
    );
    checked(recovered.bind_cell_readback(&fixture.admission));
    assert_eq!(
        checked(recovered.read_feature(&request)),
        Some(receipt.clone())
    );
    assert_eq!(checked(recovered.execute_feature(&request)), receipt);
    assert_eq!(checked(fs::read(fixture.path())), original_bytes);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn feature_control_unknown_dispatch_remains_fenced_after_reopen() {
    let mut fixture = Fixture::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let request = fixture.binding.expected.clone();
    let mut port = fixture.port(Mode::Unknown, Arc::clone(&calls), Arc::new(|| 11));
    assert_eq!(
        port.execute_feature(&request),
        Err(NeuronModelError::Indeterminate)
    );
    drop(port);
    let pending_bytes = checked(fs::read(fixture.path()));
    let mut recovered = fixture.port(
        Mode::Success,
        Arc::clone(&calls),
        Arc::new(|| panic!("pending recovery sampled clock")),
    );
    assert_eq!(checked(recovered.read_feature(&request)), None);
    assert_eq!(
        recovered.execute_feature(&request),
        Err(NeuronModelError::Indeterminate)
    );
    drop(recovered);
    let mut changed = input("ordinary");
    changed.operation_id = checked(codex_hepta_types::StableId::new("another-operation"));
    fixture.admission = admission(
        &changed,
        checked(owner(&["ordinary"]).snapshot(&changed.scope)),
    );
    fixture.binding = checked(NeuronFeatureControlBindingV1::from_admission(
        &definition(),
        &fixture.admission,
        /*worker_generation*/ 1,
    ));
    let request = fixture.binding.expected.clone();
    let mut fresh = fixture.port(Mode::Success, Arc::clone(&calls), Arc::new(|| 11));
    assert_eq!(
        fresh.execute_feature(&request),
        Err(NeuronModelError::Indeterminate)
    );
    assert_eq!(checked(fs::read(fixture.path())), pending_bytes);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn feature_control_dispatch_fsync_deadline_and_late_result_keep_original_cost() {
    let fixture = Fixture::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let request = fixture.binding.expected.clone();
    let counter = Arc::new(AtomicU64::new(11));
    let clock_counter = Arc::clone(&counter);
    let mut port = fixture.port(
        Mode::Success,
        Arc::clone(&calls),
        Arc::new(move || clock_counter.fetch_add(45, Ordering::SeqCst)),
    );
    assert_eq!(
        port.execute_feature(&request),
        Err(NeuronModelError::Indeterminate)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(checked(port.read_feature(&request)), None);
    let record = checked(port.owner.generation_record(&fixture.binding.journal));
    assert_eq!(
        record.and_then(|record| record.dispatched_at_micros),
        Some(56)
    );
    drop(port);

    let fixture = Fixture::new();
    let request = fixture.binding.expected.clone();
    let counter = Arc::new(AtomicU64::new(11));
    let mut port = fixture.port(
        Mode::Success,
        Arc::clone(&calls),
        Arc::new(move || counter.fetch_add(30, Ordering::SeqCst)),
    );
    let receipt = checked(port.execute_feature(&request));
    assert_eq!(receipt.status, NeuronFeatureTerminalStatusV1::Cancelled);
    assert!(receipt.drive_q24.is_empty() && receipt.prediction_q24.is_empty());
    assert_eq!(
        (
            receipt.observed_memory_bytes,
            receipt.transient_allocation_bytes,
            receipt.latency_micros
        ),
        (13, 17, 23)
    );
    assert!(receipt.queue_age_micros >= 19);
    assert_eq!(checked(port.read_feature(&request)), Some(receipt));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn feature_control_same_operation_changed_source_or_state_never_rebinds() {
    let mut fixture = Fixture::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let request = fixture.binding.expected.clone();
    let mut port = fixture.port(Mode::Success, Arc::clone(&calls), Arc::new(|| 11));
    let mut alias = request.clone();
    alias.input_digest = Digest32::of_bytes(b"changed-source");
    assert_eq!(
        port.execute_feature(&alias),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(checked(fs::metadata(fixture.path())).len(), 0);
    let receipt = checked(port.execute_feature(&request));
    let mut corrupted = checked(codec::encode(&receipt));
    let last = corrupted.len() - 2;
    corrupted[last] = b'2';
    assert_eq!(
        codec::decode(&request, &fixture.binding.runtime, &corrupted),
        Err(NeuronModelError::Indeterminate)
    );
    drop(port);
    let original_bytes = checked(fs::read(fixture.path()));
    let mut changed = input("ordinary");
    changed.observation.push(1);
    let mut snapshot = checked(owner(&["ordinary"]).snapshot(&changed.scope));
    snapshot.revision += 1;
    fixture.admission = admission(&changed, snapshot);
    fixture.binding = checked(NeuronFeatureControlBindingV1::from_admission(
        &definition(),
        &fixture.admission,
        /*worker_generation*/ 1,
    ));
    let alias = fixture.binding.expected.clone();
    assert_eq!(alias.request_id, request.request_id);
    let mut port = fixture.port(Mode::Success, Arc::clone(&calls), Arc::new(|| 11));
    assert_eq!(
        port.read_feature(&alias),
        Err(NeuronModelError::Indeterminate)
    );
    assert_eq!(
        port.execute_feature(&alias),
        Err(NeuronModelError::Indeterminate)
    );
    assert_eq!(checked(fs::read(fixture.path())), original_bytes);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn feature_control_original_cell_path_binds_admission_and_pending_recovery() {
    let fixture = Fixture::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let open = |clock: Arc<dyn Fn() -> u64 + Send + Sync>| {
        checked(ControlledNeuronFeaturePortV1::new(
            checked(DurableInferenceControl::open(
                fixture.path(),
                /*capacity*/ 4,
            )),
            definition(),
            /*worker_generation*/ 1,
            Worker {
                runtime: fixture.binding.runtime.clone(),
                mode: Mode::Success,
                calls: Arc::clone(&calls),
            },
            clock,
        ))
    };
    let mut port = open(Arc::new(|| 11));
    assert_eq!(
        port.read_feature(&fixture.binding.expected),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(
        port.execute_feature(&fixture.binding.expected),
        Err(NeuronModelError::Rejected)
    );
    let mut cell_owner = owner(&["ordinary"]);
    let prepared = checked(crate::prepare_cell_step(
        &definition(),
        &cell_owner,
        &Encoder,
        input("ordinary"),
        /*now_micros*/ 10,
    ));
    let original = checked(crate::infer_cell_with_clock(
        prepared,
        &mut cell_owner,
        &mut port,
        || 11,
    ));
    assert!(checked(cell_owner.pending_inference(&input("ordinary").scope)).is_some());
    drop(port);
    let bytes = checked(fs::read(fixture.path()));
    let mut recovered = open(Arc::new(|| {
        panic!("original pending readback sampled clock")
    }));
    let reopened = checked(crate::recover_cell_inference(
        &definition(),
        &cell_owner,
        &Encoder,
        input("ordinary"),
        &mut recovered,
        /*now_micros*/ 200,
    ));
    assert_eq!(reopened.output, original.output);
    assert_eq!(checked(fs::read(fixture.path())), bytes);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}
