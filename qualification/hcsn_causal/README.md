# Prospective causal controls and streaming acquisition

This stage implements two missing interfaces for the next HCSN experiment. It
does not launch training, replace the original 170-run matrix, train a stronger
frontend, or establish model benefit. It is outside `qualification/hcsn` and
`qualification/hcsn_training`, so their frozen source inventories remain intact.

## Four-arm comparison

| Arm | Kernel | Mechanism |
| --- | --- | --- |
| A | Ordinary smooth | Fixed |
| B | Ordinary smooth | Dynamic boundary/value feedback |
| C | Analytic | Fixed |
| D | Analytic | The same feedback mechanism as B |

These A/B/C/D arm letters belong to the **prospective factorial design**. They
are not the original implementation names A (value feature recurrence) and B
(population flux). `comparison.py` is a result reader, not an implementation of
these four trained models. A comparison needs a complete `Design` whose hashes
bind the exact common frontend, acquired data, common projection/addressor/head,
numerical configuration, and measurement environment. The measurement profile
must fix hardware/software, clock/latency protocol, physical-energy counter and
the entire cost boundary, including preprocessing, search, failed attempts,
rematerialization, training, validation and evaluation. Those artifacts and
original executor receipts must be independently inspected; a matching string
or a supplied integer is not evidence of actual implementation/capacity.

For each task and scale the reader requires every registered seed in every arm,
the same active parameter and persistent state capacity, shared initialization,
full submitted examples/updates and the same realized search updates. Missing
rows remain in the denominator. Duplicate completions are rejected, preventing
best-of-restarts selection. Historical failed/OOM attempts remain in the cost
sum. Unknown terminal state or training cost blocks comparison; missing physical
B/D energy blocks the prespecified D-B quality/latency/energy pass, without
imputing zero. A/C missing energy is still reported and does not establish a
four-arm energy result. Nonfinite contrast/interval or accumulated cost is
rejected explicitly even when its individual input values were finite.

An arm/seed-complete list alone does not prove complete attempt costs. The new
`inventory.scan_inventory` reads a closed owner ledger with a start and terminal
file for every attempt. It rejects unresolved starts, duplicate keys, foreign
entries and changed/link-backed files, and binds every Attempt field to the raw
records. `compare(..., inventory=...)` rescans that scope and rejects omitted or
modified attempts. Without an inventory, results remain an **unqualified paired
summary** and the net-gain flag stays false. The owner must supply its complete
ledger scope; this local filesystem verifier cannot prove that no attempts
exist elsewhere. It is not an authorization or cryptographic attestation layer.

The returned paired contrasts are B-A, D-C, C-A, D-B and D-C-B+A. Their Student-t
intervals use a Bonferroni family of five; seed independence and the sampling
assumptions remain statistical assumptions. The strict net gate requires the
prespecified D-B quality improvement and improved latency and **total** physical
energy. Quality is explicitly higher-is-better (use negative loss if desired).
Do not pool unrelated tasks, scales or OOD strata to conceal a failure. A local
stratum pass is not an automatic adoption decision or a claim of universal gain.

No prospective model budget is silently chosen here. The original campaign and
full-budget B audit must finish before a new empirical comparison. Concrete
frontend/core/head assets, active capacity, total search budget, data separation,
success margins and prospective confirmation must be frozen before running it.

## Event assimilation and physical time

The existing stream/content stage rejects nonpositive held-input durations.
Historical multimodal rows include distinct observations at an unchanged source
frontier. Replacing their duration with epsilon would manufacture time; reducing
several contents to a mean would change their information.

`event_stream.py` therefore exposes these separate operations:

1. `PrefixEncoder.encode`: verify the checkpoint bytes against a frozen
   identity; invoke the supplied encoder on the available raw prefix alone.
2. `EventCore.advance`: evolve only over positive elapsed **feature-ready** time.
3. `EventCore.observe`: assimilate a token matrix instantaneously, including at
   zero elapsed time. Preserve every token and every distinct content event.
4. `EventCore.query`: read at the current frontier without injecting an answer.

The clock is a declared common microsecond coordinate. Actual sensor clock
calibration and crop correctness belong to the acquisition owner and are not
measured by this adapter. Raw acquisition, encoder start, and encoder completion
have distinct timestamps. `PrefixEncoder` requires the owner's common monotonic
clock and samples it before and after encoding; contextual features are not
visible until the returned ready time. Queue/encoder duration is retained rather
than silently treating raw-arrival time as feature availability. The real runner
must also measure core/readout latency and full cost. The completion clock is
sampled after the callback result is materialized, copied into owned immutable
CPU tokens, and checked; lazy/device conversion cannot occur after readiness.
The encoder must synchronize any other asynchronous work that its result does
not expose through materialization. Late source content is accepted when its encoded tokens are ready;
past answers cannot be re-queried from a later state. Simultaneous events use
their explicit frozen order; the implementation does not claim permutation
invariance. A successful query at T seals all arrivals through T; later events
cannot backfill that already published frontier, even with a larger same-time
order. Multiple same-time events must be ingested before the first query there;
query swaps at the sealed frontier remain pure reads. Widths such as 768 and 1536 are retained as token matrices, without
truncation/padding into the historical 55-feature interface. Unsupported
modalities or mismatched frontend identities are rejected.

Complete incoming batches are validated before touching core state. A core
exception or interruption poisons the stream and forbids automatic replay, because the core may
already have changed. This is an in-process failure boundary; durable atomic
content/receipt commit and fresh-process recovery still require the existing
owner/runtime integration. Callback purity, actual use of checkpoint weights,
pretraining contamination and encoder strength cannot be certified by a Python
wrapper. The test core is a simple deterministic probe, not a trained encoder.

## Reproduction and next actual experiments

Run from the repository root with the pinned NumPy/SciPy versions already used
by the original reference package:

```bash
python -m qualification.hcsn_causal.checks --output /tmp/hcsn-reference-attempt-01.json
```

The immutable receipt includes exact source hashes, every method outcome and
software identity. It rejects overwriting an earlier receipt. The focused CI
contains no model fitting or CUDA launch. The historical 170-run controller
`1a1acdd69f2-fc05-5757` and its 400-update identities remain unchanged.

The real streaming experiment remains open until it connects a verified strong
common frontend, factual query/head supervision, async real arrivals,
simultaneous content, long interference, query swap and held-out OOD. Tests of
the adapter cannot close those scientific requirements. Backbone expansion
requires replicated benefit at additional widths, depths, data and context
sizes, followed by the separate deployment and adoption evidence.

Source basis: [stream #4941](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4941),
[content #4942](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4942),
and the exact [real-media readiness audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/246d6e4b5be520934af7d145cf0f7304f5c5adf4/qualification/hcsn/evidence/stream-content-20261106/multimodal-readiness.json).
