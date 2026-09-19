//! Production vertical slice from the durable kernel operation/outbox owner to
//! the existing CognitiveStore source ledger.
//!
//! The operation id is the destination event key. CognitiveStore derives a
//! stable source id from that key and rejects semantic drift, so duplicate
//! delivery is idempotent at the destination instead of relying on source-side
//! bookkeeping alone.

use std::future::Future;
use std::pin::Pin;

use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

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
use codex_hepta_contracts::Sha256Digest;

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
            return Err("cognitive source target access owner does not match store owner".to_string());
        }
        Ok(Self { store, access })
    }

    fn decode_request(&self, request: &ProductionDispatchRequest) -> Result<SourceDraft, String> {
        if request.topic != COGNITIVE_SOURCE_TOPIC_V1 {
            return Err(format!(
                "unexpected cognitive source topic {:?}",
                request.topic
            ));
        }
        if Sha256Digest::for_bytes(request.payload_json.as_bytes()) != request.payload_sha256 {
            return Err("dispatch payload digest mismatch".to_string());
        }
        let operation: CognitiveSourceOperationV1 = serde_json::from_str(&request.payload_json)
            .map_err(|error| format!("invalid cognitive source operation JSON: {error}"))?;
        if operation.event_key != request.idempotency_key {
            return Err(
                "cognitive source event key must equal the durable operation idempotency key"
                    .to_string(),
            );
        }
        operation.into_draft()
    }

    fn receipt(id: &SourceRevisionId) -> String {
        format!("{}:{}", id.source_id.as_str(), id.revision)
    }

    pub async fn observe_terminal(
        &self,
        request: &ProductionDispatchRequest,
    ) -> CognitiveSourceTerminalObservation {
        let draft = match self.decode_request(request) {
            Ok(draft) => draft,
            Err(reason) => return CognitiveSourceTerminalObservation::Quarantined { reason },
        };
        if let Err(error) = self.store.authorize(&self.access, &draft.scope) {
            return CognitiveSourceTerminalObservation::Quarantined {
                reason: error.to_string(),
            };
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
        .fetch_one(&self.store.pool)
        .await;
        let exact = match exact {
            Ok(value) => value,
            Err(error) => {
                return CognitiveSourceTerminalObservation::Unavailable {
                    reason: error.to_string(),
                };
            }
        };
        if exact == 1 {
            return CognitiveSourceTerminalObservation::Applied {
                receipt: Self::receipt(&SourceRevisionId::new(source_id)),
            };
        }

        let same_identity: Result<i64, sqlx::Error> = sqlx::query_scalar(
            "SELECT COUNT(*) FROM source_ledger WHERE source_id = ? AND source_revision = 1",
        )
        .bind(source_id.as_str())
        .fetch_one(&self.store.pool)
        .await;
        match same_identity {
            Ok(0) => CognitiveSourceTerminalObservation::NotApplied,
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
    fn dispatch<'a>(
        &'a self,
        request: ProductionDispatchRequest,
    ) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            let draft = match self.decode_request(&request) {
                Ok(draft) => draft,
                Err(reason) => return ProductionTargetOutcome::Rejected { reason },
            };
            match self.store.append_source(&self.access, &draft).await {
                Ok(id) => ProductionTargetOutcome::Committed {
                    receipt: Self::receipt(&id),
                },
                Err(
                    CognitiveStoreError::Invalid(reason)
                    | CognitiveStoreError::AccessDenied(reason)
                    | CognitiveStoreError::Conflict(reason),
                ) => ProductionTargetOutcome::Rejected { reason },
                Err(
                    CognitiveStoreError::Corrupt(reason)
                    | CognitiveStoreError::Unavailable(reason),
                ) => ProductionTargetOutcome::Indeterminate { reason },
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for CognitiveSourceOutboxTarget {
    fn destination_id(&self) -> &str {
        COGNITIVE_SOURCE_DESTINATION_V1
    }
}

#[cfg(test)]
#[path = "production_cognitive_source_target_tests.rs"]
mod tests;
