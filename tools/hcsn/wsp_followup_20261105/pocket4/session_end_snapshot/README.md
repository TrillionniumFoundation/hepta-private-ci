# Session-end pocket4 read-only delta — 2026-11-04 21:59 EST

This is a new observation after the preserved 20:55 EST snapshot. The earlier
`final_snapshot` directory's seven published files remain byte-identical; their
sizes and SHA-256 identities are included in `delta.json`. No earlier observation
is replaced or treated as current.

The trainer status source time is **2026-11-04 21:59:10.883 EST**
(**2026-11-05 02:59:10.883 UTC**). The strict audit finished at
**21:59:16.280 EST / 02:59:16.280 UTC**. Its unchanged source binds the active
trainer process, effective service arguments, guardian configuration, original
configuration, selected job/candidate, candidate manifest and actual adapter
bytes. It rechecks the live process and selected job/candidate at the end.

## Delta from the preserved 20:55 EST observation

| Item | 20:55 EST observation | 21:59 EST observation |
| --- | --- | --- |
| Running / completed / failed / admitted jobs | 0 / 114 / 2 / 0 | 0 / 114 / 2 / 0 |
| Pending evaluations | 0 | 0 |
| Completed candidates without a forward trial | 43 | 43 |
| Candidate, job, manifest and configuration identities | Bound | All unchanged |
| Adapter SHA-256 | `94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0` | Unchanged |
| Adapter layout | 9,988 bytes, 6 F32 tensors, 2,379 parameters | Unchanged; all finite, complete and nonoverlapping |
| Forward worker / trial | Neither launched nor allocated | Neither launched nor allocated |
| Direct host MemAvailable | 15,506,224 KiB | 14,394,000 KiB |
| Direct host SwapFree | 2,787,348 KiB | 4,076,744 KiB |
| Current full memory PSI avg10 / avg60 / avg300 | 0 / 0 / 0 | 0 / 0 / 0 |
| Trainer / evaluator restart counters | 0 / 0 | 0 / 0 |
| Execution service restart counter | 3,738 | 3,863; increase 125 |

The phase remains `CANDIDATE_READY_AWAITING_FORWARD_ADMISSION`. Current blockers
remain:

- `CANDIDATE_READY_AWAITING_FORWARD_ADMISSION`
- `LATEST_SOURCE_QUOTE_NOT_FRESH`
- `SOURCE_CONTINUITY_NOT_READY`
- `SOURCE_QUALITY_HOLD_NO_REFRESH_AUTHORITY`

The forward preflight does not admit a new worker. Fresh original live-source
evidence remains unproven; its source probe remains held. Current memory
pressure is not the reported admission blocker. Existing trainer/evaluator
6 GiB limits and CPU quotas were only read and remain unchanged. Direct host
measurements and the earlier preflight memory sample are not simultaneous.
Zero current moving averages do not establish zero stalls throughout the
interval, and occupied swap alone does not establish current thrashing.

The execution service remains `activating / auto-restart`. This observation
queried no new journal messages. It establishes the counter increase without
identifying a current rejection branch or carrying forward a historical root
cause. The earlier bounded error diagnostic remains separately scoped.

## Evidence, privacy and limits

`public_snapshot.json` and `capture_receipt.json` are the exact new files emitted
by the unchanged capture wrapper and sanitizer. Their transferred bytes were
verified by size and SHA-256. The private original audit stdout remains on the
observed host; only its hash and size are published. No private training rows,
parameter values, account/order identifiers, ledger records or host paths are
included. The unchanged `capture_final.py` filename and capture schema are
retained to preserve its source identity; this directory identifies the new
session-end observation.

This is not an atomic cross-file snapshot. It authenticates current file bytes,
service arguments and stable live-process identity, not the process's in-memory
configuration. The frozen base weights and readout were not rehashed. No model
forward, training, broker query, order, admission change, service change or live
model-pointer change was performed. No model efficacy or prior experimental
benefit is transferred to this candidate. The only writes were isolated
research capture and report files.

## Measured cost

The strict audit reported **0.045871349 seconds wall**, **0.007137010 seconds
process CPU**, and **23,836 KiB maximum RSS**. These are nested inside the capture
wrapper and must not be added to it.

The capture wrapper reported **0.163880461 seconds wall**, **0.003542868 seconds
own CPU**, **0.086554 seconds owned-child user CPU** and **0.031687 seconds
owned-child system CPU**. The wrapper-scope CPU sum is **0.121783868 seconds**.
That interval includes active-config selection, the auditor subprocess and the
sanitizer subprocess. Wrapper imports/startup, remote staging/dispatch,
transfer, local verification/report work and agent computation are outside
that measured interval. The audit RSS is not an aggregate host/process-tree
memory measurement.

## Independent record check

Run `python3 -B verify_records.py` from this directory in the published package.
It verifies the archive manifest, source/receipt/snapshot bindings, recorded
invariants, the delta, and the seven immutable files of the adjacent prior
snapshot. For a separately staged copy, pass the exact prior public snapshot as
`--prior /path/to/final_snapshot/public_snapshot.json`. This reads records only;
it does not contact pocket4 or execute a model.

To obtain another authorized observation, use unchanged parent `audit_live.py`
and `sanitize_export.py`, the exact hashes recorded in `capture_receipt.json`,
and a new private output directory with `capture_final.py`. Never publish its
private audit stdout or silently replace a failed binding with another model.
