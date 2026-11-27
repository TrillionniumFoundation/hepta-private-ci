# Hook metadata transport fields

The new full-wire metadata regression reached the real MCP server on Windows,
but its expected objects omitted RMCP's generated `progressToken` fields.

## Original evidence

- Source head: `4be2e45d4c90fe539abf61814fa9b362d8922881`.
- Actual checkout: `4eebcef0c284da9a1964d6c01c15c0f219f7aff9`, ordered parents
  `[07c8994f2402a58f6b59eb648c801fc40c6e2b96, 4be2e45d4c90fe539abf61814fa9b362d8922881]`.
  Its complete tree `28a74dbbf9b668c4691a93c8fd15c5ae2b4c92e9` equals the source head's tree.
- [Windows shard 1 job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45616349339/job/139214394394).
- Decoded original job log, re-encoded as UTF-8 without newline changes:
  565,955 bytes, SHA-256
  `c9e640c866cda4e8e80b82abe2707861f0d1e7b7d75687b13b39cde8ad0ce152`.
- The same test failed in all three existing attempts at
  `core/src/hook_mcp_executor_tests.rs:120`. Each attempt reported 81 passing
  cases and this one failure. Attempts are not distinct test identities.
- Both complete object diffs preserved the real `threadId`, typed turn metadata
  and nested extension. The sole additions on the actual side were numeric
  progress tokens `1` and `2`.

## Source contract and correction

The pinned `third_party/rmcp-3.9.0/src/service.rs` creates a separate default
progress counter in `Peer::new`. `send_cancellable_request` obtains its next
value, merges the application metadata, then sets the generated token. The
fixture's initial `tools/list` consumes `0`; its two successive tool calls
therefore carry `1` and `2`.

The correction adds those two exact fields to the existing expected objects.
It retains deep equality for the entire metadata array, including the real
thread ID overriding the supplied false thread ID, typed nested metadata and
extension values. It does not discard transport metadata or change production
execution, identity checks, request counts, deadlines or dependency versions.

`just fmt` and `git diff --check` passed. The corrected Rust test has not yet
been compiled or executed; the original failures remain retained. A subsequent
source cut must execute the same real prepared-client regression before this
fixture correction is reported as a native pass.
