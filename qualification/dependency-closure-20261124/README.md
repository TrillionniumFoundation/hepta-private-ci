# Dependency closure qualification, 2026-11-24

Base: `9dd2aa27a66ce951b56d9a89614067c55b1dfa3c` (PR #7065), stacked on
`07c8994f2402a58f6b59eb648c801fc40c6e2b96` (PR #6995).

## Cookie patch

The dependency locks select `cookie` 0.18.3, the upstream fixed release for
[RUSTSEC-2026-0594](https://rustsec.org/advisories/RUSTSEC-2026-0594.html).
The patch changes neither the enabled cookie features nor the audit policy.
The Cargo package checksum is
`d55f2d6c30eeec7d5c6f98bd4395d4abb1895629eab97ee6522d340623615f8a`.

The original hosted #6995 audit reported 14 advisories. A fresh audit on
2026-11-24 reports 15 before this patch because the cookie advisory was published
after that hosted run. With the same database and options, the patch removes
the cookie finding and leaves 14 findings requiring separate migrations.
It does not make the overall dependency audit pass.

### Actual validation

Environment: Linux x86_64, Rust/Cargo 1.95.0, cargo-deny 0.19.0,
cargo-nextest 0.9.103, Bazel 9.0.0. Debug information was disabled and Cargo
parallelism bounded to two jobs. No live credentials or cloud service were used.

| Check | Result |
| --- | --- |
| `cargo update -p cookie --precise 0.18.3 --offline` | Updated one package |
| `cargo-deny --locked --all-features --format json check --hide-inclusion-graph --show-stats --disable-fetch` | Advisory errors 15 to 14; bans, licenses, sources each zero errors |
| `just test --locked -p codex-http-client --lib` | 83 passed, 0 skipped; compilation 33.68 s, test execution 2.239 s |
| `bazel mod deps --lockfile_mode=update` | Generated the matching cookie fact in `MODULE.bazel.lock` |
| `just bazel-lock-check` | Passed with the repository's unchanged check script |

The fixed audit database commit is
`1d328b6bb9f2f350bf65c1c81ab68781cb9e018a`. The CI action passes
`--all-features`; qualification uses that option even though `deny.toml` has a
different default. The audit exit code remains 1 because of the 14 remaining
findings.

The first consumer build ran out of local disk space before tests started.
After reusing the already populated Cargo target directory, the command above
completed successfully. The disk failure is not counted as a failed test.

The container's Bazel embedded JVM initially rejected the network certificate
chain. The successful run points Java at the container's existing system trust
store using `--host_jvm_args=-Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts`.
TLS verification stays enabled; no certificate or environment configuration is
committed. Bazel printed existing direct-dependency version warnings for
`platforms` and `rules_cc`; the lock check still exited successfully.

### Evidence digests

| Material | SHA-256 |
| --- | --- |
| Cargo lock at cookie stage | `1caa49bb8da1211e75d727f8b5c4078fd67205a822adc9165d5faf0f003e3759` |
| Bazel lock at cookie stage | `2e473f601ad36aff5999f08605efc6d2bc610231c9d726e685f6dbe79ae507ff` |
| Successful consumer test log | `08443005d03ede2eab882f06e3b5191bdd61de89e43856d3fe4e9518b300bf69` |
| Post-patch cargo-deny JSONL | `29f38a4d214075e0dea19324a19b2d844bc1dad5bc2083343d4d4b4ac421e06d` |
| Successful Bazel lock-check log | `f4165b25e055e96abe88fb257f2af543d81ec250236e37c9ad111817b8243c58` |

## AWS, pinning utilities, SQLite, YAML, and Secret Service

The integration stage selects the following maintained upstream versions:

| Dependency | Selected version | Purpose |
| --- | --- | --- |
| `aws-config` | 1.13.3 | Moves its signing dependency to `p256` 0.14 and `crypto-bigint` 0.7.11, fixing RUSTSEC-2026-0387 |
| `hyper` / `loom` | 1.11.1 / 0.7.3 | Removes the remaining `pin-utils` dependency, fixing RUSTSEC-2026-0441 |
| `sqlx` | 0.9.1 | Permits the patched native SQLite library |
| `libsqlite3-sys` / `rusqlite` | 0.39.1 / 0.41.1 | Shares one native SQLite library between SQLx and the existing Matrix SDK patch; fixes RUSTSEC-2026-0459 |
| `yaml_serde` / `libyaml-rs` | 0.10.7 / 0.3.0 | Replaces the unmaintained `serde_yaml` / `unsafe-libyaml` chain, fixing RUSTSEC-2024-0449 |
| `keyring` | Upstream 3.6.3 source with the documented local transport backport | Preserves the existing platform backends and credential behavior while selecting official stable Secret Service 6.0.0 and zbus 6.5.0 |

The existing Matrix SDK 0.18 SQLite patch only advances its `rusqlite` version
constraint. The first-party database schemas and recovery logic are unchanged.
AWS's selected Smithy packages require `serde` 1.0.229 or newer; SQLx 0.9.1
requires `time` 0.3.48 or newer. Secret Service's new runtime graph requires
`futures-core` 0.3.34, `rustix` 1.1.5 or newer, and `socket2` 0.6.5. The lock
updates the futures family to 0.3.34 and selects rustix 1.1.6 / socket2 0.6.5.
These are required compatibility updates, not changes to application behavior.

With the same cargo-deny 0.19.0 command and fixed advisory database, the
**pure-Rust Secret Service plus YAML stage reports 7 advisory errors**, down
from 15 at the base. Bans, Cargo licenses, and sources each report zero errors.
The retired `zbus_names`, `zvariant`, and `zvariant_derive` findings and
`unsafe-libyaml` are absent. Metadata may still list weak optional dependencies
because of [Cargo issue 10801](https://github.com/rust-lang/cargo/issues/10801);
the audit result and actual selected build graph determine active dependencies.

The remaining findings are RUSTSEC-2026-0319 (anymap2), RUSTSEC-2026-0543
(chrono), RUSTSEC-2026-0318 (matrix-sdk-crypto), RUSTSEC-2026-0588 / 0589
(ruma-identifiers-validation), and RUSTSEC-2026-0451 / 0510 (vodozemac).
The audit exits 1. Complete blocking CI is not yet qualified.

### Native dependency decision

An intermediate Linux synchronous Secret Service experiment used vendored
`libdbus-sys` 0.2.7. Its native source was DBus 1.14.4, with AFL-2.1 or
GPL-2.0-or-later licensing not represented by the Cargo crate's MIT metadata.
That experiment was rejected as the final migration. The final production
change restores both consumers' original platform feature selections and uses
Secret Service 6's pure-Rust zbus transport on Linux. It adds no vendored native
libdbus dependency. The existing BSD synchronous backends are unchanged.
A zero-error Cargo license audit is not represented as a full native-source
license audit.

The local `keyring` package keeps its original name and version. Its ten Rust
implementation files and four provenance/license files are byte-for-byte pinned
in `third_party/keyring-3.6.3/UPSTREAM-PINS.json`. Only its normalized manifest,
Bazel integration, and qualification documentation are adapted. See
`third_party/keyring-3.6.3/HEPTA-PATCH.md` for the upstream release and retirement
path. The dependency audit includes this package without an advisory exclusion.

### Actual validation and limits

- At the AWS/HTTP stage, `just test --locked -p codex-aws-auth -p
  codex-http-client --lib` passed **88 tests, zero skipped**. Five AWS tests
  exercise SigV4 signing, preserved headers, session tokens, invalid
  configuration, and error classification. Compilation took 49.05 seconds;
  tests took 2.308 seconds, using synthetic values. This run predates the later
  Secret Service runtime dependency updates and is not claimed as a rerun of
  the final integration graph.
- The YAML migration compared the old and new parsers on **144 identical
  inputs**, covering non-string keys, tagged values, aliases, duplicate fields,
  scalar coercion, floating-point representation, and merge syntax. All
  comparisons passed. Seven first-party regression functions cover the four
  consumers. `libyaml-rs` contains unsafe code; no memory-safety claim is made.
- The final pure-Rust stage's Cargo metadata and `cargo-deny --locked
  --all-features` completed on Rust 1.95.0. `just bazel-lock-update` regenerated
  the matching Bazel 9 lock, and `just bazel-lock-check` passed against that lock.
  The original policy and command are unchanged.
- Local `codex-state` and `codex-secrets` consumer builds exhausted disk space
  before test execution. Those commands are uncompleted validations, not
  passing tests or assertion failures. No repeated cold build was used to hide
  that limitation.
- The synthetic keyring interoperability workflow builds the unmodified
  registry 3.6.3 baseline and the actual path-backed production consumer. Its
  isolated encrypted Secret Service fixture covers interoperability, missing
  and locked entries, ambiguity, explicit keyutils cache recovery, and rollback
  after a backing-store write failure. Local socket creation was unavailable;
  the new zbus 6 implementation still requires its normal Linux CI run. No real
  credentials, user bus, or user keyring are accessed.
- GNU fixture corrections separately restore the historic automation schema,
  update the cognitive-memory migration ledger expectation, and supply genuine
  OpenSSH to the trust tests. The automation DDL was replayed successfully
  against SQLite; Rust and Bazel qualification remains with normal CI.

No advisory rule, license allowance, target audit filter, authorization gate,
or required test has been removed. The native trust tests execute locally with
OpenSSH supplied; they are not ignored or replaced by mock signature checks.

### Pure-Rust stage evidence

The following hashes identify the measured stage; a later Matrix/chrono
integration must rerun the gates against its own complete head.

| Material | SHA-256 |
| --- | --- |
| Cargo lock | `a23361c13de44ef64fab8efa0cf140bd2960ac3d92037b20dc6237b39c0be79f` |
| Bazel lock | `1fe5c578c14e3d0f106703fae0e87583b41b25719954a51dff871e3d7c730717` |
| cargo-deny JSONL | `9f1c3a96b087d80beefbdbba073e20bd0cde5df42f41b8af3658e2d8bd3ee6d3` |
| Bazel lock-update log | `9b601e0d2d2d6b24b1c782436ce28f5d7775f2d7e725d26235403dffd6369312` |
| AWS/HTTP consumer log | `b1638667065bbd0c27fa9ec6cec77525723bd7adb25f34cf1d23d8bdb0277d89` |
