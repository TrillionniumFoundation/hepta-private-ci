# Native source and execution evidence

## Final closed execution records

The [v2 index](../native-v2/index.json) and
[member manifest](../native-v2/members.json) describe **1,011 original records,
6,033,160 decoded bytes**, stored in four independent gzip tar parts. Every
delivered file is below 480,000 bytes; the largest part is 470,447 bytes. The
index SHA-256 is
`4665e038aff887d80aca4bcc5df688a33504d7606f61139e2d8e456a72276527`;
the member manifest SHA-256 is
`312979a8455e55ce70284160201fe84462537a559022b232483068c5ab3f55fd`.

This archive preserves both original native command files and independently read
controller stdout, stderr, terminal states and transfer checks. It contains the
original failures as well as successful tool preparation, formatter repairs,
the four-package product run, strict lint, complete-source checks, upstream merge
review and final JavaScript formatting publication. Distinct views of one
execution are not additional test executions. Tool binaries, Cargo targets and
the previously published stage1 payload are excluded.

The product receipts are members
`native/evidence/native-final-gates-08/tests.json` and
`native/evidence/native-final-gates-08/clippy.json` in `p001.tar.gz`. They bind clean
source `87cce8066b5f41e2d462b9469a301245f43d8c23`, complete tree
`60604de0d6ea4805fd248574ba83fe49f16b261a` and the unchanged Rust subtree. Their
original command-log SHA-256 values are respectively
`be7cb119b5ed389a430e2544e0ee7dad22c05d17b1563a046d2d9d66d39efdec` and
`337d289653bc16a27be1b48ad8e6dac2ec2bc3b51bdf4d12e499410812b9c301`.
The raw nextest summary is **990 passed, 66 skipped, 31 binaries, one slow test**;
strict Clippy exited zero. See [the validation report](../VALIDATION.md) for the
original commands, source limits and separate CI observations.

Native07 remains an aggregate failure: its full caller proof exceeded the
900-second budget and its original full Prettier glob found 31 existing app
files. The independent local caller pass is stored separately under
[`audit/final-caller.json`](../audit/final-caller.json). The strict AST repair
retains actual template raw values; its original helper error remains preserved.
The three unchanged full-tree Ruff diagnostic drifts, pnpm preparation failures,
wrong initial nextest version and earlier compiler/preparation failures also
remain their original outcomes.

The v2 cutoff includes the terminal native07/08/09/10 jobs and native pack11.
The final assembly verification is kept outside its own payload to avoid
self-reference. Later hosted CI and final documentation observations have their
own source-bound records. Every compressed part and all 1,011 member bytes,
hashes, safe regular-file paths and archive modes were independently checked
again before repository publication. No active job directory was snapshotted as
a completed result.

The [independent root verification](../native-v2/verification.json) is a separate
record outside the payload. It includes the original product commands and
before/after identities read directly from the archived receipts.

## Earlier source preparation

`source-stage1.tar.gz` preserves 127 original files (3,171,678 decoded bytes) from the completed source preparation stages on the configured native `desktop` host. Its SHA-256 is `d17ea73df84263cbf9a6791001d5fb4f22f009815a0f51167c27011762e18fa8`; the compressed archive is 337,930 bytes. `source-stage1.json` is the original per-member manifest and records the native paths, lengths and SHA-256 values.

The closed records cover the exact source checkout, original evidence pack / verification / restore, byte and Git-mode comparisons, the initial full formatter failure, the separate formatter repair, normal Git publication, and the official V8 release-checksum verification. The initial formatter failure is retained with its repair. Earlier launch-preparation failures and compiler outcomes belong to separate records; this archive does not establish that Rust product tests passed.

The archive was independently read back through the configured controller and checked against its file digest and every member digest before publication. Native paths in the manifest identify the original observations; the adjacent archive is the durable copy for review. Running compiler output was excluded from this snapshot and is recorded separately after its original job reaches a terminal state.

No record grants effect, deployment, training or lifecycle authority. The production adoption and service-quality limits in [the architecture document](../ARCHITECTURE.md) still apply.
