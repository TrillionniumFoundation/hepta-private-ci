# Descriptor-backed final byte verification

Parent: #3775, exact 502a52f874c15968abbfd1b2eca7f114f0a5fb70, tree 9ef8e5d3e661ee08f8901b0753df206a07b1e2b1. Its parent candidate #3773 was inspected at 5d1a67b1091fb63e48c257df9ec1bf079ecbd5a9. Only custody.py and test_custody.py change, plus these verification records.

## Finding and repair

The existing final hash uses a BufferedReader. If the consumer reads only 1 or 7 of an 8-byte file, seek(0) can reuse read-ahead bytes. A same-size rewrite with the stat signature held constant then passes the final hash. This defeats the final byte check independently of timestamps; it does not establish that a real filesystem necessarily hides timestamp changes.

Use os.fdopen(fd, "rb", buffering=0) to retain the same already-open descriptor but remove stale read-ahead. All initial hash, type, link, size, and before/after stat checks remain. There is no reopen-by-path or new authorization. The returned FileIO retains the seek/read/tell interface used by the actual ZIP consumer.

The existing custody test now covers consumed lengths 0/1/7/8 with fixed signatures and asserts the specific byte-change error. Positive controls cover unchanged partial consumption and pinned_file -> ZipFile -> member_records on a tiny synthetic ZIP through EOF with member hash verification.

## Actual local outcomes

Python 3.12.14 on dot Linux. No packages installed. Each command bounded by timeout 60s.

- Original exact #3775: normal 10/10, optimized 10/10, exits 0.
- Initial diagnostic probe: 0 and 8 consumed reject; 1 consumed incorrectly accepts changed bytes.
- Initial new regression: two failed subtests (consumed 1 and 7), exit 1. Preserved separately.
- Final regression source with original custody.py: normal and optimized each run 10 methods with two failed subtests, exits 1. Other methods pass. This is deterministic controlled-stat red evidence, not a hosted execution result.
- Repaired source: normal 10/10 (0.080s), optimized 10/10 (0.081s), exits 0, no skips. Source hashes recorded after these runs; no subsequent formatting/source changes.

The red-source reproduction consists of the final project source with only custody.py replaced by original-custody.py. Run python3 -B [-O] path/to/run_synthetic_tests.py. The normal source uses the committed repaired custody.py. Raw log paths reflect these separate local directories; they are not runtime inputs.

## Limits

This establishes post-consumer descriptor rereading, not immutable snapshots or immunity to adversarial concurrent change-and-restore during the reads. The two hashes and stat observations cannot prove every consumed byte came from one immutable instant. Consumer exceptions still propagate; successful context exit is required for a receipt. No complete COCO census, images/models, BFCL, frozen P44 selection, acquisition, rights clearance, statistical qualification, production approval, CI, merge, or deployment was performed. Existing HOLD_NO_GO / DENY_ALL remains. Real large-archive performance was not remeasured.
