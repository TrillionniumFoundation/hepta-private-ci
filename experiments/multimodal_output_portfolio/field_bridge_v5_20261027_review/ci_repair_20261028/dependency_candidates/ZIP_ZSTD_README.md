# ZIP and zstd upgrade candidate — static preparation only

This directory contains a reviewable patch and complete replacement files. No
repository file was changed, no Rust tool or build was run, and no Cargo or Bazel
lockfile was generated. Rust compilation, formatting, test execution, and the
resolved dependency security audit remain **NOT RUN**.

## Candidate contents

`candidate.patch` changes only:

1. `codex-rs/Cargo.toml`: workspace `zip` from `2.4.2` to `9.1.2`, and `zstd`
   from `0.13` to `0.14.3`, preserving the existing feature configuration.
2. `codex-rs/core-plugins/src/startup_sync.rs`: update both Unix and non-Unix
   `ZipFile` signatures for the reader type parameter; propagate filename decode
   errors; explicitly restrict extracted file permissions to `0o777`; register
   a separate Unix test module.
3. New `codex-rs/core-plugins/src/startup_sync_zip_tests.rs`: a real ZIP extraction
   regression test, shared by the old and new crate API versions.

Complete new contents are under `replacements/`, and the exact original contents
used to make the patch are under `originals/`. `BASE_IDENTITIES.json` binds the
observed repository HEAD and original file bytes. The existing startup tests are
included as a read-only baseline snapshot and are not edited by either patch.

`regression_on_original.patch` adds only the same test module and its declaration
to the original extractor. It does not upgrade dependencies or change permission
handling. This permits a future CI counterexample run with zip 2.4.2 and the old
extractor, followed by the corrected candidate run. Neither run has happened in
this preparation stage.

The candidate was prepared while a separate TLS dependency repair was in
progress. If the manifest or extractor has since changed, integrate these narrow
hunks into the new base and regenerate the replacements; do not overwrite newer
work with a replacement whose baseline hash no longer matches.

## Important correction established from official source

The initial premise that zip 9.1.2 would still hand unsanitized privileged mode
bits to this custom extractor was incorrect. Official zip 9.1.2
`src/format/functions.rs`, blob
`614b5472fdb0b1572c78ecbc30722673ff8ad1e2`, already removes `0o7000` in
`get_unix_mode`. Therefore its `ZipFile::unix_mode()` removes setuid, setgid, and
sticky bits before the caller sees them. Official zip 2.4.2 `src/types.rs`, blob
`d473e289f501bac9d82b76c25406de03c3a721f1`, returns the Unix external attributes
shifted right by 16 without this filtering.

The upgrade supplies upstream filtering. The local `mode & 0o777` adds an
explicit application boundary that passes only ordinary permission bits to
chmod and preserves executable bits. The regression cannot attribute all of its
success under zip 9.1.2 to that local mask: reverting only the local mask while
keeping zip 9.1.2 would still receive filtered modes. The intended old-version
counterexample uses zip 2.4.2 together with the old extraction code.

The official sources are saved under `official/`; each full file's Git blob SHA
and SHA-256 are verified in `OFFICIAL_EXPECTED_BLOBS.json`. The zip 9.1.2 tag was
observed at commit `662ae138dbcec989ee99e6bc4668501add70e209`. The zstd 0.14.3 tag
resolves to commit `75bc74045a2f6ea0439aeed7e159a266da20aac0`.

## What the regression actually checks

The test builds three stored ZIP entries using APIs present in both zip
versions. It then obtains each actual central-header offset from the reader,
verifies the central-header signature and Unix host-system byte, and patches
the external-attributes field at offset 38. One entry contains raw mode
`0o107755`, including all three privileged bits. The others contain ordinary
`0o100755` and `0o100644` modes. Direct reads of the resulting bytes must equal
the intended full archived modes. This avoids `unix_permissions`, which masks
high bits during normal archive creation, producing a misleading safe fixture.

The test also creates a temporary control file and invokes the old raw chmod
operation, asserting that the filesystem retains at least one privileged bit.
It then calls the real `extract_zipball_to_dir`, whose file path writes the
payload and applies permissions. It compares the complete resulting vector of
`(mode & 0o7777, payload bytes)` with expected values. That checks privileged-bit
removal, executable/read-write mode preservation, root-prefix stripping, nested
directory creation, and unchanged contents through the real extraction path.
No payload is executed. All files are temporary. A filesystem unable to retain
the negative-control bits causes an explicit test failure, not a silent skip.

Static data flow predicts that the original zip 2.4.2 plus old extractor fails
this test: its reader returns the raw high bits and the old helper passes them
to chmod. This is a source-based expectation, **not an observed Rust test
failure**. The separate baseline patch makes the observation reproducible in
CI. The test is Unix-only; the updated non-Unix generic helper still requires a
Windows compile check.

## API and dependency review

The fixed zip source declares `ZipFile<'a, R: Read + ?Sized>`. Both helper
signatures use this exact bound. `enclosed_name()` remains `Option<PathBuf>` but
returns `None` when its internal `name()` fails. The candidate's existing
rejection branch therefore calls fallible `name()` with `map_err(...)?`, ensuring
decode errors are reported as such. Valid extraction, content I/O errors, and
unsafe-path rejection retain their existing behavior.

The pinned zstd 0.14.3 manifest requires zstd-safe `^8.2.0`; that manifest requires
zstd-sys `^2.1.2`. Existing workspace construction calls use stream
`read::Decoder::new`, `write::Encoder::new`, `encode_all`, and `decode_all`, whose
public signatures are present in the official new source. This is static API
inspection, not a complete compile or behavior guarantee. The current lockfile
still resolves zstd 0.13.3, zstd-safe 7.2.4, and zstd-sys 2.0.16; the candidate has
not changed that lockfile or established that the resolved graph is free of the
reported advisories. The generated graph and audit must establish that result.

zip 9.1.2 declares Rust 1.88; the observed workspace toolchain is Rust 1.95.0.
The new test module uses existing test dependencies and no external fixture file.
The crate macro already includes `src/**/*.rs`, so no compile-data addition is
needed for this module.

## Verification performed and next execution

Both patch files pass `git apply --check` against the isolated original-file
snapshot. An earlier generated diff omitted the new-file mode header and failed
this check; its exact bytes and failure receipt remain in `evidence/`. The final
patch syntax result does not imply Rust compilation or test success.

After the active TLS repair is ready, generate genuine Cargo and Bazel locks
from the combined source. Use the repository's `just test` path, for example the
scoped `codex-core-plugins` test filter for
`extract_zipball_strips_privileged_modes_and_preserves_regular_permissions`.
Run the baseline patch on the original dependency/extractor combination in a
separate CI checkout to observe the expected failure, then run the candidate
with the generated lockfiles. Run the appropriate dependent zstd tests and
cross-platform compile, formatting, and advisory checks. No lockfile content,
test result, ignored advisory, or broad feature change is invented here.
