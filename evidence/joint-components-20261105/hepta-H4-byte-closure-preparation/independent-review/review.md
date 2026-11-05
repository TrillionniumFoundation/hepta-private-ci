# Independent review of the H4 content-reference archive draft

## Decision and exact scope

No concrete fail-open blocker was found in draft `archive_reference.py` (43,223 bytes, SHA-256 `ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425`) under its stated hash-pinned-plan and authoritative-completion contract. This is a review of the storage protocol and existing small synthetic utility results. It is not permission to execute a future H4 archive, proof that H4 images overlap H3, native qualification, or completed binary persistence.

The design reviewed is `2dda5331ddd89f70164686f6ed229afca6c4bfa4236b118740a6d529098a9565`. No actual H4 image inventory, export plan or launch request exists in this draft. Those inputs, their hashes, the owned-process release, the new post-run budget and the reserved archive window still require the planned root review.

## H4 inputs are actually read twice

`validate_plan` preserves the exact embedded H4 inventory bytes and requires each planned complete image to have the same hash, length, aliases, actual paths and full original observation objects as that inventory. It rejects partial inventories, unknown image kinds, duplicate logical names or selected paths, repeated aliases, paths outside the declared retained root and a target-directory source. It preserves the H4 native outcome separately from storage success.

`export` opens every selected H4 retained source read-only through the inherited canonical-directory walk with `O_NOFOLLOW`, `O_NONBLOCK`, regular-file and single-link checks. The first pass streams every byte and verifies exact length, ELF magic, SHA and stable file metadata. This includes referenced images: their bytes are read and hashed even though they are not inserted into the child archive. The second independent open/full read requires the same file identity and hash. A final pre-publication identity check is made for each selected source. No alternative alias or parent image substitutes for a missing or changed selected H4 file.

Only one selected path per unique image is reopened. Other retained aliases remain the original mapping evidence; the index explicitly states that they were not reread. The checks preserve an already supplied H4 inventory; they do not themselves establish that an invented inventory describes real H4 processes. That attribution remains the independent native/FD review and the future actual-plan binding.

## The parent is one fixed, complete H3 package

The literal parent pins independently match the existing H3 completion, index, exporter and plan metadata: archive 283,427,280 bytes / `5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773`, index 294,654 bytes / `b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002`, 11 complete ELF images totalling 1,674,575,368 bytes and 16 actual members.

`verify_parent` requires that exact successful archive completion and exact source/plan/exporter/index identities. `read_verified_archive` first hashes the complete compressed file, then independently reads it while parsing and hashing every member, and checks the compressed hash and file identity again. The member inventory must exactly match the pinned index; unsafe, duplicate, missing or nonregular members are rejected. Complete image rows must be directly embedded `H3/elf/<sha>.elf` members with the required complete-image role and actual ELF bytes. Partial and transitive references are refused.

A referenced H4 image must name that one parent, its exact index and a matching complete member with the same full length and SHA. A new H4 image is embedded as its actual source bytes. A no-overlap plan is rejected rather than creating an unnecessary dependent package. The H3 native result remains FAILED and supplies no H4 case, PID, FD or capture credit.

This audit verified the local H3 metadata pins, not the remote 283 MB archive bytes. Future export and final consumption still have to run their complete actual-byte verification.

## Consumer requires the complete two-package byte closure

`consume` requires a hash-pinned H4 completion plus the literal H3 completion pin. It reads every declared original part for both packages, verifies exact sequential offsets, names, lengths and hashes, and hashes each complete part concatenation. Both whole archives are then independently read and every actual member verified. An index or a child metadata package alone cannot satisfy these checks.

The consumer binds the embedded exporter, plan, original H4 inventory, parent index/completion and exact owned-release proof. Each child file row must preserve every planned observation/path/alias field. Each logical H4 image resolves to an actually hashed complete member in the child or the one pinned parent; a referenced row cannot silently become an unverified local payload. The two H4 source-read records and final logical totals must agree. Both archive identities are checked again before returning the closure result.

The returned result explicitly keeps `native_qualification_awarded=false` and `capture_gaps_filled=false`. Authoritative export-job success remains an outer prerequisite: the consumer verifies bytes and the pinned completion document, not a controller job API.

## Publication and budget boundaries

The 14 inherited I/O function/class ASTs are identical to the approved H3 exporter. Source opens remain read-only. New output uses a fresh directory, bounded xz output, exclusive temporary files, full archive/member/part readback, file and directory fsync, and no-overwrite hard-link publication.

One wording correction is necessary for design `2dda…`: publication is not atomic across the whole archive, all parts and completion. The code publishes the archive, then parts, then completion. A later I/O or fsync failure can leave some final-named files without a valid completed delivery. File presence must never be treated as success. The required authoritative successful job, hash-pinned completion and verified complete closure prevent that partial publication from receiving completion credit. This is a documentation boundary, not a request to change the inherited I/O implementation; the owner accepted an additive amendment while preserving the original design and code bytes.

The draft validates a proposed 900-second post-run budget in its plan. It does not internally enforce a wall-clock deadline. The future exact launch request must enforce the reviewed cap and process ownership. This is a new storage component budget and does not change or inherit a native gate budget.

## Existing utility evidence

The original receipt, test source, stdout and stderr hashes were independently verified without rerunning the controls. All eight declared utility names appear once as `ok`; exit code is zero and no timeout is reported. The outer elapsed time is 0.916745657 seconds; unittest reports 0.369 seconds. The tests use small synthetic byte archives and temporarily mock parent constants in memory. They do not read the actual H3 archive or any H4 image.

The controls cover a complete reference plus new embedded bytes, complete two-package consumption, missing/changed parent data and parts, missing child parts, changed actual H4 source bytes, mutation before the second full read, partial/transitive references, substitution of original H4 observations, and refusal to overwrite an existing output directory. This review added no optional tests or native run.

## Current status

Draft protocol review is complete with the publication wording qualification above. Actual H4 plan/inventory/launch review, export, full download and final two-package consumption are outstanding. No desktop, native, learning, archive dispatch or remote bulk action was performed by this reviewer. H1 remains paused with zero in-flight requests.
