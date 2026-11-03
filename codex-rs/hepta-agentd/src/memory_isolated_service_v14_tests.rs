//! Real trained two-layer cells, signed artifact owners and SQLite sources.
//! The fixed resolver is a host-bound fixture, not a language-quality claim.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::learned_test_support::publish_trained;
use super::learned_test_support::train;
use super::test_support::CellFixture;
use super::test_support::generation;
use super::test_support::key;
use super::test_support::now;
use super::test_support::owner_fixture;
use super::test_support::record;
use super::test_support::request;
use super::test_support::snapshot;
use crate::AgentdMemoryInventoryRuntimeV1;
use crate::MemoryCellCandidateV12;
use crate::MemoryInventoryAddressResolverV1;
use crate::MemoryInventoryResolvedAddressV1;
use crate::MemoryIsolatedServiceV14;
use crate::memory_cell_release::test_support::fixture_manifest_template;
use crate::memory_cell_release::test_support::id;
use crate::memory_cell_release::test_support::prepare_payload_request;

struct SemanticResolver;
impl MemoryInventoryAddressResolverV1 for SemanticResolver {
    fn model_digest(&self) -> ContractDigestV1 {
        ContractDigestV1::from_digest(Digest32::of_bytes(b"v14-fixed-semantic-test-resolver"))
            .expect("digest")
    }
    fn resolve<'a>(
        &'a self,
        request: &'a MemoryInventoryRequestV1,
        owner: &'a MemoryInventoryOwnerSnapshotV1,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<Option<MemoryInventoryResolvedAddressV1>, String>>
                + Send
                + 'a,
        >,
    > {
        Box::pin(async move {
            Ok(Some(MemoryInventoryResolvedAddressV1 {
                request: request.clone(),
                operation: MemoryOperationV1::Semantic,
                owner_cut_digest: owner.owner_cut_digest(),
                model_digest: self.model_digest(),
            }))
        })
    }
}

#[tokio::test]
async fn memory_v14_trained_cells_fallback_reject_retrain_restart_and_withdraw() {
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let scope = CognitiveScope::AgentPrivate;
    let mut semantic = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    let mut procedure = CellFixture::new(
        root.path().join("procedure"),
        &owner,
        "cell:procedure",
        MemoryInventoryKindV1::Procedure,
        "flow:a",
    );
    publish_trained(&mut semantic, &owner);
    publish_trained(&mut procedure, &owner);
    let service = Arc::new(
        MemoryIsolatedServiceV14::new(
            &owner,
            generation(1),
            vec![
                (semantic.selector.clone(), Arc::clone(&semantic.host)),
                (procedure.selector.clone(), Arc::clone(&procedure.host)),
            ],
        )
        .expect("independent service"),
    );
    let runtime = AgentdMemoryInventoryRuntimeV1::with_independent_cells(
        owner.owner_agent_id().clone(),
        /*spawn_generation*/ 1,
        scope.clone(),
        Arc::clone(&service),
        Arc::new(SemanticResolver),
    )
    .expect("existing Agentd runtime");
    let query = request(&owner);
    let first = runtime.read(&store, &query).await.expect("real MLP read");
    assert_eq!(
        (
            first.status,
            first.prediction_kind,
            first.cell_digests.len()
        ),
        (
            MemoryReadStatusV1::Ok,
            MemoryPredictionKindV1::ModelPrediction,
            1
        )
    );
    let sibling = service
        .read(
            &store,
            &access,
            &scope,
            &query,
            MemoryOperationV1::Procedure,
        )
        .await
        .expect("procedure");
    store
        .write_memory_inventory(
            &access,
            &scope,
            &record(
                "item:a",
                MemoryInventoryKindV1::Semantic,
                json!({"reserve":14,"pack":2,"limit":15}),
            ),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("correction");
    let fallback = runtime
        .read(&store, &query)
        .await
        .expect("runtime source fallback");
    assert_eq!(
        (
            fallback.value.clone(),
            fallback.prediction_kind,
            fallback.cell_digests.clone()
        ),
        (
            json!({"reserve":14,"pack":2,"limit":15}),
            MemoryPredictionKindV1::SourceEvidence,
            Vec::new()
        )
    );
    assert_ne!(fallback.source_ids, first.source_ids);
    let independent = service
        .read(
            &store,
            &access,
            &scope,
            &query,
            MemoryOperationV1::Procedure,
        )
        .await
        .expect("unaffected procedure");
    assert_eq!(
        (independent.value, independent.cell_digests),
        (sibling.value.clone(), sibling.cell_digests.clone())
    );
    let mixed = service
        .read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
        .await
        .expect("source plus model");
    assert_eq!(
        (
            mixed.value["value"].clone(),
            mixed.prediction_kind,
            mixed.cell_digests.len()
        ),
        (json!(15), MemoryPredictionKindV1::Mixed, 1)
    );
    // Real training on the old cut loses the race; publication must reject it.
    let candidate_generation = 3;
    let old = owner
        .training_projection_v11(&semantic.selector)
        .expect("old source cut");
    let candidate = MemoryCellCandidateV12::from_projection(
        &old,
        generation(candidate_generation),
        &train(&old),
    )
    .expect("actual trained candidate");
    let manifest = candidate
        .bind_manifest(fixture_manifest_template(
            &semantic.config,
            candidate_generation,
            Digest32::of_bytes(b"v14-stale-training-candidate"),
        ))
        .expect("candidate manifest");
    let rejected = prepare_payload_request(
        &semantic.service,
        &semantic.config,
        manifest,
        candidate.bytes().to_vec(),
        candidate_generation,
    );
    let current = snapshot(&store, &access).await;
    assert!(semantic.host.publish(rejected, &current).is_err());
    let after_reject = runtime
        .read(&store, &query)
        .await
        .expect("rejected candidate retains fallback");
    assert_eq!(
        (
            after_reject.value,
            after_reject.prediction_kind,
            after_reject.cell_digests
        ),
        (
            fallback.value.clone(),
            MemoryPredictionKindV1::SourceEvidence,
            Vec::new()
        )
    );
    publish_trained(&mut semantic, &current);
    let learned = runtime
        .read(&store, &query)
        .await
        .expect("new learned version");
    assert_eq!(
        (learned.value, learned.prediction_kind),
        (fallback.value, MemoryPredictionKindV1::ModelPrediction)
    );
    assert_ne!(learned.cell_digests, first.cell_digests);
    drop(runtime);
    drop(service);
    let semantic = semantic.reopen();
    let procedure = procedure.reopen();
    let restored = Arc::new(
        MemoryIsolatedServiceV14::new(
            &current,
            generation(1),
            vec![
                (semantic.selector.clone(), Arc::clone(&semantic.host)),
                (procedure.selector.clone(), Arc::clone(&procedure.host)),
            ],
        )
        .expect("reauthenticated selected owners"),
    );
    let runtime = AgentdMemoryInventoryRuntimeV1::with_independent_cells(
        current.owner_agent_id().clone(),
        /*spawn_generation*/ 1,
        scope.clone(),
        Arc::clone(&restored),
        Arc::new(SemanticResolver),
    )
    .expect("restored runtime");
    assert_eq!(
        runtime
            .read(&store, &query)
            .await
            .expect("restored learned model")
            .cell_digests,
        learned.cell_digests
    );
    store
        .forget_memory_inventory(
            &access,
            &scope,
            &record("item:a", MemoryInventoryKindV1::Semantic, json!(null)).address(),
            /*expected_revision*/ 2,
            "withdraw current source",
            now(),
        )
        .await
        .expect("source withdrawal");
    let refused = runtime
        .read(&store, &query)
        .await
        .expect("bounded refused readout");
    assert_eq!(
        (
            refused.status,
            refused.value,
            refused.source_ids,
            refused.cell_digests
        ),
        (
            MemoryReadStatusV1::Abstain,
            json!(null),
            Vec::new(),
            Vec::new()
        )
    );
    assert_eq!(
        restored
            .read(
                &store,
                &access,
                &scope,
                &query,
                MemoryOperationV1::Procedure
            )
            .await
            .expect("procedure survives")
            .cell_digests,
        sibling.cell_digests
    );
}

#[tokio::test]
async fn memory_v14_preserves_full_fitted_dependencies_and_return_fences() {
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let scope = CognitiveScope::AgentPrivate;
    let mut semantic = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    semantic.selector.keys.push(key("item:b"));
    publish_trained(&mut semantic, &owner);
    let service = MemoryIsolatedServiceV14::new(
        &owner,
        generation(1),
        vec![(semantic.selector.clone(), Arc::clone(&semantic.host))],
    )
    .expect("full-partition cell");
    let query = request(&owner);
    store
        .write_memory_inventory(
            &access,
            &scope,
            &record(
                "item:b",
                MemoryInventoryKindV1::Semantic,
                json!({"reserve":1,"pack":1,"limit":2}),
            ),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("unqueried fitted dependency changes");
    let fallback = service
        .read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
        .await
        .expect("exact current a fallback");
    assert_eq!(
        (fallback.prediction_kind, fallback.cell_digests),
        (MemoryPredictionKindV1::SourceEvidence, Vec::new())
    );
    let current = snapshot(&store, &access).await;
    publish_trained(&mut semantic, &current);
    let prepared = service
        .prepare_read(&query, MemoryOperationV1::Semantic, current)
        .expect("prepared learned read");
    let value = prepared
        .execute(&query, MemoryOperationV1::Semantic)
        .expect("native execution");
    store
        .write_memory_inventory(
            &access,
            &scope,
            &record("item:a", MemoryInventoryKindV1::Event, json!(8)),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("concurrent source commit");
    assert_eq!(
        service
            .finish_read(&store, &access, &scope, &query, prepared, value.clone())
            .await
            .expect("unconsumed event commit must not invalidate the semantic read"),
        value
    );
    let current = snapshot(&store, &access).await;
    let prepared = service
        .prepare_read(&query, MemoryOperationV1::Semantic, current)
        .expect("next query reuses model");
    let value = prepared
        .execute(&query, MemoryOperationV1::Semantic)
        .expect("native execution");
    publish_trained(&mut semantic, &snapshot(&store, &access).await);
    assert!(
        service
            .finish_read(&store, &access, &scope, &query, prepared, value)
            .await
            .is_err()
    );
    assert_eq!(
        service
            .read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
            .await
            .expect("fresh selected version")
            .prediction_kind,
        MemoryPredictionKindV1::ModelPrediction
    );
    let prepared = service
        .prepare_read(
            &query,
            MemoryOperationV1::Semantic,
            snapshot(&store, &access).await,
        )
        .expect("complete fitted partition before concurrent correction");
    let value = prepared
        .execute(&query, MemoryOperationV1::Semantic)
        .expect("native execution");
    store
        .write_memory_inventory(
            &access,
            &scope,
            &record(
                "item:b",
                MemoryInventoryKindV1::Semantic,
                json!({"reserve":3,"pack":1,"limit":8}),
            ),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 2,
            },
        )
        .await
        .expect("unqueried fitted dependency changes during inference");
    assert_eq!(
        service
            .finish_read(&store, &access, &scope, &query, prepared, value)
            .await
            .expect_err("full fitted dependencies remain fenced"),
        (
            MemoryReadStatusV1::Stale,
            "V14 used model full projection changed"
        )
    );
    let mut wrong = query;
    wrong.scope = key("different-scope");
    assert!(
        service
            .read(&store, &access, &scope, &wrong, MemoryOperationV1::Semantic)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn memory_v14_query_fence_ignores_unrelated_source_commits() {
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let scope = CognitiveScope::AgentPrivate;
    let mut semantic = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    let mut procedure = CellFixture::new(
        root.path().join("procedure"),
        &owner,
        "cell:procedure",
        MemoryInventoryKindV1::Procedure,
        "flow:a",
    );
    publish_trained(&mut semantic, &owner);
    publish_trained(&mut procedure, &owner);
    let service = MemoryIsolatedServiceV14::new(
        &owner,
        generation(1),
        vec![
            (semantic.selector.clone(), Arc::clone(&semantic.host)),
            (procedure.selector.clone(), Arc::clone(&procedure.host)),
        ],
    )
    .expect("independent trained cells");
    let query = request(&owner);
    let mut pending = Vec::new();
    for operation in [
        MemoryOperationV1::Current,
        MemoryOperationV1::History,
        MemoryOperationV1::Change,
        MemoryOperationV1::Semantic,
        MemoryOperationV1::Procedure,
        MemoryOperationV1::Apply,
    ] {
        let prepared = service
            .prepare_read(&query, operation, owner.clone())
            .expect("prepared before unrelated writer");
        let value = prepared.execute(&query, operation).expect("execute");
        pending.push((prepared, value));
    }
    // A real writer task commits after all reads acquired their sources and
    // before their return fences. No timer or scheduler race decides the test.
    let writer = tokio::spawn({
        let store = store.clone();
        let access = access.clone();
        let scope = scope.clone();
        async move {
            store
                .write_memory_inventory(
                    &access,
                    &scope,
                    &record(
                        "item:b",
                        MemoryInventoryKindV1::Semantic,
                        json!({"reserve":1,"pack":1,"limit":2}),
                    ),
                    MemoryCellWriteModeV1::Correct {
                        expected_revision: 1,
                    },
                )
                .await
        }
    });
    writer
        .await
        .expect("writer joined")
        .expect("writer committed");
    assert_ne!(
        snapshot(&store, &access).await.owner_cut_digest(),
        owner.owner_cut_digest(),
        "the complete owner cut really changed"
    );
    for (prepared, value) in pending {
        assert_eq!(
            service
                .finish_read(&store, &access, &scope, &query, prepared, value.clone())
                .await
                .expect("unrelated write preserves every read operation"),
            value
        );
    }
}

#[tokio::test]
async fn memory_v14_fallback_fences_reject_required_corrections_and_withdrawals() {
    use MemoryInventoryKindV1::Event;
    use MemoryInventoryKindV1::Hold;
    use MemoryInventoryKindV1::Procedure;
    use MemoryInventoryKindV1::Semantic;
    for (operation, address, kind, corrected) in [
        (MemoryOperationV1::Current, "item:a", Event, json!(8)),
        (MemoryOperationV1::History, "item:a", Event, json!(8)),
        (MemoryOperationV1::Change, "item:a", Event, json!(8)),
        (
            MemoryOperationV1::Semantic,
            "item:a",
            Semantic,
            json!({"reserve":14,"pack":2,"limit":15}),
        ),
        (
            MemoryOperationV1::Procedure,
            "flow:a",
            Procedure,
            json!({"opcodes":[0,0,0,6]}),
        ),
        // Even unchanged hold=false content at a new revision is a new source.
        (MemoryOperationV1::Apply, "item:a", Hold, json!(false)),
    ] {
        let (_root, store, access) = owner_fixture().await;
        let owner = snapshot(&store, &access).await;
        let scope = CognitiveScope::AgentPrivate;
        let service = MemoryIsolatedServiceV14::new(&owner, generation(1), Vec::new())
            .expect("legal source fallback without selected models");
        let query = request(&owner);
        let prepared = service
            .prepare_read(&query, operation, owner)
            .expect("prepared fallback");
        let value = prepared
            .execute(&query, operation)
            .expect("source execution");
        assert_eq!(
            value.prediction_kind,
            MemoryPredictionKindV1::SourceEvidence
        );
        store
            .write_memory_inventory(
                &access,
                &scope,
                &record("item:b", Semantic, json!({"reserve":1,"pack":1,"limit":2})),
                MemoryCellWriteModeV1::Correct {
                    expected_revision: 1,
                },
            )
            .await
            .expect("unrelated source correction");
        assert_eq!(
            service
                .finish_read(&store, &access, &scope, &query, prepared, value.clone())
                .await
                .expect("fallback is also query-local"),
            value
        );
        let prepared = service
            .prepare_read(&query, operation, snapshot(&store, &access).await)
            .expect("before required correction");
        let value = prepared
            .execute(&query, operation)
            .expect("source execution");
        store
            .write_memory_inventory(
                &access,
                &scope,
                &record(address, kind, corrected),
                MemoryCellWriteModeV1::Correct {
                    expected_revision: 1,
                },
            )
            .await
            .expect("required source correction");
        assert_eq!(
            service
                .finish_read(&store, &access, &scope, &query, prepared, value)
                .await
                .expect_err("old output cannot follow a changed required source"),
            (
                MemoryReadStatusV1::Stale,
                "V14 required sources changed before use"
            )
        );
        let prepared = service
            .prepare_read(&query, operation, snapshot(&store, &access).await)
            .expect("new read uses corrected source");
        let value = prepared
            .execute(&query, operation)
            .expect("corrected execution");
        store
            .forget_memory_inventory(
                &access,
                &scope,
                &record(address, kind, json!(null)).address(),
                /*expected_revision*/ 2,
                "withdraw required source during read",
                now(),
            )
            .await
            .expect("required source tombstone");
        assert_eq!(
            service
                .finish_read(&store, &access, &scope, &query, prepared, value)
                .await
                .expect_err("withdrawn source cannot authorize an old output"),
            (MemoryReadStatusV1::Stale, "V14 support withdrawn")
        );
        assert!(
            service
                .read(&store, &access, &scope, &query, operation)
                .await
                .is_err(),
            "fallback cannot resurrect a deleted source"
        );
    }
}

#[tokio::test]
async fn memory_v14_artifact_withdrawal_fences_old_read_and_cold_selection() {
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let scope = CognitiveScope::AgentPrivate;
    let mut semantic = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    publish_trained(&mut semantic, &owner);
    let service = MemoryIsolatedServiceV14::new(
        &owner,
        generation(1),
        vec![(semantic.selector.clone(), Arc::clone(&semantic.host))],
    )
    .expect("selected model");
    let query = request(&owner);
    let prepared = service
        .prepare_read(&query, MemoryOperationV1::Semantic, owner.clone())
        .expect("before artifact withdrawal");
    let value = prepared
        .execute(&query, MemoryOperationV1::Semantic)
        .expect("trained inference");
    assert_eq!(
        value.prediction_kind,
        MemoryPredictionKindV1::ModelPrediction
    );
    let mut withdrawals = semantic
        .service
        .lock()
        .expect("artifact owner")
        .withdrawal_registry()
        .clone();
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdraw-v14-semantic"),
            dataset_digest: semantic
                .publication
                .admission
                .validated_manifest
                .manifest
                .lineage_digests[0],
            source_tombstone_digest: Digest32::of_bytes(b"v14-artifact-owner-withdrawal"),
            authority_id: id("memory-dataset-owner"),
            credential_chain_digest: Digest32::of_bytes(b"dataset-credential"),
            signing_key_digest: Digest32::of_bytes(b"dataset-signer"),
            authority_epoch: 1,
            issued_at: now() as u64,
        })
        .expect("authoritative withdrawal frontier");
    semantic
        .service
        .lock()
        .expect("artifact owner")
        .install_withdrawal_frontier(withdrawals.clone())
        .expect("advance live artifact frontier");
    assert_eq!(
        service
            .finish_read(&store, &access, &scope, &query, prepared, value)
            .await
            .expect_err("old learned output is revoked"),
        (
            MemoryReadStatusV1::Stale,
            "V14 used publication changed before use"
        )
    );
    assert!(semantic.readmit_same_version().is_err());
    // Artifact withdrawal revokes learned bytes, not an independently current
    // owner source. A fresh read may still select that explicit source fallback.
    let fallback = service
        .read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
        .await
        .expect("current owner source is still legal");
    assert_eq!(
        (fallback.prediction_kind, fallback.cell_digests.clone()),
        (MemoryPredictionKindV1::SourceEvidence, Vec::new())
    );
    drop(service);
    semantic.config.withdrawal_registry = withdrawals;
    let semantic = semantic.reopen_unselected();
    assert!(
        semantic.try_install().is_err(),
        "old admission stays revoked after restart"
    );
    assert!(semantic.host.load_current().is_err());
    let restored = MemoryIsolatedServiceV14::new(
        &snapshot(&store, &access).await,
        generation(1),
        vec![(semantic.selector.clone(), Arc::clone(&semantic.host))],
    )
    .expect("cold service cannot manufacture model eligibility");
    let cold = restored
        .read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
        .await
        .expect("cold legal source fallback");
    assert_eq!(
        (
            cold.value,
            cold.source_ids,
            cold.prediction_kind,
            cold.cell_digests
        ),
        (
            fallback.value,
            fallback.source_ids,
            MemoryPredictionKindV1::SourceEvidence,
            Vec::new()
        )
    );
}
