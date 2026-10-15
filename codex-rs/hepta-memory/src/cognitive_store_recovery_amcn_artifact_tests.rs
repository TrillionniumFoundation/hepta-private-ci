//! Real two-owner research exercise: original Learning Artifacts withdrawal
//! registry + original CognitiveStore SQLite; neither is mocked here.
//! Local mutex is not a signed or durable ArtifactOwnerHost production fence.
use super::*;

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_learning_artifacts::{
    ArtifactKind, DatasetWithdrawalNoticeV1, DatasetWithdrawalScopeV1,
    LearningArtifactManifestV2, ProvenanceModeV1,
    admit_manifest_at_withdrawal_head_v3,
};
use codex_hepta_types::{Generation, StableId};
use tempfile::TempDir;

use crate::cognitive_test_support::{agent_id, layout, source};

fn id(text: &str) -> StableId {
    StableId::new(text).expect("test identifier")
}
fn d(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

fn fixtures() -> (
    Arc<Mutex<DatasetWithdrawalRegistry>>,
    WithdrawalBoundArtifactAdmissionV3,
    Digest32,
    Digest32,
) {
    let dataset = d("amcn-actual-training-source-set");
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("amcn-test-artifact-authority"),
        registry_id: id("amcn-test-withdrawal-registry"),
        scope_id: id("amcn-test-owner-scope"),
    };
    let registry = DatasetWithdrawalRegistry::new_scoped(scope);
    let head = registry.head_digest();
    let manifest = LearningArtifactManifestV2 {
        artifact_id: id("amcn-test-head"),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(1).expect("test generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![dataset],
        lineage_digests: vec![d("amcn-source-lineage")],
        predecessor_ids: vec![],
        rollback_predecessor: None,
        bytes_digest: d("test-head-safetensors"),
        encoded_size_bytes: 2048,
        training_code_digest: d("training-source"),
        runtime_tuple_digest: d("model-tuple"),
        device_profile_digest: d("device-profile"),
        objective_class_digest: d("evidence-selection"),
        compatibility_digest: d("shared-stem"),
        schema_profile_digest: d("typed-memory-cell"),
        normalization_digest: d("frozen-source-features"),
        producer_id: id("amcn-test-trainer"),
        created_at: 10,
        expires_at: 100,
    };
    let admitted = admit_manifest_at_withdrawal_head_v3(&registry, head, manifest, 20)
        .expect("existing Artifacts Owner admission contract");
    assert!(!admitted.authority.grants_any());
    (Arc::new(Mutex::new(registry)), admitted, head, dataset)
}

fn withdraw(dataset: Digest32) -> DatasetWithdrawalNoticeV1 {
    DatasetWithdrawalNoticeV1 {
        notice_id: id("amcn-test-withdrawal"),
        dataset_digest: dataset,
        source_tombstone_digest: d("durable-tombstone"),
        authority_id: id("test-owner"),
        credential_chain_digest: d("test-credential"),
        signing_key_digest: d("test-key"),
        authority_epoch: 1,
        issued_at: 21,
    }
}

#[tokio::test]
async fn amcn_shadow_two_owner_withdrawal_denies_old_head_when_cognitive_cut_is_unchanged() {
    let temp = TempDir::new().expect("isolated source owner");
    let agent = agent_id(226);
    let store = CognitiveStore::open(&layout(&temp, &agent)).await.expect("CognitiveStore");
    let access = CognitiveAccess::agent_private(agent);
    let cognitive_scope = CognitiveScope::AgentPrivate;
    store.append_source(
        &access, &source(cognitive_scope.clone(), "training-evidence", "original source"),
    ).await.expect("actual source write");
    let current_cut = store.recovery_anchor().await.expect("complete source owner cut");
    let (withdrawals, admission, expected_head, dataset) = fixtures();
    let called = AtomicBool::new(false);

    let admitted = store.with_amcn_shadow_artifact_and_source(
        &access, &cognitive_scope, &current_cut,
        &withdrawals, &admission, expected_head, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 20,
        || {
            called.store(true, Ordering::SeqCst);
            Ok::<_, CognitiveStoreError>(7_u64)
        },
    ).await.expect("bounded CURRENT research candidate");
    assert_eq!(admitted, 7);
    assert!(called.load(Ordering::SeqCst));
    assert!(!AMCN_TWO_OWNER_SHADOW_PRODUCTION_ACCEPTED);

    withdrawals.lock().await.append(withdraw(dataset))
        .expect("real Artifacts Owner withdrawal");
    assert_eq!(
        store.recovery_anchor().await.expect("unchanged original source"),
        current_cut,
        "artifact withdrawal must be tested even when CognitiveStore has not changed"
    );
    called.store(false, Ordering::SeqCst);
    let stale = store.with_amcn_shadow_artifact_and_source(
        &access, &cognitive_scope, &current_cut,
        &withdrawals, &admission, expected_head, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 21,
        || {
            called.store(true, Ordering::SeqCst);
            Ok::<_, CognitiveStoreError>(())
        },
    ).await;
    assert!(matches!(stale, Err(CognitiveStoreError::AccessDenied(_))));
    assert!(!called.load(Ordering::SeqCst));
    let new_head = withdrawals.lock().await.head_digest();
    let stolen = store.with_amcn_shadow_artifact_and_source(
        &access, &cognitive_scope, &current_cut,
        &withdrawals, &admission, new_head, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 21,
        || {
            called.store(true, Ordering::SeqCst);
            Ok::<_, CognitiveStoreError>(())
        },
    ).await;
    assert!(matches!(stolen, Err(CognitiveStoreError::AccessDenied(_))));
    assert!(!called.load(Ordering::SeqCst));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn amcn_shadow_two_owner_holds_artifact_and_sqlite_locks_during_actual_callback() {
    let temp = TempDir::new().expect("isolated source owner");
    let agent = agent_id(227);
    let root = layout(&temp, &agent);
    let first = CognitiveStore::open(&root).await.expect("first original Source Store");
    let writer = CognitiveStore::open(&root).await.expect("real competing Source Store");
    let access = CognitiveAccess::agent_private(agent);
    let scope = CognitiveScope::AgentPrivate;
    first.append_source(&access, &source(scope.clone(), "seed", "present"))
        .await.expect("seed");
    let original_cut = first.recovery_anchor().await.expect("source current cut");
    let (withdrawals, admission, original_head, dataset) = fixtures();

    let (artifact_go_tx, artifact_go_rx) = mpsc::channel::<()>();
    let (artifact_started_tx, artifact_started_rx) = mpsc::channel();
    let (artifact_done_tx, artifact_done_rx) = mpsc::channel();
    let withdrawals_writer = Arc::clone(&withdrawals);
    let artifact_thread = std::thread::spawn(move || {
        artifact_go_rx.recv_timeout(Duration::from_secs(5))
            .expect("wait until BOTH owner locks acquired");
        artifact_started_tx.send(()).expect("withdrawal attempt signaled");
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all().build().expect("independent Artifact Owner reactor");
        let result = rt.block_on(async {
            withdrawals_writer.lock().await.append(withdraw(dataset))
        });
        artifact_done_tx.send(result).expect("withdrawal receipt");
    });

    let (source_go_tx, source_go_rx) = mpsc::channel::<()>();
    let (source_started_tx, source_started_rx) = mpsc::channel();
    let (source_done_tx, source_done_rx) = mpsc::channel();
    let writer_access = access.clone();
    let writer_scope = scope.clone();
    let source_thread = std::thread::spawn(move || {
        source_go_rx.recv_timeout(Duration::from_secs(5))
            .expect("wait until BOTH owner locks acquired");
        source_started_tx.send(()).expect("source attempt signaled");
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all().build().expect("independent Source Owner reactor");
        let result = rt.block_on(writer.append_source(
            &writer_access,
            &source(writer_scope, "concurrent-source", "new source"),
        ));
        source_done_tx.send(result).expect("source write receipt");
    });

    let observed = first.with_amcn_shadow_artifact_and_source(
        &access, &scope, &original_cut,
        &withdrawals, &admission, original_head, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 20,
        || {
            artifact_go_tx.send(()).expect("release competing artifact writer");
            source_go_tx.send(()).expect("release competing source writer");
            artifact_started_rx.recv_timeout(Duration::from_secs(5))
                .expect("withdrawal started");
            source_started_rx.recv_timeout(Duration::from_secs(5))
                .expect("source write started");
            assert!(matches!(
                artifact_done_rx.recv_timeout(Duration::from_millis(120)),
                Err(mpsc::RecvTimeoutError::Timeout),
            ), "Artifact Owner withdrawal committed while source/model lease held");
            assert!(matches!(
                source_done_rx.recv_timeout(Duration::from_millis(120)),
                Err(mpsc::RecvTimeoutError::Timeout),
            ), "CognitiveStore source write committed while lease held");
            Ok::<_, CognitiveStoreError>(17_u64)
        },
    ).await.expect("both source and Artifact locks held");
    assert_eq!(observed, 17);

    artifact_thread.join().expect("artifact writer thread");
    source_thread.join().expect("source writer thread");
    assert!(artifact_done_rx.recv_timeout(Duration::from_secs(5))
            .expect("withdrawal response").is_ok());
    assert!(source_done_rx.recv_timeout(Duration::from_secs(5))
            .expect("source response").is_ok());

    assert_ne!(first.recovery_anchor().await.expect("updated source"), original_cut);
    assert_ne!(withdrawals.lock().await.head_digest(), original_head);
    let forbidden = first.with_amcn_shadow_artifact_and_source(
        &access, &scope, &original_cut,
        &withdrawals, &admission, original_head, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 21,
        || Ok::<_, CognitiveStoreError>(0_u8),
    ).await;
    assert!(matches!(forbidden, Err(CognitiveStoreError::AccessDenied(_))));
}

#[tokio::test]
async fn amcn_shadow_two_owner_invalid_scope_admission_and_error_never_mint_authority() {
    let temp = TempDir::new().expect("isolated source owner");
    let agent = agent_id(228);
    let store = CognitiveStore::open(&layout(&temp, &agent)).await.expect("Source Store");
    let access = CognitiveAccess::agent_private(agent);
    let scope = CognitiveScope::AgentPrivate;
    let original = store.recovery_anchor().await.expect("current complete source cut");
    let (withdrawals, admission, head, dataset) = fixtures();
    let called = AtomicBool::new(false);
    let error = store.with_amcn_shadow_artifact_and_source(
        &access, &scope, &original,
        &withdrawals, &admission, Digest32::ZERO, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 20,
        || {
            called.store(true, Ordering::SeqCst);
            Ok::<_, CognitiveStoreError>(())
        },
    ).await;
    assert!(matches!(error, Err(CognitiveStoreError::AccessDenied(_))));
    assert!(!called.load(Ordering::SeqCst));

    let wrong = CognitiveAccess::agent_private(agent_id(229));
    let error = store.with_amcn_shadow_artifact_and_source(
        &wrong, &scope, &original, &withdrawals, &admission, head, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 20,
        || {
            called.store(true, Ordering::SeqCst);
            Ok::<_, CognitiveStoreError>(())
        },
    ).await;
    assert!(matches!(error, Err(CognitiveStoreError::AccessDenied(_))));
    assert!(!called.load(Ordering::SeqCst));
    // All three pins are required to identify the exact selected Head and
    // its immutable source-training set, not merely a healthy registry head.
    for (candidate, runtime_tuple, training_set) in [
        (id("another-head"), d("model-tuple"), dataset),
        (id("amcn-test-head"), d("different-runtime"), dataset),
        (id("amcn-test-head"), d("model-tuple"), d("different-training-set")),
    ] {
        called.store(false, Ordering::SeqCst);
        let denied = store.with_amcn_shadow_artifact_and_source(
            &access, &scope, &original, &withdrawals, &admission, head,
            &candidate, runtime_tuple, training_set, 20,
            || {
                called.store(true, Ordering::SeqCst);
                Ok::<_, CognitiveStoreError>(())
            },
        ).await;
        assert!(matches!(denied, Err(CognitiveStoreError::AccessDenied(_))));
        assert!(!called.load(Ordering::SeqCst));
    }

    let error = store.with_amcn_shadow_artifact_and_source(
        &access, &scope, &original, &withdrawals, &admission, head, 
        &id("amcn-test-head"), d("model-tuple"), dataset, 20,
        || Err::<(), _>(CognitiveStoreError::Invalid("research candidate refused".into())),
    ).await;
    assert!(matches!(error, Err(CognitiveStoreError::Invalid(_))));
    store.append_source(&access, &source(scope, "after-error", "actual source"))
        .await.expect("both owner locks were released after callback error");
}
