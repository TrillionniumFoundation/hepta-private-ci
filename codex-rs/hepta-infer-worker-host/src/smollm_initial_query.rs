//! Initial-only query consumption by the original selected material/session owner.
//! Observations are historical; this adds no Agentd route or evaluated admission.
use super::*;
use crate::smollm_neural_read::SmolLmMeasuredForwardV1;
use std::time::Duration;

// Only this original owner module constructs this same-port borrowed permit.
// It cannot be serialized, cloned, extracted or made from receipt/DTO fields.
pub(crate) struct InitialReadPermitV1<'a> {
    port: &'a SmolLmNeuralReadPortV1,
    selection_digest: Digest32,
}

impl InitialReadPermitV1<'_> {
    pub(crate) fn consume_for(self, port: &SmolLmNeuralReadPortV1) -> Result<Digest32, String> {
        if !std::ptr::eq(self.port, port) || self.selection_digest.is_zero() {
            return Err("initial permit belongs to another original port".to_owned());
        }
        Ok(self.selection_digest)
    }
}

/// Borrowed actual load and completed forward from this original owner only.
/// The bounded read-only callback must not dispatch effects or reenter the port.
pub struct InitialSelectedReadObservationV1<'a> {
    load: &'a SmolLmMeasuredLoadV1,
    forward: &'a SmolLmMeasuredForwardV1,
    selection_digest: Digest32,
    scores_q32: Option<&'a [i64]>,
}

impl InitialSelectedReadObservationV1<'_> {
    pub fn measured_load(&self) -> &SmolLmMeasuredLoadV1 {
        self.load
    }
    pub fn measured_forward(&self) -> &SmolLmMeasuredForwardV1 {
        self.forward
    }
    pub fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }
    pub fn scores_q32(&self) -> Option<&[i64]> {
        self.scores_q32
    }
}

impl PreparedSelectedInitialSmolLmV1 {
    /// Call on the host blocking executor with the original operation deadline.
    /// This distinct initial route never satisfies the evaluated neural trait.
    /// The read-only callback sees historical evidence before final checks.
    /// A later Err cannot retract values it copied; only successful return
    /// completes this bounded before/after observation, without effect authority.
    pub fn with_current_initial_read<T>(
        &mut self,
        query: &str,
        action_ids: &[StableId],
        execution: &codex_hepta_agentd::NeuralCognitiveExecutionV1,
        observe: impl for<'a> FnOnce(InitialSelectedReadObservationV1<'a>) -> Result<T, String>,
    ) -> Result<T, String> {
        // The existing observation owns all CURRENT/selector/load checks and
        // closes its capsule on clock/callback errors. All locks end here.
        self.observe(initial_now_seconds, |_| {
            if execution.remaining()? > Duration::from_secs(2) {
                return Err(
                    "initial query requires the original at-most-two-second window".to_owned(),
                );
            }
            Ok(())
        })?;
        let mut material = self.material.take().ok_or("initial owner is unavailable")?;
        let association = self
            .association
            .as_ref()
            .ok_or("initial load association unavailable")?;
        let port = self
            .session
            .port
            .as_ref()
            .ok_or("initial session is closed")?;
        execution.check()?;
        let selection = material.selection_digest();
        let (scores, receipt) = port.execute_initial(
            InitialReadPermitV1 {
                port,
                selection_digest: selection,
            },
            query,
            action_ids,
            execution,
        )?;
        execution.check()?;
        let result = port.with_measurements(|load, forward| {
            let forward = forward.ok_or("original completed forward unavailable")?;
            let ids = load
                .control_load_ids()
                .ok_or("initial load was not settled")?;
            if load.ready_digest() != association.0
                || ids != (association.1.as_str(), association.2.as_str())
                || forward.ready_digest() != load.ready_digest()
                || forward.response_digest() != receipt
            {
                return Err("initial forward differs from its original load".to_owned());
            }
            Ok(std::panic::catch_unwind(std::panic::AssertUnwindSafe(
                || {
                    observe(InitialSelectedReadObservationV1 {
                        load,
                        forward,
                        selection_digest: selection,
                        scores_q32: scores.as_deref(),
                    })
                },
            )))
        })??;
        // Never unwind while original measurement locks are held.
        let result = match result {
            Ok(result) => result?,
            Err(panic) => std::panic::resume_unwind(panic),
        };
        execution.check()?;
        let now = initial_now_seconds()?;
        let current = self
            .current
            .current_registry_view(now)
            .map_err(|e| e.to_string())?;
        material
            .with_current(current, now, |_| ())
            .map_err(|e| e.to_string())?;
        execution.check()?;
        self.material = Some(material);
        Ok(result)
    }
}
