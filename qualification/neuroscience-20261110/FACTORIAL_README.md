# HPCA four-arm factorial qualification — independent read-only gate

**Status: HOLD_NO_GO.** This is an additional strict evidence parser for the
existing #5811 shadow suite, not another HPCA-MICRO-V1 run, model training,
production owner integration, real evaluator or evidence of benefit. It makes
no changes to native Cell, Agentd, PERC/MEM/PRED/CTRL/VERIFY/ACT/LEARN weights,
permissions or adoption behavior.

`hpca_factorial.audit(manifest, rows)` requires a frozen source commit and exact
tree SHA, dataset, evaluator and seed assignment digests, distinct ordinary
and Hepta architecture IDs, four explicit cells `A=Ordinary`,
`B=Ordinary+NDU`, `C=Hepta`, `D=Hepta+NDU`, all six task families and both
dense/sparse feedback regimes. Every registered seed/family/regime block must
contain all four arms with the same A/B/C task identities and resource
**opportunity caps**. A training task must differ from the held-out evaluator
task and a proposed *different* next task; sequence times must be ordered.
All actual resource counters, costs, failures, missing retention and result
receipts are accounted separately. It rejects missing/duplicated arms,
reused receipt IDs, nonfinite scores, future-label overlap, different
task/caps, and self-inconsistent source IDs.

The four predeclared seed-cluster means are `B−A`, `D−C`, `D−B`, and
`(D−C)−(B−A)`. Positive-side exact sign-flip p-values are diagnostic under
seed-level symmetry, only when 2..16 independent seeds are present. Holm
adjusts across *these four primary contrasts*, not exploratory per-family
breakdowns; it does not establish a confirmatory theorem for adaptive design.
With more seeds, p-values are explicitly `null`, not silently approximated.

This parser verifies **internal consistency only**. Input SHA-256 digests and
booleans are self-declarations, not owner signatures. Timing, task family,
independence, actual delivery, missing data, training/evaluator separation,
rights, data consent, energy, or finances remain unverified externally. Even
optimistic synthetic metrics always emit `verdict=HOLD_NO_GO` and
`authority=DENY_ALL`. Independent owner-attested real A→B→selection/NoUpdate
→different C→cold recovery, prospective multi-seed data, strong baselines,
real cost mapping and safety/noninferiority remain **OPEN**.

Test locally: `python3 -m unittest discover -v -s qualification/neuroscience-20261110 -p 'test_*.py'`.
The tests use *synthetic* values exclusively; no benchmark score in this suite
can be reported as realized training/production performance.

## Coexisting input contracts

This module is named `hpca_factorial.py` in the consolidated tree so that the
separate `factorial.py` family/cohort preflight remains available. The schemas
and required inputs differ; do not substitute one parser for the other.

| Module | Interface | Schema | Scope |
| --- | --- | --- | --- |
| `factorial.py` | `FactorialRow`, `factorial_evidence(rows)` | `hepta.neuroscience.factorial-shadow.v1` | Balanced registered family/episode roster, frozen per-seed core/controller cohort, nullable outcomes/resources |
| `hpca_factorial.py` | `audit(manifest, rows)` | `hepta.hpca.factorial.shadow.v1` | Complete six-family, dense/sparse and four-arm manifest, resource totals and temporal A/B/C declarations |
| `factorial_trial_preflight.py` | `FactorialTrialRow`, `evaluate_core_ndu(rows, required_cells=...)` | `hepta.neuroscience.core-ndu-preflight.v1` | Explicit registered family/density cells, measured resource fields, equal cell weighting, declared seed/task partition and episode-roster checks |

All three preserve four primary seed-cluster contrasts and unconditional
HOLD_NO_GO / DENY_ALL outputs. The HPCA parser pins architectures and records
trained-model identities; it does not prove common trained weights across its
arms or families. None of these parsers grants causal attribution, physical
execution or owner authority.

The original family/cohort command remains:

```sh
python3 qualification/neuroscience-20261110/factorial.py --trials legacy_rows.jsonl
```

The separate trial preflight consumes `FactorialTrialRow` JSONL and a JSON array
of registered `[family, feedback_density]` pairs, for example
`[["ACT", "sparse"], ["ACT", "dense"]`:

```sh
python3 qualification/neuroscience-20261110/factorial_trial_preflight.py \
  --trials trial_rows.jsonl --required-cells registered_cells.json
```

The trial contract requires declared actual CPU, wall time and peak RSS, freezes
cell evaluator/opportunity fields across seeds and episodes, and rejects declared
training/evaluation task or seed overlap and unequal per-cell episode-ID rosters.
It averages episodes within cells, then weights registered cells equally within
each seed. These inputs and weights differ from the family/cohort contract;
there is no implicit row conversion. The original nullable-outcome/resource
rules and missing-primary inference masking in `factorial.py` are unchanged.
Self-declared resource values and digests do not authenticate actual execution.

The original tests remain in `test_factorial.py` and `test_hpca_factorial.py`.
The trial suite is `test_factorial_trial_preflight.py`, with
`test_seed_identity.py`, `test_episode_roster.py` and `test_partition_overlap.py`.
All run through the original discovery command above and the existing
`hepta-neuroscience-shadow.yml` path trigger. The retained cell, seed, roster and
partition RED/GREEN logs describe their original historical source snapshots;
they are not current-source test results or authority to run owner/model tasks.
