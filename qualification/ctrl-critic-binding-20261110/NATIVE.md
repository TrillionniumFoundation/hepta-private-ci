# Native metacontrol dependency binding

Base: `1c7c9598cfb1d623afce2d026332502e9c9dd066` (#5687).

Public feature shape and the observed numeric envelope cannot establish that a
critic remains valid after upstream weights or candidate generation change.
The new shared `CriticContext` freezes nine dependency identities across fitting,
calibration, prediction, choosing, diagnostics, checkpoint serialization and cold
loading. Encoder pins include preprocessing; public-state pins include the codec
and runtime; action pins include the fixed graph, primitive/macro distinction and
continuation suffix; settlement pins include the terminal finalizer.

Observations must include the complete typed context and an original evidence
context digest. Study ingestion also checks the outcome's evaluator, utility and
tariff against this context. The context file and its byte digest are required by
the CLI. Its canonical digest is retained in the registration, fit receipt,
calibration, checkpoint and pre-future freeze. The study source manifest includes
the shared context implementation. No identity is inferred from numeric values.

Missing identity or drift refuses fitting, calibration, predictions and cold
loading. `choose` returns legal STOP with `recalibration_required`, unavailable
continuations and HOLD when the context is missing or changed. It cannot reuse a
non-STOP light action or old calibrated residual. A valid state with legal STOP
is required. Refitting and recalibrating on a separate source partition under
the new context restores access to the new critic.

This is a research API migration: observation, fit receipt, study and study-report
schemas are v2. Legacy v1 observations/checkpoints stay readable as historical
evidence with their old source, but this new loader rejects them. They cannot be
made into new observations by adding identity fields after the fact. New study
invocations add `--critic-context PATH --critic-context-sha256 SHA256` to the
existing pinned-input CLI arguments.

## Action meanings retained

| User-facing purpose | Current receipt runtime |
| --- | --- |
| Obtain another observation | `PREPARE_ROI`, then `READ_ROI` when legal |
| Write or repair a delivered result | `WRITE_TEXT` / `RENDER_IMAGE` under the existing output constraints |
| Verify the result | Independent post-actor scorer; no selectable VERIFY primitive is added |
| Stop | Primitive STOP settles the last delivery |
| Native macro baseline | `WRITE_TEXT -> STOP` with the frozen finalizer |
| Native paid READ macro | `PREPARE_ROI -> READ_ROI -> WRITE_TEXT -> STOP` with that same finalizer |

The one-continuation study still requires `[action, STOP]`. It rejects a hidden
delivery suffix; macro gains cannot be relabelled primitive action values.
The original V3 collector files and historical dispatch record are unchanged.
A separate reconciliation now binds its recovered failed terminal state and
complete logs; its source flow did not reach the episode loop. Reserved future
sources and the default actor are unchanged. No original business operation is
retried by this migration.

Dependency digests are not observer authentication or complete physical resource
accounting. Existing missing-result and one-off-cost gates remain in force.
Local regression and manufactured CLI results qualify these contracts only.
Independent real tasks added = 0; policy benefit and production adoption remain
unqualified; the scientific disposition remains `HOLD_NO_GO / NoUpdate`.
