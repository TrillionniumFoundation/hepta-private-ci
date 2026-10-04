# Rust 1.99 build-toolchain qualification

## Decision and source identity

Assessment date: 2026-10-04. Upgrade the supported product build toolchain to
the exact stable Rust 1.99.0 release, rather than a floating `stable` channel.
The assessed integration source is PR #1375 commit `24537b10`, tree
`6ad626bfd4fbbde9e899cad0ef53ba47bacfb65d`. Canonical PR #1303
`9d3c9f5bc33bf58a8c4afa77696956eaa6d14f4b` also pins 1.96.0; main
`c6f90d48c40f7b5267db587bb3c3f4934f1414a8` pins 1.95.0.

This is justified by compiler correctness and build-tool fixes, not a claim
that a known exploit or miscompilation has been demonstrated in this product:

- [Rust 1.96.1](https://blog.rust-lang.org/2026/06/30/Rust-1.96.1/) fixes a MIR
  miscompilation, Cargo HTTP retry/timeouts, and Cargo's bundled libssh2
  CVE-2025-15661, CVE-2026-55199 and CVE-2026-55200. The integration's 1.96.0
  predates these fixes. Current CI normally uses the Git CLI, which limits
  applicability of Cargo's libssh2 fixes there; other Cargo users may differ.
- [Rust 1.97.1](https://blog.rust-lang.org/2026/07/16/Rust-1.97.1/) fixes an LLVM
  miscompilation present since at least 1.87. Release builds use optimization
  and thin LTO, so testing only debug builds is insufficient.
- [Rust 1.99.0](https://blog.rust-lang.org/2026/10/01/Rust-1.99.0/) was released
  on October 1 and is the latest stable release verified during this assessment.
  It includes the intervening fixes. We do not require its new APIs or assume
  a product performance gain.
- The May Cargo CVE-2026-5222/5223 fixes already shipped in 1.96.0; they are
  not evidence of a new 1.96-to-1.99 benefit. The 1.98.1 vtable fix repairs a
  1.98.0 regression, not a demonstrated defect in the current 1.96 compiler.

## Scope and intentionally separate versions

Upgrade Cargo workspace and native app pins, Bazel's default toolchain and
generated archive bindings, Nix packages and development shell, Windows setup,
devcontainer, development command, active CI, V8 consumer smoke builds and
offline compiler exports together. Refresh only Nix's rust-overlay input.
Keep dependency versions and Cargo lockfiles unchanged unless actual compiler
testing proves a necessary compatibility fix.

This does not raise a downstream MSRV promise. The main workspace declares no
`rust-version`; vendored Matrix SDK and Rama crates declare 1.96 and retain it.
Servo's independent worker declares 1.88 and its development-evidence workflow
retains that separate baseline. Upstream rusty_v8's source build retains its
own 1.91 compiler; the product consumer is tested using 1.99. The
`nightly-2025-09-18` rustc-private argument-comment linter remains separate.
Historical `single-main-*` workflows replay a fixed September 22 source and
retain their original toolchain/evidence identity. Historical audit branches,
past reports and the separate Game 1.85 environment are not rewritten.

The old dtolnay action SHA `ebb3d1676050bfd0971c36c1e215b5751473994d`
[hardcodes 1.96.0](https://github.com/dtolnay/rust-toolchain/blob/ebb3d1676050bfd0971c36c1e215b5751473994d/action.yml)
and ignores `with.toolchain`. Active workflows now pin verified generic action
`7e38f4b43b4db5c8dd498af069a4f6196df1d067` and pass the exact desired version.
This also makes the existing nightly inputs effective, instead of attempting
to install nightly-only components on the old stable toolchain.

## Compatibility risks and required validation

[Official release notes](https://doc.rust-lang.org/stable/releases.html) identify
changes worth testing: LLVM 23 and static PIE support; v0 symbol mangling and
backtrace formatting; Windows thread-local destructors and socket error kinds;
stricter transparent layout/transmute checks; new Clippy/rustc diagnostics;
debug string escaping; temporary scopes in assertion macros; and edition-2024
workspace dependency default-feature inheritance. Initial manifest inspection
found no first-party top-level inherited dependency disabling defaults enabled
by the parent, but full target-specific resolution still requires testing.

Qualification requires the exact final commit, not results from the old compiler:

1. Generate `MODULE.bazel.lock` with the repository's actual Bazel and pass
   `--lockfile_mode=error`. Compare all stable-toolchain archive hashes and
   target coverage against the official Rust 1.99.0 distribution manifest.
2. Generate `flake.lock` with Nix, changing only rust-overlay. Evaluate both
   package and development-shell derivations for Linux and Darwin, x86_64 and
   aarch64. This is evaluation, not a completed native build on all four systems.
3. Review the source-bound generated lock artifacts and commit them. Re-run
   checks on that commit; no CI job writes to a branch or creates credentials.
4. Run existing full Cargo CI: formatting, benchmark smoke, shear, Clippy and
   build for the eight existing Linux GNU/musl, macOS and Windows MSVC target
   triples; retain its representative release builds and all existing nextest
   platform suites. Run existing full Bazel CI, including Windows cross/native
   coverage and dependency/lock drift gates.
5. Validate native app compilation and V8 archive/allocator ABI consumer smoke
   on supported targets. Keep the separate nightly linter and ancillary build
   baselines operational. Record blockers separately from upgrade regressions.

## Current qualification status

The first draft is a source proposal. Its original generated Bazel and Nix
locks deliberately remain unchanged until the hosted `locks` phase produces
real, source-bound artifacts. It must not be treated as a completed upgrade,
release, or merge-ready change at that point.

The `compatibility` phase reuses the repository's existing full Cargo and Bazel
workflows only after reviewed lock artifacts have been committed. Lock receipts
explicitly say compilation/testing did not occur during generation. Results
must distinguish passed, failed, skipped and unrun work. No merge or deployment
is part of this change.
