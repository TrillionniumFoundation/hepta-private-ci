# Fixed fresh-object cache setup accounting

SOURCE ONLY; requires independent static review and separate run admission.
Do not modify or replace the original cache benchmark. Bind its exact source
freeze, RESULT, WAIT4 receipt and independent saved-result review.

Original six tests and five paired serving comparisons passed. The original
compile and serialization CPU observations were zero: these are censored or
sub-resolution observations, NOT free operations. In particular the stored
compile break-even zero is not a credible claim. Load recomputes72maps and its
observed CPU was .003997229. Original serving median ratio .667227 remains the
fixed-workload result; no new quality, end-to-end or universal speed conclusion.

## Prospective measurement
Same literal profile as original benchmark: fixed model digest a*64, permuted
text/image semantic inventories, tau .5/2. No model or dataset. Construct only
one literal fixture outside timings, without applying any serving law.

In exactly this order, one aggregate timed batch each:
1. Compile64fresh cache objects from the same immutable profile.
2. Serialize each of those64objects once.
3. Load each of those64documents once, independently reconstructing profile/maps.

No warmup, search, early stop, repeated timing batch, favorable-run selection,
new serving timing or adaptive count. Hold all objects/documents through the end.
This measures fresh-object setup in an already loaded interpreter, not cold
interpreter startup. Imports/setup/checks remain included in whole-child costs.
Use process_time_ns and perf_counter_ns per batch and report clock metadata.
Report all batch values, per-instance average, and unresolved/censored status if
an aggregate CPU value is zero; do not claim true zero or retry until positive.
Instrumentation increments destination-call counts inside both timed stages;
this adds overhead, so the setup estimate is instrumented rather than an exact
uninstrumented latency. Clock calls/list construction likewise remain in timings.

Exact map calls: compile64*72=4608; load64*72=4608; total9216.
Serialization itself does not compute destination maps. Post-timing128 dumps
verify each compiled/loaded object's identity and roundtrip; their cost is inside
whole-child CPU but outside the stage estimates. All generation keys unchanged;
all64serialized documents equivalent. Runtime aborts on count/identity mismatch.
No numerical qualification tests rerun; exact saved original qualification is
checked before measurement. No forward, decoder, training or serving call.

Estimate compile-only and load-only break-even from per-instance positive batch
CPU divided by the ORIGINAL fixed saved serving CPU difference. At least one
batch is required if the positive setup estimate amortizes within one batch.
If setup is unresolved or original saved delta not positive, report null.
Serialization is separately reported, not silently zero; caller can include it
when budgeting a persisted-cache path. Do not reinterpret this historical-ratio
estimate as a new simultaneous paired performance test or a new acceptance gate.

## Controls and ledger
Existing synthetic benchmark lock, nonblocking refusal; no replacement lock,
retry or concurrent numeric run. CPU0, single numerical thread, 3CPU/20wall,
512MiB/4MiB outputs; all child outcomes fully waited with wait4 and exit/RSS/CPU/
wall recorded. Original .775283 child CPU is historical additional cost. Source,
review and supervisor tail remain outside-child/nonzero caveats. Original
artifacts immutable; new outputs confined to this candidate RUN_ONCE.
No original validation/TEST, dataset generation, model payload, scientific gate
change, deployment or default behavior change. This accounting supplement does
not substitute for ongoing group-heldout generation experiments.
