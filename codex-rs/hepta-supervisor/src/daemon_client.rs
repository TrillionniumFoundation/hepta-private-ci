use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use crate::DurableMutationStatusV1;
use crate::DurableReleaseTransaction;
use crate::H7H89ProductionGrant;
use crate::ProductionMutationState;
use crate::ProductionRecoveryDecision;
use crate::SupervisorError;
use crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use crate::daemon_protocol::SupervisordAgentStatus;
use crate::daemon_protocol::SupervisordControlFence;
use crate::daemon_protocol::SupervisordHealth;
use crate::daemon_protocol::SupervisordMethod;
use crate::daemon_protocol::SupervisordMutationAccepted;
use crate::daemon_protocol::SupervisordPayload;
use crate::daemon_protocol::SupervisordRequest;
use crate::daemon_protocol::SupervisordResponse;

pub struct SupervisordClient {
    socket_path: PathBuf,
    next_request_id: AtomicU64,
    timeout: Duration,
}

impl SupervisordClient {
    pub fn new(socket_path: PathBuf) -> Result<Self, SupervisorError> {
        if !socket_path.is_absolute() {
            return Err(SupervisorError::Invalid(
                "supervisord client requires an absolute socket path".to_string(),
            ));
        }
        Ok(Self {
            socket_path,
            next_request_id: AtomicU64::new(random_request_seed()),
            timeout: Duration::from_secs(2),
        })
    }

    /// Read one selected module from the existing durable Supervisor owner.
    pub async fn runtime_module_selection(
        &self,
        module_id: String,
    ) -> Result<codex_hepta_agent_protocol::RuntimeModuleSelectionV1, SupervisorError> {
        codex_hepta_agent_protocol::validate_runtime_module_id(&module_id)
            .map_err(SupervisorError::Invalid)?;
        match self
            .send(SupervisordMethod::RuntimeModuleSelection {
                module_id: module_id.clone(),
            })
            .await?
        {
            SupervisordPayload::RuntimeModuleSelection { selection } => {
                selection.validate().map_err(SupervisorError::Invalid)?;
                if selection.module_id != module_id {
                    return Err(SupervisorError::Invalid(
                        "runtime module response identity mismatch".to_string(),
                    ));
                }
                Ok(selection)
            }
            payload => unexpected(payload),
        }
    }

    pub fn reserve_request_id(&self) -> u64 {
        loop {
            let candidate = self.next_request_id.fetch_add(1, Ordering::Relaxed);
            if candidate != 0 {
                return candidate;
            }
        }
    }

    pub async fn execute_mutation_with_request_id(
        &self,
        request_id: u64,
        method: SupervisordMethod,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        if request_id == 0 {
            return Err(SupervisorError::Invalid(
                "ordinary mutation request identity must be non-zero".to_string(),
            ));
        }
        if !matches!(
            &method,
            SupervisordMethod::Start { .. }
                | SupervisordMethod::Drain { .. }
                | SupervisordMethod::Stop { .. }
                | SupervisordMethod::Kill { .. }
                | SupervisordMethod::Restart { .. }
                | SupervisordMethod::Upgrade { .. }
                | SupervisordMethod::Rollback { .. }
        ) {
            return Err(SupervisorError::Invalid(
                "execute_mutation_with_request_id requires an ordinary lifecycle mutation"
                    .to_string(),
            ));
        }
        self.mutation_with_request_id(request_id, method).await
    }

    pub async fn ordinary_mutation_status(
        &self,
        agent_id: AgentId,
        mutation_request_id: u64,
    ) -> Result<Option<DurableMutationStatusV1>, SupervisorError> {
        match self
            .send(SupervisordMethod::OrdinaryMutationStatus {
                agent_id,
                mutation_request_id,
            })
            .await?
        {
            SupervisordPayload::OrdinaryMutationStatus { status } => Ok(status),
            payload => unexpected(payload),
        }
    }

    pub async fn reconcile_ordinary_mutation(
        &self,
        fence: SupervisordControlFence,
        mutation_request_id: u64,
    ) -> Result<Option<DurableMutationStatusV1>, SupervisorError> {
        match self
            .send(SupervisordMethod::ReconcileOrdinaryMutation {
                fence,
                mutation_request_id,
            })
            .await?
        {
            SupervisordPayload::OrdinaryMutationStatus { status } => Ok(status),
            payload => unexpected(payload),
        }
    }

    pub async fn health(&self) -> Result<SupervisordHealth, SupervisorError> {
        match self.send(SupervisordMethod::Health).await? {
            SupervisordPayload::Health(health) => Ok(health),
            payload => unexpected(payload),
        }
    }

    pub async fn roster(&self, limit: u16) -> Result<Vec<SupervisordAgentStatus>, SupervisorError> {
        match self.send(SupervisordMethod::Roster { limit }).await? {
            SupervisordPayload::Roster { agents } => Ok(agents),
            payload => unexpected(payload),
        }
    }

    pub async fn snapshot(
        &self,
        agent_id: AgentId,
    ) -> Result<SupervisordAgentStatus, SupervisorError> {
        self.agent(SupervisordMethod::Snapshot { agent_id }).await
    }

    pub async fn release_selection(
        &self,
        agent_id: AgentId,
    ) -> Result<Option<DurableReleaseTransaction>, SupervisorError> {
        match self
            .send(SupervisordMethod::ReleaseSelection { agent_id })
            .await?
        {
            SupervisordPayload::ReleaseSelection { selection } => Ok(selection),
            payload => unexpected(payload),
        }
    }

    pub async fn production_mutation_status(
        &self,
        agent_id: AgentId,
    ) -> Result<Option<ProductionMutationState>, SupervisorError> {
        match self
            .send(SupervisordMethod::ProductionMutationStatus { agent_id })
            .await?
        {
            SupervisordPayload::ProductionMutationStatus { state } => Ok(state),
            payload => unexpected(payload),
        }
    }

    pub async fn resolve_production_recovery(
        &self,
        fence: SupervisordControlFence,
        decision: ProductionRecoveryDecision,
    ) -> Result<ProductionMutationState, SupervisorError> {
        match self
            .send(SupervisordMethod::ResolveProductionRecovery { fence, decision })
            .await?
        {
            SupervisordPayload::ProductionMutationStatus { state: Some(state) } => Ok(state),
            payload => unexpected(payload),
        }
    }

    pub async fn start(
        &self,
        fence: SupervisordControlFence,
        release_id: ReleaseId,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Start { fence, release_id })
            .await
    }

    pub async fn drain(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Drain { fence }).await
    }

    pub async fn stop(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Stop { fence }).await
    }

    pub async fn kill(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Kill { fence }).await
    }

    pub async fn restart(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Restart { fence }).await
    }

    pub async fn upgrade(
        &self,
        fence: SupervisordControlFence,
        release_id: ReleaseId,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Upgrade { fence, release_id })
            .await
    }

    pub async fn rollback(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Rollback { fence }).await
    }

    pub async fn signed_upgrade(
        &self,
        fence: SupervisordControlFence,
        grant: H7H89ProductionGrant,
        h7_envelope: H7SignedArtifactEnvelope,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::SignedUpgrade {
            fence,
            grant,
            h7_envelope,
        })
        .await
    }

    pub async fn signed_rollback(
        &self,
        fence: SupervisordControlFence,
        grant: H7H89ProductionGrant,
        h7_envelope: H7SignedArtifactEnvelope,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::SignedRollback {
            fence,
            grant,
            h7_envelope,
        })
        .await
    }

    async fn agent(
        &self,
        method: SupervisordMethod,
    ) -> Result<SupervisordAgentStatus, SupervisorError> {
        match self.send(method).await? {
            SupervisordPayload::Agent(status) => Ok(status),
            payload => unexpected(payload),
        }
    }

    async fn mutation(
        &self,
        method: SupervisordMethod,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        let request_id = self.reserve_request_id();
        self.mutation_with_request_id(request_id, method).await
    }

    async fn mutation_with_request_id(
        &self,
        request_id: u64,
        method: SupervisordMethod,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        match self.send_with_request_id(request_id, method).await? {
            SupervisordPayload::MutationAccepted {
                operation,
                accepted_state_digest,
                agent,
                production_receipt,
            } => Ok(SupervisordMutationAccepted {
                operation,
                accepted_state_digest,
                agent,
                production_receipt,
            }),
            payload => unexpected(payload),
        }
    }

    async fn send(&self, method: SupervisordMethod) -> Result<SupervisordPayload, SupervisorError> {
        let request_id = self.reserve_request_id();
        self.send_with_request_id(request_id, method).await
    }

    async fn send_with_request_id(
        &self,
        request_id: u64,
        method: SupervisordMethod,
    ) -> Result<SupervisordPayload, SupervisorError> {
        let request = SupervisordRequest::new(request_id, method);
        request
            .validate()
            .map_err(|_| SupervisorError::Invalid("invalid supervisord request".to_string()))?;
        let stream = timeout(self.timeout, UnixStream::connect(&self.socket_path))
            .await
            .map_err(|_| SupervisorError::Invalid("supervisord connect timed out".to_string()))??;
        let (reader, mut writer) = tokio::io::split(stream);
        let mut bytes = serde_json::to_vec(&request)
            .map_err(|error| SupervisorError::Invalid(format!("encode request: {error}")))?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES {
            return Err(SupervisorError::Invalid(
                "supervisord request exceeded frame bound".to_string(),
            ));
        }
        timeout(self.timeout, writer.write_all(&bytes))
            .await
            .map_err(|_| SupervisorError::Invalid("supervisord write timed out".to_string()))??;
        writer.shutdown().await?;
        let mut reader = BufReader::new(reader).take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1);
        let mut response_bytes = Vec::new();
        let count = timeout(self.timeout, reader.read_until(b'\n', &mut response_bytes))
            .await
            .map_err(|_| SupervisorError::Invalid("supervisord read timed out".to_string()))??;
        if count == 0
            || count as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES
            || !response_bytes.ends_with(b"\n")
        {
            return Err(SupervisorError::Invalid(
                "supervisord returned an invalid bounded response".to_string(),
            ));
        }
        let response: SupervisordResponse = serde_json::from_slice(&response_bytes)
            .map_err(|error| SupervisorError::Invalid(format!("decode response: {error}")))?;
        if response.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION
            || response.request_id != request_id
        {
            return Err(SupervisorError::Invalid(
                "supervisord response identity does not match request".to_string(),
            ));
        }
        match response.payload {
            SupervisordPayload::Error {
                code,
                message,
                actual: _,
            } => Err(SupervisorError::Invalid(format!(
                "supervisord rejected request ({code}): {message}"
            ))),
            payload => Ok(payload),
        }
    }
}

fn random_request_seed() -> u64 {
    let bytes = *uuid::Uuid::new_v4().as_bytes();
    let seed = u64::from_be_bytes(
        bytes[..8]
            .try_into()
            .expect("UUID prefix is exactly eight bytes"),
    );
    seed.max(1)
}

fn unexpected<T>(payload: SupervisordPayload) -> Result<T, SupervisorError> {
    Err(SupervisorError::Invalid(format!(
        "supervisord returned unexpected payload {payload:?}"
    )))
}
