# Read-only historical content audit

The auditor reads an externally SHA-pinned manifest of original trajectories,
numbered snapshots and evaluator receipts. An optional explicitly supplied private
reference permits normalized candidate comparisons. It never changes originals
and emits no candidate or reference text. Byte integrity relative to caller pins
does not authenticate observer authority. Do not publish low-entropy private text
digests as if they were anonymous.

It separates action-to-delivery continuity, evaluator consumption of those exact
bytes, reference-candidate availability, delivered-text correctness and text-score
agreement. Legacy missing selected indices remain unknown, including when the
payload uniquely matches a recorded candidate. Same-case artifact joins and the
scorer's reference identity are checked before reference-based diagnosis.

## Actual retained-host audit

[ORIGINAL_CONTENT_REPLAY.json](ORIGINAL_CONTENT_REPLAY.json) records a post hoc,
read-only audit and frozen-model replay of the six previously declared diagnostic
WRITE_TEXT episodes. The original collection plan, diagnostic JSONL and weights
matched their prior pins; all 60 source-file pins were verified. Reference
comparisons in this replay used the hash-bound original diagnostic row fields.

- All six candidate sets contained a normalized reference match.
- All six frozen-model argmax texts failed that reference comparison and matched
  the original serialized action text. Top-two logit margins were 1.4152–5.4140.
- All six action texts reached the immediate and terminal delivery unchanged.
- All six evaluator receipts bound the actual delivery bytes; their zero text
  scores agreed with the delivered texts.

This identifies candidate ranking/selection as the failing stage under the pinned
replay. It found no downstream payload, delivery or text-scoring discrepancy in
these six cases. Exact historical selected indices remain unrecorded; one payload
matched two candidate entries. The replay does not reconstruct a missing original
selection receipt or establish why the learned ranking failed.

The successful replay executed the strengthened auditor before formatting, SHA256
`a41c6f2fae3439b9b1a081c7873d53cff623545256231af3bee94f03bd3a0b48`.
Its exact source bytes and runner are retained internally with the original run;
subsequent repository formatting does not replace those executed bytes. The
aggregate identifies that execution snapshot, rather than asserting that the
formatted file was executed on the retained host. Independent process-output and
stdout-file reads matched: 7,512 bytes, exit 0, no stderr or truncation. Their SHA256
is recorded in the aggregate. Worker time was 0.7247 seconds including Torch
import; HeptaRuntime control-plane transport is outside that interval.

No originals or model parameters changed. This is an audit of the declared six
cases, not a new confirmation sample or a demonstrated policy benefit. Action
realization was successful even though choice quality was zero; those labels must
remain separate. The published aggregate excludes per-case content hashes, text,
labels and private paths. Observer authority remains unauthenticated.

Manufactured-artifact tests separately cover deliberate substitutions and missing
references. They validate auditor behavior, not the historical findings above.

```sh
PYTHONPATH=scripts python -m unittest ndu_real_runtime.test_audit_content_trace -v
PYTHONPATH=scripts python -m ndu_real_runtime.audit_content_trace --help
```
