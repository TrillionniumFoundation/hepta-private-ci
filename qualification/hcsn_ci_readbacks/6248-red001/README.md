# First hosted Torch RED originals for #6248

Original outcome: **failure / HOLD**. This archive preserves [run43216185145 / job131175904511](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43216185145/job/131175904511) at immutable source `bc1b94039dea52c5426b99ba617f7a2f59742377`.

| Actual attempt accounting | Value |
| --- | ---: |
| Completed model-primal numerical calls | 1 |
| Backward attempts / adjoint calls / optimizer updates | 0 / 0 / 0 |
| Forward-basis calls / guard rejections | 0 / 0 |
| Full child wall / CPU seconds | 2.330044445 / 2.185178 |
| Full child peak RSS | 344044 KiB |
| Original artifact ZIP | 6153 B; SHA256 `bec5f7727e9cb0492cf768651c355ae180100fcfff0a52db69ae46de701e67f0` |

The original traceback reports `AttributeError: attribute 'metadata' of 'torch._C._FunctionBase' objects is not writable` at the assignment to `ctx.metadata`. Frozen source places this assignment after `_primal` returned, the second metadata check and the forward-record append, before the custom Function returned its Tensor. The one completed primal and its partial arrays remain charged and retained. No backward, adjoint, gradcheck, guard or optimizer success is claimed.

The full ZIP and all six raw members are retained, including RESULT, partial ARRAYS, source manifest, stdout, empty stderr and WRAPPER-COST. Complete decoded job logs and API metadata are retained. Raw result fields match the logged summary; raw wrapper/source match their logged originals. All ten prefrozen source hashes were freshly recomputed from exact-source GitHub bytes. Whole ZIP and NPZ bytes and all remote blob identities are read back independently.

Full-child costs include Python/Torch imports and source admission. The separate validation interval is0.208232293s wall /0.208230529s CPU; the forward record is0.203868047s wall with542 internal steps. These scopes are not additive. Runtime is Python3.12.16, Torch2.8.0+cpu, one thread. Original qualification flags remain false.

This archive adds zero candidate, model, Torch, adjoint or optimizer executions and requests no rerun. Candidate fixes or later attempts have separate source/run identities; this RED is retained unchanged. All new paths are under `qualification/hcsn_ci_readbacks/6248-red001`; the archiver changes no PR source head. Retained original bytes are not reformatted. HOLD_NO_GO.
