# MEM8 V6 original independent source-only qualification

Original run `43032289667`, job `130562136934`, attempt 1 completed successfully at
2026-11-11 13:52:45 UTC. Its workflow/harness commit is
`268539ff9272c8c1950ad630416f66774ce2f890`. The separately checked-out source is
`421d15080b3cb942be8ac51bbe443e268d124a9e`, initial tree
`df293c7709860ecfc3889e4cabb1f970fb649d8e`.

The original gate ran from 13:47:51.535614 to 13:52:35.002618 UTC, 283.467004 seconds
within its unchanged 600-second deadline. Repository formatting, full-tree scan
for all 13 old test names, both Python regression modules (16 + 2 unique cases),
caller self-test, and full caller verification succeeded. The complete caller JSON
matches the retained 75,046-byte golden receipt except for the explicitly derived
`rustFilesScanned` count, 6200 to 6201. There are no ignored receipt fields.

All 109 cumulative source paths, their original/base/formatted bytes, and all three
complete Git trees are inside the authoritative original records tar within the
original ZIP. The final staged tree is
`3f89ddeff13d0af85f4abe2690699107357f1038`. Four files have formatter changes;
the original source HEAD and its committed tree were unchanged, and its working
tree is consequently not clean after those staged edits. Both lock files remain
byte-identical. No source commit/ref was changed by this run.

`ORIGINAL_ARTIFACT.zip` is the complete original 6,686,095-byte GitHub artifact;
its 365 ZIP members all pass CRC/hash verification. Its authoritative records tar
contains 363 regular members, including the manifest. Scattered ZIP record files
omit hidden paths by upload-artifact policy; only the complete embedded tar is
authoritative for the full source record set. The original job log is preserved
as its complete 108,272 UTF-8 bytes. No temporary download URL is included.

Run `python verify_package.py <extracted-package-directory>` to verify the outer
manifest, original metadata/log/ZIP, every embedded tar member, all 109 source
postimages, three Merkle trees, exact test IDs and raw OK counts, full golden JSON,
tools, lock identities and original deadlines. This only replays an offline
evidence validator. It does not run repository tests, a compiler, a host service,
or a model. `verify_source_records.py` can also audit the extracted records directly.

This is source-only qualification. It does not claim native Rust compilation,
Windows behavior, a fresh Bazel dependency-graph solution, ordinary provider
success, episodic benefit, or complete hosted CI success. Earlier failures and
unknown remote requests retain their separate identities.
