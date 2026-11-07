# E17 independent addendum: a dynamic policy input must have an admission contract

## Decision and scope

E17 remains **OPEN**. The reviewed non-macOS implementation still refuses authorized bounded reads. The original feasibility report correctly rules out enabling that method by dispatch alone. This addendum identifies one further premise that a future admitted-handle constructor must establish: cloning the permission value and applying the existing project-roots materializer does not freeze every input used by the original read predicate. [S1, S2]

The concrete additional input is `TMPDIR`. This is a conditional source-level counterexample to an incomplete future constructor contract. It is not an observed exploit, a new production regression, or an explanation of the three historical skill failures. No process environment, file, namespace, kernel state, candidate, or native test was changed to construct it.

The original report, its manifest, and the status v2 preview remain unchanged. This appendix is additive. Its conclusion does not change the original report's refusal to activate the capability.

## Fixed source facts

In the fixed permission source, `can_read_path_with_cwd` calls `resolve_access_with_cwd`. For a restricted policy, that function resolves entries on each call and selects the matching entry by path precedence. `resolved_entries_with_cwd` reaches `resolve_file_system_special_path` through `resolve_entry_path` and `resolve_file_system_path`. The `FileSystemSpecialPath::Tmpdir` branch reads `std::env::var_os("TMPDIR")` at that point. An empty, missing, or non-absolute value has no resolved path. [S1]

The existing `materialize_project_roots_with_workspace_roots` operation handles project-root entries and their related patterns. It does not replace a remaining `Tmpdir` entry with a captured absolute path. Cloning the profile, cwd, and workspace roots therefore does not, by itself, make this later read predicate a function of those captured values alone. [S1]

This observation is narrower than a claim about every policy. A profile without a remaining dynamic entry does not take this branch. An executor contract that actually keeps the relevant environment input immutable throughout admission would exclude the schedule below. A separately reviewed complete materialization boundary might also address it, but that would need an explicit semantic contract; silently substituting a captured value would not prove that the unchanged original predicate was evaluated under its original semantics.

The fixed source also has other conditional resolution inputs, including the `SlashTmp` directory-existence check. This appendix does not claim to exhaust those dependencies or to provide a counterexample for each of them. It establishes the `Tmpdir` dependency precisely and requires a future supported policy class to account for all resolution inputs it retains. [S1]

## Conditional schedule that defeats the incomplete premise

The following is a paper interleaving, not an executed model or native observation. Assume a proposed constructor has already solved its root and mount-authority premises. Let its captured restricted policy contain only a read allowance for `Special::Tmpdir`, with no competing allowance or exact deny alias. Let a unique regular file initially be at `/scope/a/X/f`, and let the process initially resolve `TMPDIR` to `/scope/b`.

The schedule additionally requires an actor able to change that process environment input between observations. Ordinary filesystem mutation authority alone does not grant that ability. This is an explicit conditional premise; this review neither proves such an actor exists in the deployed executor nor assigns it to the historical tests.

| Step | Live file location | Current `TMPDIR` | Event and consequence |
| --- | --- | --- | --- |
| 1 | `/scope/a/X/f` | `/scope/b` | The hypothetical constructor obtains its metadata handles A and B, retains A's guard, and observes the coherent path P as `/scope/a/X/f`. It has not returned payload. The actual file is outside the allowed root. |
| 2 | `/scope/a/X/f` | `/scope/c` | The environment input changes. The actual file remains outside the allowed root. |
| 3 | `/scope/b/X/f` | `/scope/c` | An ancestor directory X moves from a to b. The leaf's name, inode, and link count need not change; a leaf delegation is not an ancestor-path lease. The actual file is still outside the allowed root. |
| 4 | `/scope/b/X/f` | `/scope/a` | The environment input changes again. The actual file is still outside the allowed root. |
| 5 | `/scope/b/X/f` | `/scope/a` | Evaluating the original predicate on the previously observed P can now accept P under the current `Tmpdir` entry. The retained leaf guard need not report the ancestor move as invalidation. |

There is no instant in this sequence at which the live file is under the current allowed `Tmpdir` root. Nevertheless, the incomplete construction can combine a path from step 1 with policy resolution from step 5. A common admission instant does not follow from those separate successful observations. [S1, K1]

The schedule does not challenge a constructor that re-establishes the required common-instant relation through another proved mechanism. It shows why a stable profile value, leaf guard, and trusted mount/root view are not a complete list of premises if policy evaluation still consults a mutable external input.

The required interval is admission, before returning the bounded readable result. This finding does not authorize a new requirement that pathname uniqueness or policy aliases remain unchanged throughout the subsequent payload read. The original positive behavior for later rename or hardlink creation after successful admission must remain intact. [S2]

## Relationship to the original three skill cases

The fixed `executor_skills.rs` restricted fixture writes `default_permissions = "workspace"` and a workspace-root write entry. That literal contains no explicit `Tmpdir` entry. The permission-approval scenario also uses an ordinary symlink to an external reference and a turn-scoped read grant, which a valid repair must continue to support. [S3]

This review did not reconstruct every runtime configuration default and the final materialized permission object for those historical requests. Whether any actual failing request retained a `Tmpdir` entry is therefore **UNKNOWN**. It must not be inferred from the generic permission implementation or from the fixture's temporary-directory layout.

The already established failure boundary remains the non-macOS authorized-read method's immediate `Unsupported` result and the false advertised capability. The new conditional schedule does not replace that source-linked explanation. [S2, R1]

## Concrete remaining work before E17 can close

| Required input or proof | Current disposition | A bounded next deliverable |
| --- | --- | --- |
| Trusted resolver/root and topology authority, with an identified owner and lifetime | Missing from the selected production constructor chain; runtime paths carry executable locations only. | Define the actual executor-owned producer and its supported deployment/root class. Observations or caller-supplied booleans alone are insufficient. [S4] |
| Complete authority-input boundary | Exact deny aliases remain a separate problem; `Tmpdir` adds a demonstrated dynamic input if retained. | State and enforce an immutable-input premise, reject an unsupported dynamic policy class before payload, or propose a separately reviewed complete-materialization semantic boundary. None is implemented here. [S1, R1] |
| Runtime support and caller eligibility for the exact delegation mechanism | Fixed kernel code and a target PASS are not proof for an arbitrary production filesystem or worker. | Bind the actual file, supported kernel/FS, ownership/LSM conditions, guard acquisition, final consuming query, and error/cleanup paths. [K1, R2] |
| One actual admitted-handle operation preserving original behavior | No production constructor or enabled capability has been demonstrated. | Combine the authority producer with A/B custody, strict resolved-target reopening, same-inode/common-instant authorization, bounded complete reads, and the unchanged positive and negative oracles. [S2, S3] |

These are technical inputs and proof obligations. They are not a claim that the user's authorization is missing. The broad blocker-resolution task permits preparing a concrete implementation contract and source proposal; it does not supply an absent runtime authority or turn a static precursor into a completed product fix.

A full-root stable-view authority is the sufficient strategy examined by the original report. This review does not prove that it is the only possible implementation. Any alternative must establish the same admission result under an explicit threat and lifetime model. A new run of unchanged code or more matching before/after path samples would not supply that missing result.

## Evidence custody and limits

`SOURCE_CHECKS.json` records independent byte, size, mode, and Git-blob checks for thirteen selected repository bodies and five fixed kernel files, plus the seventeen retained report inputs. The root's separate current-main audit binds the thirteen selected bodies through sixteen complete trees at main #5276, commit `21288dde4a391f93963da7958d30e391d50c27bb`, tree `1e77037b9d0c45297a58d754c5f14711ff5da80c`. This appendix relies on that root receipt for the current-main tree continuation; it does not claim an independent remote refetch or whole-repository absence proof. [R3]

No candidate helper was imported, no policy predicate or interleaving was executed, and no private console, execution ZIP, or rejected stream was read. Linux41's two actual TestRunner cache flags remain `[false, false]`; its two XML-generation cache flags are `[false, true]`. The same action and binary do not establish independent GNU/musl ABI executions, and direct records for the three delegation subcases remain unavailable. [R2]

### Fixed references

- **S1:** `codex-rs/protocol/src/permissions.rs`, Git blob `1537230e0a8f1685530eb03c2c782a587ad6bb6a`, SHA256 `3ad7c54a19a3bddd72e9e8d8d0641835674ac2b596001ee0d7ce32293863fe06`; exact local path is recorded in `SOURCE_CHECKS.json`.
- **S2:** `codex-rs/exec-server/src/local_file_system.rs`, blob `228fa8027d5f6aa49d9efe499ef225f98fb90513`, and `local_file_system_authorized_read_tests.rs`, blob `1f61a8f4546c33275a3db712f95db1ae71d0d9a7`; their complete byte identities are in `SOURCE_CHECKS.json`.
- **S3:** `codex-rs/app-server/tests/suite/v2/executor_skills.rs`, blob `2d138526d59accd5241fde1e2804c6bc6e8592b6`, SHA256 `9542f38bc52ffc7bbb76c4ce6ce084be6b5015cd38199227abb86a5f21406ec7`.
- **S4:** `codex-rs/exec-server/src/runtime_paths.rs`, blob `1d3713b1c1e49e6d2ccd6a106826b05d0535630f`, together with the fixed environment, filesystem-helper, and sandbox-context sources in `SOURCE_CHECKS.json`.
- **K1:** Linux v7.0 commit `028ef9c96e96197026887c0f092424679298aae8`; the fixed `fs/locks.c`, `fs/namei.c`, `fs/namespace.c`, `fs/d_path.c`, and `kernel/fork.c` byte identities are in `SOURCE_CHECKS.json`. This identifies source, not any running kernel.
- **R1:** Original `/dev/shm/ndu_e17_production_review_20261107/PRODUCTION_ADMISSION_REVIEW.md`, SHA256 `f6d8bebc8ad4368d129e1405a3b3789104a9ed0cb4778b3f2e9c0fddb5bce4f8`; original manifest SHA256 `a5588bb6c2026fd0408560d5be6320c5406fda97c6fb6c2767cd340d2a8ce7d6`.
- **R2:** `/workspace/scratch/3f6a885bb83c/round3_ci/independent_reviews/linux_delegation41_native/REVIEW.json`, SHA256 `44605d2a1f363f760e01c2d7bcb46226977511430b0769813f30d965862df4ed`; root target review SHA256 `df1a80792210af6f827a7eee76e2ed9e9f55c6cd8ba2d3bd876b96c52fb8b3cf`.
- **R3:** `/dev/shm/ndu_root_continuation_20261107/e17_root_review/ROOT_REVIEW.json`, SHA256 `021a016d48af01430a23c62828c6203e95f0c40cbb5d13eb7446c131012eb3ed`.
