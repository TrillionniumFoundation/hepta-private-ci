use super::*;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::CompactionProofWitnessV1;
use codex_hepta_compact_engine::CompactionQualificationV2;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
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

fn payload(seed: &str) -> Vec<u8> {
    format!("durable-compact-payload:{seed}").into_bytes()
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
    let payload = payload(payload_seed);
    let mut checkpoint = CompactCheckpointV1 {
        checkpoint_id: id(&format!("checkpoint:{compact_generation}:{payload_seed}")),
        generation: generation(compact_generation),
        source_snapshot: snapshot_key(compact_generation - 1),
        source_memory_snapshot_digest: digest(&format!("source-memory:{payload_seed}")),
        support_manifest_digest: digest(&format!("support:{payload_seed}")),
        algorithm_digest: digest("algorithm"),
        payload_digest: Digest32::of_bytes(&payload),
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

fn proof_signing_key() -> SigningKey {
    SigningKey::from_bytes(&[37_u8; 32])
}

fn proof_witness(proof: &CompactionProofV2) -> CompactionProofWitnessV1 {
    let signing_key = proof_signing_key();
    let mut qualification = CompactionQualificationV2 {
        tokenizer_implementation_digest: proof.tokenizer_implementation_digest,
        tokenizer_attestation_digest: proof.tokenizer_attestation_digest,
        tokenizer_key_digest: proof.tokenizer_key_digest,
        evaluator_id: proof.evaluator_id.clone(),
        evaluator_implementation_digest: proof.evaluator_implementation_digest,
        evaluation_artifact_digest: proof.evaluation_artifact_digest,
        attestation_digest: proof.attestation_digest,
        retained_query_suite_digest: proof.retained_query_suite_digest,
        reconstruction_obligation_digest: proof.reconstruction_obligation_digest,
        contradiction_holdout_digest: proof.contradiction_holdout_digest,
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    qualification.signature = signing_key
        .sign(&qualification.signing_bytes(proof.candidate_digest))
        .to_bytes();
    let witness = CompactionProofWitnessV1 {
        evaluator_verifying_key: signing_key.verifying_key().to_bytes(),
        qualification_signature: qualification.signature,
    };
    witness.verify_proof(proof).expect("proof witness");
    witness
}

fn proof(checkpoint: &CompactCheckpointV1, candidate_seed: &str) -> CompactionProofV2 {
    let signing_key = proof_signing_key();
    let candidate_digest = digest(&format!("candidate:{candidate_seed}"));
    let evaluator_implementation_digest = digest("evaluator-implementation");
    let attestation_digest = digest(&format!("attestation:{candidate_seed}"));
    let mut qualification = CompactionQualificationV2 {
        tokenizer_implementation_digest: digest("tokenizer-implementation"),
        tokenizer_attestation_digest: digest("tokenizer-attestation"),
        tokenizer_key_digest: digest("tokenizer-key"),
        evaluator_id: id("evaluator:independent"),
        evaluator_implementation_digest,
        evaluation_artifact_digest: digest(&format!("evaluation:{candidate_seed}")),
        attestation_digest,
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    qualification.signature = signing_key
        .sign(&qualification.signing_bytes(candidate_digest))
        .to_bytes();
    let witness = CompactionProofWitnessV1 {
        evaluator_verifying_key: signing_key.verifying_key().to_bytes(),
        qualification_signature: qualification.signature,
    };
    let mut proof = CompactionProofV2 {
        checkpoint_digest: checkpoint.checkpoint_digest,
        candidate_digest,
        tokenizer_implementation_digest: digest("tokenizer-implementation"),
        tokenizer_attestation_digest: digest("tokenizer-attestation"),
        tokenizer_key_digest: digest("tokenizer-key"),
        evaluator_id: qualification.evaluator_id,
        evaluator_implementation_digest,
        evaluation_artifact_digest: qualification.evaluation_artifact_digest,
        attestation_digest,
        attestation_signature_digest: Digest32::of_bytes(&qualification.signature),
        signature_verification_receipt_digest: witness.verification_receipt_digest(
            candidate_digest,
            evaluator_implementation_digest,
            attestation_digest,
        ),
        retained_query_suite_digest: qualification.retained_query_suite_digest,
        reconstruction_obligation_digest: qualification.reconstruction_obligation_digest,
        contradiction_holdout_digest: qualification.contradiction_holdout_digest,
        deletion_cutoff: checkpoint.tombstone_cutoff,
        source_count: 10,
        retained_count: 4,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_proof_digest();
    proof.validate().expect("proof");
    witness.verify_proof(&proof).expect("proof witness");
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
async fn canonical_checkpoint_payload_and_proof_survive_reopen() {
    let (temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "one");
    let first_proof = proof(&first, "one");
    let first_payload = payload("one");

    let inserted = store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &first,
            &first_proof,
            &proof_witness(&first_proof),
            &first_payload,
        )
        .await
        .expect("publish");
    assert_eq!(
        inserted.disposition,
        QualifiedCompactPublicationDisposition::Inserted
    );
    let replay = store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &first,
            &first_proof,
            &proof_witness(&first_proof),
            &first_payload,
        )
        .await
        .expect("idempotent replay");
    assert_eq!(
        replay.disposition,
        QualifiedCompactPublicationDisposition::Unchanged
    );

    let second = checkpoint(3, first.checkpoint_digest, "two");
    let second_proof = proof(&second, "two");
    let second_payload = payload("two");
    store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &second,
            &second_proof,
            &proof_witness(&second_proof),
            &second_payload,
        )
        .await
        .expect("publish successor");

    let owner = agent_id(84);
    drop(store);
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
    let resolved = reopened
        .resolve_qualified_compact_payload(
            &id("scope:qualified-compact"),
            &id("purpose:consolidation"),
            second.payload_digest,
        )
        .await
        .expect("resolve")
        .expect("payload");
    assert_eq!(resolved, second_payload);
}

#[tokio::test]
async fn store_rejects_checkpoint_generation_that_skips_source_snapshot() {
    let (_temp, store, lease, fence) = prepared().await;
    let skipped = checkpoint(3, digest("skipped-predecessor"), "skipped");
    let skipped_proof = proof(&skipped, "skipped");
    assert!(matches!(
        store
            .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &skipped,
            &skipped_proof,
            &proof_witness(&skipped_proof),
            &payload("skipped"),
        )
            .await,
        Err(QualifiedCompactStoreError::Invalid(ref message))
            if message.contains("successor of the source snapshot")
    ));
}

#[tokio::test]
async fn predecessor_cas_rejects_divergent_successor() {
    let (_temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "one");
    let first_proof = proof(&first, "one");
    store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &first,
            &first_proof,
            &proof_witness(&first_proof),
            &payload("one"),
        )
        .await
        .expect("publish first");

    let wrong = checkpoint(3, digest("wrong-predecessor"), "wrong");
    let wrong_proof = proof(&wrong, "wrong");
    assert!(matches!(
        store
            .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &wrong,
            &wrong_proof,
            &proof_witness(&wrong_proof),
            &payload("wrong"),
        )
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
    let left_payload = payload("left");
    let right_payload = payload("right");

    let left_witness = proof_witness(&left_proof);
    let right_witness = proof_witness(&right_proof);
    let left_call = store.publish_qualified_compact_checkpoint(
        &lease,
        &fence,
        &left,
        &left_proof,
        &left_witness,
        &left_payload,
    );
    let right_call = store.publish_qualified_compact_checkpoint(
        &lease,
        &fence,
        &right,
        &right_proof,
        &right_witness,
        &right_payload,
    );
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
async fn current_selection_requires_exact_current_cut_and_live_payload() {
    let (_temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "current");
    let first_proof = proof(&first, "current");
    store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &first,
            &first_proof,
            &proof_witness(&first_proof),
            &payload("current"),
        )
        .await
        .expect("publish");

    let current = snapshot_key(2);
    let selected = store
        .select_current_qualified_compact_checkpoint(
            &current,
            first.source_memory_snapshot_digest,
            first.compatibility_digest,
        )
        .await
        .expect("select")
        .expect("current checkpoint");
    assert_eq!(selected.payload, payload("current"));

    let mut stale_vector = current.vector.clone();
    stale_vector.tombstone_frontier += 1;
    let stale = CognitiveSnapshotKeyV1::new(stale_vector).expect("stale snapshot shape");
    assert!(matches!(
        store
            .select_current_qualified_compact_checkpoint(
                &stale,
                first.source_memory_snapshot_digest,
                first.compatibility_digest,
            )
            .await,
        Err(QualifiedCompactStoreError::Conflict(message))
            if message.contains("stale")
    ));
}

#[tokio::test]
async fn payload_revocation_blocks_resolution_then_allows_gc() {
    let (_temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "revoked");
    let first_proof = proof(&first, "revoked");
    store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &first,
            &first_proof,
            &proof_witness(&first_proof),
            &payload("revoked"),
        )
        .await
        .expect("publish");

    let direct_delete = sqlx::query(
        "DELETE FROM cognitive_qualified_compact_payloads
         WHERE owner_agent_id = ? AND scope_id = ? AND purpose_id = ? AND payload_digest = ?",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(first.source_snapshot.vector.scope_id.as_str())
    .bind(first.source_snapshot.vector.purpose_id.as_str())
    .bind(first.payload_digest.to_string())
    .execute(&store.pool)
    .await;
    assert!(
        direct_delete.is_err(),
        "direct payload delete must fail before revocation"
    );

    assert!(matches!(
        store
            .gc_revoked_qualified_compact_payload(
                &lease,
                &fence,
                &first.source_snapshot.vector.scope_id,
                &first.source_snapshot.vector.purpose_id,
                first.payload_digest,
            )
            .await,
        Err(QualifiedCompactStoreError::Conflict(_))
    ));

    store
        .revoke_qualified_compact_payload(
            &lease,
            &fence,
            &first.source_snapshot.vector.scope_id,
            &first.source_snapshot.vector.purpose_id,
            first.payload_digest,
            7,
            digest("payload-revocation"),
        )
        .await
        .expect("revoke");
    assert!(
        store
            .resolve_qualified_compact_payload(
                &first.source_snapshot.vector.scope_id,
                &first.source_snapshot.vector.purpose_id,
                first.payload_digest,
            )
            .await
            .expect("resolve after revoke")
            .is_none()
    );
    assert!(
        store
            .gc_revoked_qualified_compact_payload(
                &lease,
                &fence,
                &first.source_snapshot.vector.scope_id,
                &first.source_snapshot.vector.purpose_id,
                first.payload_digest,
            )
            .await
            .expect("gc")
    );
}

#[tokio::test]
async fn rollback_returns_candidate_only_after_current_cut_re_admission() {
    let (_temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "rollback");
    let first_proof = proof(&first, "rollback");
    store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &first,
            &first_proof,
            &proof_witness(&first_proof),
            &payload("rollback"),
        )
        .await
        .expect("publish");

    let candidate = store
        .rollback_qualified_compact_payload_candidate(
            generation(2),
            &snapshot_key(3),
            first.source_memory_snapshot_digest,
            first.compatibility_digest,
        )
        .await
        .expect("rollback re-admission")
        .expect("candidate");
    assert_eq!(candidate.source_generation, generation(2));
    assert_eq!(candidate.payload, payload("rollback"));
    assert!(!candidate.authority.grants_any());
}

#[tokio::test]
async fn fault_after_payload_write_rolls_back_owner_publication_on_reopen() {
    let (temp, store, lease, fence) = prepared().await;
    let checkpoint = checkpoint(2, digest("bootstrap-predecessor"), "fault-payload");
    let proof = proof(&checkpoint, "fault-payload");
    let witness = proof_witness(&proof);
    let payload = payload("fault-payload");

    assert!(matches!(
        store
            .publish_qualified_compact_checkpoint_with_fault(
                &lease,
                &fence,
                &checkpoint,
                &proof,
                &witness,
                &payload,
                QualifiedCompactFaultPoint::AfterPayloadWrite,
            )
            .await,
        Err(QualifiedCompactStoreError::FaultInjected("after_payload_write"))
    ));
    drop(store);

    let owner = agent_id(84);
    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen after payload-write fault");
    assert!(
        reopened
            .latest_qualified_compact_checkpoint(
                &checkpoint.source_snapshot.vector.scope_id,
                &checkpoint.source_snapshot.vector.purpose_id,
            )
            .await
            .expect("read checkpoint after fault")
            .is_none()
    );
    assert!(
        reopened
            .resolve_qualified_compact_payload(
                &checkpoint.source_snapshot.vector.scope_id,
                &checkpoint.source_snapshot.vector.purpose_id,
                checkpoint.payload_digest,
            )
            .await
            .expect("resolve payload after fault")
            .is_none()
    );
}

#[tokio::test]
async fn fault_after_checkpoint_write_rolls_back_owner_publication_on_reopen() {
    let (temp, store, lease, fence) = prepared().await;
    let checkpoint = checkpoint(2, digest("bootstrap-predecessor"), "fault-checkpoint");
    let proof = proof(&checkpoint, "fault-checkpoint");
    let witness = proof_witness(&proof);
    let payload = payload("fault-checkpoint");

    assert!(matches!(
        store
            .publish_qualified_compact_checkpoint_with_fault(
                &lease,
                &fence,
                &checkpoint,
                &proof,
                &witness,
                &payload,
                QualifiedCompactFaultPoint::AfterCheckpointWrite,
            )
            .await,
        Err(QualifiedCompactStoreError::FaultInjected("after_checkpoint_write"))
    ));
    drop(store);

    let owner = agent_id(84);
    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen after checkpoint-write fault");
    assert!(
        reopened
            .latest_qualified_compact_checkpoint(
                &checkpoint.source_snapshot.vector.scope_id,
                &checkpoint.source_snapshot.vector.purpose_id,
            )
            .await
            .expect("read checkpoint after fault")
            .is_none()
    );
    assert!(
        reopened
            .resolve_qualified_compact_payload(
                &checkpoint.source_snapshot.vector.scope_id,
                &checkpoint.source_snapshot.vector.purpose_id,
                checkpoint.payload_digest,
            )
            .await
            .expect("resolve payload after fault")
            .is_none()
    );
}

#[tokio::test]
async fn fault_after_revocation_write_leaves_payload_live_on_reopen() {
    let (temp, store, lease, fence) = prepared().await;
    let checkpoint = checkpoint(2, digest("bootstrap-predecessor"), "fault-revoke");
    let proof = proof(&checkpoint, "fault-revoke");
    let witness = proof_witness(&proof);
    let payload = payload("fault-revoke");
    store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &checkpoint,
            &proof,
            &witness,
            &payload,
        )
        .await
        .expect("publish before revocation fault");

    assert!(matches!(
        store
            .revoke_qualified_compact_payload_with_fault(
                &lease,
                &fence,
                &checkpoint.source_snapshot.vector.scope_id,
                &checkpoint.source_snapshot.vector.purpose_id,
                checkpoint.payload_digest,
                7,
                digest("fault-revocation"),
                QualifiedCompactFaultPoint::AfterRevocationWrite,
            )
            .await,
        Err(QualifiedCompactStoreError::FaultInjected("after_revocation_write"))
    ));
    drop(store);

    let owner = agent_id(84);
    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen after revocation-write fault");
    assert_eq!(
        reopened
            .resolve_qualified_compact_payload(
                &checkpoint.source_snapshot.vector.scope_id,
                &checkpoint.source_snapshot.vector.purpose_id,
                checkpoint.payload_digest,
            )
            .await
            .expect("resolve payload after revocation fault"),
        Some(payload)
    );
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
    let crash_payload = payload("crash");

    let mut transaction = store.pool.begin_with("BEGIN IMMEDIATE").await.expect("tx");
    sqlx::query(
        "INSERT INTO cognitive_qualified_compact_payloads (
            owner_agent_id, scope_id, purpose_id, payload_digest,
            source_snapshot_digest, tokenizer_digest, payload_bytes, created_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(checkpoint.source_snapshot.vector.scope_id.as_str())
    .bind(checkpoint.source_snapshot.vector.purpose_id.as_str())
    .bind(checkpoint.payload_digest.to_string())
    .bind(checkpoint.source_snapshot.vector_digest.to_string())
    .bind(
        checkpoint
            .source_snapshot
            .vector
            .tokenizer_digest
            .to_string(),
    )
    .bind(&crash_payload)
    .bind(i64::try_from(unix_seconds()).expect("time"))
    .execute(&mut *transaction)
    .await
    .expect("uncommitted payload insert");
    sqlx::query(
        "INSERT INTO cognitive_qualified_compact_checkpoints (
            owner_agent_id, scope_id, purpose_id, generation,
            checkpoint_digest, predecessor_digest, candidate_digest, proof_digest,
            source_snapshot_digest, source_memory_snapshot_digest, tokenizer_digest,
            publication_digest, checkpoint_json, proof_json, published_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    .bind(checkpoint.source_memory_snapshot_digest.to_string())
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
    assert!(
        reopened
            .resolve_qualified_compact_payload(
                &id("scope:qualified-compact"),
                &id("purpose:consolidation"),
                checkpoint.payload_digest,
            )
            .await
            .expect("resolve after rollback")
            .is_none()
    );
}

#[tokio::test]
async fn corrupt_persisted_checkpoint_fails_store_reopen() {
    let (temp, store, lease, fence) = prepared().await;
    let first = checkpoint(2, digest("bootstrap-predecessor"), "one");
    let first_proof = proof(&first, "one");
    store
        .publish_qualified_compact_checkpoint(
            &lease,
            &fence,
            &first,
            &first_proof,
            &proof_witness(&first_proof),
            &payload("one"),
        )
        .await
        .expect("publish");

    sqlx::query(
        "INSERT INTO cognitive_qualified_compact_checkpoints (
            owner_agent_id, scope_id, purpose_id, generation,
            checkpoint_digest, predecessor_digest, candidate_digest, proof_digest,
            source_snapshot_digest, source_memory_snapshot_digest, tokenizer_digest,
            publication_digest, checkpoint_json, proof_json, published_at_unix_seconds
         ) VALUES (?, ?, ?, 3, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?)",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(first.source_snapshot.vector.scope_id.as_str())
    .bind(first.source_snapshot.vector.purpose_id.as_str())
    .bind(digest("corrupt-checkpoint").to_string())
    .bind(first.checkpoint_digest.to_string())
    .bind(digest("corrupt-candidate").to_string())
    .bind(digest("corrupt-proof").to_string())
    .bind(digest("corrupt-snapshot").to_string())
    .bind(digest("corrupt-source-memory-snapshot").to_string())
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
    let proof_json =
        serde_json::to_string(&ProofImageV2::from_contract(&proof)).expect("serialize proof image");
    let publication = publication_digest(&checkpoint, &proof);

    sqlx::query(
        "INSERT INTO cognitive_qualified_compact_checkpoints (
            owner_agent_id, scope_id, purpose_id, generation,
            checkpoint_digest, predecessor_digest, candidate_digest, proof_digest,
            source_snapshot_digest, source_memory_snapshot_digest, tokenizer_digest,
            publication_digest, checkpoint_json, proof_json, published_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    .bind(checkpoint.source_memory_snapshot_digest.to_string())
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

#[tokio::test]
async fn tampered_immutable_trigger_fails_store_reopen() {
    let (temp, store, _lease, _fence) = prepared().await;
    sqlx::query("DROP TRIGGER cognitive_qualified_compact_checkpoints_no_update")
        .execute(&store.pool)
        .await
        .expect("drop immutable update guard");
    sqlx::query(
        "CREATE TRIGGER cognitive_qualified_compact_checkpoints_no_update
         BEFORE UPDATE ON cognitive_qualified_compact_checkpoints BEGIN
             SELECT 1;
         END",
    )
    .execute(&store.pool)
    .await
    .expect("replace immutable update guard");
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
        evaluator_key_digest: Digest32::of_bytes(
            &proof_witness(&proof).evaluator_verifying_key,
        ),
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

#[test]
fn persisted_proof_image_rejects_tampered_raw_signature() {
    let checkpoint = checkpoint(2, digest("bootstrap-predecessor"), "signature-tamper");
    let proof = proof(&checkpoint, "signature-tamper");
    let witness = proof_witness(&proof);
    let mut image = ProofImageV2::from_contract(&proof, &witness).expect("proof image");
    image.qualification_signature[0] ^= 1;
    assert!(matches!(
        image.to_contract(),
        Err(QualifiedCompactStoreError::Corrupt(ref message))
            if message.contains("proof signature witness")
    ));
}

#[test]
fn checkpoint_capacity_is_a_bounded_stop_not_corruption() {
    assert!(ensure_checkpoint_capacity(MAX_QUALIFIED_CHECKPOINT_ROWS - 1).is_ok());
    assert!(matches!(
        ensure_checkpoint_capacity(MAX_QUALIFIED_CHECKPOINT_ROWS),
        Err(QualifiedCompactStoreError::CapacityExceeded { maximum })
            if maximum == MAX_QUALIFIED_CHECKPOINT_ROWS
    ));
}
