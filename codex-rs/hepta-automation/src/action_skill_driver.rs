//! An authorized driver decorator, not an authority or a durable executor.

use std::time::Duration;

use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;

use crate::AsyncAuthorizedEffectDriver;
use crate::AuthorizedEffectDriverError;
use crate::AuthorizedEffectFuture;
use crate::AuthorizedEffectOutcome;
use crate::AuthorizedEffectPending;
use crate::AuthorizedEffectProviderReceipt;
use crate::AuthorizedProviderEffectLookup;
use crate::AuthorizedProviderEffectRequest;
use crate::ProviderEffectTaskFlowDriver;
use crate::action_runtime::ActionRuntimeObservationV1;
use crate::action_runtime::verified_outcome;
use crate::action_skill::ACTION_SKILL_SCHEMA_VERSION;
use crate::action_skill::ActionConditionV1;
use crate::action_skill::ActionSkillBindingV1;
use crate::action_skill::ActionSkillContractV1;
use crate::action_skill::ActionSkillError;
use crate::action_skill::ActionSkillInvocationV1;
use crate::action_skill::ActionSkillObservationV1;
use crate::action_skill::ActionSkillObserver;
use crate::action_skill::evidence_digest;

/// Use through `AutomationStore::execute_authorized_taskflow_effect_async`.
/// The existing owner persists the intent, verifies final use and fences the
/// result. This decorator neither authorizes dispatch nor retries it.
pub struct GoalCheckedActionSkillDriver<A, O> {
    contract: ActionSkillContractV1,
    contract_digest: Sha256Digest,
    provider: ProviderEffectTaskFlowDriver<A>,
    observer: O,
}

impl<A: ProviderEffectAdapter, O: ActionSkillObserver> GoalCheckedActionSkillDriver<A, O> {
    pub fn new(
        contract: ActionSkillContractV1,
        adapter: A,
        observer: O,
    ) -> Result<Self, ActionSkillError> {
        let contract_digest = contract.digest()?;
        if observer.observer_id() != contract.observer_id {
            return Err(ActionSkillError::Contract);
        }
        let provider = ProviderEffectTaskFlowDriver::new(contract.destination_id.clone(), adapter)
            .map_err(|_| ActionSkillError::Contract)?;
        Ok(Self {
            contract,
            contract_digest,
            provider,
            observer,
        })
    }

    fn bind_invocation(
        &self,
        effect_intent_digest: &Sha256Digest,
        provider_intent: &ProviderEffectIntent,
        wire_payload: &[u8],
    ) -> Result<(ActionSkillBindingV1, ActionSkillInvocationV1), ActionSkillError> {
        if wire_payload.len() > self.contract.budget.max_wire_bytes as usize
            || provider_intent.validate().is_err()
            || Sha256Digest::parse(effect_intent_digest.as_str()).is_err()
            || Sha256Digest::for_bytes(wire_payload) != provider_intent.payload_sha256
        {
            return Err(ActionSkillError::Invocation);
        }
        let invocation: ActionSkillInvocationV1 =
            serde_json::from_slice(wire_payload).map_err(|_| ActionSkillError::Invocation)?;
        if invocation.schema_version != ACTION_SKILL_SCHEMA_VERSION
            || invocation.contract_digest != self.contract_digest
            || invocation.destination_id != self.contract.destination_id
        {
            return Err(ActionSkillError::Invocation);
        }
        Ok((
            ActionSkillBindingV1 {
                provider_intent: provider_intent.clone(),
                effect_intent_digest: effect_intent_digest.clone(),
                contract_digest: self.contract_digest.clone(),
                destination_id: self.contract.destination_id.clone(),
            },
            invocation,
        ))
    }

    /// Reuse the frozen original bytes, including after restart. This prevents
    /// a new contract from reinterpreting the same durable pending payload.
    /// Ordinary NotFound is unresolved: key/status capability alone cannot
    /// prove that no in-flight dispatch can commit later.
    pub async fn lookup(
        &self,
        pending: &AuthorizedEffectPending,
        original_wire_payload: &[u8],
    ) -> AuthorizedProviderEffectLookup {
        let Ok(binding) = self.bind_pending(pending, original_wire_payload) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let Ok(AuthorizedProviderEffectLookup::Observed(provider)) = tokio::time::timeout(
            Duration::from_millis(self.contract.budget.provider_timeout_ms),
            self.provider.lookup(pending),
        )
        .await
        else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let receipt = self.check_goal(&binding, provider).await;
        match receipt.outcome {
            AuthorizedEffectOutcome::Succeeded | AuthorizedEffectOutcome::Failed => {
                AuthorizedProviderEffectLookup::Observed(receipt)
            }
            AuthorizedEffectOutcome::Indeterminate => AuthorizedProviderEffectLookup::Unresolved,
        }
    }

    /// Read current waiting, partial-effect and cancellation facts without
    /// settling the durable attempt or granting another dispatch. When provider
    /// status is unavailable, the provider digest records that unresolved query.
    pub async fn observe_pending(
        &self,
        pending: &AuthorizedEffectPending,
        original_wire_payload: &[u8],
    ) -> Result<ActionSkillObservationV1, ActionSkillError> {
        self.observe_pending_state(pending, original_wire_payload)
            .await
            .map(|readback| readback.observation)
    }

    /// Query the original operation once and retain the independent provider,
    /// execution, goal and cancellation facts alongside their five-state view.
    /// An observation error means UNKNOWN, never failure or permission to retry.
    /// This method neither settles the attempt nor dispatches another effect.
    pub async fn observe_pending_state(
        &self,
        pending: &AuthorizedEffectPending,
        original_wire_payload: &[u8],
    ) -> Result<ActionRuntimeObservationV1, ActionSkillError> {
        let binding = self.bind_pending(pending, original_wire_payload)?;
        let provider = match tokio::time::timeout(
            Duration::from_millis(self.contract.budget.provider_timeout_ms),
            self.provider.lookup(pending),
        )
        .await
        {
            Ok(AuthorizedProviderEffectLookup::Observed(receipt)) => receipt,
            _ => unresolved(&binding, &Sha256Digest::for_bytes(b"status_unresolved")),
        };
        let observation = self
            .read_observation(&binding, &provider.receipt_digest)
            .await?;
        Ok(ActionRuntimeObservationV1::from_observation(
            provider.outcome,
            observation,
        ))
    }

    fn bind_pending(
        &self,
        pending: &AuthorizedEffectPending,
        wire_payload: &[u8],
    ) -> Result<ActionSkillBindingV1, ActionSkillError> {
        if pending.destination_id != self.contract.destination_id {
            return Err(ActionSkillError::Invocation);
        }
        let logical_id = format!("taskflow:{}:{}", pending.run_id, pending.step_id);
        let key = ProviderEffectKey::for_logical_effect(&pending.destination_id, &logical_id)
            .map_err(|_| ActionSkillError::Invocation)?;
        let intent = ProviderEffectIntent::new(key, pending.payload_digest.clone());
        self.bind_invocation(&pending.intent_digest, &intent, wire_payload)
            .map(|(binding, _)| binding)
    }

    async fn read_observation(
        &self,
        binding: &ActionSkillBindingV1,
        provider_digest: &Sha256Digest,
    ) -> Result<ActionSkillObservationV1, ActionSkillError> {
        let observation = tokio::time::timeout(
            Duration::from_millis(self.contract.budget.observer_timeout_ms),
            self.observer.observe(binding, provider_digest),
        )
        .await
        .map_err(|_| ActionSkillError::Observation)??;
        if observation.binding != *binding
            || observation.provider_receipt_digest != *provider_digest
            || observation.observer_id != self.contract.observer_id
            || Sha256Digest::parse(observation.evidence_digest.as_str()).is_err()
            || observation
                .absence_proof_digest
                .as_ref()
                .is_some_and(|digest| Sha256Digest::parse(digest.as_str()).is_err())
        {
            return Err(ActionSkillError::Observation);
        }
        Ok(observation)
    }

    async fn check_goal(
        &self,
        binding: &ActionSkillBindingV1,
        provider: AuthorizedEffectProviderReceipt,
    ) -> AuthorizedEffectProviderReceipt {
        let Ok(observation) = self
            .read_observation(binding, &provider.receipt_digest)
            .await
        else {
            return unresolved(binding, &provider.receipt_digest);
        };
        let Ok(receipt_digest) =
            evidence_digest(b"hepta.action-skill.observation.v1\0", &observation)
        else {
            return unresolved(binding, &provider.receipt_digest);
        };
        let outcome = verified_outcome(provider.outcome, &observation);
        AuthorizedEffectProviderReceipt {
            outcome,
            receipt_digest,
        }
    }
}

impl<A: ProviderEffectAdapter, O: ActionSkillObserver> AsyncAuthorizedEffectDriver
    for GoalCheckedActionSkillDriver<A, O>
{
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            if request.intent.destination_id != self.contract.destination_id
                || self.provider.adapter().capability()
                    != ProviderEffectIdempotencyCapability::KeyAndStatusLookup
            {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            let (binding, invocation) = self
                .bind_invocation(
                    request.intent_digest,
                    &request.provider_intent,
                    request.wire_payload,
                )
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            let initiation = tokio::time::timeout(
                Duration::from_millis(self.contract.budget.observer_timeout_ms),
                self.observer.check_initiation(&binding, &invocation.body),
            )
            .await;
            let Ok(Ok(initiation)) = initiation else {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            };
            if initiation.binding != binding
                || initiation.observer_id != self.contract.observer_id
                || initiation.condition != ActionConditionV1::Met
                || Sha256Digest::parse(initiation.evidence_digest.as_str()).is_err()
            {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            // No error after invoking the downstream driver can become local
            // absence proof, including its own error or a dropped I/O future.
            let provider = match tokio::time::timeout(
                Duration::from_millis(self.contract.budget.provider_timeout_ms),
                self.provider.dispatch(request),
            )
            .await
            {
                Ok(Ok(receipt)) => receipt,
                _ => unresolved(&binding, &Sha256Digest::for_bytes(b"provider_unresolved")),
            };
            Ok(self.check_goal(&binding, provider).await)
        })
    }
}

fn unresolved(
    binding: &ActionSkillBindingV1,
    provider_digest: &Sha256Digest,
) -> AuthorizedEffectProviderReceipt {
    AuthorizedEffectProviderReceipt {
        outcome: AuthorizedEffectOutcome::Indeterminate,
        receipt_digest: evidence_digest(
            b"hepta.action-skill.unresolved.v1\0",
            &(binding, provider_digest),
        )
        .unwrap_or_else(|_| binding.effect_intent_digest.clone()),
    }
}
