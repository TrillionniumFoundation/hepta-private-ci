# Bounded SubagentStop failure observation

This is a test-only diagnostic, not a hook lifecycle fix.

## Original evidence

Source is `97ab00451799667faebac2c455a1e3176ebc90cb`. Windows job
`139620849733` in run `45732887025` ultimately succeeded after Bazel marked
`core-all-test` flaky. Its retained first failure for
`subagent_stop_replaces_stop_and_skips_internal_subagents` reports one hook
entry (`stop_hook_active=false`) where two are required. The original failure
block is 259,192 bytes, SHA-256
`b75bcd740acb1e1a2961ab79c50ba80f93e508d93a641a423f87868499096316`.

The trace records both child responses completing. The continuation request
therefore establishes that the first blocking hook succeeded. It does not
establish that the second hook was dispatched, started, or completed before
the test's two-second log deadline. The existing raw output has no corresponding
HookStarted/HookCompleted observation. Python startup latency, hook failure,
and pre-dispatch work are not established root causes. A second internal Bazel
shard attempt also failed; its test identity remains unknown in the retained
console and is not attributed to this case.

## Candidate scope

Only after the existing log wait returns an error, capture a non-waiting
snapshot of the one spawned child's status and already queued lifecycle
events. There are at most 128 one-poll calls (three lookups plus 125 event
polls), eight retained event records, and 4,096 bytes of added diagnostics.
Only fixed scalars/counts and bounded identifier prefixes (64 characters)
are collected. Hook output entries, status/error messages, commands, stdout,
and stderr are not copied or serialized. The summary records scanned/retained/
omitted counts, queue state, and byte truncation. Pending or failed lookups report unknown. Missing events remain
unknown because this is a bounded observation, not proof of non-dispatch.

The original error remains the cause. The success path, two-second deadline,
ten-millisecond polling interval, exact two-hook expectations, transcript
checks, root Stop exclusion, and internal-subagent exclusions are unchanged.
No production code, dependency, timeout, retry, or skip is changed.

Validation so far: `just fmt` and `git diff --check` exited zero; a byte-level
comparison preserved the original polling helper and the complete assertion
tail. Rust compilation and native execution of this candidate are pending.
