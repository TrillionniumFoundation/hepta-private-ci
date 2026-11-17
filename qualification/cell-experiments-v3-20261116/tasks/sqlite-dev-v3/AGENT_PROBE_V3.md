# SQLite agent probe interface

`scripts/cell_experiments/sqlite_agent_probe_v3.py` collects sequential predictor decisions against the three existing exposed SQLite development tasks. It imports no model runtime and never loads or closes the caller's predictor. `DevelopmentSession` and its pinned destination bytes remain unchanged.

## Caller contract

The probe accepts the generic interface used by `causal_probe_v3.Predictor`:

```python
predictor.model_digest  # lowercase SHA-256 of the loaded manifest
output = predictor.predict({
    "record_id": task_id,
    "task": {"input": original_prompt, "messages": incremental_messages},
})
```

The result must retain a text `answer` and `loaded_model_digest`. The probe saves the complete returned object before validating it. It accepts the predictor's `input_tokens`, `output_tokens`, `hit_output_limit`, input/rendered-prompt digests, timestamps and wall measurement without rewriting the raw return. A provided input or message digest must match the actual request. The loaded digest and predictor property must match the originally bound model digest before any action executes. Weight-to-manifest validation remains the predictor loader's responsibility.

The actual model is supplied and closed by root:

```python
from scripts.cell_experiments.sqlite_agent_probe_v3 import run_panel

panel = run_panel(
    predictor,
    new_output_directory,
    actor_kind="model",
    maximum=12,
)
```

`run_task(predictor, task_id, directory, actor_kind="model", maximum=12)` selects one of the same declared tasks. `actor_kind` is required and can be `model` or `scripted`. Scripted predictor calls remain separately counted, with model calls zero. This declaration is explicit caller metadata, not independently authenticated identity.

## Actions and feedback

Each reply must parse in its entirety as one JSON string naming `inspect`, `stage`, `apply`, or `stop`. An unquoted action, object, array, Markdown block, unknown action, or multiple JSON values is rejected. The probe does not extract a string from prose, repair JSON, substitute authored references, or execute a rejected reply. A rejected reply still consumes one of the maximum twelve predictor decisions and is appended unchanged as the assistant message; its actual no-execution feedback follows as a tool message.

Each next request retains the complete earlier message prefix and appends exactly the preceding raw answer and observation. No hidden goal payload, reference action sequence, final answer, training trajectory or verifier record is supplied to the predictor. The prompt explicitly identifies the task as action planning with destination-supplied payloads, exposed development, one common lineage and no new C/source. It describes the real primitive semantics and the stopping rule.

Successful parsed actions use the same persistent SQLite database. Every step records its actual environment transition. Parser/identity rejections explicitly have no destination action receipt and zero primitive/write/effect deltas; they are never relabelled as executed SQL. SQLite counters remain separate from repository patch-verifier and subprocess counters.

An immediately preceding actual readback of an unstaged unsatisfied row, followed by an apply with no effect, can be labelled an observed unstaged-apply error. A stale view after stage/apply cannot establish this error. Idempotent repeated apply is therefore not mislabelled as a failed recovery. Format-error and observed-unstaged-apply recovery flags require subsequent actual successful completion; ordinary intermediate incomplete states do not count as errors.

The destination stops on the actor's `stop`, a provider budget terminal result, or the twelve-decision limit. Predictor errors, identity mismatches and outputs larger than the frozen 8192-byte history bound are retained and end the attempt. The bounded-history rule does not truncate or replace raw saved output. No automatic retry, restart, model reload or reference fallback occurs.

## Evidence and costs

Every run creates a new directory containing:

- `STARTED.json` with protocol, actor/model identity, task/source lineage, input/message and executable source digests.
- `request-N.json`, `call-started-N.json`, `output-N.json` and `step-N.json` for every actual predictor attempt.
- The ordered final `MESSAGES.json`, hash-linked step receipts, final `RESULT.json`, and the destination's original `TASK.json`, `ACTIONS.jsonl`, `RESULT.json` and `destination.db`.

The call-started receipt precedes the call. An interrupted process that leaves only this receipt remains an unresolved attempt; absence of a return is not a successful or free call. Returned errors retain their exception type/message and unknown usage. Provider token/usage/charge fields remain in the raw output. Aggregate token totals are null when any required measurement is missing; known subsets are labelled separately. No missing fee is converted to zero. The probe records actual measured wall and local process CPU; load/close, remote/service/GPU CPU, monetary invoices and full-system cost remain outside this measurement. Nested predictor-call and total-task wall measurements must not be added together.

These files are local reviewable evidence, not independently authenticated owner receipts. A real model run must retain the root loader's exact manifest and weight identity, runtime configuration and complete load/close measurements separately.

## Actual engineering verification

The final source in `probe-engineering-check-02/RESULT.json` ran four integration tests with explicitly scripted predictors and actual SQLite execution. They check:

1. A raw JSON format error and an observed unstaged apply are preserved, followed by real success through appended feedback.
2. Twelve invalid outputs exhaust the decision budget with zero SQLite primitives and no replacement actions.
3. A returned model-digest mismatch is saved and rejected before any effect.
4. All three task destinations reach their actual prescribed state, preserve an already satisfied row, and permit idempotent retries without false error labels.

All four tests passed. The earlier successful check remains in `probe-engineering-check-01` at its own source identity; the second check adds the stale-readback/idempotent-apply correction. No result is transferred between source identities.

`scripted-agent-probe-01` preserves an additional reviewable scripted execution: seven predictor decisions, one malformed output, one observed unstaged apply, five actual SQLite primitive calls, one applied effect, final success and both recovery flags. Its model-call count is zero; token and monetary costs are unknown rather than invented. This replay is not another independent task or source. No model, training job, new C, native Cell adoption or production process was launched in this handoff.

The separate `SOURCE_PUBLICATION_REVIEW_V3.json` covers the seventeen captured original source files only, including decompressed trajectory bytes. All prior file hashes matched; eight credential-pattern classes found no hits, and content review identified no credential material. Public GitHub account fields and local provenance paths were retained. Later model outputs and exception messages require their own publication review and are outside that source-file check.
