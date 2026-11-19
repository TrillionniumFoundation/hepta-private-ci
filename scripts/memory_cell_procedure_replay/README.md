# Historical procedural repair replay

These drivers retain the original target tests, source hashes, genuine commit
patches, patch preconditions and actual command outcomes for a small historical
CI cohort. They do not call a learned model.

The recorded experiment and exact executed driver bytes are preserved in
`qa/stem-bakeoff/evidence/20261023-natural-ci-repair-replay/`. Extract its evidence
archive and use the pinned drivers inside that archive to reproduce its plan.
The source copies here are formatted for review; formatting preserves their
Python AST but changes the byte hashes that the old plan intentionally checks.

For a newly registered replay, place the admitted `source_bundle/` and
`evidence/` inputs next to these drivers, run `replay_bundle.py --output` into a
new plan directory, then pass that plan and its SHA-256 to `replay_run.py`. Never
rewrite the recorded plan or relabel the historical cases as future tasks.

The executor is Linux-specific because it records `wait4` resource units and
uses process groups. Each admitted action runs real `git apply --check` and
`git apply`, then the original target command. A failed no-op must reproduce the
original signature before the result can count as a repair effect.
