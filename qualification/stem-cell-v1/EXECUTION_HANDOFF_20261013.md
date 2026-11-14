# Shared Stem / Cell: implementation and execution handoff

Source baseline: `8c8003d9164edbdb997b37c78156e1ad9b91d52b` on
`research/shared-stem-next-round-clean-20261013`.
Code candidate: `978bcc1ff9aac8e7ce93dc57173e824de656ad47`.
This is a qualification-only change. No production owner, authority, selected
artifact, existing runner or historical result is replaced.

## P0: corrected experimental semantics

V1 produced `[true,true,true,true,true]` for its five NDU flags and Head ceilings
`[32M,32M,32M,64M,64M]`. The original two source blobs were retrieved and verified
byte-for-byte before reproducing these defects. V2 preserves the five arm IDs
but yields `[false,false,false,false,true]`; its main seven arms have 32M final
Head ceilings. Fixed sparse-16, direct-initialized sparse-32 and explicit 64M
capacity controls give nine arms and eight named contrasts. Every arm's split
flag, including the 64M split control, is tested.

These are ceilings, not proof of equal actual tensor counts, training trajectories
or physical work. `paired_execution.py` checks actual total trainable and peak
counts, including router/critic allocations. Head capacity may trade against
router/critic capacity. Frozen-base storage remains separately reported.

Every train/search/evaluation/inference/migration counter and cap is retained.
Match offline work (train + evaluation + migration) and online work (search +
inference) separately. This prevents unnecessary dummy search/migration in a
control, while preventing offline savings from hiding online compute increases.
The partition is bound into the plan. Numeric caps and a declared tolerance must
be frozen before execution. The default matching tolerance is 1%, not a physical
measurement or a claim of exact equality. Do not adjust it after results.

Rebuild V2 plans and audit potentially affected V1 consumers; do not rewrite old
receipts or assume every historical model execution actually used NDU. The plan
ID covers all semantics. Boolean/integer substitution, altered flags/budgets,
unknown fields and attempted evidence promotion are rejected. Output creation
is exclusive rather than check-then-overwrite.

## Executable research additions

`head_surgery.py` implements a CPU float32 linear-readout split with independent
children, a conditional top-1 gate, selected-subset execution, budget checks and
candidate-only training. A frozen selected model is thawed only in its candidate
copy. Training timestamps cannot exceed the fixed cutoff. Identical children can
merge exactly; divergent children cannot be averaged implicitly. Function-
preserving splitting ADDS capacity and gate tensors. It is not a magic constant-
parameter transformation, does not establish multi-generation learning, and is
not yet wired into the native checkpoint/selection owner.

`system2_execution.py` actually invokes propose/verify/value callbacks and revises
using returned feedback. Budgets include failed and invalid callbacks and value
calls. Public inputs have causal timestamps and no final-evaluation-label field.
Adapters remain responsible for real data authorization and external isolation;
Python typing and timestamps are not an information-flow security proof.
The continuation helper is the explicitly linear-discounted special case using
actual segment duration. Chance nodes aggregate expectations, not optimistic
maxima. These algebra/callback tests are not a general stochastic FBSDE solver,
pretrained reasoning benchmark or evidence that a learned NDU estimator works.

`paired_execution.py` consumes normalized owner exports. Missing energy, memory,
FLOPs or outcomes stay missing; failures/timeouts remain in request denominators.
Source, device, workload, observer and future-window mismatches are rejected.
A clean result is only `structurally_comparable_unattested`: digests do not prove
profiler authenticity or independent observation. Existing owner receipts,
retention/calibration/safety evaluation, preregistered statistical analysis and
selection governance are still required. No new production evidence issuer exists.

## Reproduce the focused tests

The measured local profile is recorded in `LOCAL_TEST_RECEIPT_20261013.json`.
PyTorch is a required test dependency, not silently skipped when unavailable.
From a checkout of the candidate:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
git diff --check
```

The retained local run passed 38 test methods: 9 matrix, 13 paired-audit, 8 tensor
surgery and 8 reasoning/continuation. The logs and source blob identities are
retained. These were run on the exact eight file contents in a bounded local
source mirror, NOT a complete repository build. No remote Actions result, Rust
format/build/test result, prospective merge qualification or native-host result
is inherited. Existing CI has not been expanded to run all new tests in this
change; the command above is the required focused review entry point.

## P0-P5 acceptance remains explicit

| Phase | Delivered here | Still required for completion |
|---|---|---|
| P0 | Corrected flags, budgets/contrasts, immutable semantics and executable comparability audit | Real exports must validate before any efficacy comparison; audit affected historical consumers |
| P1 | Full-cost and independent-observation audit checks | Bind approved actual snapshots/data, integrate exports with existing local runners, run joint/cached/conditional representations and calibrated quality on the target host |
| P2 | Executed split, sparse routing, candidate training and exact-equal merge primitives | Native owner integration, specialty training, evaluated distillation/pruning, at least three future windows and old-task retention |
| P3 | Executed callback loop and tested linear continuation semantics | Real generator/verifier/value adapters, frozen NDU estimator, qualified stochastic solver where used, equal-budget no-search/fixed-depth/voting comparisons |
| P4 | No new trained multimodal generator or real outputs | Approved codecs/decoders, actual image/audio/video training and generation, independent condition-following/quality/consistency evaluation |
| P5 | Actual tensor storage counting on small reference modules only | Native 1024/4096-Cell serving, hot/cold allocation, batching, recovery, end-to-end latency/memory/energy and longitudinal measurements |

The session container has CPU-only PyTorch, no attached model snapshots or target
cloud workspace, and direct repository network access failed. The connected
GitHub API was used to publish the source. The missing model/host material is not
the only remaining work: the adapter/native integration and scientific acceptance
items above are also open. No fabricated measurements fill those gaps.
