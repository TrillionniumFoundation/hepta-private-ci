# `learning.eval` active-trust and lifecycle-capacity contract addendum

This addendum is normative for the source candidate that includes it. It narrows
and completes the selected-host recovery and capacity rules in
[`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md) and
[`RECOVERY_CONTRACT.md`](RECOVERY_CONTRACT.md); it does not weaken any existing
holdout, archive, publication, authority or external-evidence requirement.

## Per-attempt current trust at recovery use

A persistent recovery page must not receive one bare
`LearningEvidenceVerifierV1` and treat it as current for every item in the page.
Before each attempt, the host owner supplies a freshly resolved
`ActivatedLearningTrustV1` together with the host time used for that attempt.
That activation must already have passed the root-signature, distribution,
scope, generation and authority-epoch checks owned by `learning.ledger`.

Within one page, `learning.eval` enforces all of the following:

- host time is monotonic;
- the activated distribution is effective at the sampled time;
- root identity remains exact;
- distribution generation, effective time and authority epoch do not regress;
- one generation cannot silently change distribution digest;
- the archive is re-decoded and V2/V3 evidence is reverified with that attempt's
  active verifier before any first publication write.

An independently authorized root-rotation ceremony starts a new recovery page;
it is never inferred inside an in-flight page. A trust-provider, cursor or
journal error aborts the page. Already persisted cursor progress for earlier
handled identities remains durable, while the rejected identity is not advanced.

`ActivatedLearningTrustV1` authenticates the repository trust distribution. It
does not authenticate the deployment host, independent anchor service, outcome
provider or publication service. Those remain selected-topology evidence gates.

## Full-lifecycle capacity and qualification limits

The file attempt owner reserves all remaining lifecycle frames when
`IntentPersisted` is admitted, before any irreversible final-holdout use. A new
attempt is rejected when its own full lifecycle cannot fit. Rejection does not
consume an existing reservation, so an already admitted attempt can still reach
`Published`, `Failed` or `RejectedBeforeHoldout`.

The backend hard ceilings remain 64 MiB and 1,000,000 events. The hidden
`create_with_qualification_limits` and
`recover_with_qualification_limits` constructors may only tighten those ceilings.
They exist solely to exercise the real file owner at an exact near-capacity
boundary without creating a 64 MiB test artifact. They are not a deployment
configuration, do not relax a hard bound, do not replace the independently
anchored production wrapper and confer no authority.

The near-capacity regression fixes a seven-event namespace whose byte and event
limits equal exactly one successful lifecycle. It proves that a second intent is
rejected, the first attempt consumes every reserved phase through `Published`,
the full journal reopens at the exact boundary, and no additional intent is then
accepted.

## Evidence and claim boundary

External gates remain false unless their separately governed evidence and
authority are supplied. The fresh-trust process regression, near-capacity file
regression, two-process cold recovery, unresolved-page cursor test,
checkpoint-tail soak and exact-tree qualification are repository source evidence
only. The following remain false until independently supplied and verified:

- `targetHostQualified`;
- `independentAcceptance`;
- `productionImplementation` or production qualification;
- activation, promotion and release.

The selected topology must still provide authenticated host identity, an
independently administered rollback anchor, a real provider and publication
store, qualified lock/CAS/fsync behavior, real future-calendar outcomes,
retention/privacy/unlearning evidence and the applicable independent approvals.
