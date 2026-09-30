from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Make begin idempotent across an interrupted phase and return the durable phase
# so an identical retry can resume rather than regress the transition.
intent_store = "codex-rs/hepta-agentd/src/prompt_pipeline_intent_store.rs"
replace_once(
    intent_store,
    '''    pub(crate) fn begin(
        &self,
        intent: PromptPipelineIntentV1,
    ) -> Result<(), PromptPipelineIntentStoreError> {
        intent.validate()?;
        self.commit(|intents| {
            if let Some(existing) = intents.get(&intent.key) {
                return if existing == &intent {
                    Ok(())
                } else {
                    Err(PromptPipelineIntentStoreError::Conflict)
                };
            }
            if intents.len() >= MAX_INTENTS {
                return Err(PromptPipelineIntentStoreError::CapacityExceeded);
            }
            intents.insert(intent.key.clone(), intent);
            Ok(())
        })
    }
''',
    '''    pub(crate) fn begin(
        &self,
        intent: PromptPipelineIntentV1,
    ) -> Result<PromptPipelineIntentPhase, PromptPipelineIntentStoreError> {
        intent.validate()?;
        self.commit(|intents| {
            if let Some(existing) = intents.get(&intent.key) {
                return if existing.same_identity(&intent) {
                    Ok(existing.phase)
                } else {
                    Err(PromptPipelineIntentStoreError::Conflict)
                };
            }
            if intents.len() >= MAX_INTENTS {
                return Err(PromptPipelineIntentStoreError::CapacityExceeded);
            }
            intents.insert(intent.key.clone(), intent);
            Ok(PromptPipelineIntentPhase::Preparing)
        })
    }
''',
)
replace_once(
    intent_store,
    '''    pub(crate) fn entries(
        &self,
    ) -> Result<Vec<PromptPipelineIntentV1>, PromptPipelineIntentStoreError> {
''',
    '''    pub(crate) fn count(&self) -> Result<usize, PromptPipelineIntentStoreError> {
        self.ensure_available()?;
        Ok(self
            .intents
            .lock()
            .map_err(|_| PromptPipelineIntentStoreError::StatePoisoned)?
            .len())
    }

    pub(crate) fn entries(
        &self,
    ) -> Result<Vec<PromptPipelineIntentV1>, PromptPipelineIntentStoreError> {
''',
)

replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod prompt_final_use_store;\nmod prompt_runtime;\n",
    "mod prompt_final_use_store;\nmod prompt_pipeline_intent_store;\nmod prompt_runtime;\n",
)

runtime_path = Path("codex-rs/hepta-agentd/src/prompt_runtime.rs")
text = runtime_path.read_text(encoding="utf-8")

imports = '''use crate::prompt_pipeline_intent_store::PromptPipelineIntentPhase;
use crate::prompt_pipeline_intent_store::PromptPipelineIntentStore;
use crate::prompt_pipeline_intent_store::PromptPipelineIntentStoreError;
use crate::prompt_pipeline_intent_store::PromptPipelineIntentV1;
'''
marker = "use crate::prompt_final_use_store::PromptFinalUseStoreError;\n"
if text.count(marker) != 1:
    raise SystemExit("prompt runtime final-use import marker changed")
text = text.replace(marker, marker + imports, 1)

# Raw runtime introspection is crate-private and used only by the composition
# reconciler; it does not expose a new product capability.
staged_count = '''    pub fn staged_count(&self) -> Result<usize, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .staged
            .len())
    }
'''
staged_helpers = staged_count + '''
    fn staged_attachment(
        &self,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<Option<PromptRuntimeAttachmentV1>, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .staged
            .get(&key)
            .cloned())
    }

    fn has_unresolved_turn(
        &self,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<bool, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        Ok(has_unresolved_dispatch(
            &self
                .state
                .lock()
                .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?,
            &key,
        ))
    }
'''
if text.count(staged_count) != 1:
    raise SystemExit("staged_count body changed")
text = text.replace(staged_count, staged_helpers, 1)

# Phase 2 has already made the raw runtime owner private and introduced the
# explicit compensation variant. Generalize that result for three durable owners.
error_pattern = re.compile(
    r"    FinalUseStore\(PromptFinalUseStoreError\),\n"
    r"    FinalUseCompensation \{\n"
    r"        store: PromptFinalUseStoreError,\n"
    r"        cleanup: AgentdPromptRuntimeError,\n"
    r"    \},\n"
)
replacement = '''    FinalUseStore(PromptFinalUseStoreError),
    IntentStore(PromptPipelineIntentStoreError),
    PipelineCompensation {
        initial_store: PromptFinalUseStoreError,
        runtime_cleanup: Option<AgentdPromptRuntimeError>,
        lease_cleanup: Option<PromptFinalUseStoreError>,
        intent_cleanup: Option<PromptPipelineIntentStoreError>,
    },
    PipelineReconciliationRequired,
'''
text, count = error_pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit("phase 2 compensation error variant changed")

replace_pairs = [
    (
        '''    final_use: Arc<PromptFinalUseLeaseStore>,
    final_use_validator: PromptFinalUseValidator,
''',
        '''    final_use: Arc<PromptFinalUseLeaseStore>,
    intents: Arc<PromptPipelineIntentStore>,
    final_use_validator: PromptFinalUseValidator,
''',
    ),
    (
        '''            .field("runtime", &self.runtime)
            .field("final_use", &self.final_use)
            .finish_non_exhaustive()
''',
        '''            .field("runtime", &self.runtime)
            .field("final_use", &self.final_use)
            .field("intents", &self.intents)
            .finish_non_exhaustive()
''',
    ),
]
for old, new in replace_pairs:
    if text.count(old) != 1:
        raise SystemExit(f"prompt runtime owner marker changed: {old.splitlines()[0]}")
    text = text.replace(old, new, 1)

old_open = '''        let final_use = PromptFinalUseLeaseStore::open(runtime_directory)
            .map_err(AgentdPromptPipelineError::FinalUseStore)?;
        Ok(Self {
            registry: Mutex::new(registry),
            runtime: Arc::new(runtime),
            final_use: Arc::new(final_use),
            final_use_validator: PromptFinalUseValidator::default(),
        })
'''
new_open = '''        let final_use = PromptFinalUseLeaseStore::open(runtime_directory)
            .map_err(AgentdPromptPipelineError::FinalUseStore)?;
        let intents = PromptPipelineIntentStore::open(runtime_directory)
            .map_err(AgentdPromptPipelineError::IntentStore)?;
        let owner = Self {
            registry: Mutex::new(registry),
            runtime: Arc::new(runtime),
            final_use: Arc::new(final_use),
            intents: Arc::new(intents),
            final_use_validator: PromptFinalUseValidator::default(),
        };
        owner.reconcile_pipeline_intents()?;
        Ok(owner)
'''
if text.count(old_open) != 1:
    raise SystemExit("pipeline open block changed")
text = text.replace(old_open, new_open, 1)

compile_start = text.index("    #[expect(\n        clippy::too_many_arguments,\n        reason = \"Preserve explicit signed operation-bound fields\"\n    )]\n    pub fn compile_and_stage(")
compile_end = text.index("    pub fn clear_turn(\n", compile_start)
new_compile = '''    #[expect(
        clippy::too_many_arguments,
        reason = "Preserve explicit signed operation-bound fields"
    )]
    pub fn compile_and_stage(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        portfolio: &SelectedPromptPortfolioV1,
        exercise_request: &PromptExerciseRequestV1,
        compilation_request: PromptRegistryCompilationRequestV2,
    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {
        self.reconcile_pipeline_intents()?;
        let issued_unix_ms = compilation_request.now_unix_ms;
        let compiled = {
            let registry = self
                .registry
                .lock()
                .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?;
            compile_prompt_registry_v2(&registry, portfolio, exercise_request, compilation_request)
                .map_err(|error| AgentdPromptPipelineError::Compilation(error.to_string()))?
        };
        let lease = PromptFinalUseLeaseV1::from_compiled(
            portfolio,
            &compiled,
            issued_unix_ms,
            requested_deadline_ms,
        )
        .map_err(AgentdPromptPipelineError::FinalUseLease)?;
        let key = PromptFinalUseKeyV1::new(thread_id, turn_id)
            .map_err(AgentdPromptPipelineError::FinalUseStore)?;
        let intent = PromptPipelineIntentV1::new(
            key.clone(),
            lease.compilation_id.clone(),
            compiled.attachment.attachment_digest(),
            lease.lease_digest,
        )
        .map_err(AgentdPromptPipelineError::IntentStore)?;
        let phase = self
            .intents
            .begin(intent.clone())
            .map_err(AgentdPromptPipelineError::IntentStore)?;
        if phase == PromptPipelineIntentPhase::Ready {
            return Ok(PromptRuntimeStageDisposition::Unchanged);
        }

        let disposition = match self.runtime.stage_compiled_prompt_context(
            thread_id,
            turn_id,
            model,
            requested_deadline_ms,
            &compiled,
        ) {
            Ok(disposition) => disposition,
            Err(error) => {
                self.intents
                    .remove(&key, &intent.operation_id, intent.lease_digest)
                    .map_err(AgentdPromptPipelineError::IntentStore)?;
                return Err(AgentdPromptPipelineError::Stage(error));
            }
        };
        self.intents
            .advance(
                &key,
                &intent.operation_id,
                intent.lease_digest,
                PromptPipelineIntentPhase::RuntimeStaged,
            )
            .map_err(AgentdPromptPipelineError::IntentStore)?;

        if let Err(initial_store) = self.final_use.put(key.clone(), lease) {
            return match self.compensate_pipeline_intent(&intent) {
                Ok(()) => Err(AgentdPromptPipelineError::FinalUseStore(initial_store)),
                Err((runtime_cleanup, lease_cleanup, intent_cleanup)) => {
                    Err(AgentdPromptPipelineError::PipelineCompensation {
                        initial_store,
                        runtime_cleanup,
                        lease_cleanup,
                        intent_cleanup,
                    })
                }
            };
        }
        self.intents
            .advance(
                &key,
                &intent.operation_id,
                intent.lease_digest,
                PromptPipelineIntentPhase::LeaseCommitted,
            )
            .map_err(AgentdPromptPipelineError::IntentStore)?;
        self.intents
            .advance(
                &key,
                &intent.operation_id,
                intent.lease_digest,
                PromptPipelineIntentPhase::Ready,
            )
            .map_err(AgentdPromptPipelineError::IntentStore)?;
        Ok(disposition)
    }

'''
text = text[:compile_start] + new_compile + text[compile_end:]

clear_start = text.index("    pub fn clear_turn(\n", compile_start)
clear_end = text.index("    fn prepare_final_use(\n", clear_start)
new_clear_and_helpers = '''    pub fn clear_turn(
        &self,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<bool, AgentdPromptPipelineError> {
        let key = PromptFinalUseKeyV1::new(thread_id, turn_id)
            .map_err(AgentdPromptPipelineError::FinalUseStore)?;
        let intent = self
            .intents
            .get(&key)
            .map_err(AgentdPromptPipelineError::IntentStore)?;
        if let Some(intent) = intent.as_ref() {
            self.intents
                .advance(
                    &key,
                    &intent.operation_id,
                    intent.lease_digest,
                    PromptPipelineIntentPhase::Aborting,
                )
                .map_err(AgentdPromptPipelineError::IntentStore)?;
        }
        let cleared = match self.runtime.clear_turn(thread_id, turn_id) {
            Ok(cleared) => cleared,
            Err(error) => {
                if let Some(intent) = intent.as_ref() {
                    let _ = self.intents.advance(
                        &key,
                        &intent.operation_id,
                        intent.lease_digest,
                        PromptPipelineIntentPhase::Quarantined,
                    );
                }
                return Err(AgentdPromptPipelineError::Stage(error));
            }
        };
        self.final_use
            .remove(&key)
            .map_err(AgentdPromptPipelineError::FinalUseStore)?;
        if let Some(intent) = intent {
            self.intents
                .remove(&key, &intent.operation_id, intent.lease_digest)
                .map_err(AgentdPromptPipelineError::IntentStore)?;
        }
        Ok(cleared)
    }

    fn compensate_pipeline_intent(
        &self,
        intent: &PromptPipelineIntentV1,
    ) -> Result<
        (),
        (
            Option<AgentdPromptRuntimeError>,
            Option<PromptFinalUseStoreError>,
            Option<PromptPipelineIntentStoreError>,
        ),
    > {
        let mut runtime_cleanup = None;
        let mut lease_cleanup = None;
        let mut intent_cleanup = self
            .intents
            .advance(
                &intent.key,
                &intent.operation_id,
                intent.lease_digest,
                PromptPipelineIntentPhase::Aborting,
            )
            .err();
        match self
            .runtime
            .has_unresolved_turn(&intent.key.thread_id, &intent.key.turn_id)
        {
            Ok(false) => {
                if let Err(error) = self
                    .runtime
                    .clear_turn(&intent.key.thread_id, &intent.key.turn_id)
                {
                    runtime_cleanup = Some(error);
                }
                if runtime_cleanup.is_none()
                    && let Err(error) = self.final_use.remove(&intent.key)
                {
                    lease_cleanup = Some(error);
                }
            }
            Ok(true) => runtime_cleanup = Some(AgentdPromptRuntimeError::IndeterminatePending),
            Err(error) => runtime_cleanup = Some(error),
        }
        if runtime_cleanup.is_none() && lease_cleanup.is_none() && intent_cleanup.is_none() {
            if let Err(error) = self.intents.remove(
                &intent.key,
                &intent.operation_id,
                intent.lease_digest,
            ) {
                intent_cleanup = Some(error);
            }
        }
        if runtime_cleanup.is_some() || lease_cleanup.is_some() || intent_cleanup.is_some() {
            let quarantine = self.intents.advance(
                &intent.key,
                &intent.operation_id,
                intent.lease_digest,
                PromptPipelineIntentPhase::Quarantined,
            );
            if intent_cleanup.is_none() {
                intent_cleanup = quarantine.err();
            }
            return Err((runtime_cleanup, lease_cleanup, intent_cleanup));
        }
        Ok(())
    }

    fn reconcile_pipeline_intents(&self) -> Result<(), AgentdPromptPipelineError> {
        for intent in self
            .intents
            .entries()
            .map_err(AgentdPromptPipelineError::IntentStore)?
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
                    .map_err(AgentdPromptPipelineError::IntentStore)?;
                continue;
            }
            if !staged_matches && !lease_matches {
                self.intents
                    .remove(
                        &intent.key,
                        &intent.operation_id,
                        intent.lease_digest,
                    )
                    .map_err(AgentdPromptPipelineError::IntentStore)?;
                continue;
            }
            if self.compensate_pipeline_intent(&intent).is_err() {
                return Err(AgentdPromptPipelineError::PipelineReconciliationRequired);
            }
        }
        Ok(())
    }

    #[cfg(test)]
    fn intent_count(&self) -> Result<usize, AgentdPromptPipelineError> {
        self.intents
            .count()
            .map_err(AgentdPromptPipelineError::IntentStore)
    }

'''
text = text[:clear_start] + new_clear_and_helpers + text[clear_end:]

# Empty staged state must clean both remaining composition owners explicitly.
old_absent = '''        let attachment = self.runtime.prepare(request)?;
        let Some(attachment) = attachment else {
            let _ = self.final_use.remove(&key);
            return Ok(None);
        };
'''
new_absent = '''        let attachment = self.runtime.prepare(request)?;
        let Some(attachment) = attachment else {
            self.final_use
                .remove(&key)
                .map_err(final_use_store_host_error)?;
            if let Some(intent) = self
                .intents
                .get(&key)
                .map_err(pipeline_intent_host_error)?
            {
                self.intents
                    .remove(&key, &intent.operation_id, intent.lease_digest)
                    .map_err(pipeline_intent_host_error)?;
            }
            return Ok(None);
        };
'''
if text.count(old_absent) != 1:
    raise SystemExit("prepare empty cleanup changed")
text = text.replace(old_absent, new_absent, 1)

old_terminal = '''        let key = PromptFinalUseKeyV1::new(&record.thread_id, &record.turn_id)
            .map_err(final_use_store_host_error)?;
        let clear = terminal_clears_stage(&record);
        self.runtime.record(record)?;
        if clear {
            self.final_use
                .remove(&key)
                .map_err(final_use_store_host_error)?;
        }
        Ok(())
'''
new_terminal = '''        let key = PromptFinalUseKeyV1::new(&record.thread_id, &record.turn_id)
            .map_err(final_use_store_host_error)?;
        let clear = terminal_clears_stage(&record);
        let intent = if clear {
            self.intents
                .get(&key)
                .map_err(pipeline_intent_host_error)?
        } else {
            None
        };
        if let Some(intent) = intent.as_ref() {
            self.intents
                .advance(
                    &key,
                    &intent.operation_id,
                    intent.lease_digest,
                    PromptPipelineIntentPhase::Aborting,
                )
                .map_err(pipeline_intent_host_error)?;
        }
        self.runtime.record(record)?;
        if clear {
            self.final_use
                .remove(&key)
                .map_err(final_use_store_host_error)?;
            if let Some(intent) = intent {
                self.intents
                    .remove(&key, &intent.operation_id, intent.lease_digest)
                    .map_err(pipeline_intent_host_error)?;
            }
        }
        Ok(())
'''
if text.count(old_terminal) != 1:
    raise SystemExit("terminal cleanup block changed")
text = text.replace(old_terminal, new_terminal, 1)

host_mapper = '''fn final_use_store_host_error(error: PromptFinalUseStoreError) -> PromptRuntimeHostError {
    PromptRuntimeHostError::new("agentd_prompt_final_use_store_error", error.to_string())
}
'''
new_host_mapper = host_mapper + '''
fn pipeline_intent_host_error(error: PromptPipelineIntentStoreError) -> PromptRuntimeHostError {
    PromptRuntimeHostError::new("agentd_prompt_pipeline_intent_error", error.to_string())
}
'''
if text.count(host_mapper) != 1:
    raise SystemExit("final-use host error mapper changed")
text = text.replace(host_mapper, new_host_mapper, 1)

runtime_path.write_text(text, encoding="utf-8")
