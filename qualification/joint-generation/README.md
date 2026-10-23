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

Source and preparation checks are available. **Codex Cloud execution, final
held-out benefit, and this first goal's acceptance remain pending until that
environment actually runs the commands and retains their receipts.** Local
preparation results are not Codex Cloud receipts. Synchronous audio/video,
long-term interaction and production integration remain outside this first goal.
