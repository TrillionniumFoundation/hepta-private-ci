# cc57 isolated reconstruction: preparation only

Status: HOLD. No host operation, source repair, new repository, admission, Cargo command, gate, ref update, or new native main is authorized by this document.

## Intended result and preserved evidence

Preserve `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1` in its actually observed condition, including its extra local ref, changed raw index, and seven missing evidence archives. Do not restore, reset, delete refs, change index flags, rename the old repository, or reuse the failed 1cd4 records.

The proposed fresh destination is `/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1`. It must be absent when a separately reviewed materialization starts. Its subject remains commit `cc57c7198db6293ccca562253c42fffbe2a04633`, tree `b7b357c07b5539769a068c6b9b009629f5612d1e`, and parent `246d8cb614770252ee42029a5c014f2a4904176a`. This is not a new source revision.

The full original physical inventory is 15,188 entries / 5,611,184 B / SHA256 `13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9`. The original native five-field projection is 3,530,181 B / SHA256 `20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9`. Neither expected value changes to the failed snapshot's `6c28...`.

Actual evidence: source job 1cb4 passed its three original gates and retained an intact original source in that observation window. Native job 1cd4 later failed admission before any behavioral stage. Observer 1ce4 completely read the two original artifact streams and found 15,181 equal rows plus seven `missing:true` rows; the current read-only refs query separately reported one extra ref. The index body has not yet been retrieved. The writer/cause remains Unknown. No old pass is relabeled as a successful native execution.

## First operation proposed for exact review

`OBJECT_AVAILABILITY.HOLD.py` is only a read-only observer. It reads the already completed original 1cb4 inventory artifact, derives the complete B7 Merkle tree, verifies the current repository's raw cc57 commit and all 1,828 expected tree objects, and fully reads/hashes the seven required local Git blobs (18,176,884 B total). It checks ordinary `cat-file --batch-check` metadata for the exact current snapshot's 16,439 unique objects: 14,610 blobs, 1,828 trees, one commit. No parent-history traversal or fsck is performed, and no network fetch occurs.

The observer also retains fixed old HEAD/config/index/ref identities before and after these reads and preserves the actual current index full-read identity and stable stat. It does not transmit the approximately 2 MB index body or a compressed copy. It does not require the old repository to be clean or refs to be empty; those conditions remain required for the future fresh destination. All present/missing/wrong-type/wrong-size outcomes are explicit. A normal observer exit means the observation completed, not that materialization or qualification passed.

The observer does not read the current 15,181 physical source files. Their continued availability is therefore not established by this first operation. The exact original inventory and seven missing-row identities are frozen inputs, not new source observations. Source and records are never opened for writing. Any process cleanup is limited to the observer's own read-only Git child. Observer outer 60 seconds, action deadline 45 seconds, bounded Git subprocess waits; these are diagnostic budgets and do not change any gate budget.

## Can reconstruction use 15,181 existing files plus seven local Git blobs?

Yes, conditionally. The required bytes, modes, SHA256 and Git blob identities for every path are already fixed by the fully verified 13d3 inventory. The seven missing archives have exact identities, not guessed substitutes. If the first observer confirms those seven local Git blobs, a subsequent approved materializer can re-read every remaining physical source file with stable before/after metadata, verify full bytes/mode/Git identity, and create independent destination files; for the seven missing paths it writes only the exact Git blob bytes that pass their known length/SHA256/Git SHA. Symlink contents must be preserved as raw link targets and never followed.

The remaining 15,181 files must pass that new full read. The earlier native snapshot is not a substitute. Any unexpected path change, extra source entry, missing file, symlink traversal, or object mismatch fails preparation and preserves partial new output without rollback. There is no permission to copy the old raw index, refs, skip flags, config, alternates, or working-tree omissions into the new source.

For the new Git store, the 15,188 source leaves deterministically produce 14,610 exact unique blob bodies and 1,828 exact raw tree bodies. Import only independently verified bodies; preserve the original cc57 raw commit bytes and required original parent anchors. Do not invent or reserialize commits, install shallow/graft boundaries, or claim full history completeness. The precise retained ancestor-object scope must be fixed before materialization is approved; current native/source entry points use current HEAD/tree and tracked files, and this preparation does not authorize a new formatter/history traversal. If preserving additional already-present historical objects is necessary, scope that separately without recursive full-history fsck or a network fetch.

The new repository must have its own object store, no alternates, detached exact cc57 HEAD, no local refs, and a normal fully refreshed index equal to B7. Index entry modes/OIDs and absence of skip-worktree/assume-unchanged state must be checked. The new raw index will have different normal stat bytes; its exact new raw identity is recorded as a new baseline, never copied from the old 8aa or b6ab index hashes.

## Materialization proof and source invariants

A later separately approved materializer must create fresh control/run directories and an independent repository, retaining the original preparation budgets of action 600 seconds plus evidence 180 seconds and outer 900 seconds. It must take the task's cooperative source lock in the reviewed mode, preserve old source/Git observations, verify every input and object, record each attempted mutation only in the new destination, and produce a normal authoritative supervisor terminal plus complete source/Git/input audits. There is no implicit approval to start it now.

Success must bind: actual destination path; actual cc57/B7/[246d] identities; 15,188 full physical rows; exact 13d3 full inventory and 20008 native projection; no extra files; normal index logical contents and complete raw Git state; no refs/alternates; independent object storage; old source/index/refs untouched by this operation; input identities unchanged; no Cargo, formatter, tests, remote ref updates, retries, or source revision changes. Record missing historical observations as Unknown rather than claiming a new old-source clean state.

Materialization proof is not qualification. It cannot rewrite the previous canonical alignment's source_repo or raw index. It may establish a new current Git baseline only after its actual normal terminal and all complete audits are reviewed.

## Minimal successor admission: two unchanged V5 instances

Keep the original V5 file byte-for-byte at 63,007 B / SHA256 `ff2078884d48dcb92ec3b681d7479c33e9b074d1677108ce60e913c90f002431` / Git `6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735`. Keep original b92, 5118, source wrapper, native test sequence, repository entry points, and all limits unchanged.

1. The historical-runtime instance retains its original REPO, SEED_HEAD/SEED_TREE/parents, DEPOT, TARGET and historical proof paths. Invoke only the unchanged `environment_preflight` chain; it validates the actual original restore result/environment/normal terminal and re-observes tools, versions, V8 pair, external Python/Ruff, external directories, target ownership/free space and the original same-UID global process guard. It never treats the damaged old worktree as the current qualification subject.
2. A separate current-source instance loads the same exact V5 bytes, verifies its original constants, and then receives explicit, reviewed assignments for the new REPO and current HEAD/TREE/OUT. Use its unchanged raw Git/no-refs/inventory/input helpers for the fresh repository. Never temporarily swap this instance back to the historical path to make its source predicate pass.
3. Keep the original runtime environment's nine approved configuration components and exact values. CARGO_TARGET_DIR remains `/data/hepta-utility-36fa-final-native-target-v1`; minimum free space remains 32 GiB; create_target_if_absent remains false. No reinstall or changed compiler flags are implied. Moving the source absolute path can require additional ordinary Cargo compilation, which remains inside the original budgets.
4. Independently enforce current-source separation from target/depot/venv/cache/records directories with the current instance. The historical restore actually observed inherited CODEX_REPO_ROOT and PYTHONPATH as null; retain that exact prerequisite and inspect it again. The native wrapper later explicitly sets these to the current repo and its scripts directory as it originally does. Do not accept an inherited pointer to the damaged old worktree.
5. Historical final-format and canonical-alignment results remain tied to their real original source_repo. Continue every existing original command/terminal/audit/tree/postimage predicate with that fixed historical path. Do not rewrite original proofs or compare new raw index bytes to old alignment.after.git_state.
6. Add one strict fresh-materialization proof binding: exact result and authoritative normal supervisor/job, exact old canonical content anchor, exact destination/new Git state/full inventory, all flags/audits above. Current raw Git must equal this new actual state, and current full inventory/native projection must remain 13d3/20008.
7. Audit inputs and read-only commands of both independent guard instances, retaining separate output namespaces and finally checks. Current source before/after checks and original stage guards remain mandatory. A historical-runtime check does not provide current-source before/after evidence.

The current a8be module has four specific coupled predicates to adapt explicitly: m.REPO==cfg.repo in __init__; final_format.source_repo==cfg.repo; aligned.source_repo==cfg.repo; current raw Git==old alignment.after.git_state. The original V5 environment validator additionally binds historical runtime-restoration source_repo to its original REPO; the separate historical instance preserves this predicate unchanged.

## Qualification remains separately gated

No new native request is part of this plan. New records/control names must not reuse 1cd4. Root has now specified that the actual existing successful source-gate result remains bound to the same cc57 source and will be accompanied by a new actual materialization proof; a directory move alone does not justify rerunning those gates. Any new source recheck requires a specific remaining risk. This does not turn the old result into a new execution or a native pass. Original source 600/300/4800 with outer7200, native outer45000, original eval/focused/ordinary/Root budgets, 8 MiB stack, original nextest overrides, zero retries, permission checks and all source invariants remain unchanged.

## Supporting immutable evidence

- Native 1cd4 failure originals: placement `60fadd59f5dce6cdfd3897236414be8fac86ee1e`.
- Read-only 1ce4 original row/refs diagnostic: placement `553bc526febf4c5d607a9d353e4c17c7f8f4a15e`; complete row diff `5ca1a28c507d5f38710cbac9fe11b67418e98214`.
- Environment/source dependency review from evaluation: `4e4bd8f3cbf84fe599427ccb9f97c503af8e389f` (independent static review; live tool/material checks still required).
- Current source artifact identity was actually re-read by 1ce4; exact recovered raw failed snapshot is evidence only, not the target source.
