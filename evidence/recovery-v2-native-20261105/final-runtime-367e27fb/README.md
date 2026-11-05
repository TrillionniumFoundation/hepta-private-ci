# Runtime recovery V2 — final status and next native attempt

**HOLD / NO GO.** The selected runtime is **`367e27fb6bf30443641b9e23a063d24e49eda9f7`**, tree **`6a2465606f0270eeecec83c2b7d9dbef5dc96076`**. The seven new owner controls, two signed-frontier controls and IPC product controls have not obtained native acceptance in this continuation. The corrected owner attempt is **BUILD_FAILED (E0463), with zero tests executed**; it is not an expected assertion RED.

This document and [manifest.json](manifest.json) preserve the completed work and describe a future attempt. They are not a completed execution receipt. No Cargo process or test was started while preparing them. The precisely scoped cache quarantine described below completed; the rebuild remains NOT_RUN.

## Code and record identities

| Record | Exact identity and scope |
| --- | --- |
| Selected runtime | `367e27fb6bf30443641b9e23a063d24e49eda9f7`, tree `6a2465606f0270eeecec83c2b7d9dbef5dc96076` |
| Production and Rust test source ancestor | `d206c3c787f6b67c771b67a8e1d46c8261810042`, tree `00048be8564f7726716f78edbb37d79ab273167a` |
| Original V2 integration | `29fcd2e88654d5bec2bf30134cc030b5bfa7831b` |
| Historical NOT_RUN evidence | `f2bc730eb40faaf1937c5f5f5c6286e24cb2b4f7` |
| Initial environment/compile checkpoint | `3558ced0fd983603a3082a42359e8da63dfc8418` |
| RED baseline | `3a8e50ddd79ec3e52ca58157323726c37069202c`, with the recorded test-only overlay |

The selected `367e` commit adds the existing workflow entry and evidence after `d206`. Production and Rust test entries remain the `d206` entries. The JSON lists all fourteen retained source identities and the unchanged actual caller. The coordinating pair selects Chain `b5bb7bc8d7ffe79d46c6a58fd5189e2bb9e4550c`; this runtime record claims no additional Chain execution or combined pair acceptance.

Historical receipts retain their original SHA, tree, commands, timestamps and outcomes. In particular, the original NOT_RUN snapshot, an intermediate RUNNING snapshot, prerequisite failure, E0277, HEAD guard refusal and E0463 are not rewritten as later executions. New results must go into new attempt records.

## Implemented behavior

Recovery snapshot V2 reads the existing migration, qualification and AuthBus projections together with provider effect intents, uncertainty and ACK history inside one SQLite read transaction. It pages effect history, imposes a cumulative one-million-row ceiling, rejects invalid sequence values and revalidates JSON against stored record digests. Its commitment includes kind, sequence, key, digest, timestamp and ACK provenance. The schema and signing domain reject old V1 frontier input; there is no V1/V2 alias or implicit database migration.

The actual configured `EvidenceHost::open` path uses this projection. Cold-open provider validation now refuses a `StatusLookup` ACK followed by a `DispatchResponse` claim, including the path without an uncertainty row, while preserving the legitimate dispatch-then-status progression. `d206` changes four dynamic SQL expressions in the corruption/restoration test to fixed literals accepted by the SQLx safety boundary; production behavior, dependencies and features are unchanged.

The guard remains optional configuration. Signing remains **Ed25519**, with the existing **V1 signer trust-file format**. Neither different keys nor these source changes establish independent custody, independent freshness, a PQ recovery root, whole-host rollback resistance or atomic revocation with an external provider effect. AutomationStore coverage and the frontier/clock/provider race remain outside the completed scope.

## Actual validation

| Observation | Actual outcome |
| --- | --- |
| Initial owner build on the original V2 source | BUILD_FAILED: missing `pkg-config`; zero new tests |
| Original RED attempt with original test fixture | BUILD_FAILED: four E0277 SQLx errors; zero tests; no assertion RED |
| Corrected RED fixture from `d206` | BUILD_FAILED: E0463 for `sqlx_macros_core`; zero tests; no assertion RED |
| Corrected owner GREEN, signed2, full owner package and post-fix scoped lint | NOT_RUN |
| Cache preparation | CACHE_QUARANTINED_REBUILD_NOT_RUN; all original bytes retained; E0463 resolution remains UNKNOWN |
| Actual IPC product controls | NOT_RUN; local AF_UNIX creation returned EPERM |
| Source/script preflights and scoped formatting | Passed within the identities and scopes of their retained receipts |
| Workflow selection audit | 43 fixture cases passed: one accepts all 26 named controls; 42 reject missing, ignored, repeated, zero, unexpected or inconsistent records |

The 43 fixtures execute the workflow's real inline audit. They are **not Rust native tests**. They were run against workflow blob `c07b903bc589096f5927ee224abd10684d9a3c82` in a worktree based on `d206`; the same blob is now published in `367e`. Nine exact selectors were matched to real Rust function/module names, the three changed shell blocks passed `bash -n`, and the old configuration and audit logic were checked unchanged apart from the new name sets. The workflow-only `just fmt --base d206…` invocation returned zero and explicitly reported no applicable formatter groups; it is not a full-repository formatting pass.

The existing CI artifact for **29fcd**, run **41962900659**, inspected x86 source-head job **127033176702**, shows the original **14 dispatcher + 3 product** controls passing. That job subsequently failed scoped `just fix` on the original E0277 test fixture. Its artifact is 43,499 bytes with SHA256 `1931320398293bb72357ffcb829de8f35e4df3956926ab576e4f2a00ba2a659b`. Those 17 controls are historical results at 29fcd, with **no credit for the new owner7/signed2** or for execution at d206/367e.

See [the initial checkpoint](../checkpoints/restore-and-sqlx-blocker/checkpoint.json), [corrected RED E0463 checkpoint](../checkpoints/corrected-red-e0463/checkpoint.json), and [workflow audit receipt](../workflow-entry/receipt.json). No manually dispatched CI or new CI result is asserted here.

## Published CI entry

The existing PQ renewal workflow now selects the seven owner and two signed-frontier tests by complete `test(=name)` filters, with zero retries and one test thread. Each new step has a 600-second limit and shares the original 90-minute job deadline. The original 14+3 controls, four **pull-request** matrix combinations, permissions, pinned toolchain, dependency handling, concurrency policy, source checks, formatter/linter and artifact retention remain unchanged. Manual dispatch retains its original two source-head platform combinations.

The existing audit now requires all 26 selected tests exactly once and rejects missing, skipped, extra or zero selections, incorrect command status and inconsistent log digests/counts. This entry performs candidate GREEN owner7 and signed2. It **does not execute the 3a8 baseline RED campaign**. Publishing this entry does not itself establish a successful execution.

## Resource facts and continued native pause

| Observation | 2026-11-05T04:43:25.885370+00:00 | 2026-11-05T04:55:09.678118+00:00 |
| --- | --- | --- |
| Shared memory current / maximum | 8,589,787,136 / 8,589,934,592 bytes | 8,526,364,672 / 8,589,934,592 bytes |
| Global OOM / OOM-kill counters | 4 / 4 | 5 / 5 |
| Available overlay disk | 3,664,916,480 bytes | 253,034,496 bytes, approximately 241.3 MiB |

These are time-specific, shared-cgroup observations, not a per-process guarantee or proof that OOM caused E0277/E0463. Historical receipts keep their original event observations. The latest snapshot does not meet either the memory or disk admission condition for a new owner build. The same-filesystem quarantine preserves bytes and does not reclaim their disk space. Other tasks' processes and targets were not modified. The existing production checkout remains clean at d206 after cache preparation.

## Cache quarantine completed; rebuild not run

Read-only inspection found different embedded and standalone metadata for `sqlx_macros_core-67b73f8b5327a208`: 701,368 bytes inside the rlib versus 700,801 bytes in the newer standalone rmeta, with different SHA256 values retained in the manifest. This remains an inconsistency indication, **not a proven E0463 root cause or a verified repair**. No completed owner or Agentd test binary was present. Cargo manifests, lockfile, Rust pin and vendored SQLx SQLite source are unchanged from 3a8 to d206.

Preparation completed at **2026-11-05T04:53:10.290613+00:00**, confined to the owned target:

1. The existing Cargo cache lock was acquired exclusively without blocking. Actual compiler writers were classified using their readable, absolute output paths; none targeted this cache. Other Cargo frontends could not mutate the protected target while the lock was held. External process working directories were not accessed by the successful check.
2. Each allowlisted file was checked for its path, regular-file type, owner, unshared inode, size, mode and SHA256. Both fingerprint directories were checked for their exact expected entries. A same-filesystem, unique quarantine directory was created under the owned receipts directory.
3. Exactly **five SQLx macro artifacts and two fingerprint directories** were atomically renamed. The resulting **14 ordinary files / 29,091,457 bytes** retain identical contents, sizes, modes, ownership, devices and inodes; rename-related ctime changes are permitted. All seven original top-level locations were verified absent. No source, binary or evidence bytes were deleted, and no whole-target or registry clean was performed.

The outcome is **CACHE_QUARANTINED_REBUILD_NOT_RUN**. The [actual receipt](cache-preparation/quarantine-receipt.json) and JSON manifest bind every retained path and identity. Quarantine:

`/workspace/scratch/822cc50e24f0/authority-recovery/native-20261105/receipts/cache-quarantine-367e27fb-20261105T045310Z-63ff3b92/retained-target-paths`

Two earlier refusal records are also retained. The [first](cache-preparation/quarantine-refusal-cwd.json) stopped when an external Cargo cwd was inaccessible, without moving files. The [second](cache-preparation/quarantine-refusal-argv0.json) stopped after treating the shared nextest executable location as an owned work argument, also without moving files. The successful version used only the lock and explicit compiler output paths, and excluded executable argv[0] from ownership classification. It did not obtain denied cwd data. The exact three operation-script versions are preserved alongside the receipts.

**Safe rollback:** obtain the same exclusive target lock and confirm no active target writer; verify each retained SHA256, mode and size against the pre-operation record; require every original location to remain absent; rename only the same seven entries back; verify restored identities. Refuse rollback if any new rebuild output occupies an original location. Never overwrite it or delete either copy. No rollback has been needed or performed.

The next operation is a bounded **native rebuild**, not a repeat quarantine. It must wait for the coordinated serial Cargo window. Use only repository `just test`, Rust 1.96, the unchanged locked dependencies/features/profile, one build job, a 600-second first-owner bound and the existing 512 MiB estimated-availability stop floor. At least 2 GiB effective memory headroom and 2 GiB available disk are conservative admission requirements, not measured guarantees; neither permits starting under the current resource facts.

A fresh receipt must record the actual exit and all seven names. Compilation failure remains **BUILD_FAILED with zero assertion credit**. A valid baseline RED requires six assertion failures plus the passing provenance control; only then proceed to candidate GREEN in a separately coordinated phase. A repeated E0463 stops progression and does not authorize a wider sweep or weaker build. Agentd signed2 requires a later, larger compilation window because its test binary is absent. No local owner, host, lint or IPC build was started by this preparation.

## Future reproduction binding

Future candidate execution must record the actual checkout at `367e27fb6bf30443641b9e23a063d24e49eda9f7` and tree `6a2465606f0270eeecec83c2b7d9dbef5dc96076`, verify the fourteen source identities, unchanged caller and exact workflow blob, and retain source checks before and after execution. Baseline RED must instead record its 3a8 commit and exact three-path test overlay; it must never be described as a clean candidate execution.

The existing d206-bound local reproduction script correctly rejects the added workflow change. Keep that script and its receipts intact. A later automated local attempt requires a separately versioned 367e-bound entry with the same guards, or a separately recorded invocation of the exact commands in the manifest. Expected test statuses are plans, not observations. An evidence-only successor also needs its actual tested SHA recorded explicitly.

After selected controls pass, the full owner package, required scoped lint and original IPC product controls still need their own applicable execution. Whole-directory rollback, clone, crash and reorg campaigns, independent freshness/custody, unresolved-effect coordination, ordinary combined PQ authorization and independent multi-node acceptance remain open. **No A1/A2/A3 or overall P0–E security gate is closed by this record.**
