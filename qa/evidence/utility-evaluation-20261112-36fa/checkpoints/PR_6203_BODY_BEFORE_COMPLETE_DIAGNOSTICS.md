## Problem and resulting behavior

A known failed metric could take precedence over missing evaluation evidence. Both the independent evaluator and the trusted in-process compatibility comparator returned `Ineligible`, allowing the learning bridge to interpret an incomplete comparison as a completed `NoUpdate`.

Missing applicable evidence now takes precedence, while known failed metrics remain recorded. Complete negative and complete eligible comparisons retain their meanings. The learning-stage regression combines a known negative comparison with a missing future window and requires the original Training cut to remain at Evaluation without creating a NoUpdate receipt. Existing evidence digests bind both disposition and failed metrics; current revalidation requires the current complete sealed decision.

## Frozen source and scope

- Current source: **`e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`**.
- Source tree: **`b607ff5f50812c5e0f932d7dae18d4c74f1269cb`**.
- Ordered merge parents: `19aa601fa09321f1b6d1b3ff3b4d422908004e48`, then fixed dependency `726af8f4a345a2ffb148b971f3fa16c71436862d`.
- The accepted integration base for this published candidate is fixed `726af8f4`. The live PR-base branch `codex/learn-common-profile-20261112-037c` was independently observed at **`b29869e856d08db1bfb066116a9c443376ccc57d`** on 2026-11-12 at 10:19 UTC through both the ref and branch endpoints. The PR endpoint still returned a cached `726af8f4` base; that cached value is not used to describe the live branch. A fixed-b298 successor is being prepared, and has not been published or qualified.
- GitHub comparison against that fixed base: **4 commits, 51 files, +307/-110**. The native final manifest has 53 changed paths relative to the first parent `19aa601f`; these are different comparison bases.

The stack contains the utility fix (`91d0e10e`), two stale exact-caller QA expectation repairs (`6d0da9fe`), and explicit existing-trait journal calls required by the conservative caller verifier (`19aa601f`). The final merge incorporates the fixed upstream original-owner work and reviewed native lib-test compilation/formatting repairs.

The journal calls still use the same trait, journal receiver, admission key, mutable borrow and result. Fixture repairs use explicit macro imports, existing cfg(test) peer-channel helpers and actual journal-cut decoding. Mechanical Clippy/rustfmt changes retain assertion values, test attributes, authority checks and deadlines. Two CALLERS source-order literals follow Clippy's preserved short-circuit let-chain syntax; the exact caller sets, 522 boundaries and 381 protected rows remain enforced. No verifier relaxation, ignored tests, owner fabrication or production visibility widening is introduced.

Upstream now includes strict Root authentication for the evaluated-retention 4-to-6-receipt metadata profile, plus return of the original Training/Evaluation connections after publication. These additions are preserved in full. They do not complete ordinary Version/Selector/consumer capability assembly or authorize a live ordinary learning loop.

## Validation on the new candidate

The final source was reconstructed from the actual native postimages and delta. All **53** changed paths were read back in full and independently checked against native byte counts, SHA256 and Git blob IDs; the rebuilt tree is exactly `b607ff5f`. Original canonical Git objects, both parents and source-ref readback are verified.

The desktop has now imported the exact original `e8b6fe2a` commit and aligned HEAD/index only after matching all **14,741** source files by Git blob and mode. Before/after source inventory bytes are identical and the resulting checkout is clean.

| Check | Actual evidence on e8b6fe2a |
| --- | --- |
| Integrated preparation | Original scoped agentd `just fix` and `just fmt` both exited 0 on the reviewed preparation that became tree `b607ff5f`. Raw log, final delta and manifest are preserved. |
| Exact-head scoped maintenance | **PASS**: agentd + eval fix exited 0, formatting exited 0, full source inventory unchanged and checkout clean. |
| Complete eval library | **PASS: 163 passed, 0 failed, 0 skipped**, 09:35:08–09:35:39 UTC, exit 0. Root independently checked the complete fresh XML and original raw output, including all four new regression methods. |
| Native focused suite | **FAIL**, original `just test` exit **100**, 1,213.627s, whole command not timed out. Fresh XML has **100 actual cases: 76 passed, 24 failed, 0 skipped**. Failures comprise **17 stack-overflow SIGABRTs, three individual 60-second test timeouts, and four other failures**. The mixed known-failure/missing-evidence learning-stage regression actually passed in 4.587s. Original raw, XML, helper/build material and source identities are retained. |
| Whole native pipeline / ordinary / Root | Original pipeline terminated **FAILED** at 10:08:49 UTC on its focused prerequisite. **All / ordinary / Root were not started.** No downstream pass is inferred or carried over. The exact source remained unchanged and clean. |
| Source closure | **FAIL**, exit 1 after 181.765s, not a timeout. Original unittest output says `Ran 357 tests`, `errors=28`; raw method counting finds **343 explicit ok methods, 14 unique error methods, 28 error/subtest records**. The runner's original aggregate is preserved separately. All 28 errors report two stale `if owners` source-order literals where the maintained source has `&& owners`. No PermissionError was present. |
| Caller self-test | **PASS** on the same unchanged source. |
| Full caller verifier | **FAIL**, exit 1, stage 1,696.925s, not a timeout. Actual message: `learning_source_bound_training_stage_readback` has unexpected caller `codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs`. This is a real original read-only seam that needs complete exact registration/protection review, not a parser misattribution or grounds to relax the verifier. |
| Scoped source-marker diagnostic | A separate external corrected manifest passed **381/381 protected rows** against unchanged e8 source, exit 0 in 4.387s. This is explicitly a scoped diagnostic; it is **not** a rerun or pass of source closure/full caller. Fixed b298 already contains these marker corrections and its additional protocol rows. |
| Old-comparator control | **Observed expected regression** in a separate e8-based clone: original `just test` exit **100**, **4 actual failed / 0 passed**, no timeout. Only the two comparator production files were reverted; the four new tests were retained. Fresh XML confirms old `Ineligible` versus expected `InsufficientEvidence` assertions. The wrapper's successful observation is not a passing test suite or a change to the failed native verdict. |
| GitHub CI | At the recorded 10:14–10:20 UTC observation, e8 had zero returned runs/check-runs/check-suites and no actual passing status. The live base had advanced eleven commits, and the PR was observed conflicting. An earlier inference from the cached base was retracted. This identifies a current conflict blocker; it does not prove the cause of every earlier zero-run observation. |

The published **e8b6fe2a candidate has failed exact-head qualification**. It remains frozen so all failures retain their original source identity. A successor will integrate the fixed b298 dependency, the independently reviewed retention-composition guards, and only audited repairs for the observed caller/native failures. The original full gates must then execute on that new frozen head; none of the e8 results transfer.

## Successor preparation and later source observations

The frozen fixed-b298 preparation has been checked with the original collector over **6,597 complete Rust source inputs**. Its four-boundary diagnostic actually exited 1: **one boundary passed, three failed; five protected rows passed**. The Training readback set passed, while the shared channel exposed six artifact/Selection caller omissions and the Selection connection was absent from two material-check caller sets. The exact raw failure and original source-before/source-after inventories are retained. A separate diagnostic of **all 534 boundaries and 390 protected rows** actually started at 11:16:56 UTC on 2026-11-12, under the unchanged 4,800-second budget; its final result is still pending. Both are preparation diagnostics, not the original full gate on a published successor.

Audited repairs preserve the existing original custody, current evidence and purpose checks. Artifact HEAD signing is a real original-owner effect, so the forthcoming source guards distinguish Sign from Readback and cover the minimal owner/wire/current-source dependencies. The separate Selection-only checkpoint passed eight explicitly selected source-mutation methods; its full-source membership method was not executed there. Production/native qualification remains separate.

Later native diagnostics found seven missing tracked historical archives, despite an empty git status. Exact original Git objects were checked against two prior complete inventories and restored create-only. The observed 14,741-file restoration and independent retained e8 checkout both match the expected full inventory; HEAD and raw index were unchanged. Four original complete stage gzips are retained; maintenance/eval stage gzips are currently **Unavailable**, with their original summary records retained. The original agentd test executable and subsequently its former target cache were also observed absent. Their disappearance cause is **Unknown**. New build/list diagnostics keep their own source snapshots and cannot be represented as the original failed binary or as native gate passes.

The [556-file evidence checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7986430437836096bc44c5ec651739529cf70330/qa/evidence/utility-evaluation-20261112-36fa) preserves the published e8 failures and all prior evidence, plus independently reviewed v3/v3.1 preparations, actual literal-gap counterexamples, later all-boundary failure observations, the new-build metadata originals and exact byte recovery of the four observed surviving native inventory gzips. The two unavailable stage gzips remain unavailable. Source PR head remains **e8b6fe2a**.

The reviewed v3.1 preparation changes exactly four files relative to v3: CALLERS and three newly added QA modules. All 534 boundary memberships remain unchanged; 399 protected rows represent 328 unique paths. All 95 original functions in nine inherited QA files remain byte/AST identical. Two new selected methods actually reject 14 directory/template and decoy negatives. Training now uses the full original Rust collector, and controlled pure-function injection checks reuse only a proven invariant method-local type index; real file deletions use fresh indexes. Three complete membership methods and the unchanged 600-second source gate have not run on this preparation. The original verifier is unchanged.

The same frozen-v2 all-boundary scan has additionally recorded an unresolved possible original Training readback receiver in `circuit_next_use_receipt_owner.rs` (position 281), as well as the six known missing original channel registrations (position 295). A minimal explicit Trainer reference is being prepared without changing the existing rejection, arguments, evaluated branch, caller list or verifier. The preserved progress chunk ends at position 299 starting at 11:51:21 UTC; it is not a terminal whole-scan result.

The separately labeled e8 new-build diagnostic v4 actually started Cargo compilation at 11:45:25 UTC after actual metadata exited 0. Complete original metadata and the explicitly partial compiler prefix are preserved. Its only stated environment delta from the original focused build is an isolated target on the observed writable /data filesystem, avoiding the insufficient /home build space without deleting an existing target. This checkpoint contains no terminal build result and no Rust test from that diagnostic; a new binary cannot be represented as the original failed executable.

## Historical results and evidence limits

Earlier executions remain attached to their actual source:
- `91d0e10e`: complete eval library **163 passed, 0 failed, 0 skipped**, and an independent old-production control actually failed all four targeted regressions.
- `6d0da9fe`: complete source-closure suite **346 passed, 0 failed**, with unchanged full inventory.
- `91d0e10e`: full caller verification **failed**, exit 1 after 876.408s, on the unresolved journal receiver. It did not time out; the original failure is retained.
- Cloud `19aa601f` source-closure and caller reruns lost their terminal records when the execution filesystem was replaced. Both remain **Unknown**.
- Desktop `6d0da9fe` maintenance failed with 85 lib-test compiler diagnostics. A later preparation compiled successfully but its wrapper rejected unexpected additional Clippy files; both the successful compiler exit and failed scope guard are preserved separately.
- Windows `19aa601f` CI failed at agentd lib-test compilation. **Zero of the selected 36 Windows LEARN cases executed**. The repaired source still requires its own execution evidence.

The earlier cloud eval raw logs/JUnit and full local inventories became **Unavailable** after filesystem replacement. Observed counts are historical observations, not reconstructed original artifacts. The exact 191-byte caller failure and 48-byte self-test outputs were recovered with their prior hashes. All new desktop runs receive independent source identities, raw output, JUnit and before/after inventories.

## Additional composition gap under repair

Exact-source review identified a separate contract-composition gap: a primary Eligible qualification can be paired with a complete Ineligible retention member while some composition layers derive the outgoing Qualified decision only from the primary. The complete panel signatures bind those member results but do not by themselves require all applicable member conditions to pass. **No actual erroneous ordinary Adopt has been reproduced**; the current ordinary positive path still lacks original owners and remains fail-closed.

A minimal two-file repair has been prepared and independently reviewed for both the original panel boundary and the final model-material revalidation boundary; it is not yet applied to the published source or behaviorally qualified. A primary-qualified combination with any non-eligible retention member will be refused, without relabeling it NoUpdate or fraud. Complete primary-negative NoUpdate and existing unknown-evidence refusals remain unchanged. Every current frozen member plan includes PrimarySuperiority; the repair will not reinterpret or relax those frozen roles. The original provider fixture that honestly produces Ineligible will not be rewritten to fabricate positive evidence. Current e8 gates continue unchanged and retain their own source identity.

## Audit and remaining qualification

[Evidence branch](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/codex/utility-eval-evidence-20261112-36fa/qa/evidence/utility-evaluation-20261112-36fa) retains the original source audit, ordinary integration map, historical failures, recovered raw outputs, actual native preparation records and immutable source-identity proofs. Evidence-only commits remain separate from this source PR; the audit addendum and fresh execution records will be attached as they finish.

This change supplies no independent real task outcomes, original owner authority, payment, adoption or production permission. Ordinary startup owner assembly, the evaluated-NoUpdate Version/Selector/C protocol, independently sourced task B, full deployment costs, identified changed-action outcomes and complete daemon-plus-Root recovery still require actual evidence. Fixed b298 adds original evaluated S/C attestation/recovery mechanisms, an S read-only host and explicit measurement support V2. Its product startup/readback/owner-assembly callers still do not establish the complete ordinary path. Existing TrainingNoUpdate authority and missing-owner refusals remain intact.

**Complete real ordinary Adopt = 0. Complete real ordinary evaluated NoUpdate = 0. Complete real daemon + Root cold-recovery qualification = 0.**

Draft / HOLD: published exact-head gates failed. Preparing a fixed-b298 successor; complete ordinary-loop qualification remains separately absent.
