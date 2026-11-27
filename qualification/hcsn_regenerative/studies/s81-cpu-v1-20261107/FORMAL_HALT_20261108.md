# CPU V1: first formal submission halted with unresolved remote effect

This is an append-only update to the qualified and frozen CPU study in PR #5327.
The existing 93 source files and the frozen plan remain unchanged. The numerical
qualification and original 400-update feasibility evidence remain valid within
their original scope. No formal fit completion has been verified.

## What happened

The unique formal native owner passed its actual pre-execution admission,
reserved the first 20 of the registered 160 fits, and made one provider submit.
The adapter completed its owned-notebook enumeration, persisted a `SaveKernel`
intent, and then received HTTP 400 `INVALID_ARGUMENT`. Its durable state is
`UNKNOWN` / `MAY_HAVE_BEEN_SENT`, with no verified remote identity or accepted
completion capsule.

One subsequent same-request, official read-only resume received HTTP 403
`PERMISSION_DENIED`, naming `kernelSessions.get`. The original request file is
byte-for-byte unchanged after that query. The GET's `remote_effect_unknown=false`
describes that GET; it does not resolve the earlier submission's unknown effect.

| Quantity | Observed status |
|---|---|
| Native owner | Failed, exit 1; complete and durable terminal; no timeout |
| Locally reserved fits | 20 |
| Locally unstarted fits | 140 |
| Locally ever claimed fits | 0 |
| Verified formal fit completions | 0 |
| Actual remote fits or optimizer updates | Unknown |
| Released reservations or replayed submission | 0 |
| Success-analysis watcher | Not launched |

The first adapter call took 5.512123387 seconds within a 5.753-second observed
native start-to-terminal span. The read-only query's native span was 3.014
seconds. These are different or nested cost scopes, not an additive full-cost
estimate. The complete accounting also retains a local diagnostic SyntaxError
and a separate diagnostic launch with unknown outcome. Physical energy and
monetary cost remain unknown.

## What is established about the submitted bytes

The actual source contains 1,091,095 bytes, SHA-256
`275c511e987354c973274855782cf49b4579ca598d2f43b219073c87b3c98861`.
The exact frozen builder reproduced those bytes locally without executing them.
The source is above 1 MiB and below the installed adapter's 2 MiB limit. The
response contains no field-specific explanation, so payload size remains a
diagnostic hypothesis, not the established cause of this failure.

## Continuation boundary

The original request and the 20 reservations remain halted. A legitimate
resolution of the permission barrier and authoritative observation of the
original request are needed before a reviewed continuation can proceed. The
frozen owner rejects HALTED state; directly restarting it is not recovery.
Changing the request identity, clearing the ledger, replacing source bytes, or
repeating the workload would not establish what happened to the original submit.

The registered 160 fits, 400 updates per fit, four independent training seeds,
learning rates, test episode seeds, and 480/3000/720-second resource rules remain
unchanged. The failed request receives no completion credit in this study or in
the original 170-run campaign. The expansion decision remains **HOLD**.

## Separate original 170-run progress and cost evidence

At the exact 2026-11-07 23:42:37 UTC progress snapshot, the original campaign had
39 of 170 registered completions, with its existing owner and watcher still
running. This is a dated partial-progress observation, not a final campaign
result. The historical B full-shape exit-1/OOM result remains preserved.

Six newly reconciled records (completion ordinals 34–39) contain 2,400 training
steps, 153,600 examples and 9,830,400 tokens. Their training-and-validation time
sum is 31,650.226679506 seconds, nested within 34,671.821142 seconds of observed
attempt spans. These two values must not be added. All six energy records are
missing. The earlier 33-record raw cost ledger was not recovered or reverified
in this increment; no complete 39-run or 170-run cost total is claimed.

These original arms match hidden width, not parameter count: the six-record
increment includes 5,633-parameter `no_recovery` and 72,577-parameter
`hx_attention`. The original attention nondeterminism warning is retained.

## Evidence

- `FORMAL_HALT_STATUS_20261108.json`: exact failure classification, anonymous raw
  file commitments, local ledger counts and cost scopes.
- `FORMAL_HALT_INDEPENDENT_REVIEW_20261108.json`: separate review of the actual
  evidence and its inferential limits, including reviewer-role disclosure.
- `ORIGINAL_170_PROGRESS_20261107T234237Z.json`: dated original-campaign progress
  and the six-record cost increment, with its incomplete prior-cost scope.

All preceding plans, qualification files, OOM records and unsuccessful resource
attempts remain present in the parent history. This update does not claim
external-task benefit, retention, deployment readiness or measured physical
energy.
