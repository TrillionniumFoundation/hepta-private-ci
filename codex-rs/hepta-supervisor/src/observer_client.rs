//! Read-only client for the separately enrolled lifecycle observation socket.

use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use crate::SupervisorError;
use crate::robrix_protocol::MAX_ROBRIX_SUPERVISORD_RESPONSE_BYTES;
use crate::robrix_protocol::RobrixSupervisordMethod;
use crate::robrix_protocol::RobrixSupervisordPayload;
use crate::robrix_protocol::RobrixSupervisordRequest;
use crate::robrix_protocol::RobrixSupervisordResponse;

/// Observes a pinned kernel principal without acquiring lifecycle mutation authority.
pub struct SupervisorObserverClient {
    socket_path: PathBuf,
    owner_uid: u32,
    next_request_id: AtomicU64,
}

impl SupervisorObserverClient {
    pub fn new(socket_path: PathBuf, owner_uid: u32) -> Result<Self, SupervisorError> {
        if !socket_path.is_absolute() {
            return Err(SupervisorError::Invalid(
                "observer requires an absolute socket path".into(),
            ));
        }
        let random = uuid::Uuid::new_v4();
        let request_seed =
            u64::from_be_bytes(random.as_bytes()[..8].try_into().expect("UUID prefix"));
        Ok(Self {
            socket_path,
            owner_uid,
            next_request_id: AtomicU64::new(request_seed.max(1)),
        })
    }

    /// Every query has a fresh identifier and must return its exact requested projection.
    pub async fn query(
        &self,
        method: RobrixSupervisordMethod,
    ) -> Result<RobrixSupervisordPayload, SupervisorError> {
        let request_id = self
            .next_request_id
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |id| id.checked_add(1))
            .map_err(|_| SupervisorError::Invalid("observer request identity exhausted".into()))?;
        let request = RobrixSupervisordRequest::new(request_id, method);
        request
            .validate()
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        timeout(Duration::from_secs(2), self.exchange(request))
            .await
            .map_err(|_| {
                std::io::Error::new(std::io::ErrorKind::TimedOut, "observer query timed out")
            })?
    }

    async fn exchange(
        &self,
        request: RobrixSupervisordRequest,
    ) -> Result<RobrixSupervisordPayload, SupervisorError> {
        let mut stream = UnixStream::connect(&self.socket_path).await?;
        stream.ensure_peer_user(self.owner_uid)?;
        let mut bytes = serde_json::to_vec(&request)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        bytes.push(b'\n');
        stream.write_all(&bytes).await?;
        stream.shutdown().await?;
        let mut reader = BufReader::new(stream).take(MAX_ROBRIX_SUPERVISORD_RESPONSE_BYTES + 1);
        let mut frame = Vec::new();
        let count = reader.read_until(b'\n', &mut frame).await?;
        if count == 0
            || count as u64 > MAX_ROBRIX_SUPERVISORD_RESPONSE_BYTES
            || !frame.ends_with(b"\n")
        {
            return Err(SupervisorError::Invalid(
                "observer response is incomplete or oversized".into(),
            ));
        }
        let response: RobrixSupervisordResponse = serde_json::from_slice(&frame)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        response
            .validate(request.request_id)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let matches_request = match (&request.method, &response.payload) {
            (RobrixSupervisordMethod::Health, RobrixSupervisordPayload::Health(_)) => true,
            (
                RobrixSupervisordMethod::Roster { limit },
                RobrixSupervisordPayload::Roster { agents },
            ) => agents.len() <= usize::from(*limit),
            (
                RobrixSupervisordMethod::Snapshot { agent_id },
                RobrixSupervisordPayload::Agent(agent),
            ) => agent_id == &agent.agent_id,
            (_, RobrixSupervisordPayload::Error { .. }) => true,
            _ => false,
        };
        if !matches_request {
            return Err(SupervisorError::Invalid(
                "observer returned another query's projection".into(),
            ));
        }
        Ok(response.payload)
    }
}
