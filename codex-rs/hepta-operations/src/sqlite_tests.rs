//! Operation-owner policy regression reused from reviewed integration 3c516ec.

pub(crate) async fn assert_operation_policy(pool: &sqlx::SqlitePool) -> Result<(), sqlx::Error> {
    assert_eq!(pool.options().get_max_connections(), 4);
    let mut connections = Vec::new();
    for _ in 0..4 {
        let mut connection = pool.acquire().await?;
        let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&mut *connection)
            .await?;
        let sync: i64 = sqlx::query_scalar("PRAGMA synchronous")
            .fetch_one(&mut *connection)
            .await?;
        let foreign: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
            .fetch_one(&mut *connection)
            .await?;
        let busy: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
            .fetch_one(&mut *connection)
            .await?;
        assert_eq!((journal.as_str(), sync, foreign, busy), ("wal", 2, 1, 5000));
        connections.push(connection);
    }
    assert!(
        pool.try_acquire().is_none(),
        "fifth connection must not escape owner bound"
    );
    Ok(())
}
