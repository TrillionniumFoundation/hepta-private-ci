use crate::SqliteConfig;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use codex_utils_path::windows_private::Access;
use codex_utils_path::windows_private::PrivateSqliteDirectory;
use sqlx::ConnectOptions;
use sqlx::Connection;
use sqlx::sqlite::SqliteConnectOptions;
use std::ffi::CStr;
use std::ptr;

async fn assert_private_vfs(connection: &mut sqlx::SqliteConnection) -> anyhow::Result<()> {
    let mut connection = connection.lock_handle().await?;
    let mut vfs: *mut libsqlite3_sys::sqlite3_vfs = ptr::null_mut();
    // SAFETY: lock_handle excludes the SQLx worker. The registered VFS is retained
    // by SQLite and the owner context; the output pointer lives through the call.
    let code = unsafe {
        libsqlite3_sys::sqlite3_file_control(
            connection.as_raw_handle().as_ptr(),
            c"main".as_ptr(),
            libsqlite3_sys::SQLITE_FCNTL_VFS_POINTER,
            (&mut vfs as *mut *mut libsqlite3_sys::sqlite3_vfs).cast(),
        )
    };
    assert_eq!(code, libsqlite3_sys::SQLITE_OK);
    assert!(!vfs.is_null());
    // SAFETY: The successful file-control call returned the live registered VFS.
    let name = unsafe { CStr::from_ptr((*vfs).zName) };
    assert!(name.to_bytes().starts_with(b"hepta-private-owner-"));
    Ok(())
}

#[tokio::test]
async fn private_pool_workers_create_qualified_database_and_sidecars() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    let directory = PrivateSqliteDirectory::prepare(&home)?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("private.sqlite3");
    let pool = config.open_private_durable_evidence_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value INTEGER); INSERT INTO fact VALUES (42)")
        .execute(&pool)
        .await?;
    let mut first = pool.acquire().await?;
    let mut second = pool.acquire().await?;
    let mut third = pool.acquire().await?;
    for connection in [&mut *first, &mut *second, &mut *third] {
        assert_private_vfs(connection).await?;
        let value: i64 = sqlx::query_scalar("SELECT value FROM fact")
            .fetch_one(connection)
            .await?;
        assert_eq!(value, 42);
    }
    for name in [
        "private.sqlite3",
        "private.sqlite3-wal",
        "private.sqlite3-shm",
    ] {
        let file = directory.open(name, Access::Read)?;
        directory.file_snapshot(&file)?;
    }
    drop((first, second, third));
    pool.close().await;
    let reopened = config.open_private_durable_evidence_pool(&path).await?;
    let value: i64 = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&reopened)
        .await?;
    assert_eq!(value, 42);
    reopened.close().await;
    drop(directory);
    std::fs::remove_dir_all(home)?;
    Ok(())
}

#[tokio::test]
async fn private_readonly_sqlx_worker_retains_the_explicit_vfs() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    let directory = PrivateSqliteDirectory::prepare(&home)?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("readonly.sqlite3");
    let writer = config.open_private_read_write_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value INTEGER); INSERT INTO fact VALUES (9)")
        .execute(&writer)
        .await?;
    let options = SqliteConfig::with_private_creation_owner(
        SqliteConnectOptions::new()
            .filename(&path)
            .create_if_missing(false)
            .read_only(true),
    )?;
    let mut reader = options.connect().await?;
    assert_private_vfs(&mut reader).await?;
    let value: i64 = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&mut reader)
        .await?;
    assert_eq!(value, 9);
    assert!(
        sqlx::query("UPDATE fact SET value = 10")
            .execute(&mut reader)
            .await
            .is_err()
    );
    for name in [
        "readonly.sqlite3",
        "readonly.sqlite3-wal",
        "readonly.sqlite3-shm",
    ] {
        let file = directory.open(name, Access::Read)?;
        directory.file_snapshot(&file)?;
    }
    reader.close().await?;
    let reader_pool = config.open_private_read_only_pool(&path).await?;
    let mut pooled_reader = reader_pool.acquire().await?;
    assert_private_vfs(&mut pooled_reader).await?;
    let value: i64 = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&mut *pooled_reader)
        .await?;
    assert_eq!(value, 9);
    assert!(
        sqlx::query("UPDATE fact SET value = 11")
            .execute(&mut *pooled_reader)
            .await
            .is_err()
    );
    drop(pooled_reader);
    reader_pool.close().await;
    writer.close().await;
    drop(directory);
    std::fs::remove_dir_all(home)?;
    Ok(())
}
