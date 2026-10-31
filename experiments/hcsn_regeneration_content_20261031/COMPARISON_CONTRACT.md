# Secondary compact Transformer and conventional spiking baselines

## Scope

These two fully trainable baselines supplement, and do not replace, the primary
ordinary versus renewal-flow matched-parameter comparison. They use the identical
raw data generators, batches, splits, update budget and evaluation payloads.
They have different parameter counts and different hidden-state structures.
Results must therefore show parameter count and CPU cost alongside quality.

This is a comparison of small CPU classification encoders. It is not a comparison
of large multimodal generators, optimized GPU Transformer training, FlashAttention,
or neuromorphic hardware energy. Width equality does not imply capacity equality.
No claim of general superiority over Transformer or SNN follows from this matrix.

## Transformer

One causal, single-head, pre-layernorm Transformer block:

1. Trainable projection of the raw input to width d, plus fixed sinusoidal
   positions computed from cumulative supplied dt (base 10000).
2. LayerNorm with trainable scale/bias and epsilon 1e-5.
3. Independent trainable Q/K/V matrices, causal softmax(QK'/sqrt(d)), and output
   projection. Q/K/V/output projections have no bias; the input projection has one.
4. Residual connection.
5. A second trainable LayerNorm, a d→2d→d feed-forward network with exact GELU
   and trainable biases, and another residual connection.
6. The last position's full hidden vector feeds the trainable classifier.

There is no pretrained feature extractor or frozen attention. Hand-written exact
backpropagation trains every projection, FFN array, LayerNorm scale/bias and
readout. The development audit centrally finite-differences every parameter of a
small model and checks causal prefix consistency. Softmax is evaluated with
logsumexp; future positions have exactly zero attention probability.

The implementation explicitly materializes dense attention. It is a NumPy CPU
reference, not an optimized representative of Transformer hardware efficiency.
At inference it recomputes the whole supplied sequence; no KV-cache implementation
or streaming decode throughput is being evaluated.

## Hard-spike LIF

Each width-dimensional state contains voltage v, previous binary spikes s and a
filtered spike readout r. Initial states are zero. Constants are tau_m=2,
tau_read=4 and threshold=1:

```
alpha = exp(-dt/2); rho = exp(-dt/4)
current = x @ Win + s_previous @ Wrec + b
u = alpha*v_previous + (1-alpha)*current
s = 1[u >= 1]
v = u - s
r = rho*r_previous + (1-rho)*s
logits = r @ Wread + bread
```

This discrete-slot LIF model emits at most one spike per observation slot. It is
not an exact continuous-time event simulator and does not localize intrastep spike
times. Its forward spikes are hard 0/1. The declared backward replacement is

```
ds/du := 1/(1+abs(u-1))**2
```

BPTT applies this surrogate to the recurrent spike path, filtered readout and
subtractive reset; reset derivatives are not silently detached. This is not the
true derivative of the hard-forward loss. The development evidence explicitly
records the mismatch to numerical loss derivatives in upstream parameters.

Two separate checks have different meanings: readout parameters pass genuine
loss finite differences, while independently implemented forward-mode tangents
match reverse-mode BPTT for the declared surrogate Jacobian. The latter only
establishes implementation consistency of the surrogate, not that it is an exact
loss gradient. Every training row labels its gradient kind as surrogate.

The run records spike counts, possible spike slots and parameter changes. Dead
spiking or unchanged parameter arrays remain reportable outcomes; they are not
hidden by restarting seeds. A dense CPU implementation confers no hardware energy
advantage simply because its activations are binary.

## Fixed matrix, chronology and evidence

Three raw tasks × transformer/lif_surrogate × widths 16/32/64 × seeds 11/23/37 =
54 secondary fits. Each fit uses 300 updates, batch 32, float64, Adam lr .003,
betas .9/.999, epsilon 1e-8 and global gradient norm clipping at 1. All model
parameters are passed to the optimizer; no readout-only fitting is substituted.

Data and seed contracts are identical to CONTENT_CONTRACT.md. In particular the
same training seed generates identical batches for every family at each width.
There is no architecture-specific hyperparameter search. This fixed common
optimizer is a controlled budget, not proof that every architecture is optimally
tuned. Dev and test sets are disjoint; all weights are frozen before test scores.

Every run saves initial/final parameters, final Adam state, source hashes, first
and last raw training batches, and every update's loss, gradient norms, clipping,
batch identity, cumulative examples/sequence steps and CPU/wall time. Existing
and interrupted runs are preserved. Evaluation checks checkpoint and source
hashes, then saves all logits/labels/predictions on each condition.
An existing evaluation directory is never overwritten. The training receipt's
zero test-invocation field describes this function's internal calls; the owner's
frozen-manifest and remote-readback wrapper proves cross-stage chronology.

Training timing includes batch creation and per-update evidence writing. It does
not include software installation, imports or development checks. Timings are
reference execution costs, not FLOP-matched or hardware-optimized comparisons.

Publish the fixed comparison protocol and source before formal training:

```
python comparison_run.py protocol
python comparison_run.py check
# After owner publishes the frozen secondary protocol:
python comparison_run.py train
python comparison_run.py evaluate --split dev
# After all model/controller weights are frozen:
python comparison_run.py evaluate --split test
```

`--task`, `--family`, `--widths`, `--seeds` partition execution without changing the
registered matrix; `--run` evaluates one run. Artifacts live under
`evidence/comparison/runs/{task}/{family}_w{width}_s{seed}/`.
