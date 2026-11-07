# NDU factorial statistics and cost audit

This is a preregistered ordinary/Hepta × light/NDU × frozen/joint **receipt
structure and arithmetic audit**. It does not run the content model, verify native
receipt authenticity, demonstrate real benefit, or authorize adoption. Its
bundled example is synthetic.

## Executable interface

From the repository root with the reference dependencies installed:

```bash
PYTHONPATH=scripts python -m unittest -v ndu_portfolio.test_factorial
PYTHONPATH=scripts python -m ndu_portfolio.example_factorial /tmp/ndu-factorial-example
PYTHONPATH=scripts python -m ndu_portfolio.factorial \
  --protocol /tmp/ndu-factorial-example/protocol.json \
  --rows /tmp/ndu-factorial-example/episodes.json \
  --selection /tmp/ndu-factorial-example/comparator-lock.json \
  --output /tmp/ndu-factorial-example/rechecked-audit.json
```

For a real prospective study, call `select_comparators(protocol,
validation_rows, locked_at)` **before** any test execution. The CLI equivalent is
`--select --locked-at <UTC timestamp>` with validation rows only. Store the
returned lock outside the held-out executor. Later call `audit(protocol,
validation_rows + test_rows, selection)`. Do not use the synthetic generator as
a way to acquire or certify real data.

Exit 0 means the audit completed, including an audit containing HOLD and observed
budget violations. Exit 2 means inputs cannot support the requested estimand
(e.g. an incomplete matrix, changed lock, or mismatched identities). Neither exit
code is a scientific approval. JSON Schema documents shapes; runtime validation
adds cross-record identity, chronology, completeness, and grouping constraints.

## Complete design and identities

The exact eight arm IDs are A/B/C/D, initial, tuned_fixed, voi, mpc. A is
ordinary/light, B ordinary/NDU, C Hepta/light, D Hepta/NDU. All eight run in both
frozen and joint regimes, giving 16 profiles. Ordinary baseline implementations
must actually be deployable; a JSON flag does not prove deployability.

Each task records a fixed source group, cluster, split, cohort, and family.
Training, validation, and test source groups and clusters must not overlap.
Each validation/test new-task cohort includes text_sufficient, complementary,
asymmetric, prepare_then_gain, and stop_worthwhile. Each validation/test cohort,
including retention, has at least 20 independent clusters. Twenty is a software
stability guard, not a power calculation. Crops, paraphrases, translations, and
adjacent video segments share their actual upstream cluster.

All 16 profiles have matching used parameter capacity and opportunity caps for
training compute/examples, tuning trials, episode cost, wall time, and memory.
Unused padding does not establish capacity matching. All profiles bind the data,
external objective, risk profile, model, policy, evaluator, and meter identities.
Ordinary A/B and Hepta C/D start from identical content within each core across
regimes. Frozen A/B and ordinary baselines share their actual content-model
digest; frozen C/D share theirs. Joint model changes require actual new digests.

The profile must distinguish #4875's nested entropic Bellman objective from V3's
population entropic objective. An objective artifact specifies utility, risk,
duration discount, charge timing, STOP, preference schedule, and failure penalty.
A risk-neutral router cannot be relabelled an equal-objective NDU comparator.
The external endpoint here is fixed mean normalized score minus measured cost;
the auditor does not itself implement either entropic training objective.

## Complete observations, cost, and clock checks

There is exactly one episode_terminal row per task × seed × regime × arm.
Step records and retries never increase sample size. Run and attempt identities
are unique. Failed episodes retain their registered penalty and all attempts.
Unresolved status blocks conditional admission; unmeasured fields remain null.
Missing matrix rows are rejected, never silently dropped.

Each episode has all nine additive categories: encoder, shared, decoder, critic,
planning, codec, failure, retry, sync. Register a disjoint attribution convention:
if retry forward passes are charged to encoder/decoder, retry contains only the
remaining overhead. Count each charge once. A verified zero means no expenditure;
null means unmeasured. Null propagates to totals and net effects.

Declared budget mismatches invalidate the design. **Observed overruns remain in
the audit** with their rows, costs, failures, and statistics. They are listed in
budget_violations and block conditional gates. The same rule covers observed
training/search, episode cost, peak memory, declared latency, and timestamp span.

UTC start/end span and latency have the same end-to-end scope, including failed
attempts, retries, and synchronization. Disagreement greater than 0.001 seconds
(abs tolerance, no relative tolerance) is retained in integrity_violations and
blocks conditional gates. Reversed timestamps are also retained as violations.

## Strong comparators and immutable selection

B selects the largest validation mean net score among A, initial, tuned_fixed,
voi, mpc. D adds B and C to that pool. Selection is separate for frozen and joint.
Lexical arm ID breaks exact ties. Test starts strictly after the lock.

The lock binds the complete validation rows, immutable protocol, choices, and
**pre_evaluation_receipts**. Those receipts freeze training_actual plus research
training/search charges for every profile, including null values. Completed
training/search cannot be edited or filled after the lock. Only final research
evaluation charges may be populated later. The final audit re-derives the lock
and rejects any mismatch. A hash-bound timestamp is not an authenticated native
timestamp; source and clock authenticity still need independent verification.

## Contrasts and inference

The fixed family has 20 contrasts:

- Frozen and joint B−A, D−C, D−B, and D−C−B+A.
- Frozen and joint B minus its strongest ordinary comparator, and D minus its
  strongest complete comparator.
- Joint minus frozen for A/B/C/D.
- Joint minus frozen external quality on retention for A/B/C/D.

Pair arm differences on the same task and seed, average within independent source
clusters, then average clusters equally. Resample full cluster summaries with a
preregistered NumPy seed. At least 10,000 bootstrap draws are required. Two-sided
percentile tails use alpha/(2×20), a Bonferroni family correction. Coverage remains
approximate and requires representative independent clusters. The example uses
20,000 draws, 2,560 terminal rows, and only 20 source clusters per split/cohort.

Net benefit requires the lower endpoint above net_margin. Retention requires its
quality lower endpoint at least −retention_margin. Average retention does not
guarantee every old capability is preserved; capability-specific gates need their
own prospective plan. Current seeds index episode randomness under one model
digest per profile; they do not represent independent training fits.

**scientific_gates and every contrast.gate always remain HOLD**, even if an input
self-declares real. native_receipt_verification is NOT_IMPLEMENTED.
statistical_gate is arithmetic only. conditional_gates_on_verified_receipts shows
what the statistics would support *if* genuine provenance, owner, and complete
metering were independently established. Synthetic inputs, unknowns, budget
violations, and integrity violations block those conditional gates.
adoption_authorized is always false.

## Research ledger and deployment frequency

Training, search, and evaluation are separate research categories. All use the
registered common unit and have actual usage, not assumed opportunity-cap usage.
The inference ledger and research ledger remain distinct: evaluation inference
already appearing in both must not be double-counted in a combined invoice.
Unknown components make the relevant totals unknown.

For each preregistered deployment count N, the audit reports:

`D inference net advantage − cost_weight × (D research cost − comparator research cost) / N`

Confidence endpoints shift by the same measured research-cost difference.
These intervals condition on measured research charges; they do not model energy
prices, hardware variation, or uncertain demand. The deployment counts are
scenarios. Common setup costs require consistent allocation or separate accounting.

## Qualification boundary

Thirty-five focused regressions cover complete-matrix requirements, source
leakage, repeated attempts, failures, nulls, capacity/objective matching, lock
chronology and mutation, all-cost accounting, clock inconsistencies, observed
overruns, clustered statistics, and self-declared-real rejection. The evidence
directory retains the integrated execution and synthetic arithmetic summary.
None establishes real multimodal benefit.
