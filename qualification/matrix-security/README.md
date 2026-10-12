# Matrix SDK P0 security migration: fail-closed prerequisites

This is **not a remediation** of the open Cargo advisory failures; it is a
read-only guard against false remediation. It does not grant production access,
ignore advisories, reduce `cargo-deny` coverage, disable end-to-end encryption,
remove Matrix support, or change a trust root. The existing global `cargo-deny`
remains a separate mandatory failure until the actual dependency graph is safe.

## Matrix family graph integrity guard (2026-10-12)

The prerequisite checker now rejects SDK/Base/Crypto/SQLite **mixed major.minor
families**, missing or duplicated component versions, and graph entries that
claim a safe component without an actual path from the selected `matrix-sdk`.
This closes a false-green case where a synthetic graph advertised Crypto 0.19
but still contained a Base or SQLite 0.18 package. Patch revisions within one
minor family need not be identical.

`static_graph_advisory_candidates_clean` means only that the audited lock
structure satisfies these offline *candidate* conditions. The stronger
`security_advisories_resolved` is always `false` in this static tool, even
for an artificial all-0.19/AnyMap3 fixture. Only real unchanged `cargo deny`,
approved pinned source, Matrix E2EE and actual SQLite WAL crash/recovery runs
can establish remediation. None are bypassed by these new unit tests.

## Confirmed evidence on the 2026-10-12 research HEAD

- `codex-rs/Cargo.toml` pins `matrix-sdk 0.18.0` with **both** `e2e-encryption`
  and `sqlite` features. The exact `Cargo.lock` graph includes
  `codex-hepta-matrixd -> codex-hepta-matrix-sdk -> matrix-sdk -> anymap2 0.13.0`.
- `matrix-sdk-crypto 0.18.0` is loaded through `matrix-sdk-base` and
  `matrix-sdk-sqlite`. RustSec **RUSTSEC-2026-0318** is fixed in crypto **0.19.0**
  and later: <https://rustsec.org/advisories/RUSTSEC-2026-0318.html>.
- RustSec **RUSTSEC-2026-0319** marks `anymap2` as unmaintained, recommending
  `anymap3`: <https://rustsec.org/advisories/RUSTSEC-2026-0319.html>.
  Matrix SDK **0.19.1** still lists `anymap2` as a direct dependency, so **a
  version bump alone cannot remove the advisory**:
  <https://docs.rs/crate/matrix-sdk/0.19.1/source/Cargo.toml>.
- Matrix SDK **0.19.1** declares `rust-version = "1.96"`, while Hepta's
  `codex-rs/rust-toolchain.toml` currently pins `1.95.0`.
- Hepta's 0.18 SQLite adapter is locally patched to use `rusqlite 0.39`
  and the `libsqlite3-sys 0.37` WAL-reset fix, so changing the upstream
  `matrix-sdk-sqlite` release also requires a **new actual storage migration**.

### Remaining safe implementation path

1. Freeze actual upstream 0.19.x source and versions. Migrate Rust toolchain
   coherently across Windows/macOS/Linux and strict Clippy/format checks.
2. Replace Matrix SDK's use of `anymap2` with an independently reviewed and
   reproducibly pinned `anymap3` migration **in source**, or consume a future
   upstream SDK release that no longer depends on `anymap2`. Merely patching the
   package name while retaining unmaintained code is not a fix.
3. Upgrade the **entire Matrix SDK family** (SDK/base/crypto/SQLite and related
   dependencies), removing vulnerable crypto 0.18; update the SQLite compatibility
   patch with real libsqlite3 linking and WAL crash/restart verification.
4. Retain SDK session-key, E2EE decryption/encryption, scope isolation,
   homeserver restart, checkpoint replay, durable outbox, to-device messages,
   verification missing cross-signing keys, and full `real_synapse_e2e` tests.
5. Run `cargo update`/`--locked`, refresh `MODULE.bazel.lock`, and get **new
   exact-SHA** Rust, Bazel, cargo-deny, cross-platform and E2EE receipts before
   removing the Matrix P0 blocker. Keep P1–P4 production admission closed.

### Usage

```
python3 qualification/matrix-security/matrix_dependency_gate.py --root . --output /tmp/matrix-p0-report.json
python3 qualification/matrix-security/matrix_dependency_gate.py --root . --require-safe
python3 -m unittest discover -v -s qualification/matrix-security -p 'test_*.py'
```

`--require-safe` deliberately exits nonzero on the current lockfile. Even when
static prerequisites eventually pass, the resulting report will continue to set
`cargo_deny_verified=false`, `matrix_e2ee_verified=false`,
`sqlite_wal_recovery_verified=false`, and `production_authorized=false`;
independently signed runtime/CI evidence must establish those claims.

## Pinned upstream compatibility candidate (separate from released 0.19.1)

A read-only review of the **Git source** at commit
`b3c07ea6ba6e8e46e30811c0500b04505c4be9f9` shows:

- `matrix-sdk` source still advertises `0.19.1`, but now uses `anymap3` instead
  of `anymap2`. This is a **pinned, not-yet-qualified Git tree**, not a claim
  that crates.io `matrix-sdk 0.19.1` has changed. No source is executed.
- `matrix-sdk-crypto` source is `0.19.1` and the upstream workspace requires
  Rust `1.96`. The SQLite crate uses `rusqlite 0.40.2`, which itself depends on
  `libsqlite3-sys 0.38.2`; Hepta still pins `0.37` via its SQLx 0.9 family.
- The distinct `upstream_source_probe.py` checks exact Git SHA, no `anymap2`,
  crypto version, MSRV and SQLite versions against local Hepta bindings. Its
  status remains `migration_ready=false` even if all upstream manifests pass.
- Do not patch Cargo.lock to point to this Git source without separate
  source-review, reproducible dependency resolution, SQLite `links` alignment,
  native compile, E2EE conformance and actual WAL recovery evidence.

## Disposable Cargo resolver experiment (not a safe migration)

The optional diagnostics build a **detached temporary Git worktree** at the
exact PR source SHA; `staged_resolution_probe.py` changes only the temporary
`codex-rs/Cargo.toml` dependency from published `matrix-sdk 0.18.0` to the
exact pinned upstream Git revision. It then runs **Rust 1.96 Cargo metadata
resolution only** (no unreviewed upstream build scripts, compiler invocation,
login or live Matrix network integration) and records an artifact containing
resolved crate versions or the genuine resolver error. The Git worktree is
removed afterward, and the original tracked repository is checked unchanged.

A successful graph resolution still does **not** prove crypto safety, E2EE
correctness, SQLx SQLite single-`links` compatibility or WAL crash recovery.
Neither diagnostic job may clear the separate fail-closed security gate.

## Smallest reviewable AnyMap source delta (2026-10-12)

The previous immutable candidate `b3c07ea6ba6e8e46e30811c0500b04505c4be9f9`
is **278 upstream commits ahead of** the signed `matrix-sdk-0.19.1`
release commit `b18166c68bb958a21f0bca8b2d8320cb53583362`.
Those 278 commits cannot be treated as a reviewed one-line dependency fix.

Upstream's exact `anymap2 → anymap3` change is commit
`9c5fdd2cf5be1b7b8b20541e56d7a109db968534`
([upstream diff](https://github.com/matrix-org/matrix-rust-sdk/commit/9c5fdd2cf5be1b7b8b20541e56d7a109db968534)).
That commit changes only `Cargo.lock`,
`crates/matrix-sdk/Cargo.toml`, and
`crates/matrix-sdk/src/event_handler/mod.rs`. Its source-only hunk set
is much narrower than blindly upgrading to upstream's moving Git tip.

`minimal_backport_probe.py` verifies exact release and change commit SHAs
and checks that upstream changed *only those three files*. The upstream raw
manifest hunk has later dependency context that the signed 0.19.1 release
does not have (including `assert_matches2`); the raw hunk is therefore
evaluated **separately** and its failure cannot justify importing 189 or 278
unrelated upstream commits. The probe extracts exactly **four AnyMap
substitution blocks** (one manifest block and three event-handler blocks)
from the two source files, rejects any additional source mutation, translates
only those substitutions onto exact release bytes, and runs `git apply --check`
against the **unaltered** release. Its report binds
both original and release-specific patch SHA-256 values and both check results.
It does not cherry-pick, execute external code, change any Cargo dependency,
or declare the patched tree trustworthy. The job fails if the minimal
release-specific patch cannot apply; the independent hard security gate
remains red.

```sh
python3 qualification/matrix-security/minimal_backport_probe.py \
  --release /read-only/matrix-sdk-0.19.1 \
  --migration /read-only/matrix-anymap3-9c5fdd2 \
  --output /scratch/minimal-backport-evidence.json
```

This source experiment must be followed by real signed-source review,
compatible **entire SDK family** resolution, Rust toolchain approval, SQLite
`links` migration, E2EE and WAL crash recovery before `cargo-deny` and
production authorization can become eligible. A source-only patch applying
cleanly does **not** show it compiles or repairs the Matrix vulnerabilities.

## Verified workflow startup and isolated, actually applied source candidate

The Matrix research workflow formerly failed before spawning any job because
`jobs.disposable-cargo-resolution-probe.env.STAGE` referenced
`${{ runner.temp }}`, which GitHub Actions does not allow at job scope.
It now stages to a uniquely named **sibling** of
`${{ github.workspace }}` using only permitted `github` and `matrix`
contexts. `test_workflow_context_contract.py` protects the fix and verifies
that `--require-safe` is still mandatory. Successful workflow parsing is NOT
a security advisory waiver.

`disposable_backport_probe.py` builds upon the strict read-only source probe.
After checking the exact published-release and exact upstream migration SHAs,
it clones the pinned 0.19.1 release with **no hardlinks** into a previously
nonexistent, separate candidate directory, applies only the verified two-file
AnyMap3 source patch there, checks the changed file inventory, and confirms
the original source checkouts and Hepta workspace remain unchanged. It cannot
replace `Cargo.lock`, publish a model, or issue any production authorization.

The CI then uses Rust 1.96 in that **disposable candidate** for a genuine
`cargo metadata` resolution. The resulting diagnostic records the actual
exit code, resolved `anymap2/anymap3` and `matrix-sdk-crypto` versions, and
explicitly marks Hepta integration, E2EE, WAL and `cargo-deny` as unverified.
If the graph fails or still contains the vulnerable dependency, the candidate
qualification fails; the independent no-waiver security gate remains blocked
until the **real Hepta** graph is remediated and fully tested.

This is source-identity checking, **not** independent cryptographic release
signature verification or proof that the upgraded SDK's behavior is safe.

## Isolated SQLite dependency resolution: two non-promoting arms

The `staged_resolution_probe.py` accepts only
`retain_legacy_sqlite_patch` and `use_upstream_sqlite`. The former exposes
whether the 0.18 local SQLite fork blocks the pinned 0.19.1 Git SDK; the latter
removes **only** that exact fork line inside a separate detached Git worktree,
allowing Cargo to expose the genuine `rusqlite/libsqlite3-sys` alignment
problem. Each arm retains E2EE, `sqlite`, and the unchanged real
`deny.toml` and source `Cargo.lock`; neither is a remediated production
configuration. Reports include the arm, actual resolver exit code and
dependency versions, and remain `production_authorized=false`.

## Exact obsolete async-trait lock repin in isolated diagnostics

The pinned Matrix 0.19.1 candidate currently requires `async-trait ^0.1.92`,
while Hepta's existing `Cargo.lock` contains `async-trait 0.1.89`. The genuine
disposable resolver log first failed on this specific stale transitive lock;
neither that failure nor a future successful lock update is an advisory waiver.

`isolated_lock_repin_probe.py` is a **read-only classifier**. It requires all
of the following before authorizing the *diagnostic job* to attempt anything:

- Exactly the observed Cargo `async-trait` selection conflict with
  Matrix SDK `0.19.1`, minimum `0.1.92` and tonic's locked `0.1.89`.
- The exact audited Git revision
  `b3c07ea6ba6e8e46e30811c0500b04505c4be9f9`, both
  `e2e-encryption` and `sqlite`, and `default-features = false`.
- Exactly one stale `async-trait 0.1.89` package in the *disposable* lock.

Only then does the CI run `cargo +1.96.0 update -p async-trait --precise
0.1.92` with `--manifest-path` **under the detached temporary worktree**,
followed by another real `cargo metadata` resolution. The first and second
errors, update status, lock/manifest digests, and resolved versions remain
separate diagnostics; none is copied into the real repository.

The next conflict may be another stale lock, incompatible SQLite
`libsqlite3-sys` versions, an upstream MSRV constraint, or a source API
break. A successful metadata pass is only evidence of dependency resolution,
**not** evidence of an audited Rust upgrade, stable Cargo/Bazel locks, clean
`cargo-deny`, safe E2EE, WAL recovery, or production fitness.

The hard `matrix_dependency_gate.py --require-safe` remains mandatory and
fails independently until the real source graph and runtime are remediated.


## Next prerequisite: isolated upstream anymap3 candidate actually compiles

The Matrix hard-gate workflow now has `minimal-backport-native-compile`,
which runs **only after** the pinned-release source-profile job succeeds.
It stages the exact minimal AnyMap3 patch in `$RUNNER_TEMP`, installs Rust
1.96, resolves the staged dependency graph, **rejects any resolved
`anymap2` or `matrix-sdk-crypto <0.19`**, and runs a genuine
`cargo check --locked -p matrix-sdk --lib --no-default-features
--features e2e-encryption,sqlite` against the disposable candidate.

The job records the compiler exit status and source-patch evidence. It does
**not** touch Hepta's real Cargo manifest, Cargo.lock or Bazel lock, and never
sets a successful `cargo-deny_verified`, `e2ee_runtime_tested`,
`sqlite_wal_recovery_tested` or `production_authorized` flag.
A successful **upstream compilation** can justify moving to an independent
Hepta integration branch for API adaptation and SQLite links/WAL recovery;
it cannot unblock the production Matrix hard gate by itself. A failed source
checkout, resolver or compiler remains a failed candidate test, with no
fallback to the 278-commit unreviewed upstream tip.
