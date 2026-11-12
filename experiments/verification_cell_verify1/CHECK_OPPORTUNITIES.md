# Frozen optional-check opportunities

`CheckOpportunityJournal` adds one optional-check opportunity per original
`FrozenAttempt`, at one planned predecision frontier. It uses the existing
`ShadowJournal` and `TreatmentJournal`; it creates neither terminal labels nor
an alternative permission or acceptance mechanism. This is a local study data
plane. Ordinary deployment and independent business benefit are not established.

## Freeze and execute

1. Create the actual policy Shadow/Treatment journals with the same roster and
   target. Freeze each policy's complete Shadow manifest digest. Preserve source
   groups; repeated trajectories do not become independent task sources.
2. Before any source observation, call `CheckOpportunityJournal.create` on one
   source treatment. Supply `policies={policy_name: shadow_manifest_sha256}`, the
   frontier, registered optional checker, strict integer offer numerator and
   denominator, and the free-view schema, mandatory-contract and evaluation-spec
   digests. The checker version is copied from its original registry. The
   evaluation spec freezes losses, calibration bins and cost attribution before
   outcomes. No probability or eligibility field is a permission grant.
3. Record the source policy's original `Prediction`, including the complete
   shared free-view `Snapshot`. Call `reserve` with the original free-evidence
   digest and host eligibility evidence. This must precede that trajectory's
   first treatment choice or disposition. First commit a one-use draw intent,
   then draw and commit the original ticket in a separate transaction. A
   feasible opportunity uses `secrets.randbelow`; an infeasible one retains its exclusion
   reason with zero offer probability and performs no draw. Both remain in the
   original roster. Missing observations remain missing opportunities.
4. For each other policy, record the identical original free Snapshot, then call
   `bind_policy` with its original free-evidence digest before any treatment
   choice. The source is bound automatically by `reserve`. The companion record
   pins the original ticket, free view and both original ledger positions. The
   source lock remains held while another policy commits its binding.
5. Use the original treatment `choose`, then `start_optional` before invoking an
   optional checker. `start_optional` checks the consumed offer and exact
   checker/version/snapshot, then invokes the original treatment start validator
   and writes its original event in one transaction. It never runs the checker.
   Complete only the original operation through `TreatmentJournal.complete`.
   Missing replies remain pending; recovery does not dispatch a replacement.

The no-check arm still consumes the same free view and may defer. Every policy
retains the original mandatory host checks and final disposition gates. In
particular, a missing optional offer cannot waive a required property check or
authorize an acceptance. Mandatory checks are outside this optional lottery.

## Audit and interpretation

`audit_treatment` rereads the actual journal, verifies the full roster, target,
checker version and pre-choice consumption, and rejects an optional execution
without its offer or at another snapshot/checker. Calling the old `start`
directly cannot make such a run pass this audit. The returned
`bindings_sha256` covers the companion records that the original treatment
root does not cover. The opportunity ledger checkpoint covers both the complete
draw-intent set and the ticket chain. Pin and recheck these with the manifest and
roots and the original policy journal roots when publishing an evaluation.

Retain roots outside the database; recovery can require
`expected_manifest_sha256` and `expected_ledger_sha256`. Duplicate reserve and
binding calls refuse. An interrupted entropy call or a process death after the
draw but before commit leaves a pending intent with draw status UNKNOWN; a
subsequent reserve refuses even when no ticket exists. Pending and unstarted
opportunities remain separate in the full original denominator. Reconcile the
retained originals after an uncertain call without drawing again. SQLite
consistency is not protection against coordinated
owner rewrites, authenticated wall-clock chronology or proof of random-source
custody. Digests alone cannot prove that all free information was exposed or that
its contents were actually observed before the decision.

The recorded probability is the probability of an **offer**, conditional on
declared feasibility. It is not a probability of checker execution or compliance.
This is per-opportunity assignment, not the separately authenticated whole-cluster
design required by `matched_qualification`. No p-value or causal benefit follows
from these receipts. Physical cost, independent terminal adjudication and
calibration remain separate requirements. Reports retain HOLD / NONE.
