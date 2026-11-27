# Rust consolidation checkpoint — 2026-11-19, round 07

Status: **IN PROGRESS**. This checkpoint does not merge `main` or authorize branch deletion.

The reviewed source candidate `4808c765c20a144b38279a8bdf4e79980e5cff73` has exactly the same tree as local `1109776d0b777999f0605ff92c98ddfcb03c2159`: `0ef5bf40bced3af12f1f49245acb2a87272cd520`. It includes the observed integration head `10fb34ca4ff49e8ceb38a41cc0b018dbdf81452d`, the reviewed ordinary Rust history and this round's source and CI fixes.

## Scope and exclusions

The observed census contains 7,648 branches: main, 7,169 ordinary branches, and 478 protected HIA or HIA-descendant branches. The candidate contains 2,794 frozen ordinary tips; 4,375 remain. These are candidate ancestry counts, not main coverage or a complete semantic-audit certificate. No HIA branch was written, merged, renamed or deleted by this work. Both the old and externally advanced HIA tip remain in the 498-pin protection set.

The 44,572-entry parent graph is complete and has no intersection with the protected pins. `graph/` contains bounded compressed pieces; concatenate their decompressed bytes in index order to reproduce the recorded graph digest.

## Review evidence

`evidence/root-review/` records actual merge conflicts and independent expected-tree checks. `evidence/r3-review/` records caller, peer, cost, native fixture and concurrent-head decisions. `evidence/joint-h3-review/` records H3 durable recovery, protected-cost composition and native validation, including failed attempts and their corrections.

The native validation index records test names/counts, source bindings, environments and limitations. In particular, H3 native testing used the recorded older Cargo graph; HCSN used the recorded Mac CPU runtime rather than workflow-pinned versions; PEFT/Transformers compatibility remained blocked. The Q24 physical value of 1 is an execution environment flag, not an extra test count.

## Publication identity

`publication/original-local-commits.json` retains raw bytes for all 72 original local commits. `publication/commit-map-72.json` maps them to the GitHub-created objects. Each exact tree, ordered mapped parent list, and original message content apart from API-normalized terminal newlines was verified against GitHub. The original remote parents remain their original IDs. This checkpoint is a subsequent child and intentionally is not included in its own map.

## Remaining gates

`CI required` and `Architecture required` must pass for the actual published integration head. Windows kernel isolation is still unqualified, and production admission remains fail-closed. Unix peer credentials are not treated as a Windows proof. The chrono dependency failure needs an exact-head check and an audited compatible migration. The ordinary-branch audit and actual `main` merge remain unfinished.

The existing hourly continuation must avoid audit-only pushes that cancel useful CI. If no substantive change is ready, it should inspect and report without moving refs.

`FILE_INDEX.json` covers every other checkpoint file; source provenance preserves the digest and length of original bytes, including deterministically compressed logs.
