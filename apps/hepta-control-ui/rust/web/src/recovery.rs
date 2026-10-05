//! Exact-compatible scoped recovery records with crash-consistent indexed admission.
use hepta_control_core::{
    canonical::assert_stable_identifier,
    error::{ControlError, ErrorCode},
};
use serde_json::{Value, json};
use std::{cell::Cell, collections::BTreeMap, rc::Rc};

#[cfg(target_arch = "wasm32")]
mod browser;
mod directory;
#[cfg(target_arch = "wasm32")]
pub use browser::{PreparedRecovery, ScopedRecoveryStore};

const SCHEMA: &str = "hepta.ui-control.scoped-recovery.v2";
const DIRECTORY_SCHEMA: &str = "hepta.ui-control.scoped-recovery-directory.v1";
const LEGACY_SCHEMA: &str = "hepta.ui-control.recovery-state.v1";
const MAX_RECORD_BYTES: usize = 8192;
const MAX_DIRECTORY_BYTES: usize = 1024 * 1024;
const MAX_MIGRATION_KEYS: u32 = 16384;
const IDENTITY_FIELDS: [&str; 12] = [
    "protocolVersion",
    "method",
    "operationId",
    "semanticDigest",
    "action",
    "targetId",
    "reason",
    "sessionId",
    "connectionGeneration",
    "generation",
    "displayedRevision",
    "snapshotDigest",
];
const COMPLETION_FIELDS: [&str; 7] = [
    "operationId",
    "semanticDigest",
    "method",
    "action",
    "targetId",
    "generation",
    "displayedRevision",
];

type Entries = BTreeMap<String, Entry>;

#[derive(Clone, Debug, PartialEq, Eq)]
enum Entry {
    Ready,
    Reserving(Vec<Value>),
    Removing(Vec<Value>),
}

/// Small synchronous storage boundary; mutations are called only while holding the scope lock.
trait StorageIo {
    fn get(&self, key: &str, reason: &'static str) -> Result<Option<String>, ControlError>;
    fn set(&self, key: &str, value: &str, reason: &'static str) -> Result<(), ControlError>;
    fn remove(&self, key: &str, reason: &'static str) -> Result<(), ControlError>;
    fn len(&self) -> Result<u32, ControlError>;
    fn key(&self, index: u32) -> Result<Option<String>, ControlError>;
}

fn failure(reason: &'static str) -> ControlError {
    ControlError::unsent(ErrorCode::Storage)
        .retryable(true)
        .detail("storageReason", json!(reason))
}

fn recovery_identifier(value: &str) -> Result<&str, ControlError> {
    assert_stable_identifier(value).map_err(|_| failure("identity_invalid"))?;
    Ok(value)
}

fn operation_id(operation: &Value) -> Result<&str, ControlError> {
    recovery_identifier(
        operation
            .get("operationId")
            .and_then(Value::as_str)
            .ok_or_else(|| failure("identity_invalid"))?,
    )
}

fn identity(operation: &Value) -> Vec<Value> {
    IDENTITY_FIELDS
        .iter()
        .map(|field| operation.get(field).cloned().unwrap_or(Value::Null))
        .collect()
}

fn same_identity(left: &Value, right: &Value, fields: &[&str]) -> bool {
    fields
        .iter()
        .all(|field| value_equal(left.get(field), right.get(field)))
}

// JSON.parse has one IEEE-754 Number type; 1 and 1.0 are the same retained scalar.
fn value_equal(left: Option<&Value>, right: Option<&Value>) -> bool {
    match (left, right) {
        (Some(Value::Number(left)), Some(Value::Number(right))) => left.as_f64() == right.as_f64(),
        _ => left == right,
    }
}

struct Engine {
    storage: Rc<dyn StorageIo>,
    scope_digest: String,
    prefix: String,
    directory_key: String,
    max_entries: usize,
    migration_scans: Cell<u32>,
    migration_keys: Cell<u32>,
}

#[derive(Clone)]
struct PreparedRecord {
    operation_id: String,
    raw: String,
    identity: Vec<Value>,
}

impl Engine {
    fn new(
        storage: Rc<dyn StorageIo>,
        scope_digest: String,
        max_entries: usize,
    ) -> Result<Self, ControlError> {
        if !(1..=4096).contains(&max_entries) {
            return Err(failure("capacity_invalid"));
        }
        if scope_digest.len() != 64
            || !scope_digest
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(failure("scope_invalid"));
        }
        Ok(Self {
            storage,
            prefix: format!("{SCHEMA}:{scope_digest}:"),
            directory_key: format!("{DIRECTORY_SCHEMA}:{scope_digest}"),
            scope_digest,
            max_entries,
            migration_scans: Cell::new(0),
            migration_keys: Cell::new(0),
        })
    }

    fn record_key(&self, operation_id: &str) -> Result<String, ControlError> {
        Ok(format!(
            "{}{}",
            self.prefix,
            recovery_identifier(operation_id)?
        ))
    }

    fn decode_record(&self, key: &str, raw: &str) -> Result<Value, ControlError> {
        if raw.len() > MAX_RECORD_BYTES {
            return Err(failure("record_oversized"));
        }
        let value: Value = serde_json::from_str(raw).map_err(|_| failure("record_corrupt"))?;
        let operation = value
            .get("operation")
            .ok_or_else(|| failure("record_scope_mismatch"))?;
        if value.get("schema").and_then(Value::as_str) != Some(SCHEMA)
            || value.get("scopeDigest").and_then(Value::as_str) != Some(self.scope_digest.as_str())
            || key != self.record_key(operation_id(operation)?)?
        {
            return Err(failure("record_scope_mismatch"));
        }
        Ok(operation.clone())
    }

    fn load(&self) -> Result<Value, ControlError> {
        let entries = self.read_directory()?;
        let mut operations = Vec::with_capacity(entries.len());
        for (id, entry) in entries {
            if entry != Entry::Ready {
                continue;
            }
            let key = self.record_key(&id)?;
            if let Some(raw) = self.storage.get(&key, "record_read_failed")? {
                operations.push(self.decode_record(&key, &raw)?);
            } else if self.read_directory()?.get(&id) == Some(&Entry::Ready) {
                // Only a verified concurrent transition can explain a missing ready record.
                return Err(failure("directory_record_missing"));
            }
        }
        Ok(json!({"schema": LEGACY_SCHEMA, "operations": operations}))
    }

    fn diagnostics(&self) -> Result<Value, ControlError> {
        let entries = self.read_directory()?;
        let (mut ready, mut reserving, mut removing) = (0, 0, 0);
        for entry in entries.values() {
            match entry {
                Entry::Ready => ready += 1,
                Entry::Reserving(_) => reserving += 1,
                Entry::Removing(_) => removing += 1,
            }
        }
        Ok(
            json!({"schema": DIRECTORY_SCHEMA, "entries": entries.len(), "maxEntries": self.max_entries,
            "states": {"ready": ready, "reserving": reserving, "removing": removing},
            "migrationScans": self.migration_scans.get(), "migrationKeys": self.migration_keys.get()}),
        )
    }

    fn prepare_locked(&self, operation: &Value) -> Result<PreparedRecord, ControlError> {
        let id = operation_id(operation)?;
        let key = self.record_key(id)?;
        let mut entries = self.read_directory()?;
        if self.reconcile(&mut entries)? {
            self.write_directory(&entries)?;
        }
        if let Some(raw) = self.storage.get(&key, "record_read_failed")? {
            let prior = self.decode_record(&key, &raw)?;
            if !same_identity(&prior, operation, &IDENTITY_FIELDS) {
                return Err(ControlError::unsent(ErrorCode::OperationConflict));
            }
            let mut error = ControlError::new(ErrorCode::AmbiguousSubmission)
                .retryable(true)
                .with_dispatch(true);
            if !entries.contains_key(id) {
                let repair = if entries.len() >= self.max_entries {
                    Err(failure("capacity_exhausted"))
                } else {
                    entries.insert(id.into(), Entry::Ready);
                    self.write_directory(&entries)
                };
                if let Err(repair) = repair {
                    error.details = repair.details;
                }
            }
            return Err(error);
        }
        if entries.contains_key(id) {
            return Err(failure("directory_record_missing"));
        }
        if entries.len() >= self.max_entries {
            return Err(failure("capacity_exhausted"));
        }
        let identity = identity(operation);
        entries.insert(id.into(), Entry::Reserving(identity.clone()));
        self.write_directory(&entries)?;
        let raw = serde_json::to_string(
            &json!({"schema": SCHEMA, "scopeDigest": self.scope_digest, "operation": operation}),
        )
        .map_err(|_| failure("record_corrupt"))?;
        if raw.len() > MAX_RECORD_BYTES {
            return Err(failure("record_oversized"));
        }
        self.storage.set(&key, &raw, "record_write_failed")?;
        if self
            .storage
            .get(&key, "record_write_readback_failed")?
            .as_deref()
            != Some(raw.as_str())
        {
            return Err(failure("record_write_readback_failed"));
        }
        entries.insert(id.into(), Entry::Ready);
        self.write_directory(&entries)?;
        Ok(PreparedRecord {
            operation_id: id.into(),
            raw,
            identity,
        })
    }

    fn discard_locked(&self, prepared: &PreparedRecord) -> Result<bool, ControlError> {
        let mut entries = self.read_directory()?;
        if self.reconcile(&mut entries)? {
            self.write_directory(&entries)?;
        }
        let key = self.record_key(&prepared.operation_id)?;
        if self.storage.get(&key, "record_read_failed")?.as_deref() != Some(prepared.raw.as_str()) {
            return Ok(false);
        }
        entries.insert(
            prepared.operation_id.clone(),
            Entry::Removing(prepared.identity.clone()),
        );
        self.write_directory(&entries)?;
        self.storage.remove(&key, "record_remove_failed")?;
        if self
            .storage
            .get(&key, "record_remove_readback_failed")?
            .is_some()
        {
            return Err(failure("record_remove_readback_failed"));
        }
        entries.remove(&prepared.operation_id);
        self.write_directory(&entries)?;
        Ok(true)
    }

    fn complete_locked(&self, operation: &Value) -> Result<bool, ControlError> {
        if operation.get("state").and_then(Value::as_str) != Some("terminal") {
            return Ok(false);
        }
        let id = operation_id(operation)?;
        let key = self.record_key(id)?;
        let mut entries = self.read_directory()?;
        if self.reconcile(&mut entries)? {
            self.write_directory(&entries)?;
        }
        let Some(raw) = self.storage.get(&key, "record_read_failed")? else {
            if entries.contains_key(id) {
                return Err(failure("directory_record_missing"));
            }
            return Ok(false);
        };
        let stored = self.decode_record(&key, &raw)?;
        if !same_identity(&stored, operation, &COMPLETION_FIELDS) {
            return Err(failure("terminal_identity_mismatch"));
        }
        let indexed = entries.contains_key(id);
        if indexed {
            entries.insert(id.into(), Entry::Removing(identity(&stored)));
            self.write_directory(&entries)?;
        }
        self.storage.remove(&key, "record_remove_failed")?;
        if self
            .storage
            .get(&key, "record_remove_readback_failed")?
            .is_some()
        {
            return Err(failure("record_remove_readback_failed"));
        }
        if indexed {
            entries.remove(id);
            self.write_directory(&entries)?;
        }
        Ok(true)
    }
}

#[cfg(test)]
#[path = "recovery/storage_tests.rs"]
mod tests;
