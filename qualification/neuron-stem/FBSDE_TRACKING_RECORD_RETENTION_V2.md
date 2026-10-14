# Bound retained evidence graphs without changing model or budget semantics

Parent: `a7bae7d3b66e90d0f6e2b25fb85198239ab6f0a3`, Draft #1550.
This changes research evidence retention, not native execution ownership, a
learning algorithm, the classifier, the grammar, or any acceptance threshold.
The existing entrypoint and four original physical tracking lanes remain.

## A reproduced local cause, not a universal attribution

A predeclared single-pass local pair used the same final computational path,
simulator fit seed, original 750 BBH inputs and `local_participant_v2` frontend.
With `retained_objects_v1`, proposal 10,860 was denied at 232,504,256 process CPU
ns, with no feature miss. An observer-only GC callback measured a generation-2
collection wholly inside that original proposal interval: 232,094,408 process
CPU ns (99.8237%), including 220,184,371 caller-thread CPU ns. It collected zero
objects. This identifies a synchronous scan delay in THIS Python run, not all
previous hosted failures. No GC thresholds, enabled state, thread settings or
100,000,000 ns process-CPU admission were changed. Observation adds some cost.

Keeping all nested proposal/transition dictionaries alive until evaluation ends
makes their object graphs part of the collector's retained working set. The new
`serialized_records_v2` snapshots each completed record as immutable canonical
JSON bytes. One shared 256 MiB serialized-payload budget, per-stream row bounds
and a 512 KiB row bound reject overflow. These are payload bounds, not RSS bounds.
A caller's later mutation cannot change the saved record, and the buffer does
not retain the original nested object. It neither disables nor schedules GC.

Existing JSON ARRAY files and semantic values are retained. Emission streams
already serialized rows without materializing all nested graphs. Per-row reads
are available for the original post-run scorer. Ordinary exception cleanup still
writes the attempted denied proposal and partial output arrays. No crash/WAL
persistence guarantee is introduced. Capacity or write errors fail rather than
silently dropping evidence. The independent recording audit recomputes array
counts, original byte hashes, canonical payload sizes and shared usage.

Serialization happens where record appends already occurred, after the original
proposal compute interval. It is recorded separately and charged in the actual
study envelope; the newly named completion envelope also includes original
post-run audits. Neither is a zero-cost or whole deployment claim. The final
completion report's own write and interpreter startup are explicitly excluded.
No timing clock change or hidden budget waiver is introduced.

## Actual local pair and final-source revalidation

The serialized arm completed all 750 tasks, 6,000 answers and 15,000 proposals.
All 10,859 common returned proposal records and 4,816 complete output records
match the failed retained-object arm after removing ONLY timing fields. The
failed proposal remains denied in its original run. Comparison does not invent
a complete old-arm score or total-speedup ratio.

After adding final arithmetic checks, one final-source revalidation again
completed 750 tasks and 15,000 proposals. Proposal process CPU median 92,427 ns,
p99 4,148,665 ns, maximum 7,626,474 ns. No generation-2 collection occurred inside
these proposal intervals; three occurred elsewhere and their cost was NOT free.
Records retain 29,029,316 payload bytes; serialization/emission consumed
1,145,564,454 CPU ns. Measured study CPU through original audits was
10,305,010,591 ns (outer harness through return: 11,166,873,938 ns).
These are repeated historical tasks on one local host, not independent latency
trials or prospective efficacy. No stable deployment or new mmBERT result follows.

Learned, verified and exact methods each score 750/750. Exact tracking remains
cheaper; this repair supplies no NDU/System2 improvement. The old retained profile
stays default and explicit. Physical CI adds only the local-feature serialized
profile for each backend, with unique artifacts; earlier lanes are not removed.

## Executed validation and retained failures

369 model-free regressions passed. The new serialized generated-study integration
passed three actual Torch tests, including all 1,536 state outputs, 5,376 records,
original proposal arithmetic and retained cheap controls. Fifty-two inherited
non-tracking Torch tests passed. The thirteen inherited tracking tests had twelve
passes and one unchanged 100ms budget error in the retained-object path. This is
NOT an all-green Torch or final-head qualification. The failed run was not retried
until green. Initial test-message mismatch and diagnostic logs remain archived.

Use the original entrypoint with `--tracking-record-profile serialized_records_v2`
for the new path; use `retained_objects_v1` for the control. Full-repository/native
Rust, physical mmBERT budget stability and independent future risk/learning gates
remain open. Keep the PR Draft and production promotion disabled.

Reference semantics (not evidence of a universal fix):
https://docs.python.org/3.13/library/gc.html#gc.callbacks
https://docs.python.org/3.13/library/time.html#time.process_time_ns
