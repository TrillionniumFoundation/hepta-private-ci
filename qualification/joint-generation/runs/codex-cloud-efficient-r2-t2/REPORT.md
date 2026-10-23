# r2 training/validation t2 — failed budget and readiness

The math-equivalent implementation follow-up executed in the same configured
Codex Cloud environment. Source `3c69a9460d`, freeze commit `bf0996f09b`, train
exit **2**. The independent formal test remained unopened. t1 and r1 receipts
remain retained; no statistical gate or budget cap changed.

The early supervised/anchor/additive candidates reached 396/387 useful updates.
Their full attributed builds used approximately 6.48/6.90/6.66 process-CPU seconds.
Later NDU candidates returned only 7 and 6 updates; their complete per-candidate
training/validation/export rows consumed 3.36 and 6.31 CPU seconds. NDU's complete
build reached **26.65 seconds**; NDU-control reached **12.96 seconds**. Both violate
the unchanged 10-second cap. These are real failures, not successful equal-budget
comparisons. The observed slowdown's cause remains under investigation; candidate
row CPU includes validation/export and must not be mislabeled as pure step CPU.

Validation additive-anchor task/joint differences were +0.023052/+0.023953;
NDU-additive were -0.060662/-0.062778; control-additive CPU-net was -0.145698.
Positive cheaper-random-view quality does not rescue these failed conditions.

A separate fresh-process manual random-input diagnostic observed OpenBLAS0.3.30
with one thread, one `/proc/self/task` thread, and 20 NDU steps of roughly
0.00043–0.00270 CPU seconds. It is not a replay of t2 or evidence of an environment
cause; no test data was constructed. Further work must identify and preserve the
cost cause, and complete frozen-input budget/source guards, before another build.
