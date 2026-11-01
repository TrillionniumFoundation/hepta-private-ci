# Reproducible publication packaging

`pack_results.py` is a separate publication utility. It is **not part of the
formal scientific source freeze** and does not load models, parse NPZ arrays,
select successful runs, or compute scientific results. Its SHA256 is recorded
in each bundle manifest and in the synthetic validation receipt.

## Scope and timing

Run packaging only after all training, evaluation and report writers have
finished. Include the entire study directory so that completed results,
checkpoints, raw NPZ files, receipts, source snapshots and retained failures all
travel together. In this campaign, keep `results/formal_01`, `formal_02` and
`formal_03`: `formal_01` was superseded, and `formal_02` retains the interrupted
six-worker attempt. Packaging makes no quality judgment about any of them.

Every input must be an explicitly mapped directory. The mapping is
`ARCHIVE_PREFIX=SOURCE_DIRECTORY`; archive paths use `/`. Multiple roots can
place external development evidence inside the reconstructed study without
copying it into a live run. Duplicate member paths and file/parent collisions
are refused. Paths cannot be absolute, contain `..`, backslashes, drive colons,
empty components or control characters.

Example after completion; substitute the actual completed development roots:

```bash
repo=/workspace/scratch/e8334174d4c2/hepta
study="$repo/experiments/hcsn_distribution_content_r15_20261101"
logical=experiments/hcsn_distribution_content_r15_20261101
python -B "$study/publication/pack_results.py" pack \
  --root "$logical=$study" \
  --root "$logical/development/development01=/workspace/scratch/e8334174d4c2/development01" \
  --root "$logical/development/development02=/workspace/scratch/e8334174d4c2/development02" \
  --output "$study/publication/archives/completed_bundle" \
  --chunk-bytes 49152 --dict-mib 128
```

For development results in `/tmp`, change the source side of a root mapping to
that exact directory, retaining an informative archive prefix. For individual
external helpers such as `/tmp/hcsn_tail_json_writer.py`, first copy the desired
files into a dedicated, stopped provenance directory, then map that directory
to `$logical/development/publication_provenance`. Do not map all of `/tmp`.
Alternatively, copy the required evidence into the study before packaging.
Keep the original failed partial JSON and successful wrapper result together.

The default omissions are `__pycache__`, `.git`, `.pytest_cache`, `archive` and
`archives` directories; existing `.tar`, `.tar.*`, `.tgz`, `.txz`, `.tbz*`, `.zip`
and `.7z` files; and sockets. `.npz` and `.pt` are included byte-for-byte.
All symlinks are refused, and other special files are refused. `--exclude GLOB`
adds an archive-relative omission and records it in the manifest. An explicitly
mapped source root may itself be named `archives` when it contains required
input evidence: exclusions apply to descendants, not the mapped root itself.
The current output and its temporary packaging directory are always omitted.

Use a private output path with one publisher. An existing output is refused;
the final directory rename is not an atomic no-replace primitive against a
concurrent process creating an empty output directory. Stop input writers too:
the tool checks file identity, size, mtime and ctime before/after reading and
rescans the inventory, but this is not a snapshot filesystem. Do not redirect
pack stdout into an included source directory: the shell would create a live
receipt file before packing. Save that stdout outside every mapped root.

## Format and integrity

One lexically ordered POSIX PAX tar stream is compressed as one continuous XZ
stream using LZMA2, preset 6, CRC64, and a configurable dictionary (default
128 MiB). Only then is the compressed stream cut into chunks. Compression state
continues across member and shard boundaries, allowing repeated NPZ byte
sequences within the dictionary window to be reused. No file is recompressed
individually. A larger dictionary can help more distant repetition but uses
substantially more encoder memory; the 128 MiB setting can require roughly a
gigabyte or more. Run it after the training workers have exited.

The default 49,152-byte shard becomes exactly 65,536 Base64 characters when
full. `--chunk-bytes` accepts 1 through 16 MiB; `--dict-mib` accepts 1 through
1024. The tar records only regular files, with mtime 0, uid/gid 0, empty owner
names and mode 0644. Shard and manifest mtimes are also set to 0. Empty
directories and original executable bits are not preserved. The same member
bytes, paths, tool, options and compression implementation produce identical
bundle bytes despite changes to source mtimes. No cross-libxz-version bitwise
identity is promised.

`manifest.json` records every member's relative path, byte count and SHA256;
every ordered shard's path, byte count, SHA256 and Git blob SHA1; the combined
XZ stream's byte count and SHA256; exclusions and compression options; and the
publication helper SHA256. Git blob SHA1 means
`SHA1(b"blob " + ASCII(byte_count) + b"\\0" + shard_bytes)`, using an actual NUL
byte after the count. `manifest.sha256` checks the manifest itself. Save the
printed manifest SHA256 with a trusted publication receipt or Git commit;
checksums alone do not establish the publisher's identity.

## Fresh restoration

Upload/copy **all** shards, `manifest.json`, and `manifest.sha256`. The shards
are pieces of one XZ stream, not independently extractable archives.

```bash
python -B "$study/publication/pack_results.py" restore \
  --bundle "$study/publication/archives/completed_bundle" \
  --destination /workspace/scratch/e8334174d4c2/publication_fresh_restore \
  --manifest-sha256 MANIFEST_SHA256_FROM_PACK_RECEIPT
```

Restoration checks the manifest checksum, every shard's two hashes, the whole
compressed stream, and each tar member's size and SHA256 before publishing any
member to the destination. It refuses missing, extra or reordered shards;
duplicate JSON keys or members; unexpected members; path escapes; links,
directories and special tar entries; and noncanonical metadata. It uses no
`extractall`. A private staging directory contains only verified regular files.
Destination components use directory descriptors and `O_NOFOLLOW`; publication
uses atomic hard links that cannot replace an existing path. An existing
identical regular file is accepted, while different content is refused. A
private destination without concurrent writers is required. Use a fresh
destination for the final independent restoration receipt; all source/member
hashes are checked even on an idempotent repeat restore.

The standard-library utility requires Python 3.10+ on POSIX with directory-FD
and `O_NOFOLLOW` support. Linux is tested. Staging is created beside the
destination; restoration requires that destination files share that filesystem
for atomic hard-link publication. It needs disk space for the concatenated
compressed stream plus a full extracted copy. A destination nested mount may
fail safely with a cross-device error.

## Synthetic validation

`validate_packaging.py` creates only temporary synthetic artifacts and runs
the actual pack/restore CLI. The fixture includes a checkpoint-shaped binary,
NPZ containers with repeated identity bytes, receipts, source-like text, an
external development root, an empty file, Unicode and a long PAX path. It uses
a 4 MiB dictionary to keep this mechanical check small. It verifies complete
byte equality, fixed restored mtimes, deterministic bundle bytes after source
mtime changes, idempotence, conflicting-file refusal, corrupt-shard refusal,
source/destination symlink refusal, path checks, duplicate members, and
non-regular tar entries. It does not access scientific results or test data.

`packaging_validation_02.json` records 15 passing checks. The retained
`packaging_validation_attempt_01.json` records a fixture setup failure: the
execution environment denied creating an AF_UNIX socket. The succeeding
receipt explicitly leaves actual socket-fixture execution untested here; the
production scanner excludes `stat.S_ISSOCK` entries. To repeat the synthetic
check, supply a new receipt filename:

```bash
python -B "$study/publication/validate_packaging.py" \
  --output "$study/publication/packaging_validation_repeat.json"
```
