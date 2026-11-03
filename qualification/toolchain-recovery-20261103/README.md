# Isolated toolchain recovery, 2026-11-03

The prior execution environment reset after the i18n source and its qualification
were persisted in PR #4709. This checkpoint records a fresh isolated installation
of official tools in the replacement environment. It is tooling evidence only and
does not establish any application, Bazel, full-CI, or production qualification.

The Rust channel manifest was fetched from the official URL, checked against its
official SHA-256 sidecar, and every downloaded component checked against the
manifest's exact x86_64-unknown-linux-gnu archive hash before its official installer
ran with a task-owned prefix and --disable-ldconfig. All five installers returned
zero. rustc, cargo, rustfmt and clippy versions were executed and captured.
The small std probe in this directory was compiled and executed successfully;
its input, command, result, and output binary hashes are in rust-provenance.json.

The CLI archive hashes are pinned to official GitHub release assets. Each extracted
binary was hashed and executed with --version. cargo-nextest 0.9.151's archive and
binary hashes also match the independently retained PR #4709 qualification.

To reproduce, download the URLs in the two JSON receipts, reject any mismatched
archive size or SHA-256, install the Rust components with their official install.sh
into an isolated prefix, and extract the named CLI executables into another
isolated bin directory. Use explicit RUSTC and RUSTDOC from the Rust prefix, and
place both bin directories on PATH. Compile toolchain-smoke.rs with that rustc,
--edition=2024, and -Cdebuginfo=0, then execute it. Expected stdout is
`rust-toolchain-smoke:10` and exit status is zero. Use separate Cargo homes/targets
for each concurrent task; the installed prefixes are shared read-only.

No global Rust/account configuration was changed. Native binaries, downloaded
archives, and third-party build caches are reproducible and are not committed.
Local paths in the receipts describe the observed run, not permanent availability.
