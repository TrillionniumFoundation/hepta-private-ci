# ACT3 stage 4: real filesystem effects

**384 actual episodes / 16 controlled probe tasks; no learned-model promotion.**
The fixed option library, head and GRU all receive the same public-state stop
guard and primitive budget. All three complete 96/128 episodes, use 1,600
primitive calls per arm, and have zero observed false success or duplicate
effects. The GRU needs 34 stop overrides. The 25% incomplete stratum is the
deliberately opaque owner after its first effect; UNKNOWN is preserved.

The new adapter stages files and atomically publishes immutable effect
directories. Version 1 stores plain content and version 2 a JSON envelope.
The cohort covers lengths 3/5, both versions, lost acknowledgements, one-time
precommit failure after partial progress, and unavailable post-effect observation.
The owner binds invocation, original task, key, goal, codec and physical bytes.
Cross-task copied effects, metadata-only drift, changed intent, codec mismatch
and corrupted payload cannot establish completion. Three behavioral tests pass.

The 16 generated task IDs are controlled probes, not independent production or
field tasks. The observations are deliberately normalized to the same ten ACT2
features and three options; this does not establish open-ended skill acquisition
or semantic generalization. Eight repeated model seeds are not extra task units.

`run1/` retains the frozen manifest, all 384 trajectories and complete physical
destination bytes. `retained-audit.json` independently verifies the full panel,
goals and 1,248 payloads from the archive. `SOURCE_AND_EVIDENCE.json` binds the
local runtime, tests and all evidence. No earlier source's pass is transferred.

```sh
python3 -m unittest discover -s scripts/act2_learning -p test_file_family.py -v
python3 scripts/act2_learning/qualify_families.py \
  --archive qualification/act2-learning-20261110/run2 \
  --families filesystem --output /new/empty/path/filesystem
python3 scripts/act2_learning/audit_families.py /new/empty/path/filesystem
```

Policy selection, owner requests, scoring and wall time are recorded. These are
not complete production lifetime costs. Same-UID fixture ownership, no general
concurrent-writer/power-loss claim, no production FinalUse, no adoption. The
following browser/composition stage must obtain actual browser evidence itself.
