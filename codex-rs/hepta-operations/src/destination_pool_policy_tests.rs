use super::*;

#[tokio::test]
async fn destination_constructor_preserves_all_connection_policies() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store =
        DestinationDedupeStore::open_standalone(&directory.path().join("destination.sqlite3"))
            .await
            .expect("destination");
    crate::sqlite_pool_policy_tests::assert_operation_policy(&store.pool).await;
    store.pool.close().await;
}
