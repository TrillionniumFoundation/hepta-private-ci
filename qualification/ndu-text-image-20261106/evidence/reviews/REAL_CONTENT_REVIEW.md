# Independent review of the retained NDU text/image evidence

Review snapshot: 2026-11-07T00:22:45Z. This is a read-only source and evidence
review. No model was instantiated, no forward/backward pass or optimization was
executed, and no original experiment was repeated. The reviewer previously wrote
the scoped saturation fix; the numerical section below is a fresh integration
and receipt check, not an external scientific replication of that fix.

## Decision

The retained artifacts are internally consistent with the narrow reported
result: **a frozen real image/text encoder and real language decoder propagated
loss gradients into two named pooled content slots and either the ordinary or
Hepta core, and one bridge update per core was saved and read back in the same
process**. The reported `PASS_SCOPED_REAL_CONTENT_GRADIENT` is supportable at this
scope. It must not be promoted to a task-quality, STOP, controller, deployment,
Hepta-increment, native-owner, or complete factorial result.

The original source bundle remains the authority for this execution. Two state
and material files have changed after the run. Their later fixes require their
own source-bound contract evidence; they must not be relabelled as the code used
by this model run. **This review does not request a model rerun.** Preserve the
original execution, source bundle and supervisor without modification.

## 1. Execution and source identity

Reviewed inputs are `scripts/ndu_portfolio/real_content.py`, the files under
`qualification/ndu-text-image-20261106/evidence/real-content/`, the original
`real-content-source-bundle.json`, and `run_remote_probe.py`.

| Item | Verified identity or result |
| --- | --- |
| Original source bundle SHA-256 | `12241add5ffcb665c054db6ec5bc7012bad278fab171ed7175a7d14a8ab32462` |
| Supervisor SHA-256 | `de0969a1136ecd990fe706106754a0238d5864561f41fb14a67d49985132f514` |
| Executed `real_content.py` SHA-256 | `644fc070820a0cada57a10f721c947058b32b01bdba628bf136a4850e1ef9fbf` |
| Executed Hepta core SHA-256 | `54c2e9724f6cb924582451bea907d671fe510963879117dd5f00cf4e95f1e978` |
| `EXECUTION.json` SHA-256 | `43b83e8f275f1233374d3415ed0cded7d58316527dba5695f5ad82373cc2512a` |
| `probe/terminal.json` SHA-256 | `49afe24170351341c9772d66392ef30e022e533ad4e92457fcd56607146b79d6` |
| Retained runtime job | `1a1b3568d31-fc05-8235` |
| Retained launch nonce | `a6e6b34f02cf02d259a4a87287e11505` |

All nine source bundle members have matching content length, bundle hash field,
and `SOURCE_MANIFEST.json` entry. Every source-before/source-after map in the
supervisor and both stage receipts equals that original nine-file map. Both
stages exited zero. The retained runtime status reports succeeded, exit zero,
terminal publication confirmed, complete durable output, no timeout, and
`automatic_retry=false`. This identifies the retained attempt; it does not
establish a global absence of every other job on the host.

The current `real_content.py` and core still match the executed bytes. At the
review snapshot the following post-run differences exist:

| File | Executed SHA-256 | Current SHA-256 at review |
| --- | --- | --- |
| `scripts/ndu_semantic_state/state.py` | `d02c89bff8d506fd006613da5638bc14aaa0604006961caa812b567b3d619058` | `c60bce8e28884243599299e8f95e10b4d978b212951ff46942fde4fbf250c0eb` |
| `scripts/ndu_semantic_state/materials.py` | `d8fd69e6e56436a18408c2adf8a04387067507c4fe2cae60f7a437787500fa49` | `174fc08fa6c86cbc48dc44b774d40230f75ee9194c071c0a4a90e4262139697c` |

The observed changes harden state construction/immutability/prefix validation and
material source/case/history binding. They are not edits to the saved model
results. The source manifest must retain its original hashes. Archive the full
original bundle and supervisor with the published evidence so the executed
versions remain available after later repository edits.

## 2. Real model and gradient claims

The executed source pins the acquisition manifest before reading its entries,
checks every listed file, pins the safetensors digest, and checks the same model
and image identity after the run. The source and terminal receipt agree on:

- Model: `HuggingFaceTB/SmolVLM2-256M-Video-Instruct`.
- Revision: `067788b187b95ebe7b2e040b3e4299e342e5b8fd`.
- Acquisition manifest SHA-256:
  `432a086810f32ba90ef34dc210fcb2f0f56fe8b27595266725d1846b5dad0e6c`.
- Weight SHA-256:
  `dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2`.
- Disclosed development image SHA-256:
  `8b21ba78250f852ca5990063866b1ace6432521d0251bde7f8de783b22c99a6d`.
- CPU float32, torch `2.8.0+cpu`, transformers `4.57.3`, and 13 verified model
  files as reported by the executed verifier.

The reviewer did not independently download or rehash the large model weights;
this check binds the executed verification logic and its retained result. The
fused tensor is recorded as `[1, 90, 576]`, and visual features as `[1, 64, 576]`.
The image and text inputs are encoded before the loss target is constructed.
`TARGET="bee"` enters only the first-next-token cross-entropy; the recorded target
token list is `[20728]`. No target is supplied to the public-content encoder.

The source keeps the bridge, named slot tensors and decoder input perturbation
in one autograd graph. `features_torch` detaches only validation snapshots and
concatenates the live graph tensors. The decoder parameters are frozen, while
the decoder loss forward runs with gradients enabled. The terminal records and
source checks agree that all 28 trainable bridge tensors were connected and
finite, and both named slot gradients and the shared-state gradient were nonzero.

| Engineering observation | Ordinary core | Hepta dual core |
| --- | ---: | ---: |
| Trainable bridge parameters, including the core | 61,472 | 61,472 |
| Trainable tensors with finite connected gradients | 28/28 | 28/28 |
| Sum of individual core-parameter gradient norms | 0.1900954629595617 | 0.19432998049751404 |
| Frozen bridge, three-step token CE | 11.438033103942871 | 11.43957805633545 |
| After one bridge update, token CE | 11.436823844909668 | 11.438328742980957 |
| Frozen decoder accumulated parameter gradients | No | No |

Both arms have the same initial bridge parameter hash:
`af62df30be4bac7110a8215a0f9a73060a4ca06f549825eef4fe5fee9b548492`.
The code copies that exact state into the second arm and verifies equal counts
and initial hashes. The zero-step bridge CE is correctly named
`bridge_zero_step_token_ce`; it is not the CE of the unmodified initial decoder.

The numerical CE decreases are same-image optimization observations. They are
not independently evaluated content gains. The real initial decoded text is
`The insect shown on the flower is a`, a truncated response under the eight-token
cap, not the requested one-word answer. The retained text file and its hash match
the terminal receipt. No post-update natural-language answer is decoded or
independently judged in this experiment.

The word `joint` in these local report fields refers to one update of the content
bridge and core through a frozen real decoder. It does not mean the VLM encoder,
decoder, NDU controller and all multimodal generators were jointly trained.
There is no image-output decoder in this execution. The two content slots are
pooled modality latents, explicitly not full token or spatial addressing.

## 3. Checkpoint identity and actual scope

The binary checkpoint hashes match their terminal entries. An independent,
strict-whitelist parse of the ZIP/pickle metadata and NumPy tensor storage bytes
recomputed each parameter hash, counted 28 float32 tensors and 61,472 values,
checked all values finite, and matched tensor names to the gradient records.
No Torch model, forward pass, or checkpoint replay was executed by this review.

| Checkpoint | File SHA-256 | Recomputed parameter SHA-256 |
| --- | --- | --- |
| `probe/ordinary.pt` | `28f4359dca318c4d5f5752060bbc705dcf039276f44e2a5533511ebc6b97ed85` | `0cfd9b204b8a288d26c2885568ba1bfb72574fae269f6e5a05ccf3133f70c1a5` |
| `probe/dual.pt` | `6be5d8c9f0f73cccd6542af7cddb4dc12b81451658aa171261d4b37250cfcbd4` | `a83ebf729f53a8afe047b6efe928b7f56ac0802bdec043d29f224fe3f838f48c` |

The executed code verifies changed parameter bytes, saves only the bridge
`state_dict`, reloads with `weights_only=True`, recomputes from the same frozen
inputs, and requires exact logits plus parameter-hash agreement. That supports
`weights_only_same_process_recomputation`. It does not restore a live recurrent
state, optimizer state, native owner, or a cold process. The terminal fields
correctly say `cold_process_replay=false` and `runtime_state_restored=false`.

## 4. Cost and resource boundaries

The supervisor reports 0.749446 child CPU seconds for the three Torch contract
tests and 9.804742 child CPU seconds for the real-content probe, totaling
10.554188 child CPU seconds. Its two-stage window is 8.443446503020823 wall
seconds. The real-content child alone has 7.72618767991662 measured wall seconds.
The probe reports peak process RSS of 1,468,584 KiB, or 1,503,830,016 bytes.

The probe's internal envelope, 9.317475975999999 CPU seconds and
7.209729712922126 wall seconds, excludes its startup receipt and final write/exit.
It is nested inside the supervisor's whole-child measurement. Per-stage costs
must not be added to either envelope. The state metadata clock and budget are
explicitly logical core time and remaining update count; they are not these
physical resource meters.

The audited supervisor sets child `RLIMIT_CPU=(180,181)` and a 240-second timeout
for the real probe. Its two-thread environment and probe setting are visible.
The constants `cpu_quota_percent=200` and `memory_max_bytes=12 GiB` in its
preflight declaration do not themselves enforce a cgroup quota or memory limit.
The supplied runtime status has no effective cgroup-limit fields. Actual CPU
quota and MemoryMax enforcement therefore cannot be independently certified
from this review set. Retain the existing launch/effective-limit receipt if
available; otherwise describe those two limits as unverified here. This is a
receipt-scope gap, not a reason to rerun the model.

Energy, tool dispatch, transfer, prior acquisition and complete research cost are
not measured here. These timings are not matched deployment-efficiency evidence
and cannot justify an external net-benefit claim.

## 5. Numerical saturation fix

The numerical subsection is accurately scoped. The unchanged five-file source
identities in the passed-after receipt match the current integrated numerical
files. Raw stdout/stderr hashes match their receipts for both attempts. The same
five new tests ran against the fixed original #4875 implementation and the fix.

- Original: 11 original core tests passed; the complete 16-method invocation
  ended with four error subtests in three new methods, exit 1.
- Fixed: all 16 methods passed, including the original 11 and five additions,
  exit 0. Source-before equals source-after in both runs.
- The retained errors demonstrate division by a zero softmax probability at
  small positive risk and invalid normalization when a zero-mass branch poisons
  the exponential shift at high risk.
- The implementation uses positive joint support, log-space normalization and
  algebraic cancellation of the probability division. It adds no probability
  floor and does not change `core.py` or the objective.

The reference checks include independent forward finite differences, finite
gradients, risk-neutral behavior and deterministic/zero-support cases at the
registered values. They are not a theorem covering arbitrary floating-point
configurations, not a numerical check of the complete real VLM gradient, and not
evidence of Hepta efficacy or full repository CI. The README and SUMMARY retain
these limitations. Its statement that no real-model experiment was started is
local to this numerical test invocation, not a claim about the separate canary.

## 6. Claims that remain unavailable

| Claim | Evidence status |
| --- | --- |
| Exact source-bound real decoder-to-content/core gradient connection | Supported for this original canary source bundle |
| One bridge update and same-process weight readback per core | Supported |
| Initial STOP through an execution owner | `NOT_EXECUTED` |
| Light or NDU control policy execution | False for both arms |
| Complete core/controller 2x2 and frozen/joint scientific experiment | Not executed |
| Independent semantic quality, old ability retention or generalization | Not evaluated |
| Strong deployable comparator or complete external net benefit | Not established |
| Hepta independent contribution or the scientific D-B contrast | Not established; there are no NDU B/D controller arms |
| Native Cell journal, authority, delivery, LedgerWriter or adoption | Not executed |
| Cold process or live-state recovery | Not executed |
| Image generation, audio or video qualification | Not executed |
| Latest post-run state/material revisions qualified by this model run | Not established; preserve the original run separately |

The terminal report explicitly keeps the relevant false, null, NOT_EVALUATED
and NOT_EXECUTED fields. A repository summary or PR must carry them forward.
The physical runtime job owner is not a substitute for #4944's authenticated
Cell owner, generation, writer epoch, settled delivery or independent Outcome.

## Publication handoff

Preserve the original source bundle, supervisor, execution/terminal receipts,
initial text and checkpoints verbatim. Describe later state/material fixes and
their own contract-test source hashes separately. Include effective resource
limit evidence only if it was actually retained. Report the real-gradient and
numerical results at the scopes above. No source or original evidence was
modified by this review, and no model rerun is requested.
