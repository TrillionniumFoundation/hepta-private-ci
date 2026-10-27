//! Optional real-encoder/worker + native-model + control-socket integration.
//! The six positive phrases come from public fit examples. This is wiring and
//! owner-binding evidence, never an independent language-quality evaluation.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_memory::MemoryCellRecordV1;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use crate::AgentdMemoryCellRuntimeV1;
use crate::MemoryCellAddressResolverV1;
use crate::MemoryCellAddressWorkerConfigV1;
use crate::MemoryCellAddressWorkerV1;
use crate::MemoryCellTrainingModeV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request;
use crate::memory_cell_training_test_support::fit;
use crate::memory_cell_training_test_support::trainer;

#[path = "memory_cell_temporal_runtime_tests.rs"]
mod temporal;

fn worker_configuration(orion: &ContractIdV1, vega: &ContractIdV1) -> MemoryCellAddressWorkerConfigV1 {
    let qualified = codex_utils_cargo_bin::repo_root().expect("repository root").join("qualification");
    let addressing = qualified.join("memory-cell-v7/addressing");
    let mut code_pins = BTreeMap::new();
    for entry in std::fs::read_dir(&addressing).expect("address code inventory") {
        let path = entry.expect("address code entry").path();
        if path.extension().is_some_and(|extension| extension == "py") {
            code_pins.insert(path.clone(), ContractDigestV1::from_digest(Digest32::of_bytes(&std::fs::read(path).expect("code bytes"))).expect("code pin"));
        }
    }
    for relative in ["memory-cell-v6/v6/__init__.py", "memory-cell-v6/v6/encoder.py"] {
        let path = qualified.join(relative);
        code_pins.insert(path.clone(), ContractDigestV1::from_digest(Digest32::of_bytes(&std::fs::read(path).expect("encoder code bytes"))).expect("encoder pin"));
    }
    let script = addressing.join("worker.py");
    let directory = |name| {
        let path = PathBuf::from(std::env::var_os(name).unwrap_or_else(|| panic!("explicit {name} is required for the ignored learned-worker profile")));
        assert!(path.is_absolute(), "configured profile paths must be absolute");
        path
    };
    MemoryCellAddressWorkerConfigV1 {
        python: directory("MEMORY_CELL_TRAINING_PYTHON"), worker_script_digest: code_pins[&script], worker_script: script, code_pins,
        model_directory: directory("MEMORY_CELL_ADDRESS_MODEL_DIR"),
        model_digest: ContractDigestV1::parse(&std::env::var("MEMORY_CELL_ADDRESS_MODEL_DIGEST").expect("explicit selected model digest")).expect("exact model digest"),
        encoder_directory: directory("MEMORY_CELL_ADDRESS_ENCODER_DIR"),
        aliases: BTreeMap::from([(orion.clone(), vec!["Orion".to_string()]), (vega.clone(), vec!["Vega".to_string()])]),
        request_timeout: Duration::from_millis(1_500), startup_timeout: Duration::from_secs(30),
    }
}

fn expected_sources(snapshot: &MemoryCellOwnerSnapshotV1, entity: &ContractIdV1, operation: MemoryOperationV1) -> BTreeSet<ContractDigestV1> {
    use MemoryCellKindV1::Event;
    use MemoryCellKindV1::Procedure;
    use MemoryCellKindV1::Semantic;
    let current = |kind| snapshot.current(entity, kind).expect("independent owner source").source_id;
    match operation {
        MemoryOperationV1::Current => BTreeSet::from([current(Event)]),
        MemoryOperationV1::History => BTreeSet::from([snapshot.at(entity, Event, 15).expect("historical source").source_id]),
        MemoryOperationV1::Semantic => BTreeSet::from([current(Semantic)]),
        MemoryOperationV1::Procedure => BTreeSet::from([current(Procedure)]),
        MemoryOperationV1::Change => BTreeSet::from([current(Event), snapshot.at(entity, Event, 10).expect("change source").source_id]),
        MemoryOperationV1::Apply => BTreeSet::from([current(Event), current(Semantic), current(Procedure)]),
    }
}

#[tokio::test]
#[ignore = "requires the pinned encoder, admitted address model and NumPy training Python profile"]
async fn actual_language_worker_addresses_six_operations_through_native_parameters_and_agentd_socket() {
    let fixture = ControlFixture::new().await;
    let orion = ContractIdV1::new("meter:agentd-cell").expect("Orion canonical identity");
    let vega = ContractIdV1::new("meter:language-vega").expect("Vega canonical identity");
    for (kind, effective_at, value) in [
        (MemoryCellKindV1::Event, 10, json!(6)), (MemoryCellKindV1::Event, 20, json!(14)),
        (MemoryCellKindV1::Semantic, 20, json!({"factor":4,"label":"vega semantic"})),
        (MemoryCellKindV1::Procedure, 20, json!({"opcode":"affine","bias":3,"limit":1000})),
    ] {
        let record = MemoryCellRecordV1 { schema: "hepta.memory.cell-record.v1".to_string(), entity: vega.clone(), kind, effective_at, value };
        fixture.store.write_memory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &record, MemoryCellWriteModeV1::Create).await.expect("second real owner entity");
    }
    let fitted = fit(&trainer(), &fixture, /*generation*/ 1, MemoryCellTrainingModeV1::Clean).await;
    let (semantic, procedure) = fitted.native_payloads();
    let release = ReleaseFixture::from_models_with_training_code(fitted.snapshot(), semantic.as_bytes(), procedure.as_bytes(), fitted.training_code_digest());
    let bundle = release.host.load_current().expect("verified actually trained native bundle");
    assert_eq!(bundle.semantic().predict(vega.as_str()).expect("native Vega prediction").value, Some(json!({"factor":4,"label":"vega semantic"})));
    let configuration = worker_configuration(&orion, &vega);
    let address_model = configuration.model_digest;
    let started = Instant::now();
    let worker = Arc::new(MemoryCellAddressWorkerV1::start(configuration).await.expect("real pinned model and encoder prewarm"));
    let startup_wall_ns = started.elapsed().as_nanos();
    let resolver: Arc<dyn MemoryCellAddressResolverV1> = worker.clone();
    let runtime = Arc::new(AgentdMemoryCellRuntimeV1::new(fixture.state.identity().agent_id.clone(), /*spawn_generation*/ 1,
        CognitiveScope::AgentPrivate, Arc::clone(&release.host), resolver).expect("real worker product runtime"));
    fixture.state.attach_memory_cells(runtime).expect("configured memory host");
    fixture.ready();
    let cases = [
        (orion.clone(), MemoryOperationV1::Current, "Retrieve Orion's latest unprocessed sample.", json!(9)),
        (vega.clone(), MemoryOperationV1::History, "For Vega, recall the reading on file by the supplied cutoff.", json!(6)),
        (orion.clone(), MemoryOperationV1::Semantic, "Recall Orion's stored multiplier itself.", json!({"factor":3,"label":"owner semantic"})),
        (vega.clone(), MemoryOperationV1::Procedure, "Describe only the saved steps for Vega, without executing them.", json!({"opcode":"affine","bias":3,"limit":1000})),
        (orion.clone(), MemoryOperationV1::Change, "Read Orion's current and earlier values, then return current minus earlier.", json!(5)),
        (vega, MemoryOperationV1::Apply, "Use Vega's saved recipe to produce a result from its latest observation.", json!(59)),
    ];
    let mut evidence = Vec::new();
    for (index, (entity, operation, text, value)) in cases.into_iter().enumerate() {
        let mut query = request(fitted.snapshot().scope().clone());
        query.query_id = ContractIdV1::new(format!("query:real-language-{index}")).expect("unique query");
        query.entity = entity.clone(); query.text = text.to_string();
        let readout = fixture.client.memory_cell_read(query.clone()).await.expect("real worker and native control read");
        assert_eq!((readout.query_id.clone(), readout.operation, readout.status, readout.value.clone(), readout.generation, readout.snapshot_digest),
            (query.query_id.clone(), Some(operation), MemoryReadStatusV1::Ok, value, bundle.generation(), bundle.bundle_digest()));
        assert_eq!(readout.source_ids.iter().copied().collect::<BTreeSet<_>>(), expected_sources(fitted.snapshot(), &entity, operation));
        evidence.push(json!({"request":query,"readout":readout,"owner_cut_digest":fitted.snapshot().owner_cut_digest()}));
    }
    for (index, (entity, text)) in [
        (ContractIdV1::new("meter:unregistered-sirius").expect("unknown entity"), "Retrieve Sirius's latest unprocessed sample."),
        (orion.clone(), "Square Orion's stored factor."),
    ].into_iter().enumerate() {
        let mut query = request(fitted.snapshot().scope().clone());
        query.query_id = ContractIdV1::new(format!("query:real-language-reject-{index}")).expect("negative query");
        query.entity = entity; query.text = text.to_string();
        let readout = fixture.client.memory_cell_read(query.clone()).await.expect("bound rejection frame");
        assert_eq!((readout.query_id.clone(), readout.status, readout.value.clone(), readout.source_ids.clone(), readout.cell_digests.clone()),
            (query.query_id.clone(), MemoryReadStatusV1::Abstain, Value::Null, vec![], vec![]));
        evidence.push(json!({"request":query,"readout":readout,"owner_cut_digest":fitted.snapshot().owner_cut_digest()}));
    }
    let counters = worker.metrics();
    assert_eq!((counters.attempted_requests, counters.validated_responses, counters.process_starts), (8, 8, 1));
    assert!(counters.stdin_bytes > 0 && counters.stdout_bytes > 0 && counters.host_request_nanoseconds > 0);
    assert!(counters.reported_cpu_nanoseconds > 0 && counters.reported_wall_nanoseconds > 0);
    let temporal = temporal::real_dates(&fixture, &release, &orion).await;
    let counters = worker.metrics();
    let report = json!({"schema":"hepta.memory.v7.language-runtime-integration.v1", "test_kind":"product-protocol-and-data-binding-only",
        "address_model_digest":address_model,"training_code_digest":fitted.training_code_digest().to_string(), "parameter_training":fitted.receipt(),
        "bundle_digest":bundle.bundle_digest(),"owner_cut_digest":fitted.snapshot().owner_cut_digest(),"readbacks":evidence,
        "worker":{"attempts":counters.attempted_requests,"responses":counters.validated_responses,"process_starts":counters.process_starts,
            "stdin_bytes":counters.stdin_bytes,"stdout_bytes":counters.stdout_bytes,"cpu_ns":counters.reported_cpu_nanoseconds,
            "reported_wall_ns":counters.reported_wall_nanoseconds,"host_request_ns":counters.host_request_nanoseconds,"startup_wall_ns":startup_wall_ns},
        "control_transport":fixture.client.traffic_snapshot(),"positive_phrases_from_public_fit_examples":true,
        "temporal_transport":temporal,
        "independent_language_evaluation":false,"independent_future_task_evaluation":false,"held_reads":0});
    let path = std::env::var_os("MEMORY_CELL_LANGUAGE_RECEIPT_PATH").map(PathBuf::from)
        .unwrap_or_else(|| std::env::temp_dir().join(format!("hepta-memory-language-runtime-{}.json", std::process::id())));
    assert!(path.is_absolute(), "receipt path must be absolute");
    std::fs::create_dir_all(path.parent().expect("receipt parent")).expect("receipt directory");
    let file = std::fs::OpenOptions::new().create_new(true).write(true).open(&path).expect("create-only integration receipt");
    serde_json::to_writer_pretty(file, &report).expect("integration evidence");
    println!("MEMORY_CELL_LANGUAGE_RECEIPT_PATH={}", path.display());
    println!("MEMORY_CELL_LANGUAGE_RECEIPT={report}");
    fixture.finish().await;
}
