# HPCA four-arm factorial qualification — independent read-only gate

**Status: HOLD_NO_GO.** This is an additional strict evidence parser for the
existing #5811 shadow suite, not another HPCA-MICRO-V1 run, model training,
production owner integration, real evaluator or evidence of benefit. It makes
no changes to native Cell, Agentd, PERC/MEM/PRED/CTRL/VERIFY/ACT/LEARN weights,
permissions or adoption behavior.

`factorial.audit(manifest, rows)` requires a frozen source commit and exact
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
