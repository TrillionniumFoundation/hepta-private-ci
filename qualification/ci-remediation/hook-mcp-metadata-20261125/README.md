# Preserve executor-hook MCP metadata and owning-thread identity

## Evidence and scope

The `fac3c71755e688edd7df3c2bd60a5739aeaa2c57` GNU job `139157914143` and
musl job `139157914196` both list
`executor_stop_hook_runs_after_attachment` among failed cases. The normal CI
script prints only the last 200 lines of each failing target's test log. The
retained job logs contain this case's failed identity but not its complete panic
section. This distinction is retained; the missing panic text is not invented.

Source inspection independently establishes the broken contract. The existing
integration case requires the MCP call's `_meta.x-codex-turn-metadata` to contain
the real turn, session, thread, and model. The executor discarded
`HookMcpCall.metadata` and sent only `threadId`.

## Metadata provenance and repair

`core/src/hook_runtime.rs` obtains the current MCP-specific projection from
`TurnMetadataState::current_meta_value_for_mcp_request`. This existing projection
removes tool inventory and the agent, parent-turn, and root-turn fields. It is
passed through `StopRequest.request_metadata`, the executor-scoped dispatch
branch, and `hooks/src/engine/mcp_runner.rs` into `HookMcpCall.metadata`.

The final executor now preserves that map and inserts its own real `threadId`
last. A supplied `threadId` can never override the thread identity captured by
`CoreHookMcpExecutor`. Absent metadata still produces the original object
containing only the real `threadId`.

The same prepared client performs the call. Catalog-revision validation,
governance, executor-environment checking, timeouts, and the original metadata
filtering remain unchanged. No OpenAI Responses endpoint allowlist or internal
chat-message metadata setting is modified.

## Regression evidence required

The dedicated `hook_mcp_executor_tests.rs` case creates a real Session and HTTP
MCP server, completes initialization and tool discovery, and invokes the actual
executor twice. The first call has no metadata. The second supplies a forged
`threadId`, the real filtered turn projection, and nested typed extension data.
The test compares the complete two wire `_meta` objects, including the real
owning-thread ID in both. It exercises the actual prepared-client path rather
than reimplementing map composition in a test double.

The existing attachment integration assertions are unchanged. They remain the
end-to-end check of Stop event dispatch and real turn metadata. The independently
reviewed environment-guard commit remains separate.

`just fmt` and `git diff --check` passed for this candidate. No new Core build,
unit execution, or integration execution was started locally. Both the new
real-client unit and the existing integration cases remain pending normal CI.
