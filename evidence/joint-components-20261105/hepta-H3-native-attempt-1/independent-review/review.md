# H3 ordinary-process proof and FinalUse attribution: independent review

## Decision

H3 remains **FAILED** on frozen Hepta `6db78eca53a5acdda0d96873d3f4cd65863426f0`, tree `e91f5994017fc5d2cfe58d405a20ee6ad9376772`. The ordinary process recovery test completed its assertions. The later FinalUse command returned 50 passing tests, but the external collector-composition gate rejected an unmatched live process. Full evidence, its ignored-test listing, fix, and fmt were not reached after this stop.

This review reads retained local source, raw logs, receipts, and capture records. It does not run Cargo, a native test, a benchmark, the original reader, or a remote file read. `recompute_review.py` verifies hashes and reconciles the original records; `review.json` contains the exact input inventory and extracted evidence.

## Ordinary process recovery actually reached the final readback

The product command reported 2 passed, 0 failed, no timeout, in 51.07525175099727 seconds. Its two exact test names and FD-exec records form a bijection. The test image SHA is `5e23924bee81a156601ba19d849f94a4196bd1ad1831bffc16934937d7c81a07`; it is distinct from the daemon executable whose two generations are described below.

The complete proof has SHA `f70ff1df3fd8a4b38b9c984400c1fa5101a882cae38720638bed6ee77310c50f`. The original coordinator's separate daemon-verification receipt is present and binds that proof. The original coordinator rehashed the retained daemon image before writing this receipt; this local review has not independently downloaded or rehashed the daemon ELF.

| Binding | First process | Restarted process |
| --- | --- | --- |
| PID / start ticks | 1032350 / 99355292 | 1033361 / 99358739 |
| Owner generation | 1 | 5 |
| Capture method | Actual live FD, full hash and retained copy | Same held file object, independently checked current process identity |
| Full hash and copy in this capture | Yes | No |
| Actual executable bytes | 488,112,384 | Same held object |
| Actual executable SHA | `00a637f55c720b06a655b569930bddaef19fd791467bc4784fe0bfb9e0002a26` | Same |
| Device / inode | 2050 / 58259796 | Same |

The source writes `completed.json` only after all of the following succeed: the provider has durably applied the request before an ACK is delivered; the controlled first process is killed; the original recovery trust/frontier bytes remain unchanged; the restarted process has a new owner generation; the old client and old-generation grant cannot dispatch; a temporary provider lookup miss remains **Indeterminate**; a later lookup recovers the original operation; and a third local read returns the same durable terminal without another lookup.

The final counts are **one POST, one physical application, two provider lookups, one consumed FinalUse nonce**. The provider record and durable ACK agree on the effect key, payload digest, and provider operation ID digest. Reopening the store returns the same succeeded terminal receipt. The second process is then killed through the owned cleanup path and its exact lease is removed.

These are the assertions that H2 did not reach after its second ELF capture timed out. They now have actual H3 evidence. They do not retroactively qualify H2. The scope is controlled local operator/provider fixtures and a supervisor that pre-fences the daemon before SIGKILL. This is not an unannounced power-loss test, a full-host restore, independent custody, or a generic-tool/provider authorization closure. Held-file metadata stability also does not claim resistance to a privileged hostile writer.

## FinalUse: command passed; original capture composition failed

The original FinalUse raw log SHA is `5e9f024b087d98f23a6b717d617369cfcf7c3cde7afe385a6d78c393fc450387`. It contains 50 exact `ok` outcomes. The 50 primary FD-exec records have unique PID/start identities and the same exact-name multiset. They identify a 14,103,072-byte test image with SHA `1383f1adbe7721e1ff362142f0ce35ef755bece0ae2a188cb28e375a2332b923`.

The live polling result also has 50 observations, but its membership differs:

| Observation | Identity | Meaning supported by the retained record |
| --- | --- | --- |
| Matching live / primary records | 49 identities | Corresponding outer test processes |
| Extra live observation | PID 1038111, start 99368575 | Same image and selected killed-owner case, in the bound wrapper subtree |
| Corresponding exact outer test | PID 1038102, start 99368558 | Primary FD record for `final_use::tests::killed_owner_releases_lock_but_keeps_claim` |
| Primary record missed by polling | PID 1038034, start 99368370 | `authority_rejects_shared_state_directory_and_symlinked_files`, a different short-lived case |

Exact frozen `final_use_tests.rs`, Git blob `76ea4ef5aab6c25c806fcbfe6a0f24329b60dc69`, explains why a second process can exist for the killed-owner test. It directly starts `current_exe()` with `--exact`, its own case name, and `--nocapture`, setting the child-state environment variable. The child persists a claim, writes a ready marker, and parks until the outer test kills it. Its stdout and stderr are suppressed. This direct spawn does not go through the nextest target runner.

The H3 coordinator nevertheless requires every selected-image live observation to match a distinct primary FD-runner record. This is an over-strict assumption for this existing test's direct child. The extra observation is consistent with that source and timing, but the old poll format saves neither complete argv nor a contemporaneous immediate parent/ancestor identity chain. The exact parent of PID 1038111 therefore cannot be retrospectively established. It must remain an unmatched observation. It cannot fill the unrelated short outer process that polling missed.

The original error, `final-use-profile-controls lacks an exact per-case test-image binding`, remains valid for the frozen H3 capture configuration. No original record is deleted or relabelled, and the overall FAILED status is preserved.

## Minimal boundary for a new H4 configuration

The primary outcome-to-FD bijection must remain unchanged. A helper child is supplemental process evidence, never a 51st test or a substitute FD record. The exception should be fixed to this gate, exact contracts target, exact killed-owner test name, and exact child argv.

The collector should save the child's complete argv and stable before/after PID/start identity, opened executable identity, and real ancestor chain to the exact bound wrapper PID/start. The immediate parent PID/start must match the unique primary outer record for this case. The parent's contemporaneous argv and executable identity must also match that primary record. Matching only a wrapper, image, source, or selected test name is insufficient.

Two stable observations around opening the child and direct-parent executable FDs are a sufficient attribution instant for this controlled collector. Retaining both FDs and checking their file metadata after hashing preserves the opened images even if a process exits later. It is not necessary to require that the parent remain live through the entire copy; that would lose otherwise valid short-process evidence. The report must state this timing scope. If the parent is already gone, reparented, has changed image/argv, or the chain is incomplete during those observations, the collector must not invent the association.

The focused controls are a real direct-child positive association, wrong immediate parent despite matching wrapper/image/name, stale or missing parent identity/chain, and changed image/argv. Missing or duplicate primary FD records must continue to fail independently. A newly observed unknown child must remain an error, not be silently discarded by a broad helper exception. H4 requires its own new execution evidence under the unchanged frozen source and original command, 60-second per-test, wrapper, and 5400-second outer limits. H3 is not upgraded by the new rule.

## Archive inventory cross-check

The separate `h3-image-inventory-review.json` cross-references all 279 observations in the original H3 inventory to retained FD/poll/proof records. Its 11 unique images total 1,674,575,368 bytes across 30 retained aliases. The unmatched FinalUse record remains unassigned, and the daemon's two generations share one retained image with only the first marked as a full hash/copy. This is a metadata/provenance review, not a remote-byte or archive-integrity result. The exporter must preserve these distinctions and the overall FAILED status.
