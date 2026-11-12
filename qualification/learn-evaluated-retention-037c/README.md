# LEARN evaluated-retention progress evidence

Status: IN_PROGRESS. All ordinary qualification counts remain 0.
This package does not replace or edit the frozen PUBLICATION.json.

The latest published source is 8faf92e260e118508fc62f4f38f3816db24cd4cc,
tree d26b9398ffe6ed269c1d018a7e4e043bbe0a2b9d. Publication of source is
separate from complete source/caller gates, native acceptance and ordinary qualification.

## Interpret the original result and source state together

| Evidence | Recorded source/state | Result and limit |
|---|---|---|
| Complete source closure | Clean exact 726af8f4, unchanged inventory | 357 source tests passed at that source only. |
| Maintenance 8b4 | Exact 8b4d162c, clean before/after | just fix exited 101. |
| Maintenance 726 | Exact 726af8f4, ten automatic postimages | just fix exited 101; complete raw log, patch, postimage manifest and recovery attribution retained. |
| Complete caller 726 | Clean exact 726, unchanged inventory | Self-test exit 0; verify exit 1; timed_out=false. A real failed gate. |
| Maintenance a43 | Exact a43 before command, nineteen dirty files afterward | The original driver status=passed means command exit 0 only. It is not a clean gate pass, native test pass, or ordinary qualification. |
| Selection/intake preflights | Local exact postimages, no original execution commit/tree binding | 45/50 source tests passed, without a clean published-head claim. |
| Complete integration v2 | Local materialized source, no original execution commit/tree binding | 72 source tests passed; preserved without attribution to a later head. |
| Complete integration v3 | 36 individually verified replacement blobs for 8faf over exact 094 | 72 source tests passed; this is not a locally materialized full Git-tree gate. |
| a43 format follow-up | Twenty derived files; exact a43/a9 inputs | Actual Rust 1.96 formatting exited 0; original native checkout remained unchanged with its nineteen dirty files. |
| Final lib format | One isolated exact input file | Actual Rust 1.96 format exit 0 and byte-for-byte unchanged. |
| UFCS boundary | Full 726 index of 6,588 Rust files plus exact-a43 single-file overlay | Before rejected, fixed overlay accepted, copied real unregistered caller rejected. One boundary only; not complete common-head fullcaller PASS. |
| Native filter audit | Exact 094 unchanged parents/workflow and recorded local postimages | Existing filters cover S3+C4+intake2 and the four Root cases in the original 32 parents. Static selection only, no native execution. |
| Ordinary producer audit | 47 exact 094 source blobs and 22 boundary rows | Identity/feasibility audit only. Actual Q24 A and final Root ten-role producer remain missing; production changes 0. |
| Exact 8faf preparation | Clean exact desktop source; 14,749 tracked-path inventory | just fmt exit 0, no postimages, identical before/after inventory. |
| 8faf maintenance attempt v1 | Same exact source, original before snapshot null | Missing old V8 archive caused FileNotFoundError before cargo launch, exit 1. This is not a Rust compile failure or native PASS. A later retry must have separate evidence. |

## Original and derived records

All original evidence files are byte-for-byte preserved. The initial 28-file
ARTIFACTS index is archived in history/ARTIFACTS.initial.json. The current
ARTIFACTS.json indexes every other physical package file with byte length,
SHA-256 and Git blob; it excludes itself to avoid recursive self-hashing.

The 726 RECOVERY.json distinguishes nine postimages read from original files
from lib.rs reconstructed using its exact base Git blob and original patch.
All ten physical postimages and the complete four-chunk raw log matched
their original fingerprints. No source files are copied into this package.

The UFCS result.from-pty.json retains its original derivation: original
terminal bytes decoded as UTF-8 and CRLF normalized to LF. A subsequent
independent disk read returned byte-identical result.json and an unchanged
source-after.json; the separate original tool receipt is retained.

The 8faf preparation terminal receipt contains complete original bytes.
terminal.raw.log preserves them exactly. observations.from-pty.json is
explicitly a derived extraction of its top-level JSON records. The failed
maintenance attempt had before=null; this package does not invent that
snapshot or confuse the preceding successful format with native testing.

LOCAL_MATERIALIZED_POSTIMAGES.json is a packaging-time inventory of the partial
local integration directory after v3. It is not an original run-time
before/after snapshot and must not retroactively bind the v2 run.

The ordinary audit's unchanged original MANIFEST also describes upstream
reports and source files in its original directory. This package contains
the requested report, source-identity manifest, verification, original
manifest and script, without its 47 source files. ARTIFACTS.json describes
the physical package contents.

The original audit report's references to its local source/ directory and to
running verify_sources.py describe the original audit directory. They do not
assert that the evidence package contains those sources. See
ordinary-producer-audit-094/PACKAGING_NOTE.md: retrieve the exact URLs/blobs in
SOURCE_MANIFEST.json into an isolated source/ tree before running the preserved
script. The original REPORT.md and verify_sources.py bytes remain unchanged.

## Acceptance remaining

The native nine-case and four-Root name lists are under native-filter-audit.
Focused currently enforces minimum_tests=1, so fresh JUnit must establish
actual execution of the intended nine cases. Existing Root acceptance
already requires actual UID0, the protected bind and exactly the original
32 parents. Scope remains the original five crates.

Complete ordinary Adopt, complete ordinary NoUpdate, complete daemon/Root
cold recovery and multi-generation improvement all remain at 0.
No h call, Rust/native run or publication occurred while assembling this package.
