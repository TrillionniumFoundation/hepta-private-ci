//! Final-use-authorized TaskFlow effect dispatch.
//!
//! The automation owner never mints authority. A step must already be durably
//! claimed in the TaskFlow outbox. Final-use verification burns the signed
//! nonce before a durable provider-attempt row is appended. Once that row
//! exists, the same step attempt can never cross the provider boundary again
//! without provider-owned recovery evidence. Provider observations are durable
//! before they are projected into the TaskFlow step/run state.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
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
    pub run_id: &'a str,
    pub step_id: &'a str,
    pub attempt: u32,
    pub intent_digest: &'a Sha256Digest,
    pub payload_digest: &'a Sha256Digest,
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
    #[allow(clippy::too_many_arguments)]
    pub async fn execute_authorized_taskflow_effect<D: AuthorizedEffectDriver>(
        &self,
        authority: &FinalUseAuthority,
        driver: &mut D,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        signed_grant: &SignedFinalUseGrant,
        expected_binding: &FinalUseBinding,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        let current = self
            .read_taskflow_step(run_id, step_id, attempt, fence)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict(
                    "authorized effect requires a prepared and claimed durable step".to_string(),
                )
            })?;
        if current.state != TaskFlowStepState::Claimed
            || current.intent_digest != *intent_digest
            || current.payload_digest != *payload_digest
        {
            return Err(TaskFlowError::Conflict(
                "authorized effect does not match the claimed durable step".to_string(),
            )
            .into());
        }
        if expected_binding.request_sha256 != digest_bytes(intent_digest)?
            || expected_binding.payload_sha256 != digest_bytes(payload_digest)?
        {
            return Err(AuthorizedEffectError::BindingMismatch);
        }
        let binding_digest = final_use_binding_digest(expected_binding)?;

        // A durable provider-attempt row is an at-most-once barrier for this
        // exact step attempt. Never burn another grant or call the driver when
        // recovery evidence already exists.
        if let Some(existing) = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
        {
            ensure_attempt_binding(
                &existing,
                intent_digest,
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
                run_id,
                step_id,
                attempt,
                intent_digest,
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
                    intent_digest,
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
            run_id,
            step_id,
            attempt,
            intent_digest,
            payload_digest,
            binding: expected_binding,
        };
        let provider = match authority
            .with_verified_use(token, expected_binding, || driver.dispatch(&request))
        {
            Ok(Ok(receipt)) => receipt,
            Ok(Err(error)) => {
                let proof = no_contact_digest(&durable, "driver_before_provider_contact");
                let durable = self
                    .record_effect_dispatch_observation(
                        run_id,
                        step_id,
                        attempt,
                        EffectDispatchObservationKind::ProvenAbsent,
                        &proof,
                        now_ms,
                    )
                    .await?;
                self.settle_effect_dispatch_attempt(&durable, fence).await?;
                return Err(AuthorizedEffectError::Driver(error));
            }
            Err(error) => {
                // `with_verified_use` invokes the consumer only after its
                // final revocation/epoch check succeeds, so this path is a
                // local proof that the provider driver was not called.
                let proof = no_contact_digest(&durable, "final_use_pre_dispatch_rejection");
                let durable = self
                    .record_effect_dispatch_observation(
                        run_id,
                        step_id,
                        attempt,
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
                run_id,
                step_id,
                attempt,
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
        let durable = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
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
                if step.receipt_digest.as_ref() != Some(&observation.evidence_digest)
                    || step.observation != Some(outcome.observation())
                {
                    return Err(TaskFlowError::Conflict(
                        "TaskFlow step is recorded with different provider evidence".to_string(),
                    )
                    .into());
                }
                step
            }
            TaskFlowStepState::Reconciled => {
                if step.receipt_digest.as_ref() != Some(&observation.evidence_digest) {
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
        if run.state != TaskFlowRunState::Running {
            return Err(TaskFlowError::Conflict(
                "provider absence cannot requeue the current TaskFlow run state".to_string(),
            )
            .into());
        }
        let step = self
            .read_taskflow_step(
                &durable.run_id,
                &durable.step_id,
                durable.attempt,
                fence,
            )
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("effect TaskFlow step vanished".to_string()))?;
        if step.state != TaskFlowStepState::Claimed {
            return Err(TaskFlowError::Conflict(
                "provider absence requires the original claimed step".to_string(),
            )
            .into());
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
