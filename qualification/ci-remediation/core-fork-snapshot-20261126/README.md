# Observe the completed fork before its first task starts

The Windows shard 1 job for source
`97ab00451799667faebac2c455a1e3176ebc90cb` retried
`agent::control::tests::spawn_agent_can_fork_parent_thread_history_with_sanitized_items`
after its full-history equality assertion failed. The first attempt recorded
85 passed and one failed case; its later pass made the target `FLAKY`.
The retained complete failure section is 47,274 bytes with SHA-256
`3fa9d1ec06d96b194a26bf8119ba4d478309504b05658c64fe52d1c7e9a6b1ab`.
The actual history contained additional first-turn AGENTS, environment, and
developer context messages. The retry does not erase the first failure.

`spawn_agent_with_metadata` finishes creating the child and then submits its
initial input before returning. The test subsequently reads live history and
the reference context baseline. The child's first turn can append context and
advance that baseline between those operations, so those reads do not reliably
observe the initial fork that the assertion describes.

The fixture now uses the existing `pause_next_startup_before_delivery` test hook.
`spawn_forked_thread` sanitizes inherited history and appends the child guidance
before calling the manager. The manager finishes startup and registration before
this hook pauses delivery. The agent's initial-input submission occurs after
delivery, so the paused fixture can capture the complete fork history and its
reference baseline before that first task starts.

The fixture releases the hook and awaits the same original spawn, checks that the
published and returned child identities agree, and retains the original initial
task and recorded-user-message check. The full history equality, managed-policy
preservation, reference-baseline equality, no-hint branch, and shutdown assertions
remain intact. There is no new production hook, history filtering, sleep, retry,
timeout increase, or model response.

This is a source-level fixture synchronization repair. Native qualification still
requires the original test to execute on the new source, with first-attempt
outcomes retained. It does not establish a production fork defect or a model
capability improvement.
