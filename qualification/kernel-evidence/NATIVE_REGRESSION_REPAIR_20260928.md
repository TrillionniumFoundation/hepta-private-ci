# kernel.evidence native regression repair — 2026-09-28

## Scope and exact provenance

Continue PR #1148 on `work/kernel-evidence-ad-integration-20260928`.
Main remains `a126987b84737dbc2ee2592442a314117bddb4a2` and is not merged or changed.
The prior #1092 is closed; this work does not create a competing candidate.

Resumption record: `987e5221e4820e1287fb075c792881ebf6dc39e7`.
Direct Rust/test repair: `66260bd865c856995de2688649d23299212775f2`,
tree `cad434b3bb2af1d52139b2a7326299033917a02b`.
The inventory/map follow-up and this report are a separate source successor.
No result from a predecessor is transferred to that successor.

## Actual retained diagnostic evidence

Downloaded and SHA-256 checked artifact `10954602347` from run `36382831471`:

- tested source: `98bc3c54ed66c9cc340ea92ff6d9a9707d6627c3`;
- tested tree: `1ffbdf4fb226a4ba85dcbbb0458a16c53bebe88b`;
- artifact name: `kernel-evidence-ad-source-head-98bc3c54ed66c9cc340ea92ff6d9a9707d6627c3-pull_request-1`;
- archive SHA-256: `5c8ae0e6cfc23c1ac3540cc2073a58bf1dbcd48ca4ba0455788057ba9491e405`.

The Git comparison from that source to the resumption record changes only
workflow, synchronization-script, Python-test and worklog files. The native
module source in the artifact therefore matches the pre-repair native source.
The retained logs are failure diagnostics, not qualification evidence for the
new candidate.

| Recorded check on the predecessor | Observed result |
| --- | --- |
| Isolated native role solver | 4 passed, including exhaustive assignment/oracle equivalence |
| Python kernel-evidence suite | 68 passed |
| Evidence package | 209 executed: 204 passed, 5 failed; 1 additional skipped test |
| Compile-fail API doctests | 4 passed |
| Native build | exit 0 |
| Agentd test compilation | E0277: raw issuer does not implement sealed `EvidenceIssuerView` |
| Strict Clippy | failed in AuthBus/Operations dependency connection boundaries and ordinary lints |
| Formatting, status, Lane-A, docs and maps | failed; not ignored or classified as passed |

## Direct compiled-source repairs

1. **Genesis archived segment.** A segment beginning at generation one has no
   predecessor. Decode it as `None`, not `Some(0)`, while keeping all sequence,
   record digest, metadata digest and backend/store checks.
2. **Later duplicate active tails.** Recovery after sealing but before active
   tail replacement starts at the latest sealed segment's authenticated
   metadata, not always at genesis. A partial or unanchored duplicate remains
   rejected. The final duplicate boundary must match the sealed record digest.
3. **Repeated rotation regression.** Publish thirteen generations, reopen after
   every publication, verify the complete history and recover every prior ACK.
   A separate case covers the second sealed segment, rejects its truncated
   prefix and then continues through another rollover.
4. **Actual disk-full injection.** Keep `page_count`, `max_page_count`, the
   transaction and the post-failure query on one acquired SQLx connection.
   Require `SQLITE_FULL` (13), not an arbitrary error. Insert a small row before
   the failing large row and prove both are rolled back. Only SQLite's exact
   already-auto-rolled-back error is tolerated during explicit rollback.
5. **Paging query-plan oracle.** Require the real
   `qualification_evidence_candidate_claim_seq` index, indexed SEARCH, no table
   SCAN and no temporary sorting tree. Do not weaken the query-plan requirement.
6. **Agentd fixture uses the sealed API.** Load the actual owner-controlled
   fixture registry and obtain `VerifiedEvidenceIssuer` through
   `VerifiedEvidenceTrustSnapshot`. Do not expose a raw issuer constructor or
   add a production trait implementation merely to compile the test.

These changes are ordinary Rust source and test files, not runtime code embedded
in a future source-rewriting script. The two new Rust tests still require
execution on the final source/merge candidates.

## Inventory and documentation binding repair

The status source inventory now explicitly includes Agentd client, configuration
and runtime mode/dispatch wiring; the protocol source root; the state manifest;
and setup-ci action sources. Missing required product admission files fail the
inventory instead of silently disappearing from it.

The production error marker lives in `evidence_production_checks.rs`, included
by `evidence_production.rs`. Map synchronization verifies both that exact include
edge and the actual marker in the anchored Git objects before rebinding the
writer marker. It rejects duplicate or foreign bindings and does not insert a
fake marker into the parent source.

Six new real-Git unit tests cover the inventory, deletion of each required
product path, exact-source versus dirty-worktree identity, include removal,
wrong/duplicate writer bindings, idempotent map synchronization and false gates.
The existing source-delivery lane now formats, hashes and executes this suite.
It retains its exact-head guard, allowed-write paths and non-forced push.

## Local checks actually executed in this session

- All seven uploaded Rust/test Git blob hashes equal the reviewed local bytes;
  `git diff --check` succeeded for that patch.
- Six inventory/map function tests passed against actual temporary Git
  repositories. This local checkout came from the three-module diagnostic
  archive; its unrelated status-projection import was isolated with an empty
  module for these function tests. The committed test uses the real status
  module in the full-repository workflow. This is not a full status-gate run.
- A real local SQLite 3.46.1 connection experiment returned error 13, rolled back
  the prior small row too, and passed `quick_check`. This validates the fault
  mechanism; it is not execution of the Rust SQLx regression.
- Python syntax and all three embedded Bash scripts in the revised delivery
  workflow were checked. No local Rust compiler or formatter was available.

## Unclosed gates and precise next failing boundaries

A-D is not marked complete by this report. A, B and C have substantial direct
implementation inherited in this candidate; the failures above demonstrate why
source presence and partial passing suites cannot establish completion.

The remaining native qualification must execute the repaired evidence suite,
Agentd library/product/profile/paging/publication CLI targets, strict Clippy,
formatting, build, canonical status, Lane-A and whole-repository document/map
checks on both final source and deterministic fixed-main merge objects.

The retained strict-lint failure includes connection creation outside the
central SQLite shim in AuthBus `authority_store.rs` / `authority_schema.rs` and
Operations `durable_store.rs` / `destination_dedupe.rs`, plus redundant-closure
and collapsible-if diagnostics. This patch neither changes dependency graphs
without their Cargo/Bazel lock verification nor disables those checks.
Whole-repository maps also report several unrelated module anchors and shared
source dependencies; those anchors are not mass-rewritten to manufacture green
status. The kernel.evidence-specific stale writer-marker binding is addressed
by the map synchronization change above.

Delivery/qualification jobs were requested for the new source, but no successful
new-source or new-merge execution artifact was available when this record was
written. Formatting and metadata synchronization, when executed, produce new
commits which must be identified and qualified in their own right.

Independent acceptance, external storage deployment, real backup/restore and
power-loss drills, measured capacity/RPO/RTO, canary, promotion and release still
require their own real principals and retained receipts. No such receipt is
created or asserted here, and no persistent qualification or external gate is
advanced.
