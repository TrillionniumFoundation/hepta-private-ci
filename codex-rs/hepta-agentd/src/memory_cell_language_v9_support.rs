//! Shared strict fixture types and pinned configurations for the V9 three-arm run.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_memory::MemoryCellRecordV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::MemoryCellAddressWorkerConfigV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NativeFixture {
    pub(super) schema: String,
    pub(super) suite_digest: ContractDigestV1,
    pub(super) split: String,
    pub(super) records: Vec<MemoryCellRecordV1>,
    pub(super) aliases: BTreeMap<ContractIdV1, Vec<String>>,
    pub(super) requests: Vec<Case>,
    pub(super) scope_source: String,
    pub(super) native_execution_claim: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Case {
    pub(super) id: ContractIdV1,
    pub(super) family: String,
    pub(super) language: String,
    pub(super) category: String,
    pub(super) entity: ContractIdV1,
    pub(super) text: String,
    pub(super) at: u64,
    pub(super) since: u64,
    pub(super) max_hops: u8,
    pub(super) max_cells: u8,
    pub(super) expected_operation: Option<MemoryOperationV1>,
    pub(super) expected_value: Value,
}

#[derive(Default, Serialize)]
pub(super) struct Counts {
    pub(super) rows: usize,
    pub(super) routing_correct: usize,
    pub(super) native_correct: usize,
    pub(super) wrong_native_accepts: usize,
    pub(super) negative_routes: usize,
    pub(super) errors: usize,
}

#[derive(Clone, Copy)]
pub(super) enum EvaluationArm {
    FrozenV7,
    FrozenV8,
    CandidateV9,
}

pub(super) fn configured_path(name: &str) -> PathBuf {
    let path =
        PathBuf::from(std::env::var_os(name).unwrap_or_else(|| panic!("explicit {name} required")));
    assert!(path.is_absolute(), "qualification paths must be absolute");
    path
}

pub(super) fn configured_digest(name: &str) -> ContractDigestV1 {
    ContractDigestV1::parse(
        &std::env::var(name).unwrap_or_else(|_| panic!("explicit {name} required")),
    )
    .unwrap()
}

pub(super) fn worker_configuration(
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
        EvaluationArm::FrozenV8 => {
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
        EvaluationArm::CandidateV9 => {
            let addressing = qualification.join("memory-cell-v9/addressing");
            let directories = vec![addressing.clone(), addressing.join("v9_addressing"), frozen];
            (
                addressing,
                directories,
                "qualification_shadow_worker.py",
                "MEMORY_CELL_V9_ADDRESS_MODEL_DIR",
                "MEMORY_CELL_V9_ADDRESS_MODEL_DIGEST",
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

pub(super) fn sources_for(
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
