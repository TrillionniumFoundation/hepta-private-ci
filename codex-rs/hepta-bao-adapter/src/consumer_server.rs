//! Production port for an independently owned, durable credential consumer.

use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use zeroize::Zeroizing;

use super::ConsumerPortError;
use super::consumer_owner::CredentialConsumerOwner;
use super::consumer_wire::ConsumerRequest;
use super::consumer_wire::ConsumerResponse;
use crate::local_endpoint::BoundSocket;
use crate::private_files::read_private;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialConsumerServiceConfig {
    pub schema_version: u32,
    pub consumer_id: String,
    pub socket_path: PathBuf,
    pub ipc_group_gid: u32,
    pub allowed_caller_uid: u32,
    pub database_path: PathBuf,
    pub credential_file: PathBuf,
    pub credential_sha256: [u8; 32],
    pub acknowledgement_signing_key_file: PathBuf,
    pub acknowledgement_verifying_key: [u8; 32],
    pub request_timeout_ms: u64,
    pub shutdown_drain_ms: u64,
}

impl CredentialConsumerServiceConfig {
    /// Enroll only from Root-owned policy; private keys stay role-owned.
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        crate::private_files::read_root_configuration(path)
    }
}

pub async fn serve_credential_consumer(
    config: CredentialConsumerServiceConfig,
    shutdown: impl Future<Output = ()>,
) -> Result<(), ConsumerPortError> {
    if config.schema_version != 1
        || config.request_timeout_ms == 0
        || config.request_timeout_ms > 5_000
        || config.shutdown_drain_ms < config.request_timeout_ms
        || config.shutdown_drain_ms > 10_000
    {
        return Err(ConsumerPortError::Invalid);
    }
    super::consumer_wire::ConsumerIntent {
        schema_version: 1,
        consumer_id: config.consumer_id.clone(),
        operation_id: "service-configuration".into(),
        semantic_sha256: [1; 32],
    }
    .validate()?;
    let credential = read_private(&config.credential_file, 8192)?;
    if credential.is_empty()
        || Digest32::of_bytes(&credential).into_array() != config.credential_sha256
    {
        return Err(ConsumerPortError::Invalid);
    }
    let signing_bytes = read_private(&config.acknowledgement_signing_key_file, 32)?;
    let signing_bytes: &[u8; 32] = signing_bytes
        .as_slice()
        .try_into()
        .map_err(|_| ConsumerPortError::Invalid)?;
    let key = SigningKey::from_bytes(signing_bytes);
    if key.verifying_key().to_bytes() != config.acknowledgement_verifying_key {
        return Err(ConsumerPortError::Invalid);
    }
    // Own the stable endpoint lock before any database access. A second
    // service cannot migrate or observe the live writer's owner first.
    let endpoint = BoundSocket::bind(&config.socket_path, config.ipc_group_gid)?;
    let owner = Arc::new(
        CredentialConsumerOwner::open(&config.database_path, config.acknowledgement_verifying_key)
            .await?,
    );
    let service = crate::local_service::LocalServiceConfig {
        socket_path: config.socket_path.clone(),
        ipc_group_gid: config.ipc_group_gid,
        service_uid: rustix::process::geteuid().as_raw(),
        allowed_peer_uids: vec![config.allowed_caller_uid],
        request_timeout_ms: config.request_timeout_ms,
        shutdown_drain_ms: config.shutdown_drain_ms,
    };
    let role = Arc::new(CredentialConsumerRole {
        config,
        owner,
        credential,
        key,
    });
    crate::local_service::serve(service, role, endpoint, shutdown).await
}

struct CredentialConsumerRole {
    config: CredentialConsumerServiceConfig,
    owner: Arc<CredentialConsumerOwner>,
    credential: Zeroizing<Vec<u8>>,
    key: SigningKey,
}

impl crate::local_service::LocalServiceOwner for CredentialConsumerRole {
    async fn handle(&self, _peer_uid: u32, request: &[u8]) -> Result<Vec<u8>, ConsumerPortError> {
        let request: ConsumerRequest = serde_json::from_slice(request).map_err(unavailable)?;
        let response = match request {
            ConsumerRequest::Authenticate { intent, proof } => {
                if intent.consumer_id != self.config.consumer_id {
                    return Err(ConsumerPortError::Rejected);
                }
                match self
                    .owner
                    .authenticate(&intent, &self.credential, &proof, &self.key)
                    .await
                {
                    Ok(receipt) => ConsumerResponse::Confirmed { receipt },
                    Err(ConsumerPortError::Conflict) => ConsumerResponse::Conflict,
                    Err(ConsumerPortError::Rejected) => ConsumerResponse::Rejected,
                    Err(_) => ConsumerResponse::Unknown,
                }
            }
            ConsumerRequest::Status { intent } => {
                if intent.consumer_id != self.config.consumer_id {
                    return Err(ConsumerPortError::Rejected);
                }
                match self.owner.status(&intent).await {
                    Ok(Some(receipt)) => ConsumerResponse::Confirmed { receipt },
                    Ok(None) => ConsumerResponse::Unknown,
                    Err(ConsumerPortError::Conflict) => ConsumerResponse::Conflict,
                    Err(_) => ConsumerResponse::Unknown,
                }
            }
        };
        serde_json::to_vec(&response).map_err(unavailable)
    }
    fn fence_unknown(&self) {
        self.owner.fence_writer();
    }
    async fn close(&self) {
        self.owner.close().await;
    }
}

fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
