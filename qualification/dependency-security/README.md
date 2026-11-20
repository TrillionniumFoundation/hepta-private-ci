# Compression dependency security maintenance

This stage upgrades ZIP and Zstandard independently of the TLS, Node, and
Matrix dependency stages. It retains the Rust 1.95 toolchain.

| Dependency | Previous lock                           | Security candidate |
| ---------- | --------------------------------------- | ------------------ |
| zip        | 2.4.2                                   | 9.1.2              |
| zstd       | 0.13.3                                  | 0.14.3             |
| zstd-safe  | 7.2.4                                   | 8.2.0              |
| zstd-sys   | 2.0.16 + zstd 1.5.7                     | 2.1.2 + zstd 1.5.7 |
| ctutils    | 0.4.2, activated by the new ZIP graph   | 0.4.4              |

The advisories require ZIP 9 or newer, Zstandard 0.14.3, zstd-safe 8.2.0,
zstd-sys 2.1.2, and ctutils 0.4.4. See
[ZIP extraction](https://rustsec.org/advisories/RUSTSEC-2026-0368.html),
[stream context reuse](https://rustsec.org/advisories/RUSTSEC-2026-0391.html),
[legacy stream decoding](https://rustsec.org/advisories/RUSTSEC-2026-0403.html),
[Wasm allocation](https://rustsec.org/advisories/RUSTSEC-2026-0410.html), and
[constant-time masks](https://rustsec.org/advisories/RUSTSEC-2026-0385.html).

## Runtime and build behavior

The workspace selects the previous ZIP codec set explicitly. ZIP 9 adds PPMd
to its defaults; this stage does not introduce that additional format. The
`bzip2-rs` feature selects `bzip2/bzip2-sys`, retaining the previous C bzip2
backend. This avoids changing that implementation as a side effect of the
security update. AES, bzip2, deflate/deflate64, LZMA, XZ, time metadata, and
Zstandard remain enabled. Dependency license, advisory, source, and build
checks retain their existing policies.

The curated-plugin extractor reads ZIP entries individually. It does not call
`ZipArchive::extract`, so upgrading that upstream function alone would not fix
the custom permission handling. The local extractor now rejects filename
decoding failures and imports only ordinary `0o777` permission bits, preserving
executability while excluding archive-controlled setuid, setgid, and sticky
bits. Existing path validation and the behavior that materializes symlink
entries as ordinary files remain in place. A later archive entry cannot use
such an entry to write through a filesystem symlink.

Zstandard's underlying bundled C version remains 1.5.7. The wrappers receive
the upstream state-reset, output-bound, and allocator fixes. The existing
rollout/thread-history compression APIs and stored record formats are retained.
Recovery still goes through the original persistence owners and their tests.

The Bazel MSVC include-directory patch is rebased against the actual
zstd-sys 2.1.2 `build.rs`. Upstream already guards the visibility flag for MSVC;
the local patch retains only the missing include directories. Check patch
application against the exact resolved crate before updating the Bazel lock.
Patch application is not a Windows runtime qualification.

## Validation and acceptance

From `codex-rs`, run:

```sh
just test -p codex-core-plugins -p codex-rollout -p codex-thread-store \
  -p codex-http-client -p codex-app-server-protocol
```

The archive tests exercise raw ZIP special-mode metadata, path traversal, and
an archive symlink followed by another entry. The original persistence,
recovery, HTTP compression, schema-fixture, and precomputed-export tests must
also pass. Do not replace those tests with lock inspection or an isolated ZIP
smoke test.

Run `just bazel-lock-update`, the Bazel lock check, and the original full
`cargo deny --all-features check`. Remaining advisories in other dependency
groups continue to fail the repository gate. A dependency-stage test or host
build does not grant Asterinas native, cross-platform, or production
qualification. Record failures inherited from the baseline and rerun the
complete owner suite after integrating their separate fixes.
