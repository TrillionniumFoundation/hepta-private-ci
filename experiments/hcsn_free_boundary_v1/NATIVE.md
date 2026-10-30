# Causal continuous channels in the original native owner

## Delivered behavior

This package restores and executes the unchanged Linux research host from
`continuous_boundary_flow` / PR #4157. Four declared continuous signals now have
an actual action path through the original sparse kernel and NDU: internal
continuation value, natural margin, predicted task risk and event activity.
The HCSN tensor recurrence remains in PyTorch. No Rust authority, top-k guard,
calibration rule, journal contract or native algorithm is modified.

The previous study002 transport compiled a precomputed score into the only
winning native coordinates; its margin/risk/activity coordinates could not
affect action selection. The new `causal_maxout` profile gives every signal a
potentially winning coordinate and nonzero keep-head coefficient:

| Native coordinate | Encoded value | Keep-head coefficient |
| --- | --- | ---: |
| 0 | `0.5 + continuation` | +1 |
| 1 | `0.5 - continuation` | -1 |
| 2 | `0.5 + margin` | +1 |
| 3 | `risk` | -1 |
| 4 | `activity` | +1 |

The keep bias is -0.55; repair has fixed score -8; STOP/abstain is exactly zero.
The original width-five/top-k-one rule selects at most 20% active coordinates.
Zero transport recurrence rates are explicit: the upstream tensor model owns
the dynamics. This is a hand-specified controller, not a newly trained native
sparse head or a solved task-optimal policy.

Two controls receive the same four typed inputs. `ordinary_affine` compiles
`continuation + .35*margin - .75*risk + .25*activity - .05` through the actual
native kernel and NDU. `continuation_only` compiles `continuation - .05` and is
explicitly a channel ablation. Neither control is fitted on evaluation outcomes.
These profiles and their numerical coefficients are written before evaluation.

## Immutable native provenance

| Identity | Value |
| --- | --- |
| Original native source | `5898cd8b0f724c3152b6cc52856721f72e5e08be` |
| Research wrapper commit | `7bec42aa4f79432f4a724d5295c67f9d69ee5a8d` |
| Archive source commit | `68eb16caa9c14c7b5729585c86d9c293018a987c` |
| Executable SHA-256 | `1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5` |
| Native source-manifest SHA-256 | `6addea031fa9ba2ca403137d8d10da6088c255474c681b106d9a2706c645dd09` |
| Unchanged adapter SHA-256 | `2a7be4914211a5166fc8ef7fbbf6a2de8632b2e7651c7175d6e3888ddbb1ec0c` |

`native_vendor/` preserves the two original gzip-stream parts, original manifest,
build receipt and adapter. Parts are 400,000 and 180,191 bytes; the restored
executable is 1,306,448 bytes. Restoration verifies every part, concatenated
compressed stream and final executable. It refuses a conflicting destination
or symbolic link. Every native launch checks the executable and runtime-reported
source and manifest identities. Original owner authority remains `DENY_ALL`.

The original native sources were unchanged in the upstream research build;
generated manifests omitted test-only dependencies and linked the original NDU
crate. That earlier build is not rerun or relabeled as a full daemon build here.
The recovered executable is Linux x86_64-specific. Runtime consumption retains
the original finite-domain calibration fixture; it is not task-quality or
probabilistic safety certification.

## Matched-state intervention result

`results/native001/` is the executed engineering validation. One real native
prefix is committed, closed and copied byte-for-byte into eight new experiment
roots. Each branch starts a new process and resumes the same case, seed, model,
profile, journal, witness, event ledger and checkpoint. The paired variants
change exactly one feature. All eight resumed frontiers match the prefix.

| Changed channel | Variant actions | Actual paid reads, including prefix | Paid read costs |
| --- | --- | --- | --- |
| Continuation | STOP / KEEP | 2 / 3 | 0.04 / 0.06 |
| Margin | STOP / KEEP | 2 / 3 | 0.04 / 0.06 |
| Risk | KEEP / STOP | 3 / 2 | 0.06 / 0.04 |
| Activity | STOP / KEEP | 2 / 3 | 0.04 / 0.06 |

First action divergence occurs at tick two. A KEEP causes the next source read
and native update to execute; STOP prevents that read. All eight exact retry
checks return the original acknowledgement without an additional transition.
All eight post-STOP probes are rejected with unchanged native frontiers.
A separate uninterrupted versus cold process run reproduces numerical states,
checkpoints, NDU decisions and actions exactly. Native process CPU, request/
response bytes, actual kernels/NDU calls, replay work and journal storage remain
in each original receipt. Source identities are pinned in the run directory.

These are deliberately constructed causal API witnesses. They show that the
four channels can change legal executed behavior. They do not establish that
the hand-specified policy has higher utility on natural data or that the new
neuron is superior to an ordinary architecture.

## Trained-model live execution

`run_native_live.run_live` takes a trained `HCSNClassifier`, heldout `x`, `dt`,
labels, read prices and optional public context. For every policy and episode,
it calls `model.step` once, constructs signals from the resulting causal state,
obtains the actual native action and stops the tensor loop immediately at STOP.
No later tensor step is computed for that episode. All policies receive the same
checkpoint, source sequence, public context and input fields.

Signal meanings are explicit:

| Field | Live mapping | Interpretation |
| --- | --- | --- |
| continuation | `tanh(mean(aux.continuation))` | Internal regenerative-cell value, not the classification Bellman value |
| margin | `tanh(mean(aux.margin))` | Natural boundary minus pressure |
| risk | `1 - max(softmax(logits))` | Model error estimate, without a safety-calibration claim |
| activity | `mean(aux.event_probability)` | Interval first-passage mass, not a hazard or spike count |

External utility is correctness minus every actually purchased input, including
the first. Internal learned `K` and expected event cost are not relabeled as
owner resource expenditure. Model CPU/wall time and exact native-child CPU are
reported separately; neither is energy. Parent time contains its own model and
transport work, so nested times must not be added twice.

If the first episode of a policy continues after its first observation, the
runner's optional recovery check writes model weights,
actual recurrent tensors, input identity and task cursor. It closes the native
process, instantiates a fresh neural model, restores the state, launches a new
native process and resumes the durable owner before the next observation. The
controlling Python interpreter is not restarted. Reaching a finite input horizon
without native STOP is retained as `finite_horizon`, not falsely reported as an
owner stop.

`run_native --traces` is a separate adapter for precomputed causal-prefix outputs.
It verifies real native consumption and paid-prefix counts but cannot claim to
save tensor computation already performed during trace creation. It requires
schema `hcsn-native-prefix-traces.v1`, explicit `split=heldout`, model SHA-256 and
all episodes; no result-dependent subset is selected.

## Reproduce

From the repository root, with the study's Python dependencies available:

```sh
python -m experiments.hcsn_free_boundary_v1.restore_native /tmp/hcsn-native/continuous_host
python -m unittest experiments.hcsn_free_boundary_v1.native_tests -v
python -m experiments.hcsn_free_boundary_v1.run_native --output /tmp/hcsn-native-recheck
```

Use a fresh output directory. The three focused native tests exercise malformed
signals and stale frontiers without state advancement, Q24 tie/positive-ULP
behavior, and equality of actual tensor updates to real owner ticks. The live
API test uses an explicitly untrained fixture and is not a training result.

Live use from the training runner:

```python
from experiments.hcsn_free_boundary_v1.run_native_live import run_live
result = run_live(
    trained_model, heldout_x, heldout_dt, heldout_labels, read_prices,
    output_directory, context=public_context, provenance=dataset_and_checkpoint_receipt,
)
```

## Predeclared trained-checkpoint study

`live_study.py` implements `PROTOCOL.json.native_evaluation`. It requires a
completed training directory containing the locked validation selection,
numeric selected checkpoint, full two-learning-rate search receipt, and a source
freeze. It verifies their hashes and the model, seed, data, and search budget
before opening the first 32 test episodes. Model or controller selection from
these episodes is not performed.

For each of the three declared read prices, the driver separately executes all
three native policies and the `read_all`, `fixed8`, `fixed16`, and `fixed24`
references. The references call the same trained model one observation at a
time; they do not reuse a precomputed prefix trace. Their fixed stopping rule
does not invoke the native owner. Native policies pay for native durability,
transport, guards, and terminal checks as actually executed. The read-price
variable is an accounting input, not a feature consumed by these controllers;
the driver checks that their actions and correctness remain invariant across
price scenarios.

The main cohort runs without deliberate restarts. A separate first-episode run
exercises the optional recovery mechanism. The cost grid amortizes its complete
verification execution once over the declared number of hypothetical episodes.
That charge includes repeated prefix/suffix inference and native replay; it is
explicitly a recovery-verification charge, not a pure restart-time estimate.
If a policy stops at the first observation, its recovery count remains zero.
True neural recovery across a new Python interpreter is a separate scaling
experiment.

The driver retains actual model CPU, per-policy Python CPU, exact native-child
CPU from `wait4`, owner/kernel/NDU counts, read counts, and correctness. CPU
scenario utility uses full per-policy Python plus native-child execution CPU,
the complete two-LR search CPU including the unselected candidate, and the
separate recovery-verification charge. Model CPU is a subset of Python CPU and
is not added a second time. The grid's CPU prices and amortization populations
are hypothetical utility conversions, not observed money, joules, or deployment
performance.

```sh
python -m experiments.hcsn_free_boundary_v1.live_study \
  --training-run PATH_TO_COMPLETED_MNIST_FREE_DUAL_SEED9101 \
  --data experiments/hcsn_free_boundary_v1/data/study001/mnist.npz \
  --source-freeze PATH_TO_SOURCE_FREEZE_JSON \
  --output experiments/hcsn_free_boundary_v1/results/native002
```

Every output directory is new. Failures retain partial journals, results, and a
failure receipt rather than overwriting a previous outcome. The 32-episode
cohort is descriptive; the checkpoint was trained for final-query prediction,
and early-prefix confidence is not claimed to be calibrated for optimal
stopping. `results/native001` remains a separate four-channel intervention
witness and must not be pooled with this task-utility cohort.

`live_study_tests.py` exercises the native driver and cost arithmetic on a
clearly labeled untrained synthetic fixture. Its saved development receipts are
not native002 results.
