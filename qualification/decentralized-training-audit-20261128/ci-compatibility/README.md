# CI compatibility repair evidence

This package records a narrow repair to five existing verification files, based
on `1383c6f4cdd271bc8eabffe664892b9b5e878749`. Its source candidate is
`f74d0ccde0ac0ad9e1a9819a3bdec4d08ce39919`, tree
`76ce2459c31f9f84c30ad8e0928d976b024c8c7d`. This directory is evidence only;
adding it does not change the source bytes that were checked.

## What changed

The B4 independent source-closure declarations now name the existing protected
paired admission, enrollment and startup sealing paths explicitly. The negative
mutation control matches the existing typed `OriginalHumanInput::First` call.
The production authority chain, `CALLERS.toml`, revocation guards and effects are
unchanged.

Four MCP OAuth refusal assertions now inspect the pinned SDK's
`DiscoveryRequestFailed { url, source }` error domain. Their refusal and foreign
origin no-request checks remain present. The modern HTTP error-body control pins
the existing 64 KiB error-body cap independently of the normal 8 MiB response
cap. No production transport, dependency, workflow, security policy, test
selection, timeout or acknowledged-failure budget changes are included.

## Actual validation and its limits

| Scope | Actual result | Source binding |
| --- | --- | --- |
| Existing complete B4 Python roster | 125 passed, 0 failed; test-body time 18.219 s, observed command duration 18.408211342 s | Run from base `1383c6f4` with the recorded B4 patch applied; the exact three changed files were subsequently committed as `3331112f1a1dc71b30ed2cc9fb1d8a10a8b3d5f9` and are unchanged in `f74d0ccde`. |
| Two original MCP integration targets | Build exited 101 after 155.122576309 s; **0 tests executed** | Clean exact source `f74d0ccde`; full before/after source maps match. The `rama-http` rustc child terminated with signal 9, SIGKILL, during dependency code generation. |
| Formatting and diff hygiene | `just fmt` and `git diff --check` completed for the incremental changes | The B4 formatter reported no changed Rust files requiring formatting. This is not a claim of a full-workspace format or lint pass. |

The host-wide `oom_kill` counter changed from 29 to 30 during the native attempt.
There is no per-PID OOM event or equivalent causal record in this package.
Consequently, the direct finding is SIGKILL before test execution; the identity
or cause of the kill is not established. Neither a native assertion pass nor a
native assertion failure is inferred from that attempt. The prepared second
local attempt was never launched. The original remote gates remain required.

The archived B4 `RESULT.json` retains the test-time base commit, rather than
rewriting it to a later commit. Its patch SHA-256 and the complete 10,758-file
source maps bind the actual patched tree. `INDEX.json` links the three published
B4 file hashes to those maps. The B4 roster does not execute or qualify the
native authority effects.

## Original CI and remaining failures

The investigated run is `46138718716`, from PR head `1383c6f4`; the actual CI
checkout in the retrieved logs is merge commit
`a9eb90bacee91535d379f13e7daf528c6c89402e`. Complete original logs for both Linux
Bazel jobs, SDK checks and B4 checks are archived. Relevant original source blobs
match the PR base, but a separate baseline workflow was not rerun. Source
correspondence does not prove identical external services or advisory databases.

These remain open:

- The MCP assertion migrations have no completed local native result.
- Legacy SSE currently loses the specific local size-error cause at the public
  caller. A separate uncompiled diagnostic-channel draft is **excluded** from
  this package; the original failing assertion is unchanged.
- Five proxy success controls need a capability-preserving implementation or an
  explicitly scoped fixture transport. Selected proxies are not silently
  bypassed, and destination restrictions are not relaxed.
- The SDK OAuth subprocess fixture uses separate loopback origins without an
  explicit capability. Remote OAuth metadata is not promoted to address
  authority.
- The original cargo-deny raw log and its RustSec database revision remain
  unknown. A bounded local attempt using the official cargo-deny 0.19.0 binary
  and a separately pinned current database stopped before checks because the
  frozen registry cache lacked packages. It is not an advisory pass, a
  confirmed vulnerability finding or an explanation of the original job.
- The complete CI run, including other platforms, is not qualified by this
  package. No failed job is relabeled as passed.

## Evidence and resource handling

`RESULTS.json` is the concise outcome record. `INDEX.json` identifies all 53
members of `raw-evidence.tar.gz` by size and SHA-256. Each archived member was
read back and checked against its digest. The archive contains the original
pass and failure outputs, frozen inputs, source inventories, exact patch,
original CI logs and source-level failure classification.

The existing blob-size asset mechanism retains this 1,477,737-byte archive via
one exact repository path and its SHA-256 in `.github/blob-size-allowlist.txt`.
The 500 KiB default, checker and policy tests remain unchanged. Altered bytes or
the same bytes at another path do not receive this exception.

The archive also records the authorized removal of 513,794,048 allocated bytes
of reconstructible build/tool cache. Exact file hashes, dependency exclusion,
prior-owner release, current coordination lease and visible process references
were checked; namespace-local process visibility is not asserted to cover the
whole host. Shared Cargo registries, source and raw validation evidence were
preserved. The alternative `ai395` host was queried only for health and process
inventory; neither request returned through the orchestration. Its load and
jobs remain unknown. No remote execution, process restart or process
cancellation was sent.
