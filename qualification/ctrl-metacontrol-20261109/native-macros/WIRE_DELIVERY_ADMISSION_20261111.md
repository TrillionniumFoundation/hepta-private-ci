# CTRL native macro wire/delivery admission — bounded adversarial repair

**2026-11-11. Draft / HOLD_NO_GO / NoUpdate.** This is a research-only
self-consistency boundary fix. It does not authenticate a native owner,
qualify a policy or demonstrate a beneficial READ/PLAN action.

## Source identity and old false positives

Exact parent: [CTRL #5772](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5772),
HEAD `602cd5695092a82f876fd122243b971b5b88eee8`. On HeptaRuntime
operator `ai395`, the parent was fetched as an isolated sparse working copy
and its Git HEAD compared to that exact SHA. Existing narrow original macro
contract baseline: 1/1 passed, no skips.

An adversarial manufactured suite created matching JSON event digests and
matching trajectory copies while varying one fact at a time. The **original**
`observe_branch` incorrectly accepted 7/7 of these:
1. Ready emitted after the first actor observation.
2. An additional unrecognized actor event injected into the stream.
3. Ready declared an unrelated case ID.
4. Non-null actor `callback_error` with exit_code=0.
5. Non-null actor `protocol_error` with exit_code=0.
6. Non-null actor `limit_reason` with exit_code=0.
7. The WRITE_TEXT action contained a different text from the final delivered
   payload, although score and delivery digests were consistent.

Actual RED run: `ai395` job `1a1caaaa3c9-2564-7ca`, seven
expected `ValueError not raised` failures. These counterexamples are
**manufactured acceptance tests**, not observed exploits or original-task data.

## Repair

- Admit only one initial actor-ready event, then the exact ordered observations,
  without ignoring extra/unsupported events; ready case and weight must match.
- Require a truly completed isolated launch with no callback, protocol or limit
  errors, not merely exit_code=0.
- Bind the unique finalizing WRITE_TEXT action argument to the final delivery's
  case and text before permitting the independently scored macro return.
- Bring the synthetic host fixture's action schema and ready case ID into line
  with the real actor's declared wire fields.

No policy, model weights, independent scorer, hidden reference, actual historical
trajectory or production branch was modified.

## Scoped verification and source digests

GREEN run `ai395` job `1a1caac8e8e-2564-7db`: 3/3 focused test
methods passed (2 positive macro subcases, all 7 rejection subcases), zero skips.
Post-rename GREEN `1a1caaec42f-2564-7ed`: 3/3 passed again and all three
changed Python files passed compileall + AST parsing, git diff --check clean.
Existing native-pair fixture suite `1a1caaf710c-2564-7f1`: 6/6 passed,
including frozen suffix, baseline state consistency and failure retention.

Final Python source SHA256:
- `metacontrol_macro_contract.py`: `9d2227af8dba2dbc3779c0225b7c6c551b68d2e83c3313bbda004c9c88fe07e2`
- `test_macro_pair_fixtures.py`: `2cf3726f7cdd4613b06915267842bd2257dbe84a622233cd981a2049c7dbde42`
- `test_macro_wire_delivery_admission.py`: `19449c7eafdc982b0e27a7fb1f451e58e045444dc3774e667386ee2d9c2dbbc1`

## Remaining gates

These receipts remain self-declared. Native owner authenticity, exact scored
original case selection, independent prospective evaluation, complete physical
costs, calibrated implementation probability, source-disjoint STOP-versus-READ
macro comparisons, later successful production FinalUse, and exact-head CI
are **not** established by these local tests. No future source was opened.
Hold and do not auto-merge until those gates have independent evidence.
