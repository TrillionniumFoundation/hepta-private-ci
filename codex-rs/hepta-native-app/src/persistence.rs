use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use serde::Deserialize;
use serde::Serialize;

use crate::runtime::MAX_OPERATION_RECORDS;
use crate::runtime::NativeError;
use crate::runtime::OperationRecord;
use crate::runtime::OperationStore;

const SERVICE: &str = "hepta.native";
const INDEX_SCHEMA: u32 = 1;
const MAX_INDEX_BYTES: usize = 2400;
const MAX_RECORD_BYTES: usize = 2200;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OperationIndex {
    schema_version: u32,
    accounts: Vec<String>,
}

pub struct KeyringOperationStore {
    keyring: Box<dyn KeyringStore>,
    index_account: String,
}

impl KeyringOperationStore {
    pub fn system(agent_id: &str) -> Result<Self, NativeError> {
        Self::new(Box::new(DefaultKeyringStore), agent_id)
    }

    pub fn new(keyring: Box<dyn KeyringStore>, agent_id: &str) -> Result<Self, NativeError> {
        if agent_id.is_empty() || agent_id.len() > 128 || agent_id.as_bytes().contains(&0) {
            return Err(NativeError::Journal(
                "keyring journal requires a bounded agent id".to_string(),
            ));
        }
        let namespace = Sha256Digest::for_bytes(agent_id.as_bytes());
        Ok(Self {
            keyring,
            index_account: format!("op-index.{}", &namespace.as_str()[..24]),
        })
    }

    fn read_index(&self) -> Result<OperationIndex, NativeError> {
        let Some(raw) = self
            .keyring
            .load(SERVICE, &self.index_account)
            .map_err(|error| NativeError::Journal(error.message()))?
        else {
            return Ok(OperationIndex {
                schema_version: INDEX_SCHEMA,
                accounts: Vec::new(),
            });
        };
        if raw.len() > MAX_INDEX_BYTES {
            return Err(NativeError::Journal(
                "keyring operation index exceeds its bound".to_string(),
            ));
        }
        let index: OperationIndex = serde_json::from_str(&raw)
            .map_err(|error| NativeError::Journal(format!("decode operation index: {error}")))?;
        if index.schema_version != INDEX_SCHEMA
            || index.accounts.len() > MAX_OPERATION_RECORDS
            || index
                .accounts
                .iter()
                .any(|account| !valid_account(account))
        {
            return Err(NativeError::Journal(
                "keyring operation index failed validation".to_string(),
            ));
        }
        let unique: BTreeSet<_> = index.accounts.iter().collect();
        if unique.len() != index.accounts.len() {
            return Err(NativeError::Journal(
                "keyring operation index contains duplicates".to_string(),
            ));
        }
        Ok(index)
    }

    fn write_index(&self, index: &OperationIndex) -> Result<(), NativeError> {
        let raw = serde_json::to_string(index)
            .map_err(|error| NativeError::Journal(format!("encode operation index: {error}")))?;
        if raw.len() > MAX_INDEX_BYTES {
            return Err(NativeError::Journal(
                "keyring operation index exceeds credential size budget".to_string(),
            ));
        }
        self.keyring
            .save(SERVICE, &self.index_account, &raw)
            .map_err(|error| NativeError::Journal(error.message()))
    }

    fn account(record: &OperationRecord) -> String {
        let identity = format!(
            "{}:{}:{}",
            record.key.session_id, record.key.session_generation, record.key.operation_id
        );
        let digest = Sha256Digest::for_bytes(identity.as_bytes());
        format!("op.{}", digest.as_str())
    }

    fn write_record(&self, account: &str, record: &OperationRecord) -> Result<(), NativeError> {
        let raw = serde_json::to_string(record)
            .map_err(|error| NativeError::Journal(format!("encode operation record: {error}")))?;
        if raw.len() > MAX_RECORD_BYTES {
            return Err(NativeError::Journal(
                "operation record exceeds credential size budget".to_string(),
            ));
        }
        self.keyring
            .save(SERVICE, account, &raw)
            .map_err(|error| NativeError::Journal(error.message()))
    }
}

impl OperationStore for KeyringOperationStore {
    fn load(&self) -> Result<Vec<OperationRecord>, NativeError> {
        let index = self.read_index()?;
        let mut records = Vec::with_capacity(index.accounts.len());
        for account in index.accounts {
            let raw = self
                .keyring
                .load(SERVICE, &account)
                .map_err(|error| NativeError::Journal(error.message()))?
                .ok_or_else(|| {
                    NativeError::Journal(format!(
                        "operation index references missing credential {account}; refusing replay"
                    ))
                })?;
            if raw.len() > MAX_RECORD_BYTES {
                return Err(NativeError::Journal(
                    "operation record exceeds credential size budget".to_string(),
                ));
            }
            records.push(
                serde_json::from_str(&raw).map_err(|error| {
                    NativeError::Journal(format!("decode operation record: {error}"))
                })?,
            );
        }
        Ok(records)
    }

    fn insert_new(&self, record: &OperationRecord) -> Result<(), NativeError> {
        let account = Self::account(record);
        let mut index = self.read_index()?;
        if index.accounts.iter().any(|existing| existing == &account) {
            return Err(NativeError::Journal(
                "operation identity already exists in secure journal".to_string(),
            ));
        }
        if index.accounts.len() >= MAX_OPERATION_RECORDS {
            return Err(NativeError::Journal(
                "secure operation journal is full".to_string(),
            ));
        }

        // Index-first is deliberate: if the second write fails, restart sees a
        // missing record and fails closed. A platform effect is never dispatched
        // until both writes succeeded.
        index.accounts.push(account.clone());
        self.write_index(&index)?;
        self.write_record(&account, record)
    }

    fn update(&self, record: &OperationRecord) -> Result<(), NativeError> {
        let account = Self::account(record);
        let index = self.read_index()?;
        if !index.accounts.iter().any(|existing| existing == &account) {
            return Err(NativeError::Journal(
                "operation update is absent from secure index".to_string(),
            ));
        }
        self.write_record(&account, record)
    }
}

fn valid_account(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("op.")
        && value[3..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}


/// Fail-closed store used when the OS credential backend is unavailable.
///
/// Read-only UI remains usable, but no effect can cross the durable-intent
/// boundary because insert/update always fail.
pub struct ReadOnlyOperationStore {
    reason: String,
}

impl ReadOnlyOperationStore {
    pub fn new(reason: impl Into<String>) -> Self {
        Self {
            reason: reason.into(),
        }
    }
}

impl OperationStore for ReadOnlyOperationStore {
    fn load(&self) -> Result<Vec<OperationRecord>, NativeError> {
        Ok(Vec::new())
    }

    fn insert_new(&self, _record: &OperationRecord) -> Result<(), NativeError> {
        Err(NativeError::Journal(format!(
            "secure operation persistence is unavailable; effect refused: {}",
            self.reason
        )))
    }

    fn update(&self, _record: &OperationRecord) -> Result<(), NativeError> {
        Err(NativeError::Journal(format!(
            "secure operation persistence is unavailable; journal update refused: {}",
            self.reason
        )))
    }
}
