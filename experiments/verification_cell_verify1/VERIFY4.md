# VERIFY-4: frozen evidence, complete denominators and repair lineage

This stage composes the VERIFY common candidate
`a2cd828aad47c56ac8c01dc2e423454eca7eafae` with the exact treatment journal from
`1609a21e5113440bab9de75ccd2afc233e29eec0`, then hardens its evidence boundaries.
The imported treatment implementation is existing work, not a new field trial.
The raw qualification is retained under
[`qualification/verify4-evidence-closure-20261110`](../../qualification/verify4-evidence-closure-20261110).

## Authority and learning have distinct responsibilities

| Component | Responsibility | Evidence required |
| --- | --- | --- |
| Native host | Permissions, ownership, signature/trust checks, revocation, deterministic constraints and effect readback | Original owner configuration and signed/read-back evidence |
| Frozen risk and checker models | Predict terminal risk and conditional outcomes of optional checks | Exact model contents, training/held-out groups and immutable version |
| Advisory scheduler | Select an optional check, defer, block or suggest a feasible follow-up action | Frozen decision losses, actual observed history and budget |
| Treatment/repair journals | Record what the host actually did, pending operations, original outcomes and lineage | Original operation identity and current independently authenticated labels |
| External study authority | Freeze the roster/design/criteria, authenticate collection and decide adoption | Independent custody, suitable assignment design, full costs and positive terminal net benefit |

The native interfaces remain `EvidenceHost` and `QualificationEvidenceStore`
for trust, and `AgentdAutomationEffectHost` for authoritative effect readback;
see [INTEGRATION.md](INTEGRATION.md). The learned component cannot relax those
checks, create an acceptance signer, or set its own scientific passing standard.

Frozen model validation recomputes content identities at construction and
consumption. Altered counts, tables, costs, registry versions or split groups
cannot retain the original model digest. This proves local content binding,
not the provenance, independence or usefulness of training data.

`RiskTable` now uses `verify-shadow-frequency-v2`: its identity includes the known
and missing training-label denominators that v1 omitted. Valid predictions are
unchanged, but old v1 identities refuse ingestion and require an explicit new
fit/freeze. Historical artifacts retain their original source and identity.

## Checks, outcomes and missingness

[TREATMENT.md](TREATMENT.md) defines the complete `checked`, `unchecked`,
`abstained`, `pending` and `missing` partition and its per-source-group summary.
The partition is fixed at the original host disposition. Late replies cannot
retroactively claim that a check was available before a decision. Old frontier
choices do not cover missing decisions at a later frontier. A completed old
check remains observed exposure and is separately marked stale.

Independent terminal labels cover the whole frozen roster, including rejected,
interrupted, unchecked and unstarted attempts. Explicit missing labels retain
their reasons. A checker result, a successful callback or a digest is not itself
an independently adjudicated semantic outcome.

Matched reports now include observed/clean/error/missing counts per disposition,
accepted-error denominators, full-roster missing-label bounds and clean-blocked
counts. A clean outcome after blocking is not automatically a causal false
positive: the intervention may have prevented the error. Therefore
`causal_false_interruption_rate` stays undefined without an appropriate control.

## Cold recovery and current trust

Use the [prospective journal](PROSPECTIVE.md) with externally retained manifest
and ledger checkpoints. Label ingress retains an opaque bounded attestation in
the same event as the exact label and issuer/version/manifest bindings.
`report(authenticate=current_host_verifier)` reauthenticates every label under
the host's current trust, revocation and freshness policy. The verifier must
check original signed evidence and cannot substitute or normalize checked bytes.

Legacy callback-only labels are inspectable as unverified diagnostic records.
They cannot enter strict authenticated reporting. Recomputing ordinary SQLite
hashes after editing an outcome does not manufacture its original attestation.
Missing, false or merely truthy verifier results refuse authentication; a ledger
that changes while being verified also refuses the report.

The public keys/secrets used by tests are engineering fixtures. They establish
neither an independent trust domain nor a new independent real task.

## Statistical admission matches the assignment design

`analyze_matched` accepts a frozen manifest, full observation roster and three
separate host verification boundaries: label, physical-cost and study-design
verification. Its output schema is `hepta.verify.matched-analysis.v2`; the input
manifest remains v1.

The supported design is one independent fair allocation coin per cluster,
assigning the same `first_arm` to all paired tasks within that cluster. The
design receipt binds the manifest, entire pair/environment allocation, method,
external study authority, frozen time and original signed evidence. A different
paired/observational design needs a justified matching inference procedure.
Issuer names, timestamps and hashes alone do not authenticate this design.

Whole-cluster sign flips use each cluster's contribution to the same task-weighted
mean that is reported. Without authenticated supported design,
`conditional_group_signflip_one_sided_p` remains a diagnostic and
`paired_group_signflip_one_sided_p` is null. No conditional p-value can satisfy
the admission gate. Authentication cannot modify the frozen manifest, rows or
design receipt.

The corrected gates require complete horizon labels, verified full costs,
acceptable coverage and accepted-error behavior, strictly positive terminal-error
reduction, strictly positive total-loss improvement, preregistered practical
thresholds and the appropriate statistical threshold. Setting a minimum to zero
does not admit zero actual benefit. Passing these checks only makes a record
externally reviewable; scientific admission remains `HOLD` and authority `NONE`.

## Repair keeps a separate outcome target

The existing numerical decision layer can compare `repair` with accept/reject.
Its supplied losses must include repair cost and residual risk. In a declared
fixture with prior error 0.2, accept losses (0,100), reject (5,5), repair (2,2),
and a perfect check costing 0.5, checking has net value 1.1. This is a numeric
decision check, not measured repair benefit or a success rate.

The unchanged-artifact treatment journal deliberately refuses repair actions.
A repair needs its own original operation, owner permission, result/readback,
new subject/version and executed-policy target. The old forecast and its label
must retain their original target. [REPAIR.md](REPAIR.md) describes the separate
lineage accounting boundary. Even authenticated before/after improvement alone
does not establish causal repair benefit; use the frozen paired/randomized task
comparison and include all repair, verification and recovery costs.

## Remaining field admission material

To run the prospective real-task confirmation, the host must supply:

1. A frozen owner/task/source-group roster with training and held-out provenance,
   target horizons, model/source versions, utilities, budgets and criteria.
2. A suitable assignment design, original allocation evidence and independently
   configured study-authority trust; use identical mandatory gates in all arms.
3. Current owner/checker/adjudicator identities and original signed terminal
   labels that cover checked, unchecked, abstained, failed and unresolved work.
4. Original check/repair/readback receipts and exclusive full-cost attribution,
   including preparation, learning, inference, scheduling, failures and recovery.
5. An external adoption decision followed by a separate next-task consumption
   qualification, if adoption is approved.

The bounded host search in this run did not locate an admissible field bundle;
its search coverage was incomplete. It is not evidence that no such bundle
exists. Newly admitted independent real tasks remain **0**. Controlled subprocess,
SQLite, authentication and numerical fixtures remain engineering evidence.
Full repository CI and exact-candidate scientific qualification are distinct gates.
