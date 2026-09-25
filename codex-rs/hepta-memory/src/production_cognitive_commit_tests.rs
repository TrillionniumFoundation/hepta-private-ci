use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::*;

struct Hold(Arc<AtomicBool>);
impl Drop for Hold {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

#[tokio::test]
async fn caller_cancellation_does_not_release_guard_before_sqlite_commit()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::TempDir::new()?;
    let pool =
        codex_state::open_durable_sqlite_pool(&temp.path().join("commit.sqlite3"), 2).await?;
    sqlx::query("CREATE TABLE counter (value INTEGER NOT NULL)")
        .execute(&pool)
        .await?;
    sqlx::query("INSERT INTO counter VALUES (0)")
        .execute(&pool)
        .await?;
    let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query("UPDATE counter SET value=1")
        .execute(&mut *transaction)
        .await?;
    let released = Arc::new(AtomicBool::new(false));
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (proceed_tx, proceed_rx) = tokio::sync::oneshot::channel();
    let (done_tx, done_rx) = tokio::sync::oneshot::channel();
    let guard = ProductionAuthorityUseGuard::from_verified_use(Hold(Arc::clone(&released)));
    let waiter = tokio::spawn(complete(
        async move {
            let _ = entered_tx.send(());
            proceed_rx.await.map_err(unavailable)?;
            transaction.commit().await.map_err(unavailable)?;
            let _ = done_tx.send(());
            Ok(())
        },
        guard,
        (),
    ));
    entered_rx.await?;
    waiter.abort();
    assert!(waiter.await.is_err());
    assert!(!released.load(Ordering::SeqCst));
    proceed_tx.send(()).map_err(|_| "commit owner lost")?;
    done_rx.await?;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while !released.load(Ordering::SeqCst) {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    let value: i64 = sqlx::query_scalar("SELECT value FROM counter")
        .fetch_one(&pool)
        .await?;
    assert_eq!(value, 1);
    Ok(())
}

#[test]
fn runtime_shutdown_retains_authority_and_writer_until_commit_finishes()
-> Result<(), Box<dyn std::error::Error>> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    let temp = tempfile::TempDir::new()?;
    let pool = runtime.block_on(codex_state::open_durable_sqlite_pool(
        &temp.path().join("shutdown.sqlite3"),
        2,
    ))?;
    runtime.block_on(sqlx::query("CREATE TABLE committed (value INTEGER)").execute(&pool))?;
    let mut keeper = runtime.block_on(pool.acquire())?;
    let mut transaction = runtime.block_on(pool.begin_with("BEGIN IMMEDIATE"))?;
    runtime.block_on(sqlx::query("INSERT INTO committed VALUES (1)").execute(&mut *transaction))?;
    let authority_released = Arc::new(AtomicBool::new(false));
    let owner_released = Arc::new(AtomicBool::new(false));
    let (started_tx, started_rx) = std::sync::mpsc::channel();
    let (proceed_tx, proceed_rx) = tokio::sync::oneshot::channel();
    let (finished_tx, finished_rx) = std::sync::mpsc::channel();
    let guard =
        ProductionAuthorityUseGuard::from_verified_use(Hold(Arc::clone(&authority_released)));
    let owner = Hold(Arc::clone(&owner_released));
    runtime.spawn(complete(
        async move {
            started_tx.send(()).map_err(unavailable)?;
            proceed_rx.await.map_err(unavailable)?;
            transaction.commit().await.map_err(unavailable)?;
            finished_tx.send(()).map_err(unavailable)?;
            Ok(())
        },
        guard,
        owner,
    ));
    started_rx.recv_timeout(std::time::Duration::from_secs(10))?;
    runtime.shutdown_background();
    assert!(!authority_released.load(Ordering::SeqCst));
    assert!(!owner_released.load(Ordering::SeqCst));
    proceed_tx
        .send(())
        .map_err(|_| "commit owner disappeared")?;
    finished_rx.recv_timeout(std::time::Duration::from_secs(10))?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    while !(authority_released.load(Ordering::SeqCst) && owner_released.load(Ordering::SeqCst)) {
        assert!(
            std::time::Instant::now() < deadline,
            "commit holds were not released"
        );
        std::thread::yield_now();
    }
    let reader = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let count: i64 = reader
        .block_on(sqlx::query_scalar("SELECT COUNT(*) FROM committed").fetch_one(&mut *keeper))?;
    assert_eq!(count, 1);
    // SQLx pool-connection Drop schedules work. Dispose the retained reader
    // connection inside its live runtime, after verifying the shutdown commit.
    reader.block_on(async move {
        drop(keeper);
        pool.close().await;
    });
    Ok(())
}
