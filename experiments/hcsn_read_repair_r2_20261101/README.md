# Paid raw-event READ and prefix reconstruction

This additive round preserves the complete R1/R2 sources and failures. It asks
whether acquired raw information can repair each ambiguous query, rather than
raising aggregate accuracy by mixing easy and hard queries. Every registered
policy emits all four query answers. The primary model answer is the frozen R1
Flow/Diagonal neural argmax after an actual causal prefix replay.

`RawProvider` accepts only an integer index of an already-ingested missing
slot. It receives no labels, availability mask, dependencies, or teacher
posterior. A successful READ returns the actual original24-field WRITE and its
original source timestamp, advances the logical service clock by0.1, and charges
the publicly known event fee once. The client caches that raw event. Repeating
the same READ has zero additional fee and wait. Strict reply checks bind raw
one-hot fields, original time, arrival time, fee and wait to the visible
request contract.

The client restores the original historical slot and replays only ingested
observations through the current query. Later writes keep their original
order; the recovered old WRITE is not appended as if it were a new update.
Replay inserts the elapsed READ wait and a repeated current query for answering.
The next source interval is reduced by that elapsed wait. Overlap is rejected
when a new source frame actually arrives; no future clock/content is consulted
by the decision. The registered profile has source gaps at least0.25 and at
most two reads totaling0.2 at one query. This is retrospective internal state
reconstruction, and does not rewrite previously executed environment actions.

The policies are fixed confidence<0.95 READ, conservative always_READ, never_READ,
and a simple price cutoff. Its task-specific cutoff is selected once on
development ordinary-reference continuations. All prices and cutoffs are
registered beforehand. Utility is the mean of four correct-answer indicators
minus actual READ fees. Logical wait, symbolic fees, CPU and energy are separate
quantities; no equality between logical service time and network wall latency
is claimed.

The exact ordinary q=2/3 policy independently checks that it requests identical
slots. It receives the same executed raw payload and timing trace as the six
core/seed arms. A provider trajectory is executed once per policy/world and
explicitly shared as matched information. It is not counted as seven separate
provider executions. Neural reconstruction is actually executed for each frozen
model, with reuse only for bit-identical x/dt/observed prefix hashes. The model
ledger records every actual forward batch, replay sequence and replay frame.

The four primary conditions retain the known R2 generator. Separate prospective
secondary cohorts erase two writes, or shift write/bridge order and value
sampling. The same policy code runs in every cohort, without a family ID.
Conservative always_READ acquires every visible missing slot and then uses
generic typed replay; it is the qualified secondary fallback. An unobserved
order-shifted write can be indistinguishable from a known-law prefix, so the
confidence policy's secondary outcomes are reported without claiming a hidden
law certificate. Acquired-information success does not establish unread
inference, arbitrary-generator reliability or analytical-core advantage.

Run from the repository root with CPU PyTorch/NumPy/SciPy and one OpenMP/BLAS
thread. Use a fresh directory and outer complete-child meter:

```sh
python -m experiments.hcsn_read_repair_r2_20261101.campaign freeze --out NEW_RUN
python -m experiments.hcsn_four_stage_flow_20261031.meter --out PREPARE_METER -- \
  python -m experiments.hcsn_read_repair_r2_20261101.campaign prepare --out NEW_RUN
# Publish/read back source, protocol, candidate and provider preflight identities.
python -m experiments.hcsn_four_stage_flow_20261031.meter --out CONFIRM_METER -- \
  python -m experiments.hcsn_read_repair_r2_20261101.campaign confirm --out NEW_RUN \
    --candidate-sha EXACT_SHA --publication EXACT_COMMIT
```

Saved source-world arrays and executed provider traces reconstruct each replay
input. Query logits and pool-index maps reconstruct each emitted answer. Labels
and final-write availability occur only in the environment scorer; no such
fields are passed to the client, service or neural model. High fees may make a
quality-preserving policy lose utility. The protocol does not force a positive
economic result or treat CPU seconds as joules.
