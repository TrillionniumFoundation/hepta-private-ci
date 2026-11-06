# Independent confirmation acceptance review

Status: prepared 2026-11-06; **awaiting the parent's stable-source notice**.
This is an independent, local-only engineering review. It does not authenticate a
provider, invoice, model revision, or source-independence assertion. It does not
run a real LLM or authorize an external request. No implementation, original
qualification receipt, frozen experiment, or THEORY.md is to be modified.

## Scope and execution contract

- `review_gate.py` builds its own explicitly synthetic positive-control bundle;
  it does not import the target's test fixture or use its statistical functions
  to calculate expected radii.
- It imports the target only with `sys.dont_write_bytecode=True`. Test changes
  are in-memory copies; any transport/runtime fixtures belong in temporary
  directories. Outputs must be new scratch files, never overwritten receipts.
- A positive control must first pass. If a new ledger format makes that control
  incompatible, stop with `FIXTURE_ADAPTATION_REQUIRED`; do not count a run in
  which every malformed input merely inherits an unrelated HOLD.
- Before and after a run, hash implementation, schema, tests, and the original
  qualification receipt. Any change during the run invalidates the review.
- Do not execute until the parent declares the implementation stable. Adapting
  an interface to the declared durable ledger format must not weaken any of
  the expectations below. Keep every failed check in the review receipt.

## A. Strict schema and semantic input checks

The runtime gate must enforce its required fields and strict numeric types even
when JSON Schema tooling is not installed. In Python, `bool` is an `int` subclass
and `False == 0`, `True == 1.0`; equality alone is not a type check.

1. `verified_quality` must be a finite nonboolean number in `[0,1]` before it is
   compared with episode quality. Both `True` and `False` must be rejected.
2. Event and episode `repeat` must be nonboolean integer indices in range.
3. The episode's `contract` values must be finite nonboolean numbers before
   comparing them with the protocol. In particular, `currency_to_score=True`
   cannot replace `1.0`, and `time_price=False` cannot replace `0.0`.
4. `stop_requested` must exist and be a boolean for **all** terminal outcomes,
   including cancellation, failure and timeout; failure branches must not skip
   structural validation. Delivered records additionally require it to be true.
5. Usage records and invoice usage must be independently validated when
   present. A malformed non-null object is not known usage. Boolean token
   counts, negative counts, cached counts exceeding input counts, malformed
   dictionaries and scalar booleans must be rejected.
6. Invoice and lifecycle `amount`, interval bounds, weights, time fields, cap,
   precision, prices and deployment volume must be finite nonboolean numbers.
   Counts need their corresponding integer constraints. Reconcile monetary
   conversion and lifecycle interval arithmetic only after those checks.
7. IDs, line IDs, families, clusters and source-group members must be nonempty
   strings. `source_groups`, `request_ids`, comparisons and mechanism claims
   must be arrays of the declared element type; strings are not arrays here.
   Source groups must not contain empty identifiers. Invoice `line_id=True`
   must not pass just because it is truthy.
8. Delete each required episode/event/invoice/lifecycle field in isolation and
   require HOLD. Check delivered and failed branches separately. Unknown event
   kinds and impossible kind/status combinations require HOLD.
9. Reject duplicate episodes, duplicate request IDs/phases, reused invoice
   lines, reused requests, missing pairs, missing attempts and unassigned
   attempts. Do not silently deduplicate retries or drop malformed ledger tails.
10. NaN and infinity must not survive JSON parsing, artifacts, numeric inputs,
    returned verdicts or cost arithmetic. A malformed bundle must not produce
    a new PASS or accidentally reuse a previous PASS output file.

### Additional gaps to inspect in the existing manual validator

Beyond the previously reproduced `verified_quality` and event-repeat issues,
inspect numeric `record.contract` equality, source-group element types, invoice
`line_id` type, empty/malformed mechanism-claim arrays, and success-only branches
that leave required failure fields unchecked. These are inspection targets,
not claims that the repaired implementation still contains each defect.

## B. Observed model identity and final billing

1. A successful model response requires its own valid observed identity and
   exact match to the frozen identity. Removing `identity_status` or
   `observed_identity_sha256` cannot be repaired by copying an expected digest
   into an invoice. A success with a mismatching observed identity stays HOLD.
2. An explicitly failed/no-response attempt may use a final authoritative bill
   to resolve identity and usage, if the declared contract permits it. Preserve
   the failure, zero terminal quality and billed spending.
3. A matching request echo or arbitrary hash material is not authentication of
   immutable weights. Keep this external-assumption boundary explicit in the
   result and documentation.
4. Missing/pending/estimated invoices, unknown price or invalid currency stay
   HOLD. `reported_amount`, a rate-card estimate or missing data never become
   an actual zero charge. Authoritative zero-charge attempts still need a final
   line with the requisite identity/usage evidence.
5. A receipt hash must have reconstructible matching material. Material
   availability alone does not prove that an unsigned provider claim is true.

## C. Durable request intent and terminal records

These cases are to be adapted to the **declared** stable ledger format, not to a
heuristic inferred from whatever fields happen to make the gate pass.

1. Persist and fsync a pending intent containing the unique client request ID
   and frozen context **before** dispatch. If opening/writing/fsyncing the intent
   fails, a marker-producing local fake worker must not execute.
2. Exactly one valid intent and one terminal record form one attempt. They must
   bind the same request ID, task/arm/repeat/protocol, request payload digest,
   transport and expected identity. Mismatch or reversed/invalid sequencing
   requires HOLD.
3. An intent without a terminal record requires HOLD even if a zero-charge
   invoice exists. An invoice alone cannot assert that the attempt completed.
4. A terminal record without its required intent requires HOLD under the new
   production format. If legacy records remain readable, label their weaker
   guarantee and do not silently qualify them as durably instrumented runs.
5. Two intents or two terminals for one request require HOLD, including equal
   duplicates. A retry needs a new attempt ID and its own bill.
6. If terminal append fails **after** the worker runs, the intent must remain
   recoverable and gate evaluation must HOLD. The receipt remains unknown; no
   automatic zeroing or deletion of the orphan is allowed.
7. A valid intent/terminal pair and one final invoice must yield **one** charge,
   not two. Supplying duplicate invoice lines or billing phases separately must
   be rejected, not counted as two valid attempts.
8. A timeout must produce one pending/terminal pair, retain unknown usage and
   charge until reconciliation, and never receive delivered quality. Killing
   a local worker does not establish remote cancellation or a zero remote bill.
9. An orphan intent not listed by an episode must still be detected as an
   unassigned attempt. Full-ledger completeness is part of qualification.

## D. Actual full-candidate binding

1. The full arm must require a declared candidate binding before dispatch. A
   missing binding cannot fall back to hashing only the adapter and settings.
2. Freeze and verify the actual callable's source artifact and entry point.
   Replacing it with a different function must fail before any request starts.
3. Two different functions in the same source file must not share an accepted
   entry-point binding merely because the file digest is the same.
4. Changing the file after freezing must be rejected. Unsupported lambdas,
   closures, partials, mutable callable state, or other implementations need an
   explicit supported binding contract, otherwise reject them.
5. All nested model calls must use the metered hook and appear in the ledger.
   Hidden external calls remain an externally audited method violation; a
   Python source hash is not a proof that arbitrary code cannot make one.
6. Binding a callable is not proof of a generally frozen runtime: loaded data,
   configuration, weights and mutable external state require their declared
   provenance. Do not overstate this finite implementation safeguard.

## E. Statistical and full-cost regression invariants

1. There is one primary confidence family covering every reported registered
   contrast, including each family's absolute net utility and each requested
   mechanism contrast. Underdeclaring `M`, omitting a required contrast, or
   selecting only successful families requires HOLD.
2. Source-sharing tasks belong to one registered cluster. Repetitions average
   within task and tasks within cluster before computing `n`. Doubling repeats
   or tasks in an existing cluster must not increase `n` or reduce its primary
   Hoeffding radius. Different printed IDs are not substantive independence.
3. For service utilities in `[-Cmax,1]`, paired radius is
   `(1+Cmax)*sqrt(2*log(M/.05)/n)` and absolute radius is half as large.
   Check these with independent arithmetic, not a call to the implementation.
4. Candidate lifecycle upper cost is subtracted; baseline lifecycle **lower**
   cost is subtracted from that penalty. Increasing an uncertain baseline's
   upper bound with its lower bound held zero cannot improve the contrast.
5. Shared actual setup allocations sum to one, cover all declared categories
   for every arm, and never reuse service invoice lines. Missing or pending
   lifecycle invoices require HOLD. Future intervals need frozen evidence and
   ordered nonnegative endpoints; they are not actual bills.
6. Subtract all declared full-cost terms before PASS. Keep failures in the
   paired analysis, preserve original qualifications, and leave scientific
   status HOLD without genuine model/billing/independent-source evidence.

## Planned artifacts

- `review_gate.py`: independent in-memory bundle mutation suite and statistical
  calculations, with explicit positive-control and stable-source checks.
- A later stable-interface transport/callback supplement will exercise sections
  C and D only with temporary local fake workers; the gate script must not be
  mistaken for having already exercised those integration cases.
- `review_*.json`: new immutable run receipts, created only after the parent
  declares the target stable. No acceptance result exists at preparation time.
