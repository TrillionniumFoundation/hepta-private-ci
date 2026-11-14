# Optional compiled-callback experiment

No original HX API imports this extension. The existing pure-Python
`bond_value(..., direct_coupon_survival=True)` remains usable without any Cython
or compiler. Missing/incompatible extension is an explicit import failure of
the experimental module, never a silent numerical fallback or pricing change.

Validated local stack: CPython3.12.14, SciPy1.17.0, Cython3.1.6, GCC, Linuxx86_64.
Install Cython in a private virtualenv (not global), then from repository root:

```
CC=gcc LDSHARED='gcc -shared' python experiments/hcsn_hx_unified_v3/build_coupon_kernel.py build_ext --inplace
python -m unittest -v experiments.hcsn_hx_unified_v3.compiled_coupon_checks
```

Use only explicit `coupon_compiled_research.bond_value_compiled(p,asset,tau,b)`.
The ordinary test discovery does not require the optional compiled extension;
its nine checks are invoked explicitly above. Build artifacts are local only;
rebuild for a different Python/SciPy ABI. Do not distribute the local .so.
Compiler must honor no fast-math and disabled FP contraction. Other platforms
or versions require new verification; observed bit parity is not universal.

Algorithm remains the reviewed adaptive survival integral: identical partition,
quad tolerances, warning rejection and final budget. C callback failures are
sticky per call and every segment result is rejected before accumulation.
QUADPACK diagnostics use full_output=1: failure messages and unexpected
return structures are rejected. No process-global warnings filter is modified.
Mixed concurrent success/message/exception/sticky-failure tests verify
error transport; they are not an all-runtime thread-safety certificate.
Fault-injection hooks are private test machinery, not pricing parameters.

Local fixed172 comparisons:167 successful and5 F/G refusals, all bit-equal to
Python.165 independent-density comparisons,2 oracle refusals; max2.14e-12.
Original105 +explicit9 tests pass. Warm100call x5 sample5.30x faster than the
correct slow Python research path, NOT than the old cancellation-prone closed
formula. Cold first calls compiled0.139s/Python0.120s: no robust cold advantage.
No certificate for global errors, negative equity, branchpoint gradients or
production qualification. Never interpret this experiment as financial advice.
