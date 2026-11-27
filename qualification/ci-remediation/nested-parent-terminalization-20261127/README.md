# Join the nested-parent fixture's terminal owner

The nested-parent reload test starts its parent through
`spawn_v2_reload_test_child`. That helper submits real user input and starts a
regular task. The fixture previously changed only the agent status and then
assigned `None` to `active_turn`, under an incorrect comment that no task runner
existed. This could drop a running task outside its controlled interruption path
or remove the exact marker required by an existing terminalization owner.

This candidate changes only that fixture preparation. It invokes the existing
interruption path, waits through the existing terminalization completion drain,
and asserts that the active slot and admission fences are clear. It then keeps
the original interrupted-status marker and mailbox drain. It does not begin
session shutdown: the production residency path still has to capture the
parent's authority, shut down the selected parent, and evict it during reload.

The original child shutdown has already completed at this point. V2 terminal
notification is awaited by the terminalization owner and uses a non-triggering
inter-agent message; this spawn path does not start the legacy detached
completion watcher. The completion drain joins existing finish/abort owners. It
does not grant a general admission lease or clear an unexpected start. The new
idle assertions reject such an unexpected state instead of erasing it. A failed
terminalization remains fenced and is subject to the existing test-target
deadline.

All original parent-eviction, environment, permission, client-MCP, shared
execution-policy identity, worker-model, provider, and message assertions remain
unchanged. The Sender route and other tests are unchanged. There is no new
timeout, polling loop, retry, mock response, production change, or dependency
change.

The retained Intel attempt declared 282 tests, printed 281 distinct `ok` results,
and named this nested-parent case as still running before the target's
900-second timeout. It did not retain a phase or stack locating the blocked
await. This is a source-proven fixture ownership repair, not proof that the
recorded timeout took this path. The separate owned-thread completion candidate
only covered the Sender route and does not establish coverage for this case.

Local qualification is limited to source comparison and formatting checks.
No new Rust compilation, native test, or CI execution has run for this candidate.
