# MCP hook visibility and thread-context regression

The complete GNU test log for source
`4be2e45d4c90fe539abf61814fa9b362d8922881` contained a failure in
`suite::hooks_mcp::mcp_tool_hook_passes_thread_metadata_to_model_hidden_tools`.
The representative log has SHA-256
`557bfc84f3e676603c8b0f790fd643acb2476c83a3486f6341f0fb35f806e59d`
and records 93 passing tests and this one failure. The failure was the exact
developer-context assertion, not a timeout.

The synthetic `thread_hint` tool declares `ui.visibility: []` by default.
`CoreHookMcpExecutor` uses `McpBinding::prepare_call`, which rejects tools whose
visibility does not include `model`. The rejected call therefore cannot produce
the two-line context expected by the old test. `HookAdditionalContext` still
uses the developer role and preserves its input text; changing the text assertion
to accept an arbitrary substring would not address this cause.

The replacement coverage uses the same hook configuration, server implementation,
thread metadata, and submission path in two cases:

- The default hidden tool must remain absent from the model's inline catalog,
  leave the server-handler marker absent, and inject neither output line into
  any message role.
- A child-process-only test setting declares that same tool model-visible. Its
  successful call must write the existing handler marker and deliver exactly one
  complete developer fragment containing the owning thread ID and both original
  output lines. Model-visible MCP tools may be deferred from the inline catalog;
  successful hook preparation still crosses the production visibility check.

The synthetic server's default catalog is unchanged. The existing governance
tests retain the hidden setting. No production visibility filter, governing
policy, approval mode, or execution authority changes. The original five-second
hook limit, MCP startup limit, and turn submission wait remain unchanged.

This is a test-fixture correction with a positive control, not implementation of
an alternate authority to invoke hidden tools. Source review and formatting do
not establish runtime qualification. The two integration cases still require
execution against the rebuilt synthetic stdio server on the new source.
