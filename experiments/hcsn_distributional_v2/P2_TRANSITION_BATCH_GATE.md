# P2 transition-batch alignment gate — research-only

**Admission: DENY_ALL.** `all_blockers_closed=false`, `production_activation_allowed=false`. Do not merge as evidence of physical repeated-event accuracy or production readiness.

## Immutable parent and observed defect

Stacked on Draft PR #4437 at exact HEAD `f1f5d704669d09eaa9c9eb1a7a17c6c455348b31`, itself based on #4434. Parent `stable_probability.py` Git blob was independently reconstructed from the GitHub response with **matching** Git SHA `2ebf722bb89941ddfbf9f30a3252f5434e6859d4`. Both unchanged parent tests were reconstructed and matched Git blobs `cc4b91f57cfe064129a34c0105fa0d6f5c5a06d3` and `6b3c8a39f4be86e7b273eb69304101c3a4320fef`.

The parent enforces event/reward functional vector batch shape *after* probability propagation, but the propagation itself uses broadcasting `torch.matmul(p.unsqueeze(-2), T)`. For a finite, normalized initial state `p.shape=(2,3)`, identity operators `T.shape=(2,1,3,3)`, and finite event vector `[0,1,2]`, the unchanged parent silently returns:

- propagated state shape `(2,2,3)` (four states from two input batches);
- accumulated event shape `(2,2)` and values `[[1.3,1.1],[1.3,1.1]]`;
- no mass, dtype, operator tag, finite, or functional vector guard failure.

The unintended Cartesian expansion occurs even when no functional vector is supplied and is not evidence of extra physical firing.

## Minimal behavior change

Before `matmul`, compare the broadcasted probability and transition **batch** axes. If probability is explicitly batched, the result must preserve *exactly* that input batch shape. Transition may be shared or aligned with its batch; extra leading axes and implicit singleton expansion refuse with `ValueError`. A single unbatched probability `[S]` may continue broadcasting to multiple independent operator batches `[...,S,S]`. Incompatible batches also raise a clear `ValueError`, not a raw `torch.matmul` exception. No weights, Poisson polynomial, dynamics, reset/refractory, original frozen comparisons, Rust owner, GPU or production behavior were changed.

## Executed source-exact CPU evidence

- Environment: Python 3.13.5, PyTorch 2.10.0+cpu, Linux; tests run on locally reconstructed byte-exact original files.
- **Before fix:** 17 selected methods, **4 failed + 1 error** from the new eight transition batch tests; prior nine tests remained passing.
- **After fix:** same **17/17 PASS, 0 skipped**, plus `python -m compileall -q` of changed source and test.
- Tests cover unintended Cartesian cross-batch with/without counts, leading singleton rank expansion, single-row batch expansion, incompatible batches, aligned and shared operators, shared 1D start across two operator axes, event/reward values and automatic differentiation.
- Committed source Git blob `542c90866a0e1b94de2655ed81bd54cc8b3fc142`, new test blob `2b6f5de3f001284c0e2ada29b0eb085cc02a0784`. Each matches bytes actually tested locally; both were independently confirmed after GitHub writes.
- Replay selected tests: `python -m unittest -v experiments.hcsn_distributional_v2.test_probability_functional_shape experiments.hcsn_distributional_v2.test_probability_functional_finite experiments.hcsn_distributional_v2.test_probability_transition_batch`.

## Remaining blockers

This gate does **not** prove actual repeated event dynamics, correct reset/refractory trajectories, long Selective Copy/MQAR retrieval, independent unseen seeds or benefits over ordinary two-gate / Transformer controls. No full original suite or CI result has been promoted as evidence, no 4-modal pairing, no native Rust/GPU 64/256/1024/4096 Cell numbers, no energy/recovery, no equal-token/compute Backbone advantage. P0 full HX obstacle/interval and boundary-gradient certification, P1 causal mechanism gain, P2 memory, P3–P5 remain **OPEN**. Prior negative comparisons (including 0/4 P1 mechanism gains) remain binding.
