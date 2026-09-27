# auth.authbus activation decision

Current decision: **BLOCKED — qualification in progress**.

The repository now contains the intended trust-boundary, owner-lifecycle, qualification and operations remediation, but activation is not inferred from source presence. The following gates must all bind the same candidate SHA/tree:

- sealed-registration closed-world inventory;
- focused AuthBus, evidence, Agentd and Bao product tests;
- owner collision, kill/restart and checkpoint fault injection;
- qualification package and owner all-target compilation;
- workspace regression and strict Clippy;
- exact-head and deterministic synthetic-merge success;
- clean tracked worktree after generators;
- source SHA/tree, schema digest, Cargo lock digest, test log digest and build artifact digest receipt;
- independent target-host ENOSPC/power-loss rehearsal;
- production KMS/HSM, trusted-time, checkpoint-volume and operator acceptance.

A later update may change this file to `APPROVED` only by naming immutable successful workflow run IDs and artifact digests. No queued, cancelled, skipped, deferred or prior-head result counts as success.
