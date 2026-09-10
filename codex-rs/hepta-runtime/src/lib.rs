//! Minimal live-runtime composition for the vNext integration trunk.
//!
//! The compatibility adapter opens the existing Hepta schema-v5 stores in
//! read-only mode. It deliberately does not copy Memory S1/S2 logic: a future
//! integrator can provide a [`RuntimeStateAdapter`] backed by the process-owned
//! `StateDbHandle` without changing the gateway contract.

#![forbid(unsafe_code)]

mod organs;

use std::fmt;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::Read;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_paths::HeptaStateLayout;
use codex_hepta_paths::HeptaStateRoot;
use hmac::Hmac;
use hmac::Mac;
use serde::Deserialize;
use serde::Serialize;
use serde_json::value::RawValue;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Connection;
use sqlx::SqliteConnection;
use sqlx::sqlite::SqliteConnectOptions;
use zeroize::Zeroizing;

pub const EXISTING_SCHEMA_VERSION: i64 = 5;
pub const RUNTIME_SNAPSHOT_VERSION: u64 = 1;
const INTEGRITY_ALGORITHM: &str = "hmac-sha256-v1";
const KEY_ID_DOMAIN: &[u8] = b"hepta.memory.durable-integrity.key-id.v1";
const ROW_MAC_DOMAIN: &[u8] = b"hepta.memory.durable-integrity.row-mac.v1";
const INTEGRITY_TAG_PREFIX: &str = "hmac-sha256:";
const MAX_DATABASE_ROWS: usize = 100_000;

type HmacSha256 = Hmac<Sha256>;
type IntegrityKey = Zeroizing<[u8; 32]>;

/// Read-only state information exposed to the loopback gateway.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RuntimeStateStatus {
    pub adapter: &'static str,
    pub schema_version: i64,
    pub outcome_generation: i64,
    pub preference_generation: i64,
    pub runtime_snapshot_version: u64,
    pub runtime_snapshot_generation: u64,
    pub integrity_binding_present: bool,
    pub integrity_verification: &'static str,
    pub open_mode: &'static str,
}

/// Seam for the parallel memory port. Implementations must already be open and
/// must not create or migrate state as a side effect of status inspection.
pub trait RuntimeStateAdapter: fmt::Debug + Send + Sync {
    fn status(&self) -> RuntimeStateStatus;
}

/// Minimal runtime held by the native loopback gateway.
#[derive(Debug, Clone)]
pub struct HeptaRuntime {
    state_root: HeptaStateRoot,
    state: Arc<dyn RuntimeStateAdapter>,
    organs: Arc<organs::RuntimeOrgans>,
}

impl HeptaRuntime {
    pub async fn open_existing(state_root: HeptaStateRoot) -> Result<Self> {
        let layout = state_root.layout();
        let adapter = SchemaV5OpenExistingAdapter::open(&layout).await?;
        let runtime = Self::from_adapter(state_root, Arc::new(adapter));
        runtime.organs.ensure_ready()?;
        Ok(runtime)
    }

    pub fn from_adapter(state_root: HeptaStateRoot, state: Arc<dyn RuntimeStateAdapter>) -> Self {
        let organs = Arc::new(organs::RuntimeOrgans::new(
            state_root.clone(),
            Arc::clone(&state),
        ));
        Self {
            state_root,
            state,
            organs,
        }
    }

    /// Query the initialized, generation-fenced, read-only organ graph.
    /// The wire payload is unchanged; no mutable or external organ is admitted.
    pub fn status_json(&self) -> Result<Vec<u8>> {
        self.organs.status_json()
    }

    pub fn status(&self) -> RuntimeStatus {
        RuntimeStatus {
            schema: "hepta_vnext_live_runtime_status_v1",
            product: "hepta",
            status: "ready",
            state_root: self.state_root.to_string(),
            state: self.state.status(),
            authority: RuntimeAuthorityStatus::default(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RuntimeStatus {
    pub schema: &'static str,
    pub product: &'static str,
    pub status: &'static str,
    pub state_root: String,
    pub state: RuntimeStateStatus,
    pub authority: RuntimeAuthorityStatus,
}

/// Explicitly closed effects for the internal-test live shell.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct RuntimeAuthorityStatus {
    pub telegram: bool,
    pub outbound: bool,
    pub model_invocation: bool,
    pub operator_mutation: bool,
    pub enforce: bool,
    pub promotion: bool,
    pub retirement: bool,
    pub automatic_transition: bool,
}

struct SchemaV5OpenExistingAdapter {
    status: RuntimeStateStatus,
}

impl fmt::Debug for SchemaV5OpenExistingAdapter {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SchemaV5OpenExistingAdapter")
            .field("status", &self.status)
            .finish_non_exhaustive()
    }
}

impl RuntimeStateAdapter for SchemaV5OpenExistingAdapter {
    fn status(&self) -> RuntimeStateStatus {
        self.status.clone()
    }
}

impl SchemaV5OpenExistingAdapter {
    async fn open(layout: &HeptaStateLayout) -> Result<Self> {
        validate_private_directory(layout.state_root().as_path(), "state root")?;
        validate_private_directory(layout.runtime_root(), "runtime root")?;
        let runtime_integrity_key =
            read_integrity_key(&layout.runtime_integrity_key(), "runtime integrity key")?;
        let preference_integrity_key = read_integrity_key(
            &layout.preference_integrity_key(),
            "preference integrity key",
        )?;
        // The read-only shell cannot use ingress authority, but the compatibility
        // layout still requires the existing key namespace to be complete.
        validate_private_key_file(&layout.preference_ingress_key(), "preference ingress key")?;

        let outcome_database = layout.outcomes_database();
        let preference_database = layout.preferences_database();
        let outcome_metadata = open_schema_v5_database(
            &outcome_database,
            "outcome database",
            &runtime_integrity_key,
        )
        .await?;
        let preference_metadata = open_schema_v5_database(
            &preference_database,
            "preference database",
            &preference_integrity_key,
        )
        .await?;
        let runtime_state = read_runtime_state(&layout.runtime_state(), &runtime_integrity_key)?;

        Ok(Self {
            status: RuntimeStateStatus {
                adapter: "schema-v5-open-existing",
                schema_version: EXISTING_SCHEMA_VERSION,
                outcome_generation: outcome_metadata.generation,
                preference_generation: preference_metadata.generation,
                runtime_snapshot_version: runtime_state.payload.version,
                runtime_snapshot_generation: runtime_state.payload.generation,
                integrity_binding_present: outcome_metadata.integrity_binding_present
                    && preference_metadata.integrity_binding_present
                    && runtime_state.integrity_verified,
                integrity_verification: "hmac-sha256-v1-key-id-and-row-macs-verified",
                open_mode: "immutable-query-only-open-existing",
            },
        })
    }
}

#[derive(Debug)]
struct DatabaseMetadata {
    generation: i64,
    integrity_binding_present: bool,
}

async fn open_schema_v5_database(
    path: &Path,
    description: &'static str,
    integrity_key: &IntegrityKey,
) -> Result<DatabaseMetadata> {
    let before = DatabaseFileSet::capture(path, description)?;
    before.require_empty_wal(description)?;
    let mut connection = open_immutable_query_only_connection(path)
        .await
        .with_context(|| format!("open immutable {description} at {}", path.display()))?;

    let schema_version =
        sqlx::query_scalar::<_, i64>("SELECT version FROM hepta_v2_schema WHERE singleton = 1")
            .fetch_optional(&mut connection)
            .await
            .with_context(|| format!("read schema version from {description}"))?
            .context("schema version row is missing")?;
    if schema_version != EXISTING_SCHEMA_VERSION {
        anyhow::bail!(
            "{description} schema version is {schema_version}, expected {EXISTING_SCHEMA_VERSION}"
        );
    }

    let generation = sqlx::query_scalar::<_, i64>(
        "SELECT generation FROM hepta_v2_write_lock WHERE singleton = 1",
    )
    .fetch_optional(&mut connection)
    .await
    .with_context(|| format!("read write-lock generation from {description}"))?
    .context("write-lock generation row is missing")?;
    if generation < 0 {
        anyhow::bail!("{description} write-lock generation must not be negative");
    }

    let integrity = sqlx::query_as::<_, (String, String)>(
        "SELECT algorithm, key_id FROM hepta_v2_integrity WHERE singleton = 1",
    )
    .fetch_optional(&mut connection)
    .await
    .with_context(|| format!("read integrity binding from {description}"))?
    .context("integrity binding row is missing")?;
    let expected_key_id = key_id(integrity_key);
    if integrity.0 != INTEGRITY_ALGORITHM || integrity.1 != expected_key_id {
        anyhow::bail!("{description} integrity algorithm or key ID does not match its pinned key");
    }
    verify_all_database_row_macs(&mut connection, integrity_key, description).await?;
    let quick_check = sqlx::query_scalar::<_, String>("PRAGMA quick_check")
        .fetch_one(&mut connection)
        .await
        .with_context(|| format!("run immutable quick-check for {description}"))?;
    if quick_check != "ok" {
        anyhow::bail!("{description} SQLite quick-check failed: {quick_check}");
    }
    connection
        .close()
        .await
        .with_context(|| format!("close immutable {description}"))?;
    let after = DatabaseFileSet::capture(path, description)?;
    if before != after {
        anyhow::bail!("{description} files changed during immutable inspection");
    }

    Ok(DatabaseMetadata {
        generation,
        integrity_binding_present: true,
    })
}

#[expect(
    clippy::disallowed_methods,
    reason = "live shell opens only an already-copied immutable snapshot and never creates or mutates SQLite state"
)]
async fn open_immutable_query_only_connection(path: &Path) -> Result<SqliteConnection> {
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(false)
        .read_only(true)
        .immutable(true);
    let mut connection = SqliteConnection::connect_with(&options).await?;
    sqlx::query("PRAGMA query_only = ON")
        .execute(&mut connection)
        .await?;
    let query_only = sqlx::query_scalar::<_, i64>("PRAGMA query_only")
        .fetch_one(&mut connection)
        .await?;
    if query_only != 1 {
        anyhow::bail!("SQLite immutable connection did not enter query-only mode");
    }
    Ok(connection)
}

async fn verify_all_database_row_macs(
    connection: &mut SqliteConnection,
    integrity_key: &IntegrityKey,
    description: &str,
) -> Result<()> {
    let queries = [
        (
            "SELECT payload_json, storage_hash FROM hepta_v2_outcome_records LIMIT 100001",
            "outcome record",
        ),
        (
            "SELECT payload_json, storage_hash FROM hepta_v2_outcome_intents LIMIT 100001",
            "outcome intent",
        ),
        (
            "SELECT payload_json, storage_hash FROM hepta_v2_execution_intents LIMIT 100001",
            "execution intent",
        ),
        (
            "SELECT payload_json, storage_hash FROM hepta_v2_execution_effect_acks LIMIT 100001",
            "execution effect ACK",
        ),
        (
            "SELECT payload_json, storage_hash FROM hepta_v2_preference_genesis LIMIT 100001",
            "preference genesis",
        ),
        (
            "SELECT payload_json, storage_hash FROM hepta_v2_preference_heads LIMIT 100001",
            "preference head",
        ),
        (
            "SELECT payload_json, storage_hash FROM hepta_v2_preference_transitions LIMIT 100001",
            "preference transition",
        ),
    ];
    let mut verified_rows = 0_usize;
    for (query, row_kind) in queries {
        let rows = sqlx::query_as::<_, (String, String)>(query)
            .fetch_all(&mut *connection)
            .await
            .with_context(|| format!("read {row_kind} rows from {description}"))?;
        verified_rows = verified_rows
            .checked_add(rows.len())
            .context("authenticated database row count overflowed")?;
        if verified_rows > MAX_DATABASE_ROWS {
            anyhow::bail!(
                "{description} exceeds the bounded {MAX_DATABASE_ROWS}-row integrity scan"
            );
        }
        for (payload_json, storage_hash) in rows {
            verify_row_mac(
                integrity_key,
                payload_json.as_bytes(),
                &storage_hash,
                row_kind,
            )?;
        }
    }
    Ok(())
}

#[derive(Debug)]
struct VerifiedRuntimeState {
    payload: RuntimeStatePayload,
    integrity_verified: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeStateEnvelope {
    payload: Box<RawValue>,
    integrity_tag: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeStatePayload {
    version: u64,
    generation: u64,
    snapshot: RuntimeSnapshotShape,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeSnapshotShape {
    sessions: Vec<serde_json::Value>,
    memories: Vec<serde_json::Value>,
    transcripts: Vec<serde_json::Value>,
}

fn read_runtime_state(path: &Path, integrity_key: &IntegrityKey) -> Result<VerifiedRuntimeState> {
    let expected_identity = validate_private_regular_file(path, "runtime state")?;
    let mut file = open_no_follow(path).context("open existing runtime state")?;
    let opened_identity = FileIdentity::from_metadata(&file.metadata()?);
    if opened_identity != expected_identity {
        anyhow::bail!("runtime state changed while opening");
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(1024 * 1024)
        .read_to_end(&mut bytes)
        .context("read existing runtime state")?;
    if bytes.is_empty() || bytes.len() >= 1024 * 1024 {
        anyhow::bail!("runtime state is empty or exceeds the one-megabyte limit");
    }
    expected_identity.revalidate(path)?;
    let envelope: RuntimeStateEnvelope =
        serde_json::from_slice(&bytes).context("decode existing runtime state")?;
    verify_row_mac(
        integrity_key,
        envelope.payload.get().as_bytes(),
        &envelope.integrity_tag,
        "runtime state envelope",
    )?;
    let payload: RuntimeStatePayload = serde_json::from_str(envelope.payload.get())
        .context("decode authenticated runtime state payload")?;
    if payload.version != RUNTIME_SNAPSHOT_VERSION {
        anyhow::bail!(
            "runtime snapshot version is {}, expected {RUNTIME_SNAPSHOT_VERSION}",
            payload.version
        );
    }
    // Decode the exact old payload shape before reporting ready. The values
    // remain unused because this shell exposes no Memory callers.
    let _shape_counts = (
        payload.snapshot.sessions.len(),
        payload.snapshot.memories.len(),
        payload.snapshot.transcripts.len(),
    );
    Ok(VerifiedRuntimeState {
        payload,
        integrity_verified: true,
    })
}

fn read_integrity_key(path: &Path, description: &str) -> Result<IntegrityKey> {
    let expected_identity = validate_private_key_file(path, description)?;
    let mut file = open_no_follow(path).with_context(|| format!("open {description}"))?;
    if FileIdentity::from_metadata(&file.metadata()?) != expected_identity {
        anyhow::bail!("{description} changed while opening");
    }
    let mut encoded = Vec::with_capacity(66);
    file.by_ref()
        .take(66)
        .read_to_end(&mut encoded)
        .with_context(|| format!("read {description}"))?;
    expected_identity.revalidate(path)?;
    let encoded = match encoded.as_slice() {
        value if value.len() == 64 => value,
        value if value.len() == 65 && value[64] == b'\n' => &value[..64],
        _ => anyhow::bail!("{description} must contain 64 lowercase hex bytes"),
    };
    let mut key = [0_u8; 32];
    for (index, pair) in encoded.as_chunks::<2>().0.iter().enumerate() {
        key[index] = (decode_hex_nibble(pair[0], description)? << 4)
            | decode_hex_nibble(pair[1], description)?;
    }
    Ok(Zeroizing::new(key))
}

fn validate_private_key_file(path: &Path, description: &str) -> Result<FileIdentity> {
    let identity = validate_private_regular_file(path, description)?;
    let metadata = std::fs::symlink_metadata(path)?;
    #[cfg(unix)]
    if metadata.mode() & 0o7777 != 0o600 {
        anyhow::bail!("{description} must have mode 0o600");
    }
    if !matches!(metadata.len(), 64 | 65) {
        anyhow::bail!("{description} must contain 64 lowercase hex bytes");
    }
    Ok(identity)
}

fn decode_hex_nibble(value: u8, description: &str) -> Result<u8> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => anyhow::bail!("{description} must be canonical lowercase hex"),
    }
}

fn key_id(key: &IntegrityKey) -> String {
    let mut digest = Sha256::new();
    update_digest_frame(&mut digest, KEY_ID_DOMAIN);
    update_digest_frame(&mut digest, key.as_ref());
    format!("sha256:{}", encode_hex(&digest.finalize()))
}

fn verify_row_mac(
    key: &IntegrityKey,
    payload: &[u8],
    expected: &str,
    row_kind: &str,
) -> Result<()> {
    let encoded = expected
        .strip_prefix(INTEGRITY_TAG_PREFIX)
        .with_context(|| {
            format!("{row_kind} keyed integrity tag has an invalid algorithm prefix")
        })?;
    let expected_bytes = decode_hex_32(encoded)
        .with_context(|| format!("{row_kind} keyed integrity tag is not canonical hex"))?;
    let mut mac =
        HmacSha256::new_from_slice(key.as_ref()).context("initialize durable integrity HMAC")?;
    update_mac_frame(&mut mac, ROW_MAC_DOMAIN);
    update_mac_frame(&mut mac, payload);
    mac.verify_slice(&expected_bytes)
        .with_context(|| format!("{row_kind} keyed integrity verification failed"))
}

#[cfg(all(test, unix))]
fn protect_row(key: &IntegrityKey, payload: &[u8]) -> Result<String> {
    let mut mac =
        HmacSha256::new_from_slice(key.as_ref()).context("initialize durable integrity HMAC")?;
    update_mac_frame(&mut mac, ROW_MAC_DOMAIN);
    update_mac_frame(&mut mac, payload);
    Ok(format!(
        "{INTEGRITY_TAG_PREFIX}{}",
        encode_hex(&mac.finalize().into_bytes())
    ))
}

fn update_mac_frame(mac: &mut HmacSha256, value: &[u8]) {
    mac.update(&(value.len() as u64).to_be_bytes());
    mac.update(value);
}

fn update_digest_frame(digest: &mut Sha256, value: &[u8]) {
    digest.update((value.len() as u64).to_be_bytes());
    digest.update(value);
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(char::from(HEX[usize::from(byte >> 4)]));
        encoded.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    encoded
}

fn decode_hex_32(encoded: &str) -> Option<[u8; 32]> {
    if encoded.len() != 64 {
        return None;
    }
    let mut decoded = [0_u8; 32];
    for (index, pair) in encoded.as_bytes().as_chunks::<2>().0.iter().enumerate() {
        let high = decode_hex_nibble_option(pair[0])?;
        let low = decode_hex_nibble_option(pair[1])?;
        decoded[index] = (high << 4) | low;
    }
    Some(decoded)
}

fn decode_hex_nibble_option(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct StableFileState {
    identity: FileIdentity,
    length: u64,
    sha256: [u8; 32],
}

impl StableFileState {
    fn capture(path: &Path, description: &str) -> Result<Self> {
        let identity = validate_private_regular_file(path, description)?;
        let mut file = open_no_follow(path).with_context(|| format!("open {description}"))?;
        if FileIdentity::from_metadata(&file.metadata()?) != identity {
            anyhow::bail!("{description} changed while opening");
        }
        let mut digest = Sha256::new();
        let mut buffer = [0_u8; 64 * 1024];
        let mut length = 0_u64;
        loop {
            let read = file
                .read(&mut buffer)
                .with_context(|| format!("hash {description}"))?;
            if read == 0 {
                break;
            }
            length = length
                .checked_add(read as u64)
                .context("file length overflow while hashing")?;
            digest.update(&buffer[..read]);
        }
        identity.revalidate(path)?;
        Ok(Self {
            identity,
            length,
            sha256: digest.finalize().into(),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DatabaseFileSet {
    database: StableFileState,
    wal: Option<StableFileState>,
    shm: Option<StableFileState>,
}

impl DatabaseFileSet {
    fn capture(path: &Path, description: &str) -> Result<Self> {
        let wal_path = sqlite_sidecar(path, "wal")?;
        let shm_path = sqlite_sidecar(path, "shm")?;
        Ok(Self {
            database: StableFileState::capture(path, description)?,
            wal: capture_optional_file(&wal_path, "SQLite WAL")?,
            shm: capture_optional_file(&shm_path, "SQLite shared-memory file")?,
        })
    }

    fn require_empty_wal(&self, description: &str) -> Result<()> {
        if self.wal.as_ref().is_some_and(|wal| wal.length != 0) {
            anyhow::bail!(
                "{description} has a nonempty WAL; make a private consistent checkpoint before immutable inspection"
            );
        }
        Ok(())
    }
}

fn sqlite_sidecar(path: &Path, suffix: &str) -> Result<std::path::PathBuf> {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .context("SQLite database filename is not UTF-8")?;
    Ok(path.with_file_name(format!("{name}-{suffix}")))
}

fn capture_optional_file(path: &Path, description: &str) -> Result<Option<StableFileState>> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => StableFileState::capture(path, description).map(Some),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error).with_context(|| format!("inspect {description}")),
    }
}

fn validate_private_directory(path: &Path, description: &str) -> Result<()> {
    let metadata = std::fs::symlink_metadata(path)
        .with_context(|| format!("inspect {description} at {}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        anyhow::bail!("{description} must be an existing non-symlink directory");
    }
    validate_private_permissions(&metadata, description)
}

fn validate_private_regular_file(path: &Path, description: &str) -> Result<FileIdentity> {
    let metadata = std::fs::symlink_metadata(path)
        .with_context(|| format!("inspect {description} at {}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        anyhow::bail!("{description} must be an existing non-symlink regular file");
    }
    validate_private_permissions(&metadata, description)?;
    #[cfg(unix)]
    if metadata.nlink() != 1 {
        anyhow::bail!("{description} must have exactly one hard link");
    }
    Ok(FileIdentity::from_metadata(&metadata))
}

#[cfg(unix)]
fn validate_private_permissions(metadata: &Metadata, description: &str) -> Result<()> {
    if metadata.mode() & 0o077 != 0 {
        anyhow::bail!("{description} must not grant group or world permissions");
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_private_permissions(_metadata: &Metadata, _description: &str) -> Result<()> {
    Ok(())
}

fn open_no_follow(path: &Path) -> Result<File> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW);
    options.open(path).map_err(Into::into)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct FileIdentity {
    #[cfg(unix)]
    device: u64,
    #[cfg(unix)]
    inode: u64,
    #[cfg(not(unix))]
    length: u64,
}

impl FileIdentity {
    fn from_metadata(metadata: &Metadata) -> Self {
        #[cfg(unix)]
        {
            Self {
                device: metadata.dev(),
                inode: metadata.ino(),
            }
        }
        #[cfg(not(unix))]
        {
            Self {
                length: metadata.len(),
            }
        }
    }

    fn revalidate(self, path: &Path) -> Result<()> {
        let current = validate_private_regular_file(path, "opened database")?;
        if self != current {
            anyhow::bail!("database identity changed while opening");
        }
        Ok(())
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    const RUNTIME_KEY_BYTES: [u8; 32] = [0x41; 32];
    const PREFERENCE_KEY_BYTES: [u8; 32] = [0x42; 32];
    const INGRESS_KEY_BYTES: [u8; 32] = [0x43; 32];

    #[expect(
        clippy::disallowed_methods,
        reason = "test fixture creates a private SQLite database before exercising immutable open"
    )]
    async fn create_database(path: &Path, schema_version: i64, key_bytes: [u8; 32]) -> Result<()> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true);
        let mut connection = SqliteConnection::connect_with(&options).await?;
        for statement in [
            "CREATE TABLE hepta_v2_schema (singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)",
            "CREATE TABLE hepta_v2_write_lock (singleton INTEGER PRIMARY KEY, generation INTEGER NOT NULL)",
            "CREATE TABLE hepta_v2_integrity (singleton INTEGER PRIMARY KEY, algorithm TEXT NOT NULL, key_id TEXT NOT NULL)",
            "CREATE TABLE hepta_v2_outcome_records (receipt_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL)",
            "CREATE TABLE hepta_v2_outcome_intents (attempt_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL)",
            "CREATE TABLE hepta_v2_execution_intents (attempt_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL)",
            "CREATE TABLE hepta_v2_execution_effect_acks (attempt_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL, effect_plan_hash TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL)",
            "CREATE TABLE hepta_v2_preference_genesis (preference_id TEXT NOT NULL, subject_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL)",
            "CREATE TABLE hepta_v2_preference_heads (preference_id TEXT NOT NULL, subject_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL)",
            "CREATE TABLE hepta_v2_preference_transitions (sequence INTEGER PRIMARY KEY, transition_id TEXT NOT NULL, evidence_id TEXT NOT NULL, receipt_id TEXT NOT NULL, preference_id TEXT NOT NULL, subject_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL)",
        ] {
            sqlx::query(statement).execute(&mut connection).await?;
        }
        sqlx::query("INSERT INTO hepta_v2_schema VALUES (1, ?)")
            .bind(schema_version)
            .execute(&mut connection)
            .await?;
        sqlx::query("INSERT INTO hepta_v2_write_lock VALUES (1, 0)")
            .execute(&mut connection)
            .await?;
        let key = Zeroizing::new(key_bytes);
        sqlx::query("INSERT INTO hepta_v2_integrity VALUES (1, ?, ?)")
            .bind(INTEGRITY_ALGORITHM)
            .bind(key_id(&key))
            .execute(&mut connection)
            .await?;
        let payload = r#"{"fixture":true}"#;
        sqlx::query("INSERT INTO hepta_v2_outcome_records VALUES ('receipt', 'attempt', ?, ?)")
            .bind(payload)
            .bind(protect_row(&key, payload.as_bytes())?)
            .execute(&mut connection)
            .await?;
        connection.close().await?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        Ok(())
    }

    fn write_key(path: &Path, key: [u8; 32]) -> Result<()> {
        std::fs::write(path, format!("{}\n", encode_hex(&key)))?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        Ok(())
    }

    async fn fixture(schema_version: i64) -> Result<(tempfile::TempDir, HeptaStateRoot)> {
        let directory = tempfile::tempdir()?;
        let root = HeptaStateRoot::parse(directory.path())?;
        let layout = root.layout();
        std::fs::create_dir(layout.runtime_root())?;
        std::fs::create_dir(layout.runtime_root().join("keys"))?;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
        std::fs::set_permissions(
            layout.runtime_root(),
            std::fs::Permissions::from_mode(0o700),
        )?;
        std::fs::set_permissions(
            layout.runtime_root().join("keys"),
            std::fs::Permissions::from_mode(0o700),
        )?;
        write_key(&layout.runtime_integrity_key(), RUNTIME_KEY_BYTES)?;
        write_key(&layout.preference_integrity_key(), PREFERENCE_KEY_BYTES)?;
        write_key(&layout.preference_ingress_key(), INGRESS_KEY_BYTES)?;
        create_database(
            &layout.outcomes_database(),
            schema_version,
            RUNTIME_KEY_BYTES,
        )
        .await?;
        create_database(
            &layout.preferences_database(),
            schema_version,
            PREFERENCE_KEY_BYTES,
        )
        .await?;
        let payload = r#"{"version":1,"generation":0,"snapshot":{"sessions":[],"memories":[],"transcripts":[]}}"#;
        let runtime_key = Zeroizing::new(RUNTIME_KEY_BYTES);
        let envelope = format!(
            "{{\"payload\":{payload},\"integrity_tag\":\"{}\"}}",
            protect_row(&runtime_key, payload.as_bytes())?
        );
        std::fs::write(layout.runtime_state(), envelope)?;
        std::fs::set_permissions(
            layout.runtime_state(),
            std::fs::Permissions::from_mode(0o600),
        )?;
        Ok((directory, root))
    }

    #[tokio::test]
    async fn opens_exact_schema_v5_without_mutation_authority() -> Result<()> {
        let (_directory, root) = fixture(EXISTING_SCHEMA_VERSION).await?;
        let runtime = HeptaRuntime::open_existing(root.clone()).await?;
        let status = runtime.status();
        assert_eq!(status.status, "ready");
        assert_eq!(status.state.schema_version, 5);
        assert_eq!(status.state.open_mode, "immutable-query-only-open-existing");
        assert_eq!(
            status.state.integrity_verification,
            "hmac-sha256-v1-key-id-and-row-macs-verified"
        );
        assert_eq!(status.authority, RuntimeAuthorityStatus::default());
        let report = runtime.status_json()?;
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&report)?,
            serde_json::to_value(&status)?
        );
        drop(runtime);
        let reopened = HeptaRuntime::open_existing(root).await?;
        assert_eq!(reopened.status_json()?, report);
        Ok(())
    }

    #[tokio::test]
    async fn rejects_wrong_schema_without_creating_or_migrating() -> Result<()> {
        let (_directory, root) = fixture(EXISTING_SCHEMA_VERSION - 1).await?;
        let Err(error) = HeptaRuntime::open_existing(root).await else {
            anyhow::bail!("wrong schema was accepted");
        };
        assert!(error.to_string().contains("expected 5"), "{error:#}");
        Ok(())
    }

    #[tokio::test]
    async fn rejects_exposed_state_file() -> Result<()> {
        let (_directory, root) = fixture(EXISTING_SCHEMA_VERSION).await?;
        let runtime_state = root.layout().runtime_state();
        std::fs::set_permissions(&runtime_state, std::fs::Permissions::from_mode(0o644))?;
        let Err(error) = HeptaRuntime::open_existing(root).await else {
            anyhow::bail!("exposed state was accepted");
        };
        assert!(error.to_string().contains("group or world"), "{error:#}");
        Ok(())
    }

    #[tokio::test]
    async fn rejects_runtime_payload_with_a_valid_shape_but_wrong_mac() -> Result<()> {
        let (_directory, root) = fixture(EXISTING_SCHEMA_VERSION).await?;
        let runtime_state = root.layout().runtime_state();
        let bytes = std::fs::read_to_string(&runtime_state)?;
        std::fs::write(
            &runtime_state,
            bytes.replace("\"generation\":0", "\"generation\":1"),
        )?;
        let Err(error) = HeptaRuntime::open_existing(root).await else {
            anyhow::bail!("runtime state with a wrong HMAC was accepted");
        };
        assert!(
            error.to_string().contains("integrity verification failed"),
            "{error:#}"
        );
        Ok(())
    }

    #[tokio::test]
    #[expect(
        clippy::disallowed_methods,
        reason = "test corrupts a private SQLite fixture before immutable verification"
    )]
    async fn rejects_database_row_with_a_wrong_mac() -> Result<()> {
        let (_directory, root) = fixture(EXISTING_SCHEMA_VERSION).await?;
        let path = root.layout().outcomes_database();
        let options = SqliteConnectOptions::new()
            .filename(&path)
            .create_if_missing(false);
        let mut connection = SqliteConnection::connect_with(&options).await?;
        sqlx::query("UPDATE hepta_v2_outcome_records SET payload_json = '{\"fixture\":false}'")
            .execute(&mut connection)
            .await?;
        connection.close().await?;
        let Err(error) = HeptaRuntime::open_existing(root).await else {
            anyhow::bail!("database row with a wrong HMAC was accepted");
        };
        assert!(
            error.to_string().contains("integrity verification failed"),
            "{error:#}"
        );
        Ok(())
    }
}
