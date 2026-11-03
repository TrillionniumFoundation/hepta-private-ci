# ZIP backend dependency coverage

This candidate is stacked on `82943251870182af4dff666b30c65eb116b82892`
(Draft #4698). It preserves the ZIP 9 API and extraction-permission repair,
and retains the application's eight explicitly selected archive capabilities.

## Actual issue and repair

Upstream ZIP 9's `bzip2-rs` feature forwards `bzip2/bzip2-sys`. Cargo also
activates ZIP's same-named `bzip2` feature and the dependency's default backend.
The actual Cargo graph and native build therefore include `libbz2-rs-sys`,
while cargo-deny 0.19.0's reconstructed graph omits it. Its license pass alone
did not prove coverage of the dependencies being built.

Weak forwarding removes the unrequested backend from Cargo's graph, but the
actual cargo-deny list then also omits the selected `bzip2-sys`. The two retained
negative controls demonstrate both failures using real tool execution.

The adopted manifests declare `bzip2-sys` directly on the optional,
default-disabled bzip2 dependency. The selected ZIP feature activates that
dependency without another forwarding edge. Both tools now include ZIP,
Bzip2 and the C backend, and neither includes the unrequested Rust backend.
This vendored package selects the application's existing C backend whenever
Bzip2 is used; independent Rust-only backend profiles are not asserted to be
unchanged. No compression format, AES feature, permission check, license
allowlist, advisory waiver, or production gate is removed or relaxed.

The official archive SHA256 and all 65 original package file hashes are in
`../../codex-rs/third_party/zip-9.0.0/VENDOR_PROVENANCE.json`. Only its two Cargo
manifests differ. All 63 other original files, including every Rust source and
the MIT license, are unchanged. The added Bazel rule is a dependency library;
the published crate omits the fixtures needed to run upstream unit tests.
Existing product extraction tests remain the behavior checks.

## Exact local results

| Check | Result and boundary |
| --- | --- |
| Original strong-forwarding Cargo/deny graph | Rejected; actual Rust backend and audit coverage differ |
| Intermediate weak-forwarding Cargo/deny graph | Rejected; the actual C backend is absent from the audit list |
| Final locked, all-features workspace graph | PASS; Cargo and cargo-deny agree on ZIP/Bzip2/C-backend packages |
| Bazel feature declaration | Matches Cargo's actual ZIP feature set; this is not a Bazel build pass |
| Native product extraction | PASS: two exact checked-in tests, five format round trips and eight Unix permission modes, zero ignored tests |
| Vendor inputs during native execution | Every file hashed before metadata/build and after execution; unchanged |
| Same-database cargo-deny | 8 advisory errors remain; licenses, bans and sources report no errors; original policy unchanged |
| Full formatter attempt | Rust and Python scripts complete; absent DotSlash and sparse SDK path prevent a full formatter pass; new BUILD is independently formatted with the repository-pinned buildifier |
| Bazel lock and original CI | Pending exact-source hosted generation and the unchanged lock check; DRAFT/HOLD |

The native replay compiles the exact contiguous production extraction span
and the exact two repository tests against the vendored dependency. It checks
Stored, Deflate, Bzip2, Zstd and Xz payloads plus eight Unix permission modes.
It is not the complete core-plugins suite, a Windows validation, an AES or
Deflate64/LZMA fixture campaign, or complete symlink isolation qualification.
The initial scratch-space preflights are retained separately; they stopped
before testing. Final execution used a separate executable temporary filesystem
and the original 900 MiB resource preflight.

The preserved advisory database is
`6c5fedf8ff03c485ed674d8f941e0180f3f72d70`. Remaining IDs are
RUSTSEC-2024-0449, RUSTSEC-2026-0318, RUSTSEC-2026-0319,
RUSTSEC-2026-0370, RUSTSEC-2026-0371, RUSTSEC-2026-0372,
RUSTSEC-2026-0374 and RUSTSEC-2026-0387. None becomes closed through this patch.

## Reproduction

Use the repository's pinned Rust/Cargo 1.95.0, cargo-deny 0.19.0, and the
recorded advisory database for an identical audit snapshot. From the root:

```bash
python scripts/check-zip-feature-isolation.py --offline --check-deny
python qualification/zip-feature-isolation/replay.py --work-dir /tmp/hepta-zip-native --offline
cargo deny --manifest-path codex-rs/Cargo.toml --all-features --locked check --disable-fetch --show-stats
just bazel-lock-update
./scripts/check-module-bazel-lock.sh
```

The graph and native JSON receipts bind command lines, input hashes and tool
outputs. The temporary read-only CI workflow checks out the exact PR head,
runs the existing lock generator, retains its lock/logs and input hashes, and
runs the original lock check. It does not write a branch or turn a failed
generation into a passing gate. The generated lock must still be read back,
matched to this source, committed and verified by the original CI.
