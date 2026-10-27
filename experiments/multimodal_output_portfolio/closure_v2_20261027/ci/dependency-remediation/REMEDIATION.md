# Non-TLS dependency remediation

The saved cargo-deny diagnostic at PR head `11a273d` contains 22 errors.
Seven are the TLS advisories handled separately by the root agent; this report
covers the other 15. The unchanged diagnostic is the baseline, not a new scan.
None of the proposed repairs is counted as passing until the actual resolved
Cargo/Bazel graph and the relevant workspace tests pass.

`UPSTREAM_AND_GRAPH.json` records the input lockfile hash, every non-TLS advisory,
representative inverse dependency paths, published versions, MSRV and features.
Its companion `upstream-metadata.tar.gz` contains 51 exact official API/source
responses. Every archive member was reopened and checked against its recorded
SHA-256. Published metadata was checked against upstream main-branch manifests
where a released upgrade still retained the problem.

## Version, dependency and regression matrix

| Family / error count | Current first-party path | Minimum fix and available candidate | Actual obstacle and required regression |
| --- | --- | --- | --- |
| ZIP / 3 | `codex-core-plugins → zip 2.4.2` | Advisory floor `zip >=9.0.0`; prepared `9.1.2`, MSRV 1.88 | `ZipFile` gains a reader type parameter and `name()` becomes fallible. The local manual extraction path also restored privileged permission bits. Preserve default compression/encryption features and test real extraction inputs. |
| zstd / 4 | Seven direct first-party consumers plus core test support and ZIP | `zstd >=0.14.3 → zstd-safe >=8.2.0 → zstd-sys >=2.1.2`; all floors are enforced by the published dependency constraints | Update both the direct zstd requirement and ZIP, or the old zstd generation can remain in the graph. Test compressed rollout/schema/history/request data and existing fixtures. |
| basic-toml / 1 | `codex-secrets → age 0.11.2 → i18n-embed-fl 0.9.4 → i18n-config 0.4.8` | No repaired basic-toml release. Prepared a narrow source patch to `i18n-config 0.4.8`, using workspace-compatible `toml 0.9.5` | Latest released age 0.11.5 and 0.12.1 still reach i18n-config 0.4.8/basic-toml. Upstream i18n-config main already uses maintained toml, but the published crate does not. Test Fluent/gettext parsing and actual secrets encryption/decryption with localization compiled. |
| Matrix crypto / 1 | `codex-hepta-matrix-sdk`, `codex-hepta-matrixd → matrix-sdk 0.18.0 → matrix-sdk-crypto 0.18.0` | Advisory floor `>=0.19.0`; published 0.19.1 is available | Both 0.19.0 and 0.19.1 require Rust 1.96; the repository and Bazel use 1.95. Their SQLite backend needs rusqlite `^0.40.2`, hence libsqlite3-sys `^0.38`, incompatible with the current SQLx 0.9 `^0.37` native `links` selection. Port the real SQLite compatibility patch, update the toolchain coherently, then test persistent session/store reopening, encryption, sync, gap fill, outbox and real Synapse transport. |
| anymap2 / 1 | Same Matrix SDK consumers | RustSec recommends actual `anymap3`; upstream Matrix main uses anymap3 1.1.0 | Released Matrix 0.19.1 still uses anymap2. A Matrix version bump alone will not close this error. Port the maintained implementation change into a properly sourced Matrix package or select a reviewed upstream commit; test event-handler context type lookup and concurrent event dispatch. |
| crypto-bigint / 1 | `codex-aws-auth → aws-config 1.8.12 → p256 0.13.2 → elliptic-curve 0.13.8 → crypto-bigint 0.5.5` | Advisory floor `crypto-bigint >=0.7.6`; p256 0.14.0 and elliptic-curve 0.14.3 can use fixed crypto-bigint `^0.7.8` | Latest aws-config 1.13.0 and current upstream main still require p256 0.13.2 for credentials-login. The semver ranges do not admit the new curve stack. A reviewed AWS login implementation port must retain login, signatures/key formats, refresh and existing credential providers. Do not disable credentials-login to erase the path. |
| zvariant / zvariant_derive / zbus_names / 3 | Four first-party consumers via `keyring 3.6.3 → zbus 4.4.0` | Standalone crates were merged into zbus starting at 6.0.0 | Keyring 4.2.0 is a modular API migration. Its current zbus-secret-service store 1.0.1 still requires both secret-service `^5` and zbus `^5`; secret-service 5.2.0 and upstream main still require zbus 5. Updating keyring alone leaves the advisory family. Preserve Linux native plus persistent credentials, macOS and Windows backends, credential formats, deletion/error behavior and OAuth/login tests when porting the actual D-Bus implementation. |
| unsafe-libyaml / 1 | `codex-skills`, `codex-skills-extension`, `codex-core-plugins`, `codex-external-agent-migration → serde_yaml` | No fixed unsafe-libyaml release. `serde-saphyr 2.0.0` is a maintained Rust parser candidate, MSRV 1.89 | `serde_yaml_ng 0.10.0` still depends on unsafe-libyaml and is not a fix. Serde-saphyr is not a drop-in Value API: current callers inspect arbitrary mapping keys, scalar types and tagged nodes. Preserve those semantics with explicit typed/visitor migration and tests; replacing all Values with JSON Values would reject valid non-string YAML keys. |

Sources for this matrix are the official registry responses preserved in the
metadata archive. The advisory floors can also be read directly:

- https://rustsec.org/advisories/RUSTSEC-2026-0367.html
- https://rustsec.org/advisories/RUSTSEC-2026-0368.html
- https://rustsec.org/advisories/RUSTSEC-2026-0369.html
- https://rustsec.org/advisories/RUSTSEC-2026-0391.html
- https://rustsec.org/advisories/RUSTSEC-2026-0398.html
- https://rustsec.org/advisories/RUSTSEC-2026-0403.html
- https://rustsec.org/advisories/RUSTSEC-2026-0410.html
- https://rustsec.org/advisories/RUSTSEC-2026-0374.html
- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://rustsec.org/advisories/RUSTSEC-2026-0387.html
- https://rustsec.org/advisories/RUSTSEC-2026-0370.html
- https://rustsec.org/advisories/RUSTSEC-2026-0371.html
- https://rustsec.org/advisories/RUSTSEC-2026-0372.html
- https://rustsec.org/advisories/RUSTSEC-2024-0449.html

## Prepared first stage: ZIP and zstd

`zip-zstd-manifest.patch` contains only the two shared workspace version changes.
The root agent owns its application and the subsequent lock resolution, so it
cannot race the separate TLS candidate. The production changes are held in the
fixed binary `zip-source.patch`, which updates
`codex-rs/core-plugins/src/startup_sync.rs` on the disposable candidate:

1. Use the actual ZIP 9 generic `ZipFile` API and handle invalid filename decoding.
2. Mask restored Unix permissions to `0o777`, retaining ordinary access and
   executable bits while stripping setuid, setgid and sticky bits.

`startup_sync_zip_tests.rs` contains six tests. They exercise Stored, Deflate,
Bzip2, zstd and XZ round trips; reading an independently encoded LZMA ZIP;
hostile Unix metadata; an escaping pathname; invalid UTF-8 metadata; and an
archive symlink whose target lies outside the extraction directory. The last
test retains the existing behavior of materializing symlink content as a
regular file and checks that its target is untouched.

The LZMA test fixture is 194 bytes. It was created with Python's standard
`zipfile.ZIP_LZMA`, a fixed 1980 timestamp, entry name
`archive/plugin/run.sh`, Unix mode `0o100755`, and the same small script payload
used in the Rust tests. ZIP 9 does not encode LZMA, so generating this fixture
with ZIP 9 itself would not test the required read path. Existing Bazel
`compile_data` includes the fixture.

No default ZIP feature was removed. In particular, the candidate retains AES,
Bzip2, Deflate64, Deflate, LZMA, time, zstd and XZ support; its upstream defaults
also include PPMd. The zstd default features remain legacy, arrays and dictionary
building. None of the advisory policy, scan scope or ignore lists changed.

Required full-repository regression after resolving the candidate:

```text
just test -p codex-core-plugins
just test -p codex-http-client
just test -p codex-rollout
just test -p codex-app-server-protocol
just test -p codex-thread-store
just test -p codex-core -E 'test(request_compression)'
```

The normal platform CI must still cover Windows and macOS. The Unix permission
test is correctly conditional; decoding and confinement tests are cross-platform.

## Prepared second stage: i18n-config

`codex-rs/third_party/i18n-config-0.4.8` preserves the checksum-verified official
source package, license and original manifest. Only the production parser
dependency, two calls and concrete parse-error payload change. Three tests load
real Cargo/i18n files, cover Fluent and gettext, and verify malformed or
duplicate-key configuration errors retain their source path.

`i18n-config-manifest.patch` activates the package through the existing
`[patch.crates-io]` section. It has not been applied by this agent. The crate's
`HEPTA_PATCH.md` records provenance, compatibility limits and regression gates.
Run `just test -p i18n-config` and `just test -p codex-secrets`, then refresh both
lock systems and rerun the unchanged cargo-deny check.

## Remote candidate workflow

`scripts/ndu_tls_lock_candidate.py` now generates the complete ZIP/zstd/i18n
candidate and consumes it for actual workspace regressions. The shared recorder
and integrity checks are in `scripts/ndu_dependency_candidate_common.py`.

The producer requires a clean checkout at the exact event source SHA, verifies
the three fixed patch hashes, applies them with Git's index checks, resolves the
requested patched versions, checks the actual graph, runs `just bazel-lock-update`
and `just bazel-lock-check`, and emits all six changed file snapshots plus a
binary `candidate.patch`. Per-command logs retain actual exit codes, durations,
byte lengths and hashes; failed generation also retains partial file snapshots.

The three test jobs download that single artifact and verify the producer
RESULT hash passed through job outputs, source SHA, patch hash, all snapshots,
vendor input hashes and unchanged dependency policy. They use the producer's
artifact name, so rerunning a failed consumer job does not accidentally request
a nonexistent artifact with a newer attempt number.

The groups run `just test --locked --cargo-profile ci-test` in the full checkout:

- `plugins`: core-plugins, i18n-config, secrets.
- `storage`: http-client, rollout, app-server-protocol, thread-store.
- `core`: core's explicit request-compression filter.

Each attempted package keeps its own log and exit code. A failed test command
does not suppress the remaining package attempts, provided the bound candidate
tree is intact. Fresh JUnit files are copied per package; a prior package's stale
JUnit file is not relabeled after a later build failure. A failed test makes its
job fail. These jobs do not replace the unchanged cargo-deny or platform gates.

The CI preparation commit retains the original ZIP 2 production source in HEAD;
ZIP 9 source and its tests are applied only with the new manifests. YAML remains
outside this candidate. Eight local orchestration tests passed using real Git
binary patches and real success/failure subprocesses. They test artifact/source
tampering, unapproved policy paths, vendor/policy mutation, failed-command
evidence and leftover vulnerable dependency versions. This is CI guard coverage,
not Rust workspace regression evidence; see `REMOTE_PREFLIGHT.json` and its log.

## Current verification boundary

Source archives were matched to the official crate checksums. Exact dependency
constraints and default features were read from the published metadata, and
the production ZIP calls were inspected against ZIP 9.1.2 source. Patch syntax,
the LZMA fixture, and preservation of upstream i18n sources were checked without
creating a Cargo target or cache.

Full Rust compilation and behavioral test execution are pending the root
agent's remote candidate workflow. Local disk capacity was reserved for the
ongoing experiment archives, so no extracted-function smoke harness was used
as a substitute for workspace verification. These are prepared repairs, not
eight newly closed scan failures. No formatting or commit was performed by
this agent.
