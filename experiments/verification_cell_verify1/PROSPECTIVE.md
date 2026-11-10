# Frozen prospective shadow and terminal-label journal

`prospective.ShadowJournal` closes the caller-supplied roster gap in
`evaluate_shadow`. Create one new SQLite file before collecting forecasts,
with a nonempty `FrozenAttempt` roster, one `Target`, ordered planned frontiers,
and frozen risk/checker/scheduler/evaluator identities. The journal freezes
identities; it does not execute the scheduler or fit models.

The host uses this order for each attempt:

1. `record(Prediction(...))` at each available frozen frontier.
2. `finish(trajectory_id, disposition)` with the original host disposition.
3. `label(TerminalLabel(...), evaluator_id=..., authenticate=...)` through
   a separate authenticated evaluator. The callback receives issuer ID, exact
   label, pinned evaluator version and manifest SHA256; only literal `True`
   admits the supplied label. Install a real evidence verifier in the host.
4. `report()` after every planned attempt has both completion and label records.

Keep explicit missing truth with its reason. Finishing without a forecast is
valid; omitting an attempt from reporting is refused. UNKNOWN dispositions can
have known terminal truth. Accepted outcomes can remain unlabeled. A reached
state before the fixed horizon cannot become the uninterrupted terminal label.
Repair changes the candidate/target and must not relabel an earlier forecast.

Writes serialize through SQLite transactions. Duplicate, reversed, unplanned
and post-completion forecasts refuse, as do duplicate completion/label writes,
changed subjects/targets/models and cross-disposition labels. Exact duplicates
also refuse; this API does not replay an uncertain write. Reopen the original
journal and reconcile its retained events before deciding what remains owed.

Retain `manifest_sha256` outside the database. On recovery use
`ShadowJournal(path, expected_manifest_sha256=retained_digest)`. The live object
pins the same digest. Retain report `ledger_sha256` externally as an audit root.
The chain checks internal consistency; it does not authenticate wall time,
prevent database-owner rewrites or prove evaluator independence. Authentication
callback signatures/attestations are not retained or reverified on reopening.

Reports retain Brier/log loss, both error denominators, acceptance coverage,
per-disposition label acquisition and each planned frontier's missing forecasts.
Missing-label bounds describe this finite dataset, not future confidence bounds.
Zero acceptance retains an undefined conditional error rate.

Validation: 58 scoped Linux tests passed, including 10 new journal tests.
Pinned Ruff 0.15.13 format and F/E9 checks passed; formatted Python ASTs match
the tested beforeimages. Full workspace formatting/native/CI checks were not
completed in the sparse local environment; see the qualification RESULT.

This increment adds no real-task trials. Checker dispatch, scheduler treatment
records, complete physical cost and a frozen independent prospective comparison
remain outstanding. Scientific admission stays HOLD and authority stays NONE.
