# E6 ACK ordering: actual d035 and 8996 results

This is an immutable evidence checkpoint for two executed candidates. **The complete original NoUpdate parent has not passed.** No cold D or Adopt run is qualified by this checkpoint.

## Exact source and outcome

| Source | Actual result |
| --- | --- |
| `d0353abfbf9ac783f0fe842fe313977e9d49bff9` | 34 component cases passed. The real Root lane mechanism parent failed its exact output-line assertion because the first marker shared the libtest prefix. Its StalePrepare child finished the mechanism assertions; the Revoked child and ordinary parent did not run. |
| `8996e4c5b6a8662c51f47d9e164b8c839635c796` | A two-byte leading newline in the test success marker fixed framing without weakening the parent's exact-count assertions. All 34 component cases were rerun and passed on this exact source. The real Root mechanism parent passed both terminal branches. The original ordinary NoUpdate parent then failed when attempted historical request 65 exceeded the unchanged maximum 64. |

The 8996 tree is `73ad85ec4ac58f2c8901b0e85375e21e27641041`. Its only difference from d035 is the two-byte marker formatting change in `root_generation_current_ack_lane_tests.rs`. All product code and all 34 case bodies are unchanged between these two sources; their executed results nevertheless remain separately source-bound.

## Product change and demonstrated scope

d035 changed the original Feature ACK recovery order: it reads the durable Source first. Missing or pending publication follows the existing reconciliation wait within the original deadline. A completed Source still goes through every existing CURRENT, Cell, Source, signed-request and publication check. Other errors remain errors. The additional failure-phase diagnostics preserve the original fence-before-return ordering and log no task payload.

This addresses the original unique C submission's pending observation. It does **not** establish general serialization of arbitrary concurrent replay after a completed Source. The old NoUpdate6 log did not identify a Root lane contention phase, so the new controls do not retroactively prove that contention caused that historical failure.

The real Root mechanism test and the Feature socket ACK tests are distinct controls. The former uses the original protected CURRENT, FinalUse, pidfd, socket and actual client-lane mutex; it does not fabricate a PublishedFeatureTask. The latter covers the actual Feature ACK path with its existing FileCAS fixture. They are not one integrated Root-backed Feature ACK proof.

## Executed controls

8996 reran the exact original 11 owner/source cases, 16 retirement and fault cases, five historical delivery cases, and two Feature ACK cases. `SUMMARY.json` records every full case name and its actual result; original protocols and JUnit files are in the archive.

The one Rust Root mechanism parent ran two child terminal branches, StalePrepare and Revoked. Each retained the original Publish, Recover, RetiredSession, terminal and RefusedReopen phases and added the explicit SourceFirst and CurrentFirst mechanisms. SourceFirst read actual Missing and cold-recovered Pending Source records without touching the held Root lane, then performed a real protocol observation after release. CurrentFirst used a current, initially unfenced session, encountered the held real lane, and remained fenced after release. The parent required exactly one full success line for each order in each child, for four mechanism lines overall. The original 500 ms, 10 s and 60 s limits were unchanged. Successful child stderr is not preserved by that original test wrapper; the evidence is the typed assertions, source, stdout markers and exact parent result, not a claimed captured failure diagnostic.

For d035, the actual source controls were 433 tests in 49 modules, 907 protected rows, 398 affected controls and the full 1,159-boundary CLI. After the marker-only change, 8996 performed a new full 1,159-boundary CLI. The older 433/907/398 evidence is explicitly bound to d035 and is not described as rerun on 8996. Required project-scoped `just fix` and compilation results, including earlier failures, are preserved.

## NoUpdate8: progress and remaining failure

The original product trace records C's receipt returning at 5,419,372 microseconds, Source publication returning at 5,424,108 microseconds, and the final run-start returning at 5,424,725 microseconds. This is actual local C execution and publication progress. The complete learning and acceptance chain still failed.

| Historical sequence | Actual meaning |
| --- | --- |
| 56–57 | Generation installation operation |
| 58–59 | Selection wait's post-admission Source validation |
| 60–61 | Actual Selection stage operation |
| 62–63 | NextUse wait's pre-admission Source validation |
| 64–65 | NextUse wait's post-admission Source validation; attempted 65 was refused before a socket write |

The rejection propagated through the original post-observation, operation fence and delivery failure handling. NextUse did not start, and no terminal Accept was observed. The previous static 63-frame whole-parent estimate is refuted by these actual results. Independent source accounting projects the unexecuted NextUse pair at 66–67, completed-delivery pair at 68–69, and separate terminal Accept at 70. Those five future request IDs are a static calculation, not executed events. A future repair must preserve the real pre/post checks, waits, exact owner identity and separate Accept while fitting the original cap; this checkpoint contains no such repair or successful rerun.

The ordinary parent command took 90.918513 s; its enclosing owner took 147.130848 s. The Root mechanism command took 3.936604 s. `ATTEMPT_COSTS.json` and original execution records preserve compile, lint, source gates, component tests, parents, preparation, physical capture and archival intervals separately. Nested windows overlap and must not be summed as disjoint costs. Physical energy, provider charges, complete network cost and storage byte-seconds were not measured.

## Evidence and verification

`MANIFEST.json` binds 612 original files totaling 200,235,726 bytes. The compressed archive is 3,400,892 bytes with SHA-256 `b86604090557849cadea5992cc2f58a3fd3c7d5320e27cd79bbf31387c3d01f3`. It is stored in eight parts, each at most 480,000 bytes, below the unchanged 512,000-byte changed-blob policy. No policy limit or allowed-path set was expanded.

Run `python3 reassemble.py` to verify all part hashes, the complete archive hash, exact member set, embedded manifest and every original file hash. It writes the reassembled archive only if absent or already identical. It neither extracts nor executes the archived contents. `LOCAL_VERIFICATION.json` records the independent completed local verification. The small top-level results provide a readable index into the original archive.

The physical readback inventories 784 files. Exactly 52 selected non-key files totaling 119,591 bytes were copied with source identity and hash checks; other entries are metadata-only. Thirteen key or business-image bodies are explicitly excluded. Executed large binaries remain at their recorded original host identities, with hashes, device/inode and mode retained; they are not replaced or embedded here. Journals and witnesses remain unchanged. File lengths alone are not completion qualifications.

The remaining limits are explicit: whole NoUpdate false, cold D zero, Adopt zero, whole FinalUse false, direct historical Root-after fault injection unproved, and general same-run ACK replay serialization unproved. The historical cap, ACK timeout, current-operation timeout, original parent harness, signed identities and rejection checks were not widened or replaced.
