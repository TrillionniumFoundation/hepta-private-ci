# Final pocket4 read-only delta — 2026-11-04 20:55 EST

This is a new observation. The preceding 19:42 EST observation and its original
evidence are retained unchanged in the parent directory. The unchanged strict
auditor binds the active trainer process, effective service configuration,
original configuration, status-selected job and candidate, candidate manifest,
and actual small adapter bytes. It repeats the process/config/candidate binding
checks at the end. The source time is **2026-11-04 20:55:07.134 EST**
(**2026-11-05 01:55:07.134 UTC**); the static audit finished at
**20:55:09.230 EST / 01:55:09.230 UTC**.

## Observed difference

| Item | Prior 19:42 EST | Final 20:55 EST |
| --- | --- | --- |
| Running / completed / failed / admitted jobs | 0 / 114 / 2 / 0 | 0 / 114 / 2 / 0 |
| Pending evaluations | 0 | 0 |
| Completed candidates without a forward trial | 43 | 43 |
| Selected candidate and job identity | Bound | Same identities |
| Adapter content | SHA-256 `94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0` | Same content |
| Adapter layout | 9,988 bytes, 6 F32 tensors, 2,379 parameters | Same; all finite and complete, nonoverlapping layout |
| Forward worker / trial | Neither launched nor allocated | Unchanged |
| Available host memory | 15,858,080 KiB | 15,506,224 KiB |
| Current full memory PSI avg10 / avg60 | 0 / 0 | 0 / 0; avg300 also 0 |
| Trainer and evaluator restarts | 0 / 0 | 0 / 0 |
| Execution service restart counter | 3,597 | 3,738; increase 141 |

Candidate manifest, bound job configuration, guardian configuration and original
configuration hashes also remain equal. The current state remains
`CANDIDATE_READY_AWAITING_FORWARD_ADMISSION`. Current blockers remain:

- `CANDIDATE_READY_AWAITING_FORWARD_ADMISSION`
- `LATEST_SOURCE_QUOTE_NOT_FRESH`
- `SOURCE_CONTINUITY_NOT_READY`
- `SOURCE_QUALITY_HOLD_NO_REFRESH_AUTHORITY`

Current memory pressure is not the reported forward admission blocker in this
observation. Existing 6 GiB trainer/evaluator caps were only read. The preflight
memory sample and direct host-memory sample have different observation times and
must not be treated as a single atomic measurement. Occupied swap alone is not
evidence of current thrashing.

The execution service still reports `activating / auto-restart`. This delta does
not query its journal. It establishes the counter increase only; it does not
reverify a current error branch, identify a root cause, or transfer a historical
ledger explanation. The earlier bounded diagnostic remains separately scoped.

## Binding, privacy and limits

`public_snapshot.json` is the explicit aggregate projection produced by the
previously frozen sanitizer. The private original audit output remains on the
observed host; only its SHA-256 and size are included. No per-row records,
parameter values, account identifiers, order identifiers or private paths are
published. `capture_receipt.json` records the unchanged audit and sanitizer
hashes and the new capture source hash. `delta.json` binds both public snapshots
and records the comparison checks.

The observation is not an atomic cross-file snapshot. The current files,
service arguments and stable live-process identity are verified; in-memory
configuration contents are not attested. The frozen base model and frozen
readout were not rehashed. This is not a model forward, held-out evaluation,
new training run, profitable strategy result or full Trader-to-Hepta-Neuron
semantic mapping. No prior experimental improvement is transferred to this
checkpoint.

No services, resource limits, training jobs, broker state, orders or live model
pointers were changed. The only writes were new research capture files.

## Cost

The strict audit reported 0.044337 seconds wall time, 0.006798 seconds process CPU
and a 23,868 KiB maximum RSS. The capture wrapper, which includes selection,
the auditor subprocess and public projection, reported 0.164027 seconds wall,
0.003851 seconds own CPU and 0.116518 seconds child CPU. Its CPU total is
0.120369 seconds over that measured scope. The inner audit measurements are
nested and must not be added again. Wrapper imports/startup, remote dispatch,
source transfer, report preparation and agent computation are excluded.

## Independent record check and repeat observation

From this directory, run `python3 -B verify_records.py`. It verifies the public
file manifest, receipt-to-source bindings and recorded invariants. With the
parent snapshot available it also rechecks the delta comparison. This is a
record check, not a new remote observation or efficacy test.

To repeat the observation on an already authorized host, supply the unchanged
parent `audit_live.py` and `sanitize_export.py` to `capture_final.py`, with their
exact SHA-256 values from `capture_receipt.json`, and a new private output
directory. The wrapper selects the active trainer process's actual `--config`
argument; it does not assume a unit fragment or historical file is effective.
Never publish the resulting `private_audit_stdout.json`; use the explicit
projection only. A changed identity, file or unsupported schema must remain a
failed capture rather than silently selecting another checkpoint.
