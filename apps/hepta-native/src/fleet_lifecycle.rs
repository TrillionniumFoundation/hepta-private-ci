//! Desktop intent references only; the Supervisor owns every durable effect.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::io::Read as _;

use crate::error::ShellError;
use crate::model::sha256_hex;
use crate::model::validate_digest;
use crate::model::validate_stable_id;
use crate::private_state::PrivateStateRoot;

pub use codex_hepta_contracts::native_gateway::lifecycle::NativeGatewayLifecycleOperationV2 as FleetLifecycleOperation;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PendingLifecycle {
    pub schema_version: u32,
    pub endpoint_id: String,
    pub owner_epoch: String,
    pub agent_id: String,
    pub request_id: u64,
    pub operation: FleetLifecycleOperation,
    pub accepted_state_digest: String,
}

impl PendingLifecycle {
    fn validate(&self) -> Result<(), ShellError> {
        validate_stable_id(&self.endpoint_id, "lifecycle endpoint")?;
        validate_digest(&self.accepted_state_digest, "lifecycle fence digest")?;
        if self.schema_version != 1
            || self.request_id == 0
            || self.operation == FleetLifecycleOperation::Receipt
            || !uuid(&self.owner_epoch)
            || !uuid(&self.agent_id)
        {
            return Err(ShellError::State(
                "invalid original lifecycle reference".into(),
            ));
        }
        Ok(())
    }

    pub fn receipt_request(&self, request_id: u64) -> Value {
        serde_json::json!({"schema_version":1,"request_id":request_id,"method":{
            "type":"receipt","agent_id":self.agent_id,"mutation_request_id":self.request_id
        }})
    }

    pub fn receipt_terminal(&self, value: &Value) -> Result<bool, ShellError> {
        if value["type"] != "ordinary_mutation_status" {
            return Ok(false);
        }
        let status = &value["status"];
        if status.is_null() {
            return Ok(false);
        }
        if status["request_id"].as_u64() != Some(self.request_id)
            || status["agent_id"] != self.agent_id
            || status["supervisor_epoch"] != self.owner_epoch
            || status["accepted_state_digest"] != self.accepted_state_digest
            || status["operation"] != serde_json::to_value(self.operation)?
        {
            return Err(ShellError::Security(
                "lifecycle receipt belongs to another original intent".into(),
            ));
        }
        Ok(matches!(
            status["phase"].as_str(),
            Some("committed" | "no_effect")
        ))
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredReference {
    pending: Option<PendingLifecycle>,
    checksum: String,
}

pub(crate) struct PendingLifecycleStore {
    root: PrivateStateRoot,
    _lock: std::fs::File,
    pending: Option<PendingLifecycle>,
    poisoned: bool,
}

impl PendingLifecycleStore {
    pub fn open(root: PrivateStateRoot) -> Result<Self, ShellError> {
        root.verify()?;
        let lock_path = root.path().join("fleet-lifecycle-pending.lock");
        let lock = crate::journal_storage::open_private_file_in(
            &root,
            &lock_path,
            crate::journal_storage::FileAccess::Lock,
            lock_path.exists(),
        )?;
        lock.try_lock().map_err(|_| {
            ShellError::State("another desktop owns the original lifecycle references".into())
        })?;
        let path = root.path().join("fleet-lifecycle-pending.json");
        let pending = if path.exists() {
            let mut bytes = Vec::new();
            crate::journal_storage::open_private_file_in(
                &root,
                &path,
                crate::journal_storage::FileAccess::Read,
                true,
            )?
            .take(32 * 1024 + 1)
            .read_to_end(&mut bytes)?;
            if bytes.len() > 32 * 1024 {
                return Err(ShellError::State(
                    "lifecycle reference exceeded bound".into(),
                ));
            }
            let stored: StoredReference = serde_json::from_slice(&bytes)?;
            if stored.checksum != checksum(&stored.pending)? {
                return Err(ShellError::Security(
                    "lifecycle reference checksum mismatch".into(),
                ));
            }
            if let Some(pending) = &stored.pending {
                pending.validate()?;
            }
            stored.pending
        } else {
            None
        };
        Ok(Self {
            root,
            _lock: lock,
            pending,
            poisoned: false,
        })
    }

    pub fn pending(&self) -> Option<&PendingLifecycle> {
        self.pending.as_ref()
    }

    pub fn reserve(&mut self, pending: PendingLifecycle) -> Result<(), ShellError> {
        pending.validate()?;
        if self.pending.is_some() || self.poisoned {
            return Err(ShellError::State(
                "inspect the original lifecycle receipt before a new action".into(),
            ));
        }
        self.pending = Some(pending);
        self.persist()
    }

    pub fn clear_terminal(&mut self) -> Result<(), ShellError> {
        if self.poisoned {
            return Err(ShellError::State(
                "lifecycle reference requires reopen and receipt inspection".into(),
            ));
        }
        let bytes = serde_json::to_vec(&StoredReference {
            pending: None,
            checksum: checksum(&None)?,
        })?;
        if let Err(error) = crate::journal_storage::write_private(
            &self.root,
            &self.root.path().join("fleet-lifecycle-pending.json"),
            &bytes,
        ) {
            self.poisoned = true;
            return Err(error);
        }
        self.pending = None;
        Ok(())
    }

    fn persist(&mut self) -> Result<(), ShellError> {
        let bytes = serde_json::to_vec(&StoredReference {
            pending: self.pending.clone(),
            checksum: checksum(&self.pending)?,
        })?;
        if let Err(error) = crate::journal_storage::write_private(
            &self.root,
            &self.root.path().join("fleet-lifecycle-pending.json"),
            &bytes,
        ) {
            self.poisoned = true;
            return Err(error);
        }
        Ok(())
    }
}

fn checksum(pending: &Option<PendingLifecycle>) -> Result<String, ShellError> {
    let mut bytes = b"hepta.desktop.lifecycle.reference.v1\0".to_vec();
    bytes.extend(serde_json::to_vec(pending)?);
    Ok(sha256_hex(bytes))
}

pub(crate) fn request_id() -> Result<u64, ShellError> {
    let mut bytes = [0; 8];
    getrandom::fill(&mut bytes)
        .map_err(|error| ShellError::Security(format!("lifecycle request identity: {error}")))?;
    Ok(u64::from_be_bytes(bytes).max(1))
}

fn uuid(value: &str) -> bool {
    crate::fleet_observation::uuid(value)
}

#[cfg(test)]
#[path = "fleet_lifecycle_tests.rs"]
mod tests;
