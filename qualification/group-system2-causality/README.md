# Group System 2 causality receipts (research / DENY_ALL)

This independently testable protocol strengthens the **evidence boundary**, not
reasoning accuracy or inference authority. It is an additive descendant of
`hepta-ndu`'s Group and System2 shadow seams: no native runtime, model loader,
Cell, task scorer, or protected policy is modified or replaced.

## Concrete blocker

`GroupDecisionTraceV1` includes `terminal_outcome_digest` in the same struct
as predecision inputs. That field is appropriate for *post-hoc trace replay*;
it is **not** a proof that an online decision or learned Critic was conditioned
only on pre-boundary evidence. In particular, a digest is not a substitute for
a causal event-time boundary. This research candidate provides a separately
versioned contract without weakening or reinterpreting V1.

## Admission and chronology

Three strictly typed, canonical SHA256-bound stages:

1. **PREDECISION:** immutable public input/Encoder generation, source frontier,
   subject run, declared legal candidate/action roster, cost ceiling, depth,
   required outputs, reserved emission budget and distinct actor/evaluator
   identities. Unknown fields
   (including terminal truth and later result fields) fail closed.
2. **EXECUTED:** must bind the exact earlier predecision digest; records every
   selected action, candidate, step index, evidence observation hash, success or
   failure and **charged cost**. STOP/ABSTAIN are terminal. Mandatory output
   emission costs are positive, charged separately and cannot borrow the
   preregistered reserved output budget. All steps including failures count
   against one bounded episode cost; missing outputs remain
   incomplete, not silently dropped or given free quality.
3. **POSTSCORE:** an actor-distinct *declared* evaluator adds terminal result,
   external evidence hash, independent outcome hash and quality only after
   execution is sealed. The report must reproduce actual charged work, and any
   incomplete/failure/abstain outcome has quality zero and severe error.

Each stage uses a different digest domain to prevent substituting one kind
of record for another. Unknown keys, duplicate JSON keys, invalid IDs,
non-finite/boolean scores, changed Encoder generations and mismatched evidence
are rejected. The resulting policy posture is always `DENY_ALL`; there is no
implicit automatic approval after tests pass.

### Reproduce

```bash
python3 -m unittest discover -s qualification/group-system2-causality -p 'test_*.py' -v
python3 -O -m unittest discover -s qualification/group-system2-causality -p 'test_*.py' -v
python3 -m compileall -q qualification/group-system2-causality
```

Local source-identical runs on Python 3.13 passed **23/23** ordinary and
**23/23** optimized assertions. Check GitHub Actions on this exact child head;
no queued, cancelled, inherited or earlier-run status is claimed to pass.

### What this does *not* close

- Identity strings and hashes are **not signatures**. The declared evaluator
  is *not independently authenticated*; a single party may have forged both
  actor and evaluator receipts. External signed owner and observer evidence,
  actual monotonic event timestamps and immutable source snapshots remain open.
- "physical_cost_claim" sums claimed step plus decoder-emission costs, **not a hardware
  attestation**. True host/GPU/queue/energy accounting requires separate
  instrumented and trusted observers.
- This code does **not** demonstrate multi-hop reasoning, a trained System 2,
  task novelty, a real model forward, output portfolio advantage, learned
  nonzero-covariance NDU, or any production policy permission.
- A causal receipt alone cannot prove nonanticipativity of hidden model
  features or internal memory. A trained policy must be separately tested with
  hidden labels withheld, model feature instrumentation and independent data.
- It does not supply statistical paired best-of-N controls, three training
  seeds, 8–16 *real* NDU decisions or new heldout natural media. It therefore
  cannot close P3/P4 scientific gates, nor does it supersede the negative NDU
  v1 result.

See `P0_P7_LEDGER.md` for a dependency-ordered acceptance and blocker handoff.
