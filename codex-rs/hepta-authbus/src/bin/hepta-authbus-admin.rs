//! Offline administrator for the single-owner AuthBus authority store.
//!
//! The tool never exposes the crate-private writer. It acquires the same
//! `AuthBusAuthorityHost` owner fence used by the product, keeps that owner live
//! while producing a checkpointed SQLite snapshot, and verifies a matched
//! database/witness pair by opening it through the production recovery path.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::env;
use std::error::Error as StdError;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::AuthBusAuthorityHost;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as ShaDigest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

const MAX_CHECKPOINT_BYTES: u64 = 4096;
const MAX_OWNER_ID_BYTES: usize = 256;

type AnyError = Box<dyn StdError + Send + Sync>;
type Result<T> = std::result::Result<T, AnyError>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Command {
    Bootstrap,
    Backup,
    RestoreCheck,
}

#[derive(Debug)]
struct Options {
    command: Command,
    database: PathBuf,
    checkpoint: PathBuf,
    owner_id: String,
    database_out: Option<PathBuf>,
    checkpoint_out: Option<PathBuf>,
    manifest: Option<PathBuf>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CheckpointDocument {
    schema_version: u32,
    owner_id: String,
    generation: u64,
    digest: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BackupReceipt {
    schema: String,
    owner_id: String,
    created_at_unix_ms: u64,
    source_database: PathBuf,
    source_checkpoint: PathBuf,
    database_backup: PathBuf,
    checkpoint_backup: PathBuf,
    database_sha256: String,
    checkpoint_sha256: String,
    database_bytes: u64,
    checkpoint_bytes: u64,
    checkpoint_generation: u64,
    checkpoint_digest: String,
}

#[derive(Debug, Serialize)]
struct BootstrapReceipt {
    schema: &'static str,
    owner_id: String,
    database: PathBuf,
    checkpoint: PathBuf,
    checkpoint_generation: u64,
    checkpoint_digest: String,
}

#[derive(Debug, Serialize)]
struct RestoreCheckReceipt {
    schema: &'static str,
    owner_id: String,
    database: PathBuf,
    checkpoint: PathBuf,
    database_sha256: String,
    checkpoint_sha256: String,
    checkpoint_generation: u64,
    checkpoint_digest: String,
    verified: bool,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    match run(env::args().skip(1)).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("hepta-authbus-admin: {error}");
            ExitCode::FAILURE
        }
    }
}

async fn run(arguments: impl Iterator<Item = String>) -> Result<()> {
    let options = Options::parse(arguments)?;
    match options.command {
        Command::Bootstrap => {
            let receipt = bootstrap(&options).await?;
            print_json(&receipt)?;
        }
        Command::Backup => {
            let receipt = backup(&options).await?;
            print_json(&receipt)?;
        }
        Command::RestoreCheck => {
            let receipt = restore_check(&options).await?;
            print_json(&receipt)?;
        }
    }
    Ok(())
}

impl Options {
    fn parse(mut arguments: impl Iterator<Item = String>) -> Result<Self> {
        let command = match arguments.next().as_deref() {
            Some("bootstrap") => Command::Bootstrap,
            Some("backup") => Command::Backup,
            Some("restore-check") => Command::RestoreCheck,
            _ => {
                return Err(
                    "usage: hepta-authbus-admin <bootstrap|backup|restore-check> \
                     --database ABS --checkpoint ABS --owner-id ID \
                     [--database-out ABS --checkpoint-out ABS --manifest ABS]"
                        .into(),
                );
            }
        };
        let mut values = BTreeMap::new();
        while let Some(flag) = arguments.next() {
            if !flag.starts_with("--") {
                return Err(format!("unexpected positional argument: {flag}").into());
            }
            let value = arguments
                .next()
                .ok_or_else(|| format!("missing value for {flag}"))?;
            if values.insert(flag.clone(), value).is_some() {
                return Err(format!("duplicate option: {flag}").into());
            }
        }

        let database = absolute(take(&mut values, "--database")?)?;
        let checkpoint = absolute(take(&mut values, "--checkpoint")?)?;
        let owner_id = take(&mut values, "--owner-id")?;
        if owner_id.is_empty() || owner_id.len() > MAX_OWNER_ID_BYTES {
            return Err("owner id is empty or exceeds 256 bytes".into());
        }
        let database_out = optional_path(&mut values, "--database-out")?;
        let checkpoint_out = optional_path(&mut values, "--checkpoint-out")?;
        let manifest = optional_path(&mut values, "--manifest")?;
        if !values.is_empty() {
            return Err(
                format!(
                    "unknown options: {}",
                    values.keys().cloned().collect::<Vec<_>>().join(", ")
                )
                .into(),
            );
        }

        match command {
            Command::Bootstrap => {
                reject_present("--database-out", database_out.as_ref())?;
                reject_present("--checkpoint-out", checkpoint_out.as_ref())?;
                reject_present("--manifest", manifest.as_ref())?;
            }
            Command::Backup => {
                if database_out.is_none() || checkpoint_out.is_none() || manifest.is_none() {
                    return Err(
                        "backup requires --database-out, --checkpoint-out and --manifest".into(),
                    );
                }
            }
            Command::RestoreCheck => {
                reject_present("--database-out", database_out.as_ref())?;
                reject_present("--checkpoint-out", checkpoint_out.as_ref())?;
                if manifest.is_none() {
                    return Err("restore-check requires --manifest".into());
                }
            }
        }

        Ok(Self {
            command,
            database,
            checkpoint,
            owner_id,
            database_out,
            checkpoint_out,
            manifest,
        })
    }
}

fn take(values: &mut BTreeMap<String, String>, name: &str) -> Result<String> {
    values
        .remove(name)
        .ok_or_else(|| format!("missing required option {name}").into())
}

fn optional_path(
    values: &mut BTreeMap<String, String>,
    name: &str,
) -> Result<Option<PathBuf>> {
    values.remove(name).map(absolute).transpose()
}

fn absolute(value: String) -> Result<PathBuf> {
    let path = PathBuf::from(value);
    if !path.is_absolute() {
        return Err(format!("path must be absolute: {}", path.display()).into());
    }
    Ok(path)
}

fn reject_present(name: &str, value: Option<&PathBuf>) -> Result<()> {
    if value.is_some() {
        return Err(format!("{name} is not valid for this command").into());
    }
    Ok(())
}

async fn bootstrap(options: &Options) -> Result<BootstrapReceipt> {
    validate_distinct_private_paths(&options.database, &options.checkpoint, true)?;
    let host = AuthBusAuthorityHost::bootstrap(
        &options.database,
        options.checkpoint.clone(),
        &options.owner_id,
    )
    .await?;
    drop(host);
    let checkpoint = read_checkpoint(&options.checkpoint)?;
    validate_checkpoint_owner(&checkpoint, &options.owner_id)?;
    Ok(BootstrapReceipt {
        schema: "hepta.authbus.bootstrap-receipt.v1",
        owner_id: options.owner_id.clone(),
        database: options.database.clone(),
        checkpoint: options.checkpoint.clone(),
        checkpoint_generation: checkpoint.generation,
        checkpoint_digest: checkpoint.digest,
    })
}

async fn backup(options: &Options) -> Result<BackupReceipt> {
    let database_out = options
        .database_out
        .as_ref()
        .ok_or("missing database backup destination")?;
    let checkpoint_out = options
        .checkpoint_out
        .as_ref()
        .ok_or("missing checkpoint backup destination")?;
    let manifest = options.manifest.as_ref().ok_or("missing manifest path")?;
    validate_distinct_private_paths(database_out, checkpoint_out, true)?;
    validate_new_private_path(manifest)?;

    let result = backup_inner(options, database_out, checkpoint_out, manifest).await;
    if result.is_err() {
        remove_if_present(database_out);
        remove_if_present(checkpoint_out);
        remove_if_present(manifest);
    }
    result
}

async fn backup_inner(
    options: &Options,
    database_out: &Path,
    checkpoint_out: &Path,
    manifest: &Path,
) -> Result<BackupReceipt> {
    let host = AuthBusAuthorityHost::open(
        &options.database,
        options.checkpoint.clone(),
        &options.owner_id,
    )
    .await?;
    host.maintenance().sync_checkpoint().await?;

    checkpoint_sqlite(&options.database).await?;
    copy_private_file(&options.database, database_out, None)?;
    copy_private_file(
        &options.checkpoint,
        checkpoint_out,
        Some(MAX_CHECKPOINT_BYTES),
    )?;

    let checkpoint = read_checkpoint(checkpoint_out)?;
    validate_checkpoint_owner(&checkpoint, &options.owner_id)?;
    let receipt = BackupReceipt {
        schema: "hepta.authbus.backup-receipt.v1".to_owned(),
        owner_id: options.owner_id.clone(),
        created_at_unix_ms: now_unix_ms()?,
        source_database: options.database.clone(),
        source_checkpoint: options.checkpoint.clone(),
        database_backup: database_out.to_path_buf(),
        checkpoint_backup: checkpoint_out.to_path_buf(),
        database_sha256: sha256_file(database_out, None)?,
        checkpoint_sha256: sha256_file(checkpoint_out, Some(MAX_CHECKPOINT_BYTES))?,
        database_bytes: std::fs::metadata(database_out)?.len(),
        checkpoint_bytes: std::fs::metadata(checkpoint_out)?.len(),
        checkpoint_generation: checkpoint.generation,
        checkpoint_digest: checkpoint.digest,
    };
    write_private_json(manifest, &receipt)?;
    drop(host);
    Ok(receipt)
}

async fn restore_check(options: &Options) -> Result<RestoreCheckReceipt> {
    let manifest_path = options.manifest.as_ref().ok_or("missing manifest path")?;
    let manifest_bytes = read_bounded(manifest_path, 64 * 1024)?;
    let manifest: BackupReceipt = serde_json::from_slice(&manifest_bytes)?;
    if manifest.schema != "hepta.authbus.backup-receipt.v1"
        || manifest.owner_id != options.owner_id
        || manifest.database_backup != options.database
        || manifest.checkpoint_backup != options.checkpoint
    {
        return Err("backup manifest identity does not match restore-check arguments".into());
    }
    let database_sha256 = sha256_file(&options.database, None)?;
    let checkpoint_sha256 = sha256_file(&options.checkpoint, Some(MAX_CHECKPOINT_BYTES))?;
    if database_sha256 != manifest.database_sha256
        || checkpoint_sha256 != manifest.checkpoint_sha256
        || std::fs::metadata(&options.database)?.len() != manifest.database_bytes
        || std::fs::metadata(&options.checkpoint)?.len() != manifest.checkpoint_bytes
    {
        return Err("backup bytes do not match the immutable manifest".into());
    }
    let checkpoint = read_checkpoint(&options.checkpoint)?;
    validate_checkpoint_owner(&checkpoint, &options.owner_id)?;
    if checkpoint.generation != manifest.checkpoint_generation
        || checkpoint.digest != manifest.checkpoint_digest
    {
        return Err("checkpoint document does not match the backup manifest".into());
    }

    let host = AuthBusAuthorityHost::open(
        &options.database,
        options.checkpoint.clone(),
        &options.owner_id,
    )
    .await?;
    host.maintenance().sync_checkpoint().await?;
    drop(host);

    Ok(RestoreCheckReceipt {
        schema: "hepta.authbus.restore-check-receipt.v1",
        owner_id: options.owner_id.clone(),
        database: options.database.clone(),
        checkpoint: options.checkpoint.clone(),
        database_sha256,
        checkpoint_sha256,
        checkpoint_generation: checkpoint.generation,
        checkpoint_digest: checkpoint.digest,
        verified: true,
    })
}

async fn checkpoint_sqlite(database: &Path) -> Result<()> {
    let connect = SqliteConnectOptions::new()
        .filename(database)
        .create_if_missing(false)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(30));
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(connect)
        .await?;

    let quick_check: String = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_one(&pool)
        .await?;
    if quick_check != "ok" {
        pool.close().await;
        return Err("SQLite quick_check failed before backup".into());
    }
    let foreign_keys = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(&pool)
        .await?;
    if !foreign_keys.is_empty() {
        pool.close().await;
        return Err("SQLite foreign_key_check failed before backup".into());
    }
    let row = sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
        .fetch_one(&pool)
        .await?;
    let busy: i64 = row.try_get(0usize)?;
    if busy != 0 {
        pool.close().await;
        return Err("SQLite WAL checkpoint remained busy".into());
    }
    pool.close().await;
    sync_existing_file(database)?;
    Ok(())
}

fn read_checkpoint(path: &Path) -> Result<CheckpointDocument> {
    let bytes = read_bounded(path, MAX_CHECKPOINT_BYTES)?;
    let checkpoint: CheckpointDocument = serde_json::from_slice(&bytes)?;
    if checkpoint.schema_version != 1
        || checkpoint.owner_id.is_empty()
        || checkpoint.owner_id.len() > MAX_OWNER_ID_BYTES
        || checkpoint.generation == 0
        || checkpoint.digest.len() != 64
        || !checkpoint.digest.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err("invalid checkpoint document".into());
    }
    Ok(checkpoint)
}

fn validate_checkpoint_owner(checkpoint: &CheckpointDocument, owner_id: &str) -> Result<()> {
    if checkpoint.owner_id != owner_id {
        return Err("checkpoint owner does not match requested owner".into());
    }
    Ok(())
}

fn validate_distinct_private_paths(left: &Path, right: &Path, require_absent: bool) -> Result<()> {
    if require_absent {
        validate_new_private_path(left)?;
        validate_new_private_path(right)?;
    } else {
        validate_existing_private_path(left)?;
        validate_existing_private_path(right)?;
    }
    let left_parent = canonical_parent(left)?;
    let right_parent = canonical_parent(right)?;
    if left_parent == right_parent {
        return Err("database and checkpoint must use distinct private directories".into());
    }
    Ok(())
}

fn validate_new_private_path(path: &Path) -> Result<()> {
    if path.exists() {
        return Err(format!("destination already exists: {}", path.display()).into());
    }
    validate_private_parent(path)
}

fn validate_existing_private_path(path: &Path) -> Result<()> {
    if !path.is_file() {
        return Err(format!("required file is missing: {}", path.display()).into());
    }
    validate_private_parent(path)
}

fn canonical_parent(path: &Path) -> Result<PathBuf> {
    Ok(path
        .parent()
        .ok_or("path has no parent")?
        .canonicalize()?)
}

#[cfg(unix)]
fn validate_private_parent(path: &Path) -> Result<()> {
    let parent = path.parent().ok_or("path has no parent")?;
    let canonical = parent.canonicalize()?;
    if canonical != parent {
        return Err(format!("parent path is not canonical: {}", parent.display()).into());
    }
    let metadata = std::fs::metadata(&canonical)?;
    if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
        return Err(format!("parent directory is not private: {}", parent.display()).into());
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_private_parent(_path: &Path) -> Result<()> {
    Err("AuthBus administration requires Unix private-file semantics".into())
}

#[cfg(unix)]
fn copy_private_file(source: &Path, destination: &Path, limit: Option<u64>) -> Result<()> {
    validate_existing_private_path(source)?;
    validate_new_private_path(destination)?;
    let source_meta = std::fs::symlink_metadata(source)?;
    if !source_meta.is_file() || source_meta.nlink() != 1 {
        return Err(format!("unsafe backup source: {}", source.display()).into());
    }

    let mut input = File::open(source)?;
    let mut output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(destination)?;
    let copied = match limit {
        Some(maximum) => io::copy(&mut Read::by_ref(&mut input).take(maximum + 1), &mut output)?,
        None => io::copy(&mut input, &mut output)?,
    };
    if limit.is_some_and(|maximum| copied > maximum) {
        return Err(format!("backup source exceeds bound: {}", source.display()).into());
    }
    output.sync_all()?;
    std::fs::set_permissions(destination, std::fs::Permissions::from_mode(0o600))?;
    sync_directory(destination.parent().ok_or("destination has no parent")?)?;
    Ok(())
}

#[cfg(not(unix))]
fn copy_private_file(_source: &Path, _destination: &Path, _limit: Option<u64>) -> Result<()> {
    Err("AuthBus backup requires Unix private-file semantics".into())
}

fn read_bounded(path: &Path, maximum: u64) -> Result<Vec<u8>> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(maximum + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(format!("file exceeds bound: {}", path.display()).into());
    }
    Ok(bytes)
}

fn sha256_file(path: &Path, maximum: Option<u64>) -> Result<String> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        total = total
            .checked_add(u64::try_from(read)?)
            .ok_or("file size overflow")?;
        if maximum.is_some_and(|bound| total > bound) {
            return Err(format!("file exceeds bound: {}", path.display()).into());
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(unix)]
fn write_private_json(path: &Path, value: &impl Serialize) -> Result<()> {
    validate_new_private_path(path)?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    sync_directory(path.parent().ok_or("manifest path has no parent")?)?;
    Ok(())
}

#[cfg(not(unix))]
fn write_private_json(_path: &Path, _value: &impl Serialize) -> Result<()> {
    Err("AuthBus administration requires Unix private-file semantics".into())
}

fn sync_existing_file(path: &Path) -> Result<()> {
    File::open(path)?.sync_all()?;
    sync_directory(path.parent().ok_or("path has no parent")?)
}

fn sync_directory(path: &Path) -> Result<()> {
    File::open(path)?.sync_all()?;
    Ok(())
}

fn remove_if_present(path: &Path) {
    match std::fs::remove_file(path) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(_) => {}
    }
}

fn now_unix_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn print_json(value: &impl Serialize) -> Result<()> {
    let stdout = io::stdout();
    let mut lock = stdout.lock();
    serde_json::to_writer_pretty(&mut lock, value)?;
    lock.write_all(b"\n")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    #[tokio::test]
    async fn bootstrap_backup_and_restore_check_form_one_matched_bundle() {
        let database_root = tempfile::tempdir().unwrap();
        let checkpoint_root = tempfile::tempdir().unwrap();
        let database_backup_root = tempfile::tempdir().unwrap();
        let checkpoint_backup_root = tempfile::tempdir().unwrap();
        let manifest_root = tempfile::tempdir().unwrap();

        for root in [
            &database_root,
            &checkpoint_root,
            &database_backup_root,
            &checkpoint_backup_root,
            &manifest_root,
        ] {
            std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
                .unwrap();
        }

        let database = database_root.path().join("authority.sqlite");
        let checkpoint = checkpoint_root.path().join("authority.checkpoint.json");
        let database_backup = database_backup_root.path().join("authority.sqlite");
        let checkpoint_backup = checkpoint_backup_root
            .path()
            .join("authority.checkpoint.json");
        let manifest = manifest_root.path().join("backup.json");
        let owner_id = "authbus-admin-test";

        let bootstrap_options = Options {
            command: Command::Bootstrap,
            database: database.clone(),
            checkpoint: checkpoint.clone(),
            owner_id: owner_id.to_owned(),
            database_out: None,
            checkpoint_out: None,
            manifest: None,
        };
        let bootstrap_receipt = bootstrap(&bootstrap_options).await.unwrap();
        assert_eq!(bootstrap_receipt.checkpoint_generation, 1);

        let backup_options = Options {
            command: Command::Backup,
            database,
            checkpoint,
            owner_id: owner_id.to_owned(),
            database_out: Some(database_backup.clone()),
            checkpoint_out: Some(checkpoint_backup.clone()),
            manifest: Some(manifest.clone()),
        };
        let backup_receipt = backup(&backup_options).await.unwrap();
        assert_eq!(backup_receipt.checkpoint_generation, 1);
        assert_eq!(backup_receipt.database_sha256.len(), 64);
        assert_eq!(backup_receipt.checkpoint_sha256.len(), 64);

        let restore_options = Options {
            command: Command::RestoreCheck,
            database: database_backup,
            checkpoint: checkpoint_backup,
            owner_id: owner_id.to_owned(),
            database_out: None,
            checkpoint_out: None,
            manifest: Some(manifest),
        };
        let restore_receipt = restore_check(&restore_options).await.unwrap();
        assert!(restore_receipt.verified);
        assert_eq!(restore_receipt.checkpoint_generation, 1);
    }

    #[test]
    fn parser_requires_complete_backup_destinations() {
        let error = Options::parse(
            [
                "backup",
                "--database",
                "/tmp/a.sqlite",
                "--checkpoint",
                "/tmp/b.json",
                "--owner-id",
                "owner",
            ]
            .into_iter()
            .map(str::to_owned),
        )
        .unwrap_err();
        assert!(error.to_string().contains("--database-out"));
    }
}
