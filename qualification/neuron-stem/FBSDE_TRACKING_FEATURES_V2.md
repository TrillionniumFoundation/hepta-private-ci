# Local-participant feature reuse without collapsing sequence state

Parent: `9dfed4086b47c58597fb7ab15dfc79ba634429cf`, Draft PR #1550. Same
study entrypoint, exact controls, gate fitting, original source checker and
100,000,000 ns process-CPU proposal limit. No native owner or model activation.

## Newly observed physical failure, not assumed thread noise

Original artifact 11727426739 (run 38204808220), SHA256
7d3e98568aaec26a877e65de28eaa06d95f10a9a31518523523ab882d4891a37,
failed on its FIRST mmBERT proposal at 189,337,443 CPU ns. It performed three
consecutive cache-miss Encoder calls taking 65,162,728, 60,598,805 and 63,335,801
CPU ns. Their sum is 189,097,334 ns. The prior simulator fitting cached the
`Then` form, but the first benchmark instruction used `First`. This instance is
serial work accumulation, not evidence of a single 189 ms Encoder tail.

The paired original lexical artifact 11727078816 (SHA256
5b71a867e7884a63bf2e5d0550124dcf413eadbbe53eb51136f883042f933c91)
completed all 750 original tracking examples. Independent rechecking reproduces
750 correct for learned/verified/exact methods, 205 frozen, 136 initial and 84
last-step-only. Exact reverse is still cheaper; this is a task-specific parser
plus classifier result, not general BBH or System2 superiority.

## Explicit profile, same global story

`ordinal_sensitive_v1` stays the default and remains in the physical CI matrix.
The added `local_participant_v2` normalizes ONLY a validated ordinal prefix to
`Then` in the already entity-normalized PARTICIPANT input. The raw story, exact
instruction text, event index and immutable predecessor/successor remain intact.
It does not reorder events or identify whole trajectories having equal features.
Unknown verbs, negation, conditions and extra text reject rather than being erased.
The invariant is specific to the declared unconditional swap grammar.

All 3,750 original benchmark instructions generate only 15 distinct V2 keys,
all already present in the separately generated simulator training rows. No
benchmark target or text is used to fit/prewarm the model. These are task-specific
input equivalences, not additional learned language capabilities. Historical
predictions, canary meaning and source denominators are unchanged.

A study-instance feature cache is bound to the frozen Encoder identity, scope,
generation and frontend profile; it has a 512-entry limit. For a current proposal
of at most seven candidates, distinct missing keys are batch encoded ON DEMAND.
No future event is prefetched. Validated copied vectors enter the cache only after
a whole batch succeeds. Repeated slots reference the actual forward batch/slot;
returned tensors cannot mutate cached vectors. Startup/fitting encodes still occur
before evaluation, with their actual costs recorded. No claim of batched/single
floating-point equality on arbitrary pretrained inputs is made.

One copy of the learned Head remains shared; state belongs to each request.
Riccati/FBSDE residuals are not substituted for original instruction checks.
There is no newly learned computation controller in this performance correction.

## Evidence and failure semantics

`encoding-batches.json`, `feature-plan.json` and proposal rows bind original and
canonical texts, source ID, arm, event index, misses, batch slots and the frozen
pipeline. Independent audits import neither Torch nor the forward executor.
They reject hidden/future encodes, changed source events, duplicate proposals,
state updates from denied observations and budget contradictions. Byte consistency
is not an authenticated hardware execution or a production permission.

Local source checks passed (357 tests). The actual tensor invocation passed ten
executed test methods but the additional source-audit integration class setup
hit the unchanged 100 ms limit, blocking its three methods. It is NOT all-green.
A generated 192-story V2 run completed with zero evaluation encodes. A full BBH
V2 attempt stopped on a warm-cache proposal (353,877,418 ns). A declared one-pass
fresh-process pair also rejected warm proposals (legacy 278,073,001 ns;
V2 411,038,130 ns). All failure logs/partial records are retained; no successful
subset is presented as a complete new 750-case result. Observer-only GC diagnosis
also failed and did not establish which maintenance event caused the denial.

Thus this change eliminates the specifically identified ordinal-driven repeated
encodings for the registered grammar, but does not establish overall budget
stability. No higher budget, retry-to-green, GC disabling or timing-clock change
was introduced. New source/merge and original-BBH physical lanes must qualify
the final SHA separately. Full-repository/Rust/native validation remains open.

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile verified_tracking_v1 --tracking-source bbh --backend mmbert \
  --tracking-feature-profile local_participant_v2 \
  --model-dir /fixed-model --publisher-root /fixed-bbh --output /new/evidence
```
