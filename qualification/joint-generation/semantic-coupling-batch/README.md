# Same coupling law, lower batched table cost

The batched implementation passed scalar-law parity and the fixed performance gate.
On1008 literal requests, median CPU fell from**0.155305s to0.015940s**,about**9.74x**.
This is a table/profile microbenchmark including binding amortization, **not an
end-to-end generator speedup or a new learning result**.

## Unchanged behavior

`batch.py` checks the existing opt-in coupling profile/model binding once per batch,
vectorizes explicit semantic transport and residual coupling,and retains separate
raw/CDF-normalized1e-12 marginal guards. The qualified scalar helper,profile identity,
sampler and default independent service are unchanged. No target,reward,decoder or
training interface is introduced. Input arrays are not modified.

Six tests cover all36commands,identity/permuted observed semantics,zero residuals,
scalar output parity,input immutability,CDF normalization/binding/rejection and
supplied-uniform draw parity. The earlier near-normalized counterexample still rejects.

```sh
PYTHONPATH=../explicit-semantic-transport:../semantic-coupling python -B -m unittest -v test_batch
```

## Fixed benchmark and result

No model or dataset payloads were accessed. Deterministic literal policies include
positive,identical,one-hot and disjoint cases. Each implementation had12warmup rows,
then five paired1008-row repeats with alternating run order. All timings are retained
in `SUMMARY.json`; the median,not a favorable minimum,determines the speed gate.

| CPU seconds per1008rows | Scalar | Batch |
|---|---:|---:|
| Repeat0 | .155365 | .015937 |
| Repeat1 | .155305 | .015940 |
| Repeat2 | .151448 | .015945 |
| Repeat3 | .151511 | .015949 |
| Repeat4 | .172365 | .015940 |
| Median | .155305 | .015940 |

The median batch/scalar ratio was**0.102640**,below the predeclared0.5 limit. Across
5040timed rows perimplementation,maximum raw and actualCDF-law differences were0;
maximum normalized marginal error was2.78e-16. All6tests and30fixed sampler checks
passed. This is evidence on the fixed fixture,not universal bitwise equivalence or
identical draws at every floating CDF boundary.

Whole waited child cost**1.078645CPU seconds**,1.098511wall,43444KiB RSS. Limits were
10CPU/60wall/512MiB,one pinned numerical thread,existing synthetic-only shared lock.
The receipt includes tests,warmups,both timed paths,20160marginal checks,comparison,
output and exit. Source/review and supervisor-tail costs remain additional,not zero.

Scalar per-request binding versus once-per-batch binding is an intentional part of
the optimization;this is not a pure arithmetic-kernel comparison. No speedup claim
is transferred to actual learned outputs,different batch sizes or full generation.
The previous structural control success and original NDU gate failures are unchanged.
