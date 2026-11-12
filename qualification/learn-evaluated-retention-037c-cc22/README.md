# LEARN follow-up evidence: exact cc22 source checks

This package preserves the path from the exact 8faf failures to the source-gate pass on cc22a69972d029d3ef28d49096f396eb5214c616, tree 827fb70ed75d30c48d4693cbd0d23ea04f5744da. Work remains in progress. All ordinary Adopt, ordinary NoUpdate, daemon-plus-Root cold-recovery and multi-generation qualifications remain **0**.

| Evidence | Actual outcome |
| --- | --- |
| Full source gate on 8faf | 397 tests: 381 observed passes and 16 failures/errors; preserved. |
| Local repair baseline | All 16 original failures reproduced in six affected suites. |
| Local repair iterations | Two unsuccessful mutation-helper attempts retained, followed by 66 tests passing on exact local postimages. |
| C product formatting | Actual Rust 1.96 rustfmt exit 0, unchanged isolated product bytes. |
| 8faf maintenance | just fix exit 0 with one source postimage; this is not a clean-source pass. |
| cc22 formatting and maintenance | just fmt exit 0 and just fix exit 0; clean, unchanged inventories and zero postimages. |
| Full source gate on cc22 | **397 observed passes, 0 failures; exit 0, no timeout, 255.525 seconds.** |
| Fullcaller on 8faf | Real exit 1 without timeout: unregistered cell_q24_training_command_readback_service.rs at the SourceBound Training readback boundary. |
| cc22 native helper | Build and verify-only commands completed; focused and Root test terminals are still pending. |
| Post-repair fullcaller | Pending separate caller-declaration repair and fresh execution. |

The source gate kept the original 600-second command and ran in an isolated clean worktree. Its 14,842 tracked-path inventory is unchanged before and after. The old caller worktree's HEAD, configuration, index, sparse state and Cargo.lock also remained unchanged. The two different source and native-maintenance inventory hashes are not compared across their different algorithms.

The source repair changes one original C call to an explicit Trainer borrow plus UFCS, retaining the same refusal, snapshot, prior receipt and await. Source-QA updates follow the real private binding extraction and actual evaluated S/C read callers. The verifier, authority values and caller boundary sets were not widened by that six-file repair. The independent caller finding is recorded separately and is not described as already repaired by the C change.

PROGRESS.json binds each result to its actual execution source and status. PACKAGING_NOTE.md explains unchanged original indexes, omitted source copies and large remote originals. The previous b298 evidence package and frozen publication are preserved.
