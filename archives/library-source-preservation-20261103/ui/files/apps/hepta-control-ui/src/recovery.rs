//! Durable local recovery identities. These bytes never establish runtime authority.
use std::collections::BTreeMap;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{ControlError, ErrorCode, Result};

pub const MAX_RECORD_BYTES: usize = 8192;
pub const MAX_RECORDS: usize = 4096;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecoveryScope {
    pub endpoint: String,
    pub protocol_version: String,
    pub identity_id: String,
}

impl RecoveryScope {
    pub fn validate(&self) -> Result<()> {
        let url = url::Url::parse(&self.endpoint).map_err(|_| storage_error())?;
        if !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || self.endpoint.len() > 4096
            || self.protocol_version != "hepta.ui-control.v1"
        {
            return Err(storage_error());
        }
        crate::canonical::assert_stable_identifier(&self.identity_id).map(|_| ())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Preparation {
    New,
    ExistingNeedsRecovery,
}

/// Exact scope-bound persistence, called before the first possible mutation dispatch.
/// Existing identities are recovery-only, never permission to send again.
pub trait RecoveryStore: Send {
    fn scope(&self) -> &RecoveryScope;
    fn load(&mut self) -> Result<BTreeMap<String, Value>>;
    fn prepare(&mut self, operation_id: &str, record: &Value) -> Result<Preparation>;
    /// Remove only exact retained admission bytes after the caller validates terminal evidence.
    fn complete(&mut self, operation_id: &str, admitted_record: &Value) -> Result<()>;
}

fn storage_error() -> ControlError {
    ControlError::new(ErrorCode::Storage)
}
#[cfg(unix)]
fn store_limits() -> crate::canonical::CanonicalLimits {
    crate::canonical::CanonicalLimits {
        max_entries: 100_000,
        max_array_length: MAX_RECORDS,
        max_encoded_bytes: 32 * 1024 * 1024,
        ..crate::canonical::CanonicalLimits::default()
    }
}

#[cfg(unix)]
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StorePayload {
    schema: String,
    scope: RecoveryScope,
    records: BTreeMap<String, Value>,
}

#[cfg(unix)]
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoreEnvelope {
    payload: StorePayload,
    checksum: String,
}

/// Private root, process lock and checksummed atomic snapshot for native clients.
/// Unix paths are retained as descriptor capabilities. Other hosts fail closed
/// until their existing platform-private-state adapter is composed and qualified.
pub struct FileRecoveryStore {
    scope: RecoveryScope,
    #[cfg(unix)]
    capacity: usize,
    #[cfg(unix)]
    directory: std::fs::File,
    #[cfg(unix)]
    path: std::path::PathBuf,
}

impl FileRecoveryStore {
    pub fn open(path: &Path, scope: RecoveryScope, capacity: usize) -> Result<Self> {
        scope.validate()?;
        if capacity == 0 || capacity > MAX_RECORDS {
            return Err(storage_error());
        }
        #[cfg(unix)]
        {
            let directory = unix::open_private_root(path)?;
            let mut store = Self {
                scope,
                capacity,
                directory,
                path: path.to_path_buf(),
            };
            let _ = store.load()?;
            Ok(store)
        }
        #[cfg(not(unix))]
        {
            let _ = path;
            Err(storage_error())
        }
    }

    #[cfg(unix)]
    fn locked(&self) -> Result<unix::Lock> {
        self.verify_root()?;
        let file = unix::open_file(&self.directory, ".owner-lock", true)?;
        file.try_lock().map_err(|_| storage_error())?;
        let guard = unix::Lock {
            file,
            directory: self.directory.try_clone().map_err(|_| storage_error())?,
        };
        guard.verify()?;
        self.verify_root()?;
        Ok(guard)
    }

    #[cfg(unix)]
    fn verify_root(&self) -> Result<()> {
        use std::os::unix::fs::MetadataExt;
        let current = unix::open_private_root(&self.path)?;
        let actual = current.metadata().map_err(|_| storage_error())?;
        let retained = self.directory.metadata().map_err(|_| storage_error())?;
        if actual.dev() != retained.dev() || actual.ino() != retained.ino() {
            return Err(storage_error());
        }
        Ok(())
    }

    #[cfg(unix)]
    fn read_records(&self) -> Result<BTreeMap<String, Value>> {
        use std::io::Read;
        if unix::exists(&self.directory, "state.pending")? {
            return Err(storage_error());
        }
        let file = match unix::open_existing(&self.directory, "state.json")? {
            Some(file) => file,
            None => return Ok(BTreeMap::new()),
        };
        let maximum = self
            .capacity
            .saturating_mul(MAX_RECORD_BYTES + 256)
            .saturating_add(8192);
        if file.metadata().map_err(|_| storage_error())?.len() > maximum as u64 {
            return Err(storage_error());
        }
        let mut bytes = Vec::new();
        file.take(maximum as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| storage_error())?;
        if bytes.len() > maximum {
            return Err(storage_error());
        }
        let text = std::str::from_utf8(&bytes).map_err(|_| storage_error())?;
        let value = crate::canonical::parse_bounded_json(text, store_limits())
            .map_err(|_| storage_error())?;
        let envelope: StoreEnvelope = serde_json::from_value(value).map_err(|_| storage_error())?;
        let payload = serde_json::to_value(&envelope.payload).map_err(|_| storage_error())?;
        if crate::canonical::digest_canonical_with_limits(
            "hepta.ui-control.native-recovery.v1",
            &payload,
            store_limits(),
        )? != envelope.checksum
            || envelope.payload.schema != "hepta.ui-control.native-recovery.v1"
            || envelope.payload.scope != self.scope
            || envelope.payload.records.len() > self.capacity
        {
            return Err(storage_error());
        }
        for (id, record) in &envelope.payload.records {
            validate_record(id, record)?;
        }
        self.verify_root()?;
        Ok(envelope.payload.records)
    }

    #[cfg(unix)]
    fn write_records(
        &self,
        records: BTreeMap<String, Value>,
        previous: &BTreeMap<String, Value>,
        lock: &unix::Lock,
    ) -> Result<()> {
        use std::io::Write;
        let payload = StorePayload {
            schema: "hepta.ui-control.native-recovery.v1".into(),
            scope: self.scope.clone(),
            records,
        };
        let checksum = crate::canonical::digest_canonical_with_limits(
            "hepta.ui-control.native-recovery.v1",
            &serde_json::to_value(&payload).map_err(|_| storage_error())?,
            store_limits(),
        )?;
        let bytes = serde_json::to_vec(&StoreEnvelope { payload, checksum })
            .map_err(|_| storage_error())?;
        self.verify_root()?;
        lock.verify()?;
        let predecessor = unix::open_existing(&self.directory, "state.json")?;
        if self.read_records()? != *previous {
            return Err(storage_error());
        }
        if let Some(file) = &predecessor {
            unix::verify_named_file(&self.directory, "state.json", file)?;
        }
        let fd = rustix::fs::openat(
            &self.directory,
            "state.pending",
            rustix::fs::OFlags::WRONLY
                | rustix::fs::OFlags::CREATE
                | rustix::fs::OFlags::EXCL
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::CLOEXEC,
            rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        )
        .map_err(|_| storage_error())?;
        let mut file = std::fs::File::from(fd);
        unix::verify_file(&file)?;
        // Failure retains the pending file: uncertain publication is never retried as new work.
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| storage_error())?;
        self.verify_root()?;
        lock.verify()?;
        unix::verify_named_file(&self.directory, "state.pending", &file)?;
        match &predecessor {
            Some(prior) => unix::verify_named_file(&self.directory, "state.json", prior)?,
            None if unix::exists(&self.directory, "state.json")? => return Err(storage_error()),
            None => {}
        }
        rustix::fs::renameat(
            &self.directory,
            "state.pending",
            &self.directory,
            "state.json",
        )
        .map_err(|_| storage_error())?;
        self.directory.sync_all().map_err(|_| storage_error())?;
        self.verify_root()?;
        lock.verify()?;
        unix::verify_named_file(&self.directory, "state.json", &file)?;
        Ok(())
    }
}

fn validate_record(id: &str, record: &Value) -> Result<()> {
    crate::canonical::assert_stable_identifier(id)?;
    let mut fields = record.as_object().cloned().ok_or_else(storage_error)?;
    if fields.len() != 16
        || record["operationId"].as_str() != Some(id)
        || serde_json::to_vec(record)
            .map_err(|_| storage_error())?
            .len()
            > MAX_RECORD_BYTES
    {
        return Err(storage_error());
    }
    crate::canonical::canonical_json(record)?;
    if !matches!(
        record["state"].as_str(),
        Some("submitting" | "pending" | "indeterminate")
    ) {
        return Err(storage_error());
    }
    for key in ["createdAt", "updatedAt"] {
        crate::canonical::assert_safe_integer(record[key].as_u64().ok_or_else(storage_error)?, 1)?;
    }
    match record.get("auditTraceId") {
        Some(Value::Null) => {}
        Some(Value::String(value)) => {
            crate::canonical::assert_stable_identifier(value)?;
        }
        _ => return Err(storage_error()),
    }
    for key in ["state", "auditTraceId", "createdAt", "updatedAt"] {
        fields.remove(key);
    }
    let request: crate::contract::OperationRequest =
        serde_json::from_value(Value::Object(fields)).map_err(|_| storage_error())?;
    request.validate()
}

impl RecoveryStore for FileRecoveryStore {
    fn scope(&self) -> &RecoveryScope {
        &self.scope
    }
    fn load(&mut self) -> Result<BTreeMap<String, Value>> {
        #[cfg(unix)]
        {
            let lock = self.locked()?;
            let records = self.read_records()?;
            lock.verify()?;
            Ok(records)
        }
        #[cfg(not(unix))]
        {
            Err(storage_error())
        }
    }
    fn prepare(&mut self, id: &str, record: &Value) -> Result<Preparation> {
        validate_record(id, record)?;
        #[cfg(unix)]
        {
            let lock = self.locked()?;
            let mut records = self.read_records()?;
            if let Some(prior) = records.get(id) {
                return if prior == record {
                    Ok(Preparation::ExistingNeedsRecovery)
                } else {
                    Err(ControlError::new(ErrorCode::OperationConflict))
                };
            }
            if records.len() >= self.capacity {
                return Err(ControlError::new(ErrorCode::PendingLimit));
            }
            let previous = records.clone();
            records.insert(id.to_owned(), record.clone());
            self.write_records(records.clone(), &previous, &lock)?;
            if self.read_records()? != records {
                return Err(storage_error());
            }
            lock.verify()?;
            Ok(Preparation::New)
        }
        #[cfg(not(unix))]
        {
            Err(storage_error())
        }
    }
    fn complete(&mut self, id: &str, record: &Value) -> Result<()> {
        validate_record(id, record)?;
        #[cfg(unix)]
        {
            let lock = self.locked()?;
            let mut records = self.read_records()?;
            match records.get(id) {
                None => return Ok(()),
                Some(prior) if prior != record => {
                    return Err(ControlError::new(ErrorCode::OperationConflict));
                }
                Some(_) => {}
            }
            let previous = records.clone();
            records.remove(id);
            self.write_records(records.clone(), &previous, &lock)?;
            if self.read_records()? != records {
                return Err(storage_error());
            }
            lock.verify()?;
            Ok(())
        }
        #[cfg(not(unix))]
        {
            Err(storage_error())
        }
    }
}

#[cfg(unix)]
#[path = "recovery_unix.rs"]
mod unix;

#[cfg(test)]
#[path = "recovery_tests.rs"]
mod tests;
