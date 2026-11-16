# E2 finite JSON artifact environment

`interaction.py` measures real model generation and a bounded local artifact
effect. Model output is parsed as one JSON object, written to an attempt-specific
file, read back, and checked with the registered semantic verifier. Model fields
never select paths, commands, imports or executable code. Invalid JSON changes no
artifact state. This environment does not claim arbitrary coding-agent execution.

## API

```python
collect(train_records, parent_manifest, artifact_root, out, max_steps=2)
evaluate(manifest, artifact_root, records, out, max_steps=2)
```

The output directory must be new. The parent/model identity is checked against the
actual loaded predictor and each generation. A loader, budget, identity, write or
inference error produces `FAILED.json` with `INCOMPLETE`, preserves earlier
originals, and raises. It never converts unfinished work into a completed failure
score. There is no automatic retry or existing-output overwrite.

`collect` accepts authorized training records only and writes three SFT JSONL files:

| Arm | Source of supervision and actual effects |
| --- | --- |
| `demonstration` | Fixed deterministic reference, independently verified; zero student generation calls. |
| `shadow` | One actual student generation on the original state, scored but not applied; deterministic reference supervises that original state. |
| `controlled` | Student JSON is actually applied and checked; failure feedback produces the next model input. Reference corrections supervise the states the student actually visited. |

The reference provider is explicitly `deterministic_reference`, with its source
hash and measured call receipt. `teacher_id` stays null; no external LLM or new
user is invented. All derived records retain task, source, lineage and family
identities, `curated_development`, and `development`. Failed student outputs are
retained as masked observations, not trained as successful action targets. Full
action/effect originals remain in the separate step receipts.

All arms reserve the same maximum student-call allowance per task. Actual use is
reported, including the demonstration arm's zero calls; it is not falsely reported
as identical actual compute. Reference calls are not student model calls. Training
steps/tokens and model evaluation quotas must also be frozen by the caller. The
same source producing more correction records does not create more users or
independent tasks.

`evaluate` accepts selection/confirmation records. Only task input and the model's
own previous artifact/output are sent to the predictor. On failure the environment
returns only `parse_ok` and `semantic_ok` booleans. Expected output, final-answer
labels, verifier parameters, reference corrections and full verifier internals
never enter model context. Evaluation never calls the deterministic oracle.

## Original evidence and limits

Each attempt retains the exact input, raw generation, policy digest, input/output
token counts, generation wall time, state before/after, actual artifact bytes,
readback verification, semantic receipt, and complete step timing. Each task stops
on semantic success or the frozen maximum; unused calls are explicit. Invalid
JSON is a completed attempt with no artifact effect, while interrupted inference
is incomplete work. Model load and total collection/evaluation time are accounted
separately from measured generation time.

This implementation closes a limited environment-execution distinction. It does
not supply independent user trajectories or authenticated external teachers.
`independent_e2=BLOCKED` and `production_eligible=false` remain explicit. Unit tests
use fake predictors solely to verify isolation, feedback, failure semantics and
budget handling; they are not LLM learning evidence.
