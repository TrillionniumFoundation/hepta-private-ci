# Frozen SmallHCSN numeric profile

This research adapter loads the original physical implementation from captured,
hash-bound capsule/common/optimized bytes. It requires the original full checkpoint
and the pinned Python 3.14.4, NumPy 2.5.5, Torch 2.15.0+cpu Linux environment.
Numeric tasks contain finite `[time,batch,6]` input and initial state, without labels.
The original model returns logits/features and preserves all five PopulationState
tensors, the step and complete configuration across real continuation.

`prepare_profile.py` builds the manifest; `numeric_runner.py` accepts the pinned
manifest and a numeric task. Run standalone scripts in fresh processes; use `--help`.
`export_candidate` permits only declared trainable coordinates and writes the full
checkpoint; unchanged coordinates and every buffer remain fixed. Hashes bind bytes,
not a person's authority. `bounded_process.py` is a reusable Linux child runner.

The retained raw N8 parent passed four tests: complete 12 ticks versus cold 5+7,
logits, features and all five state tensors, plus identity/edit/input refusals.
The test source and exact root receipt are in the next review stage. The formal
ScaledReadout path is implemented but was not covered by these raw N8 checks.
There is no dependency on sensitivity/trial modules and no production adoption.
`PARENT_PROFILE.bytes.json` preserves the original manifest bytes and their hash.
