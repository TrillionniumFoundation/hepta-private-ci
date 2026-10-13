# Matched end-to-end pretrained execution controls

Continuation of `892effe65fd0a6ab838f1ee356a1474667ef66b3`. Earlier synthetic
results and all earlier checks/studies remain. The existing learning consumer
now accepts `encoder_batch_size=1..32` (default 32). Its CLI exposes
`--encoder-batch-size`; Head defaults and the 64-Cell/4096-row envelope do not
change. Actual encoded-input rows, cache hits and peak estimated cache bytes
are reported separately; neither raw tensor storage nor cache estimates are RSS.

`development_learning_comparison.py` executes four complete, independent calls
through the original `SharedStemEngine` and original Head fitters:

```text
Arm        Encoder batch    Empty-cache capacity    Head fit group
singleton  1                0                       1
batch      32               0                       1
cache      32               64 MiB                  1
grouped    32               64 MiB                  32
```

The same frozen physical backend serves all arms. Every arm receives a newly
constructed empty feature cache, the same rows, training labels, initialization
and per-Cell update count. Order is a predeclared seed-bound rotation. Adjacent
comparisons isolate batching, caching, then grouped fitting/feature-table
materialization. Same initial digests and actual examples/steps/parameters are
checked. Complete prediction identity/cardinality and finite widths are checked.
Numerical tolerance is fixed at absolute 2e-5 / relative 2e-4; bitwise Encoder
features need not match across batch shapes. Differences and classification
mismatches are retained; the code never selects a winner or lowers a threshold.

The outer `whole_call` timer includes consumer preflight, unlike the older
consumer `total` field. `full_comparison` includes all four arms and comparison
work. Loading and network acquisition are separate costs. There is no claim of
cold loading per arm, independent-process RSS, p95/p99, energy or native latency.

`development_pretrained_study.py` exercises the unchanged safetensors-only,
local-only `FrozenLocalHfBackend` and its loading-info plus actual-tensor checks.
The fixed profile is the protocol's BGE small Chinese candidate, mean pooling,
128-token rejection-without-truncation, eight independent SwiGLU Heads of hidden
width eight, 80 SGD updates and two classes. The diagnostic corpus has 40 authored
Chinese sentences, 24 train / 16 heldout, in four topic families. Four binary
topic partitions each have two Cell replicas. These are NOT eight independent
tasks or 128 independent heldout observations. All authored sentences share one
source group per fold, with synthetic ordinal times, NOT observed future times.
This is not a public benchmark or BGE's standard retrieval pooling recipe.

All four prediction files are written create-only and hash-checked BEFORE the
separate heldout-label file is read for scoring. Every model tensor and snapshot
bytes are rechecked before scoring. Negative learned-versus-frozen results are
retained. A failed numerical-equivalence gate preserves the reports and fails
the job. No random model or synthetic backend replaces a missing real snapshot.
The study script itself has no network/model-download path.

The original development workflow retains head/merge synthetic qualification.
A separate exact-head job, limited to this owned research branch or an explicit
manual dispatch, acquires six public files at fixed HF revision
`534b6bfaaf500e70bcb9f3771cebc940c23b219d`. Weight SHA-256 is fixed to
`354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026`.
Individual byte ceilings, a download manifest and the complete local snapshot
hash bind acquisition to loading. The execution step sets offline flags and
runs fresh processes for seeds 1414/2525/3636. It uploads evidence, never weights.
No secret, write permission, custom model code or changed production owner is
introduced. Dependencies are pinned for this profile, not claimed latest.

Source: <https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/534b6bfaaf500e70bcb9f3771cebc940c23b219d/model.safetensors>.
HF loading interface: <https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/model>.

Local comparison checks use a clearly simulated deterministic backend. Actual
pretrained results require completed exact-source hosted artifacts; adding this
job is not itself a passing result. Existing global dependency/security and
cross-platform failures remain independent, non-waived gates. No main merge,
model activation, independent NDU gain or production readiness is asserted.

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest -v development_learning_comparison_checks
PYTHONPATH=qualification/stem-cell-v1 python \
  qualification/stem-cell-v1/development_pretrained_study.py \
  --snapshot /approved/local/bge --snapshot-sha256 HASH --seed 1414 \
  --output /new/external-real-study
```
