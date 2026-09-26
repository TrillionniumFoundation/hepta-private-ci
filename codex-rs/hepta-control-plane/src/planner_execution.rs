use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::GrantRequestSetV1;
use crate::GrantRequestV1;
use crate::PlannerCanonicalEnvelopeV1;
use crate::PlannerStoreError;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CurrentExecutionContextV1 {
    pub observed_at_micros: u64,
    pub revocation_frontier_digest: Digest32,
    pub authority_policy_digest: Digest32,
    pub executor_generation_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorizationDispositionV1 {
    Authorized,
    Denied,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentAuthorizationReceiptV1 {
    pub disposition: AuthorizationDispositionV1,
    pub request_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub current_revocation_frontier_digest: Digest32,
    pub authority_policy_digest: Digest32,
    pub capability_digest: Option<Digest32>,
    pub expires_at_micros: u64,
    pub receipt_digest: Digest32,
}

impl IndependentAuthorizationReceiptV1 {
    pub fn new(
        disposition: AuthorizationDispositionV1,
        request: &GrantRequestV1,
        context: CurrentExecutionContextV1,
        capability_digest: Option<Digest32>,
        expires_at_micros: u64,
    ) -> Result<Self, PlannerExecutionError> {
        validate_context(context)?;
        if expires_at_micros <= context.observed_at_micros
            || expires_at_micros > request.expires_at_micros
        {
            return Err(PlannerExecutionError::AuthorizationMismatch);
        }
        match (disposition, capability_digest) {
            (AuthorizationDispositionV1::Authorized, Some(digest)) if !digest.is_zero() => {}
            (AuthorizationDispositionV1::Denied, None) => {}
            _ => return Err(PlannerExecutionError::AuthorizationMismatch),
        }
        let request_digest = digest_request(request);
        let mut receipt = Self {
            disposition,
            request_digest,
            final_payload_digest: request.final_payload_digest,
            current_revocation_frontier_digest: context.revocation_frontier_digest,
            authority_policy_digest: context.authority_policy_digest,
            capability_digest,
            expires_at_micros,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = digest_authorization(&receipt);
        Ok(receipt)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectDispatchV1 {
    pub request_digest: Digest32,
    pub authorization_receipt_digest: Digest32,
    pub capability_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub executor_generation_digest: Digest32,
    pub dispatch_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EffectObservationDispositionV1 {
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectObservationV1 {
    pub dispatch_digest: Digest32,
    pub disposition: EffectObservationDispositionV1,
    pub observed_outcome_digest: Digest32,
    pub observation_digest: Digest32,
}

impl EffectObservationV1 {
    pub fn new(
        dispatch_digest: Digest32,
        disposition: EffectObservationDispositionV1,
        observed_outcome_digest: Digest32,
    ) -> Result<Self, PlannerExecutionError> {
        if dispatch_digest.is_zero() || observed_outcome_digest.is_zero() {
            return Err(PlannerExecutionError::EmptyDigest);
        }
        let mut value = Self {
            dispatch_digest,
            disposition,
            observed_outcome_digest,
            observation_digest: Digest32::ZERO,
        };
        value.observation_digest = digest_observation(&value);
        Ok(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconciliationDispositionV1 {
    Succeeded,
    Failed,
    StillIndeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReconciliationReceiptV1 {
    pub dispatch_digest: Digest32,
    pub prior_observation_digest: Digest32,
    pub disposition: ReconciliationDispositionV1,
    pub terminal_outcome_digest: Option<Digest32>,
    pub receipt_digest: Digest32,
}

impl ReconciliationReceiptV1 {
    pub fn new(
        dispatch_digest: Digest32,
        prior_observation_digest: Digest32,
        disposition: ReconciliationDispositionV1,
        terminal_outcome_digest: Option<Digest32>,
    ) -> Result<Self, PlannerExecutionError> {
        if dispatch_digest.is_zero() || prior_observation_digest.is_zero() {
            return Err(PlannerExecutionError::EmptyDigest);
        }
        match (disposition, terminal_outcome_digest) {
            (ReconciliationDispositionV1::Succeeded, Some(digest))
            | (ReconciliationDispositionV1::Failed, Some(digest))
                if !digest.is_zero() => {}
            (ReconciliationDispositionV1::StillIndeterminate, None) => {}
            _ => return Err(PlannerExecutionError::ReconciliationMismatch),
        }
        let mut receipt = Self {
            dispatch_digest,
            prior_observation_digest,
            disposition,
            terminal_outcome_digest,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = digest_reconciliation(&receipt);
        Ok(receipt)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutedGrantReceiptV1 {
    pub request_digest: Digest32,
    pub authorization_receipt_digest: Digest32,
    pub dispatch_digest: Option<Digest32>,
    pub terminal_receipt_digest: Digest32,
    pub disposition: ExecutedGrantDispositionV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutedGrantDispositionV1 {
    Denied,
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionBatchReceiptV1 {
    pub plan_receipt_digest: Digest32,
    pub request_set_digest: Digest32,
    pub grants: Vec<ExecutedGrantReceiptV1>,
    pub receipt_digest: Digest32,
}

pub trait IndependentPlannerAuthorityV1 {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        context: CurrentExecutionContextV1,
    ) -> Result<IndependentAuthorizationReceiptV1, PlannerExecutionError>;
}

pub trait PlannerEffectExecutorV1 {
    fn execute(
        &mut self,
        request: &GrantRequestV1,
        dispatch: &EffectDispatchV1,
    ) -> Result<EffectObservationV1, PlannerExecutionError>;
}

pub trait PlannerEffectReconcilerV1 {
    fn reconcile(
        &mut self,
        request: &GrantRequestV1,
        dispatch: &EffectDispatchV1,
        observation: &EffectObservationV1,
    ) -> Result<ReconciliationReceiptV1, PlannerExecutionError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerExecutionError {
    EmptyDigest,
    Expired,
    RequestSetMismatch,
    AuthorizationMismatch,
    ExecutorMismatch,
    ReconciliationMismatch,
    Store(PlannerStoreError),
    AuthorityUnavailable,
    ExecutorUnavailable,
    ReconcilerUnavailable,
}

impl fmt::Display for PlannerExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerExecutionError {}

impl From<PlannerStoreError> for PlannerExecutionError {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error)
    }
}

pub struct PlannerExecutionCoordinatorV1<'a, A, E, R>
where
    A: IndependentPlannerAuthorityV1,
    E: PlannerEffectExecutorV1,
    R: PlannerEffectReconcilerV1,
{
    store: &'a mut PlannerStoreV1,
    authority: &'a mut A,
    executor: &'a mut E,
    reconciler: &'a mut R,
}

impl<'a, A, E, R> PlannerExecutionCoordinatorV1<'a, A, E, R>
where
    A: IndependentPlannerAuthorityV1,
    E: PlannerEffectExecutorV1,
    R: PlannerEffectReconcilerV1,
{
    pub fn new(
        store: &'a mut PlannerStoreV1,
        authority: &'a mut A,
        executor: &'a mut E,
        reconciler: &'a mut R,
    ) -> Self {
        Self {
            store,
            authority,
            executor,
            reconciler,
        }
    }

    pub fn execute_request_set(
        &mut self,
        requests: &GrantRequestSetV1,
        context: CurrentExecutionContextV1,
    ) -> Result<ExecutionBatchReceiptV1, PlannerExecutionError> {
        validate_context(context)?;
        if requests.plan_receipt_digest().is_zero()
            || requests.request_set_digest().is_zero()
            || requests.authority().grants_any()
        {
            return Err(PlannerExecutionError::RequestSetMismatch);
        }
        let recomputed = digest_request_set(requests.plan_receipt_digest(), requests.requests());
        if recomputed != requests.request_set_digest() {
            return Err(PlannerExecutionError::RequestSetMismatch);
        }
        let request_set_body = encode_request_set(requests);
        self.store.append_envelope(PlannerCanonicalEnvelopeV1::new(
            PlannerStoreRecordKindV1::AuthorityRequest,
            stage_identity(
                b"authority-request-set",
                requests.request_set_digest(),
                requests.request_set_digest(),
            ),
            requests.request_set_digest(),
            request_set_body,
        )?)?;

        let mut grants = Vec::with_capacity(requests.requests().len());
        for request in requests.requests() {
            grants.push(self.execute_one(request, context)?);
        }
        let receipt_digest = digest_batch(
            requests.plan_receipt_digest(),
            requests.request_set_digest(),
            &grants,
        );
        Ok(ExecutionBatchReceiptV1 {
            plan_receipt_digest: requests.plan_receipt_digest(),
            request_set_digest: requests.request_set_digest(),
            grants,
            receipt_digest,
        })
    }

    fn execute_one(
        &mut self,
        request: &GrantRequestV1,
        context: CurrentExecutionContextV1,
    ) -> Result<ExecutedGrantReceiptV1, PlannerExecutionError> {
        if request.expires_at_micros <= context.observed_at_micros {
            return Err(PlannerExecutionError::Expired);
        }
        if request.revocation_frontier_digest != context.revocation_frontier_digest {
            return Err(PlannerExecutionError::AuthorizationMismatch);
        }
        let request_digest = digest_request(request);
        let authorization = self.authority.authorize(request, context)?;
        validate_authorization(request, context, &authorization)?;
        self.store.append_envelope(PlannerCanonicalEnvelopeV1::new(
            PlannerStoreRecordKindV1::AuthorityDecision,
            stage_identity(
                b"authority-decision",
                request_digest,
                authorization.receipt_digest,
            ),
            authorization.receipt_digest,
            encode_authorization(&authorization),
        )?)?;

        if authorization.disposition == AuthorizationDispositionV1::Denied {
            return Ok(ExecutedGrantReceiptV1 {
                request_digest,
                authorization_receipt_digest: authorization.receipt_digest,
                dispatch_digest: None,
                terminal_receipt_digest: authorization.receipt_digest,
                disposition: ExecutedGrantDispositionV1::Denied,
            });
        }

        let capability_digest = authorization
            .capability_digest
            .ok_or(PlannerExecutionError::AuthorizationMismatch)?;
        let dispatch = make_dispatch(request, context, &authorization, capability_digest);
        self.store.append_envelope(PlannerCanonicalEnvelopeV1::new(
            PlannerStoreRecordKindV1::EffectDispatch,
            stage_identity(b"effect-dispatch", request_digest, dispatch.dispatch_digest),
            dispatch.dispatch_digest,
            encode_dispatch(&dispatch),
        )?)?;

        let observation = self.executor.execute(request, &dispatch)?;
        validate_observation(&dispatch, &observation)?;
        self.store.append_envelope(PlannerCanonicalEnvelopeV1::new(
            PlannerStoreRecordKindV1::TerminalReceipt,
            stage_identity(
                b"effect-observation",
                dispatch.dispatch_digest,
                observation.observation_digest,
            ),
            observation.observation_digest,
            encode_observation(&observation),
        )?)?;

        match observation.disposition {
            EffectObservationDispositionV1::Succeeded => Ok(ExecutedGrantReceiptV1 {
                request_digest,
                authorization_receipt_digest: authorization.receipt_digest,
                dispatch_digest: Some(dispatch.dispatch_digest),
                terminal_receipt_digest: observation.observation_digest,
                disposition: ExecutedGrantDispositionV1::Succeeded,
            }),
            EffectObservationDispositionV1::Failed => Ok(ExecutedGrantReceiptV1 {
                request_digest,
                authorization_receipt_digest: authorization.receipt_digest,
                dispatch_digest: Some(dispatch.dispatch_digest),
                terminal_receipt_digest: observation.observation_digest,
                disposition: ExecutedGrantDispositionV1::Failed,
            }),
            EffectObservationDispositionV1::Indeterminate => {
                let reconciliation = self.reconciler.reconcile(request, &dispatch, &observation)?;
                validate_reconciliation(&dispatch, &observation, &reconciliation)?;
                self.store.append_envelope(PlannerCanonicalEnvelopeV1::new(
                    PlannerStoreRecordKindV1::Reconciliation,
                    stage_identity(
                        b"effect-reconciliation",
                        dispatch.dispatch_digest,
                        reconciliation.receipt_digest,
                    ),
                    reconciliation.receipt_digest,
                    encode_reconciliation(&reconciliation),
                )?)?;
                let disposition = match reconciliation.disposition {
                    ReconciliationDispositionV1::Succeeded => {
                        ExecutedGrantDispositionV1::Succeeded
                    }
                    ReconciliationDispositionV1::Failed => ExecutedGrantDispositionV1::Failed,
                    ReconciliationDispositionV1::StillIndeterminate => {
                        ExecutedGrantDispositionV1::Indeterminate
                    }
                };
                Ok(ExecutedGrantReceiptV1 {
                    request_digest,
                    authorization_receipt_digest: authorization.receipt_digest,
                    dispatch_digest: Some(dispatch.dispatch_digest),
                    terminal_receipt_digest: reconciliation.receipt_digest,
                    disposition,
                })
            }
        }
    }
}

fn validate_context(context: CurrentExecutionContextV1) -> Result<(), PlannerExecutionError> {
    if context.revocation_frontier_digest.is_zero()
        || context.authority_policy_digest.is_zero()
        || context.executor_generation_digest.is_zero()
    {
        return Err(PlannerExecutionError::EmptyDigest);
    }
    Ok(())
}

fn validate_authorization(
    request: &GrantRequestV1,
    context: CurrentExecutionContextV1,
    receipt: &IndependentAuthorizationReceiptV1,
) -> Result<(), PlannerExecutionError> {
    if receipt.request_digest != digest_request(request)
        || receipt.final_payload_digest != request.final_payload_digest
        || receipt.current_revocation_frontier_digest != context.revocation_frontier_digest
        || receipt.authority_policy_digest != context.authority_policy_digest
        || receipt.expires_at_micros <= context.observed_at_micros
        || receipt.expires_at_micros > request.expires_at_micros
        || receipt.receipt_digest != digest_authorization(receipt)
    {
        return Err(PlannerExecutionError::AuthorizationMismatch);
    }
    match (receipt.disposition, receipt.capability_digest) {
        (AuthorizationDispositionV1::Authorized, Some(digest)) if !digest.is_zero() => Ok(()),
        (AuthorizationDispositionV1::Denied, None) => Ok(()),
        _ => Err(PlannerExecutionError::AuthorizationMismatch),
    }
}

fn make_dispatch(
    request: &GrantRequestV1,
    context: CurrentExecutionContextV1,
    authorization: &IndependentAuthorizationReceiptV1,
    capability_digest: Digest32,
) -> EffectDispatchV1 {
    let request_digest = digest_request(request);
    let mut dispatch = EffectDispatchV1 {
        request_digest,
        authorization_receipt_digest: authorization.receipt_digest,
        capability_digest,
        final_payload_digest: request.final_payload_digest,
        executor_generation_digest: context.executor_generation_digest,
        dispatch_digest: Digest32::ZERO,
    };
    dispatch.dispatch_digest = digest_dispatch(&dispatch);
    dispatch
}

fn validate_observation(
    dispatch: &EffectDispatchV1,
    observation: &EffectObservationV1,
) -> Result<(), PlannerExecutionError> {
    if observation.dispatch_digest != dispatch.dispatch_digest
        || observation.observed_outcome_digest.is_zero()
        || observation.observation_digest != digest_observation(observation)
    {
        return Err(PlannerExecutionError::ExecutorMismatch);
    }
    Ok(())
}

fn validate_reconciliation(
    dispatch: &EffectDispatchV1,
    observation: &EffectObservationV1,
    receipt: &ReconciliationReceiptV1,
) -> Result<(), PlannerExecutionError> {
    if observation.disposition != EffectObservationDispositionV1::Indeterminate
        || receipt.dispatch_digest != dispatch.dispatch_digest
        || receipt.prior_observation_digest != observation.observation_digest
        || receipt.receipt_digest != digest_reconciliation(receipt)
    {
        return Err(PlannerExecutionError::ReconciliationMismatch);
    }
    match (receipt.disposition, receipt.terminal_outcome_digest) {
        (ReconciliationDispositionV1::Succeeded, Some(digest))
        | (ReconciliationDispositionV1::Failed, Some(digest))
            if !digest.is_zero() => Ok(()),
        (ReconciliationDispositionV1::StillIndeterminate, None) => Ok(()),
        _ => Err(PlannerExecutionError::ReconciliationMismatch),
    }
}

fn digest_request(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-grant-request.v1".to_vec();
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    push_digest(&mut bytes, request.plan_digest);
    push_digest(&mut bytes, request.final_payload_digest);
    push_digest(&mut bytes, request.objective_digest);
    push_digest(&mut bytes, request.snapshot_digest);
    push_digest(&mut bytes, request.revocation_frontier_digest);
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_request_set(plan_receipt_digest: Digest32, requests: &[GrantRequestV1]) -> Digest32 {
    let mut bytes = b"hepta.control.grant-request-set.v1".to_vec();
    push_digest(&mut bytes, plan_receipt_digest);
    bytes.extend_from_slice(
        &u32::try_from(requests.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for request in requests {
        push_id(&mut bytes, request.operation_id.as_str());
        push_id(&mut bytes, request.candidate_id.as_str());
        push_digest(&mut bytes, request.plan_digest);
        push_digest(&mut bytes, request.final_payload_digest);
        push_digest(&mut bytes, request.objective_digest);
        push_digest(&mut bytes, request.snapshot_digest);
        push_digest(&mut bytes, request.revocation_frontier_digest);
        bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_authorization(receipt: &IndependentAuthorizationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control.independent-authorization.v1".to_vec();
    bytes.push(match receipt.disposition {
        AuthorizationDispositionV1::Authorized => 1,
        AuthorizationDispositionV1::Denied => 0,
    });
    push_digest(&mut bytes, receipt.request_digest);
    push_digest(&mut bytes, receipt.final_payload_digest);
    push_digest(&mut bytes, receipt.current_revocation_frontier_digest);
    push_digest(&mut bytes, receipt.authority_policy_digest);
    push_optional_digest(&mut bytes, receipt.capability_digest);
    bytes.extend_from_slice(&receipt.expires_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_dispatch(dispatch: &EffectDispatchV1) -> Digest32 {
    let mut bytes = b"hepta.control.effect-dispatch.v1".to_vec();
    push_digest(&mut bytes, dispatch.request_digest);
    push_digest(&mut bytes, dispatch.authorization_receipt_digest);
    push_digest(&mut bytes, dispatch.capability_digest);
    push_digest(&mut bytes, dispatch.final_payload_digest);
    push_digest(&mut bytes, dispatch.executor_generation_digest);
    Digest32::of_bytes(&bytes)
}

fn digest_observation(observation: &EffectObservationV1) -> Digest32 {
    let mut bytes = b"hepta.control.effect-observation.v1".to_vec();
    push_digest(&mut bytes, observation.dispatch_digest);
    bytes.push(match observation.disposition {
        EffectObservationDispositionV1::Succeeded => 0,
        EffectObservationDispositionV1::Failed => 1,
        EffectObservationDispositionV1::Indeterminate => 2,
    });
    push_digest(&mut bytes, observation.observed_outcome_digest);
    Digest32::of_bytes(&bytes)
}

fn digest_reconciliation(receipt: &ReconciliationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control.effect-reconciliation.v1".to_vec();
    push_digest(&mut bytes, receipt.dispatch_digest);
    push_digest(&mut bytes, receipt.prior_observation_digest);
    bytes.push(match receipt.disposition {
        ReconciliationDispositionV1::Succeeded => 0,
        ReconciliationDispositionV1::Failed => 1,
        ReconciliationDispositionV1::StillIndeterminate => 2,
    });
    push_optional_digest(&mut bytes, receipt.terminal_outcome_digest);
    Digest32::of_bytes(&bytes)
}

fn digest_batch(
    plan_receipt_digest: Digest32,
    request_set_digest: Digest32,
    grants: &[ExecutedGrantReceiptV1],
) -> Digest32 {
    let mut bytes = b"hepta.control.execution-batch.v1".to_vec();
    push_digest(&mut bytes, plan_receipt_digest);
    push_digest(&mut bytes, request_set_digest);
    bytes.extend_from_slice(
        &u32::try_from(grants.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for grant in grants {
        push_digest(&mut bytes, grant.request_digest);
        push_digest(&mut bytes, grant.authorization_receipt_digest);
        push_optional_digest(&mut bytes, grant.dispatch_digest);
        push_digest(&mut bytes, grant.terminal_receipt_digest);
        bytes.push(match grant.disposition {
            ExecutedGrantDispositionV1::Denied => 0,
            ExecutedGrantDispositionV1::Succeeded => 1,
            ExecutedGrantDispositionV1::Failed => 2,
            ExecutedGrantDispositionV1::Indeterminate => 3,
        });
    }
    Digest32::of_bytes(&bytes)
}

fn stage_identity(domain: &[u8], parent: Digest32, child: Digest32) -> Digest32 {
    let mut bytes = b"hepta.control.execution-stage-identity.v1".to_vec();
    bytes.extend_from_slice(domain);
    push_digest(&mut bytes, parent);
    push_digest(&mut bytes, child);
    Digest32::of_bytes(&bytes)
}

fn encode_request_set(requests: &GrantRequestSetV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.persisted-grant-request-set.v1".to_vec();
    push_digest(&mut bytes, requests.plan_receipt_digest());
    push_digest(&mut bytes, requests.request_set_digest());
    bytes.extend_from_slice(
        &u32::try_from(requests.requests().len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for request in requests.requests() {
        push_digest(&mut bytes, digest_request(request));
    }
    bytes
}

fn encode_authorization(receipt: &IndependentAuthorizationReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.persisted-authorization.v1".to_vec();
    push_digest(&mut bytes, receipt.receipt_digest);
    push_digest(&mut bytes, receipt.request_digest);
    push_digest(&mut bytes, receipt.final_payload_digest);
    push_digest(&mut bytes, receipt.current_revocation_frontier_digest);
    push_digest(&mut bytes, receipt.authority_policy_digest);
    push_optional_digest(&mut bytes, receipt.capability_digest);
    bytes.extend_from_slice(&receipt.expires_at_micros.to_be_bytes());
    bytes
}

fn encode_dispatch(dispatch: &EffectDispatchV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.persisted-dispatch.v1".to_vec();
    push_digest(&mut bytes, dispatch.dispatch_digest);
    push_digest(&mut bytes, dispatch.request_digest);
    push_digest(&mut bytes, dispatch.authorization_receipt_digest);
    push_digest(&mut bytes, dispatch.capability_digest);
    push_digest(&mut bytes, dispatch.final_payload_digest);
    push_digest(&mut bytes, dispatch.executor_generation_digest);
    bytes
}

fn encode_observation(observation: &EffectObservationV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.persisted-observation.v1".to_vec();
    push_digest(&mut bytes, observation.observation_digest);
    push_digest(&mut bytes, observation.dispatch_digest);
    push_digest(&mut bytes, observation.observed_outcome_digest);
    bytes.push(match observation.disposition {
        EffectObservationDispositionV1::Succeeded => 0,
        EffectObservationDispositionV1::Failed => 1,
        EffectObservationDispositionV1::Indeterminate => 2,
    });
    bytes
}

fn encode_reconciliation(receipt: &ReconciliationReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.persisted-reconciliation.v1".to_vec();
    push_digest(&mut bytes, receipt.receipt_digest);
    push_digest(&mut bytes, receipt.dispatch_digest);
    push_digest(&mut bytes, receipt.prior_observation_digest);
    push_optional_digest(&mut bytes, receipt.terminal_outcome_digest);
    bytes.push(match receipt.disposition {
        ReconciliationDispositionV1::Succeeded => 0,
        ReconciliationDispositionV1::Failed => 1,
        ReconciliationDispositionV1::StillIndeterminate => 2,
    });
    bytes
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    if let Some(value) = value {
        bytes.push(1);
        push_digest(bytes, value);
    } else {
        bytes.push(0);
    }
}

#[cfg(test)]
#[path = "planner_execution_tests.rs"]
mod tests;
