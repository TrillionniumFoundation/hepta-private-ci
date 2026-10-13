//! SDK's disposable derived cache must migrate without touching Hepta state.
use matrix_sdk_sqlite::SqliteEventCacheStore;
use pretty_assertions::assert_eq;
use rusqlite::Connection;

#[tokio::test]
async fn sdk018_derived_cache_migrates_and_reopens() -> Result<(), Box<dyn std::error::Error>> {
    let fixture = tempfile::tempdir()?;
    let path = fixture.path().join("matrix-sdk-event-cache.sqlite3");
    {
        let db = Connection::open(&path)?;
        db.execute_batch(include_str!("support/sdk018_event_cache.sql"))?;
        assert_eq!(
            db.query_row("SELECT COUNT(*) FROM events", [], |row| row
                .get::<_, i64>(0))?,
            1
        );
    }
    let authoritative = fixture.path().join("hepta-authoritative-sentinel");
    std::fs::write(
        &authoritative,
        b"durable cursor and authorization remain owned by Hepta",
    )?;
    let store = SqliteEventCacheStore::open(fixture.path(), /*passphrase*/ None).await?;
    store.close().await?;
    store.reopen().await?;
    store.close().await?;
    let reopened = SqliteEventCacheStore::open(fixture.path(), /*passphrase*/ None).await?;
    reopened.close().await?;
    let db = Connection::open(&path)?;
    assert_eq!(
        db.query_row("SELECT COUNT(*) FROM events", [], |row| row
            .get::<_, i64>(0))?,
        0
    );
    let version: Vec<u8> = db.query_row("SELECT value FROM kv WHERE key='version'", [], |row| {
        row.get(0)
    })?;
    assert_eq!(version, vec![18]);
    assert_eq!(
        db.query_row("PRAGMA integrity_check", [], |row| row.get::<_, String>(0))?,
        "ok"
    );
    assert_eq!(
        std::fs::read(authoritative)?,
        b"durable cursor and authorization remain owned by Hepta"
    );
    Ok(())
}
