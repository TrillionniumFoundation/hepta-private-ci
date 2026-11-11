# MEM8 owner and memory-path checkpoint

Checkpoint: 2026-11-11 05:16:08 UTC. Adoption: **HOLD / NoUpdate**. Original blockers: **10 open**.

## Newly closed engineering subgates

The complete owner integration is now qualified on exact `66f570a77c60aac8d33e6cbeac8dfd120ef1d867` / tree `8eaee893e1e6e43423f288fc654e05c3c95f6179` in two separate executions: ai395 run `mem8-native-66f570-tools-ai395-20261111-ed353-v7` and GitHub run `42953532462`, native job `130303174020`.

| Scope | ai395 | GitHub |
| --- | --- | --- |
| Memory | 11 passed, 0 failed; 420 unselected | 11 passed, 0 failed; 420 unselected |
| Agentd | 5 passed, 0 failed; 781 unselected | 5 passed, 0 failed; 781 unselected |
| Protocol | 16 passed, 0 failed | 16 passed, 0 failed |
| Actual drain children | commit, revoke, panic | commit, revoke, panic |
| Format, V8, real CLI build | Passed | Passed |
| Three scoped fixes | Passed, source unchanged | Passed, source unchanged |

Each execution contains 32 selected cases; the three drain children belong to one Agentd case. The independent host completed at 04:07:00 UTC. Its CLI is 559,365,840 bytes with SHA-256 `2dc4165feb9cf8289b70b39c239b145d5976ec3142445cb6d15abf30bd91c8e2`; the GitHub CLI is separately built and has its own full hash. Both original binary hashes match their corresponding post-validation hashes. No source or assertion was relaxed to obtain a pass.

F1 #5916 and F2 #5917 separately add the configured episodic ingress profile. Exact F2 `0c32926cfec58d986477fc72ba3a4787ab75fde9` / tree `0d5aa1544aad103f9099c7c8347d8075d6ecc76e` completed at 04:26:35 UTC, before the original 04:47:03 deadline.

| F2 group | Passed | Failed | Unselected |
| --- | ---: | ---: | ---: |
| Config manager constraints | 2 | 0 | 323 |
| Agentd episodic | 6 | 0 | 781 |
| Qualification feature profile | 1 | 0 | 789 |
| Memory extension control | 1 | 0 | 99 |
| Native empty tool router | 1 | 0 | 2446 |

These are 11 executions and 10 distinct test IDs: the profile case also runs with `qualification-cognitive-write`. Format, V8 input preparation, exact-source CLI build and two scoped fixes passed with unchanged source. F2 retains the original cognitive store for explicit source-checked context and disables the specified automatic memory paths when episodic ingress is configured. Existing profiles without this ingress retain their selection. NativeAppServer already selects the empty tool router; this is not a claim about every ordinary client, direct host/store caller, prompt contributor or skill.

The root independently checked the full 47-, 35- and 89-member host archives, the complete official GitHub ZIP, and all 88 original files in the F2 bundle. Checks include every manifest hash, raw-log/receipt binding, actual unique case IDs, the three marker lines, exact postimages and source/binary identity. The root audit and original archives are indexed in `MANIFEST.json`. Earlier real failures remain retained and are not overwritten by successful follow-ups.

## Additional completed engineering checks

The original Linux signed-credit case passed on exact cb0b: **1 passed / 0 failed**, 780 unselected, zero retries, clean source. Its full raw log, JUnit and the two earlier zero-test sparse-checkout failures are retained under the CI evidence branch.

The original dependency run on dc96 remains **RMCP 265 passed / 3 failed**. A separately identified run built the real CLI from that same source and rechecked the original three failures: **3 passed / 0 failed**, zero retries, exact source and binary unchanged. This is not a single 268-pass execution. The complete raw follow-up bundle is still being obtained; full f1fd RMCP qualification is a separate next step.

The production Matrix candidate f1fd completed the **original 30 selected cases: 30 passed / 0 failed**, zero retries, with two ignored/unselected cases excluded. Scoped fix also passed with no source rewrite. Root independently read back both published archives, every original raw log and receipt, the JUnit, all 30 case identities and all 65 changed source postimages. The test ended at 04:52:50 UTC and scoped fix at 04:56:35 UTC. The earlier v3 compilation timeout executed zero tests; its preexisting JUnit is retained but receives no credit.

The original SDK/test bytes, five-second restart deadline and 200,000-round PBKDF2 remain unchanged. The change optimizes the locked sha2 dev profile and supplies corresponding Bazel annotations. Both real lockfiles are unchanged by that profile follow-up. Whole-repository CI and cross-version migration are not implied. Complete evidence is in CI commit [26467689b04bd183fef2dc347fdd085fcde6d41e](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/26467689b04bd183fef2dc347fdd085fcde6d41e/qualification/memory-cell-mem8-ci-followup/matrix-production-profile-v4).

The SQLx vendor review has an explicit correction: the earlier unreferenced “existing exact-upstream-byte preservation condition” was not an identified repository instruction. The frozen AGENTS/formatter require formatting and do not create that condition. The 57-file vendor nevertheless has 44 Rust files with changed bytes, seven identical Rust files, two manifest bounds changes and four identical other files. Formatter conformance, normalized syntax comparison and official byte identity are separate observations. Original archived evidence is preserved.

## Original provider request: admitted, completion unknown

The exact 55951 ordinary smoke selected one case: **0 passed / 1 failed**, 12 unselected, zero retries. Original nextest UUID is 20e63f6c-6648-4068-9b54-51f828fd99cc. The turn/start RPC returned inProgress for thread 01a1c8ef-125f-75ae-aaf1-0fe5a4c079f6 and turn 01a1c8ef-1fbd-75b0-bc6e-2b22a1f1f596. Its subsequent 20-second wait failed with “timed out waiting for turn/completed”; the native wrapper itself did not hit its outer timeout.

Only five of seven expected phases were observed. No completion notification or Full thread/read terminal was obtained. The after-state GET returned HTTP 502 and masked overall driver-result generation; the original raw log and native receipt remain intact. A proposed diagnostic patch preserves that secondary exception separately, but does not change the original run, timeout or assertions.

The retained fixture /tmp/.tmpr79GeL exists with mode 0700. Fixture-owner teardown does not prove cancellation or completion at the remote provider. This ordinary ProductClient run has no native DurableInferenceControl journal: one cannot be created afterward to pretend to recover it. Reconciliation uses only the original thread/turn and existing retained records. **One logical turn was admitted; physical request count and the final model outcome remain unknown. There are zero new scored memory-benefit episodes.**

## Reviewable source and original-owner inputs

The final B/C/D1/D2/D3/E/F1/F2 review package is retained under review-stack-final. Root reconstructed complete Git trees from the exact ad5 base: E equals qualified 66f, F1 equals 911d62a9 and F2 equals 0c32926. This is exact source equivalence, not a new native run or an assertion that every intermediate stage was separately tested.

The owner-binding review is retained at qualification/memory-cell-mem8/owner-binding-readonly-20261111. Its bounded public-role read found test_only roles; the startup record reports release false and supplies no observed timestamp. Neither host availability, a new fixture owner nor an archive copy supplies the original deployed writer/source verifier, independent issuer or real effect state. No private key or credential values were exported.

The concrete missing inputs are the original config/registration/native-profile and preheld owner pidfd; the original private writer/current cut and authenticated source adapter; the original route descriptor and pending-request reconciliation evidence; and the independent final-use authority plus original effect/outbox/destination state. A numeric PID, source digest or self-authored JSON grant is not a replacement.

G is separately published as draft [#5926](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5926), exact 9d9bdfbaeeec3c618f3fc80e2f663a29c13f4b27. Its four postimages match the real formatter and passed independent static review. A new bounded zero-model native phase is prepared to compile the new ignored fixture and run the six existing F2 cases. No G native pass or provider result is claimed at this snapshot. It does not reset the completed owner/F deadline and cannot establish unseen-source benefit or original deployment custody.

## Original acceptance gates

The full original 61,412,948-byte MEM6 archive is preserved and independently reconstructed from all 128 GitHub parts at b66d74d4a61b15f3d9e1eb3b5ddfa251777ee4c1. This closes the original raw-copy blocker. Full owner/effect cold recovery remains a separate open gate.

Historical science is unchanged: fixed-selector retention is **30/84 versus 28/84**, 2 wins/82 ties/0 losses, with 16 initial no-ops per arm. The source-level one-sided 95% lower bound remains **0.0**. The newer selector comparison is 21/54 versus 13/54, with 9 wins/44 ties/1 loss and 10 initial no-ops per arm; that is selector evidence. Previous fresh-process delivery and KV/BM25/ICL/uniform paths are zero-model mechanism checks. The now-admitted ordinary smoke is neither a successor task nor memory-benefit evidence.

Unseen episodic benefit, strong matched baselines/trained association, original source custody and independent trust, physical deletion/cache propagation, final external-effect fencing, complete owner/effect recovery, full cost and slow consolidation, and repository-wide CI retain their own gates. No scoring rule, threshold or weighting was relaxed. Current production action remains **NoUpdate**.
