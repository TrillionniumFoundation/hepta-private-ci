use std::sync::Arc;

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_memory::MemoryTrainingSelectorV11;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::MemoryServingPlanV11;
use super::test_support::CellFixture;
use super::test_support::analytic_model;
use super::test_support::generation;
use super::test_support::key;
use super::test_support::now;
use super::test_support::owner_fixture;
use super::test_support::record;
use super::test_support::request;
use super::test_support::snapshot;
use crate::MemoryCellCandidateV11;
use crate::memory_cell_release::test_support::id;

#[tokio::test]
async fn memory_v11_candidate_binds_the_complete_owner_partition_and_acquisition_cut() {
    let (_root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let mut selector = MemoryTrainingSelectorV11 {
        cell_id: key("cell:semantic"),
        kind: MemoryInventoryKindV1::Semantic,
        keys: vec![key("item:a")],
    };
    let one = owner
        .training_projection_v11(&selector)
        .expect("owner partition");
    let payload = analytic_model(&one);
    MemoryCellCandidateV11::from_projection(&one, generation(1), &payload)
        .expect("bound candidate");
    selector.keys.push(key("item:b"));
    let all = owner
        .training_projection_v11(&selector)
        .expect("larger owner partition");
    assert!(
        MemoryCellCandidateV11::from_projection(&all, generation(1), &payload).is_err(),
        "numeric payload cannot omit a declared training dependency"
    );
    let mut modified: serde_json::Value = serde_json::from_slice(&payload).expect("numeric DTO");
    modified["owner_cut_sha256"] = json!(Digest32::of_bytes(b"caller-chosen-cut").to_string());
    assert!(
        MemoryCellCandidateV11::from_projection(
            &one,
            generation(1),
            &serde_json::to_vec(&modified).expect("modified payload")
        )
        .is_err(),
        "numeric acquisition cut must match the owner-produced original cut"
    );
}

#[tokio::test]
async fn memory_v11_independent_cells_reuse_weights_with_fresh_queries_and_replace_one_version() {
    use MemoryInventoryKindV1::Event;
    use MemoryInventoryKindV1::Hold;
    use MemoryInventoryKindV1::Procedure;
    use MemoryInventoryKindV1::Semantic;
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let mut semantic = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        Semantic,
        "item:a",
    );
    let procedure = CellFixture::new(
        root.path().join("procedure"),
        &owner,
        "cell:procedure",
        Procedure,
        "flow:a",
    );
    let releases = || vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)];
    let plan =
        MemoryServingPlanV11::prepare(&owner, generation(1), releases()).expect("immutable plan");
    let checkpoint = plan.checkpoint().expect("pins");
    let query = request(&owner);
    let scope = CognitiveScope::AgentPrivate;
    let first = plan
        .read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
        .await
        .expect("actual residual inference and interpreter");
    assert_eq!(first.value["value"], json!(14));
    let sibling = procedure.host.load_current().expect("procedure pointer");
    // Query sources and another semantic cell can change without republishing.
    for row in [
        record("item:a", Event, json!(9)),
        record("item:b", Semantic, json!({"reserve":1,"pack":1,"limit":2})),
    ] {
        store
            .write_memory_inventory(
                &access,
                &scope,
                &row,
                MemoryCellWriteModeV1::Correct {
                    expected_revision: 1,
                },
            )
            .await
            .expect("unrelated to both fits");
    }
    let fresh = plan
        .read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
        .await
        .expect("reuse unchanged weights with new query evidence");
    assert_eq!(fresh.value["value"], json!(6));
    assert_eq!(fresh.cells, first.cells);
    assert_eq!(fresh.plan_digest, first.plan_digest);
    assert_ne!(fresh.query_cut_digest, first.query_cut_digest);
    assert_ne!(fresh.source_ids, first.source_ids);
    store
        .write_memory_inventory(
            &access,
            &scope,
            &record("item:a", Hold, json!(true)),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("current hold");
    assert!(
        plan.read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
            .await
            .is_err()
    );
    store
        .write_memory_inventory(
            &access,
            &scope,
            &record("item:a", Hold, json!(false)),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 2,
            },
        )
        .await
        .expect("release hold");
    semantic
        .host
        .sleep_selected()
        .expect("evict numerical cache");
    assert_eq!(
        plan.read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
            .await
            .expect("wake exact selected bytes")
            .value,
        fresh.value
    );
    store
        .write_memory_inventory(
            &access,
            &scope,
            &record(
                "item:a",
                Semantic,
                json!({"reserve":14,"pack":2,"limit":15}),
            ),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("relevant correction");
    assert!(
        plan.read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
            .await
            .is_err()
    );
    let corrected = snapshot(&store, &access).await;
    let sibling_plan =
        MemoryServingPlanV11::prepare(&corrected, generation(2), vec![Arc::clone(&procedure.host)])
            .expect("sibling remains selected");
    assert_eq!(
        sibling_plan
            .read(
                &store,
                &access,
                &scope,
                &query,
                MemoryOperationV1::Procedure
            )
            .await
            .expect("independent sibling executes")
            .value,
        json!({"opcodes":[1,2,3,6]})
    );
    semantic.replace(&corrected);
    let next = MemoryServingPlanV11::prepare(
        &corrected,
        generation(3),
        vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)],
    )
    .expect("new immutable version tuple");
    assert!(Arc::ptr_eq(
        &sibling,
        &procedure
            .host
            .load_current()
            .expect("same sibling selection")
    ));
    assert_eq!(
        next.read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
            .await
            .expect("new semantic with unchanged procedure")
            .value["value"],
        json!(10)
    );
    let old_semantic = first
        .cells
        .iter()
        .find(|cell| cell.cell_id.as_str() == "cell:semantic")
        .expect("semantic pin");
    let new_semantic = next
        .versions()
        .iter()
        .find(|cell| cell.cell_id == old_semantic.cell_id)
        .expect("new semantic pin");
    assert_eq!(
        new_semantic.generation.get(),
        old_semantic.generation.get() + 1
    );
    assert_ne!(new_semantic.artifact_digest, old_semantic.artifact_digest);
    assert_ne!(
        new_semantic.training_projection_digest,
        old_semantic.training_projection_digest
    );
    assert!(
        MemoryServingPlanV11::restore(
            &checkpoint,
            &corrected,
            vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)]
        )
        .is_err(),
        "old checkpoint cannot silently mix new weights"
    );
    assert!(
        plan.read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
            .await
            .is_err(),
        "old object cannot follow a mutable CURRENT pointer"
    );
}

#[tokio::test]
async fn memory_v11_query_fences_reject_source_and_selected_version_races() {
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let mut cell = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    let plan = MemoryServingPlanV11::prepare(&owner, generation(1), vec![Arc::clone(&cell.host)])
        .expect("plan");
    let query = request(&owner);
    let scope = CognitiveScope::AgentPrivate;
    // A deterministic interleaving after inference and before the final fence.
    let prepared = plan
        .prepare_read(
            &store,
            &access,
            &scope,
            &query,
            MemoryOperationV1::Semantic,
            now(),
        )
        .await
        .expect("prepared value");
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
    assert!(
        plan.finish_read(&store, &access, &scope, &query, prepared, now())
            .await
            .is_err(),
        "full query cut is still enforced"
    );
    plan.read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
        .await
        .expect("next query keeps weights");
    let prepared = plan
        .prepare_read(
            &store,
            &access,
            &scope,
            &query,
            MemoryOperationV1::Semantic,
            now(),
        )
        .await
        .expect("second prepared value");
    cell.replace(&snapshot(&store, &access).await);
    assert!(
        plan.finish_read(&store, &access, &scope, &query, prepared, now())
            .await
            .is_err(),
        "publication changed during inference"
    );
    assert!(
        plan.read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
            .await
            .is_err(),
        "start fence also rejects superseded tuple"
    );
    let current = snapshot(&store, &access).await;
    let next = MemoryServingPlanV11::prepare(&current, generation(2), vec![Arc::clone(&cell.host)])
        .expect("current plan");
    next.read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
        .await
        .expect("new plan executes");
    let prepared = next
        .prepare_read(
            &store,
            &access,
            &scope,
            &query,
            MemoryOperationV1::Semantic,
            now(),
        )
        .await
        .expect("before source withdrawal");
    store
        .forget_memory_inventory(
            &access,
            &scope,
            &record("item:a", MemoryInventoryKindV1::Semantic, json!(null)).address(),
            /*expected_revision*/ 1,
            "revoke training source",
            now(),
        )
        .await
        .expect("owner tombstone");
    assert!(
        next.finish_read(&store, &access, &scope, &query, prepared, now())
            .await
            .is_err()
    );
    assert!(
        next.read(&store, &access, &scope, &query, MemoryOperationV1::Semantic)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn memory_v11_return_fence_rechecks_timed_dependencies_outside_query_support() {
    let (root, store, access) = owner_fixture().await;
    let before_time = now();
    let transition = before_time + 100;
    let mut future = record(
        "flow:a",
        MemoryInventoryKindV1::Procedure,
        json!({"opcodes":[0,0,0,6]}),
    );
    future.effective_at = transition as u64;
    let scope = CognitiveScope::AgentPrivate;
    store
        .write_memory_inventory(&access, &scope, &future, MemoryCellWriteModeV1::Create)
        .await
        .expect("already stored future version");
    let owner = store
        .memory_inventory_snapshot(&access, &scope, before_time)
        .await
        .expect("before transition");
    let semantic = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    let procedure = CellFixture::new(
        root.path().join("procedure"),
        &owner,
        "cell:procedure",
        MemoryInventoryKindV1::Procedure,
        "flow:a",
    );
    let plan = MemoryServingPlanV11::prepare(
        &owner,
        generation(1),
        vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)],
    )
    .expect("before-transition plan");
    let query = request(&owner);
    let prepared = plan
        .prepare_read(
            &store,
            &access,
            &scope,
            &query,
            MemoryOperationV1::Semantic,
            before_time,
        )
        .await
        .expect("semantic-only inference");
    let after = store
        .memory_inventory_snapshot(&access, &scope, transition)
        .await
        .expect("after transition");
    assert_eq!(
        owner.owner_cut_digest(),
        after.owner_cut_digest(),
        "no source write occurred between the two fences"
    );
    assert!(
        plan.finish_read(&store, &access, &scope, &query, prepared, transition)
            .await
            .is_err(),
        "an unqueried selected cell became stale even though the complete stored cut did not change"
    );
}

#[tokio::test]
async fn memory_v11_recovery_requires_live_signed_selection_and_withdrawal_frontier() {
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let semantic = CellFixture::new(
        root.path().join("semantic"),
        &owner,
        "cell:semantic",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    let procedure = CellFixture::new(
        root.path().join("procedure"),
        &owner,
        "cell:procedure",
        MemoryInventoryKindV1::Procedure,
        "flow:a",
    );
    let plan = MemoryServingPlanV11::prepare(
        &owner,
        generation(1),
        vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)],
    )
    .expect("plan");
    let saved = plan.checkpoint().expect("checkpoint");
    let digest = plan.digest();
    drop(plan);
    let mut semantic = semantic.reopen();
    let procedure = procedure.reopen();
    let current = snapshot(&store, &access).await;
    let restored = MemoryServingPlanV11::restore(
        &saved,
        &current,
        vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)],
    )
    .expect("pins plus authenticated restored owners");
    assert_eq!(restored.digest(), digest);
    let scope = CognitiveScope::AgentPrivate;
    let query = request(&current);
    restored
        .read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
        .await
        .expect("restored real inference");
    let mut forged: serde_json::Value = serde_json::from_slice(&saved).expect("checkpoint DTO");
    forged["cells"][0]["artifact_digest"] =
        json!(Digest32::of_bytes(b"substituted-artifact").to_string());
    assert!(
        MemoryServingPlanV11::restore(
            &serde_json::to_vec(&forged).expect("tampered pins"),
            &current,
            vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)]
        )
        .is_err()
    );
    let mut withdrawals = semantic
        .service
        .lock()
        .expect("owner")
        .withdrawal_registry()
        .clone();
    let removed = semantic
        .publication
        .admission
        .validated_manifest
        .manifest
        .lineage_digests[0];
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdraw-v11-semantic"),
            dataset_digest: removed,
            source_tombstone_digest: Digest32::of_bytes(b"owner-tombstone"),
            authority_id: id("memory-dataset-owner"),
            credential_chain_digest: Digest32::of_bytes(b"dataset-credential"),
            signing_key_digest: Digest32::of_bytes(b"dataset-signer"),
            authority_epoch: 1,
            issued_at: now() as u64,
        })
        .expect("withdrawal frontier");
    semantic
        .service
        .lock()
        .expect("owner")
        .install_withdrawal_frontier(withdrawals.clone())
        .expect("live owner frontier");
    assert!(
        restored
            .read(&store, &access, &scope, &query, MemoryOperationV1::Apply)
            .await
            .is_err()
    );
    let sibling =
        MemoryServingPlanV11::prepare(&current, generation(2), vec![Arc::clone(&procedure.host)])
            .expect("unaffected independent registry");
    sibling
        .read(
            &store,
            &access,
            &scope,
            &query,
            MemoryOperationV1::Procedure,
        )
        .await
        .expect("sibling survives artifact withdrawal");
    // Crash recovery carries the authenticated external frontier, not the old
    // admission's frontier. An old checkpoint cannot reconstruct selection.
    drop(restored);
    semantic.config.withdrawal_registry = withdrawals;
    let recovered = semantic.reopen_unselected();
    assert!(
        recovered.try_install().is_err(),
        "latest withdrawal frontier rejects old admission after restart"
    );
    assert!(recovered.host.load_current().is_err());
}

#[tokio::test]
async fn memory_v11_plan_rejects_duplicate_and_ambiguous_ownership() {
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let first = CellFixture::new(
        root.path().join("first"),
        &owner,
        "cell:first",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    let overlapping = CellFixture::new(
        root.path().join("overlap"),
        &owner,
        "cell:overlap",
        MemoryInventoryKindV1::Semantic,
        "item:a",
    );
    assert!(
        MemoryServingPlanV11::prepare(
            &owner,
            generation(1),
            vec![Arc::clone(&first.host), Arc::clone(&first.host)]
        )
        .is_err()
    );
    assert!(
        MemoryServingPlanV11::prepare(
            &owner,
            generation(1),
            vec![Arc::clone(&first.host), Arc::clone(&overlapping.host)]
        )
        .is_err()
    );
}
