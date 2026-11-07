# Independent v2 confirmation review — complete

Date: 2026-11-06. Scope: local engineering acceptance of the declared
`ndu_llm_confirmation` Python/schema snapshot. This is a same-session review by a
separate agent, not an external scientific review. No external API or real LLM
was called. No target source, original qualification, frozen experiment, or
THEORY.md was modified by this reviewer.

## Outcome

The independently constructed positive-control bundle passes. On the final
snapshot, **121/121 gate checks and 23/23 local runtime checks pass**. The test
drivers construct their own data and local policy modules; they do not import
the implementation's synthetic test fixture or statistical calculations.

Both final receipts show identical target-source fingerprints before and after
execution. The snapshot agrees with the implementation owner's final 39-test
qualification. That separate 39-test result is not added to the 144 independent
check count here.

## What was actually checked

### Strict input and statistical gate

- Missing, duplicate and malformed episode/attempt/invoice records produce
  HOLD. Boolean quality, verification quality, repeat, contract numbers and
  monetary fields cannot pass as their integer/float counterparts. Nonfinite
  values and malformed usage records are rejected.
- Successful model identity cannot be filled from expected fields or a final
  invoice. Failed/no-response model attempts have positive controls for valid
  structured identity receipts, and negative controls for missing or incorrectly
  bound request, invoice or revision material.
- Unfinished intents, terminals without intents, duplicated phases, wrong intent
  digests, binding mismatches and invalid execution ordering produce HOLD.
  A valid intent/terminal pair is billed once.
- Dispatch must occur after durable intent admission, no later than recorded
  completion, and strictly before the request deadline. An OK completion cannot
  occur after its request deadline; that deadline cannot exceed the declared
  request timeout or episode deadline.
- Raw completed-attempt ordering must agree with episode request ordering.
  Delivered output requires the final successful model before the verifier,
  followed by the host meter. Reversed dependency and meter-first fixtures HOLD.
- Repeats and multiple task members within a source cluster do not inflate n or
  reduce the primary Hoeffding radius. Source splitting and duplicate content
  are rejected. M covers all registered comparisons and required mechanism
  contrasts; underdeclared multiplicity is rejected.
- Independent arithmetic reproduces the paired and absolute Hoeffding radii.
  Baseline future-cost upper bounds cannot improve the lower certificate;
  candidate upper costs are subtracted. Missing lifecycle receipts, cost
  duplication and invalid bounds HOLD.

### Local runtime and callback binding

- A fake worker observes its pending intent already present before execution.
  Intent plus terminal reconcile to exactly one known synthetic charge.
- Missing ledger directories or failed intent fsync prevent worker launch.
  Terminal-append failure after the worker runs retains the recoverable pending
  intent and is rejected as incomplete.
- Slow intent writes exhaust the original request, absolute or episode deadline
  without starting the fake worker. The clock is not restarted after admission.
- A real local subprocess timeout retains unknown usage and cost; a missing bill
  remains unresolved. A failed spawn has a consistent undispatched state.
- A valid audited callback has an end-to-end delivered positive control.
  Missing binding, another function in the same file, changed source, changed
  runtime code or changed immutable global value are rejected.
- Closures, lambdas, mutable globals, hidden defaults, imported dependencies and
  internal imports are rejected by the documented restricted callback interface.
  Registered baselines cannot be replaced by callbacks.
- Two model calls made through the supplied hook are independently recorded and
  billed as two attempts; the final verifier and host meter remain in sequence.

## Retained failed review and correction

`review_gate_v2_initial.json` is preserved unchanged: its independent positive
control passed, and 113 of 114 checks passed. The failed case moved dispatch
later than its own recorded completion while leaving it before the deadline;
the older gate incorrectly returned PASS. The implementation owner repaired the
missing temporal relation. Adjacent deadline and final-verification ordering
conditions were also tightened; the final review explicitly tests them.

The final receipts are new files, not rewritten versions of the failed review.
The original implementation qualification remains unchanged at SHA-256
`d9af64b97a57b483a76ebc37f15148eea9465186321400d1049be6df18d2a661`.

## Limits

The positive gate bundle and runtime providers are deliberately synthetic.
These checks establish consistency of the declared accounting and qualification
rules, not truth of provider claims, actual payment, immutable model weights,
semantic source independence, a general Python sandbox, or economic/scientific
benefit. The callback binder is the documented restricted trusted-code contract.
Unknown real bills, external identity evidence and genuine independent
confirmation remain separate requirements. No benchmark parameter, gate, theory
bound or negative scientific result was changed to obtain these checks.

## Reproduction

Run from the workspace root with new output filenames:

```bash
PYTHONDONTWRITEBYTECODE=1 python theory_work/llm_confirmation_review/review_gate.py --execute-after-stable-notice --output theory_work/llm_confirmation_review/review_gate_rerun.json
PYTHONDONTWRITEBYTECODE=1 python theory_work/llm_confirmation_review/review_runtime.py --execute-after-stable-notice --output theory_work/llm_confirmation_review/review_runtime_rerun.json
```

The runtime driver changes only its own process working directory so local
worker modules resolve. It does not alter network settings or target sources.
Both drivers reject existing output paths and invalidate their result if any
watched source/schema/original-receipt hash changes during execution. Script and
receipt hashes are listed in `manifest.json`.
