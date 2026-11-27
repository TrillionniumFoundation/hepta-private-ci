# Windows federation workspace identity

The original Windows shard failed the unchanged test
`federation_recall_revalidates_revoked_grant_before_physical_send` because a
`PathUri` round trip removed the verbatim prefix from the registered canonical
workspace. The grant still bound the original canonical spelling. The production
fix canonicalizes an existing Windows workspace at both recall preparation and
physical-send revalidation; missing, relative, redirected or different workspace
identities remain rejected. The grant digest and authorization protocol did not
change.

Candidate `15ce2c14345c8f72bb3f3db58c229f156a10be9c` ran the complete original
`//codex-rs/ext/hepta-memory:hepta-memory-unit-tests` target on actual
`windows-latest`, with `--nocache_test_results`. Workflow `46006708541`, job
`140531575559`, completed successfully. The target passed in 37.4 seconds and
the clean-worktree check passed. `result.json` retains the actual workflow and
step identities; the compressed job log preserves the connector's decoded text
as exact UTF-8, including its original line endings. `log-binding.json` binds
those bytes.

The original failed shard is retained separately under
`qualification/windows-shard-one-20261127`. This targeted Windows result does
not claim that the full platform matrix passed.

The following source-only organization change moves the newly added Windows
tests into `federation_workspace_tests.rs`, as required by `AGENTS.md`. The two
test bodies, platform condition and production functions are unchanged. Its
actual `just fmt` receipt is in `qualification/fixture-format-20261127` and its
runtime regression remains part of the forthcoming common platform gate.
