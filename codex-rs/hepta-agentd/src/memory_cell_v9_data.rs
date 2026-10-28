//! Independent authored tasks feed only the evaluator; exports omit domain labels.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

use codex_hepta_cognitive_store::MemoryCellRecordV1;
use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::execute_memory_cell_program_v1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use crate::memory_cell_runtime_tests::TestRoute;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request;

pub(super) enum Reader<'a> {
    Native(&'a TrustedTestResolver),
    Direct(&'a super::direct::DirectOwner),
}

pub(super) const FIXTURE_SHA: &str =
    "750ecabdcdbc0aa9f5bf253615efaff090800c3a96a2958e0d17a4df829c6502";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Fixture {
    pub schema: String,
    pub stages: Vec<Stage>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Stage {
    pub id: String,
    pub writes: Vec<Fact>,
    pub prefix: Vec<Task>,
    pub future: Vec<Task>,
    pub retention: Vec<Task>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Fact {
    pub entity: ContractIdV1,
    pub domain: String,
    pub event: i64,
    pub semantic: Value,
    pub procedure: Value,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Task {
    pub id: String,
    pub family: String,
    pub queries: Vec<Query>,
    pub coefficients: Vec<i64>,
    pub threshold: i64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Query {
    pub entity: ContractIdV1,
    pub operation: MemoryOperationV1,
}

pub(super) fn save(path: &Path, value: &Value) -> Value {
    let raw = serde_json::to_vec_pretty(value).unwrap();
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .unwrap();
    file.write_all(&raw).unwrap();
    file.sync_all().unwrap();
    json!({"path":path.file_name().unwrap().to_str().unwrap(),"bytes":raw.len(),"sha256":Digest32::of_bytes(&raw).to_string()})
}

pub(super) fn load_fixture(root: &Path) -> Fixture {
    let raw = std::fs::read(root.join("memory-cell-v9/evaluation/continual-held.json")).unwrap();
    assert_eq!(Digest32::of_bytes(&raw).to_string(), FIXTURE_SHA);
    let data: Fixture = serde_json::from_slice(&raw).unwrap();
    assert_eq!(data.schema, "hepta.memory.v9.continual-fixture.v1");
    assert_eq!(data.stages.len(), 3);
    let mut entities = BTreeSet::new();
    for stage in &data.stages {
        let old = entities.clone();
        assert!(!stage.id.is_empty());
        for fact in &stage.writes {
            assert!(!fact.domain.is_empty() && entities.insert(fact.entity.clone()));
        }
        assert!(entities.len() <= 48);
        for batch in [&stage.prefix, &stage.future, &stage.retention] {
            assert!(!batch.is_empty() && batch.len() <= 64);
            for task in batch {
                assert!(!task.id.is_empty() && !task.family.is_empty());
                assert!(
                    (1..=8).contains(&task.queries.len())
                        && task.coefficients.len() == task.queries.len()
                );
                assert!(
                    task.coefficients
                        .iter()
                        .all(|value| (-16..=16).contains(value))
                );
                assert!(
                    task.queries
                        .iter()
                        .all(|query| entities.contains(&query.entity)
                            && !matches!(
                                query.operation,
                                MemoryOperationV1::History | MemoryOperationV1::Change
                            ))
                );
            }
        }
        assert!(
            stage
                .prefix
                .iter()
                .flat_map(|task| &task.queries)
                .all(|query| query.operation == MemoryOperationV1::Current)
        );
        if !old.is_empty() {
            assert!(
                stage
                    .retention
                    .iter()
                    .flat_map(|task| &task.queries)
                    .all(|query| old.contains(&query.entity))
            );
        }
    }
    data
}

pub(super) async fn append(owner: &ControlFixture, facts: &[Fact]) {
    for fact in facts {
        for (kind, value) in [
            (MemoryCellKindV1::Event, json!(fact.event)),
            (MemoryCellKindV1::Semantic, fact.semantic.clone()),
            (MemoryCellKindV1::Procedure, fact.procedure.clone()),
        ] {
            let record = MemoryCellRecordV1 {
                schema: "hepta.memory.cell-record.v1".to_string(),
                entity: fact.entity.clone(),
                kind,
                effective_at: 20,
                value,
            };
            owner
                .store
                .write_memory_cell(
                    &owner.access(),
                    &CognitiveScope::AgentPrivate,
                    &record,
                    MemoryCellWriteModeV1::Create,
                )
                .await
                .unwrap();
        }
    }
}

fn expected(owner: &MemoryCellOwnerSnapshotV1, query: &Query) -> Value {
    let value = |kind| {
        owner
            .current(&query.entity, kind)
            .unwrap()
            .record
            .value
            .clone()
    };
    match query.operation {
        MemoryOperationV1::Current => value(MemoryCellKindV1::Event),
        MemoryOperationV1::Semantic => value(MemoryCellKindV1::Semantic),
        MemoryOperationV1::Procedure => value(MemoryCellKindV1::Procedure),
        MemoryOperationV1::Apply => json!(
            execute_memory_cell_program_v1(
                &value(MemoryCellKindV1::Procedure),
                value(MemoryCellKindV1::Event).as_i64().unwrap(),
                &value(MemoryCellKindV1::Semantic)
            )
            .unwrap()
        ),
        MemoryOperationV1::History | MemoryOperationV1::Change => unreachable!("fixture contract"),
    }
}

fn scalar(value: &Value, operation: MemoryOperationV1) -> Option<i64> {
    match operation {
        MemoryOperationV1::Semantic => value.get("factor").and_then(Value::as_i64),
        MemoryOperationV1::Procedure => value.get("bias").and_then(Value::as_i64),
        MemoryOperationV1::Current | MemoryOperationV1::Apply => value.as_i64(),
        MemoryOperationV1::History | MemoryOperationV1::Change => None,
    }
}

pub(super) async fn evaluate(owner: &ControlFixture, reader: &Reader<'_>, tasks: &[Task]) -> Value {
    let snapshot = owner.snapshot().await;
    let before = owner.client.traffic_snapshot();
    let started = Instant::now();
    let mut records = Vec::new();
    let mut correct = 0;
    let mut decisions = 0;
    let mut queries = 0;
    for task in tasks {
        let mut requests = Vec::new();
        let mut readouts = Vec::new();
        let mut expected_values = Vec::new();
        let mut total = Some(0_i64);
        let mut target = 0_i64;
        for (offset, query) in task.queries.iter().enumerate() {
            let mut request = request(snapshot.scope().clone());
            request.query_id = ContractIdV1::new(format!("query:v9:{}:{offset}", task.id)).unwrap();
            request.entity = query.entity.clone();
            let (status, value, readout) = match reader {
                Reader::Native(resolver) => {
                    resolver.set(TestRoute::Read(query.operation));
                    let readout = owner
                        .client
                        .memory_cell_read(request.clone())
                        .await
                        .unwrap();
                    (
                        readout.status,
                        readout.value.clone(),
                        serde_json::to_value(readout).unwrap(),
                    )
                }
                Reader::Direct(direct) => direct.read(owner, &request, query.operation).await,
            };
            let expected = expected(&snapshot, query);
            let ok = status == MemoryReadStatusV1::Ok;
            correct += usize::from(ok && value == expected);
            target = target
                .checked_add(
                    task.coefficients[offset]
                        .checked_mul(scalar(&expected, query.operation).unwrap())
                        .unwrap(),
                )
                .unwrap();
            total = total.and_then(|sum| {
                ok.then(|| scalar(&value, query.operation))
                    .flatten()
                    .and_then(|number| task.coefficients[offset].checked_mul(number))
                    .and_then(|number| sum.checked_add(number))
            });
            requests.push(request);
            readouts.push(readout);
            expected_values.push(expected);
            queries += 1;
        }
        let action = total.map(|sum| sum > task.threshold);
        let target_action = target > task.threshold;
        decisions += usize::from(action == Some(target_action));
        let request_bytes = serde_json::to_vec(&requests).unwrap();
        let readout_bytes = serde_json::to_vec(&readouts).unwrap();
        records.push(json!({"task":task,"requests":requests,"readouts":readouts,"expected_values":expected_values,
            "request_json":String::from_utf8(request_bytes.clone()).unwrap(),"request_digest":Digest32::of_bytes(&request_bytes).to_string(),
            "readout_json":String::from_utf8(readout_bytes.clone()).unwrap(),"readout_digest":Digest32::of_bytes(&readout_bytes).to_string(),
            "action":action,"expected_action":target_action}));
    }
    let after = owner.client.traffic_snapshot();
    json!({"source_cut":snapshot.owner_cut_digest(),"queries":queries,"correct":correct,
        "tasks":tasks.len(),"decisions_correct":decisions,"wall_ns":started.elapsed().as_nanos(),"records":records,
        "traffic":{"rpc_attempts":after.rpc_attempts-before.rpc_attempts,
            "transmitted_bytes":after.transmitted_bytes-before.transmitted_bytes,"received_bytes":after.received_bytes-before.received_bytes}})
}

pub(super) fn logical_files(root: &Path) -> u64 {
    let mut bytes = 0;
    for entry in std::fs::read_dir(root).unwrap() {
        let path = entry.unwrap().path();
        let metadata = std::fs::symlink_metadata(&path).unwrap();
        assert!(!metadata.file_type().is_symlink());
        bytes += if metadata.is_dir() {
            logical_files(&path)
        } else {
            metadata.len()
        };
    }
    bytes
}

pub(super) fn family_counts(tasks: &[Task]) -> BTreeMap<String, usize> {
    let mut result = BTreeMap::new();
    for task in tasks {
        *result.entry(task.family.clone()).or_default() += 1;
    }
    result
}
