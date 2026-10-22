use std::sync::Arc;

use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal as ApiTerminal;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_evidence::AppendDisposition;
use codex_hepta_evidence::HeptaEvidenceStore;

use crate::provider_binding::provider_terminal;
use crate::provider_error::provider_evidence_error;

pub(crate) struct DurableProviderAttemptLease {
    evidence: Arc<HeptaEvidenceStore>,
    intent: ProviderInvocationIntent,
    mode: GovernanceMode,
    request_host: Option<crate::ProviderRequestEnforcementHost>,
    binding_attempted: bool,
    body_bound: bool,
}

impl ModelProviderAttemptLease for DurableProviderAttemptLease {
    fn encoded_body_required(&self) -> bool {
        self.request_host.is_some()
    }

    fn bind_encoded_body_v1<'a>(
        &'a mut self,
        digest: ModelProviderSha256Digest,
        bytes: u64,
    ) -> ModelProviderPolicyFuture<'a, ()> {
        Box::pin(async move {
            if self.binding_attempted {
                return Err(ModelProviderPolicyError::new(
                    "hepta_provider_request_binding_repeated",
                    "encoded request binding is single-use",
                ));
            }
            self.binding_attempted = true;
            let host = self.request_host.as_ref().ok_or_else(|| {
                ModelProviderPolicyError::new(
                    "hepta_provider_request_host_required",
                    "encoded request host is absent",
                )
            })?;
            host.authorize(self.intent.clone(), digest.clone(), bytes)
                .await?;
            let digest =
                codex_hepta_contracts::Sha256Digest::parse(digest.as_str()).map_err(|detail| {
                    ModelProviderPolicyError::new("hepta_provider_request_digest_invalid", detail)
                })?;
            self.evidence
                .bind_provider_encoded_request_v1(&self.intent, &digest, bytes)
                .await
                .map_err(|error| {
                    provider_evidence_error("hepta_provider_request_binding_failed", error)
                })?;
            self.body_bound = true;
            Ok(())
        })
    }

    fn finish(self: Box<Self>, terminal: ApiTerminal) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            let DurableProviderAttemptLease {
                evidence,
                intent,
                mode,
                request_host,
                body_bound,
                ..
            } = *self;
            let missing_binding = request_host.is_some()
                && !body_bound
                && matches!(
                    terminal,
                    ApiTerminal::Completed { .. } | ApiTerminal::CompletedUnary { .. }
                );
            let terminal = if missing_binding {
                ApiTerminal::Indeterminate {
                    reason_code: "hepta_provider_request_binding_missing".into(),
                    partial_response_sha256: None,
                }
            } else {
                terminal
            };
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
                (_, Ok(())) if missing_binding => Err(ModelProviderPolicyError::new(
                    "hepta_provider_request_binding_missing",
                    "unbound completion settled as indeterminate",
                )),
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
    request_host: Option<crate::ProviderRequestEnforcementHost>,
) -> ModelProviderPolicyDecision {
    ModelProviderPolicyDecision::Allow {
        lease: Box::new(DurableProviderAttemptLease {
            evidence,
            intent,
            mode,
            request_host,
            binding_attempted: false,
            body_bound: false,
        }),
    }
}

pub(crate) fn detached_shadow_allow() -> ModelProviderPolicyDecision {
    ModelProviderPolicyDecision::Allow {
        lease: Box::new(DetachedShadowProviderLease),
    }
}
