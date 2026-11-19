# Scoped Root learning and external evidence qualification

Date: 2026-11-09. Status: **mechanism qualification passed; product assembly remains HOLD**.
This is evidence cut 11/11 for code PRs #5541 through #5550.
The cumulative code head is [`b8e8c6e82abc1479c573f61a5e17d28d581e6cad`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b8e8c6e82abc1479c573f61a5e17d28d581e6cad),
based on prior evidence head [`e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5).
All code cuts are drafts, each below 500 changed lines. No per-cut native acceptance is claimed.

## Implemented behavior

- Freeze the exact request, owners, update rule and Cell/Organ component boundary.
- Carry that scope through original Root registration, sealed handoff, scoped worker,
  protected schema-2 checkpoint and history recovery; refuse V1/V2 reinterpretation.
- Check authenticated Training candidates before record/CAS/evaluation and recheck
  every recovered Training receipt, including histories ending in NoUpdate.
- Read existing signed evidence through the original stream and pre-held pidfd,
  with exact peer identity, bounded I/O, signature checks and cancellation consumption.
- Qualify actual Root registration, retained writer/listener, schema-2 Cell handoff
  to UID 60001, checkpoint CAS/readback/exact retry and recovery of the same store.

## Observed qualification

| Check | Observed result | Source boundary |
| --- | --- | --- |
| Ordinary libraries | 772 agentd + 109 learning-artifacts = 881 passed | Tested inventory |
| Explicit Root parents | 6 passed; nested children not counted again | Tested inventory |
| Source regressions | 17 passed; caller scanner self-test passed | Before maintenance |
| Required maintenance | just fix and just fmt exited 0 | Maintained inventory |
| Binary compilation | selected-package cargo check --bins exited 0 | Maintained inventory |
| Final caller proof | 6157 Rust files, 188 boundaries, 170 protected entries / 133 paths | Final inventory |
| Authority | authorityGranted=false | Final caller proof |
| GitHub source readback | all 33 files / 636280 bytes matched SHA256, blob SHA, size and tree path | Exact code head |

## Three distinct source identities

These are canonical source-inventory SHA256 values, not Git commit IDs.

| Inventory | SHA256 | Evidence |
| --- | --- | --- |
| Behavior-tested | `34f2b72cfc17988d70935393ffdd22b31b5334e00000bbb107ef3645fdba6bfd` | 881 ordinary + 6 Root; 17 source QA |
| Maintained/compiled | `1901b15d75b0d0b7eec8c2b1a3d0abeea6e0f279661203d38b22b10c82d16f20` | fix/fmt and binary compile |
| Final | `aad7b3e68c34257731c841cb9f0140c60657df0fb72552fefe743eb5eaaa1768` | exact marker alignment and final whole-tree caller proof |

Seventeen Rust files changed during maintenance: formatting/import order and one Copy cleanup.
Static review found no material behavior change. No behavior or source-QA tests ran after maintenance.
The final change touched only exact whitespace markers in CALLERS and one source-QA file;
all Rust bytes are identical to the compiled inventory. Guard character sequences and scanner code remain unchanged.

## Evidence files

Read the two archives together. [VALIDATION.md](VALIDATION.md) describes commands, corrections and limits.
[validation.json](validation.json), [source-stack.jsonl](source-stack.jsonl) and [SHA256SUMS](SHA256SUMS)
provide machine-readable results, the published dependency chain and archive/file integrity.

- `native-qualification-final-v3.tar.xz`: 68 native receipts, logs, JUnit reports and input payloads, including original failures.
- `source-and-review-evidence-v3.tar.xz`: 89 source/review payloads, four complete canonical inventories,
  all 33 final source files, ten review cuts, runner sources and independent archive/GitHub readbacks.
- The reconcile index's original-inputs gzip is represented by the identical top-level inputs gzip.
  Its qualified-source gzip is represented by the identical canonical JSON in the source archive;
  reconstructed compressed bytes are not asserted identical to the original gzip.

## Product state and limits

`require_root_learning_assembled` still refuses unfinished assembly; registration retains
`production_ready: false`. Stage-owner assembly and evidence-client product caller sets remain empty.
Real trainer, independent evaluator, result signer and Circuit providers are not product-assembled.
This scope admission checks declared component digests, not actual gradient or tensor update masks.
Evidence V1 still binds the initial request/owners; it does not independently sign the V2 frozen scope.
Synthetic signed receipts and different UIDs do not establish scientific or operator independence.
The Root service test has no Device/Notes consumer qualification and uses synthetic Experience.
Learning checkpoint recovery does not publish a model generation: ordinary `Unpublished` is preserved.
No successor-task benefit, persistent continual learning, cloud training, merge or deployment is claimed.

The previous #5468 evidence was separately read back: its 760 ordinary / 3 Root reports and
65 archived payloads are corroborated. That earlier tested/maintained split remains distinct from this run.
