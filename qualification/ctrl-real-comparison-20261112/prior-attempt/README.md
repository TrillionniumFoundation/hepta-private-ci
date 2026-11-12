# Prior CTRL attempt: preserved failure evidence

The original prospective attempt at source `0bc9cbac00a21aae25af1a96ccbedbf3707cfa4c`
completed **125 of 126 planned matched collection pairs** and stopped during fit.
Its durable job `1a1ce4e986b-2564-15fa` is authoritatively **failed, exit 1**;
both log streams are complete, durable and untruncated. The original wrapper
never reached `evaluate`. This evidence supports a real collection attempt and
an enforced incomplete-denominator gate, not a policy-benefit result.

## Failure that remains in the denominator

`p0027-READ` executed `PREPARE_ROI`, `READ_ROI`, and `WRITE_TEXT`, then terminated
`BudgetStop` without `STOP`. The final decision used 22.736716047 seconds,
including 22.706838862 seconds in the encoder. Its gross score 1.0 and native
process exit 0 do not satisfy the declared macro. The ledger recorded
`Actual branch did not complete the declared macro`. The fit gate reported
`Incomplete planned collection cannot supply fitting rows`. The missing pair
is preserved as failed/unresolved; it was not dropped, re-run or recoded.

The final prior freeze planned **4 evaluation contexts × 6 methods = 24 actors**.
The earlier preparation report's 12 candidate contexts must not replace that
denominator. The count of 4 is attributed to the root agent's direct prior
FROZEN readback (`1a1ce66fd3a`); the historical local progress file independently
records 24 planned actors. Raw FROZEN bytes are not included in this package.

## Files and evidence strength

| Location | Contents and boundary |
| --- | --- |
| `originals/` | Nine small original JSON receipts restored from previously retrieved text and verified against their original remote SHA256s; complete original business stdout/stderr; a historical local planning record; verbatim selected ranges of a read-only diagnostic stdout. |
| `normalized/durable-job-status.json` | Previously obtained authoritative API terminal status plus parsed job records. This is not an exact-byte copy of remote `exit.json` or its witness. |
| `normalized/original-request.json` | Exact parsed executable, argument list, cwd and timeout, along with original request path and SHA. Only selected request fields were retained. |
| `normalized/freeze-summary.json` | Original source/freeze/input/export pins and planned denominators, with provenance and gaps. |
| `normalized/failure-summary.json` | Failure timing and the evaluate-not-started proof. Original p0027 result, trajectory and launch paths plus SHA256s are preserved; their full bytes are not included. |
| `normalized/retrieval-limits.json` | Later transport timeouts and an unresolved read-only diagnostic request, kept distinct from the already reconciled failed business job. |
| `MANIFEST.json` | Byte counts, local SHA256s, evidence kind and origin for every package file other than the manifest itself. |

The nine restored JSON files matched all nine previously recorded remote
SHA256s. The business logs contain 430 stdout bytes and 1,342 stderr bytes,
matching the authoritative job counts. The retained diagnostic stdout was
28,035 bytes; only its branch/timing and original job records are included,
with exact source byte ranges in the manifest. An irrelevant historical
content-checkpoint inventory was omitted. No model weights, private reference
answers, sealed packets or source image bodies are included.

## Interpretation and retrieval limits

The original request executes collect, export, fit, and evaluate in order with
`check=True`. Complete stdout ends at fit STARTING; complete stderr records fit
failure and `CalledProcessError`; authoritative status confirms terminal exit 1.
Together these establish that this wrapper launched no evaluation actors.
No new claim about filesystem absence is needed for that conclusion.

The registered development sources were already exposed research material.
Control train/calibration separation does not establish that the common content
checkpoint had no historical exposure. There was no completed control fit,
cold load, six-policy comparison or content-by-control 2×2 result in this attempt.

This package was assembled locally from retained evidence after further remote
readbacks timed out. No new actor, resume or experiment was performed. The
later read-only snapshot request remains UNKNOWN without a returned job ID;
it does not change the original business job's known failed outcome.
