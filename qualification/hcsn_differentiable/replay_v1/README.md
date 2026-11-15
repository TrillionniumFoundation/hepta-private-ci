# Real six-checkpoint recovery diagnostic

This protocol selects all six last observed complete epoch checkpoint entities
from the original C2 inventory (epochs 116/76/126/50/127/72). The fixed selection
and source-byte identities precede new training. They are complete checkpoint
states, including Adam step counts, model, Torch RNG and episode-order RNG.
Original controller job `1a1c74f3308-be2a-75` remains unknown; it is never restarted.
Its four reports, two zero-byte interrupted states and absent aliases/terminal
are not repaired in place or silently relabelled complete.

For each fit, fresh reference process A runs two actual training batches.
Producer B independently restores the same source state, executes the first
batch and atomically saves model/Adam/RNG plus the exact next-batch cursor.
Another fresh process C loads those real bytes and executes batch two.
The orchestrator independently decodes both final Torch states and requires
exact model/optimizer/RNG/cursor equality plus identical batch/loss/gradient
receipts. This is 24 real optimizer calls across the six recovery diagnostics.

Two declared controls on the first fit add one call each: omitting Adam state
must change the final model and optimizer, and crashing after real Torch save,
flush and fsync but before canonical publication must leave no canonical state.
The retained private temporary must decode to the real one-step producer state.
All 26 calls, failed processes and import/setup costs remain charged.

Limits are two concurrent workers, one CPU thread per worker, 8 GiB address
space, 300 seconds per worker plus a 330-second outer process timeout.
Original source, manifest, prepared episode, checkpoint and program identities
are checked before and after. The exact Python/Torch build is recorded in the
native PREEXECUTION before any new worker starts. D is loaded by the existing
episode reader but no new D evaluation or confirmation E access is performed.

Source commit `5cb83d9c76beedf4c1c917e4bf561f5f26261ce7` preceded both native
attempts. They actually launched, then each received authoritative cancelled
status, signal 15 and `timed_out=false`. No complete replay state/report was
produced. Actual optimizer calls in those attempts remain UNKNOWN; no later
26-call success may replace that unknown cumulative cost. The original launch,
status, stdout/stderr, plan commitment and incident ledger are preserved under
`../evidence/real-checkpoint-replay-native-20261112/`. No third native training
attempt was started. Cancel source and descendant termination remain unproven.

A separate zero-model read-only export succeeded: all six selected states and
bound inputs are retained in an 11,397,159-byte ZIP with SHA256
`37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75`.
Its 555 members contain 56,675,710 original bytes. Binary transfer and an
explicit Ubuntu CPU resource/runtime amendment are separate pending steps.
A successful future diagnostic would establish checkpoint continuity and local
crash safety for its declared states and operations. It would add
**zero independently complete C2 training replays**, establishes no adequacy,
numerical accuracy, efficacy, baseline superiority or energy benefit, and
does not resolve the original missing controller terminal. HOLD_NO_GO remains.
