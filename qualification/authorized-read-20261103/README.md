# Local authorized-read capability consistency

Status: Draft / HOLD_NO_GO / DENY_ALL.

## Original failure and production change

The original Windows MSVC job `126096184676` in workflow run `41685992806`
fails the unchanged
`authorized_read_rpc_is_capability_gated_and_denies_outside_root` assertion:
the server returns JSON-RPC `-32600` where the unsupported capability path
requires `-32603`.

`LocalFileSystem` advertises stable-handle authorized reads only on macOS.
Its authorized-read implementation was also macOS-only, so other hosts
inherited the generic trait's stream fallback. That fallback can attempt
ordinary sandbox access even while this concrete implementation advertises
the operation as unsupported.

The narrow fix adds the complementary non-macOS trait implementation. It
returns the existing `Unsupported` error before any filesystem or sandbox
access. The macOS stable-handle implementation, capability flags, generic
trait fallback, RPC bounds validation and error mapper remain unchanged.
The initial production repair also preserved every original test.
The 17 added lines belong beside the existing trait
implementation; this is a correction to an existing platform contract.

The exact combined dependency parent is
`0b9da54535a7795b2433947a479e6d9e71525e0a`. Cargo manifests and both lockfiles
are unchanged.

## Actual local comparison

Both sides used Rust 1.96.0 and the same original command:

```sh
just test --locked -p codex-exec-server --test authorized_read_rpc --no-tests=fail --retries 0
```

The original source timed out its one test at the original 60-second limit
(exit 100, zero passed, zero skipped). The candidate passed the exact same
test and every original assertion (one passed, zero skipped, 0.069 seconds
test execution). This is a Linux comparison. The original Windows failure
has a different observed error. The subsequent exact native Windows run
below now confirms its original RPC assertion passes.

The original scoped `just fix --locked -p codex-exec-server` completed with
exit 0 and did not change source. Its two existing deprecated-API warnings
in another crate remain in the complete log. A first prerequisite attempt
with an incorrect local pkg-config directory failed before testing and is
also retained. An independent local probe found TCP loopback available and
Unix socket creation denied; no sandbox environment override was used.

`local-evidence.zip` retains complete command logs, before/after input hashes,
both original JUnit reports, the local command driver, prerequisite results
and the independent read-only review. `local-evidence.json` binds every
member and the archive by SHA-256. These local results do not establish the
complete hosted filesystem suites.

The original complete Windows job log is already preserved losslessly at
the immutable V8 repair commit:

- Repository: `TrillionniumFoundation/hepta-private-ci`
- Commit: `84424d4a35153aa5ab5b1cc778e2e80be6d411e4`
- Path: `qualification/v8-allocator-20261103/windows-shard-3-original.log.gz`
- Compressed SHA-256:
  `e0179e59d4b3db1d33aa1ad6e609a64c006e6d650665671542cf3484b7b6991f`
- Original 2,118,755-byte log SHA-256:
  `a3817ccb5611322925b5f9d7eab434faaba1e3434d5ac9962ee27ca346e1b402`

## Original hosted qualification

The workflow checks out its exact candidate and uses the repository's
authenticated native Windows MSVC, Linux and macOS Bazel setup with the
original 30-minute budget. It executes these complete original targets
without cached test results or case filters:

```text
//codex-rs/exec-server:exec-server-authorized_read_rpc-test
//codex-rs/exec-server:exec-server-unit-tests
//codex-rs/file-system:file-system-unit-tests
```

It requires actual original per-suite counts, zero failed/ignored/filtered
cases and successful XML, and runs the corresponding original Clippy
targets. The RPC is an unsharded test covered by the original package glob;
the two unit suites use the original manual test binaries. Linux first
checks the committed Bazel lock. All hosts use the existing wrapper's
top-level output download option so complete test XML is materialized.

The workflow passes its real absolute Bash executable, including native
Git Bash on Windows. A fresh output directory prevents stale evidence
reuse. Full stdout/stderr, test logs/XML, exact input hashes and final
before/after comparison are retained even when a later command fails.

Hosted results must be independently checked against the exact commit.
This change does not close unrelated Windows failures, full blocking CI,
private-state, security, performance or scientific obligations. No original
test, assertion, capability or budget is weakened.

## Retained native results and fixture follow-up

Run `41710889184` used exact production commit
`ae2876036274e3be07af122fb80cb3d18acf92d5`. Its complete original artifacts
are retained byte for byte in `original-negative/`:

| Native host | Artifact | Original RPC | Complete exec-server unit suite |
| --- | --- | --- | --- |
| Linux | 13266619365 | 1 passed | 260 passed, 1 failed |
| Windows MSVC | 13266689342 | 1 passed | 251 passed, 1 failed |
| macOS ARM64 | 13267774672 | 0 passed, 1 failed | 271 passed, 4 failed |

All three complete unit suites had zero ignored, measured or filtered cases.
The separate original file-system target contains zero Rust test cases;
its wrapper did execute successfully on every host. The Windows wrapper
prints no Rust summary for this empty target. Counting it as positive Rust
coverage, or requiring a positive case count from it, would be incorrect.
The runner now accepts only that exact empty-target contract while retaining
the original execution and successful, non-skipped XML requirements.

The independent `verify_original_negative.py` replays all three ZIP
identities and CRCs, every output hash, 182 exact immutable Git input paths
per host, before/after equality, original uncached target commands, complete
Rust counts, precise failed case sets, and wrapper XML results. Linux's
committed lock check passed first. Each original target command exited 3;
Clippy was not reached on these failed runs. These are retained failures,
not complete native acceptance.

The macOS positive fixtures mixed logical temporary roots with the physical
path returned by the existing stable-handle implementation. The follow-up
creates its own temporary directories beneath the canonical temporary
parent and derives all owned allow roots, targets and deny globs from the
same physical namespace. The RPC fixture similarly canonicalizes only its
owned macOS temporary root. Production policy interpretation stays exact;
no arbitrary user policy root, symlink, hardlink or denied path is relaxed.
All original authorization and attack assertions remain.

All three native unit suites also exposed the original stalled-response
fixture writing its response before reading the actual POST request. The
follow-up drains the request headers and declared body through one
4,096-byte total read bound before sending the same partial response.
The original 50-millisecond request timeout, one-second server hold and
`is_timeout()` predicate remain. No production HTTP code changed. This
retains the original timeout test contract; there is no additional
server-phase handshake that would prove its timing under arbitrary scheduler
delays.

The exact original local selected regression then passed with seven input
hashes unchanged, exit 0, and 36.6234 seconds including compilation. Its
selection deliberately excludes the other 260 tests and is not a whole-suite
result. Scoped `just fix --locked -p codex-exec-server` and `just fmt`
subsequently exited 0 without changing those inputs; the two pre-existing
deprecated-API warnings remain in the full log. No Rust tests were rerun
after formatting. `fixture-evidence.zip` retains these original logs and
receipts, the earlier single-read trial, and independent read-only reviews.

The following command verifies the retained originals without executing
their code:

```sh
python3 qualification/authorized-read-20261103/verify_original_negative.py \
  --repository . \
  --artifacts qualification/authorized-read-20261103/original-negative \
  --output /tmp/authorized-read-original-negatives.json
```

The follow-up must pass the same complete original RPC, unit, empty-wrapper
and Clippy targets on all three native hosts at its own immutable commit.
The original 30-minute job budgets remain unchanged.
