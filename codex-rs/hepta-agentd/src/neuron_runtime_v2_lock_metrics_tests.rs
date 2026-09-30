use super::*;

use std::collections::BTreeMap;
use std::sync::Barrier;
use std::sync::atomic::AtomicUsize;
use std::thread;
use std::time::Duration;

use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_intelligence::CanonicalPortInputV1;
use codex_hepta_intelligence::CanonicalStageV1;
use codex_hepta_neuron::FileNeuronWitnessStoreV2;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronBodyBundleIdentityV1;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronGenerationStoreContextV2;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeIndexContextV2;
use codex_hepta_neuron::NeuronWitnessContextV2;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::Generation;
use serde_json::json;
use tempfile::TempDir;

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn native_config(generation: Generation) -> SparseConfig {
    SparseConfig {
        model_digest: digest("lock-metrics-head"),
        normalization_digest: digest("lock-metrics-normalization"),
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: Vec::new(),
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn runtime_config(native: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: id("lock.metrics.config"),
        generation: native.generation,
        model_id: id("lock.metrics.model"),
        model_manifest_digest: digest("manifest"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 64,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 100_000,
            maximum_ood_ppm: 900_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 5_000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 10_000_000,
            p99_latency_micros: 30_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    }
}

fn body_bundle(generation: Generation) -> NeuronBodyBundleIdentityV1 {
    NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest("body-manifest"),
        body_generation: generation,
        base_bundle_digest: digest("base-bundle"),
        organ_id: id("organ.reasoning"),
        organ_bundle_digest: digest("organ-bundle"),
        cell_slot_id: Some(id("cell.lock.metrics")),
        cell_bundle_digest: Some(digest("cell-bundle")),
        effective_parameter_digest: digest("effective-parameters"),
        source_revision_digest: digest("source-revision"),
    }
}

fn subject() -> StableId {
    id("lock.metrics.subject")
}

fn objective() -> Digest32 {
    digest("lock.metrics.objective")
}

fn scope() -> JournalScope {
    let subject = subject();
    let raw = subject.as_str().as_bytes();
    JournalScope {
        scope_digest: Digest32::of_parts(&[
            b"hepta.neuron.subject-scope.v1",
            &(raw.len() as u32).to_be_bytes(),
            raw,
        ]),
        objective_digest: objective(),
    }
}

fn contexts(
    native: &SparseConfig,
    config: &NeuronRuntimeConfigV1,
    body: &NeuronBodyBundleIdentityV1,
) -> (NeuronGenerationStoreContextV2, NeuronRuntimeIndexContextV2) {
    let config_digest = checked(config.semantic_digest());
    let body_digest = checked(body.semantic_digest());
    (
        NeuronGenerationStoreContextV2 {
            generation: native.generation,
            scope: scope(),
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 16,
            max_pending_witness: 16,
            max_checkpoint_bytes: 256 * 1024,
            max_full_receipt_bytes: 256 * 1024,
            max_file_bytes: 8 * 1024 * 1024,
            max_startup_replay_bytes: 8 * 1024 * 1024,
        },
        NeuronRuntimeIndexContextV2 {
            generation: native.generation,
            scope: scope(),
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 16,
            max_file_bytes: 1024 * 1024,
            max_startup_replay_bytes: 1024 * 1024,
        },
    )
}

fn input(generation: u64) -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: id(&format!("lock.metrics.tick.{generation}")),
        subject_id: subject(),
        logical_sequence: 1,
        monotonic_time_micros: 1_000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: codex_hepta_neuron::canonical_feature_vector_digest_v1(
            &feature_vector_q24,
        ),
        feature_vector_q24,
        objective_digest: objective(),
        ndu_snapshot_digest: digest("lock.metrics.ndu"),
        body_generation: Some(generation),
        modulator_digest: None,
    }
}

#[derive(Clone, Copy)]
struct Allow;

impl NeuronAdmissionGuard for Allow {
    fn check(
        &mut self,
        _config: &NeuronRuntimeConfigV1,
        _input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Ok(())
    }
}

struct DelayedFileWitness {
    inner: FileNeuronWitnessStoreV2,
    delay: Duration,
}

impl DelayedFileWitness {
    fn delay(&self) {
        if !self.delay.is_zero() {
            thread::sleep(self.delay);
        }
    }
}

impl AnchorWitnessStore for DelayedFileWitness {
    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        self.delay();
        self.inner.admit_new_anchor(expected)
    }

    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.delay();
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.delay();
        self.inner.compare_and_swap(expected, next)
    }
}

struct SlowControl {
    delay: Duration,
    calls: Arc<AtomicUsize>,
    started: Arc<AtomicBool>,
}

impl NeuronInferenceControlPort for SlowControl {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.started.store(true, Ordering::SeqCst);
        if !self.delay.is_zero() {
            thread::sleep(self.delay);
        }
        build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: digest("manifest"),
                weights_digest: request.weights_digest,
                tokenizer_digest: digest("tokenizer"),
                preprocessor_digest: digest("preprocessor"),
                quantization_digest: digest("quantization"),
                runtime_digest: digest("runtime"),
                device_digest: digest("device"),
            },
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24: vec![Q, 0, 0, 0, 0],
                prediction_q24: vec![0; request.expected_output_width],
                observed_memory_bytes: 8192,
                transient_allocation_bytes: 1024,
                queue_age_micros: 2,
                latency_micros: u64::try_from(self.delay.as_micros()).unwrap_or(u64::MAX),
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Indeterminate)
    }
}

impl DurableNeuronInferenceControlPort for SlowControl {}

struct RuntimeFixture {
    _root: TempDir,
    handle: AgentdNeuronHandleV2,
    invocation: AgentdNeuronInvocationV2,
    input: NeuronTickInputV1,
    canonical: CanonicalPortInputV1,
    calls: Arc<AtomicUsize>,
    started: Arc<AtomicBool>,
}

fn runtime_fixture(
    generation_value: u64,
    provider_delay: Duration,
    witness_delay: Duration,
) -> RuntimeFixture {
    let root = checked(TempDir::new());
    let generation = checked(Generation::new(generation_value));
    let native = native_config(generation);
    let config = runtime_config(&native);
    let body = body_bundle(generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness_context = NeuronWitnessContextV2 {
        generation,
        scope: scope(),
        key_epoch: 1,
        deletion_epoch: 1,
        max_records: 16,
    };
    let witness_path = root.path().join("witness.hptnwv02");
    let store_path = root.path().join("generation.hptngs02");
    let index_path = root.path().join("runtime-index.hptngi02");
    let witness = DelayedFileWitness {
        inner: checked(FileNeuronWitnessStoreV2::create(
            &witness_path,
            witness_context,
        )),
        delay: witness_delay,
    };
    let runtime = checked(NeuronRuntimeV2::bootstrap(
        &store_path,
        &index_path,
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(AtomicBool::new(false));
    let owner = AgentdNeuronOwnerV2::new(
        runtime,
        SlowControl {
            delay: provider_delay,
            calls: Arc::clone(&calls),
            started: Arc::clone(&started),
        },
    );
    let handle = checked(owner.into_shared(Allow));
    let input = input(generation_value);
    let body_digest = handle.body_bundle_digest().expect("body digest");
    let invocation = checked(handle.prepare(
        input.tick_id.clone(),
        body_digest,
        input.clone(),
    ));
    let canonical = CanonicalPortInputV1 {
        run_id: input.tick_id.clone(),
        snapshot_digest: digest("lock.metrics.snapshot"),
        objective_digest: input.objective_digest,
        candidate_set_digest: digest("lock.metrics.candidates"),
        predecessor_digest: input.ndu_snapshot_digest,
        budget_micros: 30_000_000,
        stage: CanonicalStageV1::NeuralSignalCollected,
    };
    RuntimeFixture {
        _root: root,
        handle,
        invocation,
        input,
        canonical,
        calls,
        started,
    }
}

#[derive(Debug)]
struct MatrixRow {
    scenario: &'static str,
    concurrency: usize,
    latencies: Vec<u64>,
    outcomes: BTreeMap<String, u64>,
    counters: Option<AgentdNeuronOperationalCountersV2>,
    provider_calls: Option<usize>,
}

fn outcome_code<T, E: std::fmt::Debug>(result: &Result<T, E>) -> String {
    match result {
        Ok(_) => "success".to_owned(),
        Err(error) => format!("{error:?}"),
    }
}

fn percentile(values: &[u64], percent: usize) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let rank = percent
        .saturating_mul(sorted.len())
        .saturating_add(99)
        .saturating_div(100)
        .max(1);
    sorted[rank.saturating_sub(1).min(sorted.len() - 1)]
}

fn emit(row: MatrixRow) {
    eprintln!(
        "HEPTA_NEURON_HOL {}",
        json!({
            "schema": "hepta.neuron.runtime.hol-measurement.v1",
            "scenario": row.scenario,
            "concurrency": row.concurrency,
            "samples": row.latencies.len(),
            "latencyMicros": {
                "p50": percentile(&row.latencies, 50),
                "p95": percentile(&row.latencies, 95),
                "p99": percentile(&row.latencies, 99),
                "max": row.latencies.iter().copied().max().unwrap_or(0),
            },
            "outcomes": row.outcomes,
            "ownerCounters": row.counters,
            "providerCalls": row.provider_calls,
            "productionActivation": false,
        })
    );
}

fn execute_matrix_row(
    scenario: &'static str,
    concurrency: usize,
    provider_delay: Duration,
    witness_delay: Duration,
) -> MatrixRow {
    let fixture = runtime_fixture(1, provider_delay, witness_delay);
    let barrier = Arc::new(Barrier::new(concurrency));
    let mut threads = Vec::with_capacity(concurrency);
    for _ in 0..concurrency {
        let barrier = Arc::clone(&barrier);
        let invocation = fixture.invocation.clone();
        let canonical = fixture.canonical.clone();
        threads.push(thread::spawn(move || {
            barrier.wait();
            let started = Instant::now();
            let mut allow = Allow;
            let result = invocation.execute(&canonical, &mut allow);
            (elapsed_micros(started), outcome_code(&result))
        }));
    }
    let mut latencies = Vec::with_capacity(concurrency);
    let mut outcomes = BTreeMap::new();
    for thread in threads {
        let (latency, outcome) = thread.join().expect("worker thread");
        latencies.push(latency);
        *outcomes.entry(outcome).or_insert(0) += 1;
    }
    MatrixRow {
        scenario,
        concurrency,
        latencies,
        outcomes,
        counters: Some(fixture.handle.operational_counters()),
        provider_calls: Some(fixture.calls.load(Ordering::SeqCst)),
    }
}

fn recovery_wave_row(concurrency: usize, recovery_percent: usize) -> MatrixRow {
    let fixture = runtime_fixture(1, Duration::from_millis(100), Duration::ZERO);
    let invocation = fixture.invocation.clone();
    let canonical = fixture.canonical.clone();
    let execute_thread = thread::spawn(move || {
        let mut allow = Allow;
        invocation.execute(&canonical, &mut allow)
    });
    let wait_started = Instant::now();
    while !fixture.started.load(Ordering::SeqCst) {
        assert!(
            wait_started.elapsed() < Duration::from_secs(5),
            "provider did not start"
        );
        thread::yield_now();
    }

    let recovery_count = concurrency
        .saturating_mul(recovery_percent)
        .saturating_add(99)
        .saturating_div(100)
        .max(1)
        .min(concurrency);
    let barrier = Arc::new(Barrier::new(concurrency));
    let mut threads = Vec::with_capacity(concurrency);
    for index in 0..concurrency {
        let barrier = Arc::clone(&barrier);
        let handle = fixture.handle.clone();
        let input = fixture.input.clone();
        threads.push(thread::spawn(move || {
            barrier.wait();
            let started = Instant::now();
            let outcome = if index < recovery_count {
                outcome_code(&handle.recover_operation(&input))
            } else {
                outcome_code(&handle.query_input_operation(&input))
            };
            (elapsed_micros(started), outcome)
        }));
    }
    let mut latencies = Vec::with_capacity(concurrency);
    let mut outcomes = BTreeMap::new();
    for thread in threads {
        let (latency, outcome) = thread.join().expect("recovery worker");
        latencies.push(latency);
        *outcomes.entry(outcome).or_insert(0) += 1;
    }
    let execution = execute_thread.join().expect("execute thread");
    assert!(execution.is_ok(), "holder execution failed: {execution:?}");
    MatrixRow {
        scenario: match recovery_percent {
            10 => "recovery_wave_10_percent",
            50 => "recovery_wave_50_percent",
            100 => "recovery_wave_100_percent",
            _ => "recovery_wave",
        },
        concurrency,
        latencies,
        outcomes,
        counters: Some(fixture.handle.operational_counters()),
        provider_calls: Some(fixture.calls.load(Ordering::SeqCst)),
    }
}

struct MatrixOwner {
    generation: u64,
    query_delay: Duration,
    reconcile_delay: Duration,
}

impl ProductNeuronOwnerV2 for MatrixOwner {
    fn execute(
        &self,
        _input: NeuronTickInputV1,
        _guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
        if !self.reconcile_delay.is_zero() {
            thread::sleep(self.reconcile_delay);
        }
        Ok(())
    }

    fn query_operation(
        &self,
        _tick_id: &StableId,
        _input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        if !self.query_delay.is_zero() {
            thread::sleep(self.query_delay);
        }
        Ok(NeuronOperationStatusV2::NotRecorded)
    }

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        let storage = || codex_hepta_neuron::NeuronStorageCapacityV2 {
            records: 0,
            record_limit: 16,
            file_bytes: 0,
            byte_limit: 1024 * 1024,
            reserved_bytes: 0,
        };
        Ok(NeuronRuntimeCapacityV2 {
            generation: storage(),
            index: storage(),
            witness_records_remaining: Some(16),
        })
    }

    fn generation(&self) -> Option<u64> {
        Some(self.generation)
    }

    fn body_bundle_digest(&self) -> Option<Digest32> {
        Some(digest(&format!("matrix-body-{}", self.generation)))
    }
}

fn matrix_handle(
    generation: u64,
    query_delay: Duration,
    reconcile_delay: Duration,
) -> AgentdNeuronHandleV2 {
    AgentdNeuronHandleV2 {
        owner: Arc::new(MatrixOwner {
            generation,
            query_delay,
            reconcile_delay,
        }),
        config_digest: digest(&format!("matrix-config-{generation}")),
        lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
    }
}

fn controller_row(scenario: &'static str, concurrency: usize) -> MatrixRow {
    let first = matrix_handle(1, Duration::from_millis(5), Duration::from_millis(5));
    let retained_clone = first.clone();
    let controller = Arc::new(checked(AgentdNeuronGenerationControllerV2::new(first)));
    checked(controller.start());

    if scenario == "reload_query_concurrency" {
        checked(controller.begin_quiesce());
        checked(controller.seal());
    } else if scenario == "historical_reference_retention" {
        checked(controller.begin_quiesce());
        checked(controller.seal());
        checked(controller.reload(matrix_handle(
            2,
            Duration::from_millis(5),
            Duration::from_millis(5),
        )));
    }

    let barrier = Arc::new(Barrier::new(concurrency));
    let mut threads = Vec::with_capacity(concurrency);
    for index in 0..concurrency {
        let barrier = Arc::clone(&barrier);
        let controller = Arc::clone(&controller);
        let retained = retained_clone.clone();
        threads.push(thread::spawn(move || {
            barrier.wait();
            let started = Instant::now();
            let result_code = match scenario {
                "reload_query_concurrency" => {
                    if index == 0 {
                        outcome_code(&controller.reload(matrix_handle(
                            2,
                            Duration::from_millis(5),
                            Duration::from_millis(5),
                        )))
                    } else {
                        outcome_code(&controller.query_operation(
                            1,
                            &id("matrix.query"),
                            digest("matrix.input"),
                        ))
                    }
                }
                "status_drain_mutation_concurrency" => match index % 4 {
                    0 => outcome_code(&controller.state()),
                    1 => outcome_code(&controller.controller_snapshot()),
                    2 => outcome_code(&controller.query_operation(
                        1,
                        &id("matrix.query"),
                        digest("matrix.input"),
                    )),
                    _ => outcome_code(&controller.begin_quiesce()),
                },
                "historical_reference_retention" => {
                    if index % 2 == 0 {
                        outcome_code(&retained.prepare(
                            id("historical.run"),
                            retained.body_bundle_digest().expect("historical body"),
                            input(1),
                        ))
                    } else {
                        outcome_code(&controller.query_operation(
                            1,
                            &id("matrix.query"),
                            digest("matrix.input"),
                        ))
                    }
                }
                _ => unreachable!(),
            };
            (elapsed_micros(started), result_code)
        }));
    }
    let mut latencies = Vec::with_capacity(concurrency);
    let mut outcomes = BTreeMap::new();
    for thread in threads {
        let (latency, outcome) = thread.join().expect("controller worker");
        latencies.push(latency);
        *outcomes.entry(outcome).or_insert(0) += 1;
    }
    MatrixRow {
        scenario,
        concurrency,
        latencies,
        outcomes,
        counters: None,
        provider_calls: None,
    }
}

#[test]
fn owner_lock_metrics_observe_contention_and_hold_time() {
    let row = execute_matrix_row(
        "owner_lock_regression",
        32,
        Duration::from_millis(30),
        Duration::ZERO,
    );
    let counters = row.counters.expect("owner counters");
    assert_eq!(counters.owner_lock_attempts, 32);
    assert_eq!(
        counters.owner_lock_attempts,
        counters
            .owner_lock_acquired
            .saturating_add(counters.owner_busy_rejections)
            .saturating_add(counters.owner_poisoned_failures)
    );
    assert!(counters.owner_lock_acquired >= 1);
    assert!(counters.owner_busy_rejections >= 1);
    assert!(counters.owner_lock_hold_micros_total > 0);
    assert!(counters.owner_lock_hold_micros_max > 0);
    assert!(counters.owner_lock_hold_micros_max <= counters.owner_lock_hold_micros_total);
    assert_eq!(row.provider_calls, Some(1));
}

#[test]
#[ignore = "diagnostic matrix; retained by the Neuron HOL workflow, not a release authorization"]
fn neuron_runtime_v2_hol_diagnostic_matrix() {
    for concurrency in [1, 8, 32, 128, 256] {
        emit(execute_matrix_row(
            "healthy_provider",
            concurrency,
            Duration::ZERO,
            Duration::ZERO,
        ));
        emit(execute_matrix_row(
            "slow_provider",
            concurrency,
            Duration::from_millis(20),
            Duration::ZERO,
        ));
        emit(execute_matrix_row(
            "slow_filesystem",
            concurrency,
            Duration::ZERO,
            Duration::from_millis(20),
        ));
        for recovery_percent in [10, 50, 100] {
            emit(recovery_wave_row(concurrency, recovery_percent));
        }
        emit(controller_row("reload_query_concurrency", concurrency));
        emit(controller_row(
            "status_drain_mutation_concurrency",
            concurrency,
        ));
        emit(controller_row(
            "historical_reference_retention",
            concurrency,
        ));
    }
}
