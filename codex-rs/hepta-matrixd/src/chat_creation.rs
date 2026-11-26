//! Stable protected-chat V1 request projection into the original creation Owner.
use super::*;
use codex_hepta_contracts::Sha256Digest;
use native_wire::CreationObservation;

impl AgentChatSession {
    // Preserve V1 requested parameters across additive future creation profiles.
    // Defaults omitted from the request stay omitted; the original owner receipt
    // records the effective model and permissions chosen for this one creation.
    fn protected_creation_params_v1(&self, operation_id: &str) -> ThreadStartParams {
        ThreadStartParams {
            idempotency_key: Some(operation_id.into()),
            cwd: Some(self.workspace.as_path().to_string_lossy().into_owned()),
            runtime_workspace_roots: Some(vec![self.workspace.clone()]),
            project_id: Some(self.project_id.clone()),
            ephemeral: Some(false),
            history_mode: Some(ThreadHistoryMode::Paginated),
            thread_source: Some(ThreadSource::Feature(SOURCE.into())),
            ..Default::default()
        }
    }

    pub(super) async fn create_once(&self, operation_id: String) -> Result<ChatResult> {
        let response: ThreadStartResponse = self
            .transport
            .request(ClientRequest::ThreadStart {
                request_id: self.transport.request_id(),
                params: self.protected_creation_params_v1(&operation_id),
            })
            .await?;
        if !belongs_to_scope(&response.thread, &self.project_id, &self.workspace) {
            return Err(invalid(
                "original creation receipt is outside protected scope",
            ));
        }
        Ok(ChatResult::Creation {
            operation_id,
            data: conversation(response.thread),
        })
    }

    /// Explicit recovery repairs only this key's exact rollout index/receipt.
    /// It never issues another start, loads a Core, or sends a message.
    pub async fn reconcile_creation(&self, request: &ChatRequest) -> Result<CreationObservation> {
        self.settle_creation(request, /*abandon*/ false).await
    }

    /// An explicit user action may retire only the original reserved creation.
    pub async fn abandon_creation(&self, request: &ChatRequest) -> Result<CreationObservation> {
        self.settle_creation(request, /*abandon*/ true).await
    }

    async fn settle_creation(
        &self,
        request: &ChatRequest,
        abandon: bool,
    ) -> Result<CreationObservation> {
        request.validate().map_err(invalid)?;
        let ChatCommand::CreateOnce { operation_id } = &request.command else {
            return Err(invalid(
                "only identified original creations can be recovered",
            ));
        };
        let before = self.agentd.health().await?;
        if !before.ready || before.fenced || !self.connected.load(Ordering::Acquire) {
            return Err(invalid("current original Agent is not ready"));
        }
        let params = self.protected_creation_params_v1(operation_id);
        let digest = Sha256Digest::for_bytes(
            &params
                .canonical_creation_parameters()
                .map_err(|error| invalid(&error.to_string()))?,
        )
        .as_str()
        .to_owned();
        let scoped = ThreadCreationObserveParams {
            idempotency_key: operation_id.clone(),
            expected_parameters_sha256: digest.clone(),
            expected_project_id: Some(self.project_id.clone()),
            expected_cwd: self.workspace.clone(),
            expected_thread_source: Some(ThreadSource::Feature(SOURCE.into())),
        };
        let action = if abandon {
            ClientRequest::ThreadCreationAbandon {
                request_id: self.transport.request_id(),
                params: scoped,
            }
        } else {
            ClientRequest::ThreadCreationReconcile {
                request_id: self.transport.request_id(),
                params: scoped,
            }
        };
        let observed: ThreadCreationObserveResponse = self.transport.request(action).await?;
        if observed.idempotency_key != *operation_id || observed.parameters_sha256 != digest {
            return Err(invalid(
                "original creation key or complete parameter digest changed",
            ));
        }
        let outcome = match observed.outcome {
            ThreadCreationObserveOutcome::Created { response } => {
                if !belongs_to_scope(&response.thread, &self.project_id, &self.workspace) {
                    return Err(invalid(
                        "observed creation receipt is outside protected scope",
                    ));
                }
                CreationObservation::Created {
                    data: conversation(response.thread),
                }
            }
            ThreadCreationObserveOutcome::Pending { thread_id } => {
                CreationObservation::Pending { thread_id }
            }
            ThreadCreationObserveOutcome::Materialized { thread_id } => {
                CreationObservation::Materialized { thread_id }
            }
            ThreadCreationObserveOutcome::Deleted { thread_id } => {
                CreationObservation::Deleted { thread_id }
            }
            ThreadCreationObserveOutcome::Abandoned { thread_id } => {
                CreationObservation::Abandoned { thread_id }
            }
            ThreadCreationObserveOutcome::Missing => CreationObservation::Missing,
            ThreadCreationObserveOutcome::Unknown => CreationObservation::Unknown,
        };
        if abandon && !matches!(outcome, CreationObservation::Abandoned { .. }) {
            return Err(invalid(
                "original owner did not confirm creation abandonment",
            ));
        }
        let after = self.agentd.health().await?;
        if !after.ready || after.fenced || !self.connected.load(Ordering::Acquire) {
            return Err(invalid("original Agent changed during creation recovery"));
        }
        Ok(outcome)
    }
}
