//! Final-use-authorized TaskFlow effect dispatch.
//!
//! The automation owner never mints authority. A step must already be durably
//! claimed in the TaskFlow outbox. Final-use verification burns the signed
//! nonce before a durable provider-attempt row is appended. Once that row
//! exists, the same step attempt can never cross the provider boundary again
//! without provider-owned recovery evidence. Provider observations are durable
//! before they are projected into the TaskFlow step/run state.

use std::future::Future;
use std::pin::Pin;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::AutomationStore;
use crate::TaskFlowCommand;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowRunState;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepReceipt;
use crate::TaskFlowStepState;
use crate::TaskFlowTransition;
use crate::effect_dispatch_ledger::EffectDispatchAttempt;
use crate::effect_dispatch_ledger::EffectDispatchObservationKind;
use crate::effect_dispatch_ledger::EffectDispatchStart;

const MAX_AUTHORIZED_EFFECT_DEPENDENCIES: usize = 128;
const MAX_EFFECT_ID_BYTES: usize = 256;
const MAX_FINAL_USE_ID_BYTES: usize = 128;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorizedEffectDependency {
    pub step_id: String,
    pub state_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorizedEffectIntent {
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub operation_id: String,
    pub subject_id: String,
    pub destination_id: String,
    pub payload_digest: Sha256Digest,
    pub final_use_scope_digest: Sha256Digest,
    pub policy_generation: u64,
    pub expected_predecessor_digest: Option<Sha256Digest>,
    pub dependencies: Vec<AuthorizedEffectDependency>,
    pub compensation_for: Option<String>,
}

impl AuthorizedEffectIntent {
    pub fn digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        self.validate()?;
        let operation = self.operation_intent_v1()?;
        let mut bytes = b"hepta.automation.effect.intent.v2\0".to_vec();
        push_text(&mut bytes, &self.run_id);
        push_text(&mut bytes, &self.step_id);
        bytes.extend_from_slice(&self.attempt.to_be_bytes());
        bytes.extend_from_slice(operation.semantic_digest().as_array());
        bytes.extend_from_slice(
            &u32::try_from(self.dependencies.len())
                .map_err(|_| TaskFlowError::Invalid("effect dependency count".to_string()))?
                .to_be_bytes(),
        );
        for dependency in &self.dependencies {
            push_text(&mut bytes, &dependency.step_id);
            push_digest(&mut bytes, &dependency.state_digest);
        }
        match &self.compensation_for {
            Some(operation_id) => {
                bytes.push(1);
                push_text(&mut bytes, operation_id);
            }
            None => bytes.push(0),
        }
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    fn validate(&self) -> Result<(), TaskFlowError> {
        validate_effect_id(&self.run_id, "run_id", MAX_EFFECT_ID_BYTES)?;
        validate_effect_id(&self.step_id, "step_id", MAX_EFFECT_ID_BYTES)?;
        validate_effect_id(&self.operation_id, "operation_id", MAX_EFFECT_ID_BYTES)?;
        validate_effect_id(&self.subject_id, "subject_id", MAX_FINAL_USE_ID_BYTES)?;
        validate_effect_id(
            &self.destination_id,
            "destination_id",
            MAX_FINAL_USE_ID_BYTES,
        )?;
        validate_nonzero_digest(&self.payload_digest, "payload_digest")?;
        validate_nonzero_digest(&self.final_use_scope_digest, "final_use_scope_digest")?;
        if let Some(predecessor) = &self.expected_predecessor_digest {
            validate_nonzero_digest(predecessor, "expected_predecessor_digest")?;
        }
        if self.attempt == 0 || self.policy_generation == 0 {
            return Err(TaskFlowError::Invalid(
                "effect attempt and policy generation must be nonzero".to_string(),
            ));
        }
        if self.dependencies.len() > MAX_AUTHORIZED_EFFECT_DEPENDENCIES {
            return Err(TaskFlowError::Invalid(
                "effect dependency bound exceeded".to_string(),
            ));
        }
        let mut previous: Option<&str> = None;
        for dependency in &self.dependencies {
            validate_effect_id(
                &dependency.step_id,
                "dependency.step_id",
                MAX_EFFECT_ID_BYTES,
            )?;
            validate_nonzero_digest(&dependency.state_digest, "dependency.state_digest")?;
            if dependency.step_id == self.step_id
                || previous.is_some_and(|value| value >= dependency.step_id.as_str())
            {
                return Err(TaskFlowError::Invalid(
                    "effect dependencies must be strictly ordered and exclude the current step"
                        .to_string(),
                ));
            }
            previous = Some(&dependency.step_id);
        }
        if let Some(operation_id) = &self.compensation_for {
            validate_effect_id(operation_id, "compensation_for", MAX_EFFECT_ID_BYTES)?;
            if operation_id == &self.operation_id {
                return Err(TaskFlowError::Invalid(
                    "effect cannot compensate itself".to_string(),
                ));
            }
        }
        Ok(())
    }

    /// Derive the exact final-use binding inside the automation owner.
    ///
    /// Product callers may transport the signed grant, but they do not get to
    /// supply a second independently mutable binding alongside the effect
    /// intent.
    pub fn final_use_binding(&self) -> Result<FinalUseBinding, AuthorizedEffectError> {
        let intent_digest = self.digest()?;
        Ok(FinalUseBinding {
            subject_id: self.subject_id.clone(),
            destination_id: self.destination_id.clone(),
            request_sha256: digest_bytes(&intent_digest)?,
            scope_sha256: digest_bytes(&self.final_use_scope_digest)?,
            payload_sha256: digest_bytes(&self.payload_digest)?,
        })
    }

    /// Build the kernel-owned authority-free operation contract consumed at
    /// the effect boundary. TaskFlow orchestration identity is layered on top
    /// by `digest()`; it is not duplicated into kernel.operations.
    pub fn operation_intent_v1(&self) -> Result<OperationIntentV1, TaskFlowError> {
        let operation_id = StableId::new(self.operation_id.clone())
            .map_err(|error| TaskFlowError::Invalid(format!("operation_id: {error}")))?;
        let subject_id = StableId::new(self.subject_id.clone())
            .map_err(|error| TaskFlowError::Invalid(format!("subject_id: {error}")))?;
        let destination_id = StableId::new(self.destination_id.clone())
            .map_err(|error| TaskFlowError::Invalid(format!("destination_id: {error}")))?;
        let policy_generation = Generation::new(self.policy_generation)
            .map_err(|error| TaskFlowError::Invalid(format!("policy_generation: {error}")))?;
        OperationIntentV1::new(
            operation_id,
            subject_id,
            destination_id,
            digest32(&self.payload_digest)?,
            digest32(&self.final_use_scope_digest)?,
            policy_generation,
            self.expected_predecessor_digest
                .as_ref()
                .map(digest32)
                .transpose()?,
        )
        .map_err(|error| TaskFlowError::Invalid(format!("kernel operation intent: {error}")))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizedEffectPending {
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub binding_digest: Sha256Digest,
    pub destination_id: String,
    pub authority_epoch: u64,
    pub grant_id: String,
    pub started_at_ms: u64,
}

impl From<EffectDispatchAttempt> for AuthorizedEffectPending {
    fn from(value: EffectDispatchAttempt) -> Self {
        Self {
            run_id: value.run_id,
            step_id: value.step_id,
            attempt: value.attempt,
            intent_digest: value.intent_digest,
            payload_digest: value.payload_digest,
            binding_digest: value.binding_digest,
            destination_id: value.destination_id,
            authority_epoch: value.authority_epoch,
            grant_id: value.grant_id,
            started_at_ms: value.started_at_ms,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorizedEffectOutcome {
    Succeeded,
    Failed,
    Indeterminate,
}

impl AuthorizedEffectOutcome {
    fn observation(self) -> TaskFlowStepObservation {
        match self {
            Self::Succeeded => TaskFlowStepObservation::Succeeded,
            Self::Failed => TaskFlowStepObservation::Failed,
            Self::Indeterminate => TaskFlowStepObservation::Indeterminate,
        }
    }

    fn ledger_kind(self) -> EffectDispatchObservationKind {
        match self {
            Self::Succeeded => EffectDispatchObservationKind::Succeeded,
            Self::Failed => EffectDispatchObservationKind::Failed,
            Self::Indeterminate => EffectDispatchObservationKind::Indeterminate,
        }
    }

    fn reconcile_outcome(self) -> Option<TaskFlowReconcileOutcome> {
        match self {
            Self::Succeeded => Some(TaskFlowReconcileOutcome::Succeeded),
            Self::Failed => Some(TaskFlowReconcileOutcome::Failed),
            Self::Indeterminate => None,
        }
    }
}

/// Observation produced by the registered downstream effect owner. A driver
/// must return `Indeterminate`, never an error, once external dispatch may have
/// happened. `Err` is reserved for failures proven to occur before provider
/// contact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizedEffectProviderReceipt {
    pub outcome: AuthorizedEffectOutcome,
    pub receipt_digest: Sha256Digest,
}

pub struct AuthorizedEffectRequest<'a> {
    pub operation_intent: &'a OperationIntentV1,
    pub intent: &'a AuthorizedEffectIntent,
    pub intent_digest: &'a Sha256Digest,
    /// Exact immutable provider bytes whose digest is bound by `intent` and
    /// the signed final-use grant. Drivers must send these bytes unchanged.
    pub wire_payload: &'a [u8],
    pub binding: &'a FinalUseBinding,
}

/// Registered effect-owner adapter. This synchronous boundary is intentional:
/// `FinalUseAuthority::with_verified_use` holds the current revocation fence
/// through the final check and the actual dispatch call. Drivers must impose
/// their own bounded I/O deadline and return `Indeterminate` after ambiguous
/// provider contact.
pub trait AuthorizedEffectDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError>;
}

pub struct AuthorizedProviderEffectRequest<'a> {
    pub operation_intent: &'a OperationIntentV1,
    pub intent: &'a AuthorizedEffectIntent,
    pub intent_digest: &'a Sha256Digest,
    pub binding: &'a FinalUseBinding,
    pub provider_intent: ProviderEffectIntent,
    pub wire_payload: &'a [u8],
}

pub type AuthorizedEffectFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError>>
            + Send
            + 'a,
    >,
>;

/// Async provider seam for transports that cannot cross their physical
/// boundary synchronously. The caller supplies no provider key: automation
/// derives the key and payload binding from the durable TaskFlow intent.
pub trait AsyncAuthorizedEffectDriver {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthorizedProviderEffectLookup {
    ProvenAbsent { proof_digest: Sha256Digest },
    Observed(AuthorizedEffectProviderReceipt),
    Unresolved,
}

/// Bridge from the provider-effect contract to TaskFlow's authorized effect
/// seam. The provider scope is the exact destination identifier bound by the
/// final-use grant; a driver cannot silently send a TaskFlow effect through a
/// differently configured provider.
pub struct ProviderEffectTaskFlowDriver<A> {
    provider_scope: String,
    adapter: A,
}

impl<A> ProviderEffectTaskFlowDriver<A>
where
    A: ProviderEffectAdapter,
{
    pub fn new(provider_scope: String, adapter: A) -> Result<Self, AuthorizedEffectDriverError> {
        ProviderEffectKey::for_logical_effect(&provider_scope, "taskflow:validation")
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        Ok(Self {
            provider_scope,
            adapter,
        })
    }

    pub fn adapter(&self) -> &A {
        &self.adapter
    }

    pub fn adapter_mut(&mut self) -> &mut A {
        &mut self.adapter
    }

    pub async fn lookup(
        &self,
        pending: &AuthorizedEffectPending,
    ) -> AuthorizedProviderEffectLookup {
        if pending.destination_id != self.provider_scope
            || self.adapter.capability() != ProviderEffectIdempotencyCapability::KeyAndStatusLookup
        {
            return AuthorizedProviderEffectLookup::Unresolved;
        }
        let logical_effect_id = format!("taskflow:{}:{}", pending.run_id, pending.step_id);
        let Ok(key) =
            ProviderEffectKey::for_logical_effect(&pending.destination_id, &logical_effect_id)
        else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let provider_intent = ProviderEffectIntent::new(key, pending.payload_digest.clone());
        match self.adapter.lookup_for_intent(&provider_intent).await {
            ProviderEffectLookup::Ack(ack) => {
                if ack.validate_for(&provider_intent).is_err() {
                    return AuthorizedProviderEffectLookup::Unresolved;
                }
                match provider_receipt_from_ack(&ack) {
                    Some(receipt) => AuthorizedProviderEffectLookup::Observed(receipt),
                    None => AuthorizedProviderEffectLookup::Unresolved,
                }
            }
            ProviderEffectLookup::NotFound => AuthorizedProviderEffectLookup::ProvenAbsent {
                proof_digest: provider_lookup_digest(&provider_intent, b"not_found"),
            },
            ProviderEffectLookup::Conflict { .. } | ProviderEffectLookup::Unknown => {
                AuthorizedProviderEffectLookup::Unresolved
            }
        }
    }
}

impl<A> AsyncAuthorizedEffectDriver for ProviderEffectTaskFlowDriver<A>
where
    A: ProviderEffectAdapter,
{
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            if request.intent.destination_id != self.provider_scope
                || self.adapter.capability()
                    != ProviderEffectIdempotencyCapability::KeyAndStatusLookup
            {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            let provider_intent = request.provider_intent;
            let wire_payload = request.wire_payload;
            let dispatch = self
                .adapter
                .dispatch_with_payload(&provider_intent, wire_payload)
                .await;
            provider_dispatch_receipt(&provider_intent, dispatch)
        })
    }
}

fn provider_effect_intent(
    intent: &AuthorizedEffectIntent,
    wire_payload: &[u8],
) -> Result<ProviderEffectIntent, AuthorizedEffectError> {
    let payload_digest = Sha256Digest::for_bytes(wire_payload);
    if payload_digest != intent.payload_digest {
        return Err(AuthorizedEffectError::BindingMismatch);
    }
    let logical_effect_id = format!("taskflow:{}:{}", intent.run_id, intent.step_id);
    let key = ProviderEffectKey::for_logical_effect(&intent.destination_id, &logical_effect_id)
        .map_err(|_| AuthorizedEffectError::BindingMismatch)?;
    Ok(ProviderEffectIntent::new(key, payload_digest))
}

fn provider_dispatch_receipt(
    intent: &ProviderEffectIntent,
    dispatch: ProviderEffectDispatch,
) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
    match dispatch {
        ProviderEffectDispatch::Ack(ack) => {
            if ack.validate_for(intent).is_err() {
                return Ok(AuthorizedEffectProviderReceipt {
                    outcome: AuthorizedEffectOutcome::Indeterminate,
                    receipt_digest: provider_ack_digest(&ack),
                });
            }
            let outcome = match ack.status {
                ProviderEffectAckStatus::Accepted => AuthorizedEffectOutcome::Indeterminate,
                ProviderEffectAckStatus::Completed => AuthorizedEffectOutcome::Succeeded,
                ProviderEffectAckStatus::Rejected => AuthorizedEffectOutcome::Failed,
            };
            Ok(AuthorizedEffectProviderReceipt {
                outcome,
                receipt_digest: provider_ack_digest(&ack),
            })
        }
        ProviderEffectDispatch::Rejected { reason_code } => {
            let mut bytes = provider_receipt_prefix(intent, b"rejected");
            bytes.extend_from_slice(reason_code.as_bytes());
            Ok(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Failed,
                receipt_digest: Sha256Digest::for_bytes(&bytes),
            })
        }
        ProviderEffectDispatch::NotDispatched { .. } => {
            Err(AuthorizedEffectDriverError::BeforeProviderContact)
        }
        ProviderEffectDispatch::Unknown => Ok(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Indeterminate,
            receipt_digest: provider_lookup_digest(intent, b"unknown"),
        }),
    }
}

fn provider_receipt_from_ack(ack: &ProviderEffectAck) -> Option<AuthorizedEffectProviderReceipt> {
    let outcome = match ack.status {
        ProviderEffectAckStatus::Accepted => return None,
        ProviderEffectAckStatus::Completed => AuthorizedEffectOutcome::Succeeded,
        ProviderEffectAckStatus::Rejected => AuthorizedEffectOutcome::Failed,
    };
    Some(AuthorizedEffectProviderReceipt {
        outcome,
        receipt_digest: provider_ack_digest(ack),
    })
}

fn provider_ack_digest(ack: &ProviderEffectAck) -> Sha256Digest {
    let mut bytes = b"hepta.automation.provider-effect.ack.v1\0".to_vec();
    bytes.extend_from_slice(ack.key.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(ack.payload_sha256.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(ack.provider_operation_id_sha256.as_str().as_bytes());
    bytes.push(match ack.status {
        ProviderEffectAckStatus::Accepted => 1,
        ProviderEffectAckStatus::Completed => 2,
        ProviderEffectAckStatus::Rejected => 3,
    });
    Sha256Digest::for_bytes(&bytes)
}

fn provider_lookup_digest(intent: &ProviderEffectIntent, observation: &[u8]) -> Sha256Digest {
    let mut bytes = provider_receipt_prefix(intent, b"lookup");
    bytes.extend_from_slice(observation);
    Sha256Digest::for_bytes(&bytes)
}

fn provider_receipt_prefix(intent: &ProviderEffectIntent, phase: &[u8]) -> Vec<u8> {
    let mut bytes = b"hepta.automation.provider-effect.v1\0".to_vec();
    bytes.extend_from_slice(phase);
    bytes.push(0);
    bytes.extend_from_slice(intent.key.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(intent.payload_sha256.as_str().as_bytes());
    bytes.push(0);
    bytes
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum AuthorizedEffectDriverError {
    #[error("effect driver rejected the request before provider contact")]
    BeforeProviderContact,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthorizedEffectRecovery {
    /// The registered provider owner proves the immutable dispatch identity was
    /// never accepted. This is the only recovery that permits a fresh attempt.
    ProvenAbsent { proof_digest: Sha256Digest },
    /// The provider owner reports the already-observed outcome. This never
    /// dispatches; it only appends evidence and repairs TaskFlow projection.
    Observed(AuthorizedEffectProviderReceipt),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthorizedEffectRecoveryResult {
    ProvenAbsent,
    Observed(TaskFlowStepReceipt),
}

#[derive(Debug, Error)]
pub enum AuthorizedEffectError {
    #[error(transparent)]
    TaskFlow(#[from] TaskFlowError),
    #[error("final-use authority rejected the effect: {0}")]
    FinalUse(FinalUseError),
    #[error("final-use binding does not match the durable TaskFlow intent/payload")]
    BindingMismatch,
    #[error("durable provider-contact evidence exists; reconcile it before any retry")]
    RecoveryRequired,
    #[error("provider absence was proved; allocate a new fenced step attempt before retry")]
    ProvenAbsentNeedsNewAttempt,
    #[error(transparent)]
    Driver(#[from] AuthorizedEffectDriverError),
}

impl AutomationStore {
    /// Observe an already settled effect under the automation owner's read
    /// boundary. Exact intent, payload, binding, command and terminal evidence
    /// must match. No lease is renewed, grant consumed or provider contacted.
    /// In-flight/indeterminate observations return None and still require the
    /// ordinary current-fence reconciliation path.
    pub async fn read_authorized_taskflow_effect_receipt(
        &self,
        intent: &AuthorizedEffectIntent,
        command_id: &str,
    ) -> Result<Option<TaskFlowStepReceipt>, AuthorizedEffectError> {
        let binding = intent.final_use_binding()?;
        let intent_digest = intent.digest()?;
        let Some(durable) = self
            .effect_dispatch_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
        else {
            return Ok(None);
        };
        ensure_attempt_binding(
            &durable,
            &intent_digest,
            &intent.payload_digest,
            &final_use_binding_digest(&binding)?,
            &binding,
            command_id,
        )?;
        let Some(observation) = &durable.observation else {
            return Ok(None);
        };
        let expected = match observation.kind {
            EffectDispatchObservationKind::Succeeded => TaskFlowStepObservation::Succeeded,
            EffectDispatchObservationKind::Failed => TaskFlowStepObservation::Failed,
            EffectDispatchObservationKind::Indeterminate
            | EffectDispatchObservationKind::ProvenAbsent => return Ok(None),
        };
        let Some(step) = self
            .read_terminal_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
        else {
            return Ok(None);
        };
        let matches_outcome =
            step.final_outcome
                .map_or(step.observation == Some(expected), |outcome| {
                    matches!(
                        (expected, outcome),
                        (
                            TaskFlowStepObservation::Succeeded,
                            TaskFlowReconcileOutcome::Succeeded
                        ) | (
                            TaskFlowStepObservation::Failed,
                            TaskFlowReconcileOutcome::Failed
                        )
                    )
                });
        if step.intent_digest != intent_digest
            || step.payload_digest != intent.payload_digest
            || step.receipt_digest.as_ref() != Some(&observation.evidence_digest)
            || !matches_outcome
        {
            return Err(TaskFlowError::Conflict(
                "terminal step differs from durable provider evidence".to_string(),
            )
            .into());
        }
        Ok(Some(step))
    }

    /// Dispatch one already-claimed durable TaskFlow step through a final-use
    /// authorized provider seam.
    ///
    /// The order is strict:
    /// 1. verify the claimed durable step and final-use binding;
    /// 2. durably consume the signed final-use nonce;
    /// 3. append an immutable provider-attempt row;
    /// 4. cross the provider boundary at most once for this step attempt;
    /// 5. append provider observation before TaskFlow projection changes;
    /// 6. project the observation into the step/run and reconcile terminal
    ///    outcomes explicitly.
    ///
    /// If a process dies after step 3, a subsequent call returns
    /// `RecoveryRequired` and cannot re-dispatch even with a fresh grant.
    pub async fn execute_authorized_taskflow_effect<D: AuthorizedEffectDriver>(
        &self,
        authority: &FinalUseAuthority,
        driver: &mut D,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        fence: &TaskFlowFence,
        signed_grant: &SignedFinalUseGrant,
        expected_binding: &FinalUseBinding,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        let operation_intent = intent.operation_intent_v1()?;
        if Sha256Digest::for_bytes(wire_payload) != intent.payload_digest {
            return Err(AuthorizedEffectError::BindingMismatch);
        }
        let intent_digest = intent.digest()?;
        let payload_digest = &intent.payload_digest;
        let current = self
            .read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, fence)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict(
                    "authorized effect requires a prepared and claimed durable step".to_string(),
                )
            })?;
        if current.state != TaskFlowStepState::Claimed
            || current.intent_digest != intent_digest
            || current.payload_digest != *payload_digest
        {
            return Err(TaskFlowError::Conflict(
                "authorized effect does not match the claimed durable step".to_string(),
            )
            .into());
        }
        if expected_binding.subject_id != intent.subject_id
            || expected_binding.destination_id != intent.destination_id
            || expected_binding.request_sha256 != digest_bytes(&intent_digest)?
            || expected_binding.scope_sha256 != digest_bytes(&intent.final_use_scope_digest)?
            || expected_binding.payload_sha256 != digest_bytes(payload_digest)?
        {
            return Err(AuthorizedEffectError::BindingMismatch);
        }
        let binding_digest = final_use_binding_digest(expected_binding)?;

        // A durable provider-attempt row is an at-most-once barrier for this
        // exact step attempt. Never burn another grant or call the driver when
        // recovery evidence already exists.
        if let Some(existing) = self
            .effect_dispatch_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
        {
            ensure_attempt_binding(
                &existing,
                &intent_digest,
                payload_digest,
                &binding_digest,
                expected_binding,
                command_id,
            )?;
            return match self
                .settle_effect_dispatch_attempt(&existing, fence)
                .await?
            {
                AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(receipt),
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt)
                }
            };
        }

        let token = authority
            .claim(signed_grant, expected_binding)
            .map_err(AuthorizedEffectError::FinalUse)?;
        let nonce_digest = Sha256Digest::for_bytes(&signed_grant.grant.nonce);
        let start = self
            .begin_effect_dispatch_attempt(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                &intent_digest,
                payload_digest,
                &binding_digest,
                &expected_binding.destination_id,
                signed_grant.grant.authority_epoch,
                &signed_grant.grant.grant_id,
                &nonce_digest,
                command_id,
                now_ms,
            )
            .await?;
        let durable = match start {
            EffectDispatchStart::Inserted(durable) => durable,
            EffectDispatchStart::Existing(durable) => {
                ensure_attempt_binding(
                    &durable,
                    &intent_digest,
                    payload_digest,
                    &binding_digest,
                    expected_binding,
                    command_id,
                )?;
                return match self.settle_effect_dispatch_attempt(&durable, fence).await? {
                    AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(receipt),
                    AuthorizedEffectRecoveryResult::ProvenAbsent => {
                        Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt)
                    }
                };
            }
        };

        let request = AuthorizedEffectRequest {
            operation_intent: &operation_intent,
            intent,
            intent_digest: &intent_digest,
            wire_payload,
            binding: expected_binding,
        };
        let provider = match authority
            .with_verified_use_async_with_witness(token, expected_binding, |witness| async move {
                self.record_effect_dispatch_authority_witness(
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                    &witness,
                )
                .await?;
                driver
                    .dispatch(&request)
                    .map_err(AuthorizedEffectError::Driver)
            })
            .await
        {
            Ok((Ok(receipt), _witness)) => receipt,
            Ok((Err(AuthorizedEffectError::Driver(error)), _witness)) => {
                let proof = no_contact_digest(&durable, "driver_before_provider_contact");
                let durable = self
                    .record_effect_dispatch_observation(
                        &intent.run_id,
                        &intent.step_id,
                        intent.attempt,
                        EffectDispatchObservationKind::ProvenAbsent,
                        &proof,
                        now_ms,
                    )
                    .await?;
                self.settle_effect_dispatch_attempt(&durable, fence).await?;
                return Err(AuthorizedEffectError::Driver(error));
            }
            Ok((Err(error), _witness)) => return Err(error),
            Err(error) => {
                // `with_verified_use` invokes the consumer only after its
                // final revocation/epoch check succeeds, so this path is a
                // local proof that the provider driver was not called.
                let proof = no_contact_digest(&durable, "final_use_pre_dispatch_rejection");
                let durable = self
                    .record_effect_dispatch_observation(
                        &intent.run_id,
                        &intent.step_id,
                        intent.attempt,
                        EffectDispatchObservationKind::ProvenAbsent,
                        &proof,
                        now_ms,
                    )
                    .await?;
                self.settle_effect_dispatch_attempt(&durable, fence).await?;
                return Err(AuthorizedEffectError::FinalUse(error));
            }
        };
        validate_receipt_digest(&provider.receipt_digest)?;
        let durable = self
            .record_effect_dispatch_observation(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                provider.outcome.ledger_kind(),
                &provider.receipt_digest,
                now_ms,
            )
            .await?;
        match self.settle_effect_dispatch_attempt(&durable, fence).await? {
            AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(receipt),
            AuthorizedEffectRecoveryResult::ProvenAbsent => {
                Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt)
            }
        }
    }

    /// Read one exact durable provider-contact attempt by its immutable
    /// TaskFlow identity. This avoids bounded-list intersection in product
    /// reconciliation and never authorizes redispatch.
    pub async fn authorized_taskflow_effect_attempt(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<AuthorizedEffectPending>, AuthorizedEffectError> {
        Ok(self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .map(AuthorizedEffectPending::from))
    }

    /// Read the immutable, non-authorizing witness emitted at the exact
    /// final-use dispatch-entry cut. Absence means no durable witness is known;
    /// it never authorizes retry or proves provider absence by itself.
    pub async fn authorized_taskflow_effect_authority_witness(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<VerifiedUseTokenWitnessV1>, AuthorizedEffectError> {
        Ok(self
            .effect_dispatch_authority_witness(run_id, step_id, attempt)
            .await?)
    }

    /// Settle already-durable local provider evidence into TaskFlow before a
    /// product reconciler performs any fresh provider status I/O. A missing
    /// observation returns `None`; an indeterminate observation remains
    /// non-terminal and callers may then perform owner-specific lookup.
    pub async fn settle_authorized_taskflow_effect_observation(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
    ) -> Result<Option<AuthorizedEffectRecoveryResult>, AuthorizedEffectError> {
        let Some(durable) = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
        else {
            return Ok(None);
        };
        if durable.observation.is_none() {
            return Ok(None);
        }
        Ok(Some(
            self.settle_effect_dispatch_attempt(&durable, fence).await?,
        ))
    }

    /// Async provider variant for exact caller-supplied wire bytes.
    ///
    /// The wire payload is hashed inside automation and must equal the durable
    /// TaskFlow payload digest before a final-use nonce is consumed.  A
    /// provider-stable logical key is then derived from destination + run +
    /// step, deliberately excluding the local attempt so a safely retried
    /// attempt reuses the same provider occurrence identity.
    pub async fn execute_authorized_taskflow_effect_async<D: AsyncAuthorizedEffectDriver>(
        &self,
        authority: &FinalUseAuthority,
        driver: &mut D,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        fence: &TaskFlowFence,
        signed_grant: &SignedFinalUseGrant,
        expected_binding: &FinalUseBinding,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        let provider_intent = provider_effect_intent(intent, wire_payload)?;
        let operation_intent = intent.operation_intent_v1()?;
        let intent_digest = intent.digest()?;
        let payload_digest = &intent.payload_digest;
        let current = self
            .read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, fence)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict(
                    "authorized effect requires a prepared and claimed durable step".to_string(),
                )
            })?;
        if current.state != TaskFlowStepState::Claimed
            || current.intent_digest != intent_digest
            || current.payload_digest != *payload_digest
        {
            return Err(TaskFlowError::Conflict(
                "authorized effect does not match the claimed durable step".to_string(),
            )
            .into());
        }
        if expected_binding.subject_id != intent.subject_id
            || expected_binding.destination_id != intent.destination_id
            || expected_binding.request_sha256 != digest_bytes(&intent_digest)?
            || expected_binding.scope_sha256 != digest_bytes(&intent.final_use_scope_digest)?
            || expected_binding.payload_sha256 != digest_bytes(payload_digest)?
        {
            return Err(AuthorizedEffectError::BindingMismatch);
        }
        let binding_digest = final_use_binding_digest(expected_binding)?;

        if let Some(existing) = self
            .effect_dispatch_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
        {
            ensure_attempt_binding(
                &existing,
                &intent_digest,
                payload_digest,
                &binding_digest,
                expected_binding,
                command_id,
            )?;
            return match self
                .settle_effect_dispatch_attempt(&existing, fence)
                .await?
            {
                AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(receipt),
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt)
                }
            };
        }

        let token = authority
            .claim(signed_grant, expected_binding)
            .map_err(AuthorizedEffectError::FinalUse)?;
        let nonce_digest = Sha256Digest::for_bytes(&signed_grant.grant.nonce);
        let start = self
            .begin_effect_dispatch_attempt(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                &intent_digest,
                payload_digest,
                &binding_digest,
                &expected_binding.destination_id,
                signed_grant.grant.authority_epoch,
                &signed_grant.grant.grant_id,
                &nonce_digest,
                command_id,
                now_ms,
            )
            .await?;
        let durable = match start {
            EffectDispatchStart::Inserted(durable) => durable,
            EffectDispatchStart::Existing(durable) => {
                ensure_attempt_binding(
                    &durable,
                    &intent_digest,
                    payload_digest,
                    &binding_digest,
                    expected_binding,
                    command_id,
                )?;
                return match self.settle_effect_dispatch_attempt(&durable, fence).await? {
                    AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(receipt),
                    AuthorizedEffectRecoveryResult::ProvenAbsent => {
                        Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt)
                    }
                };
            }
        };

        let request = AuthorizedProviderEffectRequest {
            operation_intent: &operation_intent,
            intent,
            intent_digest: &intent_digest,
            binding: expected_binding,
            provider_intent,
            wire_payload,
        };
        let provider = match authority
            .with_verified_use_async_with_witness(token, expected_binding, |witness| async move {
                self.record_effect_dispatch_authority_witness(
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                    &witness,
                )
                .await?;
                driver
                    .dispatch(request)
                    .await
                    .map_err(AuthorizedEffectError::Driver)
            })
            .await
        {
            Ok((Ok(receipt), _witness)) => receipt,
            Ok((Err(AuthorizedEffectError::Driver(error)), _witness)) => {
                let proof = no_contact_digest(&durable, "driver_before_provider_contact");
                let durable = self
                    .record_effect_dispatch_observation(
                        &intent.run_id,
                        &intent.step_id,
                        intent.attempt,
                        EffectDispatchObservationKind::ProvenAbsent,
                        &proof,
                        now_ms,
                    )
                    .await?;
                self.settle_effect_dispatch_attempt(&durable, fence).await?;
                return Err(AuthorizedEffectError::Driver(error));
            }
            Ok((Err(error), _witness)) => return Err(error),
            Err(error) => {
                let proof = no_contact_digest(&durable, "final_use_pre_dispatch_rejection");
                let durable = self
                    .record_effect_dispatch_observation(
                        &intent.run_id,
                        &intent.step_id,
                        intent.attempt,
                        EffectDispatchObservationKind::ProvenAbsent,
                        &proof,
                        now_ms,
                    )
                    .await?;
                self.settle_effect_dispatch_attempt(&durable, fence).await?;
                return Err(AuthorizedEffectError::FinalUse(error));
            }
        };
        validate_receipt_digest(&provider.receipt_digest)?;
        let durable = self
            .record_effect_dispatch_observation(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                provider.outcome.ledger_kind(),
                &provider.receipt_digest,
                now_ms,
            )
            .await?;
        match self.settle_effect_dispatch_attempt(&durable, fence).await? {
            AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(receipt),
            AuthorizedEffectRecoveryResult::ProvenAbsent => {
                Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt)
            }
        }
    }

    /// Return bounded provider-contact attempts that have no durable provider
    /// observation yet. A restart reconciler must hand these immutable
    /// identities to the registered downstream effect owner; this scan never
    /// redispatches and never interprets absence of a local row as provider
    /// absence.
    pub async fn pending_authorized_taskflow_effects(
        &self,
        limit: usize,
    ) -> Result<Vec<AuthorizedEffectPending>, AuthorizedEffectError> {
        Ok(self
            .pending_effect_dispatch_attempts(limit)
            .await?
            .into_iter()
            .map(AuthorizedEffectPending::from)
            .collect())
    }

    /// Append provider-owned recovery evidence for an already-started durable
    /// effect attempt. This method never calls the provider or consumes a new
    /// grant; callers must obtain the observation through the registered owner.
    pub async fn recover_authorized_taskflow_effect(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        recovery: AuthorizedEffectRecovery,
        observed_at_ms: u64,
    ) -> Result<AuthorizedEffectRecoveryResult, AuthorizedEffectError> {
        self.effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or(AuthorizedEffectError::RecoveryRequired)?;
        let (kind, evidence) = match recovery {
            AuthorizedEffectRecovery::ProvenAbsent { proof_digest } => {
                validate_receipt_digest(&proof_digest)?;
                (EffectDispatchObservationKind::ProvenAbsent, proof_digest)
            }
            AuthorizedEffectRecovery::Observed(receipt) => {
                validate_receipt_digest(&receipt.receipt_digest)?;
                (receipt.outcome.ledger_kind(), receipt.receipt_digest)
            }
        };
        let durable = self
            .record_effect_dispatch_observation(
                run_id,
                step_id,
                attempt,
                kind,
                &evidence,
                observed_at_ms,
            )
            .await?;
        self.settle_effect_dispatch_attempt(&durable, fence).await
    }

    async fn settle_effect_dispatch_attempt(
        &self,
        durable: &EffectDispatchAttempt,
        fence: &TaskFlowFence,
    ) -> Result<AuthorizedEffectRecoveryResult, AuthorizedEffectError> {
        let Some(observation) = &durable.observation else {
            return Err(AuthorizedEffectError::RecoveryRequired);
        };

        if observation.kind == EffectDispatchObservationKind::ProvenAbsent {
            self.requeue_effect_after_proven_absence(durable, fence, observation)
                .await?;
            return Ok(AuthorizedEffectRecoveryResult::ProvenAbsent);
        }

        let outcome = match observation.kind {
            EffectDispatchObservationKind::Succeeded => AuthorizedEffectOutcome::Succeeded,
            EffectDispatchObservationKind::Failed => AuthorizedEffectOutcome::Failed,
            EffectDispatchObservationKind::Indeterminate => AuthorizedEffectOutcome::Indeterminate,
            EffectDispatchObservationKind::ProvenAbsent => unreachable!(),
        };
        let step = self
            .read_taskflow_step(&durable.run_id, &durable.step_id, durable.attempt, fence)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict(
                    "provider observation has no durable TaskFlow step".to_string(),
                )
            })?;
        let step = match step.state {
            TaskFlowStepState::Claimed => {
                self.record_taskflow_step(
                    &durable.run_id,
                    &durable.step_id,
                    durable.attempt,
                    fence,
                    &durable.intent_digest,
                    &durable.payload_digest,
                    &durable.record_command_id,
                    &observation.evidence_digest,
                    outcome.observation(),
                    observation.observed_at_ms,
                )
                .await?
                .receipt
            }
            TaskFlowStepState::Recorded => {
                if step.observation == Some(TaskFlowStepObservation::Indeterminate) {
                    if let Some(terminal) = outcome.reconcile_outcome() {
                        self.reconcile_taskflow_step(
                            &durable.run_id,
                            &durable.step_id,
                            durable.attempt,
                            fence,
                            &durable.intent_digest,
                            &durable.payload_digest,
                            &effect_command_id("step-reconcile", durable),
                            &observation.evidence_digest,
                            terminal,
                            observation.observed_at_ms,
                        )
                        .await?
                        .receipt
                    } else {
                        step
                    }
                } else {
                    if step.receipt_digest.as_ref() != Some(&observation.evidence_digest)
                        || step.observation != Some(outcome.observation())
                    {
                        return Err(TaskFlowError::Conflict(
                            "TaskFlow step is recorded with different provider evidence"
                                .to_string(),
                        )
                        .into());
                    }
                    step
                }
            }
            TaskFlowStepState::Reconciled => {
                let terminal = outcome.reconcile_outcome().ok_or_else(|| {
                    TaskFlowError::Conflict(
                        "reconciled TaskFlow step cannot return to indeterminate".to_string(),
                    )
                })?;
                if step.receipt_digest.as_ref() != Some(&observation.evidence_digest)
                    || step.final_outcome != Some(terminal)
                {
                    return Err(TaskFlowError::Conflict(
                        "TaskFlow step reconciliation is bound to different evidence".to_string(),
                    )
                    .into());
                }
                step
            }
            TaskFlowStepState::Prepared => {
                return Err(TaskFlowError::Conflict(
                    "provider observation precedes durable step claim".to_string(),
                )
                .into());
            }
        };

        self.quarantine_effect_run(durable, fence, observation)
            .await?;
        if let Some(terminal) = outcome.reconcile_outcome() {
            self.reconcile_effect_run(durable, fence, observation, terminal)
                .await?;
        }
        Ok(AuthorizedEffectRecoveryResult::Observed(step))
    }

    async fn quarantine_effect_run(
        &self,
        durable: &EffectDispatchAttempt,
        fence: &TaskFlowFence,
        observation: &crate::effect_dispatch_ledger::EffectDispatchObservation,
    ) -> Result<(), AuthorizedEffectError> {
        let run = self
            .taskflow_run(&durable.run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("effect TaskFlow run vanished".to_string()))?;
        match run.state {
            TaskFlowRunState::Running => {
                let command = TaskFlowCommand::new(
                    run.run_id.clone(),
                    effect_command_id("quarantine", durable),
                    fence.clone(),
                    run.revision,
                    TaskFlowTransition::Indeterminate {
                        reason: format!(
                            "durable provider observation: {}",
                            observation.kind.as_str()
                        ),
                    },
                    observation.observed_at_ms,
                )?;
                self.apply_taskflow_effect_observation_quarantine(&command)
                    .await?;
                Ok(())
            }
            TaskFlowRunState::Indeterminate => Ok(()),
            TaskFlowRunState::Succeeded | TaskFlowRunState::Failed => Ok(()),
            _ => Err(TaskFlowError::Conflict(
                "effect TaskFlow run cannot accept provider observation".to_string(),
            )
            .into()),
        }
    }

    async fn reconcile_effect_run(
        &self,
        durable: &EffectDispatchAttempt,
        fence: &TaskFlowFence,
        observation: &crate::effect_dispatch_ledger::EffectDispatchObservation,
        terminal: TaskFlowReconcileOutcome,
    ) -> Result<(), AuthorizedEffectError> {
        let run = self
            .taskflow_run(&durable.run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("effect TaskFlow run vanished".to_string()))?;
        let already_terminal = matches!(
            (run.state, terminal),
            (
                TaskFlowRunState::Succeeded,
                TaskFlowReconcileOutcome::Succeeded
            ) | (TaskFlowRunState::Failed, TaskFlowReconcileOutcome::Failed)
        );
        if already_terminal {
            return Ok(());
        }
        if run.state != TaskFlowRunState::Indeterminate {
            return Err(TaskFlowError::Conflict(
                "effect TaskFlow run is not awaiting reconciliation".to_string(),
            )
            .into());
        }
        let command = TaskFlowCommand::new(
            run.run_id.clone(),
            effect_command_id("reconcile", durable),
            fence.clone(),
            run.revision,
            TaskFlowTransition::Reconcile {
                receipt_digest: observation.evidence_digest.clone(),
                outcome: terminal,
            },
            observation.observed_at_ms,
        )?;
        self.apply_taskflow_command(&command).await?;
        Ok(())
    }

    async fn requeue_effect_after_proven_absence(
        &self,
        durable: &EffectDispatchAttempt,
        fence: &TaskFlowFence,
        observation: &crate::effect_dispatch_ledger::EffectDispatchObservation,
    ) -> Result<(), AuthorizedEffectError> {
        let run = self
            .taskflow_run(&durable.run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("effect TaskFlow run vanished".to_string()))?;
        if run.state == TaskFlowRunState::Queued {
            return Ok(());
        }
        if !matches!(
            run.state,
            TaskFlowRunState::Running | TaskFlowRunState::Indeterminate
        ) {
            return Err(TaskFlowError::Conflict(
                "provider absence cannot requeue the current TaskFlow run state".to_string(),
            )
            .into());
        }

        let step = self
            .read_taskflow_step(&durable.run_id, &durable.step_id, durable.attempt, fence)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("effect TaskFlow step vanished".to_string()))?;
        match step.state {
            TaskFlowStepState::Claimed => {
                self.cancel_taskflow_step_after_proven_absence(
                    &durable.run_id,
                    &durable.step_id,
                    durable.attempt,
                    fence,
                    &durable.intent_digest,
                    &durable.payload_digest,
                    &provider_absence_step_command_id(durable),
                    &observation.evidence_digest,
                    observation.observed_at_ms,
                )
                .await?;
            }
            TaskFlowStepState::Recorded
                if step.observation == Some(TaskFlowStepObservation::Indeterminate) =>
            {
                self.reconcile_taskflow_step(
                    &durable.run_id,
                    &durable.step_id,
                    durable.attempt,
                    fence,
                    &durable.intent_digest,
                    &durable.payload_digest,
                    &effect_command_id("step-absent-reconcile", durable),
                    &observation.evidence_digest,
                    TaskFlowReconcileOutcome::Cancelled,
                    observation.observed_at_ms,
                )
                .await?;
            }
            TaskFlowStepState::Reconciled
                if step.final_outcome == Some(TaskFlowReconcileOutcome::Cancelled)
                    && step.receipt_digest.as_ref() == Some(&observation.evidence_digest) => {}
            _ => {
                return Err(TaskFlowError::Conflict(
                    "provider absence requires claimed or indeterminate step state".to_string(),
                )
                .into());
            }
        }

        let run = self
            .taskflow_run(&durable.run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("effect TaskFlow run vanished".to_string()))?;
        if run.state == TaskFlowRunState::Queued {
            return Ok(());
        }
        let command = TaskFlowCommand::new(
            run.run_id.clone(),
            effect_command_id("requeue-absent", durable),
            fence.clone(),
            run.revision,
            TaskFlowTransition::RequeueProvenAbsent {
                proof_digest: observation.evidence_digest.clone(),
            },
            observation.observed_at_ms,
        )?;
        self.apply_taskflow_requeue_proven_absent(&command).await?;
        Ok(())
    }
}

fn validate_effect_id(value: &str, field: &str, maximum: usize) -> Result<(), TaskFlowError> {
    if value.is_empty()
        || value.len() > maximum
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_+-.:/".contains(&byte))
    {
        return Err(TaskFlowError::Invalid(format!(
            "invalid authorized effect {field}"
        )));
    }
    Ok(())
}

fn validate_nonzero_digest(digest: &Sha256Digest, field: &str) -> Result<(), TaskFlowError> {
    let value = digest.as_str();
    if value == ZERO_DIGEST
        || value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(TaskFlowError::Invalid(format!(
            "invalid authorized effect {field}"
        )));
    }
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, digest: &Sha256Digest) {
    bytes.extend_from_slice(digest.as_str().as_bytes());
}

fn ensure_attempt_binding(
    durable: &EffectDispatchAttempt,
    intent_digest: &Sha256Digest,
    payload_digest: &Sha256Digest,
    binding_digest: &Sha256Digest,
    binding: &FinalUseBinding,
    command_id: &str,
) -> Result<(), AuthorizedEffectError> {
    if durable.intent_digest != *intent_digest
        || durable.payload_digest != *payload_digest
        || durable.binding_digest != *binding_digest
        || durable.destination_id != binding.destination_id
        || durable.record_command_id != command_id
    {
        return Err(TaskFlowError::Conflict(
            "durable effect attempt is bound to different request bytes".to_string(),
        )
        .into());
    }
    Ok(())
}

fn final_use_binding_digest(
    binding: &FinalUseBinding,
) -> Result<Sha256Digest, AuthorizedEffectError> {
    let bytes = serde_json::to_vec(binding)
        .map_err(|_| TaskFlowError::Corrupt("final-use binding serialization".to_string()))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn effect_command_id(phase: &str, durable: &EffectDispatchAttempt) -> String {
    let mut bytes = b"hepta.automation.effect.command.v1\0".to_vec();
    bytes.extend_from_slice(phase.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(durable.run_id.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(durable.step_id.as_bytes());
    bytes.extend_from_slice(&durable.attempt.to_be_bytes());
    format!(
        "effect:{phase}:{}",
        Sha256Digest::for_bytes(&bytes).as_str()
    )
}

fn provider_absence_step_command_id(durable: &EffectDispatchAttempt) -> String {
    let mut bytes = b"hepta.automation.step.provider-absent.v1\0".to_vec();
    bytes.extend_from_slice(durable.run_id.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(durable.step_id.as_bytes());
    bytes.extend_from_slice(&durable.attempt.to_be_bytes());
    bytes.extend_from_slice(durable.binding_digest.as_str().as_bytes());
    format!(
        "automation:step:provider-absent:effect:{}",
        Sha256Digest::for_bytes(&bytes).as_str()
    )
}

fn no_contact_digest(durable: &EffectDispatchAttempt, reason: &str) -> Sha256Digest {
    let mut bytes = b"hepta.automation.effect.no-contact.v1\0".to_vec();
    bytes.extend_from_slice(durable.run_id.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(durable.step_id.as_bytes());
    bytes.extend_from_slice(&durable.attempt.to_be_bytes());
    bytes.extend_from_slice(durable.binding_digest.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(reason.as_bytes());
    Sha256Digest::for_bytes(&bytes)
}

fn digest32(digest: &Sha256Digest) -> Result<Digest32, TaskFlowError> {
    digest
        .as_str()
        .parse::<Digest32>()
        .map_err(|_| TaskFlowError::Invalid("non-canonical sha256 digest".to_string()))
}

fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], AuthorizedEffectError> {
    let value = digest.as_str().as_bytes();
    if value.len() != 64 {
        return Err(AuthorizedEffectError::BindingMismatch);
    }
    let mut output = [0_u8; 32];
    for (index, pair) in value.chunks_exact(2).enumerate() {
        output[index] = (hex(pair[0])? << 4) | hex(pair[1])?;
    }
    if output == [0; 32] {
        return Err(AuthorizedEffectError::BindingMismatch);
    }
    Ok(output)
}

fn hex(value: u8) -> Result<u8, AuthorizedEffectError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(AuthorizedEffectError::BindingMismatch),
    }
}

fn validate_receipt_digest(digest: &Sha256Digest) -> Result<(), AuthorizedEffectError> {
    let value = digest.as_str();
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(TaskFlowError::Invalid("invalid provider evidence digest".to_string()).into());
    }
    Ok(())
}

#[cfg(test)]
mod intent_tests {
    use super::*;

    fn dependency(id: &str, label: &[u8]) -> AuthorizedEffectDependency {
        AuthorizedEffectDependency {
            step_id: id.to_string(),
            state_digest: Sha256Digest::for_bytes(label),
        }
    }

    fn intent() -> AuthorizedEffectIntent {
        AuthorizedEffectIntent {
            run_id: "run.1".to_string(),
            step_id: "step.2".to_string(),
            attempt: 3,
            operation_id: "matrix.send".to_string(),
            subject_id: "agent:1".to_string(),
            destination_id: "provider:matrix".to_string(),
            payload_digest: Sha256Digest::for_bytes(b"payload"),
            final_use_scope_digest: Sha256Digest::for_bytes(b"scope"),
            policy_generation: 7,
            expected_predecessor_digest: None,
            dependencies: vec![dependency("step.1", b"dep")],
            compensation_for: Some("matrix.send.original".to_string()),
        }
    }

    #[test]
    fn canonical_effect_intent_binds_every_execution_dimension() {
        let baseline = intent();
        let expected = baseline.digest().expect("baseline digest");
        let mut variants = Vec::new();

        let mut value = baseline.clone();
        value.run_id = "run.2".to_string();
        variants.push(value);
        let mut value = baseline.clone();
        value.step_id = "step.3".to_string();
        variants.push(value);
        let mut value = baseline.clone();
        value.attempt += 1;
        variants.push(value);
        let mut value = baseline.clone();
        value.operation_id = "matrix.redact".to_string();
        variants.push(value);
        let mut value = baseline.clone();
        value.subject_id = "agent:2".to_string();
        variants.push(value);
        let mut value = baseline.clone();
        value.destination_id = "provider:other".to_string();
        variants.push(value);
        let mut value = baseline.clone();
        value.payload_digest = Sha256Digest::for_bytes(b"other-payload");
        variants.push(value);
        let mut value = baseline.clone();
        value.final_use_scope_digest = Sha256Digest::for_bytes(b"other-scope");
        variants.push(value);
        let mut value = baseline.clone();
        value.policy_generation += 1;
        variants.push(value);
        let mut value = baseline.clone();
        value.expected_predecessor_digest = Some(Sha256Digest::for_bytes(b"predecessor"));
        variants.push(value);
        let mut value = baseline.clone();
        value.dependencies[0].state_digest = Sha256Digest::for_bytes(b"other-dep");
        variants.push(value);
        let mut value = baseline;
        value.compensation_for = None;
        variants.push(value);

        for variant in variants {
            assert_ne!(variant.digest().expect("variant digest"), expected);
        }
    }

    #[test]
    fn canonical_effect_intent_rejects_noncanonical_dependencies() {
        let mut value = intent();
        value.dependencies = vec![dependency("step.1", b"one"), dependency("step.0", b"zero")];
        assert!(matches!(value.digest(), Err(TaskFlowError::Invalid(_))));

        let mut value = intent();
        value.dependencies = vec![dependency("step.2", b"self")];
        assert!(matches!(value.digest(), Err(TaskFlowError::Invalid(_))));
    }
}
