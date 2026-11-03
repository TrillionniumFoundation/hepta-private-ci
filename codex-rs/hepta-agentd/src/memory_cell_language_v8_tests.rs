//! Frozen candidate measurement through real owner writes, two learned routing
//! calls per case and native control reads. This fixture grants no final use.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_memory::MemoryCellRecordV1;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use crate::AgentdMemoryCellRuntimeV1;
use crate::MemoryCellAddressResolverV1;
use crate::MemoryCellAddressWorkerConfigV1;
use crate::MemoryCellAddressWorkerV1;
use crate::MemoryCellTrainingModeV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_training_test_support::fit;
use crate::memory_cell_training_test_support::trainer;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeFixture {
    schema: String,
    suite_digest: ContractDigestV1,
    split: String,
    records: Vec<MemoryCellRecordV1>,
    aliases: BTreeMap<ContractIdV1, Vec<String>>,
    requests: Vec<Case>,
    scope_source: String,
    native_execution_claim: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: ContractIdV1,
    family: String,
    language: String,
    category: String,
    entity: ContractIdV1,
    text: String,
    at: u64,
    since: u64,
    max_hops: u8,
    max_cells: u8,
    expected_operation: Option<MemoryOperationV1>,
    expected_value: Value,
}

#[derive(Default, Serialize)]
struct Counts {
    rows: usize,
    routing_correct: usize,
    native_correct: usize,
    wrong_native_accepts: usize,
    negative_routes: usize,
    errors: usize,
}

#[derive(Clone, Copy)]
enum EvaluationArm {
    FrozenV7,
    CandidateV8,
}

fn configured_path(name: &str) -> PathBuf {
    let path =
        PathBuf::from(std::env::var_os(name).unwrap_or_else(|| panic!("explicit {name} required")));
    assert!(path.is_absolute(), "qualification paths must be absolute");
    path
}

fn configured_digest(name: &str) -> ContractDigestV1 {
    ContractDigestV1::parse(
        &std::env::var(name).unwrap_or_else(|_| panic!("explicit {name} required")),
    )
    .unwrap()
}

fn worker_configuration(
    aliases: BTreeMap<ContractIdV1, Vec<String>>,
    arm: EvaluationArm,
) -> MemoryCellAddressWorkerConfigV1 {
    let qualification = codex_utils_cargo_bin::repo_root()
        .unwrap()
        .join("qualification");
    let frozen = qualification.join("memory-cell-v7/addressing");
    let (addressing, directories, script_name, model_variable, digest_variable) = match arm {
        EvaluationArm::FrozenV7 => (
            frozen.clone(),
            vec![frozen],
            "worker.py",
            "MEMORY_CELL_ADDRESS_MODEL_DIR",
            "MEMORY_CELL_ADDRESS_MODEL_DIGEST",
        ),
        EvaluationArm::CandidateV8 => {
            let addressing = qualification.join("memory-cell-v8/addressing");
            let directories = vec![addressing.clone(), addressing.join("v8_addressing"), frozen];
            (
                addressing,
                directories,
                "qualification_shadow_worker.py",
                "MEMORY_CELL_V8_ADDRESS_MODEL_DIR",
                "MEMORY_CELL_V8_ADDRESS_MODEL_DIGEST",
            )
        }
    };
    let mut code_pins = BTreeMap::new();
    for directory in directories {
        for entry in std::fs::read_dir(directory).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().is_some_and(|extension| extension == "py") {
                code_pins.insert(
                    path.clone(),
                    ContractDigestV1::from_digest(Digest32::of_bytes(
                        &std::fs::read(path).unwrap(),
                    ))
                    .unwrap(),
                );
            }
        }
    }
    for name in ["__init__.py", "encoder.py"] {
        let path = qualification.join("memory-cell-v6/v6").join(name);
        code_pins.insert(
            path.clone(),
            ContractDigestV1::from_digest(Digest32::of_bytes(&std::fs::read(path).unwrap()))
                .unwrap(),
        );
    }
    let script = addressing.join(script_name);
    MemoryCellAddressWorkerConfigV1 {
        python: configured_path("MEMORY_CELL_TRAINING_PYTHON"),
        worker_script_digest: code_pins[&script],
        worker_script: script,
        code_pins,
        aliases,
        model_directory: configured_path(model_variable),
        model_digest: configured_digest(digest_variable),
        encoder_directory: configured_path("MEMORY_CELL_ADDRESS_ENCODER_DIR"),
        request_timeout: Duration::from_millis(1_500),
        startup_timeout: Duration::from_secs(30),
    }
}

fn sources_for(
    owner: &MemoryCellOwnerSnapshotV1,
    query: &MemoryRequestV1,
    operation: MemoryOperationV1,
) -> BTreeSet<ContractDigestV1> {
    use MemoryCellKindV1::Event;
    use MemoryCellKindV1::Procedure;
    use MemoryCellKindV1::Semantic;
    let current = |kind| {
        owner
            .current(&query.entity, kind)
            .map(|record| record.source_id)
    };
    let values = match operation {
        MemoryOperationV1::Current => vec![current(Event)],
        MemoryOperationV1::History => vec![
            owner
                .at(&query.entity, Event, query.at)
                .map(|record| record.source_id),
        ],
        MemoryOperationV1::Semantic => vec![current(Semantic)],
        MemoryOperationV1::Procedure => vec![current(Procedure)],
        MemoryOperationV1::Change => vec![
            current(Event),
            owner
                .at(&query.entity, Event, query.since)
                .map(|record| record.source_id),
        ],
        MemoryOperationV1::Apply => vec![current(Event), current(Semantic), current(Procedure)],
    };
    values.into_iter().flatten().collect()
}

#[tokio::test]
#[ignore = "requires the frozen V8 candidate, encoder, native held fixture and NumPy profile"]
async fn actual_v8_shadow_suite_records_every_frozen_request_and_bound_native_readout() {
    let baseline = measure_native_suite(EvaluationArm::FrozenV7).await;
    let candidate = measure_native_suite(EvaluationArm::CandidateV8).await;
    assert_eq!(baseline["fixture_sha256"], candidate["fixture_sha256"]);
    for report in [&baseline, &candidate] {
        assert_eq!(report["binding_failures"], json!(0));
        assert_eq!(report["errors"], json!(0));
        assert_eq!(
            report["worker"]["attempts"].as_u64().unwrap(),
            2 * report["native_rows_attempted"].as_u64().unwrap()
        );
    }
    println!(
        "MEMORY_CELL_V8_PAIRED_NATIVE_SUMMARY={}",
        json!({
        "fixture_sha256":baseline["fixture_sha256"],
        "frozen_v7_known_correct_coverage":baseline["known_correct_coverage"],
        "candidate_v8_known_correct_coverage":candidate["known_correct_coverage"],
        "frozen_v7_unsupported_route_rate":baseline["unsupported_route_acceptance_rate"],
        "candidate_v8_unsupported_route_rate":candidate["unsupported_route_acceptance_rate"],
        "both_arms_execute_same_frozen_native_requests":true,"final_use_authority":false})
    );
}

async fn measure_native_suite(arm: EvaluationArm) -> Value {
    let input_path = configured_path("MEMORY_CELL_V8_NATIVE_FIXTURE");
    let input = std::fs::read(&input_path).unwrap();
    assert!(input.len() <= 8_000_000);
    let input_digest = ContractDigestV1::from_digest(Digest32::of_bytes(&input)).unwrap();
    assert_eq!(
        input_digest,
        configured_digest("MEMORY_CELL_V8_NATIVE_FIXTURE_DIGEST")
    );
    let data: NativeFixture = serde_json::from_slice(&input).unwrap();
    assert_eq!(data.schema, "hepta.memory.v8.native-language-fixture.v1");
    assert_eq!(data.split, "held");
    assert!(!data.native_execution_claim);
    assert_eq!(
        data.scope_source,
        "actual native owner's memory snapshot; never this fixture"
    );
    assert!((120..=4096).contains(&data.requests.len()) && data.records.len() <= 480);
    let fixture = ControlFixture::new().await;
    for record in &data.records {
        record.validate().unwrap();
        fixture
            .store
            .write_memory_cell(
                &fixture.access(),
                &CognitiveScope::AgentPrivate,
                record,
                MemoryCellWriteModeV1::Create,
            )
            .await
            .unwrap();
    }
    let fitted = fit(
        &trainer(),
        &fixture,
        /*generation*/ 1,
        MemoryCellTrainingModeV1::Clean,
    )
    .await;
    let (semantic, procedure) = fitted.native_payloads();
    let release = ReleaseFixture::from_models_with_training_code(
        fitted.snapshot(),
        semantic.as_bytes(),
        procedure.as_bytes(),
        fitted.training_code_digest(),
    );
    let bundle = release.host.load_current().unwrap();
    let configuration = worker_configuration(data.aliases, arm);
    let manifest: Value = serde_json::from_slice(
        &std::fs::read(configuration.model_directory.join("manifest.json")).unwrap(),
    )
    .unwrap();
    let model_digest = configuration.model_digest;
    let began = Instant::now();
    let worker = Arc::new(
        MemoryCellAddressWorkerV1::start(configuration)
            .await
            .unwrap(),
    );
    let startup_wall_ns = began.elapsed().as_nanos();
    let resolver: Arc<dyn MemoryCellAddressResolverV1> = worker.clone();
    fixture
        .state
        .attach_memory_cells(Arc::new(
            AgentdMemoryCellRuntimeV1::new(
                fixture.state.identity().agent_id.clone(),
                /*spawn_generation*/ 1,
                CognitiveScope::AgentPrivate,
                Arc::clone(&release.host),
                resolver,
            )
            .unwrap(),
        ))
        .unwrap();
    fixture.ready();
    let mut results = Vec::new();
    let mut counts = BTreeMap::<String, Counts>::new();
    let mut ids = BTreeSet::new();
    let mut direct_wall_ns = 0;
    let mut control_wall_ns = 0;
    let mut binding_failures = 0;
    for case in data.requests {
        assert!(ids.insert(case.id.clone()));
        assert!(
            [
                "known",
                "unsupported",
                "unknown_entity",
                "ambiguous_alias",
                "time_conflict"
            ]
            .contains(&case.category.as_str())
        );
        assert_eq!(case.expected_operation.is_some(), case.category == "known");
        assert_eq!((case.max_hops, case.max_cells), (8, 8));
        let query = MemoryRequestV1 {
            schema: "hepta.memory.request.v1".to_string(),
            query_id: case.id.clone(),
            scope: fitted.snapshot().scope().clone(),
            entity: case.entity.clone(),
            text: case.text.clone(),
            at: case.at,
            since: case.since,
            max_hops: case.max_hops,
            max_cells: case.max_cells,
        };
        query.validate().unwrap();
        let began = Instant::now();
        let direct = worker.resolve(&query, fitted.snapshot()).await;
        let direct_elapsed = began.elapsed().as_nanos();
        direct_wall_ns += direct_elapsed;
        let route = direct
            .as_ref()
            .ok()
            .and_then(|decision| decision.as_ref())
            .map(|decision| decision.operation);
        let direct_error = direct.as_ref().err().cloned();
        let direct_identity_valid = direct
            .as_ref()
            .ok()
            .and_then(|value| value.as_ref())
            .is_none_or(|decision| {
                decision.request == query
                    && decision.owner_cut_digest == fitted.snapshot().owner_cut_digest()
                    && decision.model_digest == model_digest
            });
        let began = Instant::now();
        let native = fixture.client.memory_cell_read(query.clone()).await;
        let control_elapsed = began.elapsed().as_nanos();
        control_wall_ns += control_elapsed;
        let count = counts.entry(case.category.clone()).or_default();
        count.rows += 1;
        count.routing_correct +=
            usize::from(direct_error.is_none() && route == case.expected_operation);
        count.negative_routes += usize::from(case.expected_operation.is_none() && route.is_some());
        let mut native_correct = false;
        let mut read_identity_valid = false;
        match &native {
            Ok(readout) => {
                read_identity_valid = readout.validate().is_ok()
                    && readout.query_id == query.query_id
                    && readout.generation == bundle.generation()
                    && readout.snapshot_digest == bundle.bundle_digest();
                if readout.status == MemoryReadStatusV1::Ok {
                    read_identity_valid &= direct_error.is_none() && route == readout.operation;
                    let sources_match = case.expected_operation.is_some_and(|operation| {
                        readout.source_ids.iter().copied().collect::<BTreeSet<_>>()
                            == sources_for(fitted.snapshot(), &query, operation)
                    });
                    native_correct = readout.operation == case.expected_operation
                        && readout.value == case.expected_value
                        && sources_match;
                    count.wrong_native_accepts += usize::from(!native_correct);
                } else {
                    native_correct = case.expected_operation.is_none()
                        && route.is_none()
                        && direct_error.is_none()
                        && readout.status == MemoryReadStatusV1::Abstain;
                }
                count.errors += usize::from(
                    direct_error.is_some()
                        || matches!(
                            readout.status,
                            MemoryReadStatusV1::Unavailable | MemoryReadStatusV1::Stale
                        ),
                );
            }
            Err(_) => count.errors += 1,
        }
        count.native_correct +=
            usize::from(native_correct && read_identity_valid && direct_identity_valid);
        binding_failures += usize::from(!read_identity_valid || !direct_identity_valid);
        results.push(json!({"case":case,"request":query,"direct_operation":route,"direct_error":direct_error,
            "direct_identity_valid":direct_identity_valid,"direct_wall_ns":direct_elapsed,"control_wall_ns":control_elapsed,
            "read_identity_valid":read_identity_valid,"native_correct":native_correct,
            "readout":native.as_ref().ok(),"transport_error":native.as_ref().err().map(ToString::to_string)}));
    }
    let known = counts.get("known").unwrap();
    let unsupported = counts.get("unsupported").unwrap();
    let correct_coverage = known.native_correct as f64 / known.rows as f64;
    let unsupported_route_rate = unsupported.negative_routes as f64 / unsupported.rows as f64;
    let boundary_passed = counts
        .iter()
        .filter(|(name, _)| !["known", "unsupported"].contains(&name.as_str()))
        .all(|(_, value)| value.native_correct == value.rows && value.negative_routes == 0);
    let errors: usize = counts.values().map(|value| value.errors).sum();
    let quality_gate_passed = correct_coverage >= 0.8
        && known.wrong_native_accepts == 0
        && unsupported_route_rate <= 0.05
        && boundary_passed
        && errors == 0
        && binding_failures == 0;
    let counters = worker.metrics();
    let report = json!({"schema":"hepta.memory.v8.native-language-evaluation.v1","fixture_path":input_path,
        "fixture_sha256":input_digest,"suite_digest":data.suite_digest,"model_digest":model_digest,
        "arm":(match arm { EvaluationArm::FrozenV7 => "frozen-v7", EvaluationArm::CandidateV8 => "candidate-v8-shadow" }),
        "model_calibration":(manifest["calibration"]),"qualification_only":true,
        "qualification_shadow":matches!(arm, EvaluationArm::CandidateV8),"final_use_authority":false,
        "source_cut":fitted.snapshot().owner_cut_digest(),"bundle_digest":bundle.bundle_digest(),
        "language_head_fits":0,"new_memory_parameter_fits":2,"parameter_training":fitted.receipt(),
        "native_rows_attempted":results.len(),"native_rows_returned":results.iter().filter(|row| !row["readout"].is_null()).count(),
        "known_correct_coverage":correct_coverage,"unsupported_route_acceptance_rate":unsupported_route_rate,
        "counts":counts,"quality_gate_passed":quality_gate_passed,"binding_failures":binding_failures,"errors":errors,
        "direct_probe_wall_ns":direct_wall_ns,"control_roundtrip_wall_ns":control_wall_ns,"startup_wall_ns":startup_wall_ns,
        "worker":{"attempts":counters.attempted_requests,"host_time_abstentions":counters.host_time_abstentions,"responses":counters.validated_responses,"starts":counters.process_starts,
            "stdin_bytes":counters.stdin_bytes,"stdout_bytes":counters.stdout_bytes,"cpu_ns":counters.reported_cpu_nanoseconds,
            "wall_ns":counters.reported_wall_nanoseconds,"host_ns":counters.host_request_nanoseconds},
        "control_transport":fixture.client.traffic_snapshot(),"routing_calls_per_case":2,
        "cost_scope":"Direct diagnostic route and full control read are separate actual calls; no claim of exclusive communication cost.",
        "population_risk_established":false,"readouts":results});
    let output = configured_path(match arm {
        EvaluationArm::FrozenV7 => "MEMORY_CELL_V8_BASELINE_RECEIPT_PATH",
        EvaluationArm::CandidateV8 => "MEMORY_CELL_V8_NATIVE_RECEIPT_PATH",
    });
    std::fs::create_dir_all(output.parent().unwrap()).unwrap();
    let file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&output)
        .unwrap();
    serde_json::to_writer_pretty(file, &report).unwrap();
    println!("MEMORY_CELL_V8_NATIVE_RECEIPT_PATH={}", output.display());
    println!(
        "MEMORY_CELL_V8_NATIVE_SUMMARY={}",
        json!({"rows":report["native_rows_attempted"],"quality_gate_passed":quality_gate_passed,
        "known_correct_coverage":correct_coverage,"unsupported_route_acceptance_rate":unsupported_route_rate,"errors":errors})
    );
    fixture.finish().await;
    // A scientific quality failure stays in the original receipt. Successful
    // measurement of a negative result does not turn it into production admission.
    report
}
