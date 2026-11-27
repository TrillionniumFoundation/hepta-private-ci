# Seed137 explicit repair continuation

This directory defines a new, independently reviewed research attempt. It does
not modify the original experiment result or rerun the original workflow.
Publication and execution remain disabled until root materializes the exact
reviewed workflow and the two execution-binding fields.

## Actual original failure

The original source was `2d95f617effefb1a3f3baaadd4fe23816b2ba247` and the original
run was `45986114332`. Artifact `15191543148` is 694064 bytes with SHA256
`3b47fa7ec94d9fe4a2449e6b59d3c42520cac24fad8d35a1839f18efca64f342`.
Its CI job returned success, while seed137's own result was `PARENT_ABORTED`.
After 5 complete forwards, 1 backward, 24 returned root certificates and one
returned shared-key fit, a duplicate `wall_seconds` argument in the logger
raised `TypeError`. Seed137 produced no candidate checkpoint or BP result.
That is an implementation failure, not a scientific abstention.

The only modification to the existing transfer runner is:

```python
ledger.event("fit_returned", fit_evidence=row)
```

The entire fit row, including its elapsed time, is retained under a dedicated
payload key. Ledger-owned timing and counters retain their original meaning.
A separate pure stdlib regression reproduced the exact original failure and
verified this fix with the actual fit metadata and reserved-key controls.
The original source and original failed receipts are preserved independently.

## Evidence reuse and its boundary

The exact old artifact is downloaded once through the read-only GitHub API.
All 85 members are checked. Only the declared seed137 records and source47
unavailability receipt are materialized as research inputs. The public parent,
source, train-only normalizer and train/dev/retain identifiers are independently
read from their original fixed public sources. No test NPZ is extracted.

All 24 seed137 root calls returned a unique root with a complete domain
certificate. `cache_replay.py` requires their original order, exact descriptor
and all mathematical inputs and constants as `float.hex` values. It rechecks
the old receipt's full SHA at use. Different parameters, changed constants,
repeated or reordered requests and unknown arguments reject. There is no live
inverse or nearby-root fallback. Old root certificate timing remains labelled
as original work. New cache lookup work is timed separately.

The old root JSON did not itself serialize every input argument. Its input
identity is causally bound by the exact original wrapper/core, parent tensor
bytes, recorded model profile and unchanged constants recipe, complete cached
trace, and ordered descriptors in the original durable call ledger. The new
binding makes that reconstruction explicit; it does not claim that an old
root JSON alone is a self-contained proof of all its original input bits.

The first fit's receipt did not save the direction vector. Both shared-key
fits therefore count as new work: the first is repeated and the second runs
for the first time. Seed137's accumulated fit
count becomes three, exceeding the old per-parent limit of two. This is
explicitly authorized only by the new repair budget; unused seed83 capacity
does not make the old per-parent budget unchanged.

The first new model call reloads the original seed137 PT and runs all 80 train
queries with `compile_trace=False`. It compares original scores, receiver
features and physical trace outputs with the fixed prior tolerances and exact
decisions. This is one complete forward, not the old three-forward/one-backward
qualification repeated. No recurrent-linear trace replays occur. A failure
stops before new fits or BP. The proposals always use the complete original
SHA-pinned train trace and correct-query mask; fresh outputs never redefine
donors, targets or selection.

## Frozen method and evaluation

The original `boundary_program.construct`, root-selection rule, two doses
0.25/1.0, both shared-key objectives, unused wrong-role/random construction,
F32 realization helper, 40 sender-drive coordinates and radius are unchanged.
The direct candidates are saved as complete PT files and reloaded before any
candidate evaluation. All other registered tensor/buffer value bytes and the
readout storage aliases remain fixed; PT container/header bytes are not claimed
to be identical.

The BP function body is reused unchanged from the original transfer runner:
the same train80 row order, fixed PCG64 minibatches, seed, Adam settings,
16 updates, loss, clipping, projection and snapshots at steps4/16. It uses the
original cached parent scores for the unchanged protection objective.

Four available candidates are sealed before any candidate dev/retain call.
Each is evaluated on train80 and combined dev32/retain28 using the original
six-tick model. COPY doses remain unavailable because source47 produced no
candidate. All six planned slots remain in the denominator. The same KEEP,
retain protection, development ranking and tie rules apply.

## Separate resource and operation accounts

| Work | New full forwards | New backwards | New fits | New real roots |
|---|---:|---:|---:|---:|
| Fresh-parent parity | 1 | 0 | 0 | 0 |
| Exact fixed-program reconstruction | 0 | 0 | 2 | 0 |
| Original BP16 schedule | 16 | 16 | 0 | 0 |
| Four candidates, two evaluations each | 8 | 0 | 0 | 0 |
| Maximum new repair | 25 | 16 | 2 | 0 |

The repair maximum is 150 body ticks, 768 paired queries, 16 optimizer steps,
24 cache lookups, 3 real directions, at most256 Lagrange iterations, and zero
extra recurrent-linear trace replays. Compiler abstention can reduce candidate
evaluation counts; it cannot substitute another method or increase caps.

The original cross-parent attempt consumed 30F/18B/16 updates/1 fit/26 real
root calls. If the repair completes fully, the combined known totals are
55F/34B/32 updates/3 fits/26 real root calls, 330 body ticks and1468 paired
queries. The old supervisor's incomplete-count flag is preserved, while the
new result distinguishes new counts from combined known lower bounds. The
original failed fit and original qualification costs are not erased or charged
as zero. Setup, shared initialization, cache validation, program construction,
BP and candidate evaluation costs remain separate. Conversational planning
cost is unavailable, not assumed zero.

The separate owned research child has180 CPU seconds and300 wall seconds,
one CPU,1GiB memory and64 tasks. The systemd scope's330-second lifetime includes
cleanup, not additional model allowance. The existing20-second call return gate
and complete-population physical gate remain unchanged. Source admission,
unknown execution, cache mismatch and implementation failures terminate this
attempt without retry. Counters charge started operations and preserve partial
or unknown work on failure.

Before publication, a separate stdlib cache-interface qualification checks
24 exact returns and five concrete rejection classes. Its27 charged lookups
(including three rejected inputs) and24 returns are recorded separately from
the future repair's24. Those controls execute zero model, fit, root or residual
operations and make no quality claim.

All train/dev/retain observations were already seen. This is a controlled
developmental continuation and a cross-parent stability check, with no fresh
holdout, financial-return, production-deployment, native-transaction or author
benchmark reproduction claim. The preserved original two-parent experiment
and this explicit repair are reported separately.
