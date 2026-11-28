//! Preparation on the original required turn owner and writer journal.
//! The existing preparation API remains read-only. Explicit training uses a
//! private continuation and a separately installed fixed Root material owner;
//! no FinalUse or public dispatch receipt leaves either API.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::PairedLearningDataUse;
use crate::PairedTurnRequest;
use crate::VerifiedPairedTurn;
use crate::notes_literal_adapter::invalid;
use crate::text_session::AgentdTextSessionConfig;

#[path = "paired_preparation_continuation.rs"]
mod continuation;
use continuation::FreshJournalPreparation;
pub(crate) use continuation::OriginalPairedContinuation;
pub(crate) use continuation::PreparedOriginal;

#[path = "paired_material_client.rs"]
mod material_client;
#[cfg(target_os = "linux")]
#[path = "paired_material_protocol.rs"]
pub(crate) mod material_protocol;
pub use material_client::AgentdPairedMaterialClient;
pub use material_client::PairedRecordIdentityV1;
pub use material_client::PairedRecordMetadataV1;
pub use material_client::PairedRecordPinsV1;
pub use material_client::PairedTrainingMaterials;
pub use material_client::PairedTrainingReadResult;
pub use material_client::identify_original_paired_records_v1;
#[path = "paired_training.rs"]
pub(crate) mod training;
pub use training::AgentdPairedTraining;

#[path = "paired_training_plan.rs"]
mod plan;
pub use plan::PairedTrainingPlanV1;

pub(crate) const DESTINATION: &str = "paired.learning.material.v1";
const TOPIC: &str = "hepta.paired-learning.prepare.v1";
const DEADLINE: Duration = Duration::from_secs(10);

/// Frozen metadata supplied by trusted composition. It is not enrollment
/// proof, material custody, a Root policy registration or permission to read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PairedPreparationRegistration {
    pub study: Digest32,
    pub enrollment: Digest32,
    pub frozen_materials: Digest32,
    pub principal_id: String,
    pub policy_generation: Generation,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PairedPreparationRequest {
    pub original: PairedTurnRequest,
    pub operation: Digest32,
    pub materials: Digest32,
}

impl PairedPreparationRequest {
    fn identity(&self, registration: &PairedPreparationRegistration) -> Result<Value, AgentdError> {
        self.original.validate()?;
        if [
            registration.study,
            registration.enrollment,
            registration.frozen_materials,
            self.operation,
            self.materials,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || self.original.study != registration.study
            || self.original.expected_principal != registration.principal_id
            || self.materials != registration.frozen_materials
        {
            return Err(invalid(
                "paired preparation differs from frozen registration",
            ));
        }
        match self.original.usage {
            PairedLearningDataUse::RequestConsumerRun { operation, .. }
            | PairedLearningDataUse::ReportConsumerOutcome { operation, .. }
                if operation != self.operation =>
            {
                return Err(invalid(
                    "paired preparation operation differs from original use",
                ));
            }
            PairedLearningDataUse::TrainOnFailureAndCorrection { .. }
            | PairedLearningDataUse::EvaluateOnlyAfterFreeze { .. }
            | PairedLearningDataUse::RequestConsumerRun { .. }
            | PairedLearningDataUse::ReportConsumerOutcome { .. } => {}
        }
        Ok(json!({
            "study": registration.study.to_string(),
            "enrollment": registration.enrollment.to_string(),
            "materials": self.materials.to_string(),
            "principal": registration.principal_id,
            "policy_generation": registration.policy_generation.get(),
            "operation": self.operation.to_string(),
            "delivery": self.original.delivery_id.to_string(),
            "turn": self.original.turn_id,
            "purpose_statement": self.original.usage.consent_text(self.original.study),
        }))
    }
}

/// Historical journal metadata only; deliberately contains no queued receipt,
/// original-turn token, grant, material bytes or executable continuation.
#[derive(Debug, PartialEq, Eq)]
pub struct PairedPreparationObservation {
    pub operation_id: String,
    pub payload_sha256: Digest32,
    pub semantic_sha256: Digest32,
    pub state: LocalOutcomeState,
}

#[derive(Debug, PartialEq, Eq)]
pub enum PairedPreparationResponse {
    FreshPrepared(PairedPreparationObservation),
    RetainedReadOnly(PairedPreparationObservation),
    Unknown { operation_id: String },
}

/// Bounded handle to the existing required owner. It cannot open/reopen a
/// writer, install a destination, or outlive that owner's request receiver.
pub struct AgentdPairedPreparation {
    sender: mpsc::Sender<PendingPreparation>,
    registration: PairedPreparationRegistration,
}

impl AgentdPairedPreparation {
    pub async fn prepare(
        &self,
        request: PairedPreparationRequest,
    ) -> Result<PairedPreparationResponse, AgentdError> {
        request.identity(&self.registration)?;
        let operation_id = operation_id(request.original.delivery_id);
        let deadline = Instant::now() + DEADLINE;
        let (reply, response) = oneshot::channel();
        self.sender
            .try_send(PendingPreparation {
                request,
                deadline,
                reply,
                preparing: Arc::new(AtomicBool::new(false)),
            })
            .map_err(|_| invalid("original paired preparation owner is closed or occupied"))?;
        match tokio::time::timeout_at(deadline, response).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) | Err(_) => Ok(PairedPreparationResponse::Unknown { operation_id }),
        }
    }
}

pub(crate) struct PreparationLane {
    pub(crate) receiver: mpsc::Receiver<PendingPreparation>,
    pub(crate) journal: PreparationJournal,
}

pub(crate) fn channel(
    writer: Arc<ProductionDurableWriter>,
    registration: PairedPreparationRegistration,
    route: AgentdTextSessionConfig,
) -> Result<(AgentdPairedPreparation, PreparationLane), AgentdError> {
    if [
        registration.study,
        registration.enrollment,
        registration.frozen_materials,
    ]
    .into_iter()
    .any(Digest32::is_zero)
        || registration.principal_id.is_empty()
        || registration.principal_id.len() > 128
        || !registration
            .principal_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
        || writer.owner_agent_id() != &route.agent_id
    {
        return Err(invalid(
            "paired preparation requires original owner and frozen metadata",
        ));
    }
    let (sender, receiver) = mpsc::channel(1);
    Ok((
        AgentdPairedPreparation {
            sender,
            registration: registration.clone(),
        },
        PreparationLane {
            receiver,
            journal: PreparationJournal {
                writer,
                registration,
                route,
            },
        },
    ))
}

pub(crate) struct PendingPreparation {
    pub(crate) request: PairedPreparationRequest,
    pub(crate) deadline: Instant,
    pub(crate) reply: oneshot::Sender<Result<PairedPreparationResponse, AgentdError>>,
    pub(crate) preparing: Arc<AtomicBool>,
}

impl PendingPreparation {
    pub(crate) async fn complete_on_owner(
        mut self,
        cancellation: &CancellationToken,
        preparation: impl std::future::Future<Output = Result<PairedPreparationResponse, AgentdError>>,
    ) {
        if self.reply.is_closed() {
            return;
        }
        let result = if cancellation.is_cancelled() || Instant::now() >= self.deadline {
            Err(invalid(
                "original paired preparation owner ended or deadline elapsed",
            ))
        } else {
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => Err(invalid("original paired preparation owner ended")),
                _ = self.reply.closed() => return,
                result = tokio::time::timeout_at(self.deadline, preparation) => {
                    result.unwrap_or_else(|_| Err(invalid("original paired preparation deadline elapsed")))
                }
            }
        };
        let result = if cancellation.is_cancelled() || Instant::now() >= self.deadline {
            Err(invalid(
                "original paired preparation owner ended or deadline elapsed",
            ))
        } else {
            result
        };
        let result = if result.is_err() && self.preparing.load(Ordering::SeqCst) {
            Ok(PairedPreparationResponse::Unknown {
                operation_id: operation_id(self.request.original.delivery_id),
            })
        } else {
            result
        };
        let _ = self.reply.send(result);
    }
}

fn operation_id(delivery: Digest32) -> String {
    // No caller-selected operation, study, route or generation can create a
    // second slot for this same original delivery in the writer's journal.
    format!("paired.original-delivery.v1.{delivery}")
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PreparationPayload {
    schema: String,
    identity: Value,
    original_route: AgentdTextSessionConfig,
    permission_revision: u64,
    expires_at_ms: u64,
    statement_sha256: String,
}

pub(crate) struct PreparationJournal {
    writer: Arc<ProductionDurableWriter>,
    registration: PairedPreparationRegistration,
    route: AgentdTextSessionConfig,
}

impl PreparationJournal {
    fn intent(
        &self,
        request: &PairedPreparationRequest,
        payload: &str,
    ) -> Result<OperationIntentV1, AgentdError> {
        let scope = serde_json::to_vec(&(
            "hepta.paired-learning.preparation-scope.v1",
            self.registration.study.to_string(),
            self.registration.enrollment.to_string(),
            self.registration.principal_id.as_str(),
        ))?;
        OperationIntentV1::new(
            StableId::new(operation_id(request.original.delivery_id))
                .map_err(|e| invalid(&e.to_string()))?,
            StableId::new(self.writer.owner_agent_id().as_str())
                .map_err(|e| invalid(&e.to_string()))?,
            StableId::new(DESTINATION).map_err(|e| invalid(&e.to_string()))?,
            Digest32::of_bytes(payload.as_bytes()),
            Digest32::of_bytes(&scope),
            self.registration.policy_generation,
            /*expected_predecessor*/ None,
        )
        .map_err(|e| invalid(&e.to_string()))
    }

    pub(crate) async fn retained(
        &self,
        request: &PairedPreparationRequest,
    ) -> Result<Option<PairedPreparationObservation>, AgentdError> {
        let identity = request.identity(&self.registration)?;
        let Some(retained) = self
            .writer
            .retained_operation(&operation_id(request.original.delivery_id))
            .await?
        else {
            return Ok(None);
        };
        let payload: PreparationPayload = serde_json::from_str(&retained.payload_json)?;
        if payload.schema != "hepta.paired-learning.native-preparation.v1"
            || payload.identity != identity
            || payload.original_route.agent_id != *self.writer.owner_agent_id()
            || payload.permission_revision == 0
            || payload.expires_at_ms == 0
            || payload.statement_sha256
                != Digest32::of_bytes(
                    request
                        .original
                        .usage
                        .consent_text(request.original.study)
                        .as_bytes(),
                )
                .to_string()
            || retained.topic != TOPIC
            || retained.operation != self.intent(request, &retained.payload_json)?
        {
            return Err(invalid(
                "original paired delivery is retained with different semantics",
            ));
        }
        Ok(Some(PairedPreparationObservation {
            operation_id: operation_id(request.original.delivery_id),
            payload_sha256: retained.operation.payload_digest(),
            semantic_sha256: retained.operation.semantic_digest(),
            state: retained.state,
        }))
    }

    pub(crate) async fn prepare_verified(
        &self,
        request: &PairedPreparationRequest,
        verified: &VerifiedPairedTurn,
        preparing: &AtomicBool,
    ) -> Result<PairedPreparationResponse, AgentdError> {
        match self
            .prepare_original_continuation(request, verified, preparing)
            .await?
        {
            PreparedOriginal::Fresh {
                observation,
                continuation,
            } => {
                continuation.finish_read_only()?;
                Ok(PairedPreparationResponse::FreshPrepared(observation))
            }
            PreparedOriginal::Retained(observation) => {
                Ok(PairedPreparationResponse::RetainedReadOnly(observation))
            }
        }
    }

    pub(crate) async fn prepare_original_continuation<'a>(
        &self,
        request: &PairedPreparationRequest,
        verified: &'a VerifiedPairedTurn,
        preparing: &AtomicBool,
    ) -> Result<PreparedOriginal<OriginalPairedContinuation<'a>>, AgentdError> {
        if verified.request() != &request.original || verified.route() != &self.route {
            return Err(invalid(
                "paired preparation did not receive this original owner observation",
            ));
        }
        verified.original_ingress()?;
        let payload = PreparationPayload {
            schema: "hepta.paired-learning.native-preparation.v1".into(),
            identity: request.identity(&self.registration)?,
            original_route: verified.route().clone(),
            permission_revision: verified.permission_revision(),
            expires_at_ms: verified.expires_at_ms(),
            statement_sha256: verified.statement_sha256().to_string(),
        };
        match self
            .retain_original_receipt(request, payload, preparing)
            .await?
        {
            PreparedOriginal::Fresh {
                observation,
                continuation,
            } => Ok(PreparedOriginal::Fresh {
                observation,
                continuation: continuation.bind_original(verified)?,
            }),
            PreparedOriginal::Retained(observation) => Ok(PreparedOriginal::Retained(observation)),
        }
    }

    async fn retain_original_receipt(
        &self,
        request: &PairedPreparationRequest,
        payload: PreparationPayload,
        preparing: &AtomicBool,
    ) -> Result<PreparedOriginal<FreshJournalPreparation>, AgentdError> {
        if let Some(retained) = self.retained(request).await? {
            return Ok(PreparedOriginal::Retained(retained));
        }
        let payload = serde_json::to_string(&payload)?;
        let intent = self.intent(request, &payload)?;
        preparing.store(true, Ordering::SeqCst);
        let receipt = self
            .writer
            .prepare_operation(intent, TOPIC, payload)
            .await?;
        let retained = self
            .retained(request)
            .await?
            .ok_or_else(|| invalid("paired preparation acknowledgement is unknown"))?;
        if receipt.replayed {
            Ok(PreparedOriginal::Retained(retained))
        } else if retained.state != LocalOutcomeState::Queued {
            Err(invalid(
                "fresh paired preparation changed before private handoff",
            ))
        } else {
            Ok(PreparedOriginal::Fresh {
                observation: retained,
                continuation: FreshJournalPreparation::from_original_commit(
                    Arc::clone(&self.writer),
                    receipt,
                    request.clone(),
                )?,
            })
        }
    }
}

#[cfg(test)]
#[path = "paired_preparation_tests.rs"]
mod tests;
