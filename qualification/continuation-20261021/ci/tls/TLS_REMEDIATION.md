# TLS dependency remediation and cargo-deny root cause

## Result

Exact candidate base: `0cb777545966333a96be265a69d03c9982231bc7`. Two changed repository files: `codex-rs/Cargo.lock` and `MODULE.bazel.lock`. Real Cargo updates and real Bazel generation completed. The unchanged `just bazel-lock-check` passed; a repeated update left the generated lock byte-for-byte identical. Cargo-deny remains **failed with four maintenance advisories**, reduced from seven errors by closing all three new TLS advisories. No policy, ignore list, backend implementation, or gate was changed.

Patch: `/workspace/scratch/337c309bc660/hepta-ci-fix/tls-patch/tls-patch-upgrades.patch` (SHA-256 `6c4e6840a74eeb86369c4338d9fafbf2882eccacb9bbc1eba80d0a80280d190f`).

## Failed CI and reproduction boundary

PR #2968 head `f740aaef183e0c1724871189fe1d72fc5204a49d`, run `39523886175`, job `118974143841`: metadata identifies step 7, Run cargo-deny, as failed. The no-suppression policy step, installation, and clean-worktree check succeeded. Original job log retrieval repeatedly failed with Transport closed; generic log endpoints were unsupported. This report therefore supplies an **exact-source local reproduction**, not a purported downloaded copy of the failed job log.

The workflow pins EmbarkStudios/cargo-deny-action commit `82eb9f621fbc699dd0918f3ea06864c14cc84246`; its Docker image uses cargo-deny 0.19.0, and the workflow selects Rust 1.95.0. The baseline command was:

```sh
cargo-deny --locked --manifest-path codex-rs/Cargo.toml --all-features check --hide-inclusion-graph --show-stats
```

The RustSec database used was `e6f94f3760d5e6c54c1b05f204002263bc025524`. This database includes the three TLS advisories assigned on 2026-10-20; an earlier cached database can miss those findings. The relevant Cargo and Bazel lock inputs are identical between reproduced f740 and candidate base 0cb. Source snapshots, exact command logs, checksums, and package paths are retained in the audit directory.

| Advisory | Baseline crate | Candidate handling |
|---|---|---|
| RUSTSEC-2026-0382 | rustls-webpki 0.103.15 | Updated to 0.103.16 |
| RUSTSEC-2026-0383 | webpki-root-certs 1.0.9 | Updated to 1.0.10 |
| RUSTSEC-2026-0381 | webpki-roots 1.0.9 | Updated to 1.0.10 |
| RUSTSEC-2026-0374 | basic-toml 0.1.10 | Remains an error; reuse owner work after integration review |
| RUSTSEC-2026-0371 | zbus_names 4.3.4 | Remains an error |
| RUSTSEC-2026-0370 | zvariant 5.15.0 | Remains an error |
| RUSTSEC-2026-0372 | zvariant_derive 5.15.0 | Remains an error |

Both baseline and candidate report zero bans, licenses, and sources errors. Candidate advisories report exactly four errors. Existing warnings/notes remain subject to the original policy; none were suppressed to obtain this reduction.

## Existing owner comparison

PR #2961, head `c210d26350ac57e527b4ff59663e5c8d518ff95a`, already implements a checksum-verified i18n-config 0.4.8 maintained-TOML backport for the exact basic-toml path. Current path is `codex-secrets -> age 0.11.5 -> i18n-embed-fl 0.9.4 -> i18n-config 0.4.8 -> basic-toml 0.1.10`. That PR is the first reuse candidate. Its 60-file diff includes Cargo and vendor/source changes but no generated MODULE.bazel.lock; its author-reported local cargo-deny pass is not a full CI pass. Inventory refreshed it at 01:12:31 UTC: required CI still failed, Architecture succeeded.

PR #2917, head `9a9e3b2e9dabd6957594861208b49f275f273e84`, addresses the older keyring 3.6.3 / secret-service / zbus 4.4.0 path, with zbus_names 3.0.0 and zvariant 4.2.0. Current source instead reaches `keyring 4.2.0 -> zbus-secret-service-keyring-store 1.0.1 -> zbus 5.19.0`, through codex-keyring-store, codex-login, and codex-secrets. The old backend patch cannot be treated as covering the current major-version path. No backend permissions or credential-store behavior was changed in this candidate.

PR #2964 head `fad7f6b342e9a087bbc921862ba93f67b1873f51` fixes Bazel command exit status, not these dependencies. PR #2966 head `a2fb6e621787cdb9230dfd1350f82fb281d4ec91` changes HOS2 libc/pretty_assertions dependencies, not the TLS/basic-toml/zbus remedies. PR #2910 is a no-suppression policy guard. Searches found no explicit open-PR text owner for the three TLS advisories; that is a text-search result, not proof that no overlapping code exists.

## Real Cargo update and all additional resolver changes

Executed on exact 0cb with Cargo 1.95.0:

```sh
cargo update --manifest-path codex-rs/Cargo.toml -p rustls-webpki@0.103.15 --precise 0.103.16
cargo update --manifest-path codex-rs/Cargo.toml -p webpki-root-certs@1.0.9 --precise 1.0.10
cargo update --manifest-path codex-rs/Cargo.toml -p webpki-roots@1.0.9 --precise 1.0.10
just bazel-lock-update
just bazel-lock-check
```

All update commands exited zero. Cargo changed only the three TLS package versions/checksums. It also re-resolved nine dependency edges to an already locked windows-sys version. These are real resolver output, retained as generated rather than manually reverted:

| Unchanged parent package | Declared windows-sys requirement | Old edge | New edge |
|---|---|---|---|
| arboard 3.7.0 | >=0.52.0, <0.62.0 | 0.52.0 | 0.59.0 |
| errno 0.3.14 | >=0.52, <0.62 | 0.52.0 | 0.59.0 |
| is-terminal 0.4.17 | >=0.52, <0.62 | 0.52.0 | 0.59.0 |
| os_pipe 1.2.3 | >=0.28, <=0.61 | 0.52.0 | 0.59.0 |
| quinn-udp 0.5.16 | >=0.52, <=0.61 | 0.52.0 | 0.59.0 |
| rustix 1.1.5 | >=0.52, <0.62 | 0.52.0 | 0.59.0 |
| rustls-platform-verifier 0.7.1 | >=0.52.0, <0.62.0 | 0.52.0 | 0.59.0 |
| tempfile 3.27.0 | >=0.52, <0.62 | 0.52.0 | 0.59.0 |
| winapi-util 0.1.11 | >=0.48.0, <=0.61 | 0.52.0 | 0.59.0 |

All nine dependencies are `cfg(windows)` and both selections satisfy their declared ranges. Parent versions, sources, and checksums are unchanged. Exact feature selections are in `windows-edge-review.json`. This establishes resolver consistency; **native Windows runtime/build qualification has not been performed by this agent**, so it does not establish absence of Windows semantic changes.

## Bazel generation evidence

Bazel 9.3.0 official binary SHA-256: `d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8`. The local wrapper isolated output/cache directories and bounded the Java process, using the existing system Java truststore. It did not disable TLS verification or add a new trust root. The first attempt rejected an inapplicable resource flag; the next identified the embedded JDK truststore mismatch. After the existing system truststore was selected, a V8 repository materialization failure remained.

The pinned V8 archive matched SHA-256 `164f3d3e0a8b4c02a386d3a88d1b1133d37e5c20be0239fecdcdde414a4340d5`. It contained the required 6,248-byte file, SHA-256 `01b8d01a3fad28211c5a6d243ff3c9d2e90e9437dc2b125861fcec4a8b4a460a`; the failed external repository contained only an empty temporary directory. Native `bazel fetch --repo=@v8` successfully materialized the repository and the file hash matched. No source file was supplied by hand. The subsequent original update succeeded, and the unchanged original check succeeded.

The initially failing update had already written the final lock bytes. Those bytes were only accepted after the later complete successful update, a repeated successful update with identical hash, and a successful original lock check. The partial-attempt evidence remains available.

JSON semantic comparison shows exactly three old TLS facts removed and their three updated facts added under `@@rules_rs+//rs:extensions.bzl%crate`; **every other JSON value is identical**. Lock format remains 28. No manual lock edits were made.

## Final receipts and qualification

| File | SHA-256 | Bytes |
|---|---|---:|
| codex-rs/Cargo.lock | aa3efcad4d26d4ba8d5b8adbea793955acef36551f00da43ef7b03bbab3bfb5a | 417851 |
| MODULE.bazel.lock | 394f5d9cdcc1d9c96cebc357ad4635a01f0fa80f2e76a4d6665989343352f3ea | 1751659 |

A real Git index at exact 0cb was compared against all **9,057 tracked files**, including Git blob identities and executable/symlink modes: precisely those two files changed, with zero mode differences. `deny.toml` remains SHA-256 `17639b2e8539fd6192e2d5c86538c149b9c2e9237fc09ce4acc0c7828a588ac7`.

The parent is separately merging owner head `98b40cb04a23a36a07212ef7d826024f37536057` to preserve updated ancestry and repair event/base-merge identity alignment. The TLS candidate is anchored on 0cb, and its changes should be integrated with that merge and the separately owned native fix, followed by qualification of the resulting exact head. This report does not claim that future integrated head or the full platform matrix has already passed.

Next integration step: apply `tls-patch-upgrades.patch` to the parent's reviewed tree, verify the above two hashes, then run existing Memory/cargo-bin tests and strict Clippy against the updated dependency closure. Native Windows CI remains required. The original cargo-deny gate should continue to fail with the four recorded maintenance advisories until their owners' remedies are separately integrated and validated.

## Evidence index

- `/workspace/scratch/337c309bc660/hepta-ci-fix/tls-patch/validation.json`: combined commands, timestamps, results, file hashes, limitations.
- `/workspace/scratch/337c309bc660/hepta-ci-fix/tls-patch/source-conservation.json`: all tracked-file comparison against exact Git base.
- `/workspace/scratch/337c309bc660/hepta-ci-fix/tls-patch/cargo-updates.json`, `cargo-lock-delta.json`, `windows-edge-review.json`: full Cargo changes and nine edge details.
- `/workspace/scratch/337c309bc660/hepta-ci-fix/tls-patch/bazel-lock-delta.json`, `bazel-lock-final-verification.json`: generated Bazel facts and repeat/check receipts.
- `/workspace/scratch/337c309bc660/hepta-audit/ci/cargo-deny-2968-online.log`, `tls-cargo-deny-after.log`: actual baseline and candidate output.
- `/workspace/scratch/337c309bc660/hepta-audit/ci/cargo-deny-2968-paths.json`: actual current workspace dependency paths.
- `/workspace/scratch/337c309bc660/hepta-audit/ci/tls-bazel-lock-update-after-fetch.log`, `tls-bazel-lock-update-final.log`, `tls-bazel-lock-check-final.log`: successful original recipe output.
- `/workspace/scratch/337c309bc660/hepta-ci-fix/tls-patch/disk-cleanup.json`: task-owned regenerable caches removed only after server shutdown and all checks completed; source, locks, receipts, and logs preserved.
- `/workspace/scratch/337c309bc660/hepta-ci-fix/secondwave/validation.json`: separate cargo-bin hash reconciliation, proving tested `bd04b1b7...` bytes equal final `49287adb...` bytes plus exactly one trailing LF removed by `just fmt`.

The task-owned cargo-deny cache was also reclaimed after completion at the parent's request. Its seven original advisory inputs and database commit are preserved under `rustsec-inputs`; cleanup is recorded in `cargo-deny-cache-cleanup.json`. The patch passed `git apply --check --reverse` against the generated candidate.
