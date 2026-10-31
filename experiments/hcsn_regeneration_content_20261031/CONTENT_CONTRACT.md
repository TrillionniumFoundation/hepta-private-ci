# Raw sequence content experiment

## Scope and model

This is a fully trainable ordinary-gate versus renewal-flow-gate recurrent model.
It is not a trained Transformer comparison, a conventional sampled SNN comparison,
a large model, or an implementation of the He–Xiong equity/default free boundary.

The content state is the vector `h[batch,width]`. Both models use exactly the same
parameter shapes, initial arrays for a common seed, candidate dynamics, readout,
data streams, optimizer, and update count:

```
candidate = tanh(x @ Wx + h @ Wh + b)
a = x @ Gx + h @ Gh + gb
h_new = h + gate(a,dt) * (candidate - h)
logits = h_new @ Wo + bo
```

The ordinary gate is `1-exp(-dt*softplus(a))`; at `dt=1` it is sigmoid(a).
The analytic gate is `1-exp(-E[N_dt])`, with Brownian distance
`softplus(-a)+.05`, drift `-.25`, volatility `1`, reset `.8` and refractory `.15`.
`renewal.py` sums all possible repeats in that interval. This defines a
deterministic continuous renewal-flow gate. Applying a nonlinear recurrence to
this gate is not claimed to equal the expectation of a nonlinear sampled SNN.
The interval's drift/reset parameters stay fixed inside that calculation.

The distance is a width-dimensional, coordinatewise transform of the local gate
preactivation. In exact arithmetic `a=-log(expm1(distance-.05))`. It is not a
single scalar summary of the layer, and is not an invertible encoding of the
joint input and previous hidden vector. Finite precision can saturate the
transform in its tails. It is a local gate parameter, not a solved endogenous
default boundary. The separately retained `h` carries content.

## Public API

`Model(family,input_dim,width,classes,seed)` supports `initial(batch)`, pure
`step(x,h,dt=1)` returning a new hidden array, `logits(h)`, `features(h)`,
`loss_grad(sequence,label,dt)`, `save(path)` and `Model.load(path)`.
Sequence shape is `[time,batch,input_dim]`; labels are `[batch]`; dt may be
`[time,batch]`. Single-step dt can be scalar or `[batch]`. Features concatenate
hidden content and softmax logits; no true label or posterior is supplied.

Every array Wx/Wh/b/Gx/Gh/gb/Wo/bo receives hand-written full BPTT gradients and
Adam updates. No random-feature or frozen-encoder shortcut is used. An independent
central finite-difference audit checks every parameter in both tiny models at
nonuniform times, without using task held-out outcomes.

## Tasks and splits

| Task | Raw input | Label and sequence | Held-out change |
| --- | --- | --- | --- |
| associative_recall | 9-token one-hot vocabulary | 3 randomly ordered key/value pairs; 4 random distractors; query marker and key; 3-class queried value | delay 12 instead of 4 |
| multimodal_evidence | A: 2-way noisy categorical bit; B: 8 raw waveform coordinates; two modality flags; 12 total inputs | independent evidence about binary label over 8 random-modality observations | 16 observations instead of 8 |
| digits_rows | the installed sklearn 8x8 handwritten images, each row divided by 16 | 8 raw rows; 10-way digit label | 8 blank rows after image completion |

All tasks also have clock shift: alternating dt=.5/1.5 instead of dt=1, with
identical raw inputs and labels to the IID condition. For multimodal evidence,
the condition named `long_delay` is a longer evidence sequence, not an empty delay;
its extra observations carry extra information equally for both models.

No task supplies a precomputed posterior, pretrained features, target label in
the input, or a class-dependent initial state. Waveform noise has finite support:
A's sign is correct with probability .70; B's sign with .75 and an independent
equiprobable nuisance waveform. These synthetic waveforms are not natural audio.

`multimodal_support(modality,q_a=.70,q_b=.75)` returns `[outcome,12]` inputs and
`[label,outcome]` conditional probabilities for an offline policy oracle. A order
is sign -1,+1. B order is (sign,nuisance)=(-1,-1),(-1,+1),(+1,-1),(+1,+1).
The content model only sees realized raw inputs after an authorized READ.

Digit partitions are stratified with fixed seed 20261031: per class, floor(.6*n)
train, floor(.2*n) development, and the remainder test. The raw dataset hash,
indices and split hashes are saved before fitting. Loading data to establish its
identity does not calculate held-out loss or accuracy. No feature transform is
fitted to the full dataset.

Train data seed is `700000+10000*task_index+model_seed`. Development data seed is
`1200000+10000*task_index`; test seed is `1700000+10000*task_index`; add 100 only
for long_delay. Task order follows the table. Development uses 512 synthetic
examples per condition; test uses 2048. Digits evaluate the entire requested
partition exactly once. Family, width and initialization seed never alter the
evaluation data.

## Fixed fit matrix and evidence

Three tasks × two families × widths 16/32/64 × seeds 11/23/37 = 54 fits. Each fit
uses 300 updates, batch 32, float64 CPU, Adam lr .003, betas .9/.999, epsilon 1e-8,
global gradient norm clipping at 1.0. The objective is mean final-state
classification cross entropy. There is no early stopping, test-based seed choice,
hyperparameter search, or readout-only training.

Each update records loss, gradient norm and per-array norms, clipping scale,
cumulative examples/sequence steps/cell updates, raw batch hash, and CPU/wall time.
Each fit saves initial/final parameter arrays, optimizer state, first/last raw
training batches, deterministic generator seeds, source hashes, and a final
checkpoint receipt. The training entry point never calls held-out evaluation.

The owner first publishes the fixed protocol, then performs training and any
declared development-only calibration, freezes all weights, and separately runs
test evaluation. Evaluation verifies each frozen checkpoint hash and saves all
per-example logits, labels and predictions. These runs compare equal parameter
capacity and equal update/data budget; they do not enforce equal wall-clock time.
Total compute and the analytic gate's overhead must accompany any quality claim.

## Commands

Run from this experiment directory:

```
python content_audit.py protocol
python content_audit.py identity
python content_audit.py check
# Only after the owner publishes the frozen protocol:
python content_audit.py train
python content_audit.py evaluate --split dev
# After all trained/calibrated weights have been frozen:
python content_audit.py evaluate --split test
```

Subsets are selectable with `--task`, `--family`, `--widths`, `--seeds` during
orchestration; formal runs retain the registered settings. `--run` identifies one
run for evaluation. The owner serializes measured runs to avoid timing overlap.
