# HCSN P2: expected-event/reward batch-shape admission

**DRAFT / RESEARCH ONLY / DENY_ALL / all_blockers_closed=false /
production_activation_allowed=false.** Narrow stacked change on #4362 exact
HEAD `913a18c752326f2f101327a53e08fb2454755b2a`. This touches only
`stable_probability.py`, one test and this evidence note. No model weights,
finance kernel, event mechanism, training, GPU, owner, authority, stored evidence
or production activation are modified.

## Reproduced exact-source counterexample

Original GitHub `stable_probability.py` blob:
`2f325119da3a3830ed32f4a45ddeecce4b7fbeb9`.

With `probability.shape=(2,3)`, identity transition `(3,3)` and per-start
`event_vector.shape=(2,1,3)`, the original code validates only the **last**
state dimension and silently returns an **event count of shape `(2,2)`** instead
of `(2,)`. The two batches are cross-broadcast: four counts are produced
rather than two. The reward-vector path has the same defect. Such numbers may
silently inflate expected total event or reward accounting and downstream
sequence features. All probabilities and event entries can remain finite and
nonnegative, so the original safeguards do not detect this.

## Bounded correction

- For each supplied functional vector, compare the broadcast result of the
  pre-state, functional vector and **already computed propagated state**.
  Refuse any vector that introduces extra batch axes or cannot broadcast.
- Retain legitimate shared last-axis vectors and per-batch vectors, including
  a single shared initial state broadcast across explicitly batched operators.
  Expand the *pre-transition state* only to the already established output
  shape, so expected events remain pre-transition expectations.
- Retain the existing dtype, device, finite, nonnegative-event, mass and
  autograd rules; no normalization, clipping or remapping changes.

## Local CPU validation (source-exact)

The original parent Git blob was materialized byte-for-byte and checked with
`git hash-object`. Reproduction before edit: `(2,3)` state × `(2,1,3)` vector
produces `(2,2)` event counts. Patched source and newly added test are local
Git blob-exact; PyTorch 2.10.0+cpu, Python 3.13.5:

```
python -m unittest -v \
  experiments.hcsn_distributional_v2.test_probability_functional_shape
# 5/5 PASS, 0 skips
```

The five checks cover extra event and reward axes rejection, shared/per-batch
valid vectors, shared-start operator broadcasting, and differentiable event
expectation through batched operators. The original full research audit,
2000-token content training, four-modal data, native Rust/GPU and complete CI
were **not** rerun and are not claimed.

## Retained gates

P0 global coupled HX and precision; P1 registered causal mechanism benefit;
P2 selective copy/MQAR/overwrite/long recall/irregular event clocks and
repeated physical regeneration **still not accepted**; P3 genuine paired
text-image-audio-video; P4 native 64-4096 cells, energy and recovery; P5
externally tuned matched-budget net-quality advantage. This is an accounting
shape safety patch, not P2 memory-task success or a production go/no-go change.
