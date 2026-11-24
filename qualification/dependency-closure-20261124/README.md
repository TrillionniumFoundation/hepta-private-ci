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
