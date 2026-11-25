# Executor-scoped hook call authority

## Observed failure

At source `fac3c71755e688edd7df3c2bd60a5739aeaa2c57`, the existing
`executor_stop_hook_rejects_mismatched_environment` integration case observed two
MCP `tools/call` requests where it required one. The GNU job `139157914143` and
musl job `139157914196` each contain three failed attempts of this assertion.
These are repeated attempts of one case, not six distinct cases.

The fixture retains the original plugin root, registers a second executor without
that root, and moves the `node_repl` MCP server to the second executor. The hook
must remain bound to the original executor. The fixture's existing ready-root and
single-call assertions are preserved.

## Cause and change

`hooks/src/engine/mcp_runner.rs` already supplies the executor-scoped handler's
environment in `HookMcpCall.environment_id`. `CoreHookMcpExecutor::execute` did not
consume this constraint. It resolved a server and tool by name and invoked the
prepared client regardless of the client's environment.

The fix compares a present expected environment with
`PreparedMcpCall::server_environment_id()` immediately before invoking that same
prepared call. A mismatch returns an error before sending an MCP tool request.
An absent environment retains its previous semantics. The comparison uses the
immutable server metadata captured with the client, rather than looking up a
separate mutable catalog. The prepared call's existing catalog-revision check and
read lock remain unchanged.

This change does not modify hook governance, server discovery, configuration
refresh, request metadata, or model-tool approval policy. In particular, it does
not claim to fix the separate handling of `HookMcpCall.metadata`.

## Regression control

The existing mismatched-environment case still requires exactly one recorded
call after the attempted mismatch. It now restores the server's original
environment and submits a third real turn. The restored call must occur, and its
complete arguments must equal the expected Stop event, session, and new turn ID.
This checks that rejection is tied to the binding rather than disabling the hook.

Each fixture supplies its expected SSE response IDs explicitly. The two existing
two-turn cases still require exactly two model requests; the extended case
requires exactly three. Existing timeouts and assertions remain intact.

## Qualification boundary

`just fmt` and `git diff --check` passed locally. No new Core build or integration
execution was started for this candidate. The changed integration case and the
unchanged attachment/disconnection controls must run in the normal CI source
tree. Source review and formatting do not establish a runtime pass.

The original raw job logs are retained with these SHA-256 values:

- GNU `139157914143`: `28f21cdebda97235b2e1b5f9a434e77a8654227948f14e0611b72ad95c5c4156`; first failure at line 10987.
- musl `139157914196`: `3db853b8e7135a149652a1ba38e4d2801d6db5bf84078f213830fd46104d7f8c`; first failure at line 9421.

The evidence manifest records complete source and log hashes, the original failed
attempts, and the absence of new execution evidence. No failure was reclassified
as passing by this source change.
