//! Current Calculator state from the exact attached application, without an
//! effect handle. State cannot replace a retained operation's causal receipt.

use std::io::Read;

use codex_hepta_memory::CalculatorState;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::ProductionCalculatorObserver;

use crate::AgentdError;

#[derive(Clone)]
pub struct AgentdCalculatorStateObserver {
    inner: ProductionCalculatorObserver,
}

impl AgentdCalculatorStateObserver {
    pub(crate) fn new(inner: ProductionCalculatorObserver) -> Self {
        Self { inner }
    }

    pub fn target(&self) -> &CalculatorTargetIdentity {
        self.inner.target()
    }

    pub fn observe_state(&self) -> Result<CalculatorState, AgentdError> {
        let mut bytes = [0_u8; 16];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
        let observation_id: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
        self.inner
            .observe_state(&observation_id)
            .map_err(AgentdError::Protocol)
    }
}
