# Independent progression audit

This package is written by a separate review agent. It does not change the
candidate models, choose their hyperparameters, or inspect confirmation data
before the freeze. It is a finite-model qualification, not a positive efficacy
or production admission verdict.

## Executed independent references

Run from the repository root:

```bash
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.progression_audit_20261031.independent_checks \
  --out /path/to/new-audit-result.json
```

The value reference rebuilds the recurrence from the public contract. Recovery
uses its independent closed-form survival probability and expected waiting time.
It does not consume the candidate's edge or reward arrays. Randomized-policy
values are recomputed with this reference, and logit gradients are checked by
central finite differences of the full initial-value objective.

The first-FIRE reference uses an embedded event-count recursion and Poisson
tails. It does not call a matrix exponential or the candidate's first-event
implementation. It includes initial FIRE atoms, STOP/deadline loss, observation
branches, finite budgets and randomized continuation decisions. Arrival-rate and
deadline-rate derivatives are checked separately by finite differences.

The ordinary planning reference enumerates one-observation plans on independently
generated public schedules, including asymmetric observation confusion matrices.
Its results are compared to the implementation and to the full fitted Bellman
teacher's lower-bound relationship.

The native audit recomputes paired outcomes and CPU accounting directly from
raw rollout receipts. The pair identity is `(split, session_id)`, since the
development IID and stress cases deliberately reuse their local session names.

## Pre-freeze results

`PRE_FREEZE_AUDIT_02.json` records:

| Reference | Coverage | Maximum discrepancy |
| --- | --- | ---: |
| Independent optimal finite recurrence | 8 contracts, 640 states | `4.44e-16` |
| Independent randomized-policy values | Same 640 states | `2.22e-16` |
| Full-objective logit finite differences | 32 directions | `6.27e-12` |
| Event-count first-FIRE CDF | 120 cases | `7.22e-16` |
| Arrival/deadline derivative finite differences | 48 directions | `8.09e-12` |
| Independent one-read plan values | 512 states, 32 schedules | `2.22e-16` |
| Native/Python task outcomes | 33 pairs, 134 actual reads | All semantic outcomes equal |

Summed native child CPU is exactly `0.693685` seconds in the retained receipts.
Parent-plus-child arithmetic differs by at most `1.272e-6` seconds because parent
timer fields are sampled successively. The 32 ordinary cases' mean complete CPU
is `0.0209460945` seconds for Python and `0.0448448330` seconds for native.
The native fixture therefore does not support a performance-improvement claim.

The first audit report is retained. Its mathematical checks passed, but its
native audit grouped cases by `session_id` alone and counted only 17 unique
pairs. The auditor corrected the identity key, added a cardinality assertion,
and reran all checks in report 02. The candidate native code was unaffected.

## Cost accounting finding

Pre-freeze review found that the value-boundary preparation's reported outer
CPU stopped before writing its compressed model bundle, while confirmation
loaded the bundle before starting its outer timer. Per-policy preparation also
omitted deployment-artifact loading/serialization. This does not change the
mathematical solution, but the existing fields could not support an unqualified
claim of complete preparation/deployment cost.

The implementation owner accepted this finding and retained preparation attempt
01. The corrected `prepared-v2` serializes, hashes, reloads and validates each
actual deployable policy. Confirmation uses those artifacts and charges their
measured per-policy loading cost. Its outer timers include source validation,
large bundle loading, result serialization and evidence hashing. The final small
receipt and manifest writes, and process startup/exit, are explicitly outside
these internal timers; an external process wrapper can account for the lifecycle.

`VALUE_PREPARE_AUDIT.json` independently verifies all 112 prepared artifacts,
13 source dependencies, 96 deployment artifacts and all 40 fit certificates.
The amended freeze-manifest SHA256 is
`d91df0ef83c9431777b17ec6f1071bd611e0ab3698e9efd86aef9db8a39ef356`.
Preparation stage CPU is `17.840955134` seconds, including `0.320330921` seconds
after the former pre-bundle timer endpoint. Actual deployment serialization and
prepare-time reload/validation total `0.105790286` seconds. The finding is closed
for this declared stage/deployment accounting scope. No confirmation episodes
had been generated at this verification.

`TEACHER_PREPARE_AUDIT.json` independently verifies 688 artifacts and 18 source
dependencies. All five selected models have 4,484 parameters, 6,000 actual
updates, nonzero output weights, and validation improvement over update zero.
This establishes training and selection provenance; it does not establish
heldout improvement. The teacher manifest SHA256 is
`a6c002ff2d61ca0d387af8cbc7d45ab9399aeda8019ef2ea9ba1a46791fd9694`.

## Scope limits retained

The direct mirror fit is model-based finite policy improvement using current-
policy Q values. It is not a model-free deep-Q convergence result. Each contract
is refitted; the stress contracts do not establish amortized out-of-distribution
neural generalization. The first-FIRE region's derivative holds its active policy
fixed and does not differentiate a discontinuous hard boundary selection.

The same-policy ordinary and analytic task effects should be pathwise equal;
the analytic execution currently adds first-FIRE probability calculation. An
equal-policy null cannot establish an independent analytic-cell utility benefit.

The native binary executes the residual network and a durable action owner.
Cell physics and actual file/content effects remain external. Verified restores
follow acknowledged completed effects. Trusted checkpoint recovery does not
prove exactly-once settlement across arbitrary native/external crashes or
security against hostile checkpoint authors.

The host CPU price is a declared research accounting coefficient, separate from
the task's stochastic clock and Bellman objective. CPU counts are not hardware
energy measurements. Actual confirmation effects and admission gates require
their own independently recomputed post-freeze evidence.
