//! Attach installed model assistance to the daemon's original runtime owners.

use std::sync::Arc;

use tokio_util::sync::CancellationToken;

use super::AgentdConfig;
use crate::AgentdError;
use crate::AgentdNeuronRuntimeV2Host;
use crate::AgentdState;
use crate::PlasticityRuntimeHandleV1;

/// Original daemon owners made available after native runtime composition.
/// Handles retain their existing admission, lifetime and bounded queue checks;
/// this context opens no writer, journal, model or artifact store.
pub struct AgentdSelfIterationModelOwnerContextV2 {
    neuron: Option<Arc<AgentdNeuronRuntimeV2Host>>,
    plasticity: Option<PlasticityRuntimeHandleV1>,
}

impl AgentdSelfIterationModelOwnerContextV2 {
    pub(crate) fn from_state(state: &Arc<AgentdState>) -> Self {
        Self {
            neuron: state.neuron_runtime_v2.get().cloned(),
            plasticity: state.plasticity_runtime_handle(),
        }
    }

    /// The daemon's existing Neuron host, when the installed profile composed it.
    pub fn neuron_host(&self) -> Option<Arc<AgentdNeuronRuntimeV2Host>> {
        self.neuron.clone()
    }

    /// A bounded sender to the sole governed plasticity owner, when present.
    pub fn plasticity_handle(&self) -> Option<PlasticityRuntimeHandleV1> {
        self.plasticity.clone()
    }
}

pub(super) type SelfIterationModelOwner = Box<
    dyn FnOnce(
            AgentdSelfIterationModelOwnerContextV2,
            CancellationToken,
        ) -> std::pin::Pin<
            Box<dyn std::future::Future<Output = Result<(), AgentdError>> + Send>,
        > + Send,
>;

impl AgentdConfig {
    pub fn with_self_iteration_model_owner<F, Fut>(self, owner: F) -> Result<Self, AgentdError>
    where
        F: FnOnce(CancellationToken) -> Fut + Send + 'static,
        Fut: std::future::Future<Output = Result<(), AgentdError>> + Send + 'static,
    {
        self.with_self_iteration_model_owner_context(move |_context, cancellation| {
            owner(cancellation)
        })
    }

    /// Start installed model assistance with the already composed native owners.
    pub fn with_self_iteration_model_owner_context<F, Fut>(
        mut self,
        owner: F,
    ) -> Result<Self, AgentdError>
    where
        F: FnOnce(AgentdSelfIterationModelOwnerContextV2, CancellationToken) -> Fut
            + Send
            + 'static,
        Fut: std::future::Future<Output = Result<(), AgentdError>> + Send + 'static,
    {
        if self.self_iteration_model_owner.is_some() {
            return Err(AgentdError::Invalid(
                "self-iteration model owner is already configured".into(),
            ));
        }
        self.self_iteration_model_owner = Some(Box::new(move |context, cancellation| {
            Box::pin(owner(context, cancellation))
        }));
        Ok(self)
    }

    pub(crate) fn take_self_iteration_model_owner(&mut self) -> Option<SelfIterationModelOwner> {
        self.self_iteration_model_owner.take()
    }
}
