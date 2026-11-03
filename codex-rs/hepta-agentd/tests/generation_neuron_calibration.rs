//! Actual feature owner execution with a frozen, failed calibration profile.
//! This test must observe native rejection. It never replaces measured values
//! by fixture constants to obtain an admitted neuron or activate the daemon.
#![allow(clippy::expect_used, reason = "explicit integration assertions")]

use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::Duration;

use codex_hepta_infer_core::GenerationModelPinsV1;
use codex_hepta_infer_core::GenerationRequestV1;
use codex_hepta_infer_core::GenerationStateV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::InferenceRequest;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_infer_core::generation_json_digest;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_infer_worker_host::generation_driver::GenerationDriver;
use codex_hepta_infer_worker_host::generation_driver::GenerationRegistrationV1;
use codex_hepta_infer_worker_host::generation_driver::neuron::GenerationNeuronBindingV1;
use codex_hepta_infer_worker_host::generation_driver::neuron::generation_neuron_head_digest;
use codex_hepta_infer_worker_host::generation_driver::neuron::generation_projection_digest;
use codex_hepta_infer_worker_host::generation_driver::neuron::project_generation_state;
use codex_hepta_infer_worker_host::model_worker::InferenceWorker;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::NeuronFeatureRequest;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_infer_worker_host::model_worker::canonical_neuron_feature_payload_digest;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Fixture {
    repository: PathBuf,
    python: PathBuf,
    artifact_root: PathBuf,
    checkpoint_name: String,
    model_id: String,
    pins: GenerationModelPinsV1,
    request: GenerationRequestV1,
    previous_state: GenerationStateV1,
    expected_drive_q24: Vec<i64>,
    expected_prediction_q24: Vec<i64>,
    expected_png_sha256: String,
    expected_text_sha256: String,
    calibration_directory: PathBuf,
    specification_sha256: String,
    calibration_summary_sha256: String,
    calibration_rows_sha256: String,
}

fn digest(value: &str) -> Digest32 {
    Digest32::from_str(value).expect("digest")
}
fn id(value: &str) -> StableId {
    StableId::new(value).expect("identity")
}
fn u32_field(value: &Value, key: &str) -> u32 {
    u32::try_from(value[key].as_u64().expect("measured unsigned integer")).expect("u32")
}

struct OwnerPort {
    control: DurableInferenceControl,
    worker: InferenceWorker<GenerationDriver>,
    expected: NeuronFeatureRequestV1,
    prepared: NeuronFeatureRequest,
    manifest: ModelManifest,
    cached: Option<NeuronFeatureReceiptV1>,
}

impl NeuronInferenceControlPort for OwnerPort {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        if request != &self.expected {
            return Err(NeuronModelError::Rejected);
        }
        if let Some(receipt) = &self.cached {
            return Ok(receipt.clone());
        }
        let auth = &self.prepared.authorization;
        let submitted = self
            .control
            .submit(
                /*now_ms*/ 100,
                InferenceRequest {
                    request_id: auth.request_id.clone(),
                    principal_id: "qualification.host".into(),
                    model_digest: auth.model_digest.clone(),
                    payload_digest: auth.payload_digest.clone(),
                    maximum_tokens: 8,
                    deadline_ms: auth.deadline_ms,
                    semantic_digest: request.input_digest.to_string(),
                },
            )
            .map_err(|_| NeuronModelError::Rejected)?;
        let reservation = Reservation {
            reservation_id: auth.reservation_id.clone(),
            quota_units: 65_000_000_000,
            maximum_tokens: 8,
            authority_epoch: 1,
            valid_until_ms: 90_000,
        };
        assert!(
            self.control
                .reserve(
                    /*now_ms*/ 100,
                    &auth.request_id,
                    submitted.revision + 1,
                    reservation.clone()
                )
                .is_err()
        );
        let reserved = self
            .control
            .reserve(
                /*now_ms*/ 100,
                &auth.request_id,
                submitted.revision,
                reservation,
            )
            .map_err(|_| NeuronModelError::Rejected)?;
        let assigned = self
            .control
            .assign(
                &auth.request_id,
                reserved.revision,
                Assignment {
                    worker_id: self.worker.worker_id().into(),
                    worker_generation: 1,
                    assignment_digest: Digest32::of_bytes(b"explicit-test-feature-assignment")
                        .to_string(),
                },
            )
            .map_err(|_| NeuronModelError::Rejected)?;
        let record = self
            .control
            .get(&auth.request_id)
            .expect("actual assigned record");
        assert_eq!(record.request.payload_digest, auth.payload_digest);
        assert_eq!(
            record
                .reservation
                .as_ref()
                .expect("actual reservation")
                .reservation_id,
            auth.reservation_id
        );
        let receipt = self
            .worker
            .run_neuron_features_receipt(
                /*now_ms*/ 100,
                &self.manifest.model_id,
                self.prepared.clone(),
            )
            .map_err(|_| NeuronModelError::Rejected)?;
        verify_neuron_feature_receipt_v1(request, &receipt)
            .map_err(|_| NeuronModelError::Rejected)?;
        let status = match receipt.status {
            NeuronFeatureTerminalStatusV1::Succeeded => RequestState::Completed,
            NeuronFeatureTerminalStatusV1::Failed => RequestState::Failed,
            NeuronFeatureTerminalStatusV1::Cancelled => RequestState::Cancelled,
            NeuronFeatureTerminalStatusV1::Indeterminate => RequestState::Indeterminate,
        };
        let observation = TerminalObservation {
            request_id: auth.request_id.clone(),
            reservation_id: auth.reservation_id.clone(),
            worker_id: self.worker.worker_id().into(),
            worker_generation: 1,
            model_digest: auth.model_digest.clone(),
            payload_digest: auth.payload_digest.clone(),
            terminal_observed: status != RequestState::Indeterminate,
            terminal_status: if status == RequestState::Indeterminate {
                None
            } else {
                Some(status)
            },
            output_digest: if status == RequestState::Completed {
                Some(receipt.output_digest.to_string())
            } else {
                None
            },
            consumed_tokens: if status == RequestState::Completed {
                8
            } else {
                0
            },
            usage_units: receipt.latency_micros.saturating_mul(1000),
        };
        let settled = self
            .control
            .settle(
                &auth.request_id,
                assigned.revision,
                receipt.receipt_digest.to_string(),
                observation.clone(),
            )
            .map_err(|_| NeuronModelError::Rejected)?;
        assert!(
            self.control
                .settle(
                    &auth.request_id,
                    settled.revision,
                    receipt.receipt_digest.to_string(),
                    observation
                )
                .expect("idempotent settle")
                .idempotent
        );
        self.cached = Some(receipt.clone());
        Ok(receipt)
    }
}

fn writable(path: &Path) -> std::fs::File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .expect("new owner file")
}

#[test]
#[ignore = "requires the preserved completed full-002 calibration and registered CPU Python fixture"]
fn actual_generation_feature_owner_preserves_calibration_rejection() {
    let fixture_path = PathBuf::from(
        std::env::var_os("HEPTA_NEURON_CALIBRATION_FIXTURE").expect("prepared native-fixture.json"),
    );
    let fixture_bytes = std::fs::read(&fixture_path).expect("fixture");
    let expected_fixture = std::env::var("HEPTA_NEURON_CALIBRATION_FIXTURE_SHA256")
        .expect("independently recorded fixture byte pin");
    assert_eq!(
        Digest32::of_bytes(&fixture_bytes).to_string(),
        expected_fixture
    );
    let fixture: Fixture = serde_json::from_slice(&fixture_bytes).expect("fixture JSON");
    let report_bytes = std::fs::read(fixture.calibration_directory.join("summary.json"))
        .expect("measured calibration");
    assert_eq!(
        Digest32::of_bytes(&report_bytes).to_string(),
        fixture.calibration_summary_sha256
    );
    let report: Value = serde_json::from_slice(&report_bytes).expect("calibration JSON");
    assert_eq!(
        report["registration"]["checkpoint"]
            .as_str()
            .expect("calibrated model"),
        fixture.pins.checkpoint_sha256
    );
    assert_eq!(
        report["specification_sha256"]
            .as_str()
            .expect("calibrated profile"),
        fixture.specification_sha256
    );
    let rows = std::fs::read(fixture.calibration_directory.join("rows.jsonl"))
        .expect("independent raw rows");
    assert_eq!(
        Digest32::of_bytes(&rows).to_string(),
        fixture.calibration_rows_sha256
    );
    let selected = std::str::from_utf8(&rows)
        .expect("UTF-8 rows")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).expect("row JSON"))
        .filter(|row| row["pair_index"] == 704)
        .collect::<Vec<_>>();
    assert_eq!(selected.len(), 1);
    let selected = &selected[0];
    assert_eq!(
        serde_json::from_value::<GenerationRequestV1>(selected["generation_request"].clone())
            .expect("recorded request"),
        fixture.request
    );
    assert_eq!(
        serde_json::from_value::<GenerationStateV1>(selected["previous_state"].clone())
            .expect("recorded predecessor"),
        fixture.previous_state
    );
    assert_eq!(
        selected["drive_q24"],
        serde_json::to_value(&fixture.expected_drive_q24).expect("drive JSON")
    );
    assert_eq!(
        selected["prediction_q24"],
        serde_json::to_value(&fixture.expected_prediction_q24).expect("prediction JSON")
    );
    assert_eq!(
        selected["output_hashes"]["image"]
            .as_str()
            .expect("recorded PNG"),
        fixture.expected_png_sha256
    );
    assert_eq!(
        selected["output_hashes"]["text"]
            .as_str()
            .expect("recorded text"),
        fixture.expected_text_sha256
    );
    let spec_bytes = std::fs::read(fixture.calibration_directory.join("specification.json"))
        .expect("frozen specification");
    assert_eq!(
        Digest32::of_bytes(&spec_bytes).to_string(),
        fixture.specification_sha256
    );
    assert_eq!(
        fixture.specification_sha256,
        "7472ac00a31a032d164101eb9e691622bdf3b52d5400b9f4ca525a32396c3e49"
    );
    let specification: Value = serde_json::from_slice(&spec_bytes).expect("specification JSON");
    assert_eq!(report["point_gates_passed"], false);
    assert_eq!(
        report["projection_sha256"].as_str().expect("projection"),
        generation_projection_digest().to_string()
    );
    let output = tempfile::Builder::new()
        .prefix("native-owner-")
        .tempdir_in(&fixture.calibration_directory)
        .expect("evidence directory")
        .keep();
    let raw_digest = generation_json_digest(&fixture.request).expect("generation request");
    let previous =
        project_generation_state(&fixture.previous_state).expect("complete predecessor projection");
    assert_eq!(previous, fixture.expected_prediction_q24);
    let tick = NeuronTickInputV1 {
        tick_id: id(&format!("ndu-neuron:{raw_digest}")),
        subject_id: id("validation-pair:704"),
        logical_sequence: 1,
        monotonic_time_micros: 100_000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&previous),
        feature_vector_q24: previous.clone(),
        objective_digest: digest(&fixture.specification_sha256),
        // This isolated feature/admission test has no NDU valuation owner.
        // Keep its explicit test context distinct from the model checkpoint.
        ndu_snapshot_digest: Digest32::of_bytes(
            b"test-context:no-NDU-valuation-owner;validation-pair704;persistence-calibration",
        ),
        body_generation: None,
        modulator_digest: None,
    };
    let driver = GenerationDriver::new(
        GenerationRegistrationV1 {
            repository: fixture.repository,
            python: fixture.python,
            artifact_root: fixture.artifact_root,
            checkpoint_name: fixture.checkpoint_name,
            model_id: fixture.model_id.clone(),
            pins: fixture.pins.clone(),
            timeout: Duration::from_secs(/*secs*/ 60),
        },
        vec![fixture.request.clone()],
    )
    .expect("registered backend");
    let manifest = driver.manifest().expect("actual model manifest");
    let mut prepared = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: tick.tick_id.as_str().into(),
            reservation_id: "neuron-test-reservation".into(),
            model_digest: manifest.model_digest.clone(),
            payload_digest: String::new(),
            maximum_tokens: 8,
            deadline_ms: 90_000,
            lease_payload_digest: String::new(),
            reservation_model_digest: manifest.model_digest.clone(),
            reservation_maximum_tokens: 8,
            cancelled: false,
        },
        encoder_digest: fixture.pins.source_sha256.clone(),
        head_digest: generation_neuron_head_digest().to_string(),
        weights_digest: fixture.pins.parameters_sha256.clone(),
        input_digest: tick
            .semantic_digest()
            .expect("complete tick identity")
            .to_string(),
        feature_vector_q24: previous.clone(),
        expected_output_width: 96,
    };
    let payload = canonical_neuron_feature_payload_digest(&prepared);
    prepared.authorization.payload_digest = payload.clone();
    prepared.authorization.lease_payload_digest = payload.clone();
    let driver = driver
        .with_neuron_bindings(vec![GenerationNeuronBindingV1 {
            request: prepared.clone(),
            generation_request_sha256: raw_digest.clone(),
            previous_state: fixture.previous_state.clone(),
        }])
        .expect("immutable raw request/predecessor binding");
    let process_evidence = driver.evidence();
    let feature_evidence = driver.neuron_evidence();
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "neuron-test-worker".into(),
        /*generation*/ 1,
        ResourceGrant {
            grant_id: "explicit-test-grant".into(),
            authority_epoch: 1,
            generation: 1,
            expires_at_ms: 100_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 1,
            maximum_memory_bytes: 2 * 1024 * 1024 * 1024,
            semantic_digest: Digest32::of_bytes(b"test-authority-only").to_string(),
        },
        driver,
    )
    .expect("worker");
    worker
        .load_model(/*now_ms*/ 100, manifest.clone())
        .expect("load");
    let generation = Generation::new(/*value*/ 1).expect("generation");
    let expected = NeuronFeatureRequestV1 {
        request_id: tick.tick_id.clone(),
        generation,
        model_id: id(&fixture.model_id),
        encoder_digest: digest(&prepared.encoder_digest),
        head_digest: digest(&prepared.head_digest),
        weights_digest: digest(&prepared.weights_digest),
        input_digest: digest(&prepared.input_digest),
        feature_vector_q24: previous,
        expected_output_width: 96,
    };
    let model_request = NeuronModelRequestV1 {
        request_id: expected.request_id.clone(),
        config_id: id("ndu-neuron-persistence-pilot"),
        generation,
        model_id: expected.model_id.clone(),
        encoder_digest: expected.encoder_digest,
        head_digest: expected.head_digest,
        weights_digest: expected.weights_digest,
        input_digest: expected.input_digest,
        feature_vector_q24: expected.feature_vector_q24.clone(),
        expected_output_width: 96,
    };
    let mut port = OwnerPort {
        control: DurableInferenceControl::open(
            output.join("inference.journal"),
            /*capacity*/ 8,
        )
        .expect("inference owner"),
        worker,
        expected: expected.clone(),
        prepared,
        manifest: manifest.clone(),
        cached: None,
    };
    let observed = InferenceControlModelPort::new(&mut port)
        .execute(&model_request)
        .expect("real owner feature execution");
    assert_eq!(observed.drive_q24, fixture.expected_drive_q24);
    assert_eq!(observed.prediction_q24, fixture.expected_prediction_q24);
    let receipt = port.cached.clone().expect("actual typed receipt");
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        port.execute_feature(&expected).expect("exact retry"),
        receipt
    );
    let mut changed = expected.clone();
    changed.input_digest = Digest32::of_bytes(b"changed tick context");
    assert_eq!(
        port.execute_feature(&changed),
        Err(NeuronModelError::Rejected)
    );
    let process = process_evidence
        .get(&raw_digest)
        .expect("actual child evidence");
    let executed = process.execution.as_ref().expect("actual model output");
    executed
        .verify(&fixture.request)
        .expect("raw generation contract");
    assert_eq!(executed.png_sha256, fixture.expected_png_sha256);
    assert_eq!(executed.text_sha256, fixture.expected_text_sha256);
    assert_eq!(executed.states[0], fixture.previous_state);
    std::fs::write(
        output.join("process.json"),
        serde_json::to_vec_pretty(&process).expect("process JSON"),
    )
    .expect("retain process");
    std::fs::write(
        output.join("feature.json"),
        serde_json::to_vec_pretty(&feature_evidence.get(&payload).expect("feature evidence"))
            .expect("feature JSON"),
    )
    .expect("retain feature");
    std::fs::write(
        output.join("typed-feature-receipt.txt"),
        format!("{receipt:#?}\n"),
    )
    .expect("retain complete typed receipt");
    let native = SparseConfig {
        model_digest: expected.head_digest,
        normalization_digest: generation_projection_digest(),
        generation,
        width: 96,
        top_k: 12,
        temporal_decay_q24: 8_388_608,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: 8_388_608,
        target_activity_q24: 2_097_152,
        threshold_rate_q24: 262_144,
        threshold_min_q24: -16_777_216,
        threshold_max_q24: 16_777_216,
        eligibility_decay_q24: 12_582_912,
    };
    let calibration = &specification["calibration"];
    let config = NeuronRuntimeConfigV1 {
        config_id: model_request.config_id,
        generation,
        model_id: expected.model_id,
        model_manifest_digest: digest(&manifest.model_digest),
        encoder_digest: expected.encoder_digest,
        head_digest: expected.head_digest,
        weights_digest: expected.weights_digest,
        tokenizer_digest: digest(&manifest.tokenizer_digest),
        preprocessor_digest: digest(&manifest.preprocessor_digest),
        quantization_digest: digest(&manifest.quantization_digest),
        runtime_digest: digest(&manifest.runtime_digest),
        device_digest: digest(&manifest.device_digest),
        normalization_digest: generation_projection_digest(),
        native_config_digest: native.digest().expect("native config"),
        input_feature_dimension: 96,
        state_width: 96,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest(&fixture.calibration_summary_sha256),
            ood_artifact_digest: digest(
                report["row_set_sha256"]
                    .as_str()
                    .expect("raw cohort identity"),
            ),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 128,
            zero_confidence_error_q24: calibration["zero_confidence_error_q24"]
                .as_i64()
                .expect("scale"),
            maximum_in_domain_error_q24: calibration["maximum_in_domain_error_q24"]
                .as_i64()
                .expect("scale"),
            minimum_confidence_ppm: u32_field(calibration, "minimum_confidence_ppm"),
            maximum_ood_ppm: u32_field(calibration, "maximum_ood_ppm"),
            minimum_active_ppm: 105_000,
            maximum_active_ppm: 145_000,
            maximum_projection_count: 0,
            measured_ece_ppm: u32_field(&report, "native_measured_ece_ppm"),
            maximum_ece_ppm: u32_field(calibration, "maximum_ece_ppm"),
            measured_false_acceptance_ppm: u32_field(
                &report,
                "native_measured_false_acceptance_ppm",
            ),
            maximum_false_acceptance_ppm: u32_field(calibration, "maximum_false_acceptance_ppm"),
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3000,
            p99_latency_micros: 8000,
            transient_allocation_bytes: 524_288,
            checkpoint_bytes: 1_048_576,
            write_amplification_ppm: 4_000_000,
        },
    };
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(b"local-neuron-pilot-scope"),
        objective_digest: tick.objective_digest,
    };
    let witness = FileAnchorWitnessStore::open(
        writable(&output.join("witness.journal")),
        scope,
        generation,
        /*max_records*/ 8,
    )
    .expect("separate witness owner");
    let admission = NeuronRuntime::bootstrap(
        writable(&output.join("neuron.journal")),
        native,
        scope,
        /*max_records*/ 8,
        config,
        witness,
    );
    assert!(matches!(
        admission,
        Err(NeuronRuntimeError::InvalidCalibration)
    ));
    assert_eq!(
        std::fs::metadata(output.join("neuron.journal"))
            .expect("journal metadata")
            .len(),
        0
    );
    let binary = std::fs::read(std::env::current_exe().expect("test executable"))
        .expect("test binary bytes");
    std::fs::write(output.join("admission.json"), serde_json::to_vec_pretty(&serde_json::json!({
        "schema": "hepta.ndu-v6.neuron-admission-observation.v1", "status": "rejected", "native_error": "InvalidCalibration",
        "measured_ece_ppm": report["native_measured_ece_ppm"], "measured_false_acceptance_ppm": report["native_measured_false_acceptance_ppm"],
        "specification_sha256": fixture.specification_sha256, "calibration_summary_sha256": fixture.calibration_summary_sha256,
        "actual_inference_owner_terminal": "Completed", "model_executed": true, "neuron_checkpoint_committed": false,
        "daemon_activated": false, "authority": "deny_all", "test_binary_sha256": Digest32::of_bytes(&binary).to_string()
    })).expect("admission JSON")).expect("retain rejection");
}
