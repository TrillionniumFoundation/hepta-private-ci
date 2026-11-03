
#[tokio::test]
async fn privileged_sequence_rewind_must_not_hide_next_frontier_event() {
    let root = TempDir::new().unwrap();
    let path = root.path().join("counterexample.sqlite");
    let store = AuthBusAuthorityStore::open(&path).await.unwrap();
    let initial = AuthorityCheckpoint {
        generation: 1,
        digest: store.authority_frontier_digest().await.unwrap(),
    };
    store.initialize_authority_checkpoint(initial).await.unwrap();
    store.create_policy(policy(Digest32::of_bytes(b"sequence-scope")), sample(1, 2_000)).await.unwrap();
    let published = store.reconcile_authority_checkpoint(initial).await.unwrap().unwrap();
    store.advance_authority_checkpoint(initial.generation, published).await.unwrap();
    let applied: i64 = sqlx::query_scalar("SELECT applied_change_id FROM authbus_frontier_accumulator WHERE singleton=1")
        .fetch_one(&store.pool).await.unwrap();
    assert!(applied > 0);
    // Privileged storage-corruption fixture, not a supported caller operation.
    sqlx::query("UPDATE sqlite_sequence SET seq=? WHERE name='authbus_frontier_change'")
        .bind(applied - 1).execute(&store.pool).await.unwrap();
    store.observe_time(sample(2, 2_100)).await.unwrap();
    assert_eq!(store.last_trusted_time().await.unwrap().unwrap().wall_time_ms(), 2_100);
    let new_event: i64 = sqlx::query_scalar("SELECT MAX(change_id) FROM authbus_frontier_change")
        .fetch_one(&store.pool).await.unwrap();
    assert_eq!(new_event, applied);
    let folded = store.authority_frontier_digest().await.unwrap();
    assert_ne!(folded, published.digest, "privileged sequence rewind hid a successfully committed trusted-time event from the incremental frontier");
}
