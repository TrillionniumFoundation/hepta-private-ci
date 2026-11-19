# Independent saved-result review: fresh-byte content memo

Decision: PASS_FOR_PUBLICATION_AS_FIXED_SAVED128_PAYLOAD_SHA_WORK_QUALIFICATION.

This certifies the retained evidence and scoped work-count result, not CPU acceleration, production readiness, or strict256 admission. The reviewer did not import or execute the candidate, original history, model or test suite. An independent standard-library audit read saved source/data, verified hashes and JSON linkage, grouped actual opaque bytes, and reconciled recorded results. No candidate or historical artifact was modified.

## Evidence bindings

- Candidate FREEZE SHA256: `4b0653dddd7465e9740e4d723ee492db89a9587320b287bc082c4b8adcc68828`.
- RESULT SHA256: `a10c9d466c0bbb7d982e8511979d565d370b60618d2b74ca773011da964075bc`.
- WAIT4_RECEIPT SHA256: `581a7a63c85d22b49874d534dbddffa8e173fb8c5774b01eb817df6db0d914a0`.
- The source review's admitted freeze matches the executed receipt and current candidate.
- All five frozen files and all 392 pinned input files were independently checked. Input bytes total 2,406,239.

The audit independently reconstructed the full 128-leaf saved history chain, verified before/after and reference linkage, and checked all 256 opaque payload lengths and SHA256 values without decoding arrays. The 128 order payloads contain exactly 24 distinct actual byte strings, not merely 24 declared digest values.

## Work-count result

The complete original and memo walks each perform 256 fresh logical payload reads totaling 1,680,512 bytes. Original computes payload SHA256 256 times over that volume. Memo computes it 174 times over 1,612,780 bytes and records 82 exact-content hits. Thus this fixed walk avoids 82 payload SHA computations and 67,732 hashed bytes, with no reduction in logical reads or read bytes.

The reduction is 32.03125% of scoped payload SHA calls and about 4.03% of scoped hashed payload bytes. Independent grouping of the actual newly audited byte strings reproduces the 174/82 count and pre-clear occupancy of 16 entries / 13,216 bytes. Tail64 similarly reproduces 80 SHA computations, 800,608 hashed bytes and 48 hits from 128 reads / 840,256 logical bytes.

All nine recorded history calls match their independently derived expected errors, work counters, SHA statistics and cleanup flags. The second new memo invocation reproduces the full-walk statistics. Wrong boundaries 0, 64 and 128 reject identically in both modes. All memo history records report cleanup; their entry and retained-byte statistics are snapshots before that cleanup.

The absolute total, including both temporary-file sequences, matches the pre-run independent prediction:

- 9 history walks.
- 768 visited leaves.
- 1,552 logical payload reads.
- 10,083,248 logical payload bytes.

These are source-defined logical counters, not physical disk traffic. Input barriers, JSON/history identity hashing, expected-reference construction, returned-value verification and capacity baselines are outside the scoped payload SHA counts. Python dictionary content hashing, exact equality, allocation, compilation and memory also cost resources. The result does not establish lower total hashing cost or lower CPU cost.

## Actual temporary-file and capacity evidence

Each implementation retains nine named file-sequence observations: four acceptances and five refusals. The audit independently checks every expected error, returned-content SHA and logical-read delta. Original and memo observations are identical. Wrong expected digest on a content hit, stale reference after a same-path same-size change, append, truncation and symlink all refuse. The correct reference to changed bytes accepts, as does restored content. Each mode reads eight times / 88 bytes and makes six digest attempts. Original computes six SHA values over 66 bytes; memo computes two over 22 bytes with four hits.

Both saved temporary directories have exactly a.bin, b.bin and link.bin. In each:

- a.bin contains the final ten-byte truncation `old payloa`, SHA256 `01b68a1d1c0fb8c046204fce76a874a56491125deb85278734087012155a346c`.
- b.bin contains eleven-byte `old payload`, SHA256 `3f04a14abaeed43d93d71863024d4186c91b41b32cb7dbba39bbeb0a42b619b1`.
- link.bin is a symbolic link whose literal target is `b.bin`.

Those terminal files corroborate the final fixture state. Intermediate writes were overwritten rather than preserved as individual snapshots; their evidence is the frozen executed sequence and bound observations. This is trusted-local change detection, not an adversarial-filesystem, race or authentication test. Historical input hashes remain unchanged.

The capacity record exactly matches 21 calls, 20 SHA computations over 81,922 bytes, one hit, 16 entries and 65,536 retained key bytes. Bytearray refusal is recorded with unchanged counters. This establishes the specified per-memo key-payload cap in the fixed fixture, not a total-interpreter memory guarantee.

## Process termination and cost

The independently read child receipt binds the exact result and source freeze. It records complete wait4, raw status 0, exit code 0 and no automatic retry. Child stdout and stderr are empty. User CPU 0.136007 s plus system CPU 0.041790 s equals whole-child CPU 0.177797 s. Recorded wall duration is 0.1799031179980375 s; peak RSS is 12,708 KiB.

The outer CPU prefix adds 0.031517557 s, giving a known invocation CPU lower bound of 0.209314557 s. The final outer tail is unknown and nonzero; preparation, review and historical work are additional. The worker's 0.166882681 s prefix is already included in whole-child cost and must not be added again.

The saved OUTER_TOOL_TRANSCRIPT is explicitly a posthoc excerpt supplied by the invoking agent. It records exec_command chunk `e28eea`, shell exit 0, no returned session_id and completed execution. Its stdout JSON is checked against the saved child receipt. It is relayed tool-transcript evidence for outer termination, not a second independent wait4 receipt or a synchronized method clock. Worker lock release alone would not establish outer completion.

No per-case timing records, timing screen or speed comparison appear in the result. Receipt CPU is invocation cost only. In particular, comparing this 0.177797 s child cost with the earlier equality experiment's 0.285247 s would not demonstrate acceleration: the workloads differ.

Per-process child/outer CPU and wall limits, address-space cap and file limit remain as reviewed. They do not establish complete-subtree enforcement, bounded unknown overshoot, or strict256 total-budget certification.

## Publication scope

The nine-file publication snapshot preserves the six candidate/provenance files byte-for-byte. SUMMARY embeds JSON objects identical to the source freeze, result and child receipt. README correctly limits the finding to saved128 payload SHA work and retains unchanged-IO, memory, cost, fixture, provenance and portability limits. The accompanying publication binding records exact hashes.

Publication as this evidence snapshot is supported. It does not authorize a rerun, integration, deployment, training, 256-step execution, permission changes or relaxation of HOLD_NEW_TRAIN, access restrictions or scientific stops. Future integration requires separate review. The runner still depends on the original sibling saved128 inputs and shared lock and is not a standalone portable artifact.
