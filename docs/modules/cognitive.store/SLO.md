# Cognitive store SLO and capacity profile

These are qualification targets, not claims about an unmeasured host.

- Correctness: zero acknowledged mutations without a committed receipt; zero cross-owner reads/writes; zero resurrection after a committed tombstone or current-witness rollback rejection.
- Availability: 99.9% successful bounded local read/revalidation operations over a 30-day target-host window, excluding explicit security denial.
- Latency targets: p99 local semantic commit <= 100 ms at the 256-record profile; p99 exact-ID read/revalidation <= 50 ms; cold reopen <= 2 s; 16,384-record snapshot/profile measurements must complete inside the dedicated CI command deadline.
- Growth: report database, WAL/journal and recovery-generation bytes; alert at 70% and stop new ordinary writes before the qualified hard limit.
- Recovery: crash/reopen RTO <= 60 s on the selected host; RPO is the last acknowledged SQLite FULL commit.  Descriptor-safe recovery requires the exact independently retained witness.

The workflow records p50/p95/p99/max, file bytes, cold-open, recovery-anchor and reopen cost for 256 and 16,384 records.  Threshold promotion requires target-host evidence and operator approval; repository CI artifacts alone do not activate production.
