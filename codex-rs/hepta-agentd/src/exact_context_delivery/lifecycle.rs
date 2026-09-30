//! Lifecycle operations on the existing exact delivery owner. No second store
//! or authority is introduced; publication follows exact-state -> runtime-state
//! lock order and never awaits or invokes a physical provider here.
use super::*;

impl AgentdExactContextDeliveryOwner {
    #[cfg(test)]
    pub(crate) fn stage(
        &self,
        thread_id: &str,
        turn_id: &str,
        compiled: PromptRegistryCompiledContextV3,
    ) -> Result<(), ExactContextDeliveryError> {
        self.stage_with(thread_id, turn_id, compiled, || Ok(()))
    }

    /// Publish the runtime projection while the exact-state reservation is
    /// exclusive. The callback must not reenter this owner or perform effects.
    /// An error publishes no exact stage; uncertain runtime durability remains
    /// fenced by the runtime owner and cannot release bytes after restart.
    pub(crate) fn stage_with<R, E>(
        &self,
        thread_id: &str,
        turn_id: &str,
        compiled: PromptRegistryCompiledContextV3,
        publish: impl FnOnce() -> Result<R, E>,
    ) -> Result<R, E>
    where
        E: From<ExactContextDeliveryError>,
    {
        let _stage_time = self.measure(Phase::StagePublication);
        self.store.ensure_available()?;
        validate_runtime_id(thread_id, "thread id")?;
        validate_runtime_id(turn_id, "turn id")?;
        compiled
            .validate()
            .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        let key = ExactTurnKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        let mut state = self
            .state
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        self.store.ensure_available()?;
        if state.preparing.contains(&key)
            || state.durable.has_unresolved_for_turn(thread_id, turn_id)
        {
            return Err(ExactContextDeliveryError::RecoveryRequired.into());
        }
        if let Some(existing) = state.staged.get(&key) {
            if existing.as_ref() != &compiled {
                return Err(ExactContextDeliveryError::Conflict(
                    "a different compiled context is already staged for this turn",
                )
                .into());
            }
            return publish();
        }
        // A retired turn is not a new admission identity. Tool continuation
        // retains the original stage instead of reopening a completed turn.
        if state
            .durable
            .pre_sends
            .values()
            .any(|record| record.thread_id == thread_id && record.turn_id == turn_id)
            || settled_history::has_seen_turn(&state.durable, thread_id, turn_id)
        {
            return Err(ExactContextDeliveryError::RecoveryRequired.into());
        }
        if state.staged.len() >= MAX_STAGED_CONTEXTS {
            return Err(ExactContextDeliveryError::Capacity.into());
        }
        let result = publish()?;
        state.staged.insert(key, Arc::new(compiled));
        Ok(result)
    }

    /// Retire only an unused or fully settled turn. A preparation reservation
    /// is already an admission boundary, even before its durable pre-send.
    pub(crate) fn clear_turn_with<E>(
        &self,
        thread_id: &str,
        turn_id: &str,
        clear_runtime: impl FnOnce() -> Result<bool, E>,
    ) -> Result<bool, E>
    where
        E: From<ExactContextDeliveryError>,
    {
        self.store.ensure_available()?;
        validate_runtime_id(thread_id, "thread id")?;
        validate_runtime_id(turn_id, "turn id")?;
        let key = ExactTurnKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        let mut state = self
            .state
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        self.store.ensure_available()?;
        if state.preparing.contains(&key)
            || state.durable.has_unresolved_for_turn(thread_id, turn_id)
        {
            return Err(ExactContextDeliveryError::RecoveryRequired.into());
        }
        let runtime_removed = clear_runtime()?;
        Ok(state.staged.remove(&key).is_some() || runtime_removed)
    }

    pub(crate) fn measure(&self, phase: Phase) -> metrics::Measurement<'_> {
        self.store.metrics.measure(phase)
    }

    pub(crate) fn diagnostics(&self) -> Result<serde_json::Value, ExactContextDeliveryError> {
        let state = self
            .state
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        let unresolved = state
            .durable
            .pre_sends
            .keys()
            .filter(|attempt| state.durable.has_unresolved_attempt(attempt))
            .count();
        Ok(serde_json::json!({
            "schema": "hepta.context-owner-diagnostics.v1",
            "authority": "deny_all",
            "requires_reopen": self.store.poisoned.load(Ordering::Acquire),
            "staged_turns": state.staged.len(),
            "staged_payload_bytes": state.staged.values().map(|value| value.payload().len()).sum::<usize>(),
            "preparing_turns": state.preparing.len(),
            "active_attempts": state.active.len(),
            "unresolved_attempts": unresolved,
            "pre_send_records": state.durable.pre_sends.len(),
            "final_records": state.durable.terminals.len(),
            "nonfinal_observations": state.durable.observations.len(),
            "recent_settled_attempts": state.durable.settled_attempts.len(),
            "checkpointed_settled_attempts": state.durable.settlement_checkpoint.archived_count,
            "settlement_checkpoint_sequence": state.durable.settlement_checkpoint.last_sequence,
            "reserved_completion_bytes": completion_reserve(&state.durable)?,
            "phases": self.store.metrics.snapshot(),
        }))
    }
}

pub(super) fn retire_completed_stage(state: &mut ExactRuntimeState, key: &ExactTurnKey) {
    if state.preparing.contains(key)
        || state
            .durable
            .has_unresolved_for_turn(&key.thread_id, &key.turn_id)
    {
        return;
    }
    let ended = settled_history::ended_turn(&state.durable, &key.thread_id, &key.turn_id)
        || state.durable.pre_sends.iter().any(|(attempt, record)| {
            record.thread_id == key.thread_id
                && record.turn_id == key.turn_id
                && state
                    .durable
                    .terminals
                    .get(attempt)
                    .is_some_and(|terminal| {
                        terminal.disposition == "Rejected"
                            || terminal.provider_receipt.as_ref().is_some_and(|receipt| {
                                matches!(
                                    &receipt.terminal,
                                    ProviderTerminal::Completed {
                                        end_turn: Some(true),
                                        ..
                                    }
                                )
                            })
                    })
        });
    if ended {
        // Raw context dies here; proof, attempt and observation history stays.
        state.staged.remove(key);
    }
}
