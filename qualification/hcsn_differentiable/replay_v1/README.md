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

This initial source stage is prepared for native execution. No new optimizer
call or replay pass is yet claimed by this document. Execution evidence will
be appended separately. A successful diagnostic establishes checkpoint
continuity and local crash safety for these states and operations. It adds
**zero independently complete C2 training replays**, establishes no adequacy,
numerical accuracy, efficacy, baseline superiority or energy benefit, and
does not resolve the original missing controller terminal. HOLD_NO_GO remains.
