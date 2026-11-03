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
trait fallback, RPC bounds validation, error mapper and every original test
remain unchanged. The 17 added lines belong beside the existing trait
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
has a different observed error and still requires actual Windows validation.

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
