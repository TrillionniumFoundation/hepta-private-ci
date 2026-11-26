# learning.plasticity algorithm and evidence contract

This document makes the current proposal algorithm self-contained. It describes
repository behavior and required evidence; it grants no selection, installation,
topology-application, activation, promotion or release authority.

## 1. Frozen iteration context

One iteration is identified by `IterationEnvelopeV1`, the selected artifact digest,
window ID and digest, exact baseline and candidate generations, objective digest,
canonical `MutationGrammarManifestV1.semanticDigest`, and current owner-frontier
digests. The envelope is immutable after independent evidence is signed. A retry
uses the same envelope, generation and proposal identity or it is a new iteration.

Immediately before durable admission Agentd re-reads the authoritative artifact,
learning-ledger, NDU, broadcast-policy and neuron frontiers. A stale, rolled-back,
unavailable, wrong-owner or value-substituted fact fails closed.

## 2. Parameter candidate generation

For every policy-allowed signal and every declared positive update scale, generation
computes a bounded Q32 delta from eligibility, modulator and learning rate, applies
the signal and policy bounds, and groups deltas in canonical layer/parameter order.
The set always includes one explicit no-change candidate. Candidate and generator
digests bind the selected artifact, exact window, complete norm profile, mutation
policy, signal values/evidence, scale policy and canonical candidate bytes.

`GeneratorCoverageDraftV1` separately proves generator-relative coverage:

- the expected learnable parameter set;
- the actual signal parameter set;
- exactly one content-addressed omission reason for each expected-but-absent signal;
- the declared scales and number of generated update candidates;
- artifact, qualification and owner-evidence frontiers;
- one of `CandidatesGenerated`, `ZeroEligibleSignals`,
  `PolicyDisabledUpdates` or `NoAdmissibleUpdate`.

An independently authenticated Observer seals the draft. The terminal categories are
not interchangeable and no terminal implies selection or installation.

## 3. Numeric semantics and trust regions

`FixedQ32` values use signed fixed-point raw integers. Checked arithmetic is required;
overflow, impossible conversion, zero denominator or malformed bound is an error,
never saturation. Canonical encodings use big-endian fixed-width integers and stable
length prefixes.

For every layer, the proposal verifies the exact squared L2 numerator against the
declared non-zero Q64 baseline denominator and the layer relative-norm limit. It also
verifies the aggregate energy-weighted numerator against the checked sum of all
declared layer denominators and the global limit. Passing the global check never
waives a failing per-layer check.

All comparisons are exact integer ratio comparisons. Ordering, duplicate rejection
and digest construction occur before persistence so platform floating-point behavior
cannot change proposal identity.

## 4. Independent evaluation and no-change

Every generated update has one exact independently signed evaluation bound to the
candidate, baseline, frozen evaluation plan, final holdout use, retention slices and
metric-role semantics. Generator, Observer and Evaluator identities are pairwise
independent at the configured principal/controller/key boundaries.

A no-change-only result is durable only when an independent Evaluator attests the
exact `NoAdmissibleUpdate` payload. Empty signals and policy-disabled scales use
their distinct coverage terminals and are not silently relabelled as evaluation
failure.

## 5. Topology proposal semantics

Topology candidates use typed add, remove, replace, split, merge, rewire and retire
operations. Every operation binds compatibility, lesion/ablation, resource, security,
migration, rollback, writer-handoff and evidence digests. A handoff identifies the
old and new owners, strictly advancing writer fences and exact source/migration/
rollback/acknowledgement plans.

`learning.plasticity` persists proposals only. A separate runtime owner may consume an
independently accepted governed handoff under a payload-bound, single-use FinalUse
grant. Healthy replacement and stopped/quarantined recovery are distinct transitions
with distinct destinations and grants.

State and optimizer transport for split/merge/replace must be supplied as an exact
migration plan. Unconstrained node multiplication, implicit weight averaging and
loss of outstanding operations are invalid.

## 6. Stopping, instability and retention evidence

A self-iteration coordinator must retain the frozen identity and terminate with one
typed outcome: committed proposal, independently attested no-update, rejected input,
queue overload, cancellation before durable admission, deadline exceeded before
durable admission, unavailable owner, or indeterminate durable outcome requiring
exact-key reconciliation.

Repeated sign reversal, boundary clipping, worsening held-out metrics, old-task
retention loss, safety violation, lineage mismatch or canary rollback failure are
instability evidence. They stop or quarantine the iteration; they never authorize a
larger trust region or automatic promotion.

Prospective efficacy requires held-out task families and future windows that were not
used to choose the candidate. Old-task retention, adverse/noisy evidence and explicit
no-change/fixed-update baselines are mandatory comparisons.

## 7. Golden and property evidence

Repository qualification must include:

- stable parameter and topology golden vectors;
- deterministic regeneration under input-order permutation;
- exact no-change and terminal taxonomy;
- duplicate, unknown-field, oversize and protected-surface rejection;
- checked arithmetic and ratio-boundary properties;
- state-machine tests for proposal/anchor/terminal receipt recovery;
- malformed/truncated/complete-invalid frame tests;
- long-horizon deterministic replay;
- parameter/topology sequence tests preserving generation and handoff lineage;
- differential comparison against an independently implemented integer oracle.

The exact mapping receipt binds every claimed operation and focused test function to
the current candidate commit and blob. Test names in a tracked document are not pass
receipts.

## 8. Claim boundary

Repository source and tests can establish deterministic proposal construction,
admission, persistence and source composition. They cannot establish physical
rollback-domain independence, target-host filesystem behavior, production telemetry,
independent acceptance, operator acceptance, activation, promotion or release.
Those facts require the target-host qualification contract.
