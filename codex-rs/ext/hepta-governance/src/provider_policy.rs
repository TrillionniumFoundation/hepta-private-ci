use std::sync::Arc;

use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_evidence::AppendDisposition;
use codex_hepta_evidence::ProviderBindingState;
use codex_hepta_evidence::ProviderIntentClaimDisposition;

use crate::GovernanceState;
use crate::install::HeptaGovernanceExtension;
use crate::provider_binding::provider_intent;
use crate::provider_error::provider_block;
use crate::provider_error::provider_block_for_error;
use crate::provider_error::provider_evidence_error;
use crate::provider_lease::detached_shadow_allow;
use crate::provider_lease::durable_allow;

impl GovernanceState {
    pub(crate) async fn begin_provider(
        &self,
        input: ModelProviderInvocationInput<'_>,
    ) -> Result<ModelProviderPolicyDecision, ModelProviderPolicyError> {
        match (
            input.ephemeral_input_sha256,
            input.ephemeral_input_witness_sha256,
        ) {
            (Some(_), None) => {
                return Ok(provider_block(
                    "hepta_ephemeral_input_witness_missing",
                    "Hepta blocked ephemeral model input without an exact pre-send witness",
                ));
            }
            (None, Some(_)) => {
                return Ok(provider_block(
                    "hepta_ephemeral_input_witness_orphaned",
                    "Hepta blocked an ephemeral input witness without model input",
                ));
            }
            (Some(_), Some(_)) if !self.enabled => {
                return Ok(provider_block(
                    "hepta_ephemeral_input_governance_disabled",
                    "Hepta blocked ephemeral model input while governance was disabled",
                ));
            }
            (Some(_), Some(_)) | (None, None) => {}
        }
        if !self.enabled {
            return Ok(detached_shadow_allow());
        }
        let intent = match provider_intent(&input) {
            Ok(intent) => intent,
            Err(error) => return Ok(self.provider_failure_or_shadow(error)),
        };
        let evidence = match self.evidence.as_ref() {
            Ok(evidence) => Arc::clone(evidence),
            Err(detail) => {
                return Ok(
                    self.provider_failure_or_shadow(ModelProviderPolicyError::new(
                        "hepta_provider_evidence_unavailable",
                        detail.to_string(),
                    )),
                );
            }
        };
        match self.mode {
            GovernanceMode::Shadow => match evidence.append_provider_intent(&intent).await {
                Ok(AppendDisposition::Inserted) => Ok(durable_allow(evidence, intent, self.mode)),
                Ok(AppendDisposition::AlreadyPresent) => {
                    tracing::warn!(
                        attempt_id = intent.attempt_id.as_str(),
                        request_binding_id = intent.request_binding_id.as_str(),
                        "shadow governance observed an exact provider attempt replay"
                    );
                    Ok(detached_shadow_allow())
                }
                Err(error) => Ok(self.provider_failure_or_shadow(provider_evidence_error(
                    "hepta_provider_intent_write_failed",
                    error,
                ))),
            },
            GovernanceMode::Enforce => match evidence.claim_provider_intent(&intent).await {
                Ok(ProviderIntentClaimDisposition::Inserted) => {
                    Ok(durable_allow(evidence, intent, self.mode))
                }
                Ok(ProviderIntentClaimDisposition::ExactReplay) => {
                    let reason_code = match evidence.get_provider_attempt(&intent.attempt_id).await
                    {
                        Ok(Some(stored)) if stored.receipt.is_some() => {
                            "hepta_provider_attempt_replay"
                        }
                        Ok(Some(_)) => "hepta_provider_attempt_pending",
                        Ok(None) => "hepta_provider_evidence_corrupt",
                        Err(_) => "hepta_provider_evidence_read_failed",
                    };
                    Ok(provider_block(
                        reason_code,
                        "Hepta blocked replay of an existing durable provider attempt",
                    ))
                }
                Ok(ProviderIntentClaimDisposition::BlockedByBinding(state)) => {
                    let (reason_code, message) = match state {
                        ProviderBindingState::Pending => (
                            "hepta_provider_request_pending",
                            "Hepta blocked retry of a provider request with a pending attempt",
                        ),
                        ProviderBindingState::Completed => (
                            "hepta_provider_request_completed",
                            "Hepta blocked retry of an already completed provider request",
                        ),
                        ProviderBindingState::Indeterminate => (
                            "hepta_provider_request_indeterminate",
                            "Hepta blocked automatic retry of an indeterminate provider request",
                        ),
                    };
                    Ok(provider_block(reason_code, message))
                }
                Err(error) => Ok(provider_block_for_error(error)),
            },
        }
    }

    fn provider_failure_or_shadow(
        &self,
        error: ModelProviderPolicyError,
    ) -> ModelProviderPolicyDecision {
        match self.mode {
            GovernanceMode::Enforce => provider_block(
                error.reason_code(),
                "Hepta could not establish durable provider intent evidence",
            ),
            GovernanceMode::Shadow => {
                tracing::warn!(
                    reason_code = error.reason_code(),
                    detail = error.detail(),
                    "shadow provider governance observation failed"
                );
                detached_shadow_allow()
            }
        }
    }
}

impl<F> ModelProviderPolicyContributor for HeptaGovernanceExtension<F>
where
    F: Send + Sync,
{
    fn is_active(&self, thread_store: &codex_extension_api::ExtensionData) -> bool {
        thread_store
            .get::<GovernanceState>()
            .is_none_or(|state| state.enabled)
    }

    fn begin<'a>(
        &'a self,
        input: ModelProviderInvocationInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderPolicyDecision> {
        Box::pin(async move {
            let Some(state) = input.thread_store.get::<GovernanceState>() else {
                return Ok(match self.mode {
                    GovernanceMode::Enforce => provider_block(
                        "hepta_governance_state_missing",
                        "Hepta provider governance state was not initialized",
                    ),
                    GovernanceMode::Shadow => {
                        tracing::warn!(
                            "shadow provider governance thread state was not initialized"
                        );
                        detached_shadow_allow()
                    }
                });
            };
            state.begin_provider(input).await
        })
    }
}
