# N128 matrix-exponential resource development observation

Status: **POST_FREEZE_LOCAL_RESOURCE_DEVELOPMENT_NOT_ADMISSION / HOLD**

This file durably records an observer transcription from a local development
measurement performed on 2026-11-12 UTC after the source freeze in Draft
#6264 at `4dfa569b213d02859f76128ed09cacd7a829b91e`.

It is deliberately not presented as an original stdout artifact. The command
output was observed through the execution tool but was not written to a
durable file before the observation completed. No original stdout bytes, ZIP,
or precommitted request exist for this measurement. The values below must not
be used as qualification evidence or silently reconstructed into an
"original" later.

## Execution ledger

The first invocation attempted to use `/usr/bin/time`, which was absent. It
terminated with exit 127 before Python started and executed 0 matrix
exponentials.

A second local invocation materialized the four unique actual N128 operator
shapes from the frozen #6264 candidate lineage and executed one SciPy
`scipy.linalg.expm` call for each operator at `dt=0.2`:

| Dimension | Nonzero entries | Observed wall seconds |
| ---: | ---: | ---: |
| 1 | 0 | 0.000083 |
| 127 | 379 | 0.118 |
| 128 | 381 | 0.120 |
| 255 | 762 | 0.249 |

Observed aggregate accounting:

- actual matrix-exponential calls: 4;
- model forwards: 0;
- packet dynamics: 0;
- oracle calls: 0;
- Torch calls: 0;
- optimizer updates: 0;
- approximate summed per-call wall: 0.488 seconds;
- observed process CPU: approximately 3.589 seconds;
- observed maximum resident set size: 59,464 KiB.

The operator-identity strings were not retained in full in durable output and
are therefore intentionally not asserted here. Only the shape, nonzero-count,
call-count, and observed resource transcription is recorded.

## Interpretation and stop rule

This post-freeze measurement is useful only for designing a future, separately
source-frozen resource-profile admission. It does not close the #6264
requirements for a frozen dynamic core, packet alpha values, serializer,
full-state oracle, independently retained raw artifacts, or a durable
allocation.

No new numerical idempotency key is allocated by this evidence-only branch.
The four calls already occurred locally and are counted above; this commit does
not execute or repeat them.

It grants no N128 dynamic qualification, no N256/N512 qualification, no
current-state checkpoint qualification, no arbitrary-history or third-cycle
coverage, no C2 full replay, no HPCA benefit/custody result, and no production
adoption. Historical RED and UNKNOWN records remain unchanged. Global status
remains **HOLD / NoUpdate / all_closed=false**.
