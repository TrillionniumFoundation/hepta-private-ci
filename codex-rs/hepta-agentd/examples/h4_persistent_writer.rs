#![forbid(unsafe_code)]
#![allow(
    clippy::disallowed_methods,
    reason = "Opt-in qualification harness intentionally opens a read-only SQLite pool and host-local sysfs files."
)]

//! Opt-in H4 persistent prepare/recover harness.
//!
//! This example is deliberately not part of Agentd startup and is never run
//! by default.  `prepare` opens the real `AgentdProductionWriterHost` seam,
//! admits one durable outbox occurrence, records the WAL/FULL and storage
//! cache observations, then waits for an operator-controlled gate.  After a
//! crash or an approved physical power-cycle, a new invocation of `recover`
//! reopens the same store, verifies replay and terminal recovery, and emits a
//! JSON receipt.  No provider target is attached and every effect/power-loss
//! claim remains false.

use std::env;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_JOURNAL_MODE;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionLeaseReceipt;
use codex_hepta_memory::ProductionOutcomeReceipt;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_memory::ProductionRecoveryReceipt;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde::Serialize;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

const HARNESS_SCHEMA_VERSION: u32 = 1;
const HARNESS_NAMESPACE: &str = "h4_agentd_production_writer_persistent";
const AGENT_ID_TEXT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2cde";
const LEASE_ID: &str = "production:h4:persistent";
const OCCURRENCE_KEY: &str = "occurrence:h4:persistent";
const TOPIC: &str = "h4.persistent.power_cut.v1";
const PAYLOAD: &str = "{\"qualification\":true,\"external_effect\":false}";
const DEFAULT_WAIT_SECONDS: u64 = 0;
const DEFAULT_LEASE_SECONDS: u64 = 86_400;

type HarnessResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Debug)]
struct QualificationVerifier;

impl ProductionAuthorityVerifier for QualificationVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        if &authority.agent_id != expected_agent {
            return Err("qualification verifier agent mismatch".to_string());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct CacheDeviceEvidence {
    name: String,
    model: Option<String>,
    write_cache: Option<String>,
    fua: Option<String>,
    rotational: Option<String>,
    state: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct DbEvidence {
    database_path: String,
    journal_mode: String,
    synchronous: i64,
    integrity_check: String,
    lease_rows: i64,
    event_rows: i64,
    outbox_rows: i64,
    cache_devices: Vec<CacheDeviceEvidence>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct PrepareMarker {
    schema_version: u32,
    namespace: String,
    opt_in_only: bool,
    phase: String,
    host: String,
    process_id: u32,
    prepared_at_unix_seconds: u64,
    boot_id: String,
    fleet_root: String,
    database_path: String,
    agent_id: AgentId,
    lease_id: String,
    generation: u64,
    authority_epoch: u64,
    owner_epoch: u64,
    lease_expires_at_unix_seconds: u64,
    grant_digest: Sha256Digest,
    fencing_token_digest: Sha256Digest,
    queued: ProductionQueuedReceipt,
    database: DbEvidence,
    authority_source: String,
    external_effect: bool,
    production_caller: bool,
    kg_write_authority: bool,
    physical_power_loss_claim: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct RecoverReceipt {
    schema_version: u32,
    namespace: String,
    opt_in_only: bool,
    phase: String,
    host: String,
    recovered_at_unix_seconds: u64,
    previous_boot_id: String,
    current_boot_id: String,
    boot_id_changed: bool,
    operator_confirmed_cut: bool,
    physical_cut_observed: bool,
    marker: PrepareMarker,
    replayed: bool,
    status_before_terminalization: LocalOutcomeState,
    replay_recovery: ProductionRecoveryReceipt,
    indeterminate: ProductionOutcomeReceipt,
    rollback: ProductionOutcomeReceipt,
    release: ProductionLeaseReceipt,
    database_before_terminalization: DbEvidence,
    database_after_terminalization: DbEvidence,
    authority_source: String,
    external_effect: bool,
    production_caller: bool,
    kg_write_authority: bool,
    physical_power_loss_claim: bool,
}

fn boxed_error(message: impl Into<String>) -> Box<dyn std::error::Error + Send + Sync> {
    Box::new(std::io::Error::new(ErrorKind::InvalidInput, message.into()))
}

fn now_unix_seconds() -> HarnessResult<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}

fn read_trimmed(path: impl AsRef<Path>) -> Option<String> {
    fs::read_to_string(path)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn boot_id() -> String {
    read_trimmed("/proc/sys/kernel/random/boot_id").unwrap_or_else(|| "unavailable".to_string())
}

fn host_name() -> String {
    read_trimmed("/etc/hostname")
        .or_else(|| env::var("HOSTNAME").ok())
        .unwrap_or_else(|| "unknown".to_string())
}

fn cache_devices() -> Vec<CacheDeviceEvidence> {
    let mut devices = fs::read_dir("/sys/block")
        .ok()
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .map(|entry| {
            let name = entry.file_name().to_string_lossy().to_string();
            let root = entry.path();
            CacheDeviceEvidence {
                name,
                model: read_trimmed(root.join("device/model")),
                write_cache: read_trimmed(root.join("queue/write_cache")),
                fua: read_trimmed(root.join("queue/fua")),
                rotational: read_trimmed(root.join("queue/rotational")),
                state: read_trimmed(root.join("device/state")),
            }
        })
        .collect::<Vec<_>>();
    devices.sort_by(|left, right| left.name.cmp(&right.name));
    devices
}

fn root_from_env() -> HarnessResult<PathBuf> {
    let raw = env::var_os("H4_PERSISTENT_ROOT").ok_or_else(|| {
        boxed_error("H4_PERSISTENT_ROOT is required and must be an absolute test root")
    })?;
    let raw = PathBuf::from(raw);
    if !raw.is_absolute() || raw == Path::new("/") {
        return Err(boxed_error(
            "H4_PERSISTENT_ROOT must be absolute and non-root",
        ));
    }
    fs::create_dir_all(&raw)?;
    Ok(raw.canonicalize()?)
}

fn fleet_root(root: &Path) -> HarnessResult<HeptaFleetRoot> {
    let path = root.join("fleet-v1");
    fs::create_dir_all(&path)?;
    Ok(HeptaFleetRoot::parse(path.canonicalize()?)?)
}

fn marker_path(root: &Path) -> PathBuf {
    root.join("h4-persistent-prepare.json")
}

fn continue_path(root: &Path) -> PathBuf {
    root.join("h4-persistent-continue")
}

fn receipt_path(root: &Path) -> PathBuf {
    root.join("h4-persistent-recover.json")
}

fn validate_prepare_root(root: &Path) -> HarnessResult<()> {
    let marker = marker_path(root);
    if marker.exists() {
        return Err(boxed_error(format!(
            "prepare marker already exists: {}; use a fresh H4_PERSISTENT_ROOT",
            marker.display()
        )));
    }
    // A missing marker is not enough to establish a fresh qualification
    // database: an operator could have removed it while leaving the old
    // `fleet-v1` store behind.  Mixing old rows with a new run would make
    // replay/count evidence ambiguous, so require an entirely empty root.
    let mut entries = fs::read_dir(root)?;
    if let Some(entry) = entries.next().transpose()? {
        return Err(boxed_error(format!(
            "H4_PERSISTENT_ROOT must be empty for prepare; found {}",
            entry.path().display()
        )));
    }
    Ok(())
}

fn write_json_atomic<T: Serialize>(path: &Path, value: &T) -> HarnessResult<()> {
    let parent = path
        .parent()
        .ok_or_else(|| boxed_error("JSON path has no parent"))?;
    fs::create_dir_all(parent)?;
    let file_name = path
        .file_name()
        .ok_or_else(|| boxed_error("JSON path has no file name"))?
        .to_string_lossy();
    let temporary = parent.join(format!(".{file_name}.tmp-{}", std::process::id()));
    let bytes = serde_json::to_vec_pretty(value)?;
    let result = (|| -> HarnessResult<()> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, path)?;
        // The file fsync makes the JSON bytes durable, while the directory
        // fsync makes the rename durable.  A qualification marker is the
        // witness that permits a later recovery process to proceed; silently
        // ignoring a directory-sync failure would turn an unproven marker
        // into an apparent crash/power-cut result, so fail closed instead.
        let directory = File::open(parent)?;
        directory.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> HarnessResult<T> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

fn parse_u64_env(name: &str, default: u64) -> HarnessResult<u64> {
    match env::var(name) {
        Ok(value) => Ok(value.parse::<u64>().map_err(|error| {
            boxed_error(format!("{name} must be an unsigned integer: {error}"))
        })?),
        Err(_) => Ok(default),
    }
}

fn qualification_token() -> HarnessResult<ProductionAuthorityToken> {
    let value = env::var("H4_QUALIFICATION_TOKEN")
        .unwrap_or_else(|_| "h4-persistent-qualification-token".to_string());
    Ok(ProductionAuthorityToken::from_verified_bytes(
        value.into_bytes(),
    )?)
}

fn authority_for(
    agent_id: AgentId,
    marker: Option<&PrepareMarker>,
) -> HarnessResult<ProductionAuthorityLease> {
    let grant_digest = marker
        .map(|marker| marker.grant_digest.clone())
        .unwrap_or_else(|| {
            Sha256Digest::for_bytes(
                env::var("H4_QUALIFICATION_GRANT_LABEL")
                    .unwrap_or_else(|_| "h4-persistent-qualification-grant".to_string())
                    .as_bytes(),
            )
        });
    let authority_epoch = marker
        .map(|marker| marker.authority_epoch)
        .unwrap_or(parse_u64_env("H4_AUTHORITY_EPOCH", 1)?);
    let owner_epoch = marker
        .map(|marker| marker.owner_epoch)
        .unwrap_or(parse_u64_env("H4_OWNER_EPOCH", 1)?);
    let expiry = marker
        .map(|marker| marker.lease_expires_at_unix_seconds)
        .unwrap_or(
            now_unix_seconds()?
                .saturating_add(parse_u64_env("H4_LEASE_SECONDS", DEFAULT_LEASE_SECONDS)?),
        );
    let authority = ProductionAuthorityLease::from_verified_parts(
        agent_id,
        grant_digest,
        authority_epoch,
        owner_epoch,
        expiry,
        qualification_token()?,
    )?;
    if let Some(marker) = marker {
        let fencing_digest = authority.fencing_token_digest()?;
        if fencing_digest != marker.fencing_token_digest {
            return Err(boxed_error(
                "H4_QUALIFICATION_TOKEN changed since prepare; refusing stale recovery",
            ));
        }
    }
    Ok(authority)
}

async fn open_store(root: &Path, agent_id: &AgentId) -> HarnessResult<CognitiveStore> {
    let fleet = fleet_root(root)?;
    Ok(CognitiveStore::open(&fleet.layout().agent(agent_id)).await?)
}

async fn inspect_database(path: &Path, lease_id: &str) -> HarnessResult<DbEvidence> {
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(false)
        .read_only(true)
        .busy_timeout(Duration::from_secs(5));
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await?;
    let evidence = inspect_database_with_pool(&pool, path, lease_id).await;
    pool.close().await;
    evidence
}

async fn inspect_database_with_pool(
    pool: &SqlitePool,
    path: &Path,
    lease_id: &str,
) -> HarnessResult<DbEvidence> {
    let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(pool)
        .await?;
    let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
        .fetch_one(pool)
        .await?;
    let integrity_check: String = sqlx::query_scalar("PRAGMA integrity_check")
        .fetch_one(pool)
        .await?;
    let lease_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_leases WHERE lease_id = ?")
            .bind(lease_id)
            .fetch_one(pool)
            .await?;
    let event_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events WHERE lease_id = ?")
            .bind(lease_id)
            .fetch_one(pool)
            .await?;
    let outbox_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_outbox WHERE lease_id = ?")
            .bind(lease_id)
            .fetch_one(pool)
            .await?;
    Ok(DbEvidence {
        database_path: path.display().to_string(),
        journal_mode,
        synchronous,
        integrity_check,
        lease_rows,
        event_rows,
        outbox_rows,
        cache_devices: cache_devices(),
    })
}

fn validate_database_evidence(database: &DbEvidence) -> HarnessResult<()> {
    if !database
        .journal_mode
        .eq_ignore_ascii_case(PRODUCTION_DURABLE_WRITER_JOURNAL_MODE)
        || database.synchronous != PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL
    {
        return Err(boxed_error(format!(
            "H4 durability precondition changed: journal_mode={} synchronous={}",
            database.journal_mode, database.synchronous
        )));
    }
    if !database.integrity_check.eq_ignore_ascii_case("ok") {
        return Err(boxed_error(format!(
            "SQLite integrity_check failed: {}",
            database.integrity_check
        )));
    }
    Ok(())
}

async fn wait_for_continue(root: &Path) -> HarnessResult<()> {
    let wait_seconds = parse_u64_env("H4_WAIT_SECONDS", DEFAULT_WAIT_SECONDS)?;
    let gate = continue_path(root);
    let deadline = (wait_seconds != 0)
        .then(|| tokio::time::Instant::now() + Duration::from_secs(wait_seconds));
    loop {
        if gate.exists() {
            return Ok(());
        }
        if deadline.is_some_and(|deadline| tokio::time::Instant::now() >= deadline) {
            return Err(boxed_error(format!(
                "timed out waiting for operator gate {}",
                gate.display()
            )));
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
}

async fn prepare(root: &Path) -> HarnessResult<()> {
    validate_prepare_root(root)?;
    let marker_path = marker_path(root);
    let agent_id = AgentId::parse(AGENT_ID_TEXT).map_err(|error| boxed_error(error.to_string()))?;
    let authority = authority_for(agent_id.clone(), None)?;
    let generation = parse_u64_env("H4_GENERATION", 1)?;
    let store = open_store(root, &agent_id).await?;
    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority.clone(),
        &QualificationVerifier,
        LEASE_ID,
        generation,
    )
    .await?;
    let writer = host.writer();
    let queued = writer.admit(OCCURRENCE_KEY, TOPIC, PAYLOAD).await?;
    let database = inspect_database(writer.store().path(), LEASE_ID).await?;
    validate_database_evidence(&database)?;
    let marker = PrepareMarker {
        schema_version: HARNESS_SCHEMA_VERSION,
        namespace: HARNESS_NAMESPACE.to_string(),
        opt_in_only: true,
        phase: "prepare".to_string(),
        host: host_name(),
        process_id: std::process::id(),
        prepared_at_unix_seconds: now_unix_seconds()?,
        boot_id: boot_id(),
        fleet_root: root.join("fleet-v1").display().to_string(),
        database_path: writer.store().path().display().to_string(),
        agent_id,
        lease_id: LEASE_ID.to_string(),
        generation,
        authority_epoch: authority.authority_epoch,
        owner_epoch: authority.owner_epoch,
        lease_expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
        grant_digest: authority.grant_digest.clone(),
        fencing_token_digest: authority.fencing_token_digest()?,
        queued,
        database,
        authority_source: "local qualification verifier; not external authority".to_string(),
        external_effect: false,
        production_caller: false,
        kg_write_authority: false,
        physical_power_loss_claim: false,
    };
    write_json_atomic(&marker_path, &marker)?;
    println!("{}", serde_json::to_string_pretty(&marker)?);
    std::io::stdout().flush()?;
    wait_for_continue(root).await
}

async fn recover(root: &Path) -> HarnessResult<()> {
    let marker: PrepareMarker = read_json(&marker_path(root))?;
    if marker.schema_version != HARNESS_SCHEMA_VERSION
        || marker.namespace != HARNESS_NAMESPACE
        || marker.phase != "prepare"
        || !marker.opt_in_only
        || marker.lease_id != LEASE_ID
    {
        return Err(boxed_error("invalid H4 persistent prepare marker"));
    }
    let expected_agent =
        AgentId::parse(AGENT_ID_TEXT).map_err(|error| boxed_error(error.to_string()))?;
    if marker.agent_id != expected_agent {
        return Err(boxed_error(
            "prepare marker agent id does not match harness identity",
        ));
    }
    let authority = authority_for(expected_agent.clone(), Some(&marker))?;
    let store = open_store(root, &expected_agent).await?;
    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority,
        &QualificationVerifier,
        &marker.lease_id,
        marker.generation,
    )
    .await?;
    let writer = host.writer();
    let database_before_terminalization = inspect_database(writer.store().path(), LEASE_ID).await?;
    validate_database_evidence(&database_before_terminalization)?;
    let replay = writer
        .admit(
            marker.queued.occurrence_key.clone(),
            marker.queued.topic.clone(),
            marker.queued.payload_json.clone(),
        )
        .await?;
    if !replay.replayed
        || replay.event_id != marker.queued.event_id
        || replay.outbox_id != marker.queued.outbox_id
        || replay.payload_sha256 != marker.queued.payload_sha256
    {
        return Err(boxed_error(
            "H4 recovery did not replay the exact prepared event/outbox receipt",
        ));
    }
    let status_before_terminalization = writer.status(&marker.queued.occurrence_key).await?;
    if status_before_terminalization != LocalOutcomeState::Queued {
        return Err(boxed_error(format!(
            "H4 recovery expected queued state, observed {status_before_terminalization:?}"
        )));
    }
    let replay_recovery = writer.recover(&marker.queued.occurrence_key).await?;
    if replay_recovery.state != "queued" {
        return Err(boxed_error(format!(
            "H4 replay recovery unexpectedly terminalized as {}",
            replay_recovery.state
        )));
    }
    let indeterminate = writer
        .mark_indeterminate(
            &marker.queued.occurrence_key,
            "persistent_harness_recovery_without_provider_ack",
        )
        .await?;
    let rollback = writer
        .rollback_occurrence(
            &marker.queued.occurrence_key,
            "persistent_harness_recovery_terminalization",
        )
        .await?;
    let release = writer.release().await?;
    let database_path = writer.store().path().to_path_buf();
    drop(host);
    drop(writer);
    let database_after_terminalization = inspect_database(&database_path, LEASE_ID).await?;
    validate_database_evidence(&database_after_terminalization)?;
    let current_boot_id = boot_id();
    let boot_id_changed = marker.boot_id != current_boot_id
        && marker.boot_id != "unavailable"
        && current_boot_id != "unavailable";
    let operator_confirmed_cut = env::var("H4_OPERATOR_CONFIRMED_CUT")
        .map(|value| value == "1")
        .unwrap_or(false);
    let receipt = RecoverReceipt {
        schema_version: HARNESS_SCHEMA_VERSION,
        namespace: HARNESS_NAMESPACE.to_string(),
        opt_in_only: true,
        phase: "recover".to_string(),
        host: host_name(),
        recovered_at_unix_seconds: now_unix_seconds()?,
        previous_boot_id: marker.boot_id.clone(),
        current_boot_id,
        boot_id_changed,
        operator_confirmed_cut,
        physical_cut_observed: operator_confirmed_cut && boot_id_changed,
        marker,
        replayed: replay.replayed,
        status_before_terminalization,
        replay_recovery,
        indeterminate,
        rollback,
        release,
        database_before_terminalization,
        database_after_terminalization,
        authority_source: "local qualification verifier; not external authority".to_string(),
        external_effect: false,
        production_caller: false,
        kg_write_authority: false,
        physical_power_loss_claim: false,
    };
    write_json_atomic(&receipt_path(root), &receipt)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

#[tokio::main]
async fn main() -> HarnessResult<()> {
    let mut args = env::args().skip(1);
    let phase = args
        .next()
        .ok_or_else(|| boxed_error("usage: h4_persistent_writer <prepare|recover>"))?;
    if args.next().is_some() {
        return Err(boxed_error("usage: h4_persistent_writer <prepare|recover>"));
    }
    let root = root_from_env()?;
    match phase.as_str() {
        "prepare" => prepare(&root).await,
        "recover" => recover(&root).await,
        _ => Err(boxed_error("phase must be prepare or recover")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_memory::ProductionDispatchFuture;
    use codex_hepta_memory::ProductionDispatchRequest;
    use codex_hepta_memory::ProductionOutboxTarget;
    use codex_hepta_memory::ProductionTargetOutcome;
    use std::sync::Arc;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    use tempfile::TempDir;
    use tokio::sync::Notify;
    use tokio::time::Duration;
    use tokio::time::timeout;

    /// Target fixture that is entered only after `claim_dispatch` has
    /// committed.  Aborting the task while this future is pending models a
    /// process crash in the claim→target window without invoking a provider
    /// effect; a fresh writer must observe the durable indeterminate claim.
    struct ClaimThenBlockTarget {
        calls: Arc<AtomicUsize>,
        entered: Arc<Notify>,
    }

    impl ProductionOutboxTarget for ClaimThenBlockTarget {
        fn dispatch<'a>(
            &'a self,
            _request: ProductionDispatchRequest,
        ) -> ProductionDispatchFuture<'a> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            let entered = Arc::clone(&self.entered);
            Box::pin(async move {
                entered.notify_one();
                std::future::pending::<ProductionTargetOutcome>().await
            })
        }
    }

    #[tokio::test]
    async fn claim_before_target_abort_reopens_indeterminate_without_redispatch() {
        let temp = TempDir::new().expect("H4 claim/reopen temp dir");
        let root = temp.path().join("claim-reopen");
        let agent_id = AgentId::parse(AGENT_ID_TEXT).expect("H4 claim/reopen agent");
        let authority = authority_for(agent_id.clone(), None).expect("H4 claim/reopen authority");
        let store = open_store(&root, &agent_id)
            .await
            .expect("H4 claim/reopen store");
        let host = AgentdProductionWriterHost::open_with_store(
            store.clone(),
            authority.clone(),
            &QualificationVerifier,
            "production:h4:claim-reopen",
            1,
        )
        .await
        .expect("H4 claim/reopen writer");
        let writer = host.writer();
        let queued = writer
            .admit("occurrence:h4:claim-reopen", "h4.claim", "payload")
            .await
            .expect("H4 claim/reopen admission");
        let retry_receipt = queued.clone();
        let calls = Arc::new(AtomicUsize::new(0));
        let entered = Arc::new(Notify::new());
        let target = Arc::new(ClaimThenBlockTarget {
            calls: Arc::clone(&calls),
            entered: Arc::clone(&entered),
        });
        let dispatch_host = host.attach_target(target);
        let dispatch_task = tokio::spawn(async move { dispatch_host.dispatch(queued).await });

        timeout(Duration::from_secs(5), entered.notified())
            .await
            .expect("target must be entered after durable claim");
        dispatch_task.abort();
        let join_error = dispatch_task
            .await
            .expect_err("aborted claim/target task must not return normally");
        assert!(join_error.is_cancelled());
        assert_eq!(calls.load(Ordering::SeqCst), 1);

        // Close every handle from the crashed generation before reopening a
        // fresh pool, matching the process boundary of the real harness.
        drop(writer);
        drop(store);
        let reopened_store = open_store(&root, &agent_id)
            .await
            .expect("H4 claim/reopen fresh store");
        let reopened_host = AgentdProductionWriterHost::open_with_store(
            reopened_store,
            authority,
            &QualificationVerifier,
            "production:h4:claim-reopen",
            1,
        )
        .await
        .expect("H4 claim/reopen fresh writer");
        let reopened_writer = reopened_host.writer();
        assert_eq!(
            reopened_writer
                .status("occurrence:h4:claim-reopen")
                .await
                .expect("H4 claim/reopen status"),
            LocalOutcomeState::Indeterminate
        );

        let retry_calls = Arc::new(AtomicUsize::new(0));
        let retry_target = Arc::new(ClaimThenBlockTarget {
            calls: Arc::clone(&retry_calls),
            entered: Arc::new(Notify::new()),
        });
        let retry_result = reopened_host
            .attach_target(retry_target)
            .dispatch(retry_receipt)
            .await;
        assert!(matches!(
            retry_result,
            Err(codex_hepta_agentd::AgentdError::ProductionWriter(
                codex_hepta_memory::ProductionWriterError::StaleReceipt
            ))
        ));
        assert_eq!(retry_calls.load(Ordering::SeqCst), 0);

        let recovery = reopened_writer
            .recover("occurrence:h4:claim-reopen")
            .await
            .expect("H4 claim/reopen explicit recovery");
        assert_eq!(recovery.state, "released_indeterminate");
        assert!(!recovery.external_effect);
        assert!(!recovery.physical_power_loss_claim);
        // `recover` appends the released lease witness atomically; a second
        // release on this handle must not be attempted after terminalization.
    }

    #[test]
    fn prepare_rejects_stale_marker_and_existing_database_root() {
        let temp = TempDir::new().expect("H4 prepare-root temp dir");
        let root = temp.path().join("prepare-root");
        fs::create_dir_all(&root).expect("H4 prepare-root directory");
        validate_prepare_root(&root).expect("empty H4 prepare root");

        fs::create_dir(root.join("fleet-v1")).expect("stale H4 fleet directory");
        let stale_database = validate_prepare_root(&root).expect_err("stale H4 root rejected");
        assert!(stale_database.to_string().contains("must be empty"));
        fs::remove_dir(root.join("fleet-v1")).expect("remove stale H4 fleet directory");

        fs::write(marker_path(&root), b"stale marker").expect("stale H4 marker");
        let stale_marker = validate_prepare_root(&root).expect_err("stale H4 marker rejected");
        assert!(
            stale_marker
                .to_string()
                .contains("prepare marker already exists")
        );
    }
}
