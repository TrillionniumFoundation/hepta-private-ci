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
   V8 uses its existing independently PR-triggered workflow and original
   permissions; it is not nested under the read-only upgrade workflow. Verify
   that its exact-final-head matrix actually runs rather than assuming that
   a successful metadata-only result provides consumer ABI coverage.

## Current qualification status

The first draft retained its original generated Bazel and Nix locks until the
existing manual `hepta-diagnostic-source-export.yml` workflow was dispatched on the
upgrade branch with `rust_toolchain_locks=true`. The added job produces real,
source-bound lock artifacts; the default false value preserves all existing
diagnostic jobs. This extends the workflow's original Bazel-lock diagnostic
owner, which already checks, updates and exports `MODULE.bazel.lock` and is
listed in `scripts/ENTRYPOINTS.md`. It adds no automatic trigger or permissions.
The new job independently satisfies the existing bounded, credential-free
manual diagnostic envelope. Existing reviewed jobs containing local actions
remain on their original integration-review path; no admission rule changes.

Initial automatic bootstrap run 37192766977 never started a job: the nested
V8 caller lacked the child workflow's original actions-read permission. The
repository-surface guard also rejected that new automatic workflow. The
automatic wrapper was removed entirely; neither restriction is weakened.
Original V8 qualification remains its own independently triggered workflow.

After reviewing and committing generated locks, explicitly run the existing
full Cargo and Bazel workflows on the exact final head; select Bazel's
`qualify_native_windows=true` to include its original native Windows suite.
Also verify existing native-desktop blocking CI and the complete V8 matrix.
No lock-generation receipt is a compilation/test pass. Results must distinguish
passed, failed, skipped and unrun work. This is not a completed upgrade,
release, or merge-ready change until applicable qualification succeeds.
No merge or deployment is part of this change.

### Generated locks accepted for compiler qualification

Manual [run 37193654373](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37193654373)
completed successfully on source `143ac2b22326db719019bfe13614cc96ee064ef9`,
tree `e78936205b233f24a2c4e8c727f63c827049b728`. Its explicit lock-only job
ran; the five ordinary diagnostic jobs were skipped as selected. Actual Bazel
generation and strict lock recheck passed; Nix refreshed only rust-overlay and
evaluated eight package/development-shell derivations across the four systems.

Artifact `11300405315` has ZIP SHA-256
`801f86ad6f67cc27196624bdacd5a891f7256fcc1994d9be34f63872da2ae4f7`.
Its exact source/run receipt, every declared artifact digest and both original
input locks were independently checked. The bundled manifest is byte-identical
to the separately retrieved official Rust 1.99.0 manifest. All 101 generated
archive hashes match it, with identical target/component coverage, including
compiler source and target-independent rust-src.

- `MODULE.bazel.lock` SHA-256:
  `60754b2f9a7a49ac5f08e44bd7c8fcfd829763e6b211c9beb218a1b29ceb4585`.
  Only the 101 old/new stable Rust archive facts changed; all other JSON values
  are unchanged.
- `flake.lock` SHA-256:
  `2d7760939fdfb6faf943cf17b1bf978cbbeb1402bc2532fa7fe361a78b0d61e6`.
  Only rust-overlay's revision, NAR hash and timestamp changed. Its revision is
  `dbc715a4b7c0ace63b9769a032d1dd34cd89e5bd`; all other inputs and wiring remain.

These accepted generated files are prerequisites for the subsequent exact-head
compiler matrix. They do not prove Rust compilation, native runtime tests,
whole-repository compatibility or release readiness.

### Release source-integrity correction

The first full Cargo run `37194453076` exposed a pre-existing flaw in the
release-profile job: `cargo chef cook` ran directly in the checked-out workspace
before Clippy. [cargo-chef 0.1.71's implementation](https://github.com/LukeMathWalker/cargo-chef/blob/v0.1.71/src/recipe.rs)
creates its minimum dummy project in the current directory. The workflow did
not restore the product sources afterward. Actual x86_64 and aarch64 musl
release jobs `111413298399` and `111413298593` reported success while compiling
first-party dummy crates at version 0.0.1. These green jobs are explicitly
excluded from product-source qualification.

The correction removes that in-place cache optimization, retains the existing
release Clippy command, targets, features, lint rules and deadlines, and runs
a real locked release build on those existing release matrix entries. The
ordinary Cargo/sccache caches remain, but musl Cargo home and fallback sccache
now live under RUNNER_TEMP instead of polluting the product checkout. Matching
cache restore/save paths move with them; no source-guard exclusion is added.
The job now records its input commit/tree,
checks the expected commit and the complete worktree before Cargo, compares
the final commit/tree, and rejects tracked or untracked worktree changes after
Cargo. No product path is excluded from these worktree checks. Identity files
are retained with the existing timing artifact. Six disposable-Git regression
tests execute the actual guards against clean source, dummy replacement,
untracked product input, a clean replacement commit, a wrong starting SHA and
the real musl cache setup without changing the product source.
Only a fresh run on the corrected source can establish release qualification.
