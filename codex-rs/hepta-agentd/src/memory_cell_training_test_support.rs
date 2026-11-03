//! Actual source writes and native/socket readbacks for the pinned NumPy test.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::MemoryCellRecordV1;
use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::execute_memory_cell_program_v1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use crate::MemoryCellFitBudgetV1;
use crate::MemoryCellReplayParentV1;
use crate::MemoryCellTrainerConfigV1;
use crate::MemoryCellTrainingCandidateV1;
use crate::MemoryCellTrainingModeV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_runtime_tests::TestRoute;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request;

pub(crate) const CODE_FILES: [&str; 7] = [
    "memory-cell-v7/training.py",
    "memory-cell-v7/training_worker.py",
    "memory-cell-v7/native_export.py",
    "memory-cell-v6/v6/__init__.py",
    "memory-cell-v6/v6/cells.py",
    "memory-cell-v6/v6/values.py",
    "memory-cell-v6/v6/contracts.py",
];

pub(crate) fn trainer() -> MemoryCellTrainerConfigV1 {
    let python = PathBuf::from(
        std::env::var_os("MEMORY_CELL_TRAINING_PYTHON").expect("explicit pinned NumPy CPU profile"),
    );
    assert!(
        python.is_absolute(),
        "training Python must be an absolute host-supplied path"
    );
    let qualification_root = codex_utils_cargo_bin::repo_root()
        .unwrap()
        .join("qualification");
    let code_pins: BTreeMap<_, _> = CODE_FILES
        .into_iter()
        .map(|name| {
            (
                name.to_string(),
                Digest32::of_bytes(&std::fs::read(qualification_root.join(name)).unwrap()),
            )
        })
        .collect();
    MemoryCellTrainerConfigV1 {
        python,
        qualification_root,
        code_pins,
        deadline: Duration::from_secs(30),
    }
}

pub(crate) fn budget() -> MemoryCellFitBudgetV1 {
    MemoryCellFitBudgetV1 {
        seed: 91_317,
        steps: 600,
        dimension: 48,
        hidden: 64,
        threshold: 0.5,
    }
}

#[derive(Clone)]
pub(crate) struct Expected {
    pub entity: ContractIdV1,
    pub event: i64,
    pub semantic: Value,
    pub procedure: Value,
}

pub(crate) fn row(item: &Expected, kind: MemoryCellKindV1, value: Value) -> MemoryCellRecordV1 {
    MemoryCellRecordV1 {
        schema: "hepta.memory.cell-record.v1".to_string(),
        entity: item.entity.clone(),
        kind,
        effective_at: 20,
        value,
    }
}

pub(crate) async fn write_new(
    fixture: &ControlFixture,
    seed: &str,
    range: std::ops::Range<u32>,
) -> Vec<Expected> {
    let mut expected = Vec::new();
    for index in range {
        let bytes = Digest32::of_bytes(format!("random-owner-values:{seed}:{index}").as_bytes());
        let random = bytes.as_array();
        let opcode = ["affine", "multiply", "add_bias", "clamp"][usize::from(random[3] % 4)];
        let item = Expected {
            entity: ContractIdV1::new(format!(
                "entity:trained-{index}-{}",
                &bytes.to_string()[..12]
            ))
            .unwrap(),
            event: i64::from(u16::from_be_bytes([random[0], random[1]]) % 1_000),
            semantic: json!({"factor": i64::from(random[2] % 13) + 1, "label": format!("owner-value-{}", &bytes.to_string()[12..28])}),
            procedure: json!({"opcode": opcode, "bias": i64::from(random[4] % 17) - 8, "limit": 10_000}),
        };
        for (kind, value) in [
            (MemoryCellKindV1::Event, json!(item.event)),
            (MemoryCellKindV1::Semantic, item.semantic.clone()),
            (MemoryCellKindV1::Procedure, item.procedure.clone()),
        ] {
            fixture
                .store
                .write_memory_cell(
                    &fixture.access(),
                    &CognitiveScope::AgentPrivate,
                    &row(&item, kind, value),
                    MemoryCellWriteModeV1::Create,
                )
                .await
                .unwrap();
        }
        expected.push(item);
    }
    expected
}

pub(crate) async fn fit(
    trainer: &MemoryCellTrainerConfigV1,
    fixture: &ControlFixture,
    generation: u64,
    mode: MemoryCellTrainingModeV1,
) -> MemoryCellTrainingCandidateV1 {
    let candidate = trainer
        .train(
            &fixture.store,
            &fixture.access(),
            &CognitiveScope::AgentPrivate,
            ContractGenerationV1::new(generation).unwrap(),
            budget(),
            mode,
        )
        .await
        .unwrap();
    for kind in ["semantic", "procedure"] {
        let receipt = &candidate.receipt()["types"][kind];
        let training = &receipt["training"];
        assert_eq!(training["kind"], "actual-numpy-tanh-mlp-adam");
        assert_eq!(training["steps"], budget().steps);
        assert!(
            training["final_cross_entropy"].as_f64().unwrap()
                < training["initial_cross_entropy"].as_f64().unwrap()
        );
        assert_ne!(training["initial_parameters"], receipt["parameter_digest"]);
        assert_eq!(
            receipt["written_address_diagnostic"]["correct"],
            receipt["written_address_diagnostic"]["rows"]
        );
        assert_eq!(receipt["independent_future_task_evaluation"], false);
    }
    candidate
}

pub(crate) fn replay(
    release: &ReleaseFixture,
    parent: &MemoryCellTrainingCandidateV1,
) -> MemoryCellTrainingModeV1 {
    let (semantic, procedure) = parent.original_payloads();
    MemoryCellTrainingModeV1::Replay(MemoryCellReplayParentV1 {
        release: Arc::clone(&release.host),
        selected: release.host.load_current().unwrap(),
        semantic_original: semantic.to_string(),
        procedure_original: procedure.to_string(),
    })
}

pub(crate) fn publish(
    release: &ReleaseFixture,
    candidate: &MemoryCellTrainingCandidateV1,
    generation: u64,
) {
    let (semantic, procedure) = candidate.native_payloads();
    let request = release.prepare_models(
        candidate.snapshot(),
        generation,
        semantic.as_bytes(),
        procedure.as_bytes(),
        candidate.training_code_digest(),
    );
    release
        .host
        .publish(request.clone(), candidate.snapshot())
        .unwrap();
    release.install(&request).unwrap();
}

pub(crate) async fn readback(
    fixture: &ControlFixture,
    resolver: &TrustedTestResolver,
    expected: &[Expected],
) -> Value {
    let owner = fixture.snapshot().await;
    let mut count = 0;
    for item in expected {
        let mut query = request(owner.scope().clone());
        query.entity = item.entity.clone();
        let applied =
            execute_memory_cell_program_v1(&item.procedure, item.event, &item.semantic).unwrap();
        for (operation, value) in [
            (MemoryOperationV1::Current, json!(item.event)),
            (MemoryOperationV1::Semantic, item.semantic.clone()),
            (MemoryOperationV1::Procedure, item.procedure.clone()),
            (MemoryOperationV1::Apply, json!(applied)),
        ] {
            resolver.set(TestRoute::Read(operation));
            let result = fixture
                .client
                .memory_cell_read(query.clone())
                .await
                .unwrap();
            assert_eq!(
                (result.status, result.value),
                (MemoryReadStatusV1::Ok, value)
            );
            count += 1;
        }
    }
    json!({"queries": count, "correct": count, "source_cut": owner.owner_cut_digest(),
        "routing": "explicit trusted integration resolver", "independent_future_task_evaluation": false})
}
