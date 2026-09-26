# Knowledge graph continuation — 2026-09-26

## Source and scope

Continue PR #990 / `work/product-convergence-20260923`. No parallel KG branch,
fact owner, executor or incremental-writer promotion is introduced. Pre-existing
worktrees and concurrent tasks are preserved.

The baseline independently executed in this continuation is
`dc93634d07ba3bc6401be3f4cb24fe6b6dade1fa`, tree
`7cadcd97f4089cd508009149fd266a85699a986e`. Its 398 native library tests passed
with zero retries; eight explicitly ignored qualification cases were not
represented as passes. This includes migration/schema, KG oracle, memory,
prompt registry and optimizer libraries. These results are baseline evidence,
not an exact-head receipt for the following source changes.

## Changes and interpretation

- Preserve both Agentd E2E profiles and strict lint before the expensive CI
  capacity measurement. Failed source-map gates remain failed; they no longer
  suppress independently executable runtime prerequisites.
- Group the complete borrowed cognitive final-use payload in
  `CognitiveContextRevalidationInput`. The actual product consumer and all
  affected regressions use the same entry; current-owner validation is unchanged.
- Give only the explicit ignored full release benchmark a bounded 600-second
  measurement watchdog. Keep all 256 writes, queries, contention and reopen
  samples, zero retries, and unchanged ordinary product/correctness deadlines.
- Require complete capacity, generation, edge/support work, throughput and Linux
  RSS/CPU evidence. Keep raw failure logs and reject a valid-looking receipt from
  a nonzero process exit. Record the actual scratch filesystem and ambient load.
- Rebind changed cross-owner source observations through the existing mapping
  generator. Do not turn observation refresh into execution or acceptance.

## Measurements and remaining gates

The unchanged baseline release attempt exceeded its ordinary 60-second nextest
watchdog. At 64 writes, elapsed write time was 47,426 ms; no final performance
receipt was produced. Progress samples are not latency percentiles or an SLA.
The previous failed run remains failed after separating the measurement profile.

An isolated SQLite query-plan probe found no material VM-work reduction from
forcing the historical source-cut CTE to materialize. That experiment was not
promoted into the product. The selected writer remains complete generation
rebuild over immutable revision facts. Localized incremental promotion still
requires independent equivalence and measured end-to-end target-host benefit.

Exact tested SHA/tree, default/witness E2E, crash-matrix, strict-lint outcomes and
complete target-host JSON are recorded with the PR execution comment and retained
raw logs, not inferred from commands or this document. Missing or failed checks
remain blockers. No independent production acceptance, activation, merge or
release is claimed; module-wide production flags remain false.

Authorized desktop work and logs:
`/tmp/hepta-kg-resume-20260926-A8MUsm/`.
