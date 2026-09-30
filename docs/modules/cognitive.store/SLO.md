# cognitive.store candidate SLO and capacity policy

These are qualification objectives, not measured deployment claims. A selected host profile must publish exact-run metrics before activation.

## Profiles

| Profile | Purpose | Required workload |
|---|---|---|
| `PERF-DURABLE-256` | normal candidate latency | 256 committed records plus reopen/snapshot/recovery-anchor measurements |
| `PERF-DURABLE-16384` | maximum retained pilot | 16,384 committed records plus database/WAL bytes, paging and reopen |
| `FAULT-RECOVERY` | crash behavior | child kill at named transaction/recovery boundaries, then reopen and exact-cut comparison |
| `BOOTSTRAP-HOST` | product admission | signed bundle verify, descriptor recovery, canary, rotation/restart and live revocation |

## Initial objectives

| Signal | Candidate objective |
|---|---:|
| 256-profile commit p95 | <= 50 ms on selected local SSD host |
| 256-profile commit p99 | <= 100 ms |
| exact-id read p95 | <= 20 ms for <= 128 ids |
| 512-head snapshot page p95 | <= 250 ms at maximum retained pilot |
| ordinary reopen p95 | <= 2 s at 16,384 records |
| signed bootstrap plus exact-cut recovery p95 | <= 10 s excluding operator signing time |
| live authority revalidation p95 | <= 10 ms from local external state storage |
| crash/reopen data loss | zero committed revisions; zero tentative revisions visible |
| stale-backup acceptance | zero |
| blind replay after indeterminate outcome | zero |

A host may adopt stricter thresholds. Relaxation requires a versioned host profile and review; it cannot be hidden in prose.

## Capacity ceilings

Current pilot bounds include 16,384 whole-scope immutable revisions, page sizes up to 512 heads, 65,536 citations/source rows per declared durable bound and bounded recovery rows/bytes. Crossing a hard bound returns an explicit capacity/unavailable result before partial publication. It never triggers silent pruning.

## Required metrics

- cold/warm commit p50/p95/p99/max;
- read and page latency by selected count/encoded bytes;
- SQLite database, WAL, journal and recovery-generation bytes;
- process RSS and peak temporary-copy bytes;
- recovery-anchor capture and exact-cut comparison;
- ordinary reopen, descriptor recovery and checkpoint duration;
- canary remember/tombstone duration;
- authority file verification and revocation-detection latency;
- archive/rebuild metrics once ADR-0001 is implemented.

## Alerts and stop conditions

Stop write admission on schema/integrity failure, current-cut mismatch, signer/token mismatch, revocation, writer-generation conflict, persistent capacity exhaustion or active-pointer ambiguity. Latency alerts do not bypass correctness; overload rejects before mutation.
