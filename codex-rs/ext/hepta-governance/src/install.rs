use std::sync::Arc;

use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::ToolPolicyContributor;
use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyError;
use codex_extension_api::ToolPolicyFuture;
use codex_extension_api::ToolPolicyInput;
use codex_extension_api::ToolPolicyTerminalInput;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::StateRuntime;

use crate::state::GovernanceState;

pub(crate) struct HeptaGovernanceExtension<F> {
    pub(crate) enabled: F,
    pub(crate) mode: GovernanceMode,
    pub(crate) state_db: Option<Arc<StateRuntime>>,
    pub(crate) evidence: tokio::sync::OnceCell<Arc<HeptaEvidenceStore>>,
}

impl<F> HeptaGovernanceExtension<F> {
    pub(crate) async fn initialize_thread<C>(
        &self,
        config: &C,
        thread_store: &codex_extension_api::ExtensionData,
    ) where
        F: Fn(&C) -> bool,
    {
        if !(self.enabled)(config) {
            thread_store.insert(GovernanceState::disabled());
            return;
        }
        let evidence = match self.state_db.as_ref() {
            Some(state_db) => self
                .evidence
                .get_or_try_init(|| async {
                    HeptaEvidenceStore::open(state_db.sqlite())
                        .await
                        .map(Arc::new)
                        .map_err(|error| Arc::<str>::from(error.to_string()))
                })
                .await
                .cloned(),
            None => Err(Arc::from("Codex state runtime is unavailable")),
        };
        thread_store.insert(GovernanceState::enabled(self.mode, evidence));
    }
}

impl<C, F> ThreadLifecycleContributor<C> for HeptaGovernanceExtension<F>
where
    C: Sync,
    F: Fn(&C) -> bool + Send + Sync,
{
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, C>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.initialize_thread(input.config, input.thread_store)
                .await;
        })
    }
}

impl<F> ToolPolicyContributor for HeptaGovernanceExtension<F>
where
    F: Send + Sync,
{
    fn is_active(&self, thread_store: &codex_extension_api::ExtensionData) -> bool {
        // A missing state is kept active so enforce mode can fail closed and
        // shadow mode can emit its explicit observation. A feature-disabled
        // thread always contains a disabled state and is a true no-op.
        thread_store
            .get::<GovernanceState>()
            .is_none_or(|state| state.enabled)
    }

    fn admit<'a>(&'a self, input: ToolPolicyInput<'a>) -> ToolPolicyFuture<'a, ToolPolicyDecision> {
        Box::pin(async move {
            let Some(state) = governance_state(input.thread_store, self.mode)? else {
                return Ok(ToolPolicyDecision::Allow);
            };
            state.evaluate(input, PolicyPhase::Admission).await
        })
    }

    fn authorize<'a>(
        &'a self,
        input: ToolPolicyInput<'a>,
    ) -> ToolPolicyFuture<'a, ToolPolicyDecision> {
        Box::pin(async move {
            let Some(state) = governance_state(input.thread_store, self.mode)? else {
                return Ok(ToolPolicyDecision::Allow);
            };
            state.evaluate(input, PolicyPhase::Authorization).await
        })
    }

    fn on_terminal<'a>(&'a self, input: ToolPolicyTerminalInput<'a>) -> ToolPolicyFuture<'a, ()> {
        Box::pin(async move {
            let Some(state) = governance_state(input.thread_store, self.mode)? else {
                return Ok(());
            };
            state.terminal(input).await
        })
    }
}

pub fn install<C, F>(
    registry: &mut ExtensionRegistryBuilder<C>,
    state_db: Option<Arc<StateRuntime>>,
    enabled: F,
) where
    C: Sync + 'static,
    F: Fn(&C) -> bool + Send + Sync + 'static,
{
    install_with_mode(registry, state_db, GovernanceMode::Shadow, enabled);
}

/// Install the governance extension with an explicit rollout mode.
///
/// Product surfaces use shadow mode until the durable oracle soak is accepted;
/// focused tests exercise enforce-mode fail-closed behavior through this API.
pub fn install_with_mode<C, F>(
    registry: &mut ExtensionRegistryBuilder<C>,
    state_db: Option<Arc<StateRuntime>>,
    mode: GovernanceMode,
    enabled: F,
) where
    C: Sync + 'static,
    F: Fn(&C) -> bool + Send + Sync + 'static,
{
    let extension = Arc::new(HeptaGovernanceExtension {
        enabled,
        mode,
        state_db,
        evidence: tokio::sync::OnceCell::new(),
    });
    registry.thread_lifecycle_contributor(extension.clone());
    registry.tool_policy_contributor(extension.clone());
    registry.model_provider_policy_contributor(extension);
}

pub(crate) fn governance_state(
    thread_store: &codex_extension_api::ExtensionData,
    mode: GovernanceMode,
) -> Result<Option<Arc<GovernanceState>>, ToolPolicyError> {
    if let Some(state) = thread_store.get::<GovernanceState>() {
        return Ok(Some(state));
    }
    match mode {
        GovernanceMode::Enforce => Err(ToolPolicyError::new(
            "hepta_governance_state_missing",
            "thread governance state was not initialized",
        )),
        GovernanceMode::Shadow => {
            tracing::warn!("shadow governance thread state was not initialized");
            Ok(None)
        }
    }
}
