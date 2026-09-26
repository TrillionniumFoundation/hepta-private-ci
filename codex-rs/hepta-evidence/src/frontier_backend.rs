use std::collections::BTreeMap;
use std::sync::RwLock;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const MAX_SIGNED_FRONTIER_BYTES: usize = 128 * 1024;
pub const EVIDENCE_FRONTIER_HISTORY_MAX_RESULTS: usize = 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceFrontierDurabilityClassV1 {
    Ephemeral,
    ExternalQuorum,
    HardwareRooted,
    WriteOnce,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceFrontierBackendIdentityV1 {
    pub schema_version: u32,
    pub backend_id: String,
    pub rollback_domain_id: String,
    pub authentication_key_id: String,
    pub authentication_key_epoch: u64,
    pub durability_class: EvidenceFrontierDurabilityClassV1,
    pub authenticated_reads: bool,
    pub authenticated_writes: bool,
    pub compare_and_swap: bool,
    pub append_only_audit_log: bool,
    pub durable_acknowledgements: bool,
}

impl EvidenceFrontierBackendIdentityV1 {
    pub fn validate(&self) -> Result<(), EvidenceFrontierBackendError> {
        if self.schema_version != 1 {
            return Err(invalid("unsupported frontier backend identity schema"));
        }
        validate_id(&self.backend_id, "backend id")?;
        validate_id(&self.rollback_domain_id, "rollback-domain id")?;
        validate_id(&self.authentication_key_id, "authentication key id")?;
        Generation::new(self.authentication_key_epoch)
            .map_err(|error| invalid(&format!("invalid authentication key epoch: {error}")))?;
        Ok(())
    }

    pub fn validate_for_production(
        &self,
        local_rollback_domain_id: &str,
    ) -> Result<(), EvidenceFrontierBackendError> {
        self.validate()?;
        validate_id(local_rollback_domain_id, "local rollback-domain id")?;
        if self.rollback_domain_id == local_rollback_domain_id {
            return Err(EvidenceFrontierBackendError::UnsafeForProduction(
                "frontier backend shares the local evidence rollback domain".to_string(),
            ));
        }
        if matches!(
            self.durability_class,
            EvidenceFrontierDurabilityClassV1::Ephemeral
        ) || !self.authenticated_reads
            || !self.authenticated_writes
            || !self.compare_and_swap
            || !self.append_only_audit_log
            || !self.durable_acknowledgements
        {
            return Err(EvidenceFrontierBackendError::UnsafeForProduction(
                "backend lacks authenticated read/write, CAS, append-only audit, or durable acknowledgement"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceFrontierRecordV1 {
    pub schema_version: u32,
    pub store_id: String,
    pub generation: u64,
    pub signed_frontier_json: String,
    pub signed_frontier_sha256: Sha256Digest,
    pub backend_audit_event_id: String,
    pub committed_at_unix_ms: u64,
    pub backend_key_epoch: u64,
}

impl EvidenceFrontierRecordV1 {
    pub fn validate(&self) -> Result<(), EvidenceFrontierBackendError> {
        if self.schema_version != 1 {
            return Err(invalid("unsupported frontier record schema"));
        }
        validate_id(&self.store_id, "store id")?;
        Generation::new(self.generation)
            .map_err(|error| invalid(&format!("invalid frontier generation: {error}")))?;
        validate_id(&self.backend_audit_event_id, "backend audit event id")?;
        Generation::new(self.backend_key_epoch)
            .map_err(|error| invalid(&format!("invalid backend key epoch: {error}")))?;
        if self.committed_at_unix_ms == 0 {
            return Err(invalid("frontier commit time must be non-zero"));
        }
        if self.signed_frontier_json.is_empty()
            || self.signed_frontier_json.len() > MAX_SIGNED_FRONTIER_BYTES
        {
            return Err(invalid("signed frontier JSON is empty or exceeds 128 KiB"));
        }
        let actual = Sha256Digest::for_bytes(self.signed_frontier_json.as_bytes());
        if actual != self.signed_frontier_sha256 {
            return Err(invalid("signed frontier digest does not match its bytes"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceFrontierCasReceiptV1 {
    pub schema_version: u32,
    pub backend_id: String,
    pub store_id: String,
    pub expected_generation: Option<u64>,
    pub committed_generation: u64,
    pub signed_frontier_sha256: Sha256Digest,
    pub backend_audit_event_id: String,
    pub durable_acknowledgement: String,
    pub backend_key_epoch: u64,
    pub idempotent_replay: bool,
}

#[derive(Debug, thiserror::Error)]
pub enum EvidenceFrontierBackendError {
    #[error("invalid evidence frontier backend value: {0}")]
    Invalid(String),
    #[error("evidence frontier backend is unavailable: {0}")]
    Unavailable(String),
    #[error("evidence frontier compare-and-swap conflict: expected {expected:?}, actual {actual:?}")]
    CompareAndSwapConflict {
        expected: Option<u64>,
        actual: Option<u64>,
    },
    #[error("evidence frontier backend is unsafe for production: {0}")]
    UnsafeForProduction(String),
    #[error("evidence frontier backend lock is poisoned")]
    Poisoned,
}

/// Authenticated monotonic storage contract for a signed evidence frontier.
///
/// Production implementations live outside the evidence database rollback
/// domain. A successful `compare_and_swap` must mean both the frontier record
/// and its append-only audit event are durable before the receipt is returned.
pub trait EvidenceFrontierBackend: Send + Sync {
    fn get_latest(
        &self,
        store_id: &str,
    ) -> Result<Option<EvidenceFrontierRecordV1>, EvidenceFrontierBackendError>;

    fn compare_and_swap(
        &self,
        store_id: &str,
        expected_generation: Option<u64>,
        new_frontier: EvidenceFrontierRecordV1,
    ) -> Result<EvidenceFrontierCasReceiptV1, EvidenceFrontierBackendError>;

    fn get_history(
        &self,
        store_id: &str,
        after_generation: Option<u64>,
        limit: usize,
    ) -> Result<Vec<EvidenceFrontierRecordV1>, EvidenceFrontierBackendError>;

    fn verify_backend_identity(
        &self,
    ) -> Result<EvidenceFrontierBackendIdentityV1, EvidenceFrontierBackendError>;
}

/// Deterministic test backend. It intentionally reports ephemeral durability,
/// so `validate_for_production` always rejects it.
pub struct InMemoryEvidenceFrontierBackend {
    identity: EvidenceFrontierBackendIdentityV1,
    records: RwLock<BTreeMap<String, Vec<EvidenceFrontierRecordV1>>>,
}

impl InMemoryEvidenceFrontierBackend {
    pub fn new(backend_id: String, rollback_domain_id: String) -> Result<Self, EvidenceFrontierBackendError> {
        let identity = EvidenceFrontierBackendIdentityV1 {
            schema_version: 1,
            backend_id,
            rollback_domain_id,
            authentication_key_id: "key:in-memory-frontier".to_string(),
            authentication_key_epoch: 1,
            durability_class: EvidenceFrontierDurabilityClassV1::Ephemeral,
            authenticated_reads: true,
            authenticated_writes: true,
            compare_and_swap: true,
            append_only_audit_log: true,
            durable_acknowledgements: false,
        };
        identity.validate()?;
        Ok(Self {
            identity,
            records: RwLock::new(BTreeMap::new()),
        })
    }
}

impl EvidenceFrontierBackend for InMemoryEvidenceFrontierBackend {
    fn get_latest(
        &self,
        store_id: &str,
    ) -> Result<Option<EvidenceFrontierRecordV1>, EvidenceFrontierBackendError> {
        validate_id(store_id, "store id")?;
        let records = self.records.read().map_err(|_| EvidenceFrontierBackendError::Poisoned)?;
        Ok(records.get(store_id).and_then(|history| history.last()).cloned())
    }

    fn compare_and_swap(
        &self,
        store_id: &str,
        expected_generation: Option<u64>,
        new_frontier: EvidenceFrontierRecordV1,
    ) -> Result<EvidenceFrontierCasReceiptV1, EvidenceFrontierBackendError> {
        validate_id(store_id, "store id")?;
        new_frontier.validate()?;
        if new_frontier.store_id != store_id {
            return Err(invalid("frontier record store id does not match request"));
        }
        let required_generation = expected_generation
            .map(|value| value.checked_add(1).ok_or_else(|| invalid("generation overflow")))
            .transpose()?
            .unwrap_or(1);
        if new_frontier.generation != required_generation {
            return Err(invalid("new frontier generation must be expected generation plus one"));
        }

        let mut records = self.records.write().map_err(|_| EvidenceFrontierBackendError::Poisoned)?;
        let history = records.entry(store_id.to_string()).or_default();
        let actual = history.last().map(|record| record.generation);
        let idempotent_replay = history.last().is_some_and(|record| {
            record.generation == new_frontier.generation
                && record.signed_frontier_sha256 == new_frontier.signed_frontier_sha256
                && expected_generation == new_frontier.generation.checked_sub(1)
        });
        if !idempotent_replay && actual != expected_generation {
            return Err(EvidenceFrontierBackendError::CompareAndSwapConflict {
                expected: expected_generation,
                actual,
            });
        }
        if !idempotent_replay {
            history.push(new_frontier.clone());
        }
        Ok(EvidenceFrontierCasReceiptV1 {
            schema_version: 1,
            backend_id: self.identity.backend_id.clone(),
            store_id: store_id.to_string(),
            expected_generation,
            committed_generation: new_frontier.generation,
            signed_frontier_sha256: new_frontier.signed_frontier_sha256,
            backend_audit_event_id: new_frontier.backend_audit_event_id,
            durable_acknowledgement: format!(
                "ephemeral:{}:{}",
                self.identity.backend_id, new_frontier.generation
            ),
            backend_key_epoch: self.identity.authentication_key_epoch,
            idempotent_replay,
        })
    }

    fn get_history(
        &self,
        store_id: &str,
        after_generation: Option<u64>,
        limit: usize,
    ) -> Result<Vec<EvidenceFrontierRecordV1>, EvidenceFrontierBackendError> {
        validate_id(store_id, "store id")?;
        if limit == 0 || limit > EVIDENCE_FRONTIER_HISTORY_MAX_RESULTS {
            return Err(invalid("history limit must be between 1 and 1024"));
        }
        let records = self.records.read().map_err(|_| EvidenceFrontierBackendError::Poisoned)?;
        Ok(records
            .get(store_id)
            .into_iter()
            .flat_map(|history| history.iter())
            .filter(|record| after_generation.is_none_or(|generation| record.generation > generation))
            .take(limit)
            .cloned()
            .collect())
    }

    fn verify_backend_identity(
        &self,
    ) -> Result<EvidenceFrontierBackendIdentityV1, EvidenceFrontierBackendError> {
        self.identity.validate()?;
        Ok(self.identity.clone())
    }
}

fn validate_id(value: &str, label: &str) -> Result<(), EvidenceFrontierBackendError> {
    StableId::new(value.to_string())
        .map(|_| ())
        .map_err(|error| invalid(&format!("invalid {label}: {error}")))
}

fn invalid(message: &str) -> EvidenceFrontierBackendError {
    EvidenceFrontierBackendError::Invalid(message.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(generation: u64, payload: &str) -> EvidenceFrontierRecordV1 {
        EvidenceFrontierRecordV1 {
            schema_version: 1,
            store_id: "store:evidence-test".to_string(),
            generation,
            signed_frontier_json: payload.to_string(),
            signed_frontier_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
            backend_audit_event_id: format!("audit:evidence-frontier-{generation}"),
            committed_at_unix_ms: generation,
            backend_key_epoch: 1,
        }
    }

    #[test]
    fn cas_is_monotonic_idempotent_and_history_is_bounded() {
        let backend = InMemoryEvidenceFrontierBackend::new(
            "backend:evidence-test".to_string(),
            "rollback:test-backend".to_string(),
        )
        .expect("backend");
        let first = record(1, r#"{"generation":1}"#);
        let receipt = backend
            .compare_and_swap("store:evidence-test", None, first.clone())
            .expect("first CAS");
        assert!(!receipt.idempotent_replay);
        let replay = backend
            .compare_and_swap("store:evidence-test", None, first)
            .expect("idempotent replay");
        assert!(replay.idempotent_replay);
        let conflict = backend
            .compare_and_swap(
                "store:evidence-test",
                None,
                record(1, r#"{"generation":1,"drift":true}"#),
            )
            .expect_err("semantic drift must conflict");
        assert!(matches!(
            conflict,
            EvidenceFrontierBackendError::CompareAndSwapConflict { .. }
        ));
        backend
            .compare_and_swap("store:evidence-test", Some(1), record(2, r#"{"generation":2}"#))
            .expect("second CAS");
        assert_eq!(
            backend
                .get_history("store:evidence-test", Some(1), 16)
                .expect("history")
                .iter()
                .map(|entry| entry.generation)
                .collect::<Vec<_>>(),
            vec![2]
        );
    }

    #[test]
    fn ephemeral_backend_cannot_satisfy_production_identity() {
        let backend = InMemoryEvidenceFrontierBackend::new(
            "backend:evidence-test".to_string(),
            "rollback:test-backend".to_string(),
        )
        .expect("backend");
        let identity = backend.verify_backend_identity().expect("identity");
        assert!(matches!(
            identity.validate_for_production("rollback:local-evidence"),
            Err(EvidenceFrontierBackendError::UnsafeForProduction(_))
        ));
    }
}
