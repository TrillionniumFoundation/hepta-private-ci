# Hepta Neuron E0–E4: execution evidence gate (qualification only)

This directory contains a **no-authority** POSIX host measurement collector and an execution-matrix validator. It does not train DecisionCells, dispatch models, approve topology changes, evaluate task outcomes, or establish production readiness. It is an **experimental execution overlay** aligned with the existing [adaptive experiment registry](../../docs/learning/EXPERIMENTS.json), [neural biomimicry specification](../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md), and [causal/longitudinal evaluation specification](../../docs/learning/CAUSAL_LONGITUDINAL_SPEC.md). Its E0–E4 stage arm names are local trial labels, **not** newly accepted canonical experiment IDs or proof that the registry was programmatically consumed.

## Stage mapping

| Stage | Frozen comparison arms | Real evidence still required |
| --- | --- | --- |
| E0 | `no_change` | Real selected encoder/tokenizer/head, Q24 neuron consumer, actual task outcomes, complete CPU/RSS/GPU and request latency |
| E1 | `multi_head`, `fixed_moe`, `dynamic_moe`, `cell_graph` | Matched unique/trainable parameters, data, budgets, active compute and route/loop observations |
| E2 | `no_change`, `continue_training`, `wider_head`, `split`, `merge`, `distill` | Real artifact CAS/migration/cutover/fences; signed independent future-time utility and negative transfer |
| E3 | `fixed_circuit`, `adaptive_circuit`, `cell_ablation` | Held-out task families, compositional success, real cost and failures |
| E4 | `64`, `256`, `1024`, `4096` | Concurrency sweeps, true process-tree RSS, GPU, power, request-level p95/p99, microbatch throughput and crash recovery |

**Precedence:** E1 requires E0 accepted by an independent owner; E2 requires E1 and real lifecycle receipts; E3 requires E2; E4 only after the previous stages satisfy their scientific and resource gates. This tool does not attest those dependencies. A complete arm matrix is merely an *execution inventory*, not efficacy evidence.

## On a named target host

1. Create a *private, untracked* `manifest.json`. For **E0**, it requires the following shape (paths here are illustrative and **must point to actual, nonempty on-host files**):

   ```json
   {
     "shared": {
       "encoder": "/secure/actual-encoder-weights",
       "tokenizer": "/secure/actual-tokenizer",
       "dataset": "/secure/frozen-requests-and-split",
       "objective": "/secure/frozen-objective",
       "runtime": "/secure/runtime-build-or-configuration"
     },
     "arms": {"no_change": "/secure/selected-head-or-adapter-weights"},
     "commands": {
       "no_change": ["/path/to/qualified-neuron-runner", "--manifest=/secure/actual-model-manifest", "--benchmark-workload", "/secure/frozen-requests-and-split"]
     },
     "e0_model": {
       "model_manifest": "/secure/actual-model-manifest",
       "preprocessor": "/secure/actual-preprocessor",
       "quantization": "/secure/actual-quantization-profile",
       "normalizer": "/secure/actual-normalization-profile",
       "calibration": "/secure/actual-calibration",
       "device_manifest": "/secure/actual-device-observation",
       "license_sbom": "/secure/actual-license-and-sbom"
     }
   }
   ```

   For E1–E4, use exactly `shared`, `arms` and `commands`. All registered arms must have an on-disk candidate and an exact, non-shell command list. The tooling pins executable bytes, argv, and file arguments that already exist at freeze time. The same command is required for every trial within an arm. Runtime-loaded files or network models not represented by frozen paths require additional external owner evidence. **A file labeled "model" is not proof it contains a real model.** Never include credentials in command arguments or store private inputs in Git.

2. Freeze the exact source commit/tree, host, selected performance environment (CPU thread settings and GPU visibility), artifacts, commands and trial counts *before* observing holdout outcomes:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py freeze \
     --stage E0 --repetitions 1 \
     --manifest /secure/manifest.json --out /secure/e0-plan.json
   ```

   Submit that plan digest to a separate independent evaluator/immutable registry. A local digest is **not** an authenticated plan registration. Pilot plans from experimental schema v1 are not reinterpreted as v2; refreeze a new plan. After the in-flight/post-run evidence fix, **plan v2** remains stable but run/audit receipts intentionally advance to **v3**. Previously recorded run v2 receipts are rejected instead of being silently relabeled as verified v3; freeze a new exact-source plan and rerun under an independent external evidence owner.

3. Run the previously frozen command for each trial with no post-hoc substitution:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py run \
     --plan /secure/e0-plan.json --arm no_change --trial 0 --timeout 120 \
     --sample-group-rss --out /secure/e0-run-0.json -- \
     /path/to/qualified-neuron-runner \
     --manifest=/secure/actual-model-manifest \
     --benchmark-workload /secure/frozen-requests-and-split
   ```

   `HEPTA_NEURON_EXPERIMENT_TRIAL` is set to the frozen trial index in the child environment. For a matched arm comparison, use the same preregistered trial population, task families and budgets. Never cherry-pick fast or successful trials; retain all failed attempts in an external immutable evidence owner as well.

4. Audit **only the execution inventory**:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py audit \
     --plan /secure/e0-plan.json --receipts /secure/e0-run-0.json
   ```

   The audit rejects missing/duplicate `(arm, trial)` slots, changed commands and binaries, mismatched source/host/environment, tampered logs and failed runs. For whole-child-process wall time, it reports p50 only with at least 3 samples, p95 with at least 20 and p99 with at least 100. Those are **process-level observations including startup**, not model-internal request latency or independent experimental episodes. E4 additionally requires real concurrency and GPU/power/throughput instrumentation outside this tool.

5. The existing independent `learning.eval`, `learning.ledger`, `learning.artifacts`, Neuron, inference and model owners must supply real authenticated model load/invocation, genuine Neuron Tick/Checkpoint/CAS and external task outcomes, matched unique/trainable parameters and compute, future-time holdouts, NDU value, retention and rollback. **Nothing in this collector can issue those receipts or approve a Cell Split.**

## Existing real public-pretrained Encoder observation (NOT native E0 acceptance)

The separate, frozen research source at
[`research/shared-stem-hf-ci-conformance-20261014`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/research/shared-stem-hf-ci-conformance-20261014)
records a successful [public Encoder canary job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38513037442)
(job `115688868903`; **different source branch/check-out from this PR**). Its original
[`HF_PUBLIC_ENCODER_PROBE_20261014.json`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/research/shared-stem-hf-ci-conformance-20261014/qualification/stem-cell-v1/HF_PUBLIC_ENCODER_PROBE_20261014.json)
reports actual downloaded `answerdotai/ModernBERT-base` revision
`8949b909ec900327062f0ebf497f51aef5e6f0c8`, weight SHA-256
`340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9`,
149,655,232 full parameters, 149,014,272 feature parameters, 768-D output and
three real CPU feature forwards with repeat-input consistency and input distinction.
Those measurements concern a **public research model/checkpoint on a hosted runner**.
They do not demonstrate a selected Hepta model, an authorized local Worker,
`InferenceControlModelPort`, a committed Q24 `NeuronTickReceiptV1`/checkpoint
with independent witness, external task utility, FLOPs completeness or target-device
capacity. Reuse the pinned research observation as provenance and rerun only the
missing physical/causal comparisons rather than presenting a new dummy Encoder.

For actual E0 completion, independently authorized model/Artifact and inference
owners must bind verified loaded tensor bytes and observed invocation to the *same*
frozen input/model tuple, then the existing Neuron owner must commit that
observation through durable Q24 journal and independent CAS witness, and an
independent task-outcome owner must provide genuine results. Signed original
receipts and current revocation/fence status are required; this Python tool
does not issue, verify, or substitute them. `execution_matrix_complete` does
not become E0 acceptance even if every native process exits successfully.

## Limitations and refusal semantics

- `run` executes a **caller-explicit trusted native command** (not a sandbox) and records observed process wall time, direct-child CPU/RSS via POSIX `wait4`, an executable digest checked before and after, and raw stdout/stderr SHA-256. After the child exits, it **rechecks the full frozen Git source/inputs/model/argument-file identity**, not only the binary. It also fails and kills leftover members of its isolated process group when the direct child reports success but helpers remain (`unsettled_descendants`). Timeout/output-budget overruns kill the process group as well. Both checks are bounded endpoint observations: a file altered and restored mid-run or a helper that escapes into a different process group remains undetected. Model/provider access, token accounting and worker identity must be authenticated by existing owners.
- Optional `--sample-group-rss` measures a **Linux procfs sample lower bound** over visible processes with the child's process group ID, at approximately 100 ms intervals. It can miss short peaks, inaccessible processes, processes that change groups, or workloads launched in external services. It adds sampling overhead. Do not substitute it for full process-tree peak or GPU memory measurement.
- GPU, power, model-internal inference p95/p99, FLOPs, throughput, parameter counts, effect outcomes, and scientifically matched task/compute budgets remain **unmeasured by this collector**. A complete arm matrix is not E0/E1/E2/E3/E4 acceptance.
- Local plan/run SHA-256 digests detect unrecorded byte drift but **are not signatures or independent evidence**. A malicious writer can recompute them. Commands can import non-pinned runtime components; a loaded artifact need not be the frozen file unless the trusted inference owner provides that binding. Source weights, parameters and principal scopes are not inferred from filenames.
- The test suite uses temporary Git repositories and controllable subprocesses for **gate correctness only**, not true model training, inference efficacy or AGI performance. No experiment result from fixtures may be promoted or advertised as target-host capacity.

## Tests

```sh
python3 -m unittest discover -v -s tools/hepta-neuron-experiments -p 'test_*.py'
```

## 768-D public Encoder to Neuron V1 projection preflight

ModernBERT-base's observed output is **768-D**, while the native Neuron V1 feature contract permits at most **512 Q24 elements**. Reuse the existing shadow `qualification/stem-cell-v1/stem_projection.py` from the approved, exact-source research candidate; do not silently truncate features or rewrite the native V1 format. The additive `e0_projection_gate.py` checks only an *externally supplied* output contract: original width, projected width, Head width, actual projection-file bytes, and Q24 output range. It refuses oversize widths, wrong-length vectors, mismatched Head widths, malformed Q24 values and changed projection files.

```sh
python3 tools/hepta-neuron-experiments/e0_projection_gate.py --contract /secure/e0-projected-feature.json
```

The JSON contract must contain exactly `schema="hepta.neuron.e0-projection-preflight.v1"`, `encoder_width`, `projection_width`, `head_input_width`, absolute `projection_artifact`, its `projection_sha256`, `projected_features_q24` as a matching-length signed-Q24 integer list, `feature_source_sha256`, and `source_kind="externally_observed_not_authenticated"`. The output is **diagnostic only**, never an E0 acceptance receipt. It **does not execute** the projection, prove that the reported vector arose from the actual 768-D pretrained model, detect a deliberately substituted 256-D slice masquerading as a projection, verify an independent signature, or establish model quality. The real owner must run the pinned original projection against an authenticated Encoder output and prove Head/Worker/Neuron binding and checkpoint CAS separately.

The new eight unit tests use only a synthetic file/vector to verify rejection behavior. Their success does not count as pretrained-model, Q24-Head, or Neuron-runtime execution.

## E0 actual-f32 numerical oracle and pinned public-pretrained smoke

The additive `e0_projection_numeric.py` performs a **second, independent integer
recalculation** from actual frozen on-disk float32 big-endian features and the
**existing** `stem_projection.py` v1 shadow projection manifest format. It
validates byte-level source/weight SHA-256, declared tensor shape/rank, the
original 32-bit feature digest, deterministic round-to-nearest-even Q24
math, the full projected output, and the exact
`hepta.stem.projected-feature-bound.v1` scope/generation/input binding.
It rejects a projector without a nonzero path from any source dimension
beyond the Head input width to an output dimension, and checks artifact bytes
again after processing. This **only demonstrates numerical consistency** with
the captured bytes; it does NOT establish that the bytes were produced by an
authorized Model Worker or that the projection retains useful task information.

A separately isolated GitHub Actions job runs
`e0_public_shadow.py` **only for same-repository PR candidates**. This
runs a fresh actual pretrained CPU forward using the already proven public
`answerdotai/ModernBERT-base` revision
`8949b909ec900327062f0ebf497f51aef5e6f0c8`, checks the
original full tensor inventory via the pinned research owner source
`be511bd63aaae8813c415a116d50f01fe54baba5`, then
runs the exact existing `LowRankProjectionQ24.project_float32` implementation from
the audited source `d6f35c362289c90427bfbdffd4505d2e535c1b1b`.
The raw 768-wide float32 output is captured into a local file. An **untrained,
rank-one tail-coordinate diagnostic** projector maps 768→256 with no hidden
slice. The independent numeric oracle recalculates all outputs, and the
existing shadow `native_bridge.native_logits` runs a deterministic
256-wide diagnostic Q24 Head (matching the chosen V1 temporal-state width,
without creating a real Worker ModelPort receipt). This is an actual public-weight execution
*mechanism* test, not a trained/selected Cell or production Neuron invocation.

In a pinned full source checkout with the approved public CPU snapshot and
two exact upstream source checkouts, reproduce using:

```sh
python3 tools/hepta-neuron-experiments/e0_public_shadow.py \
  --research-root /checked-out/be511bd-source \
  --audited-root /checked-out/d6f35c-source \
  --snapshot /secure/verified-public-snapshot \
  --output /secure/new-e0-shadow-result
```

The opt-in `--acquire-public` mode downloads only from the **fixed, unauthenticated
public Hub revision** and verifies both its pinned safetensors checksum and
the full snapshot inventory before local-only feature inference. The
experiment **never uploads** original model weights or raw features as
a GitHub artifact; only a sanitized report/failure diagnosis is retained.

If the model job has not completed on the current exact SHA, it must be
reported as **queued/failed/unverified**, not as an inherited success from the
earlier public canary. Only an independent owner can subsequently authenticate
actual selected model loading, real Head training/selection, bounded Worker
reservation/final-use, Q24 Neuron checkpoint CAS and witness, and genuine
longitudinal task improvement. The numeric report flags each of these as
**false**; running it cannot approve E0/E1 or structural Cell Split.

### E0 public-source dependency-shadow hard gate

Both research checkouts are now required to match their exact pinned Git commits
**and** contain no changed tracked files **or any untracked/ignored files** before
and after model execution. The diagnostic runner disables bytecode file creation
before importing the research trees; GitHub Actions also exports
`PYTHONDONTWRITEBYTECODE=1`. This blocks injection of new `.py` files,
including `gitignore`-hidden transitive Python dependency shims, into a
nominally frozen source checkout. Module-origin assertions independently check
the direct imported HF / projection / Q24 Head modules. Existing polluted
local checkouts must be cleaned or reproduced into a fresh checkout and do
**not** pass by ignoring dirty-source evidence. These are fail-closed source
controls, **not** proof of authenticated pretrained weights, signed final use
or a durable Neuron checkpoint.

### E0 observed tail dependence: reject cancelled or Q24-rounded paths

Previously, the shadow numeric oracle counted nonzero A/B low-rank paths
from source coordinates beyond the projected Head width. That structural
condition alone admitted paths that **cancel** after aggregation or quantize
to an identical Q24 vector; it was not actual evidence against truncation.
The versioned numeric-oracle result is now `hepta.neuron.e0-projection-numeric-result.v3`.
For wide→narrow cases, it independently repeats the **full Q24 projection
arithmetic** on the same frozen input with coordinates
`[output_width, input_width)` replaced by zero, and fails closed unless the
resulting *actual Q24 vector* differs from the original. The report field
`observed_source_tail_q24_influence` is true only for that sampled pair;
it is null when no tail exists. Tests include two legitimate nonzero rank
paths that cancel to zero, an all-zero tail, and a sub-quantum float32
input, alongside the positive last-coordinate fixture. These are synthetic
mechanism tests, not real Model Worker receipts or guarantees of learned
capacity. The selected task utility of a projection still requires
independent held-out evaluation.


### E0 real-model Q24 range failure and versioned diagnostic normalization

**Actual CI failure, not a fixture:** hosted run
[38550615028](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38550615028)
job \`115807384740\` successfully installed pinned CPU Torch/Transformers,
downloaded the genuine public ModernBERT checkpoint, loaded it and reached
\`stem_projection.py.project_ref\`; the raw pretrained float32 feature
violated the existing **strict** Q24 input range \`[-8,8]\` and was rejected.
This must NOT be repaired by silent clipping, suppressing the exception,
changing Neuron V1 bounds or fabricating inference evidence.

The additive research-only \`e0_feature_normalization.py\` instead freezes a
**deterministic policy**: convert the complete raw f32 vector with the
*smallest nonnegative power-of-two right shift* that gives maximum absolute
f32 feature at most \`4.0\`. Its exponent is chosen per actual request
and explicitly recorded, not a trained or selected production normalizer.
The complete **unchanged raw 768-D encoder bytes** are retained separately
from the normalized 768-D f32 bytes, each with its own SHA-256, frozen
policy digest, scaling exponent and domain-separated raw-to-normalized
binding digest. The existing audited Q24 projector consumes only the
latter. The independent numerical oracle, under exact **trial schema v2**
and **result schema v4**, reopens both physical sources, recomputes the
minimal exponent and float32 normalization *independently*, checks the
original Stem feature digest, and only then recomputes signed Q24
projection and tail-counterfactual behavior.

The diagnostic rank-one projector now selects the strongest actually
representable source **tail** coordinate to avoid a false zero-vector
pass when one arbitrarily fixed tail coordinate happens to be small.
Both this coordinate choice and the per-request scaling are **diagnostics
only**, **not** a pre-registered fixed projection/normalizer for an E1
fair-budget or scientific comparison. Scaling can lose information
through float32 rounding, underflow or Q24 quantization; it is not
claimed mathematically reversible, task-neutral or learning-optimal.
If the source has no Q24-representable tail after scaling, the diagnostic
fails closed. Production Encoder/Head/Worker execution still needs an
independently selected, calibrated, fixed and authorized preprocessing
manifest, actual loaded-tensor receipts, final-use gates and a durable
Neuron Tick/Checkpoint with independently verified outcomes.

### Fail-closed process-group cleanup even on nonzero parent exit

The POSIX execution collector previously killed lingering same-group helper
processes when the *direct child returned zero*, but not when the direct child
returned a **nonzero exit code**. That failure receipt did correctly deny
qualification, yet a descendant could continue doing work or writing to
the log/artifact area. The owner now sends an isolated process-group kill
after reaping the direct child for **all** statuses; it continues to mark
success-with-descendants as `unsettled_descendants`, while preserving
`failed`, `timed_out` or `output_limit` as failures. A new Linux regression
runs an actual failing parent whose helper attempts a delayed filesystem
write, and rejects any surviving helper effect. A child that escapes the
isolated process group or dispatches to an independent remote service remains
outside this local process cleanup; only a real provider/Worker owner can
reconcile those external side effects.
