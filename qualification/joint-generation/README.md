# Trainable joint-generation control prototype

This qualification prototype tests whether a fixed joint utility can train the
content parameters of a two-modality generator. A shared NumPy encoder emits
text/image content distributions; a trained dense decoder emits real RGB pixels.
A training-only continuation critic chooses whether a thumbnail inference should
be followed by a full-image inference. Runtime decisions never receive labels.

The task is deliberately bounded: transform a colored square/cross at a left/right
position according to three instruction words, then emit text and an 8x8 RGB image.
It is not a natural-image model, a production Hepta worker, or a general FBSDE
solver. Text/image use the same versioned envelope; audio/video are explicit
unsupported profiles rather than silently dropped inputs.

## Execute in the configured Codex Cloud environment

Select the existing `hepta-private-ci` Codex Cloud environment and the final
prototype branch. This repository script does not select or provision an environment.
Use Python 3.11+ and install the pinned qualification dependencies if missing:

```bash
cd qualification/joint-generation
python -m pip install -r requirements.txt
python cloud_run.py --out runs/codex-cloud-20261023-r1
```

The runner executes unit tests, training/validation selection, one held-out test
evaluation, and exports compatible bundles. It writes logs plus `cloud-run.json`.
A nonzero exit means the first goal has not passed; inspect `test-result.json`
before making any benefit claim. Retain failed results. Do not adjust parameters
against an opened test set or repeat it under a new directory to obtain a pass.

`plan.json` freezes seeds, data groups, model capacity, update counts, candidate
learning rates, utility profile and acceptance criteria before testing. There are
three continued-training arms: supervised, additive joint utility, and fixed-rho
entropic joint utility. Every arm computes the same tensor operations and both
utility diagnostics before applying its declared gradient combination. Base,
decoder, candidate search/validation and controller costs are reported separately;
matching adaptation MACs alone is not a claim of equal end-to-end latency.

## Mathematical and evidence boundaries

For independent content policies p(text), q(image) and externally scored decoded
outputs R, the fixed recursive profile is

`CE_rho(R) = -log E[exp(-rho R)] / rho`; `rho=0` is expectation.

The same rho at each branch obeys the entropic tower recursion. The gradient goes
through the shared encoder and content heads. Neither the utility definition nor
the observer is trained to inflate its own score. This is one recursive-utility
special case; it does not implement endogenous preference SDEs or general FBSDEs.

The observer reads generated words and learned pixels. A decoder-corruption
negative control must reduce the score. Data groups and input hashes are disjoint
between train/validation/test. Selection uses validation only; an exclusive
`test-opened.json` prevents silent re-evaluation.

The main behavior law is independent categorical sampling. Exact expected decoded
task utility and joint success are evaluated over that finite law; greedy decoding
is reported separately. Thus an improvement in sampling-law utility must not be
reported as an improvement in greedy accuracy. The data are controlled synthetic
scenes and cannot establish natural-image generalization.

Content benefit requires positive paired seed/source-group bootstrap intervals
against both continued supervised training and the additive arm, with the declared
greedy retention bound. Dynamic benefit separately requires improvement over the
same content model with random routing at the exact same forward count and critic
work. Overall benefit requires both. Report all seeds and retained failures.

## Run a trained candidate

`cloud_run.py` exports each selected model into `RUN/bundles/NAME/` as
`model.npz`, `controller.npz`, and a hash-bound `manifest.json`.
The manifest binds the utility price and behavior profile; the run checkpoint
binds the complete bundle, not only the content weights. NPZ loading rejects
unbounded advertised tensor sizes before allocation and never enables pickle.

```bash
python serve.py --bundle RUN/bundles/ndu-11-0.01 --request request.json --out NEWDIR
```

The bundle name is selected on validation; read `selection.json` rather than
assuming the example learning rate wins. A request has exactly these fields:

```json
{
  "objective_id": "scene-transform-v1",
  "run_id": "example-1",
  "image": "replace with an 8x8x3 array of finite RGB values in [0,1]",
  "instruction": {"color": "blue", "shape": "keep", "position": "left"},
  "decoding": {"mode": "sample", "seed": 42},
  "budget": {"compute_units": 100000, "output_bytes": 4096},
  "deadline_ns": "replace with time.monotonic_ns()+60000000000 on the serving host"
}
```

Instruction vocabulary is color=keep/red/green/blue, shape=keep/square/cross,
position=keep/left/right. No target label is accepted. The CLI writes actual PNG,
caption, cost and append-only checkpoint. Compute units are the declared accounting
estimate `2*model_MACs + controller_scalar_operations + decoder_estimate`, not
measured hardware FLOPs. Scalar nonlinearities and serialization have measured
latency but are not fully represented by MAC counts.

## Current status

**The broader first goal remains open for efficient total-budget evidence.**
The [follow-up](FOLLOWUP.md) records the padding-control and modality-contract
gaps, the unchanged r1 result, and the independently frozen r2 work. The new
[media adapter](MODALITY_CONTRACT.md) provides typed audio/video transport and
synchronization boundaries while keeping those generation backends unsupported.
The first six independent r2 training/validation builds exited 2. The last
complete [t6 report](runs/codex-cloud-efficient-r2-t6/REPORT.md) retains positive
content/NDU validation means but negative effective-control CPU-net benefit.
The subsequent t7 and [t8 build](runs/codex-cloud-efficient-r2-t8/REPORT.md)
exited 1 during shared preparation/admission; t8 exceeded the unchanged
10-second CPU cap at 12.274880402 seconds before any candidate completed.
The independent formal r2 test remains unopened. Its calibrated standalone
serving/reload demonstration passed without implying experimental acceptance.
The subsequent [one-shot shared timing diagnostic](runs/codex-cloud-efficient-r2-shared-timing-d2/REPORT.md)
reproduced t8's model/library bytes in 2.528 CPU seconds but did not reproduce
or explain its slowdown. That debug result does not replace the cap failure.
The subsequent [t9 build](runs/codex-cloud-efficient-r2-t9/REPORT.md) completed
under all caps with positive content/NDU validation means, but control CPU-net
benefit remained -0.002094. It is operator-allocation limited, with CPU headroom;
the core generation claim still awaits independent evidence and the stronger
dynamic gate remains failed. Its actual standalone RGB/reload smoke passed.
The [t10 folded-adaptation build](runs/codex-cloud-efficient-r2-t10/REPORT.md)
also exited 2 under all caps. It converted saved encoder work into more real
content updates (NDU 636/637/637; control 490/475/402), while the control group
became CPU-limited. Core content/NDU validation means stayed positive, but
complete control CPU-net benefit remained -0.002650. This is still a failed
readiness result, not independent first-goal acceptance. The r2 test stays shut.
The [t11 native-Adam build](runs/codex-cloud-efficient-r2-t11/REPORT.md) retained
another exit 2, with complete dynamic CPU-net -0.002637 and no cap violations.
R2's stronger dynamic claim remains open. The separately preregistered
[CORE c1 t2 confirmation](runs/codex-cloud-core-c1-t2/REPORT.md) used fresh
physical sources and useful always-full baselines. TRAIN/validation exited 0
under all complete caps; all 12 selected models actually updated their content
parameters. Its sole formal evaluation exited **1**: both contribution means
were positive, but all six required content-control/NDU confidence intervals
crossed zero. The core benefit claim is **not confirmed**. This new test is now
opened and permanently consumed; keep its markers and do not rerun or tune on
it. The earlier core t1 TRAIN-only construction failure also remains retained.
Neither this result nor report-only N-versus-S comparisons relabel r2 failures.

The saved TRAIN receipts then motivated an optional
[local finite-code PNG path](independent/OUTPUT_CODEC.md). It pays actual
decoder/codebook preparation and retains per-request sampling/JSON accounting.
All 233 independent source tests passed, including 12 new hand/native codec
tests. Existing qualification plans still use the original path; the new profile
has no measured training/allocation or content-benefit result, and bundle export
explicitly refuses that profile until serving integration is supported. No
additional formal test or AV generation is authorized at this stage.

The subsequently frozen [D1 TRAIN-only codec comparison](runs/codex-cloud-codec-training-d1/REPORT.md)
actually launched once. Its first rowwise slot exited **1** at NDU selected
validation: complete CPU 10.022472113 s exceeded the unchanged 10 s cap.
All 36 candidates and twelve selected content states are retained, but only ten
selected-service output traces were reached. Under its predeclared hard-stop
rule, the two codebook slots and final rowwise slot never launched. START and
SLOT-0 are consumed: do not resume or relaunch D1. There is **no measured codec
speed, allocation or content effect**. The 249 integrated engine tests and eight
isolated diagnostic tests passed before that real budget failure; test success
cannot replace it. No new formal test opened. The saved TRAIN-only
[H1 dynamic headroom analysis](runs/codex-cloud-dynamic-train-headroom-h1/REPORT.md)
identifies conditional oracle allowance but lacks direct NC/full service and
static NDU TRAIN content terms. Dynamic superiority remains unconfirmed.

The separately frozen [H2 TRAIN collection](runs/codex-cloud-dynamic-train-headroom-h2/REPORT.md)
then exited **1 before any data/model/measurement** because a WorkLedger label
contained an invalid ampersand. Its fixed START remains consumed; all 36 service
calls are unexecuted and no headroom result exists. The one-line label correction
and production-constructor regression are retained, without rerunning H2. A
[technical recovery draft](training_diagnostics/dynamic-h2/TECHNICAL_RECOVERY_DRAFT.md)
requires explicit amendment of that once-only rule and preservation of prior
startup cost before the unexecuted collection can proceed. No core/dynamic
acceptance or model-family impossibility follows from this startup error.

**The first configured Codex Cloud execution passed the frozen finite-scene
acceptance on 2026-10-23**, using source commit
`57d2c7aa5880dd761b4c43f79d0f6f16b26b72e7`. The exact runner exited 0; all 30
cloud unit tests passed. All three seeds were retained, both content-comparison
confidence intervals and same-content matched-random dynamic intervals passed,
decoder corruption reduced utility, and budget violations were zero. All nine
selected encoders and both content heads changed from their shared bases.

See the [execution report](runs/codex-cloud-20261023-r1/REPORT.md) for complete
receipts, lifecycle costs, confidence intervals, exported bundles, and an external
RGB serving/reload demonstration. These results concern the finite sampling law;
they do not establish greedy accuracy improvement or equal hardware latency.
GitHub API identity/PR queries returned `Forbidden`; Git branch transport worked,
and those access failures remain recorded.

**The held-out split is now opened. Do not rerun the runner/evaluator or use a new
directory to repeat it.** Keep the exclusive marker and all results. Synchronous
audio/video, long-term interaction, natural images and production integration
remain outside this first goal and need separately frozen experiments.
