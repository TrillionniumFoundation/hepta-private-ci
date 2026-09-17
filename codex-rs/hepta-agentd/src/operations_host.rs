use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AUTOMATION_OPERATION_DESTINATION;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTask;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::automation_task_operation_intent;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_operations::DispatchEffect;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_operations::ReconciliationOutcome;
use codex_hepta_operations::ReconciliationReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

const OWNER_QUEUE_CAPACITY: usize = 32;
const CLAIM_LEASE: Duration = Duration::from_secs(30);
const QUEUE_RETRY: Duration = Duration::from_millis(50);
const DISPATCH_DOMAIN: &[u8] = b"hepta.agentd.automation-owner-queue-dispatch.v1\0";
const ACK_DOMAIN: &[u8] = b"hepta.agentd.automation-owner-queue-ack.v1\0";
const NOT_APPLIED_DOMAIN: &[u8] = b"hepta.agentd.automation-owner-queue-not-applied.v1\0";
const QUARANTINE_DOMAIN: &[u8] = b"hepta.agentd.automation-owner-queue-quarantined.v1\0";

/// Independent grant source. Implementations may talk to an external issuer or
/// consume an already authenticated owner channel, but agentd never receives a
/// signing key and never self-mints the grant it consumes.
pub trait AutomationGrantProvider: Send + Sync {
    fn signed_grant(
        &self,
        intent: &OperationIntentV1,
    ) -> Result<SignedFinalUseGrant, AgentdOperationsError>;
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdOperationsError {
    #[error("automation final-use grant unavailable: {0}")]
    Grant(String),
    #[error("durable operation failure: {0}")]
    Operation(#[from] DurableOperationError),
    #[error("automation destination failure: {0}")]
    Automation(#[from] AutomationError),
    #[error("automation owner queue unavailable")]
    QueueUnavailable,
    #[error("automation owner queue response dropped")]
    ResponseDropped,
    #[error("durable operation is not claimable")]
    NotClaimable,
}

#[derive(Clone)]
pub struct AgentdOperationsHost {
    source: DurableOperationStore,
    automation: AutomationStore,
    authority: FinalUseAuthority,
    grants: Arc<dyn AutomationGrantProvider>,
    sender: mpsc::Sender<AutomationApplyRequest>,
    generation: Generation,
    worker_id: StableId,
    observer_id: StableId,
}

struct AutomationApplyRequest {
    operation: OperationIntentV1,
    draft: AutomationTaskDraft,
    response: oneshot::Sender<Result<AutomationTask, AgentdOperationsError>>,
}

impl AgentdOperationsHost {
    pub async fn open(
        path: &Path,
        automation: AutomationStore,
        authority: FinalUseAuthority,
        grants: Arc<dyn AutomationGrantProvider>,
        generation: Generation,
    ) -> Result<Self, AgentdOperationsError> {
        let source = DurableOperationStore::open(path).await?;
        let worker_id = StableId::new("agentd:automation-owner-queue")
            .map_err(|error| AgentdOperationsError::Grant(error.to_string()))?;
        let observer_id = StableId::new("agentd:automation-terminal-observer")
            .map_err(|error| AgentdOperationsError::Grant(error.to_string()))?;
        reconcile_reopened_operations(&source, &automation, &observer_id, generation).await?;
        let (sender, receiver) = mpsc::channel(OWNER_QUEUE_CAPACITY);
        tokio::spawn(run_destination_worker(
            source.clone(),
            automation.clone(),
            observer_id.clone(),
            generation,
            receiver,
        ));
        Ok(Self {
            source,
            automation,
            authority,
            grants,
            sender,
            generation,
            worker_id,
            observer_id,
        })
    }

    pub fn source_store(&self) -> &DurableOperationStore {
        &self.source
    }

    pub fn generation(&self) -> Generation {
        self.generation
    }

    pub async fn create_automation_task(
        &self,
        draft: AutomationTaskDraft,
    ) -> Result<AutomationTask, AgentdOperationsError> {
        let intent = automation_task_operation_intent(
            self.automation.owner_agent_id(),
            &draft,
            self.generation,
        )?;
        self.source.prepare_intent(&intent).await?;

        if let Some(receipt) = self.automation.observe_task_operation(&intent).await? {
            self.source
                .reconcile_destination_receipt(
                    &receipt,
                    self.observer_id.clone(),
                    self.generation,
                )
                .await?;
            return self
                .automation
                .task(draft.task_id)
                .await?
                .ok_or(AgentdOperationsError::ResponseDropped);
        }

        let signed = self.grants.signed_grant(&intent)?;
        let claim = self
            .source
            .claim_operation(
                &intent.scope_id,
                &intent.operation_id,
                &self.worker_id,
                self.generation,
                CLAIM_LEASE,
            )
            .await?
            .ok_or(AgentdOperationsError::NotClaimable)?;
        let authorized = self
            .source
            .authorize_dispatch(&self.authority, &signed, &claim)
            .await?;
        let (response_tx, response_rx) = oneshot::channel();
        let request = AutomationApplyRequest {
            operation: intent.clone(),
            draft,
            response: response_tx,
        };
        let sender = self.sender.clone();
        let dispatch_digest = queue_digest(DISPATCH_DOMAIN, &intent, claim.fence);
        let acknowledgement_digest = queue_digest(ACK_DOMAIN, &intent, claim.fence);
        self.source
            .execute_authorized(authorized, move |_| match sender.try_send(request) {
                Ok(()) => DispatchEffect::Dispatched {
                    value: (),
                    dispatch_digest,
                    acknowledgement_digest: Some(acknowledgement_digest),
                },
                Err(mpsc::error::TrySendError::Full(_)) => DispatchEffect::NotDispatched {
                    value: (),
                    reason_digest: Digest32::of_bytes(b"hepta.agentd.automation-owner-queue-full.v1\0"),
                    retry_after: QUEUE_RETRY,
                },
                Err(mpsc::error::TrySendError::Closed(_)) => DispatchEffect::NotDispatched {
                    value: (),
                    reason_digest: Digest32::of_bytes(b"hepta.agentd.automation-owner-queue-closed.v1\0"),
                    retry_after: QUEUE_RETRY,
                },
            })
            .await?;
        response_rx
            .await
            .map_err(|_| AgentdOperationsError::ResponseDropped)?
    }
}

async fn run_destination_worker(
    source: DurableOperationStore,
    automation: AutomationStore,
    observer_id: StableId,
    generation: Generation,
    mut receiver: mpsc::Receiver<AutomationApplyRequest>,
) {
    while let Some(request) = receiver.recv().await {
        let result = apply_and_reconcile(
            &source,
            &automation,
            &observer_id,
            generation,
            &request.operation,
            &request.draft,
        )
        .await;
        let _ = request.response.send(result);
    }
}

async fn apply_and_reconcile(
    source: &DurableOperationStore,
    automation: &AutomationStore,
    observer_id: &StableId,
    generation: Generation,
    operation: &OperationIntentV1,
    draft: &AutomationTaskDraft,
) -> Result<AutomationTask, AgentdOperationsError> {
    match automation.create_task_from_operation(operation, draft).await {
        Ok(receipt) => {
            source
                .reconcile_destination_receipt(
                    &receipt.destination_receipt,
                    observer_id.clone(),
                    generation,
                )
                .await?;
            Ok(receipt.task)
        }
        Err(error) => {
            match automation.observe_task_operation(operation).await {
                Ok(Some(receipt)) => {
                    source
                        .reconcile_destination_receipt(
                            &receipt,
                            observer_id.clone(),
                            generation,
                        )
                        .await?;
                    if let Some(task_id) = task_id_from_operation(operation) {
                        if let Some(task) = automation.task(task_id).await? {
                            return Ok(task);
                        }
                    }
                }
                Ok(None) => {
                    let outcome = if matches!(
                        error,
                        AutomationError::Invalid
                            | AutomationError::AccessDenied
                            | AutomationError::Conflict
                            | AutomationError::Corrupt
                    ) {
                        ReconciliationOutcome::Quarantined
                    } else {
                        ReconciliationOutcome::NotApplied
                    };
                    let evidence_digest = match outcome {
                        ReconciliationOutcome::Quarantined => {
                            Digest32::of_bytes(QUARANTINE_DOMAIN)
                        }
                        ReconciliationOutcome::NotApplied => {
                            Digest32::of_bytes(NOT_APPLIED_DOMAIN)
                        }
                        ReconciliationOutcome::Applied => unreachable!(),
                    };
                    source
                        .observe_terminal(
                            &operation.scope_id,
                            &operation.operation_id,
                            &ReconciliationReceiptV1 {
                                outcome,
                                evidence_digest,
                                observer_id: observer_id.clone(),
                                observer_generation: generation,
                            },
                        )
                        .await?;
                }
                Err(_) => {
                    // Observation itself is unavailable. Leave the source row
                    // dispatched so the durable reopen reconciler can retry.
                }
            }
            Err(error.into())
        }
    }
}

async fn reconcile_reopened_operations(
    source: &DurableOperationStore,
    automation: &AutomationStore,
    observer_id: &StableId,
    generation: Generation,
) -> Result<(), AgentdOperationsError> {
    let destination = StableId::new(AUTOMATION_OPERATION_DESTINATION)
        .map_err(|error| AgentdOperationsError::Grant(error.to_string()))?;
    loop {
        let unsettled = source.unsettled_operations(&destination, 256).await?;
        if unsettled.is_empty() {
            return Ok(());
        }
        for record in &unsettled {
            match automation.observe_task_operation(&record.intent).await? {
                Some(receipt) => {
                    source
                        .reconcile_destination_receipt(
                            &receipt,
                            observer_id.clone(),
                            generation,
                        )
                        .await?;
                }
                None => {
                    source
                        .observe_terminal(
                            &record.intent.scope_id,
                            &record.intent.operation_id,
                            &ReconciliationReceiptV1 {
                                outcome: ReconciliationOutcome::NotApplied,
                                evidence_digest: Digest32::of_bytes(NOT_APPLIED_DOMAIN),
                                observer_id: observer_id.clone(),
                                observer_generation: generation,
                            },
                        )
                        .await?;
                }
            }
        }
        if unsettled.len() < 256 {
            return Ok(());
        }
    }
}

fn queue_digest(domain: &[u8], intent: &OperationIntentV1, fence: u64) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(intent.semantic_digest().as_array());
    bytes.extend_from_slice(&fence.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn task_id_from_operation(
    operation: &OperationIntentV1,
) -> Option<codex_hepta_automation::AutomationTaskId> {
    let value = operation.operation_id.as_str();
    let raw = value.strip_prefix("automation.task.create:")?;
    raw.parse().ok()
}
