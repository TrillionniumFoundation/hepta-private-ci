use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::LocalLeaseBinding;
use super::LocalLeaseOutbox;
use super::LocalLeaseOutboxError;
use super::LocalLeaseState;
use super::MAX_LEASE_ROWS;
use super::append_lease;
use super::load_lease_chain;
use super::now_unix_seconds;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

async fn lease_rows(store: &CognitiveStore) -> Vec<String> {
    sqlx::query_scalar(
        "SELECT json_array(lease_id, lease_sequence, owner_agent_id, generation,
                 fencing_token, state, authority_epoch, owner_epoch,
                 lease_expires_at_unix_seconds, previous_sha256, lease_sha256,
                 recorded_at_unix_seconds)
         FROM cognitive_local_leases ORDER BY lease_id, lease_sequence",
    )
    .fetch_all(&store.pool)
    .await
    .expect("complete lease rows")
}

#[tokio::test]
async fn full_lease_chain_rejects_successor_preserves_expiry_replay_and_reopens() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(240);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout).await.expect("store");
    let lease_id = "lease:capacity";
    let binding = LocalLeaseBinding::new(
        /*authority_epoch*/ 1, /*owner_epoch*/ 1,
        /*lease_expires_at_unix_seconds*/ 1,
    )
    .expect("historical bound lease");
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("seed");
    let mut head = None;
    // Real active/terminal generations, each with the owner helper's digest.
    // One transaction avoids repeatedly loading the growing history.
    for sequence in 1..MAX_LEASE_ROWS {
        let generation = u64::try_from(sequence.div_ceil(2)).expect("generation");
        let state = if sequence % 2 == 1 {
            LocalLeaseState::Active
        } else {
            LocalLeaseState::RolledBack
        };
        head = Some(
            append_lease(
                &mut transaction,
                lease_id,
                &owner,
                generation,
                &format!("capacity-fence:{generation}"),
                state,
                head.as_ref(),
                Some(&binding),
            )
            .await
            .expect("valid retained generation"),
        );
    }
    let head = head.expect("active near-limit head");
    let verified = load_lease_chain(&mut transaction, lease_id, &owner)
        .await
        .expect("all hashes and transitions");
    assert_eq!(verified, (Some(head.clone()), MAX_LEASE_ROWS - 1));
    assert!(
        sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(&mut *transaction)
            .await
            .expect("foreign keys")
            .is_empty()
    );
    transaction.commit().await.expect("seed commit");

    let handle = LocalLeaseOutbox::from_lease(&store, &head).expect("expired active handle");
    let terminal = handle.expire_lease().await.expect("last available row");
    assert_eq!(
        terminal.lease_sequence,
        u64::try_from(MAX_LEASE_ROWS).expect("limit")
    );
    let before = lease_rows(&store).await;
    assert_eq!(
        handle.expire_lease().await.expect("exact expiry replay"),
        terminal
    );
    let next_expiry = u64::try_from(now_unix_seconds().expect("clock")).expect("positive") + 3_600;
    let rejected = store
        .acquire_local_lease_bound(
            lease_id,
            binding.authority_epoch,
            binding.owner_epoch,
            head.generation + 1,
            "capacity-fence:next",
            next_expiry,
        )
        .await;
    assert!(matches!(
        rejected,
        Err(LocalLeaseOutboxError::CapacityExceeded {
            resource: "lease journal",
            maximum: MAX_LEASE_ROWS,
        })
    ));
    assert_eq!(lease_rows(&store).await, before);

    store.pool.close().await;
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("bounded reopen");
    assert_eq!(lease_rows(&reopened).await, before);
    assert_eq!(
        reopened
            .inspect_local_lease_head(lease_id)
            .await
            .expect("terminal history")
            .head,
        Some(terminal)
    );
}
