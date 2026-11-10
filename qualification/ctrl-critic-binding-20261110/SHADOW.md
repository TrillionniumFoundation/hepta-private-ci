# Shadow critic dependency binding

Base: `40ae8521a8cf806324c367bd69111e0850fde590` (#5642).

The old shadow heads checked public feature bounds but could not detect a changed
encoder, answer selector or candidate generator inside those bounds. This stage
binds the implementation and relative-to-STOP value heads to one immutable
`CriticContext`, shared with the separate native metacontrol research stack.

The nine SHA256 fields identify the encoder/preprocessing manifest, answer head,
candidate generator, public-state codec/runtime, action graph and continuation
suffix, terminal finalizer, utility profile, tariff and evaluator. These are
dependency declarations. Callers still authenticate the manifests and observers;
a matching self-declared hash does not establish that evidence is authentic.

`fit_heads`, `calibrate_heads` and `predict` now require explicit `context=`.
Every training/calibration row must carry the same typed context. Implementation,
STOP and continuation receipts must independently carry its canonical digest;
the paired evaluator, utility and tariff pins must also match it. Existing rows
without those original bindings cannot be upgraded by filling in guessed fields.

On missing or changed identity, prediction returns `recalibration_required`, with
both points and both residual summaries unavailable. A new fit and a disjoint
calibration partition are required before predictions under the new context can
be used. This API remains shadow-only and does not choose or dispatch actions.

The target remains the observed net return after continuation minus the observed
net return after STOP. Implementation probability is a separate diagnostic and
is not multiplied into that already realized target.

Validation covers the original five suites and six additional producer-change
regressions. The exact-source workflow now requires the new suite separately.
Local command and original logs are retained in the associated execution record.
These are manufactured contract tests: independent real tasks added = 0;
policy benefit and production adoption remain unqualified; `NoUpdate` remains.
