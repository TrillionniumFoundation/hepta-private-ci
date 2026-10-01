//! A frozen external credential consumer confirms original operations by signature.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::BaoConsumerObservationV1;
use crate::BaoFinalUseHostError;
use crate::BaoPreparedConsumerCallback;
use crate::RegisteredBaoConsumer;

#[path = "consumer_owner.rs"]
mod consumer_owner;
#[path = "consumer_server.rs"]
mod consumer_server;
#[path = "consumer_transport.rs"]
mod consumer_transport;
#[path = "consumer_wire.rs"]
mod consumer_wire;

pub use consumer_server::CredentialConsumerServiceConfig;
pub use consumer_server::serve_credential_consumer;
pub(crate) use consumer_transport::PreparedConnection;
use consumer_wire::ConsumerIntent;
use consumer_wire::ConsumerRequest;
use consumer_wire::ConsumerResponse;

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum ConsumerPortError {
    #[error("invalid credential consumer configuration or operation")]
    Invalid,
    #[error("credential consumer unavailable; original operation remains unknown")]
    Unavailable,
    #[error("credential consumer rejected authentication")]
    Rejected,
    #[error("credential consumer original identity conflicts")]
    Conflict,
    #[error("credential consumer admission capacity exhausted")]
    Capacity,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ConsumerPortConfig {
    pub consumer_id: String,
    pub socket_path: PathBuf,
    pub service_uid: u32,
    pub acknowledgement_verifying_key: [u8; 32],
    pub credential_reference_sha256: [u8; 32],
    pub timeout_ms: u64,
}

impl std::fmt::Debug for ConsumerPortConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ConsumerPortConfig")
            .field("consumer_id", &self.consumer_id)
            .field("service_uid", &self.service_uid)
            .field("timeout_ms", &self.timeout_ms)
            .finish_non_exhaustive()
    }
}

/// Owns no consumer signing key or credential. The final callback receives the
/// already-verified KV secret only long enough to authenticate the original
/// operation to the separately enrolled consumer process.
pub struct ConsumerPortClient {
    config: ConsumerPortConfig,
    configuration_sha256: [u8; 32],
    operation_deadlines: Arc<Mutex<BTreeMap<String, Instant>>>,
}

/// In-flight admission only; dropping this guard never changes durable operation history.
pub struct OriginalOperationBudget {
    operation_id: String,
    deadlines: Arc<Mutex<BTreeMap<String, Instant>>>,
}

impl Drop for OriginalOperationBudget {
    fn drop(&mut self) {
        if let Ok(mut deadlines) = self.deadlines.lock() {
            deadlines.remove(&self.operation_id);
        }
    }
}

impl ConsumerPortClient {
    pub fn new(config: ConsumerPortConfig) -> Result<Self, ConsumerPortError> {
        ConsumerIntent {
            schema_version: 1,
            consumer_id: config.consumer_id.clone(),
            operation_id: "configuration-validation".into(),
            semantic_sha256: [1; 32],
        }
        .validate()?;
        let key = VerifyingKey::from_bytes(&config.acknowledgement_verifying_key)
            .map_err(|_| ConsumerPortError::Invalid)?;
        if key.is_weak()
            || !config.socket_path.is_absolute()
            || config.credential_reference_sha256 == [0; 32]
            || config.timeout_ms == 0
            || config.timeout_ms > 5_000
        {
            return Err(ConsumerPortError::Invalid);
        }
        let encoding = serde_json::to_vec(&(
            "hepta.secrets.credential-consumer.configuration.v1",
            &config,
        ))
        .map_err(|_| ConsumerPortError::Invalid)?;
        Ok(Self {
            config,
            configuration_sha256: Digest32::of_bytes(&encoding).into_array(),
            operation_deadlines: Arc::new(Mutex::new(BTreeMap::new())),
        })
    }

    pub fn configuration_sha256(&self) -> [u8; 32] {
        self.configuration_sha256
    }

    /// Supply a host-selected absolute deadline for an already durably owned
    /// original operation. This guard cannot authorize a read or replay.
    pub fn begin_original_operation(
        &self,
        operation_id: &str,
        deadline: Instant,
    ) -> Result<OriginalOperationBudget, ConsumerPortError> {
        self.intent(operation_id, [1; 32])?;
        if deadline <= Instant::now() {
            return Err(ConsumerPortError::Unavailable);
        }
        let mut deadlines = self
            .operation_deadlines
            .lock()
            .map_err(|_| ConsumerPortError::Unavailable)?;
        if deadlines.contains_key(operation_id) {
            return Err(ConsumerPortError::Conflict);
        }
        if deadlines.len() >= 4 {
            return Err(ConsumerPortError::Capacity);
        }
        deadlines.insert(operation_id.to_owned(), deadline);
        Ok(OriginalOperationBudget {
            operation_id: operation_id.to_owned(),
            deadlines: Arc::clone(&self.operation_deadlines),
        })
    }

    pub fn registration(self: &Arc<Self>) -> Result<RegisteredBaoConsumer, BaoFinalUseHostError> {
        let preparation = Arc::clone(self);
        let observation = Arc::clone(self);
        RegisteredBaoConsumer::for_prepared_operations(
            self.config.consumer_id.clone(),
            self.configuration_sha256,
            Arc::new(move |operation_id, semantic| {
                preparation.prepare(operation_id, semantic).map_err(|_| ())
            }),
            Arc::new(move |operation_id, semantic| {
                // A missing row or unavailable consumer never proves no effect.
                // Only the pinned independent signature confirms success.
                Ok(match observation.observe(operation_id, semantic) {
                    Ok(true) => BaoConsumerObservationV1::Succeeded,
                    Ok(false) | Err(_) => BaoConsumerObservationV1::Unknown,
                })
            }),
        )
    }

    fn prepare(
        &self,
        operation_id: &str,
        semantic: [u8; 32],
    ) -> Result<BaoPreparedConsumerCallback, ConsumerPortError> {
        let intent = self.intent(operation_id, semantic)?;
        let deadline = self
            .operation_deadlines
            .lock()
            .map_err(|_| ConsumerPortError::Unavailable)?
            .get(operation_id)
            .copied()
            .ok_or(ConsumerPortError::Unavailable)?;
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or(ConsumerPortError::Unavailable)?;
        let connection = PreparedConnection::connect(
            &self.config.socket_path,
            self.config.service_uid,
            remaining.min(Duration::from_millis(self.config.timeout_ms)),
        )?;
        let key = self.config.acknowledgement_verifying_key;
        let credential_digest = self.config.credential_reference_sha256;
        Ok(Box::new(move |credential| {
            if Digest32::of_bytes(credential).into_array() != credential_digest {
                return Err(());
            }
            let proof = intent.proof(credential).map_err(|_| ())?;
            match connection
                .exchange(&ConsumerRequest::Authenticate {
                    intent: intent.clone(),
                    proof,
                })
                .map_err(|_| ())?
            {
                ConsumerResponse::Confirmed { receipt } => {
                    receipt.verify(&intent, &key).map_err(|_| ())
                }
                ConsumerResponse::Unknown
                | ConsumerResponse::Rejected
                | ConsumerResponse::Conflict => Err(()),
            }
        }))
    }

    pub fn observe(
        &self,
        operation_id: &str,
        semantic: [u8; 32],
    ) -> Result<bool, ConsumerPortError> {
        let intent = self.intent(operation_id, semantic)?;
        let connection = PreparedConnection::connect(
            &self.config.socket_path,
            self.config.service_uid,
            Duration::from_millis(self.config.timeout_ms),
        )?;
        match connection.exchange(&ConsumerRequest::Status {
            intent: intent.clone(),
        })? {
            ConsumerResponse::Confirmed { receipt } => {
                receipt.verify(&intent, &self.config.acknowledgement_verifying_key)?;
                Ok(true)
            }
            ConsumerResponse::Unknown => Ok(false),
            ConsumerResponse::Rejected => Err(ConsumerPortError::Rejected),
            ConsumerResponse::Conflict => Err(ConsumerPortError::Conflict),
        }
    }

    fn intent(
        &self,
        operation_id: &str,
        semantic: [u8; 32],
    ) -> Result<ConsumerIntent, ConsumerPortError> {
        let intent = ConsumerIntent {
            schema_version: 1,
            consumer_id: self.config.consumer_id.clone(),
            operation_id: operation_id.to_owned(),
            semantic_sha256: semantic,
        };
        intent.validate()?;
        Ok(intent)
    }
}

#[cfg(test)]
#[path = "consumer_port_tests.rs"]
pub(crate) mod tests;
