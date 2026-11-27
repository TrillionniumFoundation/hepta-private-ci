#!/usr/bin/env python3
"""Render the evidence checkpoint from the current, source-bound ledger."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
d = json.loads((BASE / 'BLOCKERS.json').read_text())
m = json.loads((BASE / 'MANIFEST.json').read_text())
ci = m['ci_evidence_parent']
stamp = d['checkpoint_utc']
text = f'''# MEM8 owner, source and integrated-CI checkpoint

Checkpoint: **{stamp}**. Production adoption: **HOLD / NoUpdate**. Original adoption blockers: **10 remain open**. The completed archive-copy milestone and the engineering subgates below remain closed within their stated scopes.

## Completed engineering work

| Exact source | Executed scope | Actual result |
| --- | --- | --- |
| Source admission `ad5a4ed6` | Source-admission fixtures, format and scoped fix | 4 passed / 0 failed; original source unchanged |
| Complete owner `66f570a7` | Memory, Agentd and protocol, independently on ai395 and GitHub | Each execution: 11 + 5 + 16 = 32 selected cases, no failures; three drain child markers; real same-source CLI and three clean scoped fixes |
| F2 `0c32926c` | Five focused explicit-context/isolation groups | 11 executions, 10 distinct IDs; all passed; clean format/build/fixes |
| G `9d9bdfba` | Six existing episodic Agentd regressions, compilation of added ignored provider fixture, format/V8/real CLI/fix | 6 passed / 0 failed; 782 unselected; all five source guards clean; ignored provider case executed 0 times |
| Original descriptor case `cb0b276f` | The original signed-credit case, separately on Windows and Linux | 1/0 on each host, zero retries; 269 and 780 unselected respectively |
| Dependency closure `f1fd544b` | Original complete Matrix package | 30 passed / 0 failed; two unselected; zero retries and clean scoped fix |
| Dependency closure `f1fd544b` | Original complete RMCP package with a real same-source CLI | **268 passed / 0 failed**, seven unselected, zero retries; clean scoped fix and unchanged CLI/source |

Every row retains its own source identity. Test executions are not actor episodes, and the three drain markers are children of one Agentd test. Build/fix commands execute zero test cases. The older dc96 RMCP run remains **265 passed / 3 failed**; its separate same-source CLI repair is **3/0**. The later full f1fd run is an actual separate 268-case execution, not a combination of those older scores.

### G native evidence

Exact G head is `9d9bdfbaeeec3c618f3fc80e2f663a29c13f4b27`, tree `07192603a5164f4b5d4da24e37595be2a0a04777`, reviewed in [#5926](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5926). The original run completed at **05:26:34 UTC** within its independently declared budget. Its nextest UUID is `b58361b0-49b7-47f2-a15a-43ee34823b29`. Actual drain markers are `commit`, `revoke` and `panic`.

The root fully downloaded and checked the 67-member native archive, 43-member formatter archive and 12-member static review archive. All original phase receipts/raw logs, four source postimages, two zero-byte rewrite patches and CLI identity match. The real CLI is 559,365,856 bytes with SHA256 `49bfbb583bc08a549f8f023880875d2541473f5ec9b3ddd613298855fdf3e976`. Equal production binary bytes between F2 and G do not transfer test results; the G build and source identity are separately retained.

[G complete index](g-native-context/G_COMPLETE_EVIDENCE_INDEX.json) · [Root readback](g-native-context/ROOT_G_READBACK_AUDIT.json) · [38-path component source inventory](CURRENT_SOURCES.json)

The G fixture can exercise native source-aware context under a retained private test writer and test issuer. It has **not executed its ignored provider case**, learned experience in a predecessor model episode, authenticated the original deployment, or measured unseen successor benefit. F2's explicit-context constraints retain the canonical store while disabling the specified implicit memory paths; they do not establish global isolation of every ordinary client, direct store caller, prompt contributor or skill.

### Complete f1fd consumer qualification

Exact source is `f1fd544b3e12ed6aca83872cdeda8114a1e058c0`, tree `fff40d06312d4f6a185772cd8a62a618d55f31cf`, reviewed in [#5934](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5934). Original dc96/f1fd Git commits and parent relationships were published unchanged; all 65 modes, blobs, sizes and native postimages were checked.

The full RMCP command ran **05:48:01–05:55:54 UTC**. Scoped fix finished at **06:02:43 UTC**. Its fresh nextest UUID is `b86c9959-e257-4ce0-91e0-f2eb7120d2cc`. The root checked all 43 archive members, all three complete raw logs, the complete JUnit, every original case identity, all 268 actual case timestamps and source/CLI guards. The CLI is 1,440,865,824 bytes, SHA256 `da59e2327aa74b81be2b6f64a97c060bf67e17db17c860f7642541f804dadbe2`, identical before and after the run.

The Matrix correction keeps the original SDK, test, five-second restart timeout and 200,000-round PBKDF2. It optimizes the locked sha2 dev profile and corresponding Bazel annotations. Both actual lockfiles remain unchanged by that profile follow-up. The earlier compilation timeout executed no tests; its preexisting JUnit remains excluded.

[Full CI evidence at {ci[:12]}](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/{ci}/qualification/memory-cell-mem8-ci-followup) · [Full f1fd and provider readback](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/{ci}/qualification/memory-cell-mem8-ci-followup/checkpoint-v9/ROOT_READBACK_AUDIT.json)

The SQLx provenance erratum withdraws the earlier unreferenced claim of an existing exact-upstream-byte preservation rule. The inspected AGENTS and formatter do not contain that condition. The actual vendor comparison still has 44 changed Rust files, seven identical Rust files, two manifest changes and four other identical files. Formatting conformance does not establish official upstream byte identity. Original archived wording and failures remain retained.

## Final source composition and existing CI

The source is now combined in [#5935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5935): head `2ae5215beaf8d7b7df111a090b82134beae2683d`, tree `12159640adcf073b51f3837e75575e11f5c20233`, over common `96038ccf0660154fac143ba6cbe4be81e00813e8`. The three parents are G, provider/Windows `55951ed9`, and dependency `f1fd544b`. Their 38 + 9 + 65 paths are disjoint. The original seven Windows postimages are already identical in the provider parent.

Two independent tree reconstructions checked 73 original directory objects and reproduced all four original branch roots before deriving the combined **112-path** tree. The composition adds no new source logic and preserves every original postimage.

The complete static review package has **157 members**. The root fetched its full 392,476 bytes from immutable commit `049459ac4c2b8c5626668a80d38e5aedafeb0286`, checked the archive SHA256 and Git blob, and compared every member byte with the original local package. Offline replay revalidated the 73 Git trees, four original branch roots, 112-path combination, 107 CI source files, 121 frozen CI files and 30 pinned blocker evidence files. This review performs zero new native tests or model calls.

[Root full review readback](integration-review/ROOT_FINAL_REVIEW_READBACK_AUDIT.json) · [Independent V2 blocker review](integration-review/FINAL_BLOCKER_REVIEW_V2.md) · [Existing CI policy review](integration-review/CI_REVIEW.md)

At this checkpoint, the existing automatic CI for the composition is **in progress**. MEM, architecture, Windows and the blocking-CI chain have actual new run identities. main's observed required check contexts are **CI required** and **Architecture required**; the common review base is unprotected. Classic protection detail access returned HTTP 403, so no broader absence-of-protection claim is made. Cargo/workflow changes select the repository's existing full-repo CI scope. Queued jobs, completed steps without reviewed case evidence, and older component passes do not qualify this integration head.

Both provider diagnostic cases remain ignored in these ordinary CI paths. This new CI campaign does not replay the old unknown turn or reset the already completed original owner/F deadline.

## Original provider attempt remains failed and unsettled

The ordinary smoke on exact `55951ed9094ae894f0256a3461fd9504ef060473` remains **0 passed / 1 failed**, 12 unselected and zero retries. Its native wrapper ran **04:46:25–04:48:18 UTC**, exit 100, without hitting the wrapper's outer timeout. The original **20-second matching-completion wait** failed after turn admission. Only five of seven expected phases were observed; there is no matching completion or Full thread/read terminal.

- Original thread: `01a1c8ef-125f-75ae-aaf1-0fe5a4c079f6`
- Original turn: `01a1c8ef-1fbd-75b0-bc6e-2b22a1f1f596`
- Original requested client key: `qualification-e2e-message:Integer(2)`
- Original nextest UUID: `20e63f6c-6648-4068-9b54-51f828fd99cc`

One logical application turn was admitted. **Physical provider request count and remote outcome remain UNKNOWN.** The original after-state GET returned 502 and prevented overall driver-result generation; the actual native failure is retained separately. The retained fixture remains private. Its ordinary ProductClient did not have a native DurableInferenceControl journal, so none is fabricated retrospectively.

Read-only settlement v1 failed on an obsolete logs-column assumption. Its separately identified v2 completed at **05:29:21 UTC**, with original DB/WAL hashes unchanged, an empty exact queue binding and an original recovery-ready candidate, but no assistant/terminal. A missing process path, zero local token counter or absent queue row cannot prove remote cancellation or zero physical model requests.

A later single bounded gateway journal query covered **04:47–04:49 UTC** and returned zero records/matches. Three separate current GETs at **05:53:41–05:53:42 UTC** returned HTTP 200 for health, routing and models. They are current availability observations, not original inference settlement. The complete safe RESULTs and terminal receipts were read back; a subsequent durable stdout frontend read did not return and that stream is explicitly excluded.

[Provider source PR](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5908) · [Original failed qualification](provider-original-failure/QUALIFICATION_RESULT.json) · [Current GET/journal readback](provider-gateway-readonly/ROOT_GATEWAY_READBACK_AUDIT.json)

### Explicit projection correction

The two original read-only rollout projections wrongly copied a nested world-state object while claiming private context was absent. Those original projections and the prior unreferenced unsafe archive are excluded from the current package. The original private records were not changed. Explicitly derived redacted projections retain original file/line hashes, permitted scalar observations, and only field names/type/hash/length for world-state. The old objects are not claimed deleted from GitHub.

The root and independent reviewers checked all **64 members** of the new package, the absence of the removed context text, and exact identity of original native logs, JUnit, observation and binary receipts. The correction neither changes the failure nor supplies a successful terminal. [Projection erratum](provider-original-failure/PROJECTION_PRIVACY_ERRATUM.json)

## Source exclusions and the real capacity limit

The pinned metadata audit establishes a **minimum hard exclusion union of 69 source groups**. The old MEM union was 67; two additional groups were exposed by an earlier cell-causal pilot. The released catalog has **178 groups: 97 train, 54 development and 27 retention_validation**. Of the 81 groups in the existing candidate roles, 65 are known excluded. This leaves **at most 16: 7 development and 9 retention_validation**.

All 16 have current exposure **UNKNOWN**. Verified unseen capacity is **null**, and none is admitted to a new study. The 97 train-role entries are outside the existing released-role protocol; this is not a claim that all 97 were actually trained on. Catalog/source hashes also do not authenticate custody or group independence.

The existing W gate requires at least **20 groups and four per role**. Even optimistically this catalog remainder is short by at least four. Keeping the actual old W allocation of 16 development / 4 retention_validation would require at least nine more development groups. These requirements are not transferred to E: the inspected episodic gate requires its own pre-execution protocol and contains no approved numeric source minimum or allocation.

The root downloaded the full 25-member metadata package and replayed the offline audit against the full original **61,412,948-byte** MEM6 CAS and the original MEM5 ZIP. All 17 retained metadata inputs, 69 per-group provenance chains, roles and residual counts passed. This metadata audit executed no new actor or model and cannot certify complete current exposure.

[Full source report](source-exclusion/REPORT.md) · [69 exclusions and provenance](source-exclusion/EXCLUSIONS.json) · [Capacity and W/E distinction](source-exclusion/CAPACITY.json) · [Root full readback and replay](source-exclusion/ROOT_SOURCE_READBACK_AUDIT.json)

## Scientific and original-owner gates

Historical fixed-selector retention remains **30/84 versus 28/84**, 2 wins / 82 ties / 0 losses, with 16 initial no-ops per arm. The source-level one-sided 95% lower bound remains **0.0**, so the positive-benefit gate is **not met**. Historical selector comparison remains **21/54 versus 13/54**, 9 wins / 44 ties / 1 loss, with 10 initial no-ops per arm; it is selector evidence. No new scored memory-benefit actor episode has been added.

The original archive-copy blocker is closed: all 128 parts reconstruct the original archive, and a separate host restored its files. Original owner/effect recovery remains a distinct gate. The bounded original-deployment review found test-only public roles and a release-false startup record; it did not authenticate the original production writer, source verifier, independent final-use issuer or effect destination.

The bridge code is implemented and fixture-qualified. To close its deployment gate requires the original descriptors/caller binding, canonical store/current cut, retained authority/lease lineage and source custody adapter. Cold recovery must preserve that lineage under the authorized recovery interfaces and reconcile original pending requests/effects by identity. A new test owner or grant supplies none of those original capabilities.

| Original blocker | Current evidence boundary |
| --- | --- |
| Working-state scientific gate | Existing lower bound 0.0; adequate new W cohort unavailable in current catalog |
| Ordinary-owner bridge | Implemented/qualified in fixtures; original deployed binding unauthenticated |
| Provider runtime binding | Original failed test with one admitted turn, remote terminal unknown; G provider path unexecuted |
| Unseen episodic benefit | Separate E protocol, verified unseen cohort and actual paired successor study not completed |
| Strong baselines and association | Python mechanism controls exist; matched native actor interventions and trained head not qualified |
| Source ownership/exposure/trust | 69 exclusions proven; current complete exposure and independent authority not authenticated |
| Deletion and external effect | Logical withdrawal/read checks passed; physical propagation and real commit-time effect fencing not established |
| Full owner/effect cold recovery | Original files recovered; original authority, pending inference and real effect state not recovered |
| Full cost and slow consolidation | Full lifecycle cost and an actual slow semantic/skill component not qualified |
| Hosted CI | Component scopes passed; final 112-path combination is undergoing existing required CI |

The minimum missing inputs and existing execution interfaces are recorded in the independent blocker review and the current [BLOCKERS.json](BLOCKERS.json). Hash validity, file restoration, native regression success and real successor benefit are recorded as separate observations. No threshold, timeout, assertion or historical denominator was relaxed to close a gate.
'''
(BASE / 'CHECKPOINT.md').write_text(text)
print(json.dumps({'checkpoint_utc':stamp, 'bytes':len(text.encode()), 'open_original_blockers':10}))
