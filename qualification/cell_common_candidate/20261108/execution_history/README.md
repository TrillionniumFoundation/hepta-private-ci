# Increment 010 — original workspace timeout and counterfactual failure

This increment preserves two completed history packages and their subsequent seal/readback receipts. It extends evidence commit **6e162bab21438b857179a22c6207552feda9331b**, tree **db1528464ed0369f3be4b7a8a7b4d8df6d9abde0**, from **93 to 95 packets**. All previous packet entries and bytes remain intact. The resulting **11,384 archive-member entries** include repeated provenance and observations; they are not independent tests or unique source files.

The common PR source remains **bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d**, tree **f7b65a747a1d2f585be38a4665ab2b4f1b07efb6**. Its full repository CI remains failed. The formal CURRENT SHA256 remains **c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4**. All S0–S5 stages remain **HOLD**. Physical and complete-history costs remain **null**.

## Two source scopes, with their original outcomes

| Source and retained scope                 | Actual outcome                                                                                                                                       | Interpretation                                                                                                                                                   |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6ec5993, original workspace controller v1 | Controller failure before any native command, caused by its assumption that two parent environment variables already existed.                        | The subsequent metadata-only controller correction preserved the original workspace command and budget. The failed preparation remains.                          |
| 6ec5993, original workspace v2            | The original **4,200-second** budget expired: wrapper exit **124**, child **−9**, driver/collector/outer **1/1/1**.                                  | Raw output proves native activity, but there is no final native Summary or fresh native JUnit. Complete execution counts are **null** and case closure is false. |
| 6ec5993, partial records reader           | Readback completed; **6,821 unique PASS-shaped raw keys** were observed before termination.                                                          | These are partial observations, not a verified full-workspace pass count. Declared start counts do not establish the complete executed roster.                   |
| 6ec5993, timeout artifact retainer        | Failed when the required target was unavailable; **zero paths and zero executable bytes copied**.                                                    | Original record inputs were stable. Complete source-after/helper/inventory verification was not reached, so those guards are not claimed as passed.              |
| d27431b, one exact counterfactual case    | **One FAIL**, zero PASS, zero retries, 2,447 filtered cases outside selection. Native driver/test/collector remain **1/100/1**.                      | The expected `HEAD` assertion failure was observed. Expected counterfactual failure does not change the native outcome to PASS.                                  |
| d27431b, subsequent binary retention      | One independently copied test binary, **453,757,728 bytes**, with exact hash and identity checks; retention and its independent readback returned 0. | The executable remains on the host and is not in this evidence package. Successful retention does not change the failed test.                                    |

The workspace source is **6ec5993fec3dcd6a3c569498a1d5b4c277f1c142**, tree **b0ddbe6b6f83dc42657260b266774f79c9d1ed90**. The counterfactual source is **d27431b69195a2a6331a77d19e22ebeb4cf910c7**, tree **b1cf50c33f5ec9101217ae3f6a7ff987e3aba973**, with parent **3fc4725343dccfc9487e937f77e30bc6a5d80dbc**. Results are not transferred between these sources or to common bf42.

## Workspace timeout and artifact availability

The timeout package retains the original controller attempt, corrected controller, original receipts and complete captured raw output. It also retains the bounded partial reader, process observation, failed forensic retainer, exact-path metadata observations, and the later read-only availability check of fourteen previously retained Core/helper copies and two tools. That preflight verified **3,037,089,672 bytes** of retained copies without executing them. It does not establish that the unavailable workspace target was restored or that a different target contains this run's compiled artifacts.

The bounded process observation found only the expected Root shell among its selected observable processes. Its many denied or unavailable `/proc` link reads remain explicit limitations; it is not proof that every escaped process was absent. Fixed-path observations preserve the actual missing-target facts. They do not identify a deletion actor or prove why the target became unavailable.

The timeout history was sealed at **13:27:05 UTC on 2026-11-09**. The first launch acknowledgment was retained through the later H readback interruption and was reconciled without replaying the seal. Independent packet verification finished at **14:16:13 UTC**. Those later observations do not move the original workspace execution cutoff or fabricate a native JUnit report.

## Exact d274 counterfactual and retained provenance

The selected case is `unified_exec::async_watcher::tests::terminal_summary_retains_output_published_before_streaming_subscribes` in the Core library. Its frozen 2,841-byte source has SHA256 **cccd41df340c5776dd078eac87418c25a5816dde4d43bd6946861331d4065879**. The original failure is at `async_watcher_tests.rs:161:13`, where the expected `HEAD` prefix was absent. The complete original raw output, fresh JUnit and failed collector result remain unchanged. The native outer completed at **13:37:14.679131 UTC**.

The selected-case failure supplies bounded counterfactual evidence for this frozen oracle. It does not establish the precise race that caused the older bf42 large-output CI failure. The package retains the original V8/fix/Clippy/discovery receipts and the full source-inventory metadata before and after execution and retention. All **68** originally bound record inputs are included. Six source inventory files each describe **15,010 entries**; their contents are metadata, not copies of every source file.

The one retained executable was copied independently with a new inode, one link and mode 0555. Its original native-time discovery established a path/size/hash; complete inode identity was captured later at retention time. The evidence does not retroactively claim an earlier inode observation. The retained ELF's SHA256 is **89a1bc28b83a2c0d24a917badd2e6209126c514409a332cf308957e1a26ad7fb**; its bytes remain host-only.

There is one explicit nontext source-provenance member: the original **1,800-byte Git bundle**, SHA256 **0e753e10409b9619c7ddff22cd36f00bcfb74f248f5bbb09dadbc989222a6f5e**. Its exact packet, member path, size and hash are admitted. This exception does not admit ELF payloads, arbitrary NUL-containing members or other binary files. The bundle remains subject to the archive hash, exact member closure and the same bounded pattern scan.

The d274 history was sealed at **14:44:17.740007 UTC**. Independent member verification completed at **14:51:17.696594 UTC** with all 130 members and all 119 current original record files checked; all 136 readback inputs remained stable. These are records operations and add no native cases.

## Exact package and supplementary metadata scope

| Packet                                                             | Members | Compressed bytes | Original record boundary                                         |
| ------------------------------------------------------------------ | ------: | ---------------: | ---------------------------------------------------------------- |
| desktop-6ec-workspace-timeout-and-artifact-availability-history-v1 |     146 |        2,599,580 | 140 originals, five generated metadata members and the manifest. |
| d274-negative-native-retention-history-v1                          |     130 |        1,342,472 | 119 originals, ten generated metadata members and the manifest.  |

The two packages add **276 member entries** and **3,942,052 compressed bytes**. Those storage quantities include overlap and are not network-transfer measurements, unique-program counts or complete execution costs. Actual Git file counts are determined by staged-index and committed-blob verification.

Twenty-six supplementary originals preserve the 009 publication and independent readback RESULT/commands pairs; each new packet's final seal RESULT and complete four-file outer receipt/log set; and each packet's independent RESULT, four-file outer set and exact verifier script. The 009 command metadata identifies its original stdout/stderr hashes, but this increment does not claim to copy that publication's entire raw-output directory. Every supplementary file requires exact bytes and mode verification in the staged index and final commit.

The timeout archive already preserves the PR-v7 observation and both versions of Root's 009 publication observation. The first hand-entered capture time is retained as a corrected historical value; the successor records the time evidence and leaves embedded original strings unchanged. Later PR revisions, source D/E preparation or publication, and new native activity are outside these two packet cutoffs unless a subsequent increment explicitly binds their originals.

All JSON comparisons preserve original Python integer values and exact types. Neither successful archiving, independent readback nor expected negative-control failure advances scientific qualification. The existing 009 README follows byte-for-byte as historical context.

---

# Increment 009 — completed desktop owner records and quiet-source publication

This increment preserves six completed evidence packages for frozen source **6ec5993fec3dcd6a3c569498a1d5b4c277f1c142**, tree **b0ddbe6b6f83dc42657260b266774f79c9d1ed90**, parent **45a50bffd1631d502889069fc3f713b8a5e775d8**. It extends the published 008 checkpoint at **8ca3f19c69f2f14a42aa5fbe3ff72af807c65ff2** from **87 to 93 packets**, retaining all original packet entries and bytes. The resulting **11,108 archive-member entries** include repeated provenance, receipts and readbacks. They are not unique tests or source files.

The common PR head remains **bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d**, tree **f7b65a747a1d2f585be38a4665ab2b4f1b07efb6**. Its complete repository CI remains failed. The formal CURRENT remains **c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4**. S0–S5 remain **HOLD**; physical and complete-history costs remain **null**.

Six packages add **1,004 member entries** and **8,125,656 compressed archive bytes**. These are storage quantities with overlap, not transfer measurements or full execution cost. Git file counts are established by the actual staged-index and committed-blob closure, not by adding archive member counts.

## Completed scopes and preserved outcomes

| Retained scope                            | Actual outcome                                                                                                                       | Boundary                                                                                                                                                       |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Desktop dependency and strict preparation | Nine original preparation/strict steps returned 0; original 15,010-file source inventory unchanged.                                  | Execution cutoff **09:37:11 UTC**; zero native cases in this package. Earlier desktop artifact HTTP504 and incomplete/superseded transfer observations remain. |
| Core owning package                       | **3,827 unique PASS**,9 original ignored,0 retries/leaks/explicit early-return markers. Four required regression cases are a subset. | Completed **09:58:20 UTC**. Does not establish workspace success or the historical bf42 race mechanism.                                                        |
| App Server owning package                 | **1,345 PASS +3 exit101 FAIL =1,348 selected**,2 original ignored,0 retries/observed leaks.                                          | Native driver/just-test/collector remain **1/100/1**. Five required cases passed individually; the original overall gate remains false.                        |
| Agentd default owning package             | **781 unique PASS**,71 original ignored,0 retries/leaks/explicit early-return markers. Thirteen checkpoint components are a subset.  | Completed **10:39:34 UTC**. One SLOW progress classification and later output repetition do not add executions.                                                |
| Separate Root checkpoint fixture          | **One original ignored parent case executed and passed**, four phases, real Root service and the same registered non-Root consumer.  | Completed **10:47:17 UTC**. Two libtest summaries count as one acceptance parent; this is not an ordinary-daemon learning loop.                                |
| Posthoc diagnostics/readbacks             | Bounded original records captured/compared; observer failures and narrow corrections preserved.                                      | Zero new native executions. Existing Core, Agentd and Root counts are not added again.                                                                         |
| Frozen source publication                 | One normal push of existing 6ec to its independent review branch, followed by Git/API source/tree/parent readback.                   | Completed **11:23:34 UTC**. Actions query returned 0 runs at that observation, neither CI success nor a future-absence claim.                                  |

Host-only retention sets are **14 Core copies / 3,037,089,672 bytes**, **16 App Server copies / 2,874,949,592 bytes**, and **29 Agentd copies / 3,760,364,392 bytes**. Only metadata and original receipts are included. Executable bytes were not read or rehashed by this increment's preparation. Helper copies overlap between sets and are not unique compiled-program counts.

## Exact package inventory

| Packet                                                                   | Members | Compressed bytes | Original-record boundary                                                           |
| ------------------------------------------------------------------------ | ------: | ---------------: | ---------------------------------------------------------------------------------- |
| core-output-6ec5993-desktop-dependency-strict-history-v1                 |     198 |        1,305,748 | 184 terminal originals plus 14 capture/generated metadata members.                 |
| core-output-6ec5993-desktop-core-native-retention-history-v1             |      64 |        1,860,496 | 46 originals plus 12 capture records and 6 generated metadata members.             |
| core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1 |      86 |        1,941,672 | Failed-owner records, 15 extracted failure payload files and retention metadata.   |
| core-output-6ec5993-desktop-agentd-root-native-retention-history-v1      |     100 |        1,223,632 | 81 originals plus 13 preparation/capture records and 6 generated metadata members. |
| core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1      |     117 |          247,008 | 112 explicit originals plus 5 generated metadata members.                          |
| core-output-6ec5993-quiet-source-publication-history-v1                  |     439 |        1,547,100 | 433 explicit terminal originals plus 6 generated metadata members.                 |

Every archive has a whole-file SHA256 pin, exact member roster, size/hash/mode checks and independent member readback. Full original JSON bindings use recursive type equality; numeric zero is not silently interchangeable with false. Compact input serialization preserves complete typed objects while meeting the publication-file bound. Original member bytes and JSON formatting remain in the archives.

## Failure and observation history

App Server retains three actual failures: the OAuth localhost:1455 connection failure and two managed automatic-review cases whose expected wiremock counts were unmet. Bounded posthoc comparisons do not prove one shared environmental cause and do not relabel the run. The diagnostic packet includes original managed-review captures, the OAuth collector's first cardinality-assumption failure, corrected capture and both summary versions. The original JavaScript-derived timestamp rounding remains historical; the Python lossless successor preserves original nanoseconds **1794219243183664456**.

Posthoc Core evidence includes the actual independent reader RESULT and execution receipt, not that reader's entire preparation/raw prefix. Agentd/Root audit records and preparation files are explicitly listed. The first archive reader's rejection of an original Summary containing "(1 slow)" remains beside its corrected readback; native cases were not rerun.

The Root driver's 53 bound input references are not a claim that all 53 external files were copied into this package. Its 81-original whitelist and member roster identify retained bytes. No active /run directory, executable, whole PTY or shared target was read by sealing.

Source-publication history preserves the first admission controller's integer-zero schema rejection and successor, exact final admission, all 93 command records and their stdout/stderr, 17 copied validation observations, and seven Root H/GitHub captures. It retains **13 NUL-delimited Git stdout files** only where archived commands.json supplies the same Git -z argv, size and SHA256. The discovery guard's first rejection of those valid original bytes is retained. A later independent reader initially tested a literal backslash-zero instead of a NUL byte; that observer failure, exact correction and successful successor are separate supplementary records. Neither correction executed native code or changed the archive.

## Quiet source is published; common is unchanged

The independent source ref is **refs/heads/codex/cell-s0-core-output-20261109-898e**, pointing to frozen **6ec5993fec3dcd6a3c569498a1d5b4c277f1c142** with the exact tree and parent above. Publication created no source commit, used one normal push and preserved source inventory/index, common head and formal CURRENT. Admission contains App Server FAIL and the first workspace controller's pre-native FAIL. That controller attempted no Cargo command or native case. Workspace-v2 outcome was not read or inferred by admission, publisher, sealers or this increment.

Separate source diffs affect 19, 6 and 1 paths; the last path overlaps an earlier change. Their union relative to common is **25 paths**, not 26. Publication makes the repair directly reviewable without promoting it into common or transferring passes across source revisions.

PR5397 status009-v6 is a separate metadata observation: one body PATCH, exact 9,876-byte body SHA256 **9fd94488525dfc61aecbf8fd7b0cc94d461107d7d2a413ec95232ee15698d5d0**, and before/after API captures. The PR remains open/draft at common bf42. Its **11:23:34 UTC** narrative cutoff is preserved; later metadata capture is not presented as earlier execution.

## Additive evidence and exclusions

Nineteen supplementary originals retain six independent packet readbacks; prior 008 publication/readback RESULT/commands pairs; the PR body observation; and source-publication sealer/reader failure-and-correction records. Prior 008 RESULT/commands links are retained, not the entire stdout/stderr directories. Hash references identify omitted raw files without claiming their bytes were copied here. Every new observation requires exact staged-index and committed-blob verification at publication, including original log/diff paths ignored by generic Git defaults.

This increment excludes workspace-v2 outcomes, any d274 negative-control outcome, new Windows/Bazel execution and unprovided production learning registration/owner inputs. At input freeze (11:56:21 UTC), workspace-v2 was still running and d274 had not been executed; those states are historical observations, not assertions about publication time. It does not read active targets, execute archives, repeat native cases or change assertions, budgets, retry settings, authorities or production refusals. Earlier bf42,45a and 6ec attempts remain under immutable packet entries. The original 008 README follows byte-for-byte as historical context.

---

# Increment 008: retained core failure and blocked timer history

This checkpoint adds four completed historical packets to the 83 packets in evidence commit `e781fbebad63968adf18cce97dd04657b3854917`. The result is **87 packets and 10,104 file-member entries, including overlaps**. Those entries are archive contents, not unique tests, tasks, experiments, improvements, or cost observations. All four archives, every enumerated file member, and 27 selected original JSON objects are bound by bytes and SHA-256. The prior 83 packet entries and bytes remain unchanged.

**The common product source is still `bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d`, tree `f7b65a747a1d2f585be38a4665ab2b4f1b07efb6`. Its original full repository validation remains failed. S0, S1, S2, S3, S4 and S5 remain HOLD.** The formal `CURRENT_RESULT.json` SHA-256 remains `c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4`. Physical cost and complete historical cost remain `null`.

The new histories concern two separate local candidate sources. They do not replace the common bf42 result or inherit results from the previously retained 3fc source:

| Source                                     | Exact tree                                 | Retained scope and outcome                                                                                                                                                                                                              |
| ------------------------------------------ | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `45a50bffd1631d502889069fc3f713b8a5e775d8` | `60fd0cc181f3f34dbbb3a4a9a63226b920260ce2` | Nine strict preparation stages passed; the full core owning execution **failed**. Its separate original desktop caller gate passed.                                                                                                     |
| `6ec5993fec3dcd6a3c569498a1d5b4c277f1c142` | `b0ddbe6b6f83dc42657260b266774f79c9d1ed90` | Timer-only test successor of 45a. Both retained AI preparation attempts failed during the official V8 checksum download; no helper build, owning lint, or native case began in those attempts. Its separate desktop caller gate passed. |

The four packets deliberately stop at their recorded historical cutoffs. Subsequent desktop V8 readiness, recovery, strict preparation, or native execution is outside these archives and is not inferred from them.

## Four additional immutable packets

| Packet                                                                                                                                                                  | Original archive SHA-256                                           | Original archive bytes | File members |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ---------------------: | -----------: |
| [45a AI failed owning history](packets/core-output-45a50bf-ai-failed-owning-history-v1/manifest.json)                                                                   | `f5ad5116de21dc92dfb5946e9487ce2577bd7c14e77cd505a1956efb25ace436` |              3,559,024 |          187 |
| [45a desktop preparation and caller history](packets/core-output-45a50bf-desktop-preparation-caller-history-v3/manifest.json)                                           | `b5aa757ab9003bb6d8bdae47dd0903f3a30e3cd116624e2dfb7d69d6e657103c` |              2,830,716 |          278 |
| [6ec AI checksum failures and environment preparation](packets/core-output-6ec5993-ai-two-checksum-failures-environment-history-v2/manifest.json)                       | `8a19f8d2a2bb455240d079dbc61187aaef456735cd83c4b92da381c4d1f461c3` |              1,076,276 |           61 |
| [6ec desktop source, caller, and unexecuted control preparation](packets/core-output-6ec5993-desktop-source-caller-and-unexecuted-control-preparation-v1/manifest.json) | `eb49b7680e375f3d5090be457911a0f01a85fdbac23a0c2f534b2ece1c7dac39` |              2,383,948 |          109 |

Their 635 additional member entries include copied source lineage, repeated runner inputs, independent readers, and retained preparation failures. The total original archive size is 9,849,964 bytes. Neither value is a count of independent experiments or a resource-cost measurement.

## The original 45a full core result remains FAIL

The original full core selection executed 3,827 distinct cases and left nine original ignored cases unexecuted. The original command returned **100**, its collection step returned **1**, and its owning driver returned **1**. Later independent readers returned zero only after proving the failed execution's discovery, raw status, and fresh JUnit closed sets. Their zero exits do not change the original outcome.

| Original terminal classification                   | Distinct cases |
| -------------------------------------------------- | -------------: |
| PASS                                               |          3,274 |
| Ordinary FAIL, exit 101                            |              6 |
| SIGABRT                                            |            545 |
| TIMEOUT                                            |              2 |
| Total executed                                     |      **3,827** |
| Original ignored, not executed and not added above |              9 |

The 551 failures in the original Nextest summary are the six ordinary failures plus 545 aborts. Including the two timeouts gives **553 nonpassing executed cases**. Original progress lines and final-output copies are not additional executions. The retained reader found no selected retries, LEAK records, or the known explicit early-return guards; these checks establish accounting limits, not a clean pass.

The four required output cases are a subset of this same execution:

| Binary and original case                                                                                                                      | Actual result  |
| --------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| `codex-core` / `unified_exec::async_watcher::tests::terminal_summary_retains_output_published_before_streaming_subscribes`                    | PASS           |
| `codex-core` / `unified_exec::process::observation_tests::native_output_keeps_both_prefilled_streams_through_eof`                             | PASS           |
| `codex-core` / `unified_exec::process::remote_observation_tests::remote_transcript_records_accepted_output_once_without_treating_exit_as_eof` | FAIL, exit 101 |
| `codex-core::all` / `suite::unified_exec::unified_exec_formats_large_output_summary`                                                          | SIGABRT        |

Every one of the 545 original abort payloads contained the test CODEX_HOME constructor's ENOSPC failure. Five of the six ordinary exit-101 failures also contained ENOSPC text. The other ordinary failure was the remote collector's 21 ms versus 20 ms clock assertion. The two timeouts retain their full original payloads and are **not** both proven to have the same constructor failure.

A later filesystem observation found no free inodes on the affected temporary filesystem while byte capacity remained. That was a post-run measurement, not a resource time series during all cases. It does not identify the process that consumed the inodes, explain both timeouts, or prove that an environment change fixes all failures. The archived classifications explicitly keep `all_failures_explained=false`, `all_failures_fixed=false`, and `environment_change_proven_to_fix_any_case=false`.

The native packet preserves the strict receipts, source and selection inventories, original merged raw, original JUnit, failed reader preparation, failure-aware accounting, per-failure readback, and binary retention metadata. Ten helper executables and four actual test executables were retained on their host; **their executable bytes are not in this archive**. Their exact paths, sizes, and hashes identify the retention scope and do not imply that an archive alone reproduces the complete host environment.

The separate 45a desktop packet preserves source and format preparation, its original caller gate, unexecuted timer-oracle preparation, and both rejected collector attempts before the successful bounded archive. Its caller observation was 381.8892215 seconds under the original 600-second bound, scanning 6,480 Rust files against 173 boundaries and 160 protected-file entries. That gate is not another native case or a complete cost record.

## Directly readable production and oracle changes

Reviewers can inspect the exact proposed changes without unpacking an archive:

| File                                                                               |  Bytes | SHA-256                                                            | Scope                                                                                            |
| ---------------------------------------------------------------------------------- | -----: | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| [Producer-owned transcript patch](reviewed_changes/core-output-45a-reviewed.patch) | 25,852 | `b7e4cfb754a4c0bad55dc15ad9ee67a2932dc4a386223845a5686be275e04e6f` | Six-path production change and three regressions, reviewed and frozen from 3fc into 45a.         |
| [Reviewed timer oracle patch](reviewed_changes/remote-timer-6ec-reviewed.patch)    |  1,651 | `4b7a8813bd83b07a26050d9859bbbf5d0f20a914ca1d378804cf5530dae88a42` | Test-only adjustment based on the original 45a remote-clock failure.                             |
| [Actual frozen timer diff](reviewed_changes/remote-timer-6ec-frozen.patch)         |  1,919 | `4a5b2dba27bc88ca5ad16a909dc66a7368f08c23096917e3139618a609fb3866` | Exact canonical Git diff used for the 6ec child; distinct from the reviewed diff representation. |

The production change places the bounded authoritative output transcript in `UnifiedExecProcess`. The producer records accepted output before publishing it to streaming consumers, and terminal summaries read that retained producer state. Local output handling preserves bounded backpressure while independently draining stdout and stderr to EOF. Remote normal and recovery paths record accepted output once according to the existing sequence checks; replayed output is not counted again. Presentation limits do not determine the authoritative transcript's total output accounting.

The patch does not add a grace period, enlarge the original execution budgets, add retries, weaken authorization, or change the original large-output integration test. It addresses a concrete output-ownership design risk. **The exact race responsible for the earlier common CI large-output failure remains unproven**, and the original large-output case aborted in the 45a execution. Therefore this checkpoint does not claim that the original integration failure has been resolved.

The 6ec change is limited to the remote test's clock oracle. It retains the original 20 ms collector deadline and compares completion against an independently observed timer at that same deadline, while retaining the no-output and no-early-completion assertions. It does not change production code. Its retained AI attempts never reached native execution, so the prepared oracle has no native pass in these four packets.

The patch files overlap source material inside the archives. They are review conveniences with their original bytes preserved, not additional implementations or executions. Git diff context-only blank lines contain meaningful leading spaces. Publication permits that whitespace only at these three exact paths with these whole-file hashes; all other staged paths remain subject to the normal whitespace check, and every new path still undergoes index and committed-blob byte verification.

## The two original 6ec AI dependency attempts remain failures

Both original same-source AI preparations stopped while fetching the official V8 checksum with HTTP 504. The second was one explicitly authorized dependency recovery. There was no automatic retry loop and no third AI attempt in this history. The original resolver and checksum requirements remained in force.

| Original AI attempt   | Overall preparation exit | Internal `preparation_returncode` | V8 exit | Helpers / lint / native executed |
| --------------------- | -----------------------: | --------------------------------- | ------: | -------------------------------- |
| Initial preparation   |                        1 | `null`                            |       1 | 0 / 0 / 0                        |
| One explicit recovery |                        1 | `null`                            |       1 | 0 / 0 / 0                        |

The distinction between the two preparation fields is preserved. The sealed derived `SUMMARY.json` uses `facts.strict_attempts[*].preparation_returncode=1` for the original object's **overall** `returncode`. The original internal field with that name is **null**, because the owning preparation never began. This checkpoint retains the sealed summary bytes unchanged, binds the original preparation objects, and records the schema note explicitly. It does not relabel null as zero or as a completed lint attempt.

The first AI archiver itself failed because it assumed that internal field was one. That collector failure, its invocation, and its original bytes remain in the successful v2 historical packet. Successful archival and independent member verification are integrity results, not passing product tests.

The separate 6ec desktop packet retains the source freeze, unexecuted control and admission preparation, and the actual caller gate. The caller completed in 408.2421078 seconds under the original 600-second bound, with 6,480 Rust files, 173 boundaries, 160 protected-file entries, and 15,010 unchanged source entries. The prepared negative source `d27431b69195a2a6331a77d19e22ebeb4cf910c7` was not executed within this retained scope. Source and prior comparison copies are lineage, not additional passes.

## Source, metadata, and publication limits

The [root manifest](manifest.json) retains all previous bf42 validation and historical-cutoff values with their original JSON types. The only new validation entries describe the separate 45a failed history and the two original 6ec AI dependency failures with their independent desktop preparation. Prior 3fc native results remain associated with 3fc; none of them is transferred to 45a or 6ec.

The [008 metadata](increment008-metadata.json), [append inputs](increment-008a-inputs.json), and [publication index closure](increment008-publication-index-closure.json) identify the exact packet and metadata objects. The prior 007 publication and independent readback are retained as their original two RESULT files and two complete command indexes. The command indexes refer to raw-output hashes; this addition does **not** claim to archive their entire external stdout/stderr prefixes merely by including those references.

Publication verifies every permitted new or changed Git index blob and the corresponding committed blob against the prepared bytes and modes. Only the exact verifier log is force-added where necessary. The original corrected metadata history and all old packet objects remain intact; publication uses a normal evidence-branch successor, with no amend, force push, common-source update, or test dispatch.

The complete historical cost, physical cost, and full execution-history completeness remain unknown. Partial wall times are preserved as observations and are not summed into compute, learning, or adoption cost. There is no claim of demonstrated improvement, successful successor consumption, multi-generation adoption, or improved effectiveness of the improver.

The previously exercised Learning-checkpoint transport and real Root-held fixtures remain bounded engineering evidence. They do not supply all ordinary daemon composition ports, complete a production registration flow, or prove candidate adoption and actual successor use. **S0–S5 remain HOLD under the unchanged formal result.**

The preceding README follows verbatim, including its original source identities, counts, failures, corrections, and historical cutoffs.

---

# Increment 007a: separate combined-source engineering records

This checkpoint retains **83 bounded evidence packets and 9,469 file-member entries with overlap**. It adds the two completed records below to the corrected 81-packet checkpoint at evidence commit `02f75555a857b161275ea5c6f7c960dde6cf8b13`. The two new archives contain 333 member entries and 7,770,256 compressed archive bytes. These are archival counts; they are neither unique tasks nor a measurement of complete execution cost.

The common candidate remains `bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d`, tree `f7b65a747a1d2f585be38a4665ab2b4f1b07efb6`. This evidence publication does not advance that source branch. **S0, S1, S2, S3, S4 and S5 remain HOLD.** The original formal `CURRENT_RESULT.json` bytes remain SHA-256 `c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4`. Physical cost and full history cost remain `null`; complete execution history and scientific acceptance remain false.

## The two new packets

| Packet                                        | Original archive SHA-256                                           | Original bytes | Member entries |
| --------------------------------------------- | ------------------------------------------------------------------ | -------------: | -------------: |
| `combined-3fc4725-native-history-v1`          | `ffafc08752e9f6d9c45258389858002b7afaf7239363e7bc6372c54dca162c4e` |      5,439,844 |            309 |
| `combined-callers-3fc4725-desktop-history-v1` | `8eba6d8438f9109fc9c1e0850c233ec1cc588cc27d730675d817b0b75ebd9bbb` |      2,330,412 |             24 |

Both packets bind the separately frozen combined source `3fc4725343dccfc9487e937f77e30bc6a5d80dbc`, tree `89d698ef2fba525a3b03466808337f125306085b`. Its ordered parents are `3f084182eb80bd8fac0a5717a2f5911978759a06` and `e54f7791068ad16ff6082c148cf73798836d36e4`. They are separate source observations and are not relabelled as common-candidate results.

The native packet retains source admission, exact source exports and bundle prerequisites, strict preparation, both owning-package executions, the component selection, the Root parent execution, original commands and logs, fresh JUnit, independent readbacks, the first dependency failure and the one explicit recovery request. The caller packet independently retains the original full caller command, raw output, source inventories and completed receipt. Twelve original JSON members are bound by their exact bytes and complete typed values in the append inputs.

## What actually ran on the separate combined source

| Scope                              | Actual result                                                             | Counting and coverage boundary                                                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Strict preparation                 | Seven steps returned 0 with unchanged source                              | Preparation and lint are not additional task or test passes.                                                                                                     |
| App-server default owning scope    | 1,348 unique cases passed; two original ignored cases did not execute     | Fresh discovery, original raw output and JUnit were independently reconciled.                                                                                    |
| Agentd default owning scope        | 781 unique cases passed; 71 original ignored cases did not execute        | The one SLOW progress report and repeated final output are not extra executions.                                                                                 |
| Checkpoint component selection     | 13 selected executions passed                                             | These cases are a subset of the 781 agentd cases. They add no unique default cases; 785 outside this selection did not execute in this component command.        |
| Registered Root checkpoint fixture | One exact parent case passed                                              | The non-Root child and its separate libtest summary are fixture activity, not a second acceptance case.                                                          |
| Complete caller gate               | Passed in 388.5185359 seconds under the original 600-second command bound | The unchanged closed-set engineering gate covered 6,480 Rust files, 173 boundaries and 160 protected sources. It is not a unit-test count or an authority grant. |

The two disjoint default owning package sets therefore contain **2,129 unique passed cases**, with the Root parent reported separately. Neither the component subset nor the caller gate is added to that total. The native readbacks found no selected retry, LEAK or the checked explicit early-return markers in these completed owning runs. Original ignored cases remain excluded.

The first same-source agentd attempt failed while retrieving the V8 checksum with `ConnectionRefusedError` / errno 111, before any native case executed. That FAIL, the single explicitly authorized dependency-recovery request, and the separate successful second preparation/execution are all retained. The 781-case run was the first native execution for that scope; the failed dependency attempt is not erased or described as a passed run.

The actual Root fixture is `authority_host_service::learning_checkpoint::tests::registered_root_cross_process_restore_conflict_and_committed_lost_ack`. Its native Root PID was 2254272 with UID 0; the Python wrapper PID was 2254270; the ordinary child PID was 2254274 with UID 60001. The outer wrapper observed two libtest summaries, but the accepted scope contains one parent case. This establishes the recorded registered test-only Root/non-Root checkpoint transport behavior. It does not provision a production registration or establish ordinary deployed daemon learning, complete learning owner ports, actual candidate adoption or successor-task consumption. An independent experiment in elapsed lease expiry was not performed.

Thirty-five actual binary files remain on the recorded host with their manifest-bound identities: ten source-bound helper copies, six app-server test binaries and nineteen agentd test binaries. Their bytes are not in these archives. The archive retains their metadata and the independent preservation checks; it does not claim that the current mutable Cargo cache was rehashed or that all operating-system dependencies were captured.

## The common candidate's original failures remain failures

The common source and its existing validation objects are retained with their original types and cutoffs. In particular, the original common snapshot at **2026-11-09 05:38:20.207529 UTC** records 18 terminal runs: 12 success, three skipped and three failure. The original full repository gate remains failed.

For that common source, the full default workspace executed 20,563 selected cases: 20,562 passed on their single attempt and one ended in failure, across 20,564 attempts. The separate scoped 7,910-case result includes one case that passed after a retry; it is not a clean first-attempt pass and it overlaps the workspace scope. The HostCAS parent is a separately reported selected case. The common 38-case Linux follow-up and 130 Python checks retain their own distinct scopes. None of the separate 3fc results changes or augments those old totals.

This increment contains no 45a or 6ec execution packet. Results or environmental observations from those later sources require their own original evidence and review. The unchanged historical sections below retain their stated cutoffs; an older statement that a result was pending or omitted is not silently rewritten as a current result.

## Metadata completeness and committed-object checks

The original increment-006a publication at `a9116a22d4cc429e9b34a1327bcb3945280d72d4` preserved 81 packets but omitted one ignored `VERIFY.log` from Git. Its reported 1,140 local files were not the committed count: its Git subtree held 1,139 files and fourteen of the fifteen declared observations. The independent readback failure is retained. The additive correction at `02f75555a857b161275ea5c6f7c960dde6cf8b13` restored the exact approved log and added the correction history without rewriting the original commit. Its independently verified Git subtree has 1,236 files and the original fifteen observations.

This increment additionally preserves exactly four correction observations: both complete `RESULT.json` files and both complete `commands.json` indexes from the correction publication and its independent readback. The result-to-command SHA links are checked. **The complete stdout/stderr prefixes referenced by those command indexes remain external original records.** Referencing their hashes does not make their bytes part of this increment and does not establish complete historical cost.

The 007 publication metadata lists a closed set of 21 original observations. This includes those four correction JSON files, the actual 007 append result, its pattern review and verifier log, the approved inputs and source scripts, the preparation and reverse review records, and the actual append launch request/result/stdout/stderr. The append was executed once and naturally returned 0 at **2026-11-09 07:40:24.191637 UTC**; its 48.2886701-second wall observation is not full cost. The append result itself is SHA-256 `a865cb5e8b8923f62adeaa7203ac18d8fa6e2c31d0a11d4624b8c36af824131e`.

The publisher stages only the enumerated file set, forces addition only for the exact approved new verifier-log path, and checks every new or changed file's bytes in the actual Git index and then in the resulting commit. All old 81 packet entries, packet bytes, correction objects and other existing files remain unchanged; only the root index and README are intentionally updated. The reported published file count is taken from the committed Git tree. The original bounded packet verifier and pattern scanner remain unchanged; a zero pattern finding is not a complete secret-detection claim.

The publisher's own terminal receipt and command logs are external to its own commit. A publication success requires the normal push and exact Git/API commit, tree and parent readbacks; preparation metadata alone is not a publication result. Publication and archival verification execute no new native tests and confer no scientific stage advancement.

## Retained prior checkpoint documentation

The previous README follows byte for byte. Its counts and status statements describe the historical checkpoints named in that text.

---

# Source-bound execution history

This is a bounded, lossless checkpoint of engineering evidence. It preserves
original archives, failed attempts, source preparation and publication records.
**S0, S1, S2, S3, S4 and S5 remain HOLD.** Complete execution history, full
physical cost and full historical cost remain unknown.

## Increment 006a: terminal common CI and separate-source histories

This increment adds nine terminal evidence packets to published predecessor
[`97543a30b941122ee42c99ab95c2dbf639ac6576`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/97543a30b941122ee42c99ab95c2dbf639ac6576/qualification/cell_common_candidate/20261108/execution_history).
All 72 predecessor packet index entries and their original bytes remain
unchanged. The current total is **81 packets and 9,136 archive-member entries
with overlap**, compared with 72 packets and 7,050 entries at the preceding
checkpoint. The nine new archives contain 2,086 member entries and total
78,247,976 compressed bytes. Members, duplicate artifacts, repeated status
observations and retained copies are not independent tests.

The common candidate is still
`bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d`, tree
`f7b65a747a1d2f585be38a4665ab2b4f1b07efb6`. **Its full repository CI is not
green.** This increment preserves the original failures and does not apply
a source fix, rerun a test or advance the common branch. Newer combined-source
executions are outside this increment.

### Final original bf42 workflow observation

The included snapshot 008 was observed through **2026-11-09
05:38:20.207529 UTC**. All 18 original bf42 workflow runs were then terminal:
12 reported success, three were skipped and three reported failure.
The failures were the native framework run 42553066862, blocking CI
42553073160 and original Windows regressions 42553073234. These are API
workflow conclusions, not a count of tests or proof that a skipped scope ran.
Snapshot 007 and every preceding cutoff retain their original, earlier values.

The source-head native executions below are bound to bf42/f7b and their
original receipts. This does not replace the blocking CI checkout identity:
its actual Bazel merge commit
`8828133f2566b7e537cac0bad58c84eb5b0168bb` has the same f7b tree but is a
distinct commit. Original UI source-head and two CI-local base-merge identities,
and the original Windows 158 clean passes / eight failures / one body-pass with
LEAK, remain exactly as recorded in increment 005.

### Original native framework result: failure, with retries retained

The original four artifact ZIPs, job logs, available JUnit, helper receipts and
source snapshots are retained. The actual native composition job ended in
failure at 05:25:39 UTC. API success for an earlier step is not substituted for
its original case records.

| Original native scope                | Distinct executed cases | Original result                                             | Original attempt and selection boundary                                                                       |
| ------------------------------------ | ----------------------: | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Mechanism packages                   |                   1,215 | 1,215 single-attempt passes                                 | Seven reported cases outside execution scope; no selected retry observed.                                     |
| Scoped composition                   |                   7,910 | 7,909 single-attempt passes and one retry-pass marked flaky | 7,911 attempts; 107 reported cases outside execution scope. This is not 7,910 clean single-attempt passes.    |
| Explicit ignored Root HostCAS parent |                       1 | One selected parent passed                                  | 791 other cases were outside the exact filter. Child fixture output is not a second acceptance case.          |
| Complete default workspace           |                  20,563 | **20,562 single-attempt passes and one final failure**      | 20,564 attempts; 139 reported cases outside execution scope. The failing case also failed its original retry. |

These scopes overlap. Their rows must not be summed into distinct test
coverage, and the separate earlier Linux 38-case execution and Python
130-fixture execution remain their own scopes.

The unique workspace failure is
`codex-core::all / suite::unified_exec::unified_exec_formats_large_output_summary`.
The scoped first attempt reported a missing HEAD marker and its original retry
passed. Both workspace attempts failed the original output-summary regex.
The generated fixture is HEAD, 100,000 repetitions of `token token \n`, and
TAIL, totalling 1,300,010 bytes. The failing aggregated output was not printed
in the retained assertion context, so the source-level cause is not established
by that context. The original regex, retry policy and time budgets were not
weakened for this evidence.

The readback reconciles original JUnit and terminal raw case/attempt records.
Progress-only SLOW messages and final-output repeats are not extra attempts.
The first readback's incorrect treatment of a SLOW event failed closed and is
retained; the corrected readback did not execute tests. No selected timeout or
nextest LEAK marker was observed in these original native reports. There was
no independent nextest listing artifact for this original run, and absence of
visible skip markers does not prove the absence of every silent early return.
Native test executable bytes were not uploaded in these original CI artifacts.

### Separate sources and observer failures

| Retained execution                                                                                                            | Actual result                                                                                                    | Attribution limit                                                                                                                                                                                                         |
| ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux app-server source `3f084182eb80bd8fac0a5717a2f5911978759a06`, tree `3baf936ae98d761bcba25a4e38c2501407417737`           | 1,348 distinct selected cases passed; two original ignored cases were not executed.                              | Exact listing, raw summaries, JUnit, source snapshots and independent readback are retained. This is owning-package Linux evidence, not bf42 execution or full workspace acceptance.                                      |
| Original-Broadcast counterfactual `bfcbdb20d378bdeab24078177128daec171c6063`, tree `6f4eb6cbf5dcb97353359d184877aa3bb0f0e995` | Two actual failed cases.                                                                                         | The expected negative-control result is not product PASS; its cases are not added to the positive source's count.                                                                                                         |
| Earlier Windows Cargo observers on a57 and 5eee                                                                               | A missing-Clippy preparation failure and an actual fixture compilation failure, respectively; zero native cases. | Their original sources, attempts and the subsequent 3f084 observer publication are retained without relabelling.                                                                                                          |
| Windows Cargo run 42566595607, observer `f0550f79e6c8e729e60943e8e37dded924729998`, tested source 3f084                       | Both attempts failed during V8 dependency retrieval with HTTP 504; all five selected cases remained unrun.       | One explicitly authorized failed-jobs recovery was issued. The second failure did not cause an automatic third attempt.                                                                                                   |
| Windows Bazel run 42566694888, observer `b61e1a89ce6faea79d0518b990b78470e97e2244`, tested source 3f084                       | Attempt 1 failed fetching bazel_features v1.50.0; attempt 2 failed fetching rules_cc 0.2.20, both with HTTP 504. | Both discovery commands produced zero testResult/testSummary events and zero native cases. The original public app-server target, 16-shard plan, budgets and assertions were not executed or qualified by these attempts. |
| e54 next-bootstrap source review                                                                                              | Read-only boundary analysis; no new native execution.                                                            | Existing separately tested checkpoint transport does not establish ordinary-daemon installation, a complete production learning-ports provider, real learning or later-task consumption.                                  |

The app-server history includes the 5eee compile failure and the first 3f084
selection reader's rejection of original ignored cases. The corrected reader
keeps those two cases ignored and unexecuted. Twenty-seven original helper/test
binaries remain on the native host with exact metadata; their executable bytes
are not in the publication archives.

The Bazel history also retains the first collector's wrong root-manifest
assumption and its failed post-read, followed by verification of the actual ZIP
prefix and all original members. Artifact collection failures and same-key
acknowledgement reconciliation are not native test failures or new test
executions. Repeated collection copies and first-attempt histories that appear
in multiple archives are retained overlap.

### Publication and checkpoint boundaries

The preceding evidence commit 97543 was published and verified at
06:06:05.872737 UTC. Its original outer publisher reached a 600-second observer
timeout while Git was uploading; the original Git push exit remained unknown.
The first explicit recovery then failed with HTTP 408. A second explicit,
request-local HTTP/1.1 and 256 MiB post-buffer upload succeeded with exact Git
and API commit/tree/parent readback. These are three retained upload attempts
of one identical commit. Success of the last transport does not establish the
cause of the earlier timeout or HTTP 408. No test budget or production policy
changed. Original commands, stdout/stderr, reconciliation and failure receipts
remain in their own packet.

The 006a append binds the fixed input document, 21 exact JSON member values,
all nine original archive hashes, and the unchanged 72-packet predecessor.
Its bounded pattern scan examined 2,487 member entries including nested
archives, with no findings; this is not comprehensive secret detection.
The retained packet verifier checks byte reconstruction and member consistency,
not scientific claims. Appending and verifying this checkpoint does not itself
mean it has been committed or remotely published; a successful publication
requires its own external, exact remote-readback receipt.

### Nine appended terminal packets

| Packet                                                | Original archive SHA256                                            | File members |
| ----------------------------------------------------- | ------------------------------------------------------------------ | -----------: |
| Original bf42 native terminal failure                 | `93bd9903de1191055d6a1811d4b2ba7fed401e1fd4261c653df5fdcdbd1fd19a` |          234 |
| Bazel preparation, first failure and recovery request | `66cf86773b716105694c61d307ab34f4c766e32bb6d5bfb606401419bf9d50a3` |          332 |
| Bazel second dependency failure                       | `05be50a6a4beb82b236e63d284b83bc9c97fab145243d8bc247b0980eef1dfc5` |           79 |
| Three uploads of evidence commit 97543                | `66e9e35f03bf605ab75b0c99e32e3d13269c718153ff1cb3eda59c7d503069d3` |          243 |
| a57/5eee Cargo failures and 3f084 publication         | `b9c36855ed79e25f2e3b572efed0720390a274eae38445d71daddc7c49165d40` |          454 |
| Two 3f084 Cargo dependency failures                   | `47d9e17ea3011467b45959b90568b0330e790afef6d41e4ea6ccce8388c25567` |          141 |
| 3f084 Linux owning and bfcbdb2 counterfactual         | `dd1a594cc460905bfc47cb0d3050e6dbb9335526954905f39558738d7dc99f3d` |          418 |
| e54 next-bootstrap read-only review                   | `d61f5f8509c1089d0d871d599a068b968e15c2b51d74be284a35e92add5d1e8a` |           40 |
| Original API snapshots 007 and 008                    | `ded93291d9b023704d8be4c75f5600028bfe0b9dc22c74994d67e9c76d7e49a5` |          145 |

All full physical and historical costs remain null. Retained elapsed times are
observed wall intervals and are not added into a complete cost total. Failed
builds, dependency downloads, retries, collection and publication attempts are
part of history even when no test case ran. **S0, S1, S2, S3, S4 and S5 remain
HOLD.** The formal CURRENT bytes remain unchanged. The following earlier
increment narratives retain their original counts, cutoffs and source
identities; their former pending statuses are historical observations.

## Increment 005: original UI, Windows failure, and checkpoint delivery

This checkpoint adds six packets to the 66-packet predecessor
[`5a3137e8ed198a07eb63bd97b5bb639f4471011f`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5a3137e8ed198a07eb63bd97b5bb639f4471011f/qualification/cell_common_candidate/20261108/execution_history).
All 66 original packet index entries and their bytes remain unchanged. The new
total is 72 packets. Archive members and repeated artifacts are not test counts.

The common candidate remains
`bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d`, tree
`f7b65a747a1d2f585be38a4665ab2b4f1b07efb6`. The checkpoint-delivery implementation
was validated separately at
`e54f7791068ad16ff6082c148cf73798836d36e4`, tree
`dfd0f9f53d791542cafbfc74c53ab2c981d86f66`, on its published quiet branch.
Its results are not attributed to common bf42.

### Original common-source workflows

The last included API snapshot ended at **2026-11-09 04:41:07 UTC**. Of the 18
original bf42 workflow runs, native composition and Windows x64 V8 still had
running jobs. Windows ARM V8 had reached its API terminal state. These API
observations do not establish individual test results. The common branch was
not advanced while the original jobs remained active.

| Original execution                  | Verified result                                                                           | Scope and identity                                                                                                                                                                                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Blocking CI, run 42553073160        | Failure, retained in increment 004                                                        | The actual Bazel checkout was merge `8828133f2566b7e537cac0bad58c84eb5b0168bb`, with the same f7b tree and a distinct commit identity. No full repository pass is claimed.                                                                        |
| Windows regression, run 42553073234 | 167 distinct selected executions: **158 clean passes, 8 failures, 1 body-pass with LEAK** | All 19 original groups are retained; 17 groups passed cleanly. The job ended with failure naturally at 03:51:04 UTC. No original JUnit was available. Counts are bound to the original scope, raw nextest status and summary lines, and receipts. |
| UI, run 42553073250                 | The original reported UI scopes passed and their original evidence was read back          | Source-head, foundation base-merge, and native-presentation base-merge identities remain separate. Passing these scopes does not establish real-task learning or physical-device behavior.                                                        |

The Windows deletion-route tests completed their ordinary-host controls before
the preserved legacy `FILE_DELETE_CHILD` refusal. The non-TTY body-pass with
LEAK is not a clean capability pass. No failed test, old attempt, ignored case,
or unexecuted case is converted into a passing observation.

The Windows collector's first acknowledgement timed out, but the original
collector had completed. Reconciliation with the exact same idempotency key
returned the original successful job with no second launch. This transport
acknowledgement failure is not a CI failure or a rerun.

### UI source and counting boundaries

| Lane                           | Actually tested commit                     | Original library executions                   |
| ------------------------------ | ------------------------------------------ | --------------------------------------------- |
| Source head                    | `bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d` | SDK 7, headless 29, native 52                 |
| Foundation base-merge          | `7450f0cbe49443a2b78826a2786ac37889c60e76` | SDK 7; original browser and gateway scenarios |
| Native-presentation base-merge | `52ebeefecb4ab2d2fbb3e69100ab3773df0b8ea5` | Headless 29, native 52                        |

All three tested commits have the f7b source tree. The two CI-local merge
identities are supported by original merge-creation commands and clean
before/after execution receipts; they were not independently retrieved through
a commit API. An API run head or an artifact name alone is not the tested commit.

Across the retained feature executions, the seven SDK names and 29 headless
names are subsets of the 52-name native set. The table identifies which commit
actually ran each scope. Feature/profile and commit executions remain distinct;
**7 + 29 + 52 is not 88 unique tests**. The original twelve-case JUnit checker
runs are separately identified as checker executions.

For each original browser lane, the canonical scenario executions were default
6, fixtures including sidebar 9, buffer-control 1, and gateway 7. Gateway
contains six actual missing-owner-status cases and one original SDK synthetic
sink control. The 60 default and 78 fixture captures, and their 138 and 438
semantic-check observations, are not additional tests. Repeated reports and
attachments are not extra coverage. All reported capture PNG hashes match the
archived original image bytes; this readback did not rerun a browser or pixel
checker, perform human visual review, or qualify physical IME/GPU devices.

All 29 original UI artifact ZIPs are verified. The first downloader's original
600-second outer limit left one incomplete artifact and 28 complete artifacts.
The recovery downloaded only that one missing artifact and reverified all
original ZIP members. Both the original partial and failure records remain.
This was artifact recovery, not a test budget increase. The first evidence
reader's merge-identity and group-manifest assumptions also failed closed;
the corrected reader retained the original execution results and identities.

### Separate checkpoint-delivery implementation

The quiet source
[`e54f7791068ad16ff6082c148cf73798836d36e4`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e54f7791068ad16ff6082c148cf73798836d36e4)
provides a bounded restore/checkpoint channel over the existing registered
Root authority. It uses the original authenticated consumer identity, writer
fences, sequence and protected HostCAS state. It does not fabricate stage
execution, proposal preparation, adoption receipts or downstream consumption.

| Validation at exact e54   | Actual result                                                                                      | Limit                                                                                             |
| ------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Same-source preparation   | All five preparation steps passed, including owning `just fix` and separate readonly strict Clippy | Preparation is not a test count; source entries remained unchanged.                               |
| Codec and wire components | 13 exact fresh cases passed: nine codec/CAS regressions and four wire regressions                  | Zero selected skips, retries, observed LEAK or explicit guard-skip markers.                       |
| Registered Root boundary  | One parent case passed with a real UID 60001 child and protected Root storage                      | The child's libtest summary is part of that parent fixture, not another acceptance case.          |
| Full caller scan          | Passed in 400.58282532705925 seconds within the original 600-second budget                         | 6,480 Rust files, 173 declared boundaries and 160 protected boundaries; this grants no authority. |
| Quiet publication         | Normal push and exact Git/API source, tree and parent readback succeeded                           | Common bf42 and the formal CURRENT record remained unchanged.                                     |

The real Root fixture exercised restoration, stale conflict, durable commit
followed by a lost acknowledgement, reconciliation through a freshly delivered
channel, and refusal after actual registered revocation. It retained the
original executable's SHA256 before and after execution, and the temporary
Root mount was cleaned up. Elapsed lease expiry was not independently tested.

The original 0eed compile failure and 9d Root failure remain separate historical
records. The latter failed when the child executable was placed on a
`noexec` filesystem. The corrected fixture used a fresh Root-owned executable
directory without changing mount policy, private-state permissions, writer
checks, or the original assertions. A separate post-reader permission failure
also remains recorded. Both large original test binaries are retained on the
native host with exact hash records; their executable bytes are not part of
these publication archives.

**Ordinary daemon learning is still incomplete.** The production entry still
needs independently produced learning-stage results, proposal preparation,
matching trust and attestation inputs, and a real published successor consumed
by a later task. The checkpoint client only implements restore/checkpoint;
it is not a complete learning-port implementation. This packet contains no
ordinary-daemon installation, production owner registration, real learning
dataset/model execution, or proof of successor-task consumption.

### Six appended original packets

| Packet                                    | Original archive SHA256                                            | File members |
| ----------------------------------------- | ------------------------------------------------------------------ | -----------: |
| UI shared history and native scopes       | `1e4dc0c00bf3f7c59c83fdfd2ad2f6f4ad5a1f723012bcfc9ad812b2fad8f8ce` |          288 |
| UI source-head browser scopes             | `8fa3391d5c10c95516e63e015e185a893edbc7de8d9904a50853273ae28d9ab2` |           75 |
| UI base-merge browser scopes              | `a207b056f809952903506e70678c4a0ea1aff4bac667e0c7f10b41ebd8e46e8a` |           75 |
| Original bf42 Windows failure             | `fb52c5cd35c1b8208052757d66d26de27cfe3636bb4eec069fdc204a6db844cc` |           45 |
| e54 native and failure history            | `7c51d224ad2638ab810ba97f1aba9dadf8e7a06a36e6f9821d1a65e019dd1d87` |          254 |
| e54 source, callers and quiet publication | `b94387249400ba0f841a3862ceb93d6bbbdf6251e2090dfb230a12f4665f14ce` |          219 |

Wall intervals include preparation, failures, collection and recovery where
observed. They can overlap and are not a complete CPU, physical, learning or
historical cost total. Unknown costs remain null. **S0, S1, S2, S3, S4 and S5
remain HOLD.** The earlier increment narratives below retain their original
cutoffs and source identities.

## Increment 004: common source bf42 and original observations

The common draft candidate is now
`bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d`, tree
`f7b65a747a1d2f585be38a4665ab2b4f1b07efb6`. Its predecessor common candidate was
`ba4e1e42b6a8cbab724e1755bddfb9b5b8f298a1`. The common branch advanced normally
at 2026-11-09 02:50:20 UTC, after two fresh observations confirmed that all
18 preceding ba4 workflows were terminal. The exact Git remote ref, commit,
tree, parent and draft PR head were read back. No running Rust process was
manually cancelled and no merge commit was manufactured for the fast-forward.

The [draft PR](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5397)
was updated and independently read back at 02:54:10 UTC. That PR body records
the tested source, original failures and remaining qualification gaps.
Publication is not an adoption result or an authority grant.

The preceding checkpoint is
[`4628cc139cc8067b1fa42713aa80c32c819e4e48`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4628cc139cc8067b1fa42713aa80c32c819e4e48/qualification/cell_common_candidate/20261108/execution_history),
with 53 packets. All of its original packet bytes remain unchanged. Previous
prose and index status remain recoverable at that exact commit. Historical d1
successor status and ba4 native status are explicitly identified as historical
in the new index; neither is attributed to current bf42.

### Actual validation of bf42

| Scope                                             | Original observed result                                                                                                                                                                            | Limit                                                                                                                                                                                                                               |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Same-source preparation and agentd H7 strict lint | All five original steps passed: V8 preparation, helper build, helper verification, owning-package `just fix` with `qualification-cognitive-write`, and separate readonly Clippy with `-D warnings`. | All 15,004 source entries remained clean and identical. Unchanged packages' earlier lint results retain their earlier source identities.                                                                                            |
| Python and caller gates                           | 130 independent fixtures passed; 11 original receipts all passed, including self-test and unchanged CURRENT. The full caller scan took 380.6801889021881 seconds.                                   | Original caller ceiling remains 600 seconds. The 50 nested research fixtures are counted once, not again through their parent wrapper.                                                                                              |
| Selected Linux native                             | 38 actual selected cases passed: agentd default 4, H7 qualification 1, CLI 1, Matrix startup 1, app-server 6 and the entire actually discovered operator library, 25.                               | Six fresh JUnit sets exactly match their original discovery sets. Source and binary hashes stayed unchanged. Zero selected skips or retries. This is not full workspace, Windows or scientific qualification.                       |
| Independent readback of original nextest logs     | All six original merged stdout/stderr reports contain their exact initial PASS sets and no LEAK or leaky markers.                                                                                   | No tests were rerun. The original driver lacked an explicit LEAK gate; this separate derived readback preserves that limitation. It does not prove the absence of unobserved resource leaks.                                        |
| Independent grouped Windows execution             | All eleven selected cases actually executed: ten passed and image-edit timed out at 60.015 seconds. The original aggregate and complete run both concluded failure.                                 | Exact bf42 source with observer 5574; five separately budgeted owner jobs. Zero selected skips, retries, explicit guard skips or observed LEAK markers. This does not replace the original single-job result or full repository CI. |
| Original complete workflows                       | bf42 native, blocking CI, UI and original Windows workflows were launched on the common branch.                                                                                                     | Their initial registration is not a passing result. ba4 and intermediate-source outcomes do not fill pending bf42 coverage.                                                                                                         |

The Linux groups' original unselected counts are respectively
788 / 794 / 0 / 25 / 1,015 / 0. Filtered cases are not executed passes.
Final-output repeats of PASS lines are not extra executions. Overlapping
scopes and uploaded duplicate copies are not added into distinct coverage.

The first bf42 preparation launch failed before any Cargo, V8, helper or test
subprocess because the previously used Cargo target directory was absent. The
cause of that disappearance is unknown. Its traceback, filesystem observations
and recovery remain in the original native packet. The successful preparation
used a new, initially empty target; registry-cache state was not measured.
Preparation took 343.479 seconds, and the selected native chain took 533.084
seconds. These are observed wall intervals for this attempt, not complete CPU,
machine, learning or historical cost.

The Python packet also retains the first sealer invocation failure: a basename
guard rejected an absolute path before any new archive or test execution.
The corrected invocation sealed the same original execution; it did not rerun
the tests or change the result.

### New packets in this increment

The manifest is authoritative for the exact packet set and hashes. Member
counts overlap between archives and do not represent test counts.

| Packet                                            | Original archive SHA256                                            | Members and scope                                                                                                                                                                                |
| ------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| bf42 Python execution                             | `793167e250598093524aa4f1de2de0a4b25f1fc691610db80675b731c21da200` | 49 members; original 130 independent fixtures, 11 receipts, full caller scan and sealer invocation failure.                                                                                      |
| bf42 preparation and selected native execution    | `4deb1c2bdaf59eba048f8ab05de06a383909f60dc21e70c37886421f00f0a2d0` | 179 members; pre-Cargo failure, fresh-target admission, five preparation steps, 38 actual cases and independent original-log LEAK readback.                                                      |
| Independent UI diagnostic history                 | `e8c880a965de795c7d11b8b82a0a089cf7e6eea8daeb79a06dd0148540e26923` | 417 members; original preparation failure, four-path diagnostic source, publication, job log, original artifact and bounded wait observations.                                                   |
| Original d1 Windows eleven-case partial execution | `6b6c52207b134864fc02f8df16d46858036a15dfc6ee5c41d2869a1318acfe79` | 38 members; four executed cases, original 65-minute cancellation, raw job records and all present original ZIP members. Seven hidden source copies remain missing from the old artifact.         |
| bf42 ordinary-learning checkpoint delivery audit  | `9ed951422bb44dcb9ac40c9bc77983ee09c091aa60107623a02819ee7f33b72b` | 45 members; exact-source targeted review, unchanged CURRENT and the concrete next implementation boundary. No source mutation, provisioning or new test execution.                               |
| bf42 source and publication history               | `5a9962dc4db95f4db0b6bbf955e034235bfcc0a8c165e9dfe4397869781f7268` | 273 members; source freeze, quiet publication, previous evidence publication, PR updates, common fast-forward, exact remote readbacks and initial new CI registration.                           |
| Windows Matrix owner originals                    | `4482994b3243513f0e324545cc12f6e5f22d172fab96f021740152f08bde6012` | 19 members; one selected case passed, with the original artifact ZIP and source/helper/case binding.                                                                                             |
| Windows H7 owner originals                        | `db3a43d4f70ad6dc8547916c97ecbaac10d564b52eec7d968b4c53ae5f8d672d` | 24 members; one selected H7 case passed.                                                                                                                                                         |
| Windows default agentd owner originals            | `f1656cc57fbc672774e694ed4bb7885e2fdacf5b9fd7fed898964dc6eff1287d` | 19 members; signed-credit and fleet-drain both passed.                                                                                                                                           |
| Windows CLI owner originals                       | `db11066b80b9b6610e699ac3ad26fafcf1a4d3f5e42dcfdbc4b16194d851cce7` | 19 members; one CLI cloud-permission case passed, with same-source child-helper paths retained.                                                                                                  |
| Windows app-server owner originals                | `d4cdc6f963ce15d83ed4e92899c6b662b7d6a63bd85d75dfeffbf9162118dbff` | 26 members; four cold-resume cases and approval passed; image-edit timed out.                                                                                                                    |
| Windows observer and original aggregate history   | `46ce0378c8bc75fa4e083e53d34b09ac27f6899f6e21e4f7034473b249c73a7f` | 213 members; first Ruff ENOENT, preparation attempts, exact observer publication, original aggregate artifact and terminal run. Eleven executed, ten passed, one failed, overall failure.        |
| Original bf42 common full-CI failure              | `4beffe0dace6d56e657cc9a7f58346fb032bcf8251ca3831717cdc39802127c5` | 235 members; snapshots 002/003, six completed failed-job raw logs and API records, actual merge identity, final target and original attempt accounting. No rerun, cancellation or test dispatch. |

### Original d1 Windows failure remains a failure

Run [42545587597](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42545587597)
used observer `bd7962c944e47fcadb0f205d808300f780491800` and exact tested source
`d1b32a67cbe9ada0b7d911bdc7d08820253bb1ca`, tree
`f95a33684df6aac0a32326e20b63d4017d7b1968`. It ended naturally at its original
single-job 65-minute limit at 02:31:47 UTC. The original annotation identifies
that limit; no manual cancellation is substituted for its cause.

Four actual cases executed: fleet passed in 0.619 seconds, H7 passed in 2.506
seconds, CLI failed in 0.212 seconds with zero expected Wiremock requests, and
signed-credit failed in 0.066 seconds with fixture `Invalid`. There were no
selected skips, retries or observed LEAK markers. Matrix discovery/build had
started but its case did not execute. The six app-server cases were not
launched. These seven unexecuted cases are not assigned zero cost.

Both tested source and observer were clean and unchanged before/after. All 88
present ZIP members were independently verified. The original internal
manifest's 87 present payloads matched, while seven source-file copies under
hidden `.github` or `.config` directories were omitted by the old upload
default. Those missing copies are not claimed as archived original evidence.
The later observer enables hidden-file inclusion; it does not repair old bytes.

Additional run
[42550332155](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42550332155)
uses observer `5574d6b900571123239f0a8c0742a69d24cf7d99` and exact bf42 source.
Its five owner jobs retain their original internal budgets and each has a
65-minute ceiling. CLI helper paths come from exact, hash-verified same-source
compiler metadata. The aggregate requires all five same-run, same-source
receipts and the exact original eleven-case set. Raw LEAK markers independently
reject a clean pass. This additional topology and its costs do not supersede
the failed original single-job execution. All five original groups have now
been independently reconciled against their discovery sets, fresh JUnit,
raw logs, original manifests and five dual-source snapshots per job. The
tested source and observer remained unchanged; original helper bytes were
also verified. The new artifacts include all manifest-listed hidden source
copies. No missing old artifact was reconstructed and relabelled as original.

| Original group                    | Selected result                      | Original JUnit time                   |
| --------------------------------- | ------------------------------------ | ------------------------------------- |
| Matrix startup diagnostic         | 1 PASS                               | 5.831 seconds                         |
| H7 expired-registry qualification | 1 PASS                               | 2.480 seconds                         |
| Default agentd                    | signed-credit PASS; fleet-drain PASS | 2.339 and 0.820 seconds               |
| CLI cloud permission              | 1 PASS                               | 31.998 seconds                        |
| App-server cold resume            | Four cases PASS                      | 1.535 / 1.488 / 1.856 / 1.456 seconds |
| App-server session approval       | 1 PASS                               | 4.636 seconds                         |
| App-server attached-image edit    | TIMEOUT                              | 60.015 seconds                        |

The original aggregate job `128956308785` naturally finished at 03:03:49 UTC
with `passed=false`, eleven validated executions, ten XML passes and one
failure. The entire run concluded failure. The four passing groups do not
make the app-server group pass. A successful Matrix selected case does not
establish the cause or resolution of an earlier whole-target initialization
failure and does not qualify power-loss durability.

For the failed image-edit case, the original stderr reports
`CreateProcessWithLogonW failed: 267`; the actual turn later completed without
an ImageGeneration item, leaving the original fixture waiting until its
watchdog. The [original runner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d/codex-rs/windows-sandbox-rs/src/elevated/runner_client.rs)
reads the Win32 last-error value after another Win32 call; Microsoft's
[GetLastError contract](https://learn.microsoft.com/en-us/windows/win32/api/errhandlingapi/nf-errhandlingapi-getlasterror)
requires capturing useful error information immediately. The logged 267
therefore remains a reported value rather than a
newly verified launch cause. A separately prepared immediate-error-capture
and exact-turn terminal diagnostic patch is not part of bf42 and does not
establish an ACL, directory-lifetime or launch correction. Credentials and
environment contents are not needed for that diagnostic boundary.

### Current common CI observations

The source-bound API observation at 03:30:34 UTC records original run
[42553073160](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42553073160)
as completed with failure. Windows Bazel shards 2 and 4, both macOS Bazel
jobs, the Windows aggregation and the required-CI aggregation failed. Each
aggregation remains an outcome gate rather than an additional native testcase.
The earlier snapshot at 03:16:38 UTC and its original four-job log collection
at 03:21:07 UTC remain preserved; later observations do not rewrite their cutoff.

At the latest observation the UI foundation workflow
[42553073250](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42553073250)
and architecture workflow had completed successfully. That is an API job/run
status observation; full original UI case qualification is a separate readback.
Common native composition, the original Windows regression and both Windows
V8 canaries were still running. Individual successful jobs do not fill those
remaining scopes. The API head is bf42; actual checkout merge identity and
final Bazel target results retain their own original bindings. Names appearing
in failed attempts are not silently treated as the final unique failed-target
count. No complete common CI pass or stage advancement is claimed.

All four failing native jobs actually checked out
`8828133f2566b7e537cac0bad58c84eb5b0168bb`. Its tree is the exact bf42 tree;
its ordered parents are `1eb72a1131285f5de98beeb7c95a27eab72d647e` and bf42.
The actual commit remains distinct. Raw checkout records plus the original
Git commit API establish that identity, rather than a complete post-build
working-tree byte snapshot. The required-CI aggregator also checked out this
merge but ran no native cases; the Windows aggregator had no test checkout.

| Original job    | Final nonpassing Bazel targets                                                                                                                                                   | Accounting limit                                                                                                                                                          |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows shard 2 | 3 FAILED: CLI unit, Windows sandbox unit, app-server all                                                                                                                         | The app-server target's original six failed invocations among twenty include repeated attempts in two of sixteen shards. They are not six distinct Rust cases.            |
| Windows shard 4 | 2 FAILED: exec-server Windows filesystem, core all                                                                                                                               | The core target's original sixteen failed invocations among twenty-seven include repeated attempts. A recovered earlier shard attempt does not make the full target pass. |
| macOS ARM       | 3 FAILED: forwarder, Matrix unit, Matrix store-version migration target                                                                                                          | The migration target's ordinary restart case is distinct from its ignored two-version qualification.                                                                      |
| macOS Intel     | 5 FAILED: code-mode host gRPC, code-mode host WebSocket, forwarder, Matrix unit and Matrix store-version migration; 2 TIMEOUT: agentd unit and supervisor paired-process product | Both timeouts retain the original 300-second target budget. Running-over-sixty-seconds markers do not establish a deadlock or completed case result.                      |

These are target outcomes per platform/job, not a distinct-test total. The
original logs identify multiple different boundaries. Matrix unit startup
expires in `build_until` under the original twenty-second budget before the
session-persistence assertion. The migration and forwarder messages remain
too generic to locate the underlying operation. Windows app-server helper
launches fail earlier with program-not-found, unlike the grouped Cargo run's
reported logon error. The CLI doctor timeout, unexpected app-list notification,
legacy isolation refusals and other core event waits remain separate findings.
The packet retains exact proved observations, unknowns and narrow next actions;
none is converted to a qualified root cause merely because another scope passed.

### Independent UI diagnostics

Run [42549225359](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42549225359)
uses diagnostic source `5e33ff84c6e556a63de77610ea968d480221747c`, tree
`e73045f95d99644c6f7b2b1ff2b111f6b4969782`, based on d1. It changes exactly four
paths for bounded breadcrumbs around original waits and its independent
observer. Source identity stayed clean across all three original snapshots.

All seven actual cases passed with one attempt, zero skips and zero retries.
They comprise six real-gateway status scenarios and one SDK transport control
with the original synthetic export sink. This is one original browser group,
not the whole UI workflow or all native/pixel/browser scopes. The previously
failing 1280 timeout case completed in 19.760 seconds. The complete original
command took 106.99170309 seconds. All 180 original artifact members were
verified.

All six breadcrumb records have the expected paired boundaries. Intentional
missing no-state OCR completion markers in navigation cases remain explicit.
The four timeout/navigation continuations encountered the original expected
late `Invalid InterceptionId` error and completed the existing catch/cleanup
path. Cleanup began with zero pending holds in every case, so this execution
does not exercise stalled pending cleanup. The original local unbounded awaits
remain a source-level risk.

The old failure was not reproduced, and its root cause remains unknown.
Synchronous breadcrumb I/O can change scheduling. This diagnostic execution
does not qualify the uninstrumented d1 or bf42 source, establish a production
fix or prove a performance improvement.

## Retained historical results

| Exact source                                   | Retained observation                                                                                                                                                                                                                                                                              | Current interpretation                                                                                                                                                                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ba4 `ba4e1e42b6a8cbab724e1755bddfb9b5b8f298a1` | Original native run [42534597157](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42534597157) passed 20,563 unique default-workspace cases with 139 original raw skips and 330 JUnit suites. Four original artifact ZIPs, source bindings and every member were checked. | The 7,910 scoped and 1,215 mechanisms cases are subsets. The original ignored HostCAS case is separate. This is ba4 coverage and not every feature combination.                                                                             |
| ba4 repository and UI CI                       | Full repository CI and both UI lanes failed. Windows shards 2/3/4 and both macOS jobs failed; original Windows regression reached its 65-minute limit.                                                                                                                                            | Successful evidence checkers, proposal metadata and separate security jobs do not replace these failures. Distinct actual merge commits retain their identities even when their trees match ba4.                                            |
| ba4 Windows original sandbox groups            | Six failed cases and one passed-but-leaky case in the first group; two failed cases in the delete group.                                                                                                                                                                                          | The earlier prose label `7+2 FAIL` was inaccurate. The original observer already rejected LEAK. Original bytes and the explicit correction remain together.                                                                                 |
| `82ff5119200cab9d65461eb62a3829567fbc2e8f`     | Linux selected 13: nine passed, four cold-resume cases failed. Windows original eleven-case run: four executed, two passed, two failed, seven unexecuted.                                                                                                                                         | The typed spawn-observer mismatch is preserved. Neither failure is replaced by a later source's pass.                                                                                                                                       |
| `a8d0b3dab62045a6aa6e61966c3fbeeccf1b48d6`     | Original operator E0433 strict-preparation failure.                                                                                                                                                                                                                                               | Zero native cases executed. Its Python pass is a separate scope.                                                                                                                                                                            |
| `a39bf3eeac945c83aebcadbb81dfcb93d623e0f4`     | Preparation rejected automatic source drift after canonical `just fix`.                                                                                                                                                                                                                           | Zero native cases executed. The automatic diff was retained but not adopted.                                                                                                                                                                |
| `d1b32a67cbe9ada0b7d911bdc7d08820253bb1ca`     | Linux 38 selected cases passed. Original Windows Bazel operator target separately passed 33 unique libtest cases in [42546897394](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42546897394), observer `cea37b82c63bb2a6120789d44b2e9fea1d3a10d3`.                      | The XML has one aggregate wrapper testcase; the 33 cases come from actual libtest records. This single target and its keyless BuildBuddy environment do not qualify the whole Windows shard. The first WSL-launch failure remains retained. |

The ba4 workspace raw test interval was 2,073.718 seconds. This is not complete
build, physical or historical cost. The successor series preserves ba4's Cargo,
Bazel and pnpm Git blobs and formal CURRENT bytes. That comparison does not say
the original integrated PR's dependencies were unchanged from its earlier base.
Platform working-tree hashes retain their own measured identities.

Earlier checkpoint packets retain the original integration compile failures,
owner-observation recovery, zsh build/publication/consumer records, Python and
caller gates, guarded execution rejections, scoped native tests and original
CI artifacts. The packet index and each immutable manifest define their exact
scope; no broad pass is inferred from the number of archives.

## Ordinary daemon delivery and stage boundary

The targeted bf42 audit reads immutable Git objects. Its 24 selected main source
files are byte-identical to ba4, with three additional transport files reviewed.
The scope is named symbols and direct constructors/call sites, not a complete
Rust type-resolution proof or an inventory of deployed host services.

The existing Root factory opens the fixed cognitive checkpoint owner and its
cognitive record type. That handle cannot be substituted for
`HostAuthorityFrontierStore<LearningIterationCheckpointRecordV1>`.
The concrete learning checkpoint already supports restoring its fixed request
and owner set and one-step CAS. No production named provisioning/delivery path
for that learning capability was found in this bounded source review; the
existing `vacant` construction does not itself grant or create authority.

The next concrete implementation boundary is an explicitly installed,
purpose-limited Root service retaining the original registered learning owner,
with a Root/peer/pidfd/lifetime-bound client in the ordinary process. It must
preserve existing five-lane behavior, bounded frames, original live writer
fences, open-only registration and `CommitUncertain` semantics after an
ambiguous write. Restore returns protected data, not an attestation or revoked
permission. The audit packet is a proposal and records no implementation,
provisioning or test execution.

This can close part of checkpoint delivery, D02. It cannot manufacture the
missing complete production `LearningIterationOwnerPortsV1`, independent
stage-result producers, their signatures, effective CellBundle publication or
a different real successor task's committed consumption. Existing FinalUse
issuing and the measured terminal-profile HostCAS recovery remain useful
components with their existing limited scopes.

| Stage | Remaining acceptance                                                                                                                                                                                                                   |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S0    | Ordinary daemon learning-owner composition; original registered learning checkpoint delivery; independent task/stage evidence; legitimate adoption; supported effective CellBundle loading; actual next-task consumption and recovery. |
| S1    | Matched-budget net benefit on real tasks over strong retrieval, rule and control baselines; false-acceptance and retention thresholds.                                                                                                 |
| S2    | Improved real completion with fewer unnecessary evidence/actions and correct fault semantics.                                                                                                                                          |
| S3    | Effect or complete-cost advantage over sufficiently trained GRU/SSM, gradient or other appropriate baselines.                                                                                                                          |
| S4    | Advantage over a fixed graph with a strong scheduler, including migration and organization costs.                                                                                                                                      |
| S5    | Common starting point, component swaps, independent tasks, multiple actually adopted generations and complete history cost.                                                                                                            |

The formal CURRENT file remains exactly SHA256
`c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4`.
Its source/foundation fields and jointly admitted experiment set remain
unfilled. This does not imply that the repository contains no baseline code or
historical experiments; it means that this common candidate has not earned
those joint acceptance claims.

## Verification and reconstruction

From the repository root, run the retained read-only verifier:

```sh
python3 qualification/cell_common_candidate/20261108/execution_history/verify_packets.py
```

To reconstruct the exact original archives into new files, add
`--reconstruct-dir /absolute/path/to/output`. Existing output files are never
overwritten. The verifier hashes every chunk, reconstructs the exact original
archive, checks its complete file-member set and hashes, and never executes
archive content. Its checks establish consistency of retained bytes; they do
not recreate missing execution receipts or grant scientific qualification.

Original archives are split into bounded Git blobs so the original compressed
bytes remain recoverable. New metadata observations are stored separately from
original packets. The publication receipt of this commit necessarily remains
external to that same commit and can be retained in a later checkpoint.

## Scope and costs

This checkpoint has `complete_execution_history: false` and
`full_history_cost: null`. Recorded subprocess and job wall intervals stay wall
intervals. Cache state, dependency downloads, queueing, all earlier attempts,
physical resource consumption and shared overhead are not silently assigned
zero or inferred from selected test durations. A build that starts but never
reaches a case still incurs cost. An unexecuted case remains unexecuted.

Bounded publication-pattern checks are not a claim of comprehensive secret
detection. Full source identities, archive hashes, retained original commands,
explicit failures and limits provide the review boundary. A byte-consistent
evidence archive alone is not proof that the learning system completes the
user's S0–S5 requirements.
