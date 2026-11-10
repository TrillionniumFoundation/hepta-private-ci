# Frozen prospective shadow and terminal-label journal

`prospective.ShadowJournal` closes the caller-supplied roster gap in
`evaluate_shadow`. Create one new SQLite file before collecting forecasts,
with a nonempty `FrozenAttempt` roster, one `Target`, ordered planned frontiers,
and frozen risk/checker/scheduler/evaluator identities. The journal freezes
identities; it does not execute the scheduler or fit models.

The host uses this order for each attempt:

1. `record(Prediction(...))` at each available frozen frontier.
2. `finish(trajectory_id, disposition)` with the original host disposition.
3. `label(TerminalLabel(...), evaluator_id=..., authenticate=..., attestation=...)` through
   a separate authenticated evaluator. The callback receives issuer ID, exact
   label, pinned evaluator version, manifest SHA256 and the opaque attestation;
   only literal `True` admits the supplied label. The exact attestation is retained
   in the same event as the label. Install a real evidence verifier in the host.
4. `report(authenticate=current_host_verifier)` after every planned attempt has
   both completion and label records. This revalidates all retained attestations,
   including explicit missing-label reports, under current trust and revocation.

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
prevent database-owner rewrites or prove evaluator independence. Opaque label
attestations are bounded to 16 KiB and bind issuer, version, label and manifest.
The host callback must validate original evidence, current trust/revocation and
freshness. The code supplies no accepting default and creates no trust keys.

Legacy `label(..., authenticate=...)` calls without an attestation remain readable
through descriptive `report()`, but strict authenticated reports refuse them.
They cannot be upgraded by an accepting callback without the original evidence.
`label_authentication` distinguishes retained, legacy and currently reverified
records. Changing a label during authentication, or changing the ledger while
authenticating a report, refuses publication. Authentication alone does not prove
independent custody or semantic correctness.

Reports retain Brier/log loss, both error denominators, acceptance coverage,
per-disposition label acquisition and each planned frontier's missing forecasts.
Missing-label bounds describe this finite dataset, not future confidence bounds.
Zero acceptance retains an undefined conditional error rate.

The current engineering qualification and remaining field requirements are in
[VERIFY4.md](VERIFY4.md). Treatment records are integrated in [TREATMENT.md](TREATMENT.md).
Complete physical cost and an independently authenticated prospective comparison
remain external requirements. Scientific admission stays HOLD and authority NONE.
