//! Independent current-state observation. A current numeric result cannot
//! establish that an older operation executed or authorize any new effect.

use super::*;
use serde::Deserialize;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalculatorState {
    pub target: CalculatorTargetIdentity,
    pub revision: u64,
    pub state: CalculatorValueState,
    pub state_sha256: Sha256Digest,
    pub receipt_pending: bool,
}

/// A clone retains only the original readback descriptor, never the effect lane.
#[derive(Clone)]
pub struct ProductionCalculatorObserver {
    identity: CalculatorTargetIdentity,
    recovery: Arc<dyn CalculatorRecoveryChannel>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Response {
    schema_version: u16,
    action: String,
    target: CalculatorTargetIdentity,
    observation_id: String,
    revision: u64,
    state: CalculatorValueState,
    state_sha256: String,
    receipt_pending: bool,
}

impl ProductionCalculatorTarget {
    pub fn state_observer(&self) -> ProductionCalculatorObserver {
        ProductionCalculatorObserver {
            identity: self.identity.clone(),
            recovery: Arc::clone(&self.recovery),
        }
    }
}

impl ProductionCalculatorObserver {
    pub fn target(&self) -> &CalculatorTargetIdentity {
        &self.identity
    }

    pub fn observe_state(&self, observation_id: &str) -> Result<CalculatorState, String> {
        if !model::lower_hex(observation_id, 32) || observation_id.bytes().all(|byte| byte == b'0')
        {
            return Err("invalid Calculator observation identity".into());
        }
        let request = serde_json::to_vec(&serde_json::json!({
            "schema_version":1,"action":"read_calculator","target":self.identity,
            "observation_id":observation_id
        }))
        .map_err(|error| error.to_string())?;
        let bytes = self.recovery.exchange(&request)?;
        if bytes.is_empty() || bytes.len() > CALCULATOR_RESPONSE_MAX_BYTES {
            return Err("Calculator readback exceeds its bound".into());
        }
        let response: Response =
            serde_json::from_slice(&bytes).map_err(|_| "invalid Calculator readback schema")?;
        let digest = response.state.digest()?;
        if response.schema_version != 1
            || response.action != "calculator_state"
            || response.target != self.identity
            || response.observation_id != observation_id
            || response.state_sha256 != digest.as_str()
        {
            return Err("Calculator readback does not match this observation".into());
        }
        Ok(CalculatorState {
            target: response.target,
            revision: response.revision,
            state: response.state,
            state_sha256: digest,
            receipt_pending: response.receipt_pending,
        })
    }
}
