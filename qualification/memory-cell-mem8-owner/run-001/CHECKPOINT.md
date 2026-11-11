# MEM8 owner and memory-path checkpoint

Checkpoint: 2026-11-11 04:32:18 UTC. Adoption: **HOLD / NoUpdate**.

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

## Work still running at this snapshot

The original provider smoke request is `mem8-native-provider-qualified-v1-ed353817`. Its sequential driver is compiling the original Linux signed-credit case before the exact-source provider binary and first smoke turn. No provider POST, thread, turn or new model result has been observed. Private fixture retention, exact thread/turn recording, zero automatic retries and original-identity reconciliation remain required.

The dependency candidate `dc96a441` still has its original 265/3 RMCP and 29/1 Matrix observations. A same-source real CLI build for the three original RMCP failures is linking. Those results cannot be borrowed by another source.

Matrix diagnosis identified `login_or_restore.build.timeout`. Optimizing the actual locked `sha2 0.11.1` backend let the diagnostic case pass: preparation 2.967 seconds and reopen 1.195 seconds, without changing the five-second deadline, cryptographic rounds, algorithm or assertions. Production candidate `f1fd544b` restores original SDK/test bytes, applies the Cargo profile and matching Bazel annotations, and has passed fmt, locked metadata and cache-isolated Bazel lock update with no lock drift. Its complete 30-case Matrix command is running; no terminal pass is claimed.

## Original acceptance gates

The complete original 61,412,948-byte MEM6 archive is preserved and independently reconstructed from all 128 GitHub parts at `b66d74d4a61b15f3d9e1eb3b5ddfa251777ee4c1`. This closes the raw-copy blocker. It does not restore original owners or effects.

Ten original blockers remain. Complete software qualification with fixtures does not authenticate the original deployed source/writer/provider binding or independent trust domain. Physical deletion and consumer-cache propagation, final external-effect fencing, full owner/effect cold recovery, complete cost accounting and slow consolidation still require their own evidence. Whole-repository CI is also broader than the passing MEM and Windows case gates.

Historical science is unchanged: fixed-selector retention is 30/84 versus 28/84, 2 wins/82 ties/0 losses, with 16 initial no-ops per arm; the source-level one-sided 95% lower bound remains 0.0. The newer selector comparison is 21/54 versus 13/54 with 9 wins/44 ties/1 loss and 10 initial no-ops per arm. The latter is selector evidence. Fresh-process delivery and exact KV/BM25/ICL/uniform paths are mechanism evidence with zero model calls; they do not demonstrate unseen episodic successor benefit or a trained association head.

No adoption threshold, scoring rule or source weighting has changed. Unknown remote work is reconciled under its original request identity. The current original-blocker count is **10 open**, and the production action is **NoUpdate**.
