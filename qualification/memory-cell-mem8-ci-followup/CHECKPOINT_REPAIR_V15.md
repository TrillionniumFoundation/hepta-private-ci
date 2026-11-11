# MEM8 follow-up checkpoint V15

**V6 source qualification passed and the reviewed pure source is published in draft PR #5935. All ten adoption gates remain open.**

This checkpoint binds complete original 9bd2 results, the V6 source-only qualification, its reviewed formatter output, and the actual source-ref update. It does not transfer old native passes to the new source or count archived bytes as recovered owner/effect capability.

## Current source and actual publication

- Source PR: [#5935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5935), still draft.
- Actual head: `b0547d2f874c0aeb54dabd3491caa2bee49fcb0b`.
- Complete source tree: `3f89ddeff13d0af85f4abe2690699107357f1038`.
- Parent/pre-format source: `421d15080b3cb942be8ac51bbe443e268d124a9e`; previous head `9bd2f589debdba4a93baa363817c3669cb103721`.
- The root used expected-head CAS and read the actual ref and complete raw PR response afterward. The PR remains draft, with base `96038ccf0660154fac143ba6cbe4be81e00813e8`.
- Actual native merge identity: `0789f10892ac1b4e8a3e05b4c908bdfff10b8c68`, parents [96038, b054], with the same complete source tree.
- The separate V6 qualification harness is not in the pure source ancestry.

[Actual publication receipt](v15/source-v6/SOURCE_PR_PUBLICATION.json) · [reviewable source PR body](v15/source-v6/SOURCE_PR_BODY.md) · [merge identity](v15/b054-initial/MERGE_COMMIT.json)

The ten-path increment adds invocation-local caller caching and a no-match fast path; retains same-request read-only neuron observation within the original deadline plus a persistent-uncertainty negative case; isolates the ordinary Windows delete control in a privilege-checked child without mutating the parent; and corrects the hardlink test's public error assertion while retaining physical alias checks. Four formatter postimages come directly from the actual V6 operation.

## V6 source-only qualification: passed

Original [run 43032289667](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43032289667), job 130562136934, attempt 1, used harness `268539ff9272c8c1950ad630416f66774ce2f890` and source 421d.

| Observed item | Original result |
| --- | --- |
| Source operation | 283.467004 seconds within the unchanged 600-second budget |
| Python cases | 18 distinct PASS, 0 FAIL, 0 SKIP |
| Source paths | 109 cumulative paths, including complete before/after bytes |
| Complete trees | 14,037 base entries; 14,050 initial and formatted entries |
| Caller scan | 6,201 Rust files; authorityGranted=false |
| Full caller golden | Equal except the explicitly complete-tree-derived count 6200→6201 |
| Thirteen retired names | Zero hits, without path exclusions |
| Cargo and Bazel lock files | Byte-identical |
| Original checkout after operation | Same HEAD/tree; exactly four staged formatter edits |
| Rust/native/model execution | Zero |

The root reviewed all four formatter diffs, verified actual Git postimages, independently replayed the original source-record audit, and materialized the exact final tree as b054. This is not a clean-after claim about the original CI checkout.

Original artifact 13861297427 is **6,686,095 bytes**, SHA-256 `1bcacc894f007f62f288cec8384ff93982ae524f7567fe21d4bab5951e83fe1f`. All 365 ZIP members, 363 inner records and the full 108,272-byte job log are retained. The 5,545,448-byte evidence package is stored as 13 actual Git blobs; the root read every part back at an immutable commit, reconstructed the package and replayed its verifier. The whole-package SHA is an identity, not a claim that a separate whole-package blob was created.

[Publication and all thirteen parts](v15/source-ci-v6/PUBLICATION.json) · [independent remote audit](v15/source-ci-v6/ROOT_REMOTE_ARCHIVE_AUDIT.json) · [original source audit](v15/source-ci-v6/OFFLINE_VERIFICATION.json) · [package verifier](v15/source-ci-v6/verify_package.py)

## Original 9bd2 qualification: retained, not promoted to b054

| Original scope | Observed result |
| --- | --- |
| Private CI, run 43021840252 | 34 distinct selected PASS; positive repeats and expected-failing mutants recorded separately |
| MEM native, run 43021840437 | 34 executions / 33 distinct cases: 11 memory, 6 Agentd, one repeated qualification case, 16 protocol |
| MEM Python, same run | 154 executions / 120 distinct cases; repeated integrity checks are not new distinct cases |
| Architecture source head, run 43021840388 | 664 executions: 138 Python plus 526 Rust |
| Architecture separate base merge | 136 Python executions; actual merge identity retained |
| Blocking, run 43021840778 | 37 terminal jobs: 19 success, 9 failure, 5 cancelled, 4 skipped |
| Windows-current, run 43021840561 | Cancelled; 124/167 cases completed: 122 strict PASS, one LEAK, one FAIL; 43 incomplete |

Private and MEM/Architecture packages were independently reconstructed and replayed. MEM's three JUnit UUIDs, 209 captured source files, original drain markers, pinned CLI, scoped fixes and clean source receipts were checked against their original identity. The corrected Architecture derived audit retains its original duplicate-key predecessor and correction; no original execution record was rewritten.

[Private original package](v15/private-ci/PUBLICATION.json) · [private root audit](v15/private-ci/ROOT_AUDIT.json) · [MEM/Architecture package](v15/mem-architecture/PUBLICATION.json) · [MEM/Architecture root byte audit](v15/mem-architecture/ROOT_BYTE_AUDIT.json) · [root count audit](v15/mem-architecture/ROOT_COUNT_AUDIT.json)

### Blocking originals and Mac gap

The original required gate rejected an invalid or absent Bazel result; its original NEEDS map reports Bazel and repo-checks as abandoned. This result has not been relaxed.

The terminal package retains 13 complete decoded job logs, the earlier frozen 38-member checkpoint, all 37 job terminals, and the complete Mac execution artifact 13861597870. The root read all 25 binary parts back and independently replayed the package verifier.

Mac Intel job 130526871572 failed at 13:58:22 UTC. Three decoded-log reads returned Transport closed with no raw bytes; the generic fallback endpoint was unsupported. Its 10,562,035-byte ZIP and compact execution member passed byte/CRC verification. **The full Mac job stdout/assertions are still unavailable.** No failure count or root cause is invented from that compact artifact.

[Blocking package and parts](v15/blocking-9bd2/PUBLICATION.json) · [root audit](v15/blocking-9bd2/ROOT_REMOTE_ARCHIVE_AUDIT.json) · [explicit Mac gap](v15/blocking-9bd2/MAC_FULL_RAW_GAP.json)

Other original failures remain distinct: Fence inventory setup, Linux network namespace denial, neuron CommitUncertain observation, Windows ordinary-host controls, hardlink public error assertion, plugin-cache persistence, and hook completion observations. The GNU/musl duplicated inner failure output is counted once per actual attempt, not as two separate executions.

### Windows-current and product boundary

The captured-pipe LEAK was again observed in `elevated_non_tty_cmd_forwards_env_output_and_exit`. The command exited zero, but the original strict driver correctly rejected Nextest's leaky result.

The real elevated child again deleted outside files and directories in TargetOnly, ParentOnly and Both cells. All-false outside assertions failed. Original ordinary-host controls and actual elevated outcomes remain separate. Group 14 was interrupted during compilation; groups 15–19 never started. No final source-after receipt exists, and the scheduler cancellation reason remains UNKNOWN.

The root independently verified the full original ZIP, all 16 outer archive members and the exact case accounting. The observed Cargo lock CRLF bytes were checked as the exact line-ending transform of the published Git bytes; no unobserved Git configuration was inferred.

[Windows-current original audit](v15/windows-current/AUDIT.json) · [root byte and count audit](v15/windows-current/ROOT_AUDIT.json)

A source-level review identifies broad User/Logon/Everyone restricting SIDs as a possible partial tightening while retaining WRITE_RESTRICTED. It does **not** establish the parent FILE_DELETE_CHILD boundary. A complete full-restriction alternative requires acknowledged read grants and separate filesystem read/write, child-object and desktop capabilities. Current default-DACL and private-desktop helpers cannot safely accept a mixed read/network capability vector as if roles were equivalent. No such product repair or new native pass is claimed.

[Elevated feasibility and exact interfaces](v15/elevated-capability/PRODUCT_REPAIR_FEASIBILITY.json) · [23-source/12-ACL audit](v15/elevated-capability/ROOT_REMOTE_ARCHIVE_AUDIT.json) · [root source review](v15/elevated-capability/ROOT_SOURCE_REVIEW.json)

### Fence evidence boundary

Pinned Fence e6b39c80 / v0.10.0 already ran first on the supported hosted Ubuntu image in audit mode. The generic `local_control_inventory_unavailable` error does not expose the failing LocalControlObservation. All modes require the inventory, and audit checks its baseline again before ready. No policy-preserving configuration repair is established from the original record; network allowlist changes would not supply the missing inventory evidence.

[Exact Fence review](v15/fence/REPORT.json) · [root byte audit](v15/fence/ROOT_REMOTE_ARCHIVE_AUDIT.json) · [root critical source review](v15/fence/ROOT_SOURCE_REVIEW.json)

## New b054 CI: live observation, not a completion claim

The ordinary automatic runs were created at 14:08:22 UTC: blocking 43035589938, Private 43035589916, MEM 43035589682, Architecture 43035589987 and Windows-current 43035590081. They have not been manually rerun by this checkpoint.

The new Fence job 130573423711 again reported inventory unavailability before checkout. Other native jobs were in progress at the recorded observation. Five changed native cases still require exact-head results; the independent scoped-fix preparation is a plan, not an executed pass. The plan's earlier five-case prerequisite does not prevent independent scoped lint work; final native acceptance still requires the actual selected cases.

[Timestamped initial observation](v15/b054-initial/OBSERVATION.json) · [new original Fence tool read](v15/b054-initial/FENCE_JOB_TOOL_READ.json) · [native case map](v15/native-selection/NATIVE_SELECTION_PLAN.json) · [scoped-fix preparation](v15/native-selection/SCOPED_FIX_POST_VALIDATION_PLAN.json)

## Adoption gates and retained boundaries

All ten gates remain open: working-state scientific benefit; original ordinary-owner binding; provider runtime binding; unseen episodic benefit; strong baselines/association; source ownership, exposure and independent trust; deletion/external effects; full owner/effect cold recovery; total cost and slow consolidation; final hosted CI.

The current experiments and thresholds are unchanged. No model request, different-key replay of the original UNKNOWN provider request, Provider G execution, H mutation, merger or deployment occurred in this evidence publication. Historical source-preparation UNKNOWN states and archive-recovery gaps remain explicit. A new source gate, a synthetic fresh-session fixture, or a recoverable archive does not close these adoption conditions.

Prior published evidence remains [V14](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e9c8d26d159edfb72eb9c2b8f4580478b4b37a2d/qualification/memory-cell-mem8-ci-followup/CHECKPOINT_REPAIR_V14.md). The owner checkpoint is still v9 at `fb533298874d85b6d6ec3d0d1352cd847e54ac4f` until a separate reviewed owner-ledger update is actually published.
