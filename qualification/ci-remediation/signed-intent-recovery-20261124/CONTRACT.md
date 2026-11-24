# Signed recovery fixture compilation

## Observed failure

The public source-head job for commit
`304aad85f2803c49daafa84dad1f3f6d18b701dd` failed at 2026-11-24
14:41:58 UTC while compiling `codex-hepta-supervisor` integration tests:

- Run: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45415344452>
- Raw job: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45415344452/job/138519928523>
- `signed_intent_recovery.rs:313,314`: `Sha256Digest::parse` returns a string
  error, which `?` cannot convert directly into `anyhow::Error` (E0277).
- `signed_intent_recovery.rs:373`: the integration test called the crate-private
  `SignedSupervisorIntent::with_status` method (E0624).

The three compile errors remain present at the next integration baseline
`676d59ef602e59790a58614541bfb92325bdc71f`.

## Correction and preserved checks

Only the integration fixture changes. String errors are explicitly mapped with
`anyhow::Error::msg`. The expected terminal intent is built with the existing
public constructor, copying all original digest-bound fields and selecting
`RolledBack`. The assertion still compares the complete actual and expected
intent, including the recomputed digest.

The production API, private status transition, signature validation, incorrect
signer rejection, incorrect authority epoch rejection, exact transaction binding,
release selection, and repeated-resolution rejection remain unchanged. All
signing keys in this test are existing public synthetic fixtures.

## Qualification boundary

Local `just fmt` and `git diff --check` passed. A fresh local compilation was not
attempted because the shared target lacks this crate and its fleet, control-plane,
and memory dependencies, while available storage is bounded. Formatting is not a
compile or execution receipt.

The existing normal GNU job in `.github/workflows/hepta-ci-fixtures.yml` already
executes `just test -p codex-hepta-supervisor --test restart_budget
--test restart_budget_recovery --test signed_intent_recovery --locked`.
The normal architecture source-head job also compiles the integration test.
The corrected candidate requires new-head CI receipts before qualification.
