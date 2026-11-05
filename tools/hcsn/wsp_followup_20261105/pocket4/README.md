# Current pocket4 candidate: bounded read-only audit

**Static checkpoint integrity passed. Model efficacy, a Hepta semantic mapping,
and forward admission remain unqualified. No model was loaded or evaluated.**

The successful observation was at **2026-11-05 00:42:42 UTC**, or
**2026-11-04 19:42:42 America/New_York**. Its bound status source was written at
00:42:26 UTC. It replaces older snapshots for this narrow observation only.

## Current training and candidate identity

The active trainer's effective systemd configuration and actual running process
arguments were checked. The selected guardian's actual SHA-256 was
b6760d5a84266efc7e70e174a4b87139763fc59d824f6b42839cfb172b5334e0;
the original configuration content hash was
ffde1187e1fc0d28c893328920ae0f6a6a70615adad51fadcdfc85287bd54527.
The guardian's declaration matched that actual original configuration hash.
Configuration filenames were not treated as content hashes.

The queue was RUNNING 0, COMPLETED 114, FAILED 2, ADMITTED 0, with zero pending
evaluations. The state was CANDIDATE_READY_AWAITING_FORWARD_ADMISSION.
There were 43 completed candidates without a forward trial and one blocking
deferred training candidate. A missing forward trial is not a performance
rejection or evidence of value.

The bound candidate is
8fe51f354c8a75001b0948c3588cab7d62dcb54c90f932f32e7bf9eb1505bf5a,
created at 22:17:07 UTC / 17:17:07 New York. The audit followed the configured
state root and the registered job's declared output directory. It did not
guess an artifact path from the candidate ID.

Its actual adapter is **9,988 bytes, six F32 tensors, 2,379 parameters**, SHA-256
**94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0**.
Every parameter was finite, tensor intervals covered the data exactly without
overlap, and the candidate manifest's adapter commitment matched actual bytes.
The active process identity and current candidate/job identity stayed the same
at the end of the bounded read. The two status reads also had identical bytes.
This is not an atomic cross-file snapshot and does not reserve future state.

| Tensor | Shape | Parameters |
|---|---|---:|
| model.act_head.2.A | 1 by 64 | 64 |
| model.act_head.2.B | 2 by 1 | 2 |
| model.scorer.1.A | 2 by 768 | 1,536 |
| model.scorer.1.B | 4 by 2 | 8 |
| model.scorer.3.A | 1 by 768 | 768 |
| model.scorer.3.B | 1 by 1 | 1 |

This identity differs from both the previous morning's small adapter and the
original replay checkpoint. Earlier 54-row outcomes cannot be assigned to it.
The base model and frozen readout were not rehashed in this audit, and a full
semantic equivalence between this Trader adapter and Hepta Neuron's six
proposed components was not established.

## What the candidate's training receipt says

The declared candidate metrics were read from the bound manifest, not rerun:
parent/candidate cross entropy 2.3527059890 / 2.3504293710 and Brier loss
0.9836789630 / 0.9829791058. These use **training-only measurements on 32 rows**.
They do not establish out-of-sample quality or task value. The candidate status
explicitly requires independent future evaluation. The price-calibration
model weight is approximately 0.0397510, with no independent calibration rows.

The completion counter is not a counter of cumulative training updates.
Each job resets its optimizer and starts from its configured parent. Within
the price episode, four epochs use continuous optimizer state, at most 64
steps, 32 unique rows and batches of two. The separate ACT-only AdamW phase
has at most 80 steps and 40 unique rows over four epochs, with encoder and
price parameters excluded. Repeated presentations are not independent rows.

The manifest reports a 100.9038-second training wall time and 1,591,958,016
peak GPU allocator bytes for that candidate. These are pre-existing worker
measurements, not costs of this audit or a paired direct-edit comparison.
No new price/ACT training, forward evaluation, weight editing, broker query,
order, service change or live activation occurred in this audit.

## Current blockers and resources

The current blockers are candidate forward admission, a stale authoritative
quote, source continuity not ready and source-quality hold without refresh
authority. The cached diagnostic had zero usable and 24 unusable probes;
it did not prove a fresh original live source or launch a worker.

At observation, MemAvailable was 15,858,080 KiB out of 25,739,556 KiB.
Memory PSI full/some averages were 0.00 over 10 and 60 seconds and 0.17 over
300 seconds. This snapshot does not support the previous acute memory blocker
as the current blocking cause. The historical cause of earlier pressure was
not established. SwapFree was 2,179,316 KiB; occupied swap alone does not prove
current memory thrashing. Host load averages were 4.465, 5.004 and 5.264 across
24 logical CPUs. No capacity reservation is implied.

Both trainer and evaluator retained their pre-existing 6-GiB memory high/max
limits. The trainer's current service memory accounting was about 684 MiB and its service
peak about 4.00 GiB; evaluator current accounting was about 36 MiB and peak
about 3.12 GiB. Their service restart counters were zero. Limits were not changed.

The execution service was in auto-restart with **3,597 accumulated restarts**.
The separate bounded journal observation at 00:08:42 UTC requested 15 minutes
and returned a capped 200 records spanning approximately 738.89 seconds,
including 25 occurrences of the startup rejection family
IB_FX_CASH_RESTART_CATCHUP_EXECUTION_INVALID and status 6/NOTCONFIGURED.
The final seven retained restart-counter samples rose from 3,525 to 3,531,
roughly once every 30.75 to 31.00 seconds, consistent with the existing
30-second restart configuration. This is a bounded recent sample, not the
complete incident history.

The public source maps that one rejection code to several distinct checks:
correlation and side mismatches, missing baselines, unsafe position/cash
deltas, unresolved accepted submissions, and advanced-baseline validation.
The inspected source revision is identified in execution_restart_diagnostic.json;
the deployed binary was not bound to that revision. Therefore the current log
does not prove one specific branch, nor may an old ledger failure be carried
forward as today's root cause. No current ledger was replayed. The next
bounded offline step is reason-specific diagnostics against a separately
frozen, authorized ledger plus the exact deployed source/binary identity.
Weakening admission or restarting trading to obtain evidence is not justified.

## Preserved failure and publication boundary

The first strict audit attempt failed at 00:36:05 UTC with
EFFECTIVE_SERVICE_CONFIG_MISMATCH, before any adapter read. It had followed
the main unit fragment; a later effective systemd override selected another
guardian. Its source and failure receipt are retained as attempt_1_source.py
and attempt_1_failed.json. The second version added actual running-PID/config
binding and used the observed effective guardian. No identity gate was relaxed.

The executed second source is audit_live.py, SHA-256
76b5c2e7bd36e25c8fa2d371ed44648ba3e157c94d014a5a1456193dafae90d7.
Its **raw stdout is private** because selected.steps included per-step training
row identifiers. Do not publish its direct output. The unchanged raw stdout
has 111,818 bytes and SHA-256
1d13362c985910b3a9da55a32008a8f49b476e692aac672a4c14e566d466dab0.
The public current_candidate_audit.json is an explicit whitelist derivative
created by sanitize_export.py. It contains no raw steps, private row IDs,
parameter values, account/order IDs or host source paths. The derivation and
raw commitment are explicit; the frozen audit source was not silently changed.

The successful audit's own measured wall/CPU times were 0.039200 / 0.006216
seconds, with 23,672 KiB maximum RSS. The failed attempt used 0.008775 / 0.001484
seconds and 22,276 KiB maximum RSS. These exclude earlier discovery commands,
remote dispatch, result transfer, agent time and report construction. They
are not end-to-end research or model-training cost estimates.

## Verify or repeat

Run the public record verifier:

    python verify_records.py

It validates source and receipt identities, schema binding, static counts,
scope, status consistency and the preserved failure. It does not independently
load the private checkpoint or rerun the current live audit.

An authorized operator can repeat audit_live.py with the actual effective
guardian path and its actual content SHA-256, capturing stdout to a private
file. Then use the separate whitelist exporter:

    python sanitize_export.py --private-stdout PRIVATE_JSON --public-output NEW_PUBLIC_JSON

Live snapshots may change; a new run should retain its own timestamp, source
identity, result and output path. Do not overwrite this frozen observation.
