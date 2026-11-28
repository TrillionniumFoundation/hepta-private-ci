# Preserve independent lifecycle fixtures after the first native failure

This is a prospective repair to the failed control at common source
`e33367318734f782eb5e921856d68ce4410e4466`; production code is unchanged.
The first 28-control command reached its 240-second cap with 19 named passes,
3 named failures and 6 without a terminal result. Its raw log SHA-256 is
`7cdb73e95a8da1e0e6b33ebb5c51fcbcde82fa2f7b166b2fb72651ba619d459d`.
No successful aggregate gate is inferred from those partial results.

The failed `draining_closes_native_admission_and_cannot_finish_with_live_worker`
opened multiple `AgentdState` instances over one fixture's exclusive prompt
pipeline owners. `RegistryOpen("StateLocked")` occurred before its worker began.
The production lock and owner constructors remain unchanged. Each independent
cached-Running and late-Draining state now uses an existing `AgentdFixture` with
its own actual temporary Fleet and durable directories. Each Fleet performs its
real lifecycle transitions. The actual worker keeps its original state, Ledger
and compute permit; no state is cloned to replace the cached-state counterexample.

All original assertions, the function name, five/ten-second waits and zero-fit
counter requirements remain. The cached Running state does not observe the
intermediate Draining transition before the Stopped generation rejection.
Only this previously failed function is eligible for this slice's next execution;
the passed cancellation function and the other 18 named passes are not rerun.
The exclusive native owner freezes the actual common descendant and remaining
pending cohort under Root's unchanged 3600-second shared pool before execution.
No scientific sample, final split, old E1–E6 scope or budget is added or reset.

Actual formatter postimages and source hashes precede the next native attempt.
The first failure remains intact; a repaired pass never replaces its receipt.
