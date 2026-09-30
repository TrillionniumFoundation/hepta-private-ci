from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# The final-use store exposes a crate-local immutable inventory for startup
# reconciliation. It remains the sole owner of lease persistence.
final_use_store = "codex-rs/hepta-agentd/src/prompt_final_use_store.rs"
replace_once(
    final_use_store,
    '''    pub fn count(&self) -> Result<usize, PromptFinalUseStoreError> {
        self.ensure_available()?;
        Ok(self
            .leases
            .lock()
            .map_err(|_| PromptFinalUseStoreError::StatePoisoned)?
            .len())
    }
''',
    '''    pub fn count(&self) -> Result<usize, PromptFinalUseStoreError> {
        self.ensure_available()?;
        Ok(self
            .leases
            .lock()
            .map_err(|_| PromptFinalUseStoreError::StatePoisoned)?
            .len())
    }

    pub(crate) fn entries(
        &self,
    ) -> Result<Vec<(PromptFinalUseKeyV1, PromptFinalUseLeaseV1)>, PromptFinalUseStoreError> {
        self.ensure_available()?;
        Ok(self
            .leases
            .lock()
            .map_err(|_| PromptFinalUseStoreError::StatePoisoned)?
            .iter()
            .map(|(key, lease)| (key.clone(), lease.clone()))
            .collect())
    }
''',
)

runtime_path = Path("codex-rs/hepta-agentd/src/prompt_runtime.rs")
text = runtime_path.read_text(encoding="utf-8")

# Runtime state remains privately owned; startup reconciliation sees only a
# bounded cloned inventory and cannot mutate it except through clear_turn.
staged_marker = '''    fn staged_attachment(
        &self,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<Option<PromptRuntimeAttachmentV1>, AgentdPromptRuntimeError> {
'''
staged_inventory = '''    fn staged_entries(
        &self,
    ) -> Result<Vec<(PromptFinalUseKeyV1, PromptRuntimeAttachmentV1)>, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .staged
            .iter()
            .map(|(key, attachment)| {
                (
                    PromptFinalUseKeyV1 {
                        thread_id: key.thread_id.clone(),
                        turn_id: key.turn_id.clone(),
                    },
                    attachment.clone(),
                )
            })
            .collect())
    }

'''
if text.count(staged_marker) != 1:
    raise SystemExit("staged attachment marker changed")
text = text.replace(staged_marker, staged_inventory + staged_marker, 1)

# Public Agentd errors expose a stable composition classification rather than
# leaking the private on-disk store implementation.
error_marker = "#[derive(Debug)]\npub enum AgentdPromptPipelineError {\n"
stable_error = '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdPromptPipelineIntentError {
    Missing,
    Conflict,
    InvalidTransition,
    CapacityExceeded,
    Corrupt,
    StateLocked,
    StatePoisoned,
    Unavailable,
    IndeterminateDurability,
    ReopenRequired,
}

impl From<PromptPipelineIntentStoreError> for AgentdPromptPipelineIntentError {
    fn from(error: PromptPipelineIntentStoreError) -> Self {
        match error {
            PromptPipelineIntentStoreError::Missing => Self::Missing,
            PromptPipelineIntentStoreError::Conflict => Self::Conflict,
            PromptPipelineIntentStoreError::InvalidTransition => Self::InvalidTransition,
            PromptPipelineIntentStoreError::CapacityExceeded => Self::CapacityExceeded,
            PromptPipelineIntentStoreError::Corrupt => Self::Corrupt,
            PromptPipelineIntentStoreError::StateLocked => Self::StateLocked,
            PromptPipelineIntentStoreError::StatePoisoned => Self::StatePoisoned,
            PromptPipelineIntentStoreError::Unavailable => Self::Unavailable,
            PromptPipelineIntentStoreError::IndeterminateDurability => {
                Self::IndeterminateDurability
            }
            PromptPipelineIntentStoreError::ReopenRequired => Self::ReopenRequired,
        }
    }
}

'''
if text.count(error_marker) != 1:
    raise SystemExit("pipeline error marker changed")
text = text.replace(error_marker, stable_error + error_marker, 1)
text = text.replace(
    "    IntentStore(PromptPipelineIntentStoreError),\n",
    "    IntentStore(AgentdPromptPipelineIntentError),\n",
    1,
)
text = text.replace(
    "        intent_cleanup: Option<PromptPipelineIntentStoreError>,\n",
    "        intent_cleanup: Option<AgentdPromptPipelineIntentError>,\n",
    1,
)

# Convert every private store failure at the public boundary.
text = text.replace(
    ".map_err(AgentdPromptPipelineError::IntentStore)?",
    ".map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?",
)
text = text.replace(
    "            .map_err(AgentdPromptPipelineError::IntentStore)\n",
    "            .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))\n",
)
text = text.replace(
    '''                        intent_cleanup,
                    })
''',
    '''                        intent_cleanup: intent_cleanup.map(Into::into),
                    })
''',
    1,
)

old_reconcile = '''    fn reconcile_pipeline_intents(&self) -> Result<(), AgentdPromptPipelineError> {
        for intent in self
            .intents
            .entries()
            .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?
        {
            if intent.phase == PromptPipelineIntentPhase::Quarantined {
                return Err(AgentdPromptPipelineError::PipelineReconciliationRequired);
            }
            let staged = self
                .runtime
                .staged_attachment(&intent.key.thread_id, &intent.key.turn_id)
                .map_err(AgentdPromptPipelineError::Stage)?;
            let lease = self
                .final_use
                .get(&intent.key)
                .map_err(AgentdPromptPipelineError::FinalUseStore)?;
            let staged_matches = staged.as_ref().is_some_and(|attachment| {
                attachment.compilation_id == intent.operation_id
                    && attachment.context_attachment_digest
                        == intent.context_attachment_digest
            });
            let lease_matches = lease.as_ref().is_some_and(|lease| {
                lease.compilation_id == intent.operation_id
                    && lease.lease_digest == intent.lease_digest
            });
            if staged.is_some() != staged_matches || lease.is_some() != lease_matches {
                let _ = self.intents.advance(
                    &intent.key,
                    &intent.operation_id,
                    intent.lease_digest,
                    PromptPipelineIntentPhase::Quarantined,
                );
                return Err(AgentdPromptPipelineError::PipelineReconciliationRequired);
            }
            if intent.phase != PromptPipelineIntentPhase::Aborting
                && staged_matches
                && lease_matches
            {
                self.intents
                    .advance(
                        &intent.key,
                        &intent.operation_id,
                        intent.lease_digest,
                        PromptPipelineIntentPhase::Ready,
                    )
                    .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
                continue;
            }
            if !staged_matches && !lease_matches {
                self.intents
                    .remove(
                        &intent.key,
                        &intent.operation_id,
                        intent.lease_digest,
                    )
                    .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
                continue;
            }
            if self.compensate_pipeline_intent(&intent).is_err() {
                return Err(AgentdPromptPipelineError::PipelineReconciliationRequired);
            }
        }
        Ok(())
    }
'''
new_reconcile = '''    fn reconcile_pipeline_intents(&self) -> Result<(), AgentdPromptPipelineError> {
        let mut intents = self
            .intents
            .entries()
            .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
        let intent_keys = intents
            .iter()
            .map(|intent| intent.key.clone())
            .collect::<BTreeSet<_>>();
        let staged = self
            .runtime
            .staged_entries()
            .map_err(AgentdPromptPipelineError::Stage)?
            .into_iter()
            .collect::<BTreeMap<_, _>>();
        let leases = self
            .final_use
            .entries()
            .map_err(AgentdPromptPipelineError::FinalUseStore)?
            .into_iter()
            .collect::<BTreeMap<_, _>>();
        let orphan_keys = staged
            .keys()
            .chain(leases.keys())
            .filter(|key| !intent_keys.contains(*key))
            .cloned()
            .collect::<BTreeSet<_>>();

        // Schema-1 runtime/lease state predates the composition intent. Upgrade
        // it deterministically: matching pairs become Ready; effect-free single
        // owners are removed; unresolved or mismatched state is never guessed.
        for key in orphan_keys {
            match (staged.get(&key), leases.get(&key)) {
                (Some(attachment), Some(lease))
                    if attachment.compilation_id == lease.compilation_id
                        && attachment.context_attachment_digest
                            == lease.context_attachment_digest =>
                {
                    let intent = PromptPipelineIntentV1::new(
                        key.clone(),
                        lease.compilation_id.clone(),
                        lease.context_attachment_digest,
                        lease.lease_digest,
                    )
                    .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
                    self.intents
                        .begin(intent.clone())
                        .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
                    self.intents
                        .advance(
                            &key,
                            &intent.operation_id,
                            intent.lease_digest,
                            PromptPipelineIntentPhase::Ready,
                        )
                        .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
                    intents.push(PromptPipelineIntentV1 {
                        phase: PromptPipelineIntentPhase::Ready,
                        ..intent
                    });
                }
                (Some(_), None)
                    if !self
                        .runtime
                        .has_unresolved_turn(&key.thread_id, &key.turn_id)
                        .map_err(AgentdPromptPipelineError::Stage)? =>
                {
                    self.runtime
                        .clear_turn(&key.thread_id, &key.turn_id)
                        .map_err(AgentdPromptPipelineError::Stage)?;
                }
                (None, Some(_)) => {
                    self.final_use
                        .remove(&key)
                        .map_err(AgentdPromptPipelineError::FinalUseStore)?;
                }
                _ => return Err(AgentdPromptPipelineError::PipelineReconciliationRequired),
            }
        }

        for intent in intents {
            if intent.phase == PromptPipelineIntentPhase::Quarantined {
                return Err(AgentdPromptPipelineError::PipelineReconciliationRequired);
            }
            let staged = self
                .runtime
                .staged_attachment(&intent.key.thread_id, &intent.key.turn_id)
                .map_err(AgentdPromptPipelineError::Stage)?;
            let lease = self
                .final_use
                .get(&intent.key)
                .map_err(AgentdPromptPipelineError::FinalUseStore)?;
            let staged_matches = staged.as_ref().is_some_and(|attachment| {
                attachment.compilation_id == intent.operation_id
                    && attachment.context_attachment_digest
                        == intent.context_attachment_digest
            });
            let lease_matches = lease.as_ref().is_some_and(|lease| {
                lease.compilation_id == intent.operation_id
                    && lease.lease_digest == intent.lease_digest
            });
            if staged.is_some() != staged_matches || lease.is_some() != lease_matches {
                let _ = self.intents.advance(
                    &intent.key,
                    &intent.operation_id,
                    intent.lease_digest,
                    PromptPipelineIntentPhase::Quarantined,
                );
                return Err(AgentdPromptPipelineError::PipelineReconciliationRequired);
            }
            if intent.phase != PromptPipelineIntentPhase::Aborting
                && staged_matches
                && lease_matches
            {
                self.intents
                    .advance(
                        &intent.key,
                        &intent.operation_id,
                        intent.lease_digest,
                        PromptPipelineIntentPhase::Ready,
                    )
                    .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
                continue;
            }
            if !staged_matches && !lease_matches {
                self.intents
                    .remove(
                        &intent.key,
                        &intent.operation_id,
                        intent.lease_digest,
                    )
                    .map_err(|error| AgentdPromptPipelineError::IntentStore(error.into()))?;
                continue;
            }
            if self.compensate_pipeline_intent(&intent).is_err() {
                return Err(AgentdPromptPipelineError::PipelineReconciliationRequired);
            }
        }
        Ok(())
    }
'''
if text.count(old_reconcile) != 1:
    raise SystemExit("phase 3 reconciler body changed")
text = text.replace(old_reconcile, new_reconcile, 1)

runtime_path.write_text(text, encoding="utf-8")

# Make the stable error classification reachable wherever the existing public
# Agentd pipeline error is reachable.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use prompt_runtime::AgentdPromptPipelineError;\n",
    "pub use prompt_runtime::AgentdPromptPipelineError;\n"
    "pub use prompt_runtime::AgentdPromptPipelineIntentError;\n",
)
