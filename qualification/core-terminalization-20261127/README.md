# Original core fixture terminalization

The original Windows shard recorded a rejected context injection while
`persist_thread_for_tree_resume` built its durable resume fixture. Production
`abort_all_tasks` intentionally returns when an existing start or terminalization
owner retains custody. The fixture previously injected its marker immediately.

The fixture now captures the exact start and task-terminalization completion
witnesses while holding the active-turn publication lock, releases every lock,
and awaits those witnesses before injection. It uses a bounded 10-second wait;
unresolved ownership still fails. It neither retries a rejected injection nor
relaxes the production history fence. The original tests and assertions remain.

The guardian prompt-cache test now includes the actual unsuccessful outcome in
its four failure messages. This preserves the original assessment requirement
and exposes the cause of the earlier flaky fourth review instead of inventing
a retry or suppressing the error.

The actual pinned Rust 1.96.1 `just fmt` run completed successfully; the four
formatted source hashes are retained in `qualification/fixture-format-20261127`.
The registered Windows workflow runs the complete original core unit target
with test caching disabled. Until its terminal result is recorded, this
candidate does not claim that the core tests or full platform matrix passed.
