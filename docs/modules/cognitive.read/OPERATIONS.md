# `cognitive.read` operations and alert contract

Status: source implemented; exact-head qualification pending; `activation=false`.

This runbook defines the production-facing, low-cardinality signals emitted by the Agentd cognitive read composition. It does not elevate a read result to authority and it does not replace final-use revalidation.

## Signal inventory

The in-process counters track requests, selected records, missing IDs, payload bytes, total wire bytes, budget rejections, final-use revalidation failures, stale-cut rejections, alert emissions, and cumulative latency in microseconds. The counter names are intentionally stable and must not use record IDs, owner IDs, query text, content, receipts, or digests as labels.

Structured log events provide the export boundary:

- `cognitive_context_revalidation_failure` at warning level for a candidate that is not current at final use;
- `cognitive_context_stale_cut` at warning level when the source cut changes before publication;
- `cognitive_context_revalidation_alert` at error level whenever the bounded failure count reaches another multiple of `REVALIDATION_ALERT_THRESHOLD_PER_MINUTE` within `REVALIDATION_ALERT_WINDOW_SECONDS`.

Compiled alert constants:

- `REVALIDATION_ALERT_THRESHOLD_PER_MINUTE = 3`;
- `REVALIDATION_ALERT_WINDOW_SECONDS = 60`.

The threshold deliberately emits again at bounded multiples (3, 6, 9, ...) in one window. This avoids a single edge-trigger being lost while preventing one error log per rejected candidate.

## Alert policy

Route `target=hepta.cognitive_read` and `event=cognitive_context_revalidation_alert` into the production error stream. Open an operator incident when at least one such event occurs in five minutes. Escalate immediately when the same Agentd generation also reports source-owner corruption, an unexpected generation transition, or a product request that bypassed final-use revalidation.

Routine candidate rejection remains fail-closed and does not invalidate the canonical store. Repeated rejection is operationally significant because it can indicate a rapidly changing owner cut, stale retrieval bindings, clock or generation skew, or a caller retaining a result longer than its permitted use boundary.

## Operator runbook

1. Confirm the exact Agentd binary commit, process generation, and current qualification receipt.
2. Confirm that the owner scope and generation in the read binding match the active owner cut.
3. Inspect warning events immediately preceding the alert and classify them as candidate-not-current or stale-source-cut. Do not log or copy memory content into the incident.
4. Verify that the worker repeated `cognitive.context.revalidate@1` immediately before `TurnStart` and that no fallback path consumed an unvalidated transient projection.
5. Replay the bounded product smoke against an isolated store. Preserve command records, exit codes, and the immutable artifact digest.
6. Keep `activation=false` if the alert is reproducible, if `CI required` or `Architecture required` is not successful on the exact candidate, or if the evidence bundle is absent or does not match its SHA-256 manifest.

## Evidence retention

`.github/workflows/cognitive-read-qualification.yml` publishes separate exact-head and deterministic synthetic-merge bundles. Each bundle contains command lines, complete logs, exit codes, benchmark JSON, an exact-head qualification receipt, `SHA256SUMS`, a deterministic tar archive, and its SHA-256 digest. GitHub's upload-artifact digest is additionally written to the job summary.

The evidence bundle is proof about one immutable commit only. It never changes the implementation map's activation field and it cannot be reused after source, dependency, product-composition, or workflow bytes change.
