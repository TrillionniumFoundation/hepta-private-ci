use std::sync::Arc;

use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal as ApiTerminal;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_evidence::AppendDisposition;
use codex_hepta_evidence::HeptaEvidenceStore;

use crate::provider_binding::provider_terminal;
use crate::provider_error::provider_evidence_error;
use crate::provider_final_use::ProviderFinalUseRequirement;

pub(crate) struct DurableProviderAttemptLease {
    evidence: Arc<HeptaEvidenceStore>,
    intent: ProviderInvocationIntent,
    mode: GovernanceMode,
    final_use: Option<ProviderFinalUseRequirement>,
}

impl ModelProviderAttemptLease for DurableProviderAttemptLease {
    fn authorize_dispatch(&mut self) -> ModelProviderPolicyFuture<'_, ()> {
        Box::pin(async move {
            match self.final_use.as_ref() {
                Some(requirement) => requirement.authorize().await,
                None => Ok(()),
            }
        })
    }

    fn finish(self: Box<Self>, terminal: ApiTerminal) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            let DurableProviderAttemptLease {
                evidence,
                intent,
                mode,
                final_use: _,
            } = *self;
            let result = async {
                let terminal = provider_terminal(terminal)?;
                let receipt = ProviderInvocationReceipt::new(intent, terminal);
                match evidence.append_provider_receipt(&receipt).await {
                    Ok(AppendDisposition::Inserted | AppendDisposition::AlreadyPresent) => Ok(()),
                    Err(error) => Err(provider_evidence_error(
                        "hepta_provider_terminal_write_failed",
                        error,
                    )),
                }
            }
            .await;
            match (mode, result) {
                (_, Ok(())) => Ok(()),
                (GovernanceMode::Enforce, Err(error)) => Err(error),
                (GovernanceMode::Shadow, Err(error)) => {
                    tracing::warn!(
                        reason_code = error.reason_code(),
                        detail = error.detail(),
                        "shadow provider terminal observation was not persisted"
                    );
                    Ok(())
                }
            }
        })
    }
}

struct DetachedShadowProviderLease;

impl ModelProviderAttemptLease for DetachedShadowProviderLease {
    fn finish(self: Box<Self>, _terminal: ApiTerminal) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(std::future::ready(Ok(())))
    }
}

pub(crate) fn durable_allow(
    evidence: Arc<HeptaEvidenceStore>,
    intent: ProviderInvocationIntent,
    mode: GovernanceMode,
    final_use: Option<ProviderFinalUseRequirement>,
) -> ModelProviderPolicyDecision {
    ModelProviderPolicyDecision::Allow {
        lease: Box::new(DurableProviderAttemptLease {
            evidence,
            intent,
            mode,
            final_use,
        }),
    }
}

pub(crate) fn detached_shadow_allow() -> ModelProviderPolicyDecision {
    ModelProviderPolicyDecision::Allow {
        lease: Box::new(DetachedShadowProviderLease),
    }
}
