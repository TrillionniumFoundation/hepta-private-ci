# Research actor continuation

The actual `ndu_real_runtime.actor` now accepts an optional `--checkpoint-dir`.
After each decision it creates an immutable `actor-checkpoint-NN.json` before
emitting the proposal. The output includes its path, SHA256 and next step. A
checkpoint records a decision; it does not confirm execution of that action.

To continue, the existing host first reconciles the previous action and obtains
the next public input. It supplies all three resume arguments, the original
operation ID, unchanged model/control arguments, and the exact next step:

```sh
python -m ndu_real_runtime.actor <unchanged actor arguments> \
  --start-step 1 --max-decisions 1 \
  --resume-checkpoint /original/actor-checkpoint-01.json \
  --expected-checkpoint-sha256 <SHA256 of exact checkpoint file bytes> \
  --expected-continuation-sha256 <canonical SHA256 of first next public input>
```

The continuation digest uses the existing `metering.canonical_sha` JSON rule.
The first stdin item must match it. `--checkpoint-dir` can also be supplied on
resume to retain further checkpoints. The host prepares the directory; files
are create-only. Existing files, partial attempts and uncertain acknowledgements
are never overwritten or silently resubmitted.

## Bound state and failure behavior

The 128-KiB codec binds operation, case, exact weight bytes and loaded parameter
schema, Python source pins, controller and complete control/deployment profiles,
memory mode, state dimensions, four FP32 CPU state channels, Torch CPU RNG, prior
public input, proposed action, step and OCR feature pins. Controller sampling is
derived from the pinned plan seed, action and step. Unknown fields, duplicate
fields, nonfinite/misshaped state, wrong identity, terminal checkpoints, changed
delivery and budget refills are rejected. Persistent `--start-step` without the
complete validated checkpoint remains rejected.

Checkpoint mode requires explicit `--tessdata-dir` and `--ocr-library-dir`.
It pins the OCR executable, English traineddata and configured library-tree
bytes. A cold process reconstructs the OCR cache, meters that work, and checks
reconstructed feature digests for previously seen images. Full system library
and build provenance still belong to the runtime release manifest. The host
must keep the source/runtime snapshot fixed; disk hashes do not attest already
loaded Python code against concurrent replacement.

This adapter does not install a model, authenticate a learning owner, publish a
CURRENT or journal receipt, migrate state between models, carry state between
tasks, or establish trainer/evaluator independence. The existing owner retains
these duties and must charge downtime, startup and recovery to the original
budget. The codec checks that the supplied remaining budget does not increase;
it does not independently reconstruct elapsed wall time.

## Observed qualification

Six Torch mechanism tests cover tensor/RNG continuation, identity changes,
malformed state, terminal/link rejection, public delivery/budget consistency,
and separate actor processes. Synthetic OCR and weights in those tests are
explicit fixtures. Native ai395 job `1a1ba6855c8-12894-1a67` passed all six; its
MCP launch acknowledgement timed out, and its original job/result was recovered
read-only without resubmission.

Native ai395 job `1a1ba6ec7d2-12894-1aa1` tested the updated test launcher plus
the real historical `s104729/hepta/joint-ndu/lr-0.003/weights.pt`, real OCR and
the public development image for `case-a58c5c9d518011a6c00d74e2`. All six tests
passed. A fixed `PREPARE_ROI` then `READ_ROI` schedule produced identical second
observations in uninterrupted and cold-resumed processes; the canonical
observation digest was
`0a68627ad45eafb6b5ac83420bbd84b4bab6e95b86dcdf3c90b07b50a61d03f3`.
The host applied the first public ROI-coordinate change. The second READ_ROI
was a proposal only; no private crop or external journal commit was fabricated.
These direct subprocesses test the actor protocol; they do not exercise the
production host's enforced isolation or independent owner lifecycle.

The complete second verification took 17.693609 seconds wall and 17.603215
seconds CPU. Resumed OCR cost 0.14918506 seconds versus zero cache-reuse encoding
in the uninterrupted second step. Runtime versions were Torch 2.9.1+cpu,
NumPy 1.26.4 and Pillow 12.0.0 on Python 3.12.16. These are engineering results
on reset-trained weights, with newly fixed public budgets of 60 then 55 seconds;
they do not establish persistent-trained deployment, equal-total-budget task
gain, scientific adoption or RSI. The original model remained FITTED_NOT_ADOPTED.
