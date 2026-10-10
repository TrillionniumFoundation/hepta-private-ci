# Learned read policy across frozen source sessions and restore

This continuation starts from `59f9eadd5cc919359079e04442f7343838a60057`.
It reuses the existing reader capability, controlled source collection, event
projection, calibrated persistent hybrid retrieval and ten-weight policy. It does
not claim those inherited implementations as new, nor retrain a large reader to
exercise a ten-weight policy. Source-written knowledge runs continue separately.

## Missing integration, not another memory store

The old v2 FrozenMemorySession accepted policy roots only from its current evidence
scope. A useful transferred policy was trained on other calibration scopes. The
v3 extension accepts bounded original policy-source Documents and persists only
their exact identity/scope/time/content-digest references. Training source text is
never inserted into the reader evidence view. The full training view is validated
by the existing policy consumer before freeze; reference hashes do not issue
consent, reviewer independence or production authority. Old v2 snapshots are not
silently upgraded and retain their ordinary behavior.

Source references must precede the declared cutoff, bind all policy roots, and
respect byte/count/identity bounds. First reads, post-generation checks and replay
all reject a currently withdrawn ancestor. Shared calibration roots are retained
conservatively for every contrast because the hybrid mixing policy was also tuned
on that calibration corpus. A learned policy cannot shed its ancestors merely by
being moved to a different scope or copied from an old disk snapshot.

## Actual experiment

The frozen source artifact remains `11669174727`, ZIP SHA-256
`23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`.
No source/answer, candidate pool, reader, hyperparameter or task is selected from
new scores. Sources are authored controlled-program observations, NOT production
history or independent human-verified sufficient evidence. All eight existing
questions remain; this is not a new prospective test cohort.

1. Train the existing ten weights using only eight declared calibration scopes.
2. A source/policy-only command freezes 32 local session views (eight scopes by
   four policies) before any task-plan argument is opened. These are NOT 32
   independent/qualified snapshots. Exact hashes bind every scope and policy.
3. A new process uses the SAME pinned Qwen research reader for hybrid, deterministic
   organization, initial policy and learned policy, 32 actual generations. The
   same original candidate IDs and 2,048-input/64-output budgets apply. The reader
   receives exact sources plus the existing schema expansion. No answer repair
   or citation insertion occurs. All raw answers are durable before task labels
   or procedure recipes are scored. Every procedural choice uses the same worker.
4. A separate process reopens a copied old snapshot and replays externally pinned
   committed results without invoking a model. A newer supplied withdrawal of a
   calibration root must block every dependent old result. Changed control pins,
   malformed snapshots and incomplete result censuses are errors, not successful
   withdrawal tests. A current-control file is NOT an authenticated live fleet.

The report compares final task wins/losses against calibrated hybrid, deterministic
organization and initialization separately. Beating an untrained policy does not
establish superiority over the deterministic baseline. Procedure success comes
from actual worker exits, not language-model self-assessment. Citation identity,
QA success and independent semantic entailment are distinct; no semantic precision
or production acceptance is certified.

## Costs and retained limits

Keep inclusive measured phase envelopes for original extraction, original complete
index/planning, policy write (including training), session freeze, current read,
backup/restore and replay. Their nested model/worker/training times are diagnostics,
not added a second time. Original source, index, snapshot and copied backup bytes
remain in accounting; source references do not erase original retained data. The
model inventory is retained without distributing licensed model weights. A sum of
phase work across runs is not measured online latency or a production cost claim.

The restore test establishes same-input committed-result parity, NOT old-task
retention after new parameter updates. Real long-term retention, cross-host outage
recovery, workload amortization, independent snapshots/calendar windows and
production maintenance remain unknown. The total production lifecycle cost stays
null. The earlier independent human source review remains pending; neither this
program's receipts nor its authored dependencies replace that review.

The read-only `hepta-memory-frozen-policy.yml` runs the entire locked regression
suite and real pretrained calls in different processes, then exercises the real
filesystem restore. An isolated temporary formatter can prepare a separate branch;
it never changes main/the PR head and removes itself from its candidate. All
required repository format and Architecture checks remain in force.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
python3 scripts/memory_cell/frozen_policy_trial.py --help
```

No production owner, default serving route, selected adapter or independent
acceptance policy is modified. Check exact generating source and terminal CI;
written code or successful mechanics are not new model-quality evidence.
