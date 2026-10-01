# `learning.eval` active-trust and lifecycle-capacity contract addendum

This addendum is normative for the source candidate that includes it. It narrows
and completes the selected-host recovery and capacity rules in
[`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md) and
[`RECOVERY_CONTRACT.md`](RECOVERY_CONTRACT.md); it does not weaken any existing
holdout, archive, publication, authority or external-evidence requirement.

## Selected-host final-use activation

Every public selected-host qualification and selected-host archive-recovery
entrypoint accepts `ActivatedLearningTrustV1`, not a caller-constructed bare
`LearningEvidenceVerifierV1`. The activation must have been produced by
`learning.ledger::activate_learning_trust` from a pinned root and an exact
root-signed immutable distribution.

Immediately before the selected-host archive or publication boundary,
`learning.eval` validates the host-sampled time against the activation's
`effective_at` and signed distribution `expires_at`, and rejects zero or invalid
root, distribution, scope, objective, trust or authority-epoch identity. This
check occurs before creating or opening the selected-host publication adapter.
The selected-host path then passes only the verifier contained in that admitted
activation to the internal V2/V3 verification primitive.

An activation object is not a permanently live capability. The owner must refresh
root/distribution state to observe a later revocation or an independently
authorized root-rotation ceremony. A previously activated distribution that has
expired at final use is rejected even if its embedded evidence signatures would
otherwise remain structurally valid.

Ingress verification does not survive an arbitrarily delayed archive or journal
write. After `PublicationPending` is durable, the selected-host final-use guard
loads the original typed archive, resamples the same host clock, checks clock
identity and monotonicity, verifies the current activation and original V2/V3
evidence, and compares the exact decision immediately before invoking the
publication owner. Both distribution expiry and signature expiry can independently
reject this boundary. Rejection creates no publication and retains Pending for
read-only reconciliation; it is not permission to retry an unknown write.

Before decoding or trusting the reloaded archive, the guard compares the digest
of all archived bytes with the originally prepared canonical byte digest. It
also verifies the original outer `holdout_record_digest`; a valid signed inner
payload cannot excuse a substituted outer binding. The same private prepared
bytes supply the initial durable `QualificationArtifactsPersisted` event and
guard identity. Cold recovery derives the expected byte digest from that
phase's `terminal_digest` and the holdout digest from `ComparisonSealed` in
validated anchored history. It never adopts an expected identity from the
reloaded disk archive. A mismatch leaves Pending unresolved and does not submit
to the publication owner.

Agentd consumers also check activation currentness independently of subject
signature validity. The verifier embedded in an activation does not itself
retain the root distribution's expiry.

Owner-local generic evaluator helpers may still receive an already host-owned
verifier beneath the selected-host adapter. Their existence does not permit a
selected-host caller to bypass root activation, and it does not authenticate a
real deployment host.

The default API qualification includes a compiler-negative fixture that attempts
to call the selected-host ingress with `LearningEvidenceVerifierV1`. Qualification
passes only when rustc reports the exact `ActivatedLearningTrustV1` type boundary;
an unrelated compiler failure is rejected rather than counted as evidence.

## Per-attempt current trust at recovery use

A persistent recovery page must not receive one bare
`LearningEvidenceVerifierV1` and treat it as current for every item in the page.
Before each attempt, the host owner supplies a freshly resolved
`ActivatedLearningTrustV1` together with the host time used for that attempt.
That activation must already have passed the root-signature, distribution,
scope, generation and authority-epoch checks owned by `learning.ledger`.

Within one page, `learning.eval` enforces all of the following:

- host time is monotonic;
- the activated distribution is effective and not expired at the sampled time;
- root identity remains exact;
- distribution generation, effective time and authority epoch do not regress;
- one generation cannot silently change distribution digest;
- the archive is re-decoded and V2/V3 evidence is reverified with that attempt's
  active verifier before any first publication write.

The final-use clock sample becomes the page's monotonic time frontier. A late
clock or activation failure aborts before advancing the rejected attempt's
persistent cursor.

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

## Known-no-write rejection and anchored poisoning

`AnchoredProductEvaluationAttemptJournalV1` treats only
`ProductEvaluationAttemptJournalErrorV1::Indeterminate` as evidence that a file
or anchor transition may have committed. That outcome poisons the live wrapper
until authoritative reopen and reconciliation.

Validation, identity, ordering and capacity failures are known-no-write outcomes.
They return their exact typed error and leave the anchored wrapper readable. In
particular, rejecting a second attempt with `Capacity` or rejecting a reused plan
with `Conflict` must not strand the lifecycle reservation held by an already
admitted attempt.

The source regressions exercise:

- anchored near-capacity admission followed by completion through `Published`;
- plan-identity conflict and missing-consumption rejection without poisoning;
- accepted-but-unacknowledged anchor CAS with mandatory reopen;
- every legal lifecycle prefix followed by one process restart;
- exact replay, reservation conservation and monotonic anchor advancement;
- root-signed selected-host activation, signer revocation and distribution expiry;
- compile-time rejection of a bare verifier at the selected-host ingress.

These tests establish repository source behavior only. The selected host still
must qualify the independent anchor authority and the durability/failure domains
on the deployed topology.

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
