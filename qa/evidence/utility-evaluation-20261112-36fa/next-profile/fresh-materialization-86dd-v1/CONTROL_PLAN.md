# Exact 86dd fresh source materialization: control plan

Prepared at 2026-11-12 16:54 UTC. **Status: WAITING ROOT REVIEW; driver not executed.**

This prepares an offline, create-only materialization operation. It does not authorize its execution, maintenance, compilation, tests, qualification, or deployment. Root and the sole native executor must review the exact driver and explicitly approve its own config before a launch. Use one new stable native execution identity and reconcile that execution if acknowledgement is lost; never launch a replacement merely because a response is unavailable.

**Launcher admission is separate from the config's status field.** After both Root and native complete review, freeze the actual approved config as a new immutable blob. The formal launcher must pin and verify the exact absolute driver path and driver bytes/SHA256, and the exact absolute APPROVED_CONFIG.json path and its separately approved bytes/SHA256. It must use those frozen identities in the original stable-key launch record; it must not generate approval by toggling a status field during launch. The accompanying WAITING template is intentionally not executable approval. This package neither creates the approved config nor launches anything.

## Fixed identities and boundaries

| Item | Exact identity |
| --- | --- |
| Driver | Git blob `1ca5aab7144291449f89364646b62b364d3cbe0d`; 64399 bytes; SHA256 `7787562e1bdd744b54eb73c59233810013135a55e966eeaa05317fb807ef6c16` |
| Actual read-only source repository | `/home/qian-qi/hepta-utility-36fa-source-gates-c0f78493-v1` |
| Source HEAD / tree | `c0f78493f815780f68b9bf5e390a21314d79311f` / `313ee34febc8ccc54c611ab56286e289518c63cb` |
| New target, must not exist | `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1` |
| Exact target HEAD / tree | `86dd56a930277e0d1aef3e475e35c2b5d60b43b7` / `383ab85c39ef9d848252ef5c25922d13d9fae6c6` |
| Ordered original parents | c0f above, then `a96d1b821d10ed3d9e99dd06c5141f9f242ae318` |
| Target complete snapshot | 15,188 leaves; 99 changes / 27 new paths relative to fixed a96 |
| Output records | `/home/qian-qi/hepta-utility-36fa-evidence/fresh-source-materialization-86dd-v1/run`, also create-only |

The old review-19aa worktree is never an input. Its missing archive is not repaired, copied around, or assumed present. The driver reads source objects only from the fixed source-gates Git object database; it never copies working files from any old worktree. It never changes old permissions, worktree, index, refs, config, or objects, and never performs a network Git operation. The new repository has no alternates, hardlinked object store, remote, shallow file, grafts, or replacement commits.

The old c0f original commit **and its full snapshot** are retained in the new object database. Native independently checked that the ordinary formatter's `--base c0f` uses the actual c0f commit and direct tree diff, not a merge-base or full recursive history. This operation therefore preserves the exact finite snapshot domain without inventing history.

## Required actual evidence

The following are exact immutable inputs, not merely report titles or booleans supplied by a caller:

1. Actual a96 evidence-only native `ROOT_REVIEW.json`: blob `d7c135961dfacc04fe8b69697a66450e65566acb`, 38,525 bytes, SHA256 `e3fa2ee9c142b6360fb7994db28746d54b2abf9fc27ea362f08e6a80d37f7bdb`. It records 395 provided raw objects, seven full canonical snapshots, the exact 16,082 required existing set, 15,161 a96 leaves, normal cat-file completion, and identical before/after source Git state.
2. Root's independent review: blob `96406b978365a8414f9f76169421faa1f2e318d6`, 3,394 bytes, SHA256 `b1e3c533857dfb02536d10d90f999e4fcc109fc217ef868014cec6eef45c5e47`.
3. Actual native supervisor terminal SDK: blob `e25a789e1f8ae2a08d7e512b20c81790493b141c`, 912 bytes, SHA256 `95ad61f014f0f1aa6736c47811bb97001c5ceeb37f5871e08f507d1d2569ee71`; actual job `1a1d09b7b3e-2564-1ba7`, normal exit 0, no timeout/cancellation, complete durable output.
4. Actual original c0f full physical inventory identity: 5,474,911 bytes, SHA256 `cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57`, Git blob `5ed18452e2e967281ac368f934b9e4358627b9d3`. This was previously observed at 16:03–16:07; it is **not** a new physical observation. The driver must recompute it at start and finish.
5. The exact inventory implementation: blob `51181866cbbb6e0176aab04117efffa8b6792b31`, 22,946 bytes, SHA256 `20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2`.

The inventory module is loaded from those already verified bytes under a non-main module name. Only its unchanged `inventory` and `require_inventory` interfaces are called. Its original main, clone/freeze, gates, and runner are never called. This preserves the real inventory format and missing/extra-file refusal.

The driver additionally inventories every source Git metadata file/directory, including packed/loose objects, without reading atime as a mutation. That separate audit does not replace the original full worktree inventory or pretend to be its format.

## Input staging layout

The native executor stages exact bytes only after Root reviews this control package. These staging writes are separate from executing the driver.

Existing canonical input root:

`/home/qian-qi/hepta-utility-36fa-evidence/a96-canonical-independent-validation-v1`

- `CANONICAL_MANIFEST.json`: `7781160ffff79c238c5955bd8ca2e320e7ef7c99`.
- Original `packet.part-001.gz.b64` through `packet.part-005.gz.b64`, exactly as listed by that manifest.
- Original actual `validation/ROOT_REVIEW.json`, pinned above.

New materialization evidence root:

`/home/qian-qi/hepta-utility-36fa-evidence/fresh-source-materialization-86dd-v1`

- The exact driver (conventionally `driver.py`).
- `APPROVED_CONFIG.json`: initially the accompanying WAITING template. Its flag cannot be changed to approval by this driver.
- `inventory-driver-v2.py`: exact 51181866 original.
- `ROOT_INDEPENDENT_REVIEW.json`: exact 96406b97 original.
- `CANONICAL_TERMINAL_SDK.json`: exact e25a789e original.
- `prepared-input/PREPARED_MANIFEST.json`: `d8ea5b18c429024b3ba2bdd3ee171a4fb0a58a98`.
- `prepared-input/prepared-86dd.part-001.json-fragment.txt` through `...005...`, exact manifest names.

The driver checks its own complete bytes against the approved config and rechecks every input at the end. Symlinked parent directories and reused output/target paths are rejected. There is no bootstrap or native launch embedded in this package.

## Operation sequence

### A. Read-only preflight

Require the explicit approved exact-driver config and all three actual review/terminal records. Require the current source HEAD/tree/index/refs to equal the actual successful a96 review. Compute the original c0f full physical inventory and compare all bytes to the fixed baseline. Preserve the actual observations before asserting equality, so a preflight failure has its real evidence.

Strictly parse both original manifests and their different transports. The 395 package joins five base64 segments after removing exactly each final LF, base64-decodes and gunzips to the exact 12,080,171-byte JSON packet. The 87 package joins five **raw JSON fragments without trimming, decoding, or gzip** to the exact 3,241,174-byte packet. Each object's raw_base64 is separately canonical-decoded and checked for original type, size, SHA256, and Git object SHA.

Read original objects using `git cat-file --batch`. Reconstruct the full b298 and c0f snapshots, all seven upstream snapshots and their exact per-commit differences, and the final 86dd snapshot/difference. Check raw original parent order, author/committer timezone and message ending without recreating commits. The known 16,136 old snapshot objects and 482 provided objects form an actual deduplicated import union: 16,618 is an upper bound, not an assumed observed count. Any overlap must have identical type, length, SHA256 and Git identity. Both input packages retain their full individual counts.

The 1,451 entries in the 87 package are checked as **direct references only**. All referenced tree/blob objects are recursively traversed; they are not used as a substitute for the complete closure. Earlier parent links outside the bounded import domain are recorded, not walked, removed, or replaced. Prior whole-history fsck limitations remain.

Before creating the target, check actual free disk against two conservative pack copies, all final physical file bytes, and explicit record/headroom reserve. Insufficient space stops without creating a new source. No cache cleanup or user-file deletion occurs.

### B. New repository object import

Create only the fixed nonexistent target. Initialize an independent standard Git repository with an empty template and raw-byte/filemode/symlink settings. Build a standard non-delta PACK v2 from the already verified **original raw object bodies**. Record header version/count, all object types, pack SHA1 trailer, full pack SHA256/length and zlib runtime. No commit is synthesized.

Use the explicit local command `git index-pack --threads=1 --stdin` in the new repository. Verify the resulting stored pack matches the exact input bytes and checksum. Read **every imported original object** back from the new database with a separate batch process and compare its actual type/length/SHA256/Git SHA. Reconstruct all ten bounded snapshots again from the newly read tree/commit bytes. Old c0f is available for later formatter diffs.

The original PACK input remains in the new Git directory as a recorded copy. This is a reproducible import artifact, not a tracked source file or a shared-object dependency.

### C. Exact physical tree and index

Populate the new index from the exact final tree and set only the new repository's HEAD to the actual detached 86dd commit. No branch/ref is created in the source repository or remotely. Preserve the complete new pre-materialization inventory with all 15,188 tracked leaves missing.

Write each final regular file from its newly verified original blob using exclusive creation and exact Git executable mode; recreate symlink payload bytes without following symlinks to create descendants. Preserve raw bytes, BOM, line endings and encodings. Recheck remaining actual disk space before writing. Sync newly written files and directories.

Run the same original full inventory implementation over the new source. Require all 15,188 leaf identities, full raw SHA256, modes/types, no missing or extra file, clean status, exact index entries, `write-tree = 383ab85...`, and detached `HEAD = 86dd...`. The inventory hash is observed at execution; this preparation does not invent it.

### D. Final evidence and terminal decision

Close only the driver's own cat-file helpers. Independently retain source-after, new-destination-final and input-stability audits; one failed comparison must not suppress the other available evidence. Old source inventory, Git metadata and HEAD/tree/index/refs must match their actual before states. The completed destination must still match its observed complete final inventory.

The driver uses a separately approved **600-second materialization budget**, plus **180 seconds for bounded final evidence and cleanup**. These are preparation-operation limits, not modified source-closure, fullcaller, nextest, native test, or maintenance limits. Git subprocesses are bounded and only owned Git helpers can be terminated. No Rust/Cargo process is started or killed.

Each phase has an immediate started record, a durable JSONL event and actual progress. Full original inventories and snapshot/object audit JSON are preserved losslessly as deterministic gzip with independently hashed bounded base64 chunks. Source checks, explicit integrity failures, timeouts, missing evidence, and partial target state retain different recorded statuses.

Acceptance requires both `MATERIALIZED_FOR_MAINTENANCE_ONLY` **and** the actual normal native supervisor exit 0 with complete durable output. A RESULT file alone is insufficient if terminal recording later failed. Any uncertainty prevents maintenance admission. A partial target stays in place for review; no overwrite, rename-to-retry, automatic rerun, or repair of an old worktree is permitted.

## Explicit non-actions and remaining work

The driver does not call Cargo, just, fmt, a test runner, a verifier gate, sudo, a dependency installer, fetch, push, checkout of an old worktree, or any API. It creates no remote/source/evidence ref or PR update and changes no product authority.

The prepared tree still contains incomplete non-Rust protection/QA/allowlist work. Its 59-file ordinary profile preparation and three reviewed Rust increments have not been qualified by this operation. Native's later scoped original just fix/fmt, the sole non-Rust author's final formatted fences, subsequent frozen source, and all required actual gates are separately controlled steps.

## Preparation verification actually performed

Only the driver's Python AST parse and compile-only syntax validation were executed, in a newly created cloud directory `/tmp/hepta-86dd-fresh-control-36fa-VJCeMI`. Python 3.12.14 accepted the 1,085-line, 64,399-byte driver. The main function was not executed; no Git import, native task, source tree materialization, source gate, or Rust test occurred. The driver and accompanying documents are stored as immutable Git blobs and read back in full. Old cloud files are not assumed restored.
