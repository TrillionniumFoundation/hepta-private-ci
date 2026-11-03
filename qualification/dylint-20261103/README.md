# Maintained Dylint on the original nightly

The original argument comment lint job on dependency union
`0b9da54535a7795b2433947a479e6d9e71525e0a` failed while building
`dylint_driver v5.0.0`: its Clippy checkout looked up the removed `master`
branch. The complete decoded log from run `41701057334`, job `126174513735`,
is retained as `original-lint-failure.log.gz`, with both compressed and decoded
hashes in `local-evidence.json`.

Pin `dylint_linting` and `dylint_testing` to 6.3.2 and align the installed
`cargo-dylint` and `dylint-link` versions in the existing ordinary, blocking and
release workflow definitions. The maintained implementation includes upstream
commit `f1ed83623faead3799afd91533f8647715272c33`, which follows Clippy's `main`
branch. Source and official release metadata are retained in the evidence.
The existing `nightly-2025-09-18`, Clippy revision, lint implementation, UI
expected diagnostics, linker configuration and original test commands remain
unchanged. Updating release configuration does not publish or run a release.

## Actual local result

The repository's `just test` entry point ran all eight original tests across
two binaries, including the previously failing UI aggregate: eight passed,
zero skipped, zero retries. The standalone workspace needs its existing
`.cargo/config.toml` passed explicitly when selecting it with `--manifest-path`;
it has the default nextest profile rather than the main workspace's local
profile. The exact command, complete output and all 33 input hashes before and
after execution are preserved. No inner UI case count is inferred from the
aggregate's successful result. The original six Python wrapper tests also pass.

The actual compiler was Rust 1.92.0 nightly from 2025-09-18. Official 6.3.2 CLI
binaries were verified against release digests. The UI run built its driver in
a fresh task directory. Completed native compilation cache was subsequently
reclaimed with 109 executable hashes retained; no source was deleted.

The original `just bazel-lock-update` and original lock check both exited zero
in 88.79 and 2.94 seconds. All 1,647 recorded inputs were unchanged. The generated
lock is 1,688,065 bytes, SHA-256
`50ffccd2af246c69a365f7ec35d84ca6ee3b16381ae1775a585d2fc8795a216d`.
Its 39 changed JSON paths are only dependency facts for the isolated lint
workspace; the main Cargo lock and module declarations are unchanged. Initial
local daemon, sparse checkout and Java certificate failures are retained. The
successful generation used the same official Bazel 9.0.0 in foreground mode
with the preinstalled operating system Java truststore. TLS verification and
dependency checksums remained enabled.

Run `python3 qualification/dylint-20261103/verify_local.py --repository .
--output /tmp/dylint-local-verification.json` as a single command to replay the
bounded evidence archives and compare all recorded inputs to the checkout.
The verifier does not execute archived code and rejects optimized Python.

## Remaining hosted gate

Local generation is not committed-head qualification. The added isolated
workflow first checks the committed lock using the original checker, then runs
the original update, checks again and requires byte-identical regeneration.
It preserves the complete command outputs and all input hashes. The existing
argument comment lint job must also run its original Cargo tests on the
published candidate. Keep this Draft and `HOLD_NO_GO` until those results are
independently inspected. This change does not close unrelated full CI,
performance, scientific or production activation gates.
