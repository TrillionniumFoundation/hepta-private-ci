# Parent convergence, migration-15 fixture and TLS lock repair

Observed on 2026-10-21 UTC. This follows PR #2968 source
`0cb777545966333a96be265a69d03c9982231bc7`.

## Preserve the current integration owner

The parent owner #2944 advanced from `603238ba4721b2e9656c4647ce41c5f1664c1154`
to `98b40cb04a23a36a07212ef7d826024f37536057`. Its 18 paths contain four
code-mode-host runfiles repairs, five Windows fixture repairs and nine UI
qualification paths. They are disjoint from this branch's repairs and are
preserved byte-for-byte with their source ancestry.

The automatic merge tree is `cc6170562020d8271196cbdf9d0e71fde7955ded`, exactly
matching GitHub's prospective merge `6b074e52621d77338112f02119beb0cb1a6f869f`.
Architecture job `118980327865` failed before testing while checking prospective
merge parents/tree: the event still supplied the old base while the observed
merge object's first parent was the updated owner. The job did not print its
comparison values; identifying the specific failed assertion at job time is an
inference from that original log and the retained merge object. The equality
checks are retained. This commit preserves both parent histories and requires
fresh source-head and current-base merge qualification.

## Existing migration fixture repair

The real locked Memory library test on f740 failed with 271 passed, one failed
and seven pre-existing ignored tests. An exact 0cb focused run reproduced the
failure: the migration ledger contained versions 1 through 15 while the fixture
expected only 1 through 14.

This commit applies the existing owner #2743's two-line fix from
`4290ec6480944af84646e8846dfe5e3dc5e73f81`. Its full postimage has Git blob
`dc6ae36263e1aab8c5c83e13649892ae9d3112c2`. An ordered inner SELECT makes the
group-concat order explicit, and the expected history includes migration 15.
The Memory/citation/head preservation, legacy projection revocation and header
identity assertions are unchanged. No production migration is altered.

## Actual dependency and Bazel lock updates

Three actual `cargo update -p PACKAGE --precise VERSION` commands upgraded:

| Package | Before | After |
| --- | --- | --- |
| rustls-webpki | 0.103.15 | 0.103.16 |
| webpki-root-certs | 1.0.9 | 1.0.10 |
| webpki-roots | 1.0.9 | 1.0.10 |

Cargo also selected the already present windows-sys 0.59.0 in place of 0.52.0
for arboard, errno, is-terminal, os_pipe, quinn-udp, rustix 1.1.5,
rustls-platform-verifier, tempfile and winapi-util. Those parent versions,
sources and checksums are unchanged; their declared ranges admit the selected
version. These nine Windows edges still need native Windows qualification.
The generated lock was not manually rewritten to hide resolver changes.

The pinned Bazel 9.3.0 ran the original `just bazel-lock-update`. After resolving
an incomplete V8 external-repository materialization with native `bazel fetch`,
generation completed successfully; the second generation was byte-identical,
and the original `just bazel-lock-check` passed. The lock format remains 28.
Independent structural comparison confirms that only the three TLS package
facts changed in MODULE.bazel.lock. All 1,516 Cargo package records are otherwise
identical apart from the explicit three upgrades and nine Windows edges.

Final lock SHA-256 values:

- Cargo.lock: `aa3efcad4d26d4ba8d5b8adbea793955acef36551f00da43ef7b03bbab3bfb5a`
- MODULE.bazel.lock: `394f5d9cdcc1d9c96cebc357ad4635a01f0fa80f2e76a4d6665989343352f3ea`

Actual cargo-deny 0.19.0 with `--locked --all-features check` reduced seven
advisory errors to four. The remaining basic-toml, zbus_names, zvariant and
zvariant_derive unmaintained advisories still fail the security gate. No ignore,
lint, test skip, feature removal or permission relaxation was added.

## Final native qualification and limits

The final local candidate was the combined tree above plus the two generated
locks and the existing fixture repair, working-diff SHA-256
`99ba4b1d81447b477e44bf414f8da398739746f74b591c3e30a8b31385a232a1`.
The source and both locks were checked before and after each command.

- `just test -p codex-hepta-memory --lib --locked`: **272 passed, 0 failed,
  7 pre-existing ignored**. The seven ignored qualification, stress and
  crash/target-host probes are not certified by this run.
- `just test -p codex-utils-cargo-bin --locked`: **2 passed, 0 skipped** in the
  actual locked workspace, beyond the earlier isolated harness.
- Scoped strict Clippy for both packages: **exit 0**, retaining the repository's
  disallowed-method and production lint policy.
- Subsequent `just fmt` and `git diff --check`: **exit 0**, no candidate-byte
  changes. Tests were not repeated just for formatting.

The runtime was Linux x86_64, Rust/Clippy 1.95.0, with two Cargo build jobs and
an isolated target/cache. Low disk-space observations were retained; the final
commands completed successfully and are not labelled ENOSPC failures. Only
this task's reproducible caches/install archives were reclaimed, with hashes;
other worktrees and processes were preserved.

This is scoped local qualification, not full native Windows/macOS/Bazel/V8,
UI, architecture or production acceptance. Current required checks and the
remaining dependency maintenance migrations remain blocking. Research remains
SHADOW_ONLY / DENY_ALL / NO_GO.
