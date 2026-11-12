# Fresh source materialization v2 — fixed original alternate closure

Status: **PREPARATION / HOLD.** The v2 driver has not been executed. This document does not authorize a native launch, maintenance, tests, deployment, or a ref update.

## Why this revision exists

The actual v1 job `1a1d0badea9-2564-1bbf` finished at the preconditions stage with `FAILED_PREPARATION` and the error `source alternates not admitted`. Its original RESULT is Git blob `6f4cfae9ebe5541ff1328205d413a08f862da190` (4,889 bytes; SHA256 `83cb7e05f0bf3433dbce093def3a3660eef43432cca9eb35b68f113ca338a443`). Only the four recorded read-only `rev-parse` commands ran. The target was not created, no object import or Cargo occurred, and the full original physical inventory had not begun. The result correctly leaves `source_repo_unmodified=null`; it is not evidence that the complete original physical source was observed unchanged.

The original source-gates clone legitimately uses local Git alternates. Native then performed a separate bounded read-only observation; its exact 9,541-byte stdout is `f2a69c3d434111133905c0ef454336f59bf5253e`, SHA256 `de2498c12a831faa5ed84cbb269f5423100ce8dabf90225dc60030c70428d030`. The graph and original Git state were equal before and after. Its seven Git commands returned 0. The independent process read is `c4476e687ef03298a7729a4a28af2d5e4158c2ea`; that archive is a stdout/stderr read, not a replacement for a supervisor terminal record.

## Exact admitted lookup graph

All directories are fixed absolute, real local paths. The driver pins their actual device, inode, mode and UID from the original observation. Each present alternates file is pinned by complete bytes, SHA256, Git blob SHA, mode, UID, link count and the original integer metadata version. Each raw line includes its final LF.

| Object directory | Actual next directory | Original alternates blob |
| --- | --- | --- |
| `/home/qian-qi/hepta-utility-36fa-source-gates-c0f78493-v1/.git/objects` | `/home/qian-qi/hepta-utility-36fa-review-19aa/.git/objects` | `9200f58a90f6cabee66c146e356d2140510d8b95` — 58 B |
| `/home/qian-qi/hepta-utility-36fa-review-19aa/.git/objects` | `/home/qian-qi/hepta-utility-20261112-36fa/.git/objects` | `b8472ffa047e1dec2205ffa82124ae5acaae1e6b` — 55 B |
| `/home/qian-qi/hepta-utility-20261112-36fa/.git/objects` | `/home/qian-qi/hepta-learn-ordinary-ce434-20261111/.git/objects` | `b15856bd49a06d8851106cd2180c4217714ab5fe` — 63 B |
| `/home/qian-qi/hepta-learn-ordinary-ce434-20261111/.git/objects` | None | `info/alternates` was absent and must remain absent |

Git's original `count-objects -v` reported precisely the same three alternate directories. Its existing `tmp_pack_A1STqQ` garbage warning is retained in the raw observation. This preparation neither removes that file nor scans the donor histories to explain it.

## Minimal code change

The v2 driver is `ed0c0896128528fcd19881fd9d38891104cb1e3e`, 73,386 bytes, SHA256 `2d3f96129665bb425d72bdf1d8bb6e575a1885d91d1c4eed39961032fe24fdd6`. The exact v1-to-v2 patch is `9511f6b9dea28a5e9359b4bdf8562566b000b2fa`.

The incompatible blanket prohibition on source alternates is replaced by an explicit, closed local lookup admission. It is checked before source Git/object use, again immediately before creating the new repository, and independently during final evidence collection. Complete original bytes and directory/file identities are recorded in `SOURCE_OBJECT_LOOKUP.before.json`, `SOURCE_OBJECT_LOOKUP.before-target.json`, and `SOURCE_OBJECT_LOOKUP.after.json`.

The return shape of `source_git_state()` is unchanged, so it is still compared exactly with the actual successful canonical review. New lookup evidence is separate. Of 56 original top-level functions/classes, 53 remain byte-identical; only `source_git_state`, `validate_approval_and_proofs`, and `main` change, and two lookup functions are added.

## Boundaries kept

The primary original source still requires the exact 5,474,911-byte original inventory, SHA256 `cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57`, using the unchanged original `51181866...` inventory module. Its complete physical source and complete own `.git` metadata are observed before and after. This remains distinct from the external donors: only their fixed lookup files/directories and the actual required immutable object bodies are verified. There is no donor-wide worktree/history unchanged claim.

The 395 canonical objects, 87 prepared objects, exact 16,136-object union of the two old bounded snapshots, full canonical/prepared closure checks, original raw commit bytes and parents, standard non-delta PACK v2 import, full new-object raw readback, and final 15,188-leaf physical/index proof are unchanged. The supplied/old union count is still derived with overlap verification; 16,618 is only the upper bound.

The new repository must have no alternates, shallow boundary, graft, replacement object, or inherited alternate environment. No object raw bytes, author, timezone, parent ordering, newline, scope, authority, permission, test budget or test assertion is changed. The old source and donor stores are never written.

The preparation budget remains 600 seconds plus 180 seconds for final read-only records. These are preparation budgets, not test/source-gate budgets.

## Versioned staging and launch contract

Use the same immutable input root:
`/home/qian-qi/hepta-utility-36fa-evidence/fresh-source-materialization-86dd-v1`.

Reuse its exact previously staged `prepared-input` fragments/manifest, inventory module, canonical proof and Root review bytes. Do not retransmit or rewrite them merely to rename the execution.

Create the following new artifacts without overwriting any v1 artifact:

- `driver-v2.py`: exact v2 driver above.
- `WAITING_CONFIG_V2.json`, if a staging template is useful: blob `3a8816e55999f75c3fdb4b2852733f10826dece1`.
- `APPROVED_CONFIG_V2.json`: Root must freeze this separately after Root/native review. It must never initially contain WAITING bytes and then be overwritten.
- `run-v2/`: must not exist before the new invocation.

The proposed new execution key is `hepta-utility-36fa-fresh-materialization-86dd-v2`. This is a reviewed revision after a known terminal v1 failure, not an automatic replay. Reconciliation applies only to the actual single new admitted execution. The launcher must pin the driver and the final approved config by actual path, byte count and SHA256. A status label alone is not authorization.

The target remains `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1`. V1 observed that it was not created; v2 independently checks that it still does not exist. An existing target or run directory is a rejection/Unknown to reconcile, never a reason to delete it, rename it, or automatically try a different path.

A successful result still requires actual `MATERIALIZED_FOR_MAINTENANCE_ONLY`, verified primary-source and lookup stability, complete retained evidence, and the actual normal supervisor exit 0. No source/ref publication, Cargo, formatting, tests, tool installation or maintenance is authorized by this package.

## What was checked in preparation

The new source was parsed with Python AST and compiled only to a code object; the module/main was not executed. The exact original-definition comparison and full blob readbacks succeeded. The complete static record is `77d5135f1e8750591b735c3efaedcea83076a18c`.

An initial cloud-only preparation copy contained one extra final LF, so its byte-precondition assertion failed. That copy was corrected to the already intended exact bytes before the successful syntax/diff check. This is recorded explicitly; it was not a native execution, lookup behavior test, or materialization attempt.

All runtime claims remain pending the separately approved v2 native invocation. The original v1 failure and all original observations remain immutable.
