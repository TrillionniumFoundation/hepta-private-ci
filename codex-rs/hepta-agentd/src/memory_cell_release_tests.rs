use std::fs;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_learning_artifacts::validate_artifact_publication_v3;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::MemoryCellRecordV1;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;

use super::LoadedMemoryCellBundleV1;
use super::MemoryCellBundleCandidateV1;
use super::test_support::ReleaseFixture;
use super::test_support::digest;
use super::test_support::id;
use super::test_support::single_value_model;

pub(super) async fn owner_fixture() -> (TempDir, CognitiveStore, CognitiveAccess, CognitiveScope) {
    let directory = TempDir::new().expect("cognitive root");
    let fleet = directory.path().join("fleet");
    fs::create_dir(&fleet).expect("fleet directory");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000091").expect("owner");
    let layout = HeptaFleetRoot::parse(fleet)
        .expect("fleet")
        .layout()
        .agent(&owner);
    let store = CognitiveStore::open(&layout)
        .await
        .expect("actual cognitive owner");
    let workspace = Sha256Digest::for_bytes(b"release-integration");
    let access = CognitiveAccess::workspace_private(owner, workspace.clone());
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace,
    };
    for (kind, value) in [
        (MemoryCellKindV1::Event, json!(9)),
        (
            MemoryCellKindV1::Semantic,
            json!({"factor":3,"label":"owner semantic"}),
        ),
        (
            MemoryCellKindV1::Procedure,
            json!({"opcode":"affine","bias":2,"limit":1000}),
        ),
    ] {
        let record = MemoryCellRecordV1 {
            schema: "hepta.memory.cell-record.v1".to_string(),
            entity: ContractIdV1::new("meter:release-test").expect("entity"),
            kind,
            effective_at: 20,
            value,
        };
        store
            .write_memory_cell(&access, &scope, &record, MemoryCellWriteModeV1::Create)
            .await
            .expect("real typed write");
    }
    (directory, store, access, scope)
}

#[tokio::test]
async fn signed_publication_retry_reopen_and_generation_replace_use_the_real_owner() {
    let (_directory, store, access, scope) = owner_fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, super::now().expect("time") as i64)
        .await
        .expect("snapshot");
    let fixture = ReleaseFixture::new(&snapshot);
    let loaded = fixture
        .host
        .load_current()
        .expect("authenticated current bundle");
    assert_eq!(
        loaded
            .semantic()
            .predict("meter:release-test")
            .expect("semantic inference")
            .value,
        Some(json!({"factor":3,"label":"owner semantic"}))
    );
    assert_eq!(
        loaded
            .procedure()
            .predict("meter:release-test")
            .expect("procedure inference")
            .value,
        Some(json!({"opcode":"affine","bias":2,"limit":1000}))
    );
    let receipt = fixture
        .host
        .publish(fixture.initial_request.clone(), &snapshot)
        .expect("exact acknowledged retry");
    assert_eq!(
        fixture
            .host
            .publish(fixture.initial_request.clone(), &snapshot)
            .expect("repeat retry"),
        receipt
    );
    assert_eq!(
        fixture
            .service
            .lock()
            .expect("service")
            .registry()
            .records()
            .len(),
        1
    );
    let current = fixture.initial_request.signed_current_head.clone();
    let fixture = fixture.reopen(current);
    assert!(
        fixture.host.load_current().is_err(),
        "restart does not invent a selection"
    );
    assert_eq!(
        fixture
            .host
            .publish(fixture.initial_request.clone(), &snapshot)
            .expect("durable retry after reopen"),
        receipt
    );
    fixture
        .install(&fixture.initial_request)
        .expect("fresh selection after reopen");
    assert!(
        fixture.host.revalidate(&loaded).is_err(),
        "old consumer belongs to the previous configured selection"
    );
    let first = fixture.host.load_current().expect("reopened model");
    let successor = fixture.prepare(&snapshot, 2);
    fixture
        .host
        .publish(successor.clone(), &snapshot)
        .expect("second durable generation");
    assert!(
        fixture.host.revalidate(&first).is_err(),
        "head extension invalidates old readers before replacement"
    );
    assert!(
        fixture.host.load_current().is_err(),
        "registration is not selection"
    );
    fixture
        .install(&successor)
        .expect("independent successor selection");
    let second = fixture.host.load_current().expect("successor reader");
    assert_eq!(second.generation().get(), 2);
    assert!(fixture.host.revalidate(&first).is_err());
    assert!(
        fixture.install(&fixture.initial_request).is_err(),
        "signed old candidate cannot roll back this consumer"
    );
    fixture
        .host
        .revalidate(&second)
        .expect("rejected rollback leaves selected successor intact");
}

#[tokio::test]
async fn interrupted_payload_write_reopens_and_resumes_the_existing_publication_transaction() {
    let (_directory, store, access, scope) = owner_fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, super::now().expect("time") as i64)
        .await
        .expect("snapshot");
    let fixture = ReleaseFixture::new(&snapshot);
    let next = fixture.prepare(&snapshot, 2);
    let blocked_payload = fixture.payload_path(&next);
    fs::create_dir(&blocked_payload).expect("inject durable payload target failure");
    assert!(fixture.host.publish(next.clone(), &snapshot).is_err());
    assert_eq!(
        fixture.service.lock().expect("service").recovery_required(),
        Some(&next.operation_id)
    );
    let mut unrelated = fixture.initial_request.clone();
    unrelated.operation_id = id("unrelated-publication");
    assert!(
        fixture.host.publish(unrelated, &snapshot).is_err(),
        "nonterminal operation blocks unrelated work"
    );
    let current = fixture.initial_request.signed_current_head.clone();
    let fixture = fixture.reopen(current);
    assert_eq!(
        fixture.service.lock().expect("service").recovery_required(),
        Some(&next.operation_id)
    );
    fs::remove_dir(blocked_payload).expect("remove injected failure");
    let recovered = fixture
        .host
        .publish(next.clone(), &snapshot)
        .expect("resume durable transaction");
    assert_eq!(
        fixture
            .host
            .publish(next.clone(), &snapshot)
            .expect("recovered retry"),
        recovered
    );
    assert!(
        fixture
            .service
            .lock()
            .expect("service")
            .recovery_required()
            .is_none()
    );
    fixture.install(&next).expect("select recovered generation");
    assert_eq!(
        fixture
            .host
            .load_current()
            .expect("recovered read")
            .generation()
            .get(),
        2
    );
}

#[tokio::test]
async fn live_dataset_and_complete_lineage_withdrawals_reject_self_consistent_public_receipts() {
    for withdraw_lineage in [false, true] {
        let (_directory, store, access, scope) = owner_fixture().await;
        let snapshot = store
            .memory_cell_snapshot(&access, &scope, super::now().expect("time") as i64)
            .await
            .expect("snapshot");
        let fixture = ReleaseFixture::new(&snapshot);
        let loaded = fixture
            .host
            .load_current()
            .expect("reader before withdrawal");
        let before = fixture
            .service
            .lock()
            .expect("service")
            .registry()
            .snapshot()
            .head_digest;
        let mut withdrawals = fixture
            .service
            .lock()
            .expect("service")
            .withdrawal_registry()
            .clone();
        let removed = if withdraw_lineage {
            fixture
                .initial_request
                .admission
                .validated_manifest
                .manifest
                .lineage_digests[0]
        } else {
            snapshot.owner_cut_digest().digest()
        };
        withdrawals
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("withdraw-memory-training"),
                dataset_digest: removed,
                source_tombstone_digest: digest("owner-source-tombstone"),
                authority_id: id("memory-dataset-owner"),
                credential_chain_digest: digest("dataset-credential"),
                signing_key_digest: digest("dataset-signer"),
                authority_epoch: 1,
                issued_at: super::now().expect("time"),
            })
            .expect("actual withdrawal registry append");
        fixture
            .service
            .lock()
            .expect("service")
            .install_withdrawal_frontier(withdrawals.clone())
            .expect("owner frontier update");
        assert_eq!(
            fixture
                .service
                .lock()
                .expect("service")
                .registry()
                .snapshot()
                .head_digest,
            before
        );
        assert!(
            fixture.host.revalidate(&loaded).is_err(),
            "withdrawal fails even without registry CURRENT changing"
        );
        let mut forged = fixture.initial_request.clone();
        forged.admission.withdrawal_head_digest = withdrawals.head_digest();
        let mut digest_bytes = b"hepta.learning-artifacts.withdrawal-bound-admission.v3".to_vec();
        for value in [
            forged.admission.validated_manifest.manifest_digest,
            forged.admission.withdrawal_scope_digest,
            forged.admission.withdrawal_head_digest,
        ] {
            digest_bytes.extend_from_slice(value.as_array());
        }
        digest_bytes.extend_from_slice(&forged.admission.admitted_at.to_be_bytes());
        forged.admission.admission_digest = Digest32::of_bytes(&digest_bytes);
        validate_artifact_publication_v3(
            &forged.admission,
            &withdrawals,
            super::now().expect("time"),
        )
        .expect("a public receipt hash alone cannot prove eligibility");
        assert!(
            fixture.host.publish(forged, &snapshot).is_err(),
            "real registry eligibility rejects forged fresh-head claims"
        );
        assert!(fixture.host.load_current().is_err());
    }
}

#[tokio::test]
async fn typed_bundle_and_parameter_manifest_reject_rebinding_or_incomplete_owner_evidence() {
    let (_directory, store, access, scope) = owner_fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, super::now().expect("time") as i64)
        .await
        .expect("snapshot");
    let fixture = ReleaseFixture::new(&snapshot);
    let request = &fixture.initial_request;
    let valid: Value = serde_json::from_slice(&request.payload).expect("bundle wire");
    let mut wrong_kind = valid.clone();
    wrong_kind["semantic"] = wrong_kind["procedure"].clone();
    let mut missing_lineage = valid.clone();
    missing_lineage["lineage_sources"]
        .as_array_mut()
        .expect("lineage")
        .remove(0);
    for invalid in [wrong_kind, missing_lineage] {
        let bytes = serde_json::to_vec(&invalid).expect("invalid bytes");
        assert!(LoadedMemoryCellBundleV1::decode(&bytes, Digest32::of_bytes(&bytes)).is_err());
    }
    let mut wrong_cut = valid;
    wrong_cut["owner_cut_digest"] = json!(digest("different-owner-cut").to_string());
    let bytes = serde_json::to_vec(&wrong_cut).expect("rebound bytes");
    let decoded = LoadedMemoryCellBundleV1::decode(&bytes, Digest32::of_bytes(&bytes))
        .expect("untrusted typed payload parses");
    assert!(decoded.validate_owner_snapshot(&snapshot).is_err());
    let procedure = single_value_model(&snapshot, MemoryCellKindV1::Procedure);
    assert!(
        MemoryCellBundleCandidateV1::from_owner_snapshot(
            &snapshot,
            codex_hepta_cognitive_types::hnmf::ContractGenerationV1::new(1).expect("generation"),
            &procedure,
            &procedure
        )
        .is_err()
    );
    for mutation in 0..4 {
        let mut invalid = request.clone();
        let manifest = &mut invalid.admission.validated_manifest.manifest;
        match mutation {
            0 => manifest.kind = codex_hepta_learning_artifacts::ArtifactKind::Model,
            1 => manifest.runtime_tuple_digest = digest("other-parameters"),
            2 => manifest.source_dataset_digests = vec![digest("other-owner-cut")],
            _ => {
                manifest.lineage_digests.pop();
            }
        }
        assert!(fixture.host.publish(invalid, &snapshot).is_err());
    }
    assert_eq!(
        fixture
            .service
            .lock()
            .expect("service")
            .registry()
            .records()
            .len(),
        1
    );
    fixture
        .host
        .load_current()
        .expect("rejected mutations did not publish or poison the existing model");
}
