# AuthBus end-to-end performance qualification

## Measurement boundary

A sample starts at product-caller request entry before signature verification and
ends only when the caller receives an explicit success or
`AuthBusMutationDisposition`. The measurement must include:

- signature verification;
- authority, identity, scope and policy validation;
- mutation-gate queueing;
- SQLite wait and transaction execution;
- incremental frontier update;
- checkpoint write, file fsync, rename and directory fsync;
- reconciliation when a committed mutation cannot publish immediately;
- product-caller acknowledgement.

A timer that begins after admission or stops at SQLite commit is not an AuthBus
end-to-end result.

## Required profiles

The machine-readable contract is
`PERFORMANCE_QUALIFICATION.json`. It requires fresh, medium-history and
long-history-with-active-reservations databases at concurrency 1, 8, 32 and
128, plus slow-storage, checkpoint-publication-failure and
recovery/backup-overlap cases.

Each case reports at least 200 samples and p50, p95, p99 and maximum latency for
every required stage and for the whole operation. Normal cases must report
success for every sample. Fault cases must report explicit disposition counts;
a timeout cannot be reclassified as not committed.

## Target-host harness

The protected target supplies the root-owned executable:

```text
/opt/hepta/authbus-qualification/performance
```

It is invoked with the exact candidate SHA, target profile, the repository
contract path and an output path. It writes a
`hepta.authbus.performance-receipt.v1` receipt plus a digest of retained raw
samples. `scripts/authbus-performance-evidence.py` rejects missing cases,
undersized datasets, percentile inversions, identity drift and disposition
counts that do not equal the sample count.

The validator emits a bound manifest but does not decide production thresholds.
Latency and capacity thresholds belong to the separately governed activation
decision because they depend on the selected target hardware, filesystem,
volume and product SLO.

## Interpretation

Repository CI proves that the contract and validator are internally consistent.
Only execution on the protected target proves target performance. A result from
another SHA, a different mount, synthetic delay without the selected storage
stack, or a receipt without raw-sample digest is not activation evidence.
