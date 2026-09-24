//! Production vertical slice from the durable kernel operation/outbox owner to
//! the existing CognitiveStore source ledger.
//!
//! The operation id is the destination event key. CognitiveStore derives a
//! stable source id from that key and rejects semantic drift, so duplicate
//! delivery is idempotent at the destination instead of relying on source-side
//! bookkeeping alone.

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::LedgerSourceKind;
use crate::SourceDraft;
use crate::SourceEventId;
use crate::SourceRevisionId;
use crate::production_writer::FinalUseProductionOutboxTarget;
use crate::production_writer::ProductionDispatchFuture;
use crate::production_writer::ProductionDispatchRequest;
use crate::production_writer::ProductionOutboxTarget;
use crate::production_writer::ProductionTargetOutcome;
use crate::production_writer::ProductionTerminalObservation;
use crate::production_writer::ProductionTerminalObservationFuture;
use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub const COGNITIVE_SOURCE_DESTINATION_V1: &str = "cognitive.store.source-ledger";
pub const COGNITIVE_SOURCE_TOPIC_V1: &str = "hepta.cognitive.source.append.v1";
pub const COGNITIVE_SOURCE_OPERATION_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CognitiveSourceOperationV1 {
    pub schema_version: u32,
    pub scope_kind: String,
    pub workspace_sha256: Option<String>,
    pub source_kind: String,
    pub event_key: String,
    pub content_base64: String,
    pub observed_at_unix_seconds: i64,
}

impl CognitiveSourceOperationV1 {
    pub fn from_draft(draft: &SourceDraft) -> Self {
        let (scope_kind, workspace_sha256) = draft.scope.database_parts();
        Self {
            schema_version: COGNITIVE_SOURCE_OPERATION_SCHEMA_VERSION,
            scope_kind: scope_kind.to_string(),
            workspace_sha256: workspace_sha256.map(str::to_string),
            source_kind: draft.kind.as_str().to_string(),
            event_key: draft.event_key.clone(),
            content_base64: BASE64_STANDARD.encode(&draft.content),
            observed_at_unix_seconds: draft.observed_at_unix_seconds,
        }
    }

    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }

    fn into_draft(self) -> Result<SourceDraft, String> {
        if self.schema_version != COGNITIVE_SOURCE_OPERATION_SCHEMA_VERSION {
            return Err(format!(
                "unsupported cognitive source operation schema {}",
                self.schema_version
            ));
        }
        let scope = CognitiveScope::parse(&self.scope_kind, self.workspace_sha256)?;
        let kind = LedgerSourceKind::parse(&self.source_kind)?;
        let content = BASE64_STANDARD
            .decode(self.content_base64.as_bytes())
            .map_err(|error| format!("invalid source content base64: {error}"))?;
        Ok(SourceDraft {
            scope,
            kind,
            event_key: self.event_key,
            content,
            observed_at_unix_seconds: self.observed_at_unix_seconds,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CognitiveSourceTerminalObservation {
    Applied { receipt: String },
    NotApplied,
    Quarantined { reason: String },
    Indeterminate { reason: String },
    Unavailable { reason: String },
}

#[derive(Clone)]
pub struct CognitiveSourceOutboxTarget {
    store: CognitiveStore,
    access: CognitiveAccess,
}

impl std::fmt::Debug for CognitiveSourceOutboxTarget {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("CognitiveSourceOutboxTarget")
            .field("destination", &COGNITIVE_SOURCE_DESTINATION_V1)
            .field("owner", self.store.owner_agent_id())
            .finish_non_exhaustive()
    }
}

impl CognitiveSourceOutboxTarget {
    pub fn new(store: CognitiveStore, access: CognitiveAccess) -> Result<Self, String> {
        if access.agent_id() != store.owner_agent_id() {
            return Err(
                "cognitive source target access owner does not match store owner".to_string(),
            );
        }
        Ok(Self { store, access })
    }

    fn decode_request(
        &self,
        request: &ProductionDispatchRequest,
    ) -> Result<(SourceDraft, Option<Sha256Digest>), String> {
        if request.topic != COGNITIVE_SOURCE_TOPIC_V1 {
            return Err(format!(
                "unexpected cognitive source topic {:?}",
                request.topic
            ));
        }
        if request.operation_destination_id != COGNITIVE_SOURCE_DESTINATION_V1 {
            return Err(
                "durable operation destination does not match cognitive source target".to_string(),
            );
        }
        if request.operation_subject_id != self.store.owner_agent_id().as_str() {
            return Err(
                "durable operation owner does not match cognitive source store".to_string(),
            );
        }
        if request.idempotency_key != request.occurrence_key {
            return Err("dispatch idempotency key must equal operation id".to_string());
        }
        if Sha256Digest::for_bytes(request.payload_json.as_bytes()) != request.payload_sha256 {
            return Err("dispatch payload digest mismatch".to_string());
        }

        let payload_digest = request
            .payload_sha256
            .as_str()
            .parse::<Digest32>()
            .map_err(|_| "dispatch payload digest is not a canonical Digest32".to_string())?;
        let expected_predecessor = request
            .expected_predecessor_sha256
            .as_ref()
            .map(|digest| digest.as_str().parse::<Digest32>())
            .transpose()
            .map_err(|_| "dispatch predecessor digest is not a canonical Digest32".to_string())?;
        let scope_digest = request
            .operation_scope_sha256
            .as_str()
            .parse::<Digest32>()
            .map_err(|_| "dispatch scope digest is not a canonical Digest32".to_string())?;
        let intent = OperationIntentV1::new(
            StableId::new(request.occurrence_key.clone())
                .map_err(|error| format!("invalid durable operation id: {error}"))?,
            StableId::new(request.operation_subject_id.clone())
                .map_err(|error| format!("invalid durable operation subject: {error}"))?,
            StableId::new(request.operation_destination_id.clone())
                .map_err(|error| format!("invalid durable operation destination: {error}"))?,
            payload_digest,
            scope_digest,
            Generation::new(request.operation_policy_generation)
                .map_err(|error| format!("invalid operation policy generation: {error}"))?,
            expected_predecessor,
        )
        .map_err(|error| format!("invalid durable operation intent: {error}"))?;
        if intent.semantic_digest().to_string() != request.operation_semantic_sha256.as_str() {
            return Err("destination recomputation rejected operation semantic digest".to_string());
        }

        let operation: CognitiveSourceOperationV1 = serde_json::from_str(&request.payload_json)
            .map_err(|error| format!("invalid cognitive source operation JSON: {error}"))?;
        let draft = operation.into_draft()?;
        let (scope_kind, workspace_sha256) = draft.scope.database_parts();
        let mut scope_bytes = b"hepta.cognitive.source.final-use-scope.v1\0".to_vec();
        scope_bytes.extend_from_slice(&(scope_kind.len() as u32).to_be_bytes());
        scope_bytes.extend_from_slice(scope_kind.as_bytes());
        match workspace_sha256 {
            Some(workspace) => {
                scope_bytes.push(1);
                scope_bytes.extend_from_slice(&(workspace.len() as u32).to_be_bytes());
                scope_bytes.extend_from_slice(workspace.as_bytes());
            }
            None => scope_bytes.push(0),
        }
        let expected_scope = Sha256Digest::for_bytes(&scope_bytes);
        if expected_scope != request.operation_scope_sha256 {
            return Err(
                "operation scope digest does not match destination payload scope".to_string(),
            );
        }
        if draft.event_key != request.idempotency_key {
            return Err(
                "cognitive source event key must equal the durable operation idempotency key"
                    .to_string(),
            );
        }
        Ok((draft, request.expected_predecessor_sha256.clone()))
    }

    fn receipt(id: &SourceRevisionId) -> String {
        format!("{}:{}", id.source_id.as_str(), id.revision)
    }

    fn decode_terminal_proof(
        request: &ProductionDispatchRequest,
        semantic_sha256: &str,
        disposition: &str,
        evidence: String,
    ) -> CognitiveSourceTerminalObservation {
        if semantic_sha256 != request.operation_semantic_sha256.as_str() {
            return CognitiveSourceTerminalObservation::Quarantined {
                reason: "destination terminal identity exists with different semantics".to_string(),
            };
        }
        match disposition {
            "applied" => CognitiveSourceTerminalObservation::Applied { receipt: evidence },
            "not_applied" => CognitiveSourceTerminalObservation::NotApplied,
            "quarantined" => CognitiveSourceTerminalObservation::Quarantined { reason: evidence },
            _ => CognitiveSourceTerminalObservation::Unavailable {
                reason: format!("invalid destination terminal disposition {disposition:?}"),
            },
        }
    }

    async fn terminal_proof(
        &self,
        request: &ProductionDispatchRequest,
    ) -> Result<Option<CognitiveSourceTerminalObservation>, sqlx::Error> {
        let row: Option<(String, String, String)> = sqlx::query_as(
            "SELECT semantic_sha256, disposition, evidence
             FROM cognitive_operation_destination_terminal
             WHERE destination_id = ? AND operation_id = ?",
        )
        .bind(COGNITIVE_SOURCE_DESTINATION_V1)
        .bind(&request.occurrence_key)
        .fetch_optional(&self.store.pool)
        .await?;
        Ok(row.map(|(semantic, disposition, evidence)| {
            Self::decode_terminal_proof(request, &semantic, &disposition, evidence)
        }))
    }

    async fn terminal_proof_tx(
        transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        request: &ProductionDispatchRequest,
    ) -> Result<Option<CognitiveSourceTerminalObservation>, sqlx::Error> {
        let row: Option<(String, String, String)> = sqlx::query_as(
            "SELECT semantic_sha256, disposition, evidence
             FROM cognitive_operation_destination_terminal
             WHERE destination_id = ? AND operation_id = ?",
        )
        .bind(COGNITIVE_SOURCE_DESTINATION_V1)
        .bind(&request.occurrence_key)
        .fetch_optional(&mut **transaction)
        .await?;
        Ok(row.map(|(semantic, disposition, evidence)| {
            Self::decode_terminal_proof(request, &semantic, &disposition, evidence)
        }))
    }

    async fn insert_terminal_proof_tx(
        transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        request: &ProductionDispatchRequest,
        disposition: &str,
        evidence: &str,
    ) -> Result<(), String> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_millis();
        let recorded_at =
            i64::try_from(now).map_err(|_| "terminal proof clock overflow".to_string())?;
        sqlx::query(
            "INSERT INTO cognitive_operation_destination_terminal (
                destination_id, operation_id, semantic_sha256, disposition,
                evidence, recorded_at_unix_ms
             ) VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(COGNITIVE_SOURCE_DESTINATION_V1)
        .bind(&request.occurrence_key)
        .bind(request.operation_semantic_sha256.as_str())
        .bind(disposition)
        .bind(evidence)
        .bind(recorded_at)
        .execute(&mut **transaction)
        .await
        .map_err(|error| error.to_string())?;
        Ok(())
    }

    async fn exact_count(
        &self,
        draft: &SourceDraft,
        source_id: &SourceEventId,
    ) -> Result<i64, sqlx::Error> {
        let content_sha256 = Sha256Digest::for_bytes(&draft.content);
        let (scope_kind, workspace_sha256) = draft.scope.database_parts();
        sqlx::query_scalar(
            "SELECT COUNT(*) FROM source_ledger
             WHERE source_id = ? AND source_revision = 1 AND owner_agent_id = ?
               AND scope_kind = ? AND workspace_sha256 IS ? AND source_kind = ?
               AND content = ? AND content_sha256 = ? AND observed_at_unix_seconds = ?",
        )
        .bind(source_id.as_str())
        .bind(self.store.owner_agent_id().as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(draft.kind.as_str())
        .bind(&draft.content)
        .bind(content_sha256.as_str())
        .bind(draft.observed_at_unix_seconds)
        .fetch_one(&self.store.pool)
        .await
    }

    pub async fn observe_terminal(
        &self,
        request: &ProductionDispatchRequest,
    ) -> CognitiveSourceTerminalObservation {
        let (draft, _expected_predecessor) = match self.decode_request(request) {
            Ok(value) => value,
            Err(reason) => return CognitiveSourceTerminalObservation::Quarantined { reason },
        };
        if let Err(error) = self.store.authorize(&self.access, &draft.scope) {
            return CognitiveSourceTerminalObservation::Quarantined {
                reason: error.to_string(),
            };
        }
        match self.terminal_proof(request).await {
            Ok(Some(observation)) => return observation,
            Ok(None) => {}
            Err(error) => {
                return CognitiveSourceTerminalObservation::Unavailable {
                    reason: error.to_string(),
                };
            }
        }
        let source_id = SourceEventId::for_event(
            self.store.owner_agent_id(),
            &draft.scope,
            draft.kind,
            &draft.event_key,
        );
        match self.exact_count(&draft, &source_id).await {
            Ok(1) => {
                return CognitiveSourceTerminalObservation::Applied {
                    receipt: Self::receipt(&SourceRevisionId::new(source_id)),
                };
            }
            Ok(_) => {}
            Err(error) => {
                return CognitiveSourceTerminalObservation::Unavailable {
                    reason: error.to_string(),
                };
            }
        }

        let same_identity: Result<i64, sqlx::Error> = sqlx::query_scalar(
            "SELECT COUNT(*) FROM source_ledger WHERE source_id = ? AND source_revision = 1",
        )
        .bind(source_id.as_str())
        .fetch_one(&self.store.pool)
        .await;
        match same_identity {
            Ok(0) => CognitiveSourceTerminalObservation::Indeterminate {
                reason: "destination has no terminal proof for this operation".to_string(),
            },
            Ok(_) => CognitiveSourceTerminalObservation::Quarantined {
                reason: "destination source identity exists with different semantics".to_string(),
            },
            Err(error) => CognitiveSourceTerminalObservation::Unavailable {
                reason: error.to_string(),
            },
        }
    }
}

impl ProductionOutboxTarget for CognitiveSourceOutboxTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            let (draft, expected_predecessor) = match self.decode_request(&request) {
                Ok(value) => value,
                Err(reason) => return ProductionTargetOutcome::Rejected { reason },
            };
            let mut transaction = match self.store.pool.begin_with("BEGIN IMMEDIATE").await {
                Ok(transaction) => transaction,
                Err(error) => {
                    return ProductionTargetOutcome::Indeterminate {
                        reason: error.to_string(),
                    };
                }
            };
            if let Err(error) = self.store.authorize(&self.access, &draft.scope) {
                return ProductionTargetOutcome::Rejected {
                    reason: error.to_string(),
                };
            }
            match Self::terminal_proof_tx(&mut transaction, &request).await {
                Ok(Some(observation)) => {
                    let outcome = match observation {
                        CognitiveSourceTerminalObservation::Applied { receipt } => {
                            ProductionTargetOutcome::Committed { receipt }
                        }
                        CognitiveSourceTerminalObservation::NotApplied => {
                            ProductionTargetOutcome::NotApplied {
                                reason: "destination terminal proof records NotApplied".to_string(),
                            }
                        }
                        CognitiveSourceTerminalObservation::Quarantined { reason } => {
                            ProductionTargetOutcome::Rejected { reason }
                        }
                        CognitiveSourceTerminalObservation::Indeterminate { reason }
                        | CognitiveSourceTerminalObservation::Unavailable { reason } => {
                            ProductionTargetOutcome::Indeterminate { reason }
                        }
                    };
                    if let Err(error) = transaction.commit().await {
                        return ProductionTargetOutcome::Indeterminate {
                            reason: error.to_string(),
                        };
                    }
                    return outcome;
                }
                Ok(None) => {}
                Err(error) => {
                    return ProductionTargetOutcome::Indeterminate {
                        reason: error.to_string(),
                    };
                }
            }

            let source_id = SourceEventId::for_event(
                self.store.owner_agent_id(),
                &draft.scope,
                draft.kind,
                &draft.event_key,
            );
            let content_sha256 = Sha256Digest::for_bytes(&draft.content);
            let (scope_kind, workspace_sha256) = draft.scope.database_parts();
            let exact: Result<i64, sqlx::Error> = sqlx::query_scalar(
                "SELECT COUNT(*) FROM source_ledger
                 WHERE source_id = ? AND source_revision = 1 AND owner_agent_id = ?
                   AND scope_kind = ? AND workspace_sha256 IS ? AND source_kind = ?
                   AND content = ? AND content_sha256 = ? AND observed_at_unix_seconds = ?",
            )
            .bind(source_id.as_str())
            .bind(self.store.owner_agent_id().as_str())
            .bind(scope_kind)
            .bind(workspace_sha256)
            .bind(draft.kind.as_str())
            .bind(&draft.content)
            .bind(content_sha256.as_str())
            .bind(draft.observed_at_unix_seconds)
            .fetch_one(&mut *transaction)
            .await;
            match exact {
                Ok(1) => {
                    let receipt = Self::receipt(&SourceRevisionId::new(source_id));
                    if let Err(reason) = Self::insert_terminal_proof_tx(
                        &mut transaction,
                        &request,
                        "applied",
                        &receipt,
                    )
                    .await
                    {
                        return ProductionTargetOutcome::Indeterminate { reason };
                    }
                    if let Err(error) = transaction.commit().await {
                        return ProductionTargetOutcome::Indeterminate {
                            reason: error.to_string(),
                        };
                    }
                    return ProductionTargetOutcome::Committed { receipt };
                }
                Ok(_) => {}
                Err(error) => {
                    return ProductionTargetOutcome::Indeterminate {
                        reason: error.to_string(),
                    };
                }
            }

            let same_identity: Result<i64, sqlx::Error> = sqlx::query_scalar(
                "SELECT COUNT(*) FROM source_ledger WHERE source_id = ? AND source_revision = 1",
            )
            .bind(source_id.as_str())
            .fetch_one(&mut *transaction)
            .await;
            match same_identity {
                Ok(0) => {}
                Ok(_) => {
                    return ProductionTargetOutcome::Rejected {
                        reason: "destination source identity exists with different semantics"
                            .to_string(),
                    };
                }
                Err(error) => {
                    return ProductionTargetOutcome::Indeterminate {
                        reason: error.to_string(),
                    };
                }
            }

            // source_ledger is create-only: the authoritative predecessor for
            // an absent source identity is None. Compare the operation CAS
            // expectation while holding the same BEGIN IMMEDIATE transaction
            // that will publish the destination row.
            if expected_predecessor.is_some() {
                let reason =
                    "destination predecessor/CAS mismatch: source identity has no predecessor"
                        .to_string();
                if let Err(error) = Self::insert_terminal_proof_tx(
                    &mut transaction,
                    &request,
                    "not_applied",
                    &reason,
                )
                .await
                {
                    return ProductionTargetOutcome::Indeterminate { reason: error };
                }
                if let Err(error) = transaction.commit().await {
                    return ProductionTargetOutcome::Indeterminate {
                        reason: error.to_string(),
                    };
                }
                return ProductionTargetOutcome::NotApplied { reason };
            }

            let id = match self
                .store
                .append_source_tx(&mut transaction, &self.access, &draft)
                .await
            {
                Ok(id) => id,
                Err(
                    CognitiveStoreError::Invalid(reason)
                    | CognitiveStoreError::AccessDenied(reason)
                    | CognitiveStoreError::Conflict(reason),
                ) => return ProductionTargetOutcome::Rejected { reason },
                Err(
                    CognitiveStoreError::Corrupt(reason) | CognitiveStoreError::Unavailable(reason),
                ) => return ProductionTargetOutcome::Indeterminate { reason },
            };
            let receipt = Self::receipt(&id);
            if let Err(reason) =
                Self::insert_terminal_proof_tx(&mut transaction, &request, "applied", &receipt)
                    .await
            {
                return ProductionTargetOutcome::Indeterminate { reason };
            }
            if let Err(error) = transaction.commit().await {
                return ProductionTargetOutcome::Indeterminate {
                    reason: error.to_string(),
                };
            }
            ProductionTargetOutcome::Committed { receipt }
        })
    }
}

impl FinalUseProductionOutboxTarget for CognitiveSourceOutboxTarget {
    fn destination_id(&self) -> &str {
        COGNITIVE_SOURCE_DESTINATION_V1
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            match CognitiveSourceOutboxTarget::observe_terminal(self, request).await {
                CognitiveSourceTerminalObservation::Applied { receipt } => {
                    ProductionTerminalObservation::Applied { receipt }
                }
                CognitiveSourceTerminalObservation::NotApplied => {
                    ProductionTerminalObservation::NotApplied {
                        reason: "destination has no committed source row".to_string(),
                    }
                }
                CognitiveSourceTerminalObservation::Quarantined { reason } => {
                    ProductionTerminalObservation::Quarantined { reason }
                }
                CognitiveSourceTerminalObservation::Indeterminate { reason } => {
                    ProductionTerminalObservation::Indeterminate { reason }
                }
                CognitiveSourceTerminalObservation::Unavailable { reason } => {
                    ProductionTerminalObservation::Unavailable { reason }
                }
            }
        })
    }
}

#[cfg(test)]
#[path = "production_cognitive_source_target_tests.rs"]
mod tests;
