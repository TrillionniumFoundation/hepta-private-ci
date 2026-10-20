use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::IdentityDisposition;
use super::LogicalTurnAttempt;
use super::LogicalTurnAttemptRequest;
use super::LogicalTurnAttemptTransition;
use super::LogicalTurnRegistryError;
use super::LogicalTurnRequest;
use super::LogicalTurnReservation;
use super::MAX_REGISTRY_ROWS;
use super::append_attempt;
use super::append_lease;
use super::attempt_from_existing_for_supersede;
use super::ensure_identity;
use super::genesis_attempt_digest;
use super::logical_identity_digest;
use super::now_unix_i64;
use super::now_unix_seconds;
use crate::CognitiveStore;
use crate::LocalLeaseBinding;
use crate::LocalLeaseState;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use codex_hepta_contracts::Sha256Digest;

fn physical_request(number: usize, expiry: u64) -> LogicalTurnAttemptRequest {
    LogicalTurnAttemptRequest::new(
        format!("attempt:capacity:{number}"),
        format!("lease:capacity:{number}"),
        format!("journal:capacity:{number}"),
        format!("trajectory:capacity:{number}"),
        format!("occurrence:capacity:{number}"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        format!("fence:capacity:{number}"),
        expiry,
    )
    .expect("physical request")
}

async fn seed_near_limit(
    store: &CognitiveStore,
    head_expiry: u64,
) -> (
    LogicalTurnRequest,
    LogicalTurnAttemptRequest,
    LogicalTurnAttempt,
) {
    let request = LogicalTurnRequest::new(
        "logical:capacity",
        "scope:capacity",
        Sha256Digest::for_bytes(b"capacity-logical-binding"),
    )
    .expect("logical request");
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("seed");
    let identity = logical_identity_digest(
        store.owner_agent_id(),
        &request.logical_turn_id,
        &request.scope_key,
        &request.logical_binding_sha256,
    );
    assert_eq!(
        ensure_identity(
            &mut transaction,
            store.owner_agent_id(),
            &request,
            &identity
        )
        .await
        .expect("identity"),
        IdentityDisposition::Inserted
    );
    let mut previous: Option<(LogicalTurnAttempt, crate::LocalLease)> = None;
    let last_number = MAX_REGISTRY_ROWS / 2;
    let mut last_request = None;
    for number in 1..=last_number {
        let expiry = if number == last_number {
            head_expiry
        } else {
            1
        };
        let physical = physical_request(number, expiry);
        let binding = LocalLeaseBinding::new(
            physical.authority_epoch,
            physical.owner_epoch,
            physical.lease_expires_at_unix_seconds,
        )
        .expect("lease binding");
        let lease = append_lease(
            &mut transaction,
            &physical.lease_id,
            store.owner_agent_id(),
            physical.generation,
            &physical.fencing_token,
            LocalLeaseState::Active,
            /*previous*/ None,
            Some(&binding),
        )
        .await
        .expect("fresh physical lease");
        let (sequence, previous_digest) = if let Some((prior, prior_lease)) = previous.as_ref() {
            let superseded = append_attempt(
                &mut transaction,
                store.owner_agent_id(),
                &request,
                &attempt_from_existing_for_supersede(prior),
                prior.registry_sequence + 1,
                prior.attempt_no,
                LogicalTurnAttemptTransition::Superseded,
                Some(&physical.attempt_id),
                &prior.attempt_sha256,
                now_unix_i64().expect("clock"),
            )
            .await
            .expect("superseded transition");
            let old_binding = LocalLeaseBinding::new(
                prior.authority_epoch,
                prior.owner_epoch,
                prior.lease_expires_at_unix_seconds,
            )
            .expect("historical binding");
            append_lease(
                &mut transaction,
                &prior.lease_id,
                store.owner_agent_id(),
                prior.generation,
                &prior.fencing_token,
                LocalLeaseState::RolledBack,
                Some(prior_lease),
                Some(&old_binding),
            )
            .await
            .expect("retire old lease");
            (prior.registry_sequence + 2, superseded.attempt_sha256)
        } else {
            (1, genesis_attempt_digest())
        };
        let active = append_attempt(
            &mut transaction,
            store.owner_agent_id(),
            &request,
            &physical,
            sequence,
            u64::try_from(number).expect("attempt number"),
            LogicalTurnAttemptTransition::Active,
            /*superseded_by_attempt_id*/ None,
            &previous_digest,
            now_unix_i64().expect("clock"),
        )
        .await
        .expect("active transition");
        previous = Some((active, lease));
        last_request = Some(physical);
    }
    assert!(
        sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(&mut *transaction)
            .await
            .expect("foreign keys")
            .is_empty()
    );
    transaction.commit().await.expect("seed commit");
    (
        request,
        last_request.expect("head request"),
        previous.expect("head").0,
    )
}

async fn complete_rows(store: &CognitiveStore) -> (Vec<String>, Vec<String>, Vec<String>) {
    let identities = sqlx::query_scalar(
        "SELECT json_array(owner_agent_id, logical_turn_id, scope_key,
                 logical_binding_sha256, identity_sha256, recorded_at_unix_seconds)
         FROM cognitive_logical_turns ORDER BY owner_agent_id, logical_turn_id",
    )
    .fetch_all(&store.pool)
    .await
    .expect("identity rows");
    let attempts = sqlx::query_scalar(
        "SELECT json_array(owner_agent_id, logical_turn_id, registry_sequence,
                 attempt_no, attempt_id, transition, superseded_by_attempt_id,
                 logical_binding_sha256, lease_id, lease_sequence, lease_head_sha256,
                 journal_id, trajectory_id, occurrence_key, generation, authority_epoch,
                 owner_epoch, fencing_token, lease_expires_at_unix_seconds,
                 previous_sha256, attempt_sha256, recorded_at_unix_seconds)
         FROM cognitive_logical_turn_attempts
         ORDER BY owner_agent_id, logical_turn_id, registry_sequence",
    )
    .fetch_all(&store.pool)
    .await
    .expect("attempt rows");
    let leases = sqlx::query_scalar(
        "SELECT json_array(lease_id, lease_sequence, owner_agent_id, generation,
                 fencing_token, state, authority_epoch, owner_epoch,
                 lease_expires_at_unix_seconds, previous_sha256, lease_sha256,
                 recorded_at_unix_seconds)
         FROM cognitive_local_leases ORDER BY lease_id, lease_sequence",
    )
    .fetch_all(&store.pool)
    .await
    .expect("lease rows");
    (identities, attempts, leases)
}

#[tokio::test]
async fn near_limit_takeover_second_append_rolls_back_all_three_journals_and_reopens() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(241);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout).await.expect("store");
    let (request, _, head) = seed_near_limit(&store, /*head_expiry*/ 1).await;
    let inspection = store
        .inspect_logical_turn(request.clone())
        .await
        .expect("full valid chain");
    assert_eq!(inspection.head, Some(head.clone()));
    assert_eq!(
        head.registry_sequence,
        u64::try_from(MAX_REGISTRY_ROWS - 1).expect("near limit")
    );
    let before = complete_rows(&store).await;
    let successor = physical_request(
        MAX_REGISTRY_ROWS,
        now_unix_seconds().expect("clock") + 3_600,
    );
    let result = store
        .reserve_or_replay_logical_turn(request.clone(), successor)
        .await;
    assert!(
        matches!(result, Err(LogicalTurnRegistryError::Invalid(reason))
        if reason == format!("logical-turn registry exceeds {MAX_REGISTRY_ROWS} event rows"))
    );
    // Includes the first superseded append, the old rollback marker, and the
    // newly allocated successor lease: failure of the second append loses all.
    assert_eq!(complete_rows(&store).await, before);
    assert_eq!(
        store
            .inspect_logical_turn(request.clone())
            .await
            .expect("unchanged valid head")
            .head,
        Some(head.clone())
    );
    store.pool.close().await;
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("valid reopen after rejection");
    assert_eq!(complete_rows(&reopened).await, before);
    assert_eq!(
        reopened
            .inspect_logical_turn(request)
            .await
            .expect("retained head")
            .head,
        Some(head)
    );
}

#[tokio::test]
async fn near_limit_active_registry_exact_replay_keeps_every_row_and_reopens() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(242);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout).await.expect("store");
    let (request, physical, head) =
        seed_near_limit(&store, now_unix_seconds().expect("clock") + 3_600).await;
    let before = complete_rows(&store).await;
    assert_eq!(
        store
            .reserve_or_replay_logical_turn(request.clone(), physical.clone())
            .await
            .expect("replay"),
        LogicalTurnReservation::Replayed {
            attempt: head.clone()
        }
    );
    assert_eq!(complete_rows(&store).await, before);
    store.pool.close().await;
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("valid near-limit reopen");
    assert_eq!(
        reopened
            .reserve_or_replay_logical_turn(request, physical)
            .await
            .expect("reopened replay"),
        LogicalTurnReservation::Replayed { attempt: head }
    );
    assert_eq!(complete_rows(&reopened).await, before);
}
