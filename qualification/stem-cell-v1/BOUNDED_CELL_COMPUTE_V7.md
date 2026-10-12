# Bounded Cell folding with matched validation costs

Continuation of PR #1654 at `b0f91cce9d7f9e18a19972ab353067de72ae86b9`.
Historical publication note: the original V7 GitHub write was blocked and this
material was first delivered as a local patch. The V8 continuation lands this
operator and preserves the measurements below as historical V7 evidence. New
source-head CI and measured results are identified separately in FINITE_PLAN_V8.md.

No production runtime, store, persistent compiled cache, model selection,
authority, native scheduling or current learning rule is replaced.

## Correct a real comparison asymmetry first

V6's folded control directly called unchecked folded arithmetic, while the
shared path included request/dormancy and numerical checks. A finite-operand
fixture made folded gate weights overflow to infinity; the old folded path
returned finite logits after sigmoid saturation, while shared execution rejected
`nonfinite Cell gate score`. This is an offline numerical-contract gap, not a
production-authorization exploit. The original counterexample and timings are
retained. Do not use old timings as equal-validation comparisons.

The shared request preflight is now a private helper, without changing the
original shared equation or its autograd path. The new four-method probe runs
exactly one common request check per timed batch and requires finite gate scores
and outputs in every method. Its expanded/shared equations are checked against
the unchanged BasisCellHeads implementation. V6 remains available as historical
instrumentation; V7 is a separately named, explicitly enabled sidecar.

## New bounded operator

`bounded_cell_execution.forward_tiled` compiles only the Cells referenced by one
request tile, evaluates it, and discards the temporary matrices. At most 32 lanes
enter a tile. A single-Cell invocation compiles its one matrix once, then reuses
it only until the call returns. Single-Cell matmul never broadcasts a full dense
matrix for every input. All feature/Cell references remain explicit; no vector
similarity grants permission or deduplicates unrelated inputs.

Admission occurs before base projection or folding. The default 1 MiB cap is a
conservative bound for explicit floating-point forward intermediates, including
retained outputs/readout, folded matrices, gathers and products. It excludes the
input/bank, boolean/index temporaries, Python/allocator overhead and BLAS
workspace; it is NOT measured peak RSS. Noncontiguous bases are rejected rather
than allocating an uncharged flattening copy. Autograd must be disabled so old
tiles cannot remain live through a backward graph. Learning still uses the
original separately gradient-tested operator. No partial output is returned
if a later tile fails. The caller still owns scope, freshness and mutation
exclusion; this Python operator is not a native lifecycle fence.

## Strong controls and actual cost accounting

`bounded_multicell_probe` retains expanded, shared, precompiled dense and tiled
dense methods. Four rotated repetitions place every method in every position.
It records preparation/snapshot copying, reference computation, warm-up, full
dense compilation, all actual invocations and complete probe time. No padding
wastes a cheaper method's budget. The precompiled control folds only the union
of Cells actually used, not every registered inactive Cell, and also uses the
single-Cell fast path. Its separate compiled-matrix cap is 64 MiB; this is NOT
an equal-memory experiment. Both retained compiled bytes and the integer lookup
are counted. Tiled compilation is inside each timed invocation, not made free.

## Observed final local run

CPU PyTorch 2.10.0+cpu, two threads; component wall-time medians in milliseconds:

| Input profile | Expanded checked | Shared checked | Precompiled active dense | Tiled dense |
| --- | ---: | ---: | ---: | ---: |
| Four trained Cells, 480 requests | 6.9679 | 5.1198 | 4.4209 | 6.9692 |
| 4096 synthetic Cells, one reused input | 56.5557 | 45.8731 | 40.6395 | 87.0780 |
| 4096 synthetic Cells, 32 inputs per batch | 63.6903 | 49.4511 | 41.7197 | 82.6658 |
| Synthetic width-512/rank-32/64-class Head, one active Cell, 1024 requests | 232.7315 | 62.0585 | 12.1481 | 27.6234 |

For 4096 active Cells, the precompiled control retained 31,473,664 floating tensor
bytes plus 32,768 lookup bytes. Tiled folded matrices were bounded by 245,888
bytes, total declared scratch by at most 996,352 bytes, with zero matrices
retained after a call. This saves storage but is slower than shared computation
in that workload; no default-path switch or unconditional speed claim follows.
The single-active-Cell stress case also lets the strong precompiled comparator
store just one 133,124-byte matrix bundle. Tiling is faster than shared there,
but slower than that stronger control; it is not a learned-domain result.
The first, slower tiled attempt and all raw timing trials are retained too.

Four actual independently fitted Cells on historical real mmBERT features still
have 118/120 held-out correctness each. Learned/inherited weights, normalizer and
480 prediction records are byte-identical to the delivered V6 run. Independent
affine scoring reports 3.814697265625e-6 maximum error and zero argmax reversals;
the new timing comparison's maximum error on those trained Cells is
7.62939453125e-6. Training is new CPU work; Encoder calls in this execution are
zero. Public feature history is not authenticated future observations.

163 local tests passed without failures/skips (141 inherited plus 22 new).
Local imports still use declared model_runner/study function extracts in a
partial checkout; they are never pushed as replacements. Complete-source CI,
new BGE inference, native CAS/WAL/final-use, future NDU, semantic recurrence and
multimodal generation are still separate uncompleted qualifications. No GitHub
queued result is called passed. The existing CI job runs the new checks and
explicitly requests the sidecar; no new job, bypass or permission is added.

```sh
export PYTHONPATH=qualification/stem-cell-v1
python3 -m unittest -v bounded_cell_execution_checks
python3 qualification/stem-cell-v1/multicell_learning_study.py \
  --archive /fixed/artifact-11757461425.zip --output /new/bounded-study \
  --synthetic-scaling --bounded-serving
python3 qualification/stem-cell-v1/multicell_learning_study.py \
  --archive /fixed/artifact-11757461425.zip --review-run /new/bounded-study \
  --output /new/bounded-scores.json
```
