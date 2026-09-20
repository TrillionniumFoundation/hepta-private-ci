use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_operations::DurableOperationBinding;
use codex_hepta_operations::DurableOperationLedger;
use codex_hepta_operations::OperationKey;
use codex_hepta_operations::OperationState;
use codex_hepta_operations::ReconciliationOutcome;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

const TRANSPORT_SCHEMA: &str = "hepta.ui-control.transport-request.v1";
const REQUEST_SEMANTICS_SCHEMA: &str = "hepta.ui-control.request-semantics.v1";
const CONTEXT_SCHEMA: &str = "hepta.ui-control.gateway-context.v1";
const SCOPE_SCHEMA: &str = "hepta.ui-control.final-use-scope.v1";
const DISPATCH_SCHEMA: &str = "hepta.ui-control.owner-dispatch.v1";
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum UiControlRole {
    Operator,
    RuntimeAdmin,
    EmergencyStop,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedUiPrincipal {
    pub principal_id: StableId,
    pub session_id: StableId,
    pub connection_generation: Generation,
    pub authentication_context_digest: Digest32,
    pub roles: BTreeSet<UiControlRole>,
}

pub trait UiControlSessionAuthenticator: Send + Sync {
    fn authenticate(
        &self,
        session_id: &StableId,
        connection_generation: Generation,
    ) -> Result<TrustedUiPrincipal, UiControlGatewayError>;
}

pub trait UiControlRuntimeViewVerifier: Send + Sync {
    fn verify_current_view(
        &self,
        principal: &TrustedUiPrincipal,
        runtime_generation: Generation,
        displayed_revision: Revision,
        runtime_digest: Digest32,
    ) -> Result<(), UiControlGatewayError>;
}

pub trait UiControlFinalUseGrantProvider: Send + Sync {
    fn grant_for(
        &self,
        principal: &TrustedUiPrincipal,
        binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, UiControlGatewayError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UiControlAction {
    Retry,
    Reconcile,
    Quarantine,
    Rollback,
    Stop,
}

impl UiControlAction {
    fn label(self) -> &'static str {
        match self {
            Self::Retry => "request_retry",
            Self::Reconcile => "request_reconcile",
            Self::Quarantine => "request_quarantine",
            Self::Rollback => "request_rollback",
            Self::Stop => "runtime_stop",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerDispatch {
    pub operation_id: StableId,
    pub semantic_digest: Digest32,
    pub principal_id: StableId,
    pub target_id: StableId,
    pub action: UiControlAction,
    pub expected_revision: Option<Revision>,
    pub dispatch_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerDispatchFailure {
    Rejected { evidence_digest: Digest32 },
    Indeterminate { reason_digest: Digest32 },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OwnerDispatchReceipt {
    pub dispatch_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OwnerTerminalObservation {
    pub outcome: ReconciliationOutcome,
    pub outcome_digest: Digest32,
    pub observer_generation: Generation,
}

pub trait UiControlOwnerAdapter: Send + Sync {
    fn destination_id(
        &self,
        target_id: &StableId,
        action: UiControlAction,
    ) -> Result<StableId, UiControlGatewayError>;

    fn current_revision(
        &self,
        target_id: &StableId,
    ) -> Result<Revision, UiControlGatewayError>;

    fn preflight(
        &self,
        principal: &TrustedUiPrincipal,
        dispatch: &OwnerDispatch,
    ) -> Result<(), UiControlGatewayError>;

    fn dispatch(
        &self,
        dispatch: &OwnerDispatch,
    ) -> Result<OwnerDispatchReceipt, OwnerDispatchFailure>;

    fn observe_terminal(
        &self,
        operation_id: &StableId,
        target_id: &StableId,
    ) -> Result<Option<OwnerTerminalObservation>, UiControlGatewayError>;
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UiOperationProposalV1 {
    pub kind: String,
    pub operation_id: String,
    pub subject_id: String,
    pub action: String,
    pub expected_revision: u64,
    pub authority_granted: bool,
    pub direct_store_write: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UiStopScopeV1 {
    pub scope_kind: String,
    pub target_id: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UiControlTransportRequestV1 {
    pub schema: String,
    pub session_id: String,
    pub connection_generation: u64,
    pub runtime_generation: u64,
    pub runtime_digest: String,
    pub displayed_revision: u64,
    pub operation_id: String,
    pub semantic_digest: String,
    #[serde(default)]
    pub intent: Option<UiOperationProposalV1>,
    #[serde(default)]
    pub scope: Option<UiStopScopeV1>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UiControlReconcileQueryV1 {
    pub session_id: String,
    pub connection_generation: u64,
    pub method: String,
    pub operation_id: String,
    pub semantic_digest: String,
    pub origin_session_id: String,
    pub origin_connection_generation: u64,
    pub runtime_generation: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UiControlRequestAcknowledgementV1 {
    pub accepted: bool,
    pub method: String,
    pub session_id: String,
    pub connection_generation: u64,
    pub runtime_generation: u64,
    pub operation_id: String,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UiControlReconciliationObservationV1 {
    pub session_id: String,
    pub connection_generation: u64,
    pub method: String,
    pub operation_id: String,
    pub semantic_digest: String,
    pub origin_session_id: String,
    pub origin_connection_generation: u64,
    pub runtime_generation: u64,
    pub status: String,
    pub terminal_observed: bool,
    pub outcome_digest: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UiControlGatewayError {
    InvalidRequest(&'static str),
    Unauthenticated,
    Forbidden,
    StaleView,
    StaleTargetRevision,
    SemanticDigestMismatch,
    AuthorityUnavailable,
    AuthorityRejected,
    DurableUnavailable,
    OwnerUnavailable,
    OwnerRejected,
    ReconciliationMismatch,
    TimeUnavailable,
}

impl fmt::Display for UiControlGatewayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::InvalidRequest(field) => return write!(formatter, "invalid ui.control request: {field}"),
            Self::Unauthenticated => "ui.control session is not authenticated",
            Self::Forbidden => "ui.control principal is not authorized for this action",
            Self::StaleView => "ui.control displayed view is stale",
            Self::StaleTargetRevision => "ui.control target revision is stale",
            Self::SemanticDigestMismatch => "ui.control semantic digest mismatch",
            Self::AuthorityUnavailable => "ui.control final-use authority is unavailable",
            Self::AuthorityRejected => "ui.control final-use authority rejected the operation",
            Self::DurableUnavailable => "ui.control durable operation owner is unavailable",
            Self::OwnerUnavailable => "ui.control destination owner is unavailable",
            Self::OwnerRejected => "ui.control destination owner rejected the operation",
            Self::ReconciliationMismatch => "ui.control reconciliation provenance mismatch",
            Self::TimeUnavailable => "ui.control host clock is unavailable",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for UiControlGatewayError {}

#[derive(Clone)]
pub struct UiControlGateway {
    ledger: DurableOperationLedger,
    authority: FinalUseAuthority,
    authenticator: Arc<dyn UiControlSessionAuthenticator>,
    view_verifier: Arc<dyn UiControlRuntimeViewVerifier>,
    grant_provider: Arc<dyn UiControlFinalUseGrantProvider>,
    owner: Arc<dyn UiControlOwnerAdapter>,
    owner_generation: Generation,
}

impl fmt::Debug for UiControlGateway {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("UiControlGateway")
            .field("owner_generation", &self.owner_generation)
            .finish_non_exhaustive()
    }
}

impl UiControlGateway {
    pub fn new(
        ledger: DurableOperationLedger,
        authority: FinalUseAuthority,
        authenticator: Arc<dyn UiControlSessionAuthenticator>,
        view_verifier: Arc<dyn UiControlRuntimeViewVerifier>,
        grant_provider: Arc<dyn UiControlFinalUseGrantProvider>,
        owner: Arc<dyn UiControlOwnerAdapter>,
        owner_generation: Generation,
    ) -> Self {
        Self {
            ledger,
            authority,
            authenticator,
            view_verifier,
            grant_provider,
            owner,
            owner_generation,
        }
    }

    pub async fn submit_request(
        &self,
        method: &str,
        request: UiControlTransportRequestV1,
    ) -> Result<UiControlRequestAcknowledgementV1, UiControlGatewayError> {
        let normalized = normalize_request(method, request)?;
        let principal = self
            .authenticator
            .authenticate(&normalized.session_id, normalized.connection_generation)?;
        verify_principal_session(&principal, &normalized)?;
        authorize_role(&principal, normalized.action)?;

        self.view_verifier.verify_current_view(
            &principal,
            normalized.runtime_generation,
            normalized.displayed_revision,
            normalized.runtime_digest,
        )?;

        if let Some(expected_revision) = normalized.expected_revision {
            let current = self
                .owner
                .current_revision(&normalized.target_id)
                .map_err(|_| UiControlGatewayError::OwnerUnavailable)?;
            if current != expected_revision {
                return Err(UiControlGatewayError::StaleTargetRevision);
            }
        }

        let destination_id = self
            .owner
            .destination_id(&normalized.target_id, normalized.action)
            .map_err(|_| UiControlGatewayError::OwnerUnavailable)?;
        let context_digest = gateway_context_digest(
            method,
            &principal.principal_id,
            &normalized.session_id,
            normalized.connection_generation,
            normalized.runtime_generation,
        )?;

        let durable = self
            .ledger
            .begin_bound(
                DurableOperationBinding {
                    key: OperationKey {
                        id: normalized.operation_id.clone(),
                        payload_digest: normalized.semantic_digest,
                    },
                    destination_id: destination_id.clone(),
                    context_digest,
                },
                self.owner_generation,
            )
            .await
            .map_err(map_durable_error)?;

        if !matches!(durable.operation.state, OperationState::Pending) {
            return Ok(acknowledgement(method, &normalized));
        }

        let scope_digest = final_use_scope_digest(
            normalized.action,
            &normalized.target_id,
            normalized.expected_revision,
            &destination_id,
        )?;
        let payload_digest = canonical_digest(&normalized.payload)?;
        let binding = FinalUseBinding {
            subject_id: principal.principal_id.as_str().to_string(),
            destination_id: destination_id.as_str().to_string(),
            request_sha256: normalized.semantic_digest.into_array(),
            scope_sha256: scope_digest.into_array(),
            payload_sha256: payload_digest.into_array(),
        };
        let dispatch_digest = owner_dispatch_digest(
            &normalized.operation_id,
            normalized.semantic_digest,
            &principal.principal_id,
            &normalized.target_id,
            normalized.action,
            normalized.expected_revision,
            &destination_id,
        )?;
        let dispatch = OwnerDispatch {
            operation_id: normalized.operation_id.clone(),
            semantic_digest: normalized.semantic_digest,
            principal_id: principal.principal_id.clone(),
            target_id: normalized.target_id.clone(),
            action: normalized.action,
            expected_revision: normalized.expected_revision,
            dispatch_digest,
        };
        self.owner
            .preflight(&principal, &dispatch)
            .map_err(|_| UiControlGatewayError::OwnerRejected)?;

        let signed_grant = self
            .grant_provider
            .grant_for(&principal, &binding)
            .map_err(|_| UiControlGatewayError::AuthorityUnavailable)?;
        let evidence_digest = signed_grant_evidence_digest(&signed_grant)?;
        let authority_generation = Generation::new(signed_grant.grant.authority_epoch)
            .map_err(|_| UiControlGatewayError::AuthorityRejected)?;
        let token = self
            .authority
            .claim(&signed_grant, &binding)
            .map_err(|_| UiControlGatewayError::AuthorityRejected)?;

        self.ledger
            .record_authorized_dispatch(
                &normalized.operation_id,
                evidence_digest,
                authority_generation,
                dispatch_digest,
            )
            .await
            .map_err(map_durable_error)?;

        let dispatch_result = self
            .authority
            .with_verified_use(token, &binding, || self.owner.dispatch(&dispatch));

        match dispatch_result {
            Ok(Ok(receipt)) if receipt.dispatch_digest == dispatch_digest => {
                Ok(acknowledgement(method, &normalized))
            }
            Ok(Ok(_)) => {
                self.mark_indeterminate(
                    &normalized.operation_id,
                    Digest32::of_bytes(b"ui.control.dispatch-receipt-mismatch"),
                )
                .await?;
                Err(UiControlGatewayError::ReconciliationMismatch)
            }
            Ok(Err(OwnerDispatchFailure::Rejected { evidence_digest })) => {
                self.ledger
                    .observe_terminal(
                        &normalized.operation_id,
                        ReconciliationOutcome::NotApplied,
                        evidence_digest,
                        self.owner_generation,
                    )
                    .await
                    .map_err(map_durable_error)?;
                Err(UiControlGatewayError::OwnerRejected)
            }
            Ok(Err(OwnerDispatchFailure::Indeterminate { reason_digest })) => {
                self.mark_indeterminate(&normalized.operation_id, reason_digest)
                    .await?;
                Ok(acknowledgement(method, &normalized))
            }
            Err(_) => {
                let outcome_digest =
                    Digest32::of_bytes(b"ui.control.final-use-revoked-before-owner-entry");
                self.ledger
                    .observe_terminal(
                        &normalized.operation_id,
                        ReconciliationOutcome::NotApplied,
                        outcome_digest,
                        self.owner_generation,
                    )
                    .await
                    .map_err(map_durable_error)?;
                Err(UiControlGatewayError::AuthorityRejected)
            }
        }
    }

    pub async fn reconcile(
        &self,
        query: UiControlReconcileQueryV1,
    ) -> Result<Option<UiControlReconciliationObservationV1>, UiControlGatewayError> {
        let normalized = normalize_reconcile_query(query)?;
        let principal = self
            .authenticator
            .authenticate(&normalized.session_id, normalized.connection_generation)?;
        if principal.session_id != normalized.session_id
            || principal.connection_generation != normalized.connection_generation
        {
            return Err(UiControlGatewayError::Unauthenticated);
        }

        let Some(mut durable) = self
            .ledger
            .get(&normalized.operation_id)
            .await
            .map_err(map_durable_error)?
        else {
            return Ok(None);
        };
        if durable.operation.key.payload_digest != normalized.semantic_digest {
            return Err(UiControlGatewayError::ReconciliationMismatch);
        }
        let expected_context = gateway_context_digest(
            &normalized.method,
            &principal.principal_id,
            &normalized.origin_session_id,
            normalized.origin_connection_generation,
            normalized.runtime_generation,
        )?;
        if durable.context_digest != expected_context {
            return Err(UiControlGatewayError::ReconciliationMismatch);
        }

        if !durable.operation.state.is_terminal() {
            if let Some(observation) = self
                .owner
                .observe_terminal(&normalized.operation_id, &durable.destination_id)
                .map_err(|_| UiControlGatewayError::OwnerUnavailable)?
            {
                durable = self
                    .ledger
                    .observe_terminal(
                        &normalized.operation_id,
                        observation.outcome,
                        observation.outcome_digest,
                        observation.observer_generation,
                    )
                    .await
                    .map_err(map_durable_error)?;
            }
        }

        Ok(Some(reconciliation_observation(&normalized, &durable.operation.state)))
    }

    async fn mark_indeterminate(
        &self,
        operation_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<(), UiControlGatewayError> {
        self.ledger
            .mark_indeterminate(operation_id, reason_digest)
            .await
            .map_err(map_durable_error)?;
        Ok(())
    }
}

#[derive(Clone, Debug)]
struct NormalizedRequest {
    session_id: StableId,
    connection_generation: Generation,
    runtime_generation: Generation,
    runtime_digest: Digest32,
    displayed_revision: Revision,
    operation_id: StableId,
    semantic_digest: Digest32,
    target_id: StableId,
    action: UiControlAction,
    expected_revision: Option<Revision>,
    payload: Value,
}

#[derive(Clone, Debug)]
struct NormalizedReconcile {
    session_id: StableId,
    connection_generation: Generation,
    method: String,
    operation_id: StableId,
    semantic_digest: Digest32,
    origin_session_id: StableId,
    origin_connection_generation: Generation,
    runtime_generation: Generation,
}

fn normalize_request(
    method: &str,
    request: UiControlTransportRequestV1,
) -> Result<NormalizedRequest, UiControlGatewayError> {
    if request.schema != TRANSPORT_SCHEMA {
        return Err(UiControlGatewayError::InvalidRequest("schema"));
    }
    let session_id = stable_id(request.session_id, "sessionId")?;
    let connection_generation = generation(request.connection_generation, "connectionGeneration")?;
    let runtime_generation = generation(request.runtime_generation, "runtimeGeneration")?;
    let runtime_digest = digest(&request.runtime_digest, "runtimeDigest")?;
    let displayed_revision = revision(request.displayed_revision, "displayedRevision")?;
    let operation_id = stable_id(request.operation_id, "operationId")?;
    let semantic_digest = digest(&request.semantic_digest, "semanticDigest")?;

    let (target_id, action, expected_revision, payload) = match method {
        "operation/request" => {
            let intent = request
                .intent
                .ok_or(UiControlGatewayError::InvalidRequest("intent"))?;
            if request.scope.is_some()
                || intent.kind != "UiOperationProposalV1"
                || intent.operation_id != operation_id.as_str()
                || intent.authority_granted
                || intent.direct_store_write
            {
                return Err(UiControlGatewayError::InvalidRequest("intent binding"));
            }
            let target_id = stable_id(intent.subject_id.clone(), "subjectId")?;
            let action = parse_action(&intent.action)?;
            let expected_revision = revision(intent.expected_revision, "expectedRevision")?;
            let payload = serde_json::to_value(intent)
                .map_err(|_| UiControlGatewayError::InvalidRequest("intent encoding"))?;
            (target_id, action, Some(expected_revision), payload)
        }
        "runtime/stop" => {
            let scope = request
                .scope
                .ok_or(UiControlGatewayError::InvalidRequest("scope"))?;
            if request.intent.is_some() || scope.scope_kind != "runtime" {
                return Err(UiControlGatewayError::InvalidRequest("stop scope"));
            }
            let target_id = stable_id(scope.target_id.clone(), "targetId")?;
            let payload = serde_json::to_value(scope)
                .map_err(|_| UiControlGatewayError::InvalidRequest("scope encoding"))?;
            (target_id, UiControlAction::Stop, None, payload)
        }
        _ => return Err(UiControlGatewayError::InvalidRequest("method")),
    };

    let semantics = request_semantics_value(
        method,
        &session_id,
        connection_generation,
        runtime_generation,
        displayed_revision,
        runtime_digest,
        &operation_id,
        &payload,
    );
    if canonical_digest(&semantics)? != semantic_digest {
        return Err(UiControlGatewayError::SemanticDigestMismatch);
    }

    Ok(NormalizedRequest {
        session_id,
        connection_generation,
        runtime_generation,
        runtime_digest,
        displayed_revision,
        operation_id,
        semantic_digest,
        target_id,
        action,
        expected_revision,
        payload,
    })
}

fn normalize_reconcile_query(
    query: UiControlReconcileQueryV1,
) -> Result<NormalizedReconcile, UiControlGatewayError> {
    if !matches!(query.method.as_str(), "operation/request" | "runtime/stop") {
        return Err(UiControlGatewayError::InvalidRequest("reconcile method"));
    }
    Ok(NormalizedReconcile {
        session_id: stable_id(query.session_id, "sessionId")?,
        connection_generation: generation(query.connection_generation, "connectionGeneration")?,
        method: query.method,
        operation_id: stable_id(query.operation_id, "operationId")?,
        semantic_digest: digest(&query.semantic_digest, "semanticDigest")?,
        origin_session_id: stable_id(query.origin_session_id, "originSessionId")?,
        origin_connection_generation: generation(
            query.origin_connection_generation,
            "originConnectionGeneration",
        )?,
        runtime_generation: generation(query.runtime_generation, "runtimeGeneration")?,
    })
}

fn verify_principal_session(
    principal: &TrustedUiPrincipal,
    request: &NormalizedRequest,
) -> Result<(), UiControlGatewayError> {
    if principal.session_id != request.session_id
        || principal.connection_generation != request.connection_generation
        || principal.authentication_context_digest.is_zero()
    {
        return Err(UiControlGatewayError::Unauthenticated);
    }
    Ok(())
}

fn authorize_role(
    principal: &TrustedUiPrincipal,
    action: UiControlAction,
) -> Result<(), UiControlGatewayError> {
    let allowed = match action {
        UiControlAction::Rollback => principal.roles.contains(&UiControlRole::RuntimeAdmin),
        UiControlAction::Stop => principal.roles.contains(&UiControlRole::EmergencyStop),
        UiControlAction::Retry | UiControlAction::Reconcile | UiControlAction::Quarantine => {
            principal.roles.contains(&UiControlRole::Operator)
                || principal.roles.contains(&UiControlRole::RuntimeAdmin)
        }
    };
    if allowed {
        Ok(())
    } else {
        Err(UiControlGatewayError::Forbidden)
    }
}

fn parse_action(value: &str) -> Result<UiControlAction, UiControlGatewayError> {
    match value {
        "request_retry" => Ok(UiControlAction::Retry),
        "request_reconcile" => Ok(UiControlAction::Reconcile),
        "request_quarantine" => Ok(UiControlAction::Quarantine),
        "request_rollback" => Ok(UiControlAction::Rollback),
        _ => Err(UiControlGatewayError::InvalidRequest("action")),
    }
}

fn acknowledgement(
    method: &str,
    request: &NormalizedRequest,
) -> UiControlRequestAcknowledgementV1 {
    UiControlRequestAcknowledgementV1 {
        accepted: true,
        method: method.to_string(),
        session_id: request.session_id.as_str().to_string(),
        connection_generation: request.connection_generation.get(),
        runtime_generation: request.runtime_generation.get(),
        operation_id: request.operation_id.as_str().to_string(),
        semantic_digest: request.semantic_digest.to_string(),
    }
}

fn reconciliation_observation(
    query: &NormalizedReconcile,
    state: &OperationState,
) -> UiControlReconciliationObservationV1 {
    let (status, terminal_observed, outcome_digest) = match state {
        OperationState::Pending | OperationState::Authorized { .. } | OperationState::Dispatched { .. } => {
            ("pending", false, None)
        }
        OperationState::Indeterminate { .. } => ("indeterminate", false, None),
        OperationState::Applied { outcome_digest } => {
            ("succeeded", true, Some(outcome_digest.to_string()))
        }
        OperationState::NotApplied { outcome_digest } => {
            ("failed", true, Some(outcome_digest.to_string()))
        }
        OperationState::Quarantined { reason_digest } => {
            ("rejected", true, Some(reason_digest.to_string()))
        }
    };
    UiControlReconciliationObservationV1 {
        session_id: query.session_id.as_str().to_string(),
        connection_generation: query.connection_generation.get(),
        method: query.method.clone(),
        operation_id: query.operation_id.as_str().to_string(),
        semantic_digest: query.semantic_digest.to_string(),
        origin_session_id: query.origin_session_id.as_str().to_string(),
        origin_connection_generation: query.origin_connection_generation.get(),
        runtime_generation: query.runtime_generation.get(),
        status: status.to_string(),
        terminal_observed,
        outcome_digest,
    }
}

fn request_semantics_value(
    method: &str,
    session_id: &StableId,
    connection_generation: Generation,
    runtime_generation: Generation,
    displayed_revision: Revision,
    runtime_digest: Digest32,
    operation_id: &StableId,
    payload: &Value,
) -> Value {
    serde_json::json!({
        "schema": REQUEST_SEMANTICS_SCHEMA,
        "method": method,
        "operationId": operation_id.as_str(),
        "displayedView": {
            "sessionId": session_id.as_str(),
            "connectionGeneration": connection_generation.get(),
            "generation": runtime_generation.get(),
            "revision": displayed_revision.get(),
            "digest": runtime_digest.to_string()
        },
        "payload": payload
    })
}

fn gateway_context_digest(
    method: &str,
    principal_id: &StableId,
    origin_session_id: &StableId,
    origin_connection_generation: Generation,
    runtime_generation: Generation,
) -> Result<Digest32, UiControlGatewayError> {
    canonical_digest(&serde_json::json!({
        "schema": CONTEXT_SCHEMA,
        "method": method,
        "principalId": principal_id.as_str(),
        "originSessionId": origin_session_id.as_str(),
        "originConnectionGeneration": origin_connection_generation.get(),
        "runtimeGeneration": runtime_generation.get()
    }))
}

fn final_use_scope_digest(
    action: UiControlAction,
    target_id: &StableId,
    expected_revision: Option<Revision>,
    destination_id: &StableId,
) -> Result<Digest32, UiControlGatewayError> {
    canonical_digest(&serde_json::json!({
        "schema": SCOPE_SCHEMA,
        "action": action.label(),
        "targetId": target_id.as_str(),
        "expectedRevision": expected_revision.map(Revision::get),
        "destinationId": destination_id.as_str()
    }))
}

fn owner_dispatch_digest(
    operation_id: &StableId,
    semantic_digest: Digest32,
    principal_id: &StableId,
    target_id: &StableId,
    action: UiControlAction,
    expected_revision: Option<Revision>,
    destination_id: &StableId,
) -> Result<Digest32, UiControlGatewayError> {
    canonical_digest(&serde_json::json!({
        "schema": DISPATCH_SCHEMA,
        "operationId": operation_id.as_str(),
        "semanticDigest": semantic_digest.to_string(),
        "principalId": principal_id.as_str(),
        "targetId": target_id.as_str(),
        "action": action.label(),
        "expectedRevision": expected_revision.map(Revision::get),
        "destinationId": destination_id.as_str()
    }))
}

fn signed_grant_evidence_digest(
    grant: &SignedFinalUseGrant,
) -> Result<Digest32, UiControlGatewayError> {
    let signing = grant
        .grant
        .signing_bytes()
        .map_err(|_| UiControlGatewayError::AuthorityRejected)?;
    Ok(Digest32::of_parts(&[&signing, &grant.signature]))
}

fn canonical_digest(value: &Value) -> Result<Digest32, UiControlGatewayError> {
    let encoded = canonical_json(value)?;
    Ok(Digest32::of_bytes(encoded.as_bytes()))
}

fn canonical_json(value: &Value) -> Result<String, UiControlGatewayError> {
    let mut output = String::new();
    write_canonical(value, &mut output)?;
    Ok(output)
}

fn write_canonical(
    value: &Value,
    output: &mut String,
) -> Result<(), UiControlGatewayError> {
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::String(value) => {
            output.push_str(
                &serde_json::to_string(value)
                    .map_err(|_| UiControlGatewayError::InvalidRequest("string"))?,
            );
        }
        Value::Number(value) => {
            if let Some(number) = value.as_u64() {
                if number > MAX_SAFE_INTEGER {
                    return Err(UiControlGatewayError::InvalidRequest("unsafe integer"));
                }
                output.push_str(&number.to_string());
            } else if let Some(number) = value.as_i64() {
                if number.unsigned_abs() > MAX_SAFE_INTEGER {
                    return Err(UiControlGatewayError::InvalidRequest("unsafe integer"));
                }
                output.push_str(&number.to_string());
            } else {
                return Err(UiControlGatewayError::InvalidRequest("non-integer number"));
            }
        }
        Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                write_canonical(value, output)?;
            }
            output.push(']');
        }
        Value::Object(values) => {
            output.push('{');
            let mut keys = values.keys().collect::<Vec<_>>();
            keys.sort_unstable();
            for (index, key) in keys.into_iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                output.push_str(
                    &serde_json::to_string(key)
                        .map_err(|_| UiControlGatewayError::InvalidRequest("object key"))?,
                );
                output.push(':');
                write_canonical(&values[key], output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

fn stable_id(value: String, field: &'static str) -> Result<StableId, UiControlGatewayError> {
    StableId::new(value).map_err(|_| UiControlGatewayError::InvalidRequest(field))
}

fn generation(value: u64, field: &'static str) -> Result<Generation, UiControlGatewayError> {
    if value > MAX_SAFE_INTEGER {
        return Err(UiControlGatewayError::InvalidRequest(field));
    }
    Generation::new(value).map_err(|_| UiControlGatewayError::InvalidRequest(field))
}

fn revision(value: u64, field: &'static str) -> Result<Revision, UiControlGatewayError> {
    if value > MAX_SAFE_INTEGER {
        return Err(UiControlGatewayError::InvalidRequest(field));
    }
    Revision::new(value).map_err(|_| UiControlGatewayError::InvalidRequest(field))
}

fn digest(value: &str, field: &'static str) -> Result<Digest32, UiControlGatewayError> {
    value
        .parse()
        .map_err(|_| UiControlGatewayError::InvalidRequest(field))
}

fn map_durable_error(_: codex_hepta_operations::OperationError) -> UiControlGatewayError {
    UiControlGatewayError::DurableUnavailable
}

pub fn now_unix_ms() -> Result<u64, UiControlGatewayError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| UiControlGatewayError::TimeUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| UiControlGatewayError::TimeUnavailable)
}

#[cfg(test)]
#[path = "control_gateway_tests.rs"]
mod tests;
