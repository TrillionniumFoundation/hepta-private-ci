from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Cross-crate product tests must use the governed publisher rather than the raw
# durable mutation that phase 2 intentionally makes crate-private.
tests = "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"
replace_once(
    tests,
    "use codex_hepta_prompt_registry::final_use_realization_binding;\n",
    "use codex_hepta_prompt_registry::final_use_realization_binding;\n"
    "use codex_hepta_prompt_registry::final_use_register_factor_binding;\n",
)

register_grant = '''    let register_actor = factor.proposer_id.clone();
    let register_scope = digest("scope:agentd-prompt-register");
    let register_binding =
        final_use_register_factor_binding(&factor, &register_actor, register_scope)
            .unwrap_or_else(|error| panic!("register binding: {error}"));
    let register_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-register".to_owned(),
        nonce: test_nonce("agentd-prompt-register"),
        binding: register_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_register = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &register_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("register signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: register_grant,
    };
    pipeline
        .publish_factor(
            &authority,
            &signed_register,
            &register_actor,
            register_scope,
            factor.clone(),
        )
        .unwrap_or_else(|error| panic!("publish factor: {error}"));
'''
replace_once(
    tests,
    '    let reviewer = id("reviewer:agentd-prompt");\n',
    register_grant + '    let reviewer = id("reviewer:agentd-prompt");\n',
)
replace_once(
    tests,
    '''        registry
            .register_factor(factor.clone())
            .unwrap_or_else(|error| panic!("register factor: {error}"));
''',
    "",
)

# A failed lease publication followed by a failed staged-context compensation is
# not a plain lease-store failure. Preserve both typed outcomes so restart and
# operator reconciliation never lose the cleanup failure.
runtime = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
replace_once(
    runtime,
    '''    FinalUseStore(PromptFinalUseStoreError),
    Publisher(codex_hepta_prompt_registry::DurableRegistryError),
''',
    '''    FinalUseStore(PromptFinalUseStoreError),
    FinalUseCompensation {
        store: PromptFinalUseStoreError,
        cleanup: AgentdPromptRuntimeError,
    },
    Publisher(codex_hepta_prompt_registry::DurableRegistryError),
''',
)
replace_once(
    runtime,
    '''        if let Err(error) = self.final_use.put(key, lease) {
            if disposition == PromptRuntimeStageDisposition::Inserted {
                let _ = self.runtime.clear_turn(thread_id, turn_id);
            }
            return Err(AgentdPromptPipelineError::FinalUseStore(error));
        }
''',
    '''        if let Err(store) = self.final_use.put(key, lease) {
            if disposition == PromptRuntimeStageDisposition::Inserted
                && let Err(cleanup) = self.runtime.clear_turn(thread_id, turn_id)
            {
                return Err(AgentdPromptPipelineError::FinalUseCompensation {
                    store,
                    cleanup,
                });
            }
            return Err(AgentdPromptPipelineError::FinalUseStore(store));
        }
''',
)
