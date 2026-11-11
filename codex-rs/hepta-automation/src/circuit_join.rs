//! Materialized reference envelopes for frozen join observations.
//!
//! A join's output contains causal identities and accepted output digests. It
//! does not claim to contain those facts' payloads. Downstream encoders resolve
//! the references through their existing fact owners under the frozen schema.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AutomationStore;
use crate::CircuitActivationStatusV2;
use crate::CircuitRunV2;
use crate::TaskFlowError;
use crate::circuit_profile::digest;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;

/// Join nodes must declare this schema on their output. Every outgoing edge
/// therefore checks the successor's input schema against this reference format.
pub fn circuit_join_output_schema_v2() -> Sha256Digest {
    Sha256Digest::for_bytes(b"hepta.circuit.join-envelope.v2")
}

/// The JSON object returned by canonical_bytes is the complete join output.
/// Vector order preserves the frozen arrival/causal order; callers must not
/// sort or replace these observations when recovering a downstream computation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitJoinEnvelopeV2 {
    pub node_id: String,
    pub round: u32,
    pub causal_parents: Vec<u64>,
    pub arrival_input_digests: Vec<Sha256Digest>,
}

impl CircuitJoinEnvelopeV2 {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, TaskFlowError> {
        text(&self.node_id)?;
        if self.round >= 4_096
            || self.causal_parents.is_empty()
            || self.causal_parents.len() > 4_096
            || self.causal_parents.contains(&0)
            || self.arrival_input_digests.is_empty()
            || self.arrival_input_digests.len() > 256
        {
            return Err(invalid("join envelope exceeds the bounded profile"));
        }
        for value in &self.arrival_input_digests {
            digest(value)?;
        }
        let bytes = serde_json::to_vec(self)
            .map_err(|e| TaskFlowError::Corrupt(format!("join envelope serialization: {e}")))?;
        if bytes.len() > 131_072 {
            return Err(invalid("join envelope exceeds byte bound"));
        }
        Ok(bytes)
    }
}

impl CircuitRunV2 {
    /// Read the completed join's exact frozen bytes. Run state is constructed by
    /// the reducer or canonical durable replay, never by unchecked Deserialize.
    pub fn join_output_bytes(&self, activation_id: u64) -> Result<Vec<u8>, TaskFlowError> {
        let activation = self
            .activations
            .get(&activation_id)
            .ok_or_else(|| invalid("unknown join"))?;
        if activation.status != CircuitActivationStatusV2::Completed
            || activation.arrivals.is_empty()
        {
            return Err(invalid("join output is not completed and frozen"));
        }
        let envelope = CircuitJoinEnvelopeV2 {
            node_id: activation.node_id.clone(),
            round: activation.round,
            causal_parents: activation.causal_parents.clone(),
            arrival_input_digests: activation.arrival_inputs.clone(),
        };
        let bytes = envelope.canonical_bytes()?;
        let digest = Sha256Digest::for_bytes(&bytes);
        if digest != activation.input_digest || activation.output_digest.as_ref() != Some(&digest) {
            return Err(TaskFlowError::Corrupt(
                "join output differs from its frozen input".to_string(),
            ));
        }
        Ok(bytes)
    }
}

impl AutomationStore {
    /// Materialize only from the existing owner's verified immutable history.
    /// Reopening a run returns the same bytes without dispatching any work.
    pub async fn bounded_circuit_join_output(
        &self,
        run_id: &str,
        activation_id: u64,
    ) -> Result<Vec<u8>, TaskFlowError> {
        self.bounded_circuit_run(run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".to_string()))?
            .join_output_bytes(activation_id)
    }
}
