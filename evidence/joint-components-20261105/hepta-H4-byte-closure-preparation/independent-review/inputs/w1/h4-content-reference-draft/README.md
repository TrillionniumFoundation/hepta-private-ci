# H4 actual retained image references — cloud draft

This directory is a storage-tool draft. It has not read any H4 retained image,
run on the desktop, built a binary, or launched native tests. There is no actual
H4 export plan or launch request yet. H1/H2/H3 bulk transfers remain paused while
the original H4 native job owns the desktop window.

## What the tool does

`archive_reference.py` has two explicit operations, `export` and `consume`.
It keeps 14 I/O helper bodies identical to the approved H3 standalone exporter;
`inherited-io-functions-ast-check.json` records the exact AST comparison.

The exporter accepts a hash-pinned plan containing the original H4 inventory
bytes, one selected retained path for each complete image, every original alias,
and the original H4 observations and native outcome. Every selected file is
actually read and hashed in full twice, whether its bytes will be embedded or
referenced. These reads must keep the same file identity. Missing files, changed
bytes, nonregular files and substituted H4 observations fail closed.

The only permitted parent is the actual complete H3 package:

| Identity | Exact value |
| --- | --- |
| Archive bytes | 283,427,280 |
| Archive SHA-256 | `5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773` |
| Index bytes | 294,654 |
| Index SHA-256 | `b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002` |
| Actual parent images | 11 complete images; 1,674,575,368 bytes |
| Parent native outcome | FAILED; no native credit transfers |

Before publishing a child, the exporter actually rehashes the entire parent
archive and every member. It accepts references only to complete, directly
embedded `H3/elf/<sha>.elf` members with the same full SHA and length as an
actually reread H4 retained file. It rejects transitive dependencies and any
partial artifact treated as a complete image. Actual new H4 hashes are embedded
as new payload bytes. If there is no overlap, it rejects this unnecessary
dependent format so the existing standalone export remains the appropriate
choice.

The child completion explicitly says `COMPLETE_WITH_REFERENCED_PARENT`. The
child alone is not a complete binary deliverable. The exporter keeps the original
two-read, no-overwrite, whole archive/member/part verification and file/directory
fsync publication protocol. The post-run component is bounded at 900 seconds in
the proposed plan; no native budget changes.

## Consumer contract

`consume` requires the entire parent and child archives, both original
completion records, and all original parts for both archives. The H3 completion
hash is fixed in the tool; the H4 completion hash must be supplied from its actual
successful export receipt. The tool rehashes every part, each actual complete
archive and all members, then verifies each logical H4 image against the actual
member bytes in its declared package. It also compares the H4 original inventory,
paths, aliases, observations, native outcome, source identity and two source-read
records without merging H3 observations.

The result is `VERIFIED_COMPLETE_BYTE_CLOSURE`, with
`native_qualification_awarded=false` and `capture_gaps_filled=false`. This result
does not perform or replace independent FD/case/PID attribution or native gates.
It never infers that a new process was captured because another run used the same
source or executable bytes.

## Actual cloud controls

The first recorded run of `test_archive_reference.py` passed eight tests using
small synthetic byte archives. The tests temporarily substitute fixture parent
constants in memory; they do not claim to have exercised the real 283 MB H3
archive or any H4 input. The original production H3 pins remain literal in the
tool file.

The controls check a referenced image plus a new payload, complete two-package
consumption, changed/missing parents, an actually changed H4 reference source,
mutation before its second complete read, partial/transitive references,
substitution of H4 observations, missing/changed parent parts, missing child
parts, and refusal to overwrite an existing child. Raw stdout, stderr, command,
elapsed time and hashes are retained in the utility receipt.

## Before any real execution

After the authoritative H4 terminal and its exact owned release, obtain and pin
the H4 inventory from actual capture records. Confirm actual overlap with the H3
complete image table; do not infer it from unchanged source. A plan must preserve
the inventory's actual status and every original observation. If any partial
artifact is recorded, this draft refuses it until a separately reviewed lossless
representation exists.

Root and the independent reviewer must verify the actual plan, tool hash,
release proof, 900-second request and one reserved archive window before launch.
No production plan, future result, second attempt or remote request is created
by this draft. Final persistence still requires full download and verification
of every referenced package, not only these indexes and receipts.
