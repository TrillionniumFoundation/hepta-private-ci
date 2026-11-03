//! Native hosted selection from the original canonical ObjectiveStart owner.
//! Lookups use the original Objective journal and RunCoordinator. This module
//! stores no route, queued input, grant or second run registry.

use std::sync::{Arc, Weak};

use anyhow::{Context, Result, ensure};
use codex_core::hosted_turn::{HostedTurnExecutor, HostedTurnInput};
use codex_hepta_native_agent::NativeAgent;

use crate::native_hosted_turn::{AgentdNativeHostedExecutor, NativeHostedResolution, NativeHostedResolveFuture, NativeHostedTurnConfig, NativeHostedTurnResolver};
use crate::{AgentdNativeHost, AgentdState, NativeTurnScope};

/// Select the existing input owner when installing native execution on the
/// original App Server. CanonicalObjective uses signed ObjectiveStart;
/// External retains the explicit embedding seam for another existing owner.
pub enum NativeHostedRuntimeConfig {
    CanonicalObjective {
        agent: Arc<NativeAgent>,
        scope: NativeTurnScope,
    },
    External(NativeHostedTurnConfig),
}

impl NativeHostedRuntimeConfig {
    pub(crate) fn attach(
        self,
        state: &Arc<AgentdState>,
        host: Arc<AgentdNativeHost>,
    ) -> Result<Arc<dyn HostedTurnExecutor>> {
        ensure!(Arc::ptr_eq(state, &host.gate.state()?), "native objective attachment changed its original Agentd owner");
        match self {
            Self::CanonicalObjective { agent, scope } => {
                ensure!(state.canonical_intelligence_enabled() && state.objective_runtime.get().is_some()
                    && state.authbus.get().is_some(), "native objective execution requires the configured original signed canonical owners");
                ensure!(scope.final_scope_id == scope.organ_id, "native objective scope differs from its configured organ");
                let resolver = Arc::new(CanonicalObjectiveResolver { state: Arc::downgrade(state), scope });
                let executor: Arc<dyn HostedTurnExecutor> = Arc::new(AgentdNativeHostedExecutor::new(host,
                    NativeHostedTurnConfig { agent, resolver })?);
                // The same handle is installed on the original App Server.
                // This witness does not grant execution or own another queue.
                state.native_objective_executor.set(executor.clone())
                    .map_err(|_| anyhow::anyhow!("native objective executor was already installed"))?;
                Ok(executor)
            }
            Self::External(config) => Ok(Arc::new(AgentdNativeHostedExecutor::new(host, config)?)),
        }
    }
}

struct CanonicalObjectiveResolver {
    state: Weak<AgentdState>,
    scope: NativeTurnScope,
}

impl NativeHostedTurnResolver for CanonicalObjectiveResolver {
    fn preparation_scope(&self) -> Result<NativeTurnScope> { Ok(self.scope.clone()) }

    fn resolve<'a>(&'a self, input: &'a HostedTurnInput) -> NativeHostedResolveFuture<'a> {
        Box::pin(async move {
            let state = self.state.upgrade().context("original canonical Agentd owner is gone")?;
            ensure!(!input.cancellation.is_cancelled(), "original queued turn is cancelled");
            let (run, context) = state.resolve_canonical_queued_input(input)?;
            Ok(NativeHostedResolution { run, context, scope: self.scope.clone() })
        })
    }
}
