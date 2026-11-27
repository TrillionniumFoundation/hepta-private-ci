# H3: historical cost float-binding startup failure, no measurements

**Actual terminal: worker exit 1, overall exit 1; all 36 calls unexecuted.**
The unique invocation ran at 2026-10-23T16:22:58.602581+00:00 to 2026-10-23T16:22:59.389263+00:00, frozen source `9ca2a3e7e7f318793608a311fee644e1f4fe84e8`, execution
commit `c35fc6b5a57909b2ccb2aa707d0100d054320035`, freeze SHA256 `829c2b8ae3bdc56e168a5185e41a8e837b042b518cb51df44e88a65387ea5928`.

The exact error was `ValueError: historical complete build cost changed` in
`safe_restore`. The immutable archive was correct. The guard directly compared
binary floating seconds with protocol values rounded to nanosecond decimal
precision:

| Arm | Actual original float seconds | Frozen decimal seconds | Difference seconds | Both canonical nanoseconds |
| --- | ---: | ---: | ---: | ---: |
| NC | 8.537556029000005 | 8.537556029 | 5.329070518200751e-15 | 8537556029 |
| N | 8.307966292000007 | 8.307966292 | 7.105427357601002e-15 | 8307966292 |

This is a technical representation/identity-check defect, not changed historical
cost, an actual cap breach, model failure or evidence against dynamic generation.
The guard was added during H2 preflight; opaque integer-cost tests failed to
exercise the real fractional receipt. That missed case is now directly covered.

Only dependency import and archive verification/byte restoration ran. Ten
original binary artifacts were restored to `reused-t11/`, with their source
hashes verified. No NPZ tensor/model object was loaded, no TRAIN constructor
ran, no content probe/value was computed, and zero service calls were attempted.
The known mathematical-work ledger is 0, the input-identity collection empty,
and both attempted/completed-call lists empty. There is no valid H3 headroom or
utility result. Its START/PARTIAL are consumed and cannot be resumed/aliased.

Full H3 worker/descendant CPU was 0.784206000 s, launcher-own CPU before its
receipt 0.022962997 s: **0.807168997 s** combined, wall 0.786689283 s. The H2
startup failure's **0.519258463 s** remains separately visible; cumulative
H2+H3 startup research cost is **1.326427460 s** before the outer receipts'
final serialization. No cost is refunded or converted into useful training.
The original `diagnostic.json`, `manifest.json`, START, PARTIAL, console and
outer execution receipt preserve this failure unchanged.

## Source correction and permitted evidence

The subsequent minimal correction compares `round(seconds * 1e9)` on both sides
of historical cost identity. The original timers account in nanoseconds; this
preserves that precision instead of demanding equal binary float encodings. It
does not change the 30s/4B/32MiB research bounds, qualification budgets, reward,
price, old reference, historical build charges, sample, policy or scientific
gates. Original actual floating values remain in the T11 binding receipt.

Five handmade regression checks passed, including equivalent fractional floats
at one canonical nanosecond value and rejection of a real 0.1-second mismatch.
A separate **metadata-only** check then ran the corrected `safe_restore` against
the real original archive, with imports of numpy/model/independent modules
forbidden. All ten exact binary artifacts and the identity/cost receipt passed;
no dataset, model object, numerical forward or service ran. Its temporary copied
bytes were discarded after their hash-bound binding was recorded. See
`../codex-cloud-dynamic-h3-source-preflight/canonical-cost-real-archive-smoke.json`
and its console. This is not an H3 continuation or repeated measurement.

No new recovery collection has been run. Any further prospective TRAIN repair
must explicitly retain H2/H3 failure/cost history and the one-line cost-binding
correction, and obtain authority to register a distinct once-only identity.
Do not reset either existing START or privately relaunch 36 calls.

H1 still lacks direct NC/full costs and selected-static-NDU TRAIN values. Hence
current-weight dynamic feasibility/impossibility remains unresolved. D1's real
CPU breach and unrun cache slots remain; core c1 remains a sealed formal failure;
r2 test remains unopened. No new formal evaluation, AV generation, deployment,
merge or permission change occurred.
