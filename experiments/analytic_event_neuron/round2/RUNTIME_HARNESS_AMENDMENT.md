# Qualification-only runtime admission amendment

The main source/model freeze remains unchanged. Its frozen runtime_bridge.qualify
helper admits only datasets labeled development, while the frozen protocol
registers fresh runtime data labeled runtime_confirmation. This mismatch was
identified before any registered runtime confirmation trajectories were created.

The original helper is retained byte-for-byte. A schema-only fixture containing
the runtime_confirmation label and no trajectories demonstrates its rejection.
No actual dataset is relabeled.

The new runtime_confirmation.qualify_confirmation driver imports the frozen
AdaptiveEventRuntime and retains the original qualification body, worker,
models, guards, native calls, prediction checks, state checks, costs and horizons.
Its only functional amendment is explicit data-role admission:

- Default formal mode requires runtime_confirmation.
- Explicit parity_only=True admits development and stamps the output as parity
  only. This mode cannot be reported as fresh confirmation.

The source diff also contains the new function name/signature, explanatory
docstring and provenance fields. Reversing exactly these listed changes yields
an AST identical to the original qualification body.

## Verification before fresh runtime data

The two helpers were executed on the same existing frozen development data and
the same protected model, with the complete guarded runtime profile. Neither
helper trained or selected a model. Both passed 92 checks.

The retained predictions, signed counts, categorical counts, certificates,
permissions and check outcomes were compared across 12 forecasts, two fresh
process recovery records and one deterministic tail fixture. All 3,898 compared
nodes matched; the maximum compared floating-point difference was zero.

The normalization plan was saved before execution. It removes measured timing,
process RSS, and native/composite identities derived from those changing
measurements. It does not remove model identity, public history, event packet
identity, predictions, counts, certificates, authority or check booleans.
Ancestry and recovery are validated inside each execution. Raw measurements and
receipts from both executions remain available.

The original helper's selection rule is preserved: each registered 16-row file
supplies its first four histories at three horizons, for 12 forecast cases per
profile. Unused rows are not counted as tested cases.

## Separate receipt and execution boundary

The parent study publishes this driver and its source/AST/parity evidence, then
creates a separate RUNTIME_HARNESS_FREEZE.json bound to the original FREEZE.json
and protocol before generating runtime confirmation data. This is an
operational qualification amendment, not an alteration of any predictor,
training artifact, statistical gate, action cost, random seed or main study.

Evidence resides under runtime_harness_validation in the run directory:
ORIGINAL_SPLIT_REJECTION.json, AST_DIFF.json, QUALIFICATION_SOURCE_DIFF.patch,
PARITY_PLAN.json, PARITY.json, and both raw parity qualification trees.
