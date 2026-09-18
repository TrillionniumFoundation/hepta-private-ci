use super::*;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Revision;
use tempfile::TempDir;

use crate::LocalLeaseAcquire;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("revision")
}

fn snapshot_key(compact_generation: u64) -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:qualified-compact"),
        purpose_id: id("purpose:consolidation"),
        memory_ledger_frontier: 20,
        knowledge_fact_frontier: 14,
        tombstone_frontier: 6,
        source_ledger_frontier: 21,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(compact_generation),
        prompt_registry_revision: revision(4),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 8,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .expect("snapshot key")
}

fn checkpoint(
    compact_generation: u64,
    predecessor_digest: Digest32,
    payload_seed: &str,
) -> CompactCheckpointV1 {
    let mut checkpoint = CompactCheckpointV1 {
        checkpoint_id: id(&format!("checkpoint:{compact_generation}:{payload_seed}")),
        generation: generation(compact_generation),
        source_snapshot: snapshot_key(compact_generation - 1),
        support_manifest_digest: digest(&format!("support:{payload_seed}")),
        algorithm_digest: digest("algorithm"),
        payload_digest: digest(&format!("payload:{payload_seed}")),
        omitted_information_digest: digest(&format!("omitted:{payload_seed}")),
        tombstone_cutoff: 6,
        predecessor_digest: Some(predecessor_digest),
        compatibility_digest: digest("compatibility"),
        checkpoint_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    checkpoint.checkpoint_digest = checkpoint.compute_checkpoint_digest();
    checkpoint.validate().expect("checkpoint");
    checkpoint
}

fn proof(checkpoint: &CompactCheckpointV1, candidate_seed: &str) -> CompactionProofV2 {
    let mut proof = CompactionProofV2 {
        checkpoint_digest: checkpoint.checkpoint_digest,
        candidate_digest: digest(&format!("candidate:{candidate_seed}")),
        evaluator_id: id("evaluator:independent"),
        evaluator_implementation_digest: digest("evaluator-implementation"),
        evaluation_artifact_digest: digest(&format!("evaluation:{candidate_seed}")),
        attestation_digest: digest(&format!("attestation:{candidate_seed}")),
        attestation_signature_digest: digest(&format!("signature:{candidate_seed}")),
        signature_verification_receipt_digest: digest(&format!(
            "signature-verification:{candidate_seed}"
        )),
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        deletion_cutoff: checkpoint.tombstone_cutoff,
        source_count: 10,
        retained_count: 4,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_proof_digest();
    proof.validate().expect("proof");
    proof
}

fn unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
}

async fn prepared() -> (TempDir, CognitiveStore, LocalLeaseOutbox, CompactFence) {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(84);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let fence = CompactFence::new(8, 11, 1, "qualified-compact-fence").expect("fence");
    let lease = match store
        .acquire_local_lease_bound(
            "lease:qualified-compact",
            fence.authority_epoch,
            fence.owner_epoch,
            fence.generation,
            fence.fencing_token.clone(),
            unix_seconds() + 3600,
        )
        .await
        .expect("lease")
    {
        LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
    };
    (temp, store, lease, fence)
}

#[tokio::test]
async fn canonical_checkpoint_publication_is_idempotent_and_survives_reopen() {
    let (temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "one");
    let first_proof = proof(&first, "one");

    let inserted = store
        .publish_qualified_compact_checkpoint(&lease, &fence, &first, &first_proof)
        .await
        .expect("publish");
    assert_eq!(
        inserted.disposition,
        QualifiedCompactPublicationDisposition::Inserted
    );
    let replay = store
        .publish_qualified_compact_checkpoint(&lease, &fence, &first, &first_proof)
        .await
        .expect("idempotent replay");
    assert_eq!(
        replay.disposition,
        QualifiedCompactPublicationDisposition::Unchanged
    );
    assert_eq!(replay.publication_digest, inserted.publication_digest);

    let second = checkpoint(3, first.checkpoint_digest, "two");
    let second_proof = proof(&second, "two");
    store
        .publish_qualified_compact_checkpoint(&lease, &fence, &second, &second_proof)
        .await
        .expect("publish successor");

    let owner = agent_id(84);
    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen store");
    let latest = reopened
        .latest_qualified_compact_checkpoint(
            &id("scope:qualified-compact"),
            &id("purpose:consolidation"),
        )
        .await
        .expect("reload")
        .expect("published head");
    assert_eq!(latest.checkpoint, second);
    assert_eq!(latest.proof, second_proof);
    assert!(!latest.authority.grants_any());
}

#[tokio::test]
async fn predecessor_cas_rejects_divergent_successor() {
    let (_temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "one");
    let first_proof = proof(&first, "one");
    store
        .publish_qualified_compact_checkpoint(&lease, &fence, &first, &first_proof)
        .await
        .expect("publish first");

    let wrong = checkpoint(3, digest("wrong-predecessor"), "wrong");
    let wrong_proof = proof(&wrong, "wrong");
    assert!(matches!(
        store
            .publish_qualified_compact_checkpoint(&lease, &fence, &wrong, &wrong_proof)
            .await,
        Err(QualifiedCompactStoreError::Conflict(message))
            if message.contains("predecessor")
    ));
}

#[tokio::test]
async fn concurrent_same_generation_publish_has_one_winner() {
    let (_temp, store, lease, fence) = prepared().await;
    let left = checkpoint(2, digest("bootstrap-predecessor"), "left");
    let left_proof = proof(&left, "left");
    let right = checkpoint(2, digest("bootstrap-predecessor"), "right");
    let right_proof = proof(&right, "right");

    let left_call = store.publish_qualified_compact_checkpoint(&lease, &fence, &left, &left_proof);
    let right_call =
        store.publish_qualified_compact_checkpoint(&lease, &fence, &right, &right_proof);
    let (left_result, right_result) = tokio::join!(left_call, right_call);

    let inserted = [&left_result, &right_result]
        .into_iter()
        .filter(|result| {
            matches!(
                result,
                Ok(publication)
                    if publication.disposition
                        == QualifiedCompactPublicationDisposition::Inserted
            )
        })
        .count();
    let conflicted = [&left_result, &right_result]
        .into_iter()
        .filter(|result| matches!(result, Err(QualifiedCompactStoreError::Conflict(_))))
        .count();
    assert_eq!(inserted, 1);
    assert_eq!(conflicted, 1);
}

#[tokio::test]
async fn uncommitted_publication_transaction_disappears_after_restart() {
    let (temp, store, _lease, _fence) = prepared().await;
    let checkpoint = checkpoint(2, digest("bootstrap-predecessor"), "crash");
    let proof = proof(&checkpoint, "crash");
    let checkpoint_json =
        serde_json::to_string(&CheckpointImageV1::from_contract(&checkpoint)).expect("json");
    let proof_json = serde_json::to_string(&ProofImageV2::from_contract(&proof)).expect("json");
    let publication = publication_digest(&checkpoint, &proof);

    let mut transaction = store.pool.begin_with("BEGIN IMMEDIATE").await.expect("tx");
    sqlx::query(
        "INSERT INTO cognitive_qualified_compact_checkpoints (
            owner_agent_id, scope_id, purpose_id, generation,
            checkpoint_digest, predecessor_digest, candidate_digest, proof_digest,
            source_snapshot_digest, tokenizer_digest, publication_digest,
            checkpoint_json, proof_json, published_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(checkpoint.source_snapshot.vector.scope_id.as_str())
    .bind(checkpoint.source_snapshot.vector.purpose_id.as_str())
    .bind(2_i64)
    .bind(checkpoint.checkpoint_digest.to_string())
    .bind(checkpoint.predecessor_digest.map(|value| value.to_string()))
    .bind(proof.candidate_digest.to_string())
    .bind(proof.proof_digest.to_string())
    .bind(checkpoint.source_snapshot.vector_digest.to_string())
    .bind(
        checkpoint
            .source_snapshot
            .vector
            .tokenizer_digest
            .to_string(),
    )
    .bind(publication.to_string())
    .bind(checkpoint_json)
    .bind(proof_json)
    .bind(i64::try_from(unix_seconds()).expect("time"))
    .execute(&mut *transaction)
    .await
    .expect("uncommitted insert");
    drop(transaction);
    drop(store);

    let owner = agent_id(84);
    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen after rollback");
    assert!(
        reopened
            .latest_qualified_compact_checkpoint(
                &id("scope:qualified-compact"),
                &id("purpose:consolidation"),
            )
            .await
            .expect("read")
            .is_none()
    );
}

#[tokio::test]
async fn corrupt_persisted_checkpoint_fails_store_reopen() {
    let (temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "one");
    let first_proof = proof(&first, "one");
    store
        .publish_qualified_compact_checkpoint(&lease, &fence, &first, &first_proof)
        .await
        .expect("publish");

    sqlx::query(
        "INSERT INTO cognitive_qualified_compact_checkpoints (
            owner_agent_id, scope_id, purpose_id, generation,
            checkpoint_digest, predecessor_digest, candidate_digest, proof_digest,
            source_snapshot_digest, tokenizer_digest, publication_digest,
            checkpoint_json, proof_json, published_at_unix_seconds
         ) VALUES (?, ?, ?, 3, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?)",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(first.source_snapshot.vector.scope_id.as_str())
    .bind(first.source_snapshot.vector.purpose_id.as_str())
    .bind(digest("corrupt-checkpoint").to_string())
    .bind(first.checkpoint_digest.to_string())
    .bind(digest("corrupt-candidate").to_string())
    .bind(digest("corrupt-proof").to_string())
    .bind(digest("corrupt-snapshot").to_string())
    .bind(first.source_snapshot.vector.tokenizer_digest.to_string())
    .bind(digest("corrupt-publication").to_string())
    .bind(i64::try_from(unix_seconds()).expect("time"))
    .execute(&store.pool)
    .await
    .expect("inject corrupt row");
    drop(store);

    let owner = agent_id(84);
    assert!(matches!(
        CognitiveStore::open(&layout(&temp, &owner)).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[tokio::test]
async fn unknown_checkpoint_image_field_fails_store_reopen() {
    let (temp, store, _lease, _fence) = prepared().await;
    let checkpoint = checkpoint(2, digest("bootstrap-predecessor"), "unknown-field");
    let proof = proof(&checkpoint, "unknown-field");
    let mut checkpoint_value = serde_json::to_value(CheckpointImageV1::from_contract(&checkpoint))
        .expect("serialize checkpoint image");
    checkpoint_value
        .as_object_mut()
        .expect("checkpoint image object")
        .insert(
            "unexpected_critical_field".to_string(),
            serde_json::Value::String("must-not-be-ignored".to_string()),
        );
    let checkpoint_json =
        serde_json::to_string(&checkpoint_value).expect("encode checkpoint with unknown field");
    let proof_json = serde_json::to_string(&ProofImageV2::from_contract(&proof))
        .expect("serialize proof image");
    let publication = publication_digest(&checkpoint, &proof);

    sqlx::query(
        "INSERT INTO cognitive_qualified_compact_checkpoints (
            owner_agent_id, scope_id, purpose_id, generation,
            checkpoint_digest, predecessor_digest, candidate_digest, proof_digest,
            source_snapshot_digest, tokenizer_digest, publication_digest,
            checkpoint_json, proof_json, published_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(checkpoint.source_snapshot.vector.scope_id.as_str())
    .bind(checkpoint.source_snapshot.vector.purpose_id.as_str())
    .bind(i64::try_from(checkpoint.generation.get()).expect("generation"))
    .bind(checkpoint.checkpoint_digest.to_string())
    .bind(checkpoint.predecessor_digest.map(|value| value.to_string()))
    .bind(proof.candidate_digest.to_string())
    .bind(proof.proof_digest.to_string())
    .bind(checkpoint.source_snapshot.vector_digest.to_string())
    .bind(
        checkpoint
            .source_snapshot
            .vector
            .tokenizer_digest
            .to_string(),
    )
    .bind(publication.to_string())
    .bind(checkpoint_json)
    .bind(proof_json)
    .bind(i64::try_from(unix_seconds()).expect("time"))
    .execute(&store.pool)
    .await
    .expect("inject otherwise-valid row with unknown field");
    drop(store);

    let owner = agent_id(84);
    assert!(matches!(
        CognitiveStore::open(&layout(&temp, &owner)).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[test]
fn publication_contract_is_authority_free() {
    let checkpoint = checkpoint(2, digest("bootstrap-predecessor"), "one");
    let proof = proof(&checkpoint, "one");
    let publication = QualifiedCompactCheckpointPublication {
        publication_digest: publication_digest(&checkpoint, &proof),
        checkpoint,
        proof,
        disposition: QualifiedCompactPublicationDisposition::Inserted,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert!(!publication.authority.grants_any());
}

#[test]
fn test_fixture_layout_uses_one_owner_database() {
    let temp = TempDir::new().expect("temp");
    let fleet = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet");
    let owner = agent_id(84);
    let agent_layout = fleet.layout().agent(&owner);
    assert_eq!(agent_layout.agent_id(), &owner);
}
