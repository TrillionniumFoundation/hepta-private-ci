#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one match, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1))


# The production ledger owner exposes the exact binding required before an
# independently observed outcome can close an intelligence run.
replace_once(
    "codex-rs/hepta-learning-ledger/src/production.rs",
    """    pub fn witness_frontier(&self) -> Result<LedgerWitnessFrontier, ProductionLedgerError> {
""",
    """    /// Verify the complete active intelligence Decision identity before an
    /// Outcome append. This closes run/episode-only substitution: snapshot,
    /// selected candidate and decision support must all match the active fact.
    pub fn verify_active_intelligence_decision_binding(
        &self,
        record_id: &StableId,
        episode_id: &StableId,
        run_snapshot_digest: Digest32,
        selected_candidate_id: &StableId,
        decision_digest: Digest32,
    ) -> Result<(), ProductionLedgerError> {
        let ledger = self.backend.core()?;
        if ledger
            .active_record_by_id(record_id)?
            .is_some_and(|record| {
                matches!(
                    &record.event,
                    LedgerEvent::AuthenticatedDecisionV2(value)
                        if &value.record_id == record_id
                            && &value.episode_id == episode_id
                            && value.run_snapshot_digest == run_snapshot_digest
                            && &value.selected_candidate_id == selected_candidate_id
                            && value.support_digest == decision_digest
                )
            })
        {
            Ok(())
        } else {
            Err(ProductionLedgerError::Binding(
                "active intelligence decision binding",
            ))
        }
    }

    pub fn witness_frontier(&self) -> Result<LedgerWitnessFrontier, ProductionLedgerError> {
""",
)

# Public module surface.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod intelligence_invocation_registry;\nmod intelligence_learning_outbox;\nmod intelligence_product;",
    "mod intelligence_invocation_registry;\nmod intelligence_learning_host;\nmod intelligence_learning_outbox;\nmod intelligence_observability;\nmod intelligence_outcome_registry;\nmod intelligence_profile;\nmod intelligence_product;",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use intelligence_invocation_registry::RegisteredAgentdIntelligenceInvocationProviderV1;\npub use intelligence_learning_outbox::IntelligenceLearningIntentKindV1;",
    "pub use intelligence_invocation_registry::RegisteredAgentdIntelligenceInvocationProviderV1;\npub use intelligence_learning_host::AgentdIntelligenceDecisionAppendV1;\npub use intelligence_learning_host::AgentdIntelligenceLearningDispositionV1;\npub use intelligence_learning_host::AgentdIntelligenceLearningErrorV1;\npub use intelligence_learning_host::AgentdIntelligenceLearningHostV1;\npub use intelligence_learning_host::AgentdIntelligenceLearningReceiptV1;\npub use intelligence_learning_host::AgentdIntelligenceOutcomeAppendV1;\npub use intelligence_learning_host::AgentdIntelligenceReconciliationSummaryV1;\npub use intelligence_learning_outbox::IntelligenceLearningIntentKindV1;",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use intelligence_learning_outbox::IntelligenceLearningOutboxV1;\npub use intelligence_product::AgentdEvaluationBindingV1;",
    "pub use intelligence_learning_outbox::IntelligenceLearningOutboxV1;\npub use intelligence_observability::AgentdIntelligenceObservabilitySnapshotV1;\npub use intelligence_observability::AgentdIntelligenceObservabilityV1;\npub use intelligence_observability::IntelligenceStageMetricsV1;\npub use intelligence_outcome_registry::MAX_PENDING_INTELLIGENCE_OUTCOMES;\npub use intelligence_outcome_registry::RegisteredAgentdIntelligenceOutcomeProviderV1;\npub use intelligence_profile::AgentdCanonicalIntelligenceProfileV1;\npub use intelligence_product::AgentdEvaluationBindingV1;",
)

# Atomic profile assembly in config. Legacy runner/provider setters remain
# source-compatibility seams but cannot enable the capability by themselves.
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "    intelligence_invocation_provider:\n        Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,\n}",
    "    intelligence_invocation_provider:\n        Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,\n    canonical_intelligence_profile: Option<crate::AgentdCanonicalIntelligenceProfileV1>,\n}",
)
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "            intelligence_invocation_provider: None,\n        })",
    "            intelligence_invocation_provider: None,\n            canonical_intelligence_profile: None,\n        })",
)
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    """    pub(crate) fn intelligence_invocation_provider(
        &self,
    ) -> Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>> {
        self.intelligence_invocation_provider.clone()
    }

    pub fn identity(&self) -> &AgentdIdentity {
""",
    """    pub(crate) fn intelligence_invocation_provider(
        &self,
    ) -> Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>> {
        self.intelligence_invocation_provider.clone()
    }

    /// Attach the all-or-none product profile. A complete profile is the only
    /// configuration that can advertise `intelligence.canonical_v1`.
    pub fn with_canonical_intelligence_profile(
        mut self,
        profile: crate::AgentdCanonicalIntelligenceProfileV1,
    ) -> Result<Self, AgentdError> {
        if self.canonical_intelligence_profile.is_some()
            || self.intelligence_product_runner.is_some()
            || self.intelligence_invocation_provider.is_some()
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence profile conflicts with a partial configuration"
                    .to_string(),
            ));
        }
        self.canonical_intelligence_profile = Some(profile);
        Ok(self)
    }

    pub(crate) fn take_canonical_intelligence_profile(
        &mut self,
    ) -> Option<crate::AgentdCanonicalIntelligenceProfileV1> {
        self.canonical_intelligence_profile.take()
    }

    pub fn identity(&self) -> &AgentdIdentity {
""",
)

# State contains every owner required for capability activation.
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    """    pub(crate) intelligence_invocation:
        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
""",
    """    pub(crate) intelligence_invocation:
        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
    pub(crate) intelligence_learning:
        std::sync::OnceLock<Arc<crate::AgentdIntelligenceLearningHostV1>>,
    pub(crate) intelligence_observability:
        std::sync::OnceLock<Arc<crate::AgentdIntelligenceObservabilityV1>>,
    pub(crate) intelligence_outcomes:
        std::sync::OnceLock<Arc<crate::RegisteredAgentdIntelligenceOutcomeProviderV1>>,
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
""",
)
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    "            intelligence_invocation: std::sync::OnceLock::new(),\n            evidence:",
    "            intelligence_invocation: std::sync::OnceLock::new(),\n            intelligence_learning: std::sync::OnceLock::new(),\n            intelligence_observability: std::sync::OnceLock::new(),\n            intelligence_outcomes: std::sync::OnceLock::new(),\n            evidence:",
)
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    """    pub(crate) fn canonical_intelligence_enabled(&self) -> bool {
        self.intelligence_product.get().is_some() && self.intelligence_invocation.get().is_some()
    }
""",
    """    pub(crate) fn canonical_intelligence_enabled(&self) -> bool {
        self.intelligence_product.get().is_some()
            && self.intelligence_invocation.get().is_some()
            && self.intelligence_learning.get().is_some()
            && self.intelligence_observability.get().is_some()
            && self.intelligence_outcomes.get().is_some()
    }
""",
)

# Runtime composes an atomic profile; partial legacy attachments remain disabled.
replace_once(
    "codex-rs/hepta-agentd/src/runtime.rs",
    "    let intelligence_product = config.intelligence_product_runner();\n    let intelligence_invocation = config.intelligence_invocation_provider();",
    "    let intelligence_product = config.intelligence_product_runner();\n    let intelligence_invocation = config.intelligence_invocation_provider();\n    let intelligence_profile = config.take_canonical_intelligence_profile();",
)
replace_once(
    "codex-rs/hepta-agentd/src/runtime.rs",
    """    if let Some(provider) = intelligence_invocation {
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
    }
""",
    """    if let Some(provider) = intelligence_invocation {
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
    }
    if let Some(profile) = intelligence_profile {
        let (runner, provider, learning, observability, outcomes) = profile.into_parts();
        state.intelligence_product.set(runner).map_err(|_| {
            AgentdError::Invalid("intelligence product runner already attached".to_string())
        })?;
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
        state.intelligence_learning.set(learning).map_err(|_| {
            AgentdError::Invalid("intelligence learning host already attached".to_string())
        })?;
        state.intelligence_observability.set(observability).map_err(|_| {
            AgentdError::Invalid("intelligence observability already attached".to_string())
        })?;
        state.intelligence_outcomes.set(outcomes).map_err(|_| {
            AgentdError::Invalid("intelligence outcome provider already attached".to_string())
        })?;
    }
""",
)
