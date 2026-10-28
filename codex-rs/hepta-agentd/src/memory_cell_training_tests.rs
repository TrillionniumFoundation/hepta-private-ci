use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_types::Digest32;
use serde_json::json;

use crate::MemoryCellLearningDecisionV1;
use crate::MemoryCellTrainerConfigV1;
use crate::MemoryCellTrainingModeV1;
use crate::memory_cell_learning::test_support::LedgerFixture;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_runtime_tests::TestRoute;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_runtime_tests::attach;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request;
use crate::memory_cell_training_test_support::*;

#[tokio::test]
async fn memory_trainer_refuses_missing_import_pins_and_invalid_fit_budget_before_spawn() {
    let owner = ControlFixture::new().await;
    let root = tempfile::tempdir().unwrap();
    let mut config = MemoryCellTrainerConfigV1 {
        python: root.path().join("must-not-execute"),
        qualification_root: root.path().to_path_buf(),
        code_pins: BTreeMap::new(),
        deadline: Duration::from_secs(30),
    };
    assert!(
        config
            .train(
                &owner.store,
                &owner.access(),
                &CognitiveScope::AgentPrivate,
                ContractGenerationV1::new(1).unwrap(),
                budget(),
                MemoryCellTrainingModeV1::Clean
            )
            .await
            .is_err()
    );
    for name in CODE_FILES {
        let path = root.path().join(name);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "# No execution allowed in this configuration test\n").unwrap();
        config.code_pins.insert(
            name.to_string(),
            Digest32::of_bytes(&std::fs::read(path).unwrap()),
        );
    }
    let mut excessive = budget();
    excessive.steps = 0;
    let result = config
        .train(
            &owner.store,
            &owner.access(),
            &CognitiveScope::AgentPrivate,
            ContractGenerationV1::new(1).unwrap(),
            excessive,
            MemoryCellTrainingModeV1::Clean,
        )
        .await;
    assert!(matches!(result, Err(reason) if reason == "memory training budget exceeded"));
    owner.finish().await;
}

#[tokio::test]
#[ignore = "requires pinned NumPy CPU training profile"]
async fn actual_parameter_training_replay_correction_and_clean_rebuild_read_back_through_agentd() {
    let fixture = ControlFixture::new().await;
    let trainer = trainer();
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos()
        .to_string();
    let mut expected = write_new(&fixture, &seed, 0..6).await;
    let first = fit(
        &trainer,
        &fixture,
        /*generation*/ 1,
        MemoryCellTrainingModeV1::Clean,
    )
    .await;
    let rebuilt = fit(
        &trainer,
        &fixture,
        /*generation*/ 1,
        MemoryCellTrainingModeV1::Clean,
    )
    .await;
    for kind in ["semantic", "procedure"] {
        assert_eq!(
            first.receipt()["types"][kind]["parameter_digest"],
            rebuilt.receipt()["types"][kind]["parameter_digest"]
        );
        assert!(rebuilt.receipt()["types"][kind]["training"]["parent_parameters"].is_null());
    }
    let (semantic, procedure) = first.native_payloads();
    let release = ReleaseFixture::from_models_with_training_code(
        first.snapshot(),
        semantic.as_bytes(),
        procedure.as_bytes(),
        first.training_code_digest(),
    );
    let resolver = TrustedTestResolver::new(&fixture);
    let _runtime = attach(&fixture, &release, &resolver);
    let initial_reads = readback(&fixture, &resolver, &expected).await;
    let ledger = LedgerFixture::new();
    let decision =
        MemoryCellLearningDecisionV1::from_training(&first, ledger.context("actual-numpy-fit"))
            .unwrap();
    let signed = ledger.sign(
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision.signing_payload().unwrap(),
    );
    let learning = ledger
        .sink
        .append_training(Digest32::ZERO, &decision, &signed, /*now*/ 50)
        .unwrap();
    assert_eq!(ledger.sink.snapshot().unwrap().records().len(), 1);

    expected.extend(write_new(&fixture, &seed, 6..8).await);
    let replayed = fit(
        &trainer,
        &fixture,
        /*generation*/ 2,
        replay(&release, &first),
    )
    .await;
    for kind in ["semantic", "procedure"] {
        assert_eq!(
            replayed.receipt()["types"][kind]["training"]["parent_parameters"],
            first.receipt()["types"][kind]["parameter_digest"]
        );
    }
    publish(&release, &replayed, /*generation*/ 2);
    let replay_reads = readback(&fixture, &resolver, &expected).await;

    expected[0].semantic = json!({"factor": 19, "label": format!("corrected-new-value:{seed}")});
    fixture
        .store
        .write_memory_cell(
            &fixture.access(),
            &CognitiveScope::AgentPrivate,
            &row(
                &expected[0],
                MemoryCellKindV1::Semantic,
                expected[0].semantic.clone(),
            ),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
    assert!(
        trainer
            .train(
                &fixture.store,
                &fixture.access(),
                &CognitiveScope::AgentPrivate,
                ContractGenerationV1::new(3).unwrap(),
                budget(),
                replay(&release, &replayed)
            )
            .await
            .is_err()
    );
    let corrected = fit(
        &trainer,
        &fixture,
        /*generation*/ 3,
        MemoryCellTrainingModeV1::Clean,
    )
    .await;
    publish(&release, &corrected, /*generation*/ 3);
    let corrected_reads = readback(&fixture, &resolver, &expected).await;

    let withdrawn = expected.pop().unwrap();
    let old_source = corrected
        .snapshot()
        .current(&withdrawn.entity, MemoryCellKindV1::Semantic)
        .unwrap()
        .source_id;
    fixture
        .store
        .forget_memory_cell(
            &fixture.access(),
            &CognitiveScope::AgentPrivate,
            &row(
                &withdrawn,
                MemoryCellKindV1::Semantic,
                withdrawn.semantic.clone(),
            )
            .address(),
            /*expected_revision*/ 1,
            "explicit owner withdrawal",
            crate::memory_cell_runtime::now_unix_seconds().unwrap(),
        )
        .await
        .unwrap();
    assert!(
        trainer
            .train(
                &fixture.store,
                &fixture.access(),
                &CognitiveScope::AgentPrivate,
                ContractGenerationV1::new(4).unwrap(),
                budget(),
                replay(&release, &corrected)
            )
            .await
            .is_err()
    );
    let cleaned = fit(
        &trainer,
        &fixture,
        /*generation*/ 4,
        MemoryCellTrainingModeV1::Clean,
    )
    .await;
    assert!(
        !cleaned
            .snapshot()
            .current_source_ids()
            .contains(&old_source)
    );
    assert!(
        !cleaned
            .native_payloads()
            .0
            .contains(withdrawn.semantic["label"].as_str().unwrap())
    );
    publish(&release, &cleaned, /*generation*/ 4);
    let clean_reads = readback(&fixture, &resolver, &expected).await;
    resolver.set(TestRoute::Read(MemoryOperationV1::Apply));
    let mut withdrawn_query = request(cleaned.snapshot().scope().clone());
    withdrawn_query.entity = withdrawn.entity;
    let denied = fixture
        .client
        .memory_cell_read(withdrawn_query)
        .await
        .unwrap();
    assert_eq!(
        (
            denied.status,
            denied.value,
            denied.source_ids,
            denied.cell_digests
        ),
        (
            MemoryReadStatusV1::Abstain,
            serde_json::Value::Null,
            vec![],
            vec![]
        )
    );

    let report = json!({"schema": "hepta.memory.v7.actual-training-integration.v1", "seed_nonce": seed,
        "training_code_digest": first.training_code_digest().to_string(), "training": [first.receipt(), replayed.receipt(), corrected.receipt(), cleaned.receipt()],
        "readback": [initial_reads, replay_reads, corrected_reads, clean_reads], "clean_parameter_rebuild_equal": true,
        "replay_rejected_after_correction": true, "replay_rejected_after_withdrawal": true,
        "ledger_decision_event_digest": learning.event_digest.to_string(), "ledger_decision_chain_digest": learning.chain_digest.to_string(),
        "independent_future_task_evaluation": false, "natural_language_evaluation": false, "training_receipt_not_an_outcome": true});
    let path = std::env::var_os("MEMORY_CELL_TRAINING_RECEIPT_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::temp_dir().join(format!(
                "hepta-memory-training-receipt-{}.json",
                std::process::id()
            ))
        });
    assert!(path.is_absolute(), "training receipt path must be absolute");
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(&path, serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("MEMORY_CELL_TRAINING_RECEIPT_PATH={}", path.display());
    println!("MEMORY_CELL_TRAINING_RECEIPT={report}");
    fixture.finish().await;
}
