# Local annotations and the provider transport boundary

Source candidate, based on integrated commit
`304aad85f2803c49daafa84dad1f3f6d18b701dd`. Runtime qualification is pending;
formatting is not a test execution receipt.

## Correct observation layers

`core/src/client.rs` intentionally removes
`internal_chat_message_metadata_passthrough` unless the resolved endpoint is the
exact permitted OpenAI endpoint. Localhost mock servers are not an exception.
This change does not modify production endpoint selection, credentials, transport,
metadata persistence or feature flags.

Content kinds are observed through the real
`CodexThread::load_history(false).await?.items`, selecting
`RolloutItem::ResponseItem(envelope).item`. The test-only helper matches explicitly
selected actual request inputs to an ordered subsequence of those persisted
items. It ignores only top-level response IDs and internal metadata. Content,
roles, names, call IDs, arguments and media must otherwise compare exactly. It
also asserts that **every actual mock request input has no internal metadata**.
No metadata is rehydrated into a captured wire request.

The initial changes cover token-budget guidance ordering, local-image and resize
notice annotations, and the comprehensive context-annotation snapshot plus the
feature-disabled case. The existing wire content/ordering/image assertions remain.
The local-image helper explicitly selects user content and resize notices because
Responses Lite may add request-only base instructions; this is not presented as
persisted history.

## Attempted tool calls are a different layer

`ExecutedToolCallRecorder::attach_pending_to_prompt` annotates a prompt clone in
`session/turn.rs`. It does not write the annotation back to persisted history.
The MCP hook tests therefore assert the original attempted call's exact wire
namespace/name/arguments, the real blocked output and exact hook input, and the
absence of internal wire metadata.

An opt-in marker exists only in the synthetic `test_stdio_server` binary and
writes only the path supplied by the test's disposable `TestCodex` home. It uses
`File::create_new`, so it cannot overwrite an existing file or hide a second call.
Both blocked-name variants require no marker; the successful rewritten echo case
checks the marker's exact name and rewritten arguments as a positive control.

The recorder unit test independently verifies both MCP namespace conventions:
original model-attempted name/arguments are attached to the prompt clone even
when its output says the attempt was blocked, while retained input history stays
unchanged. This test is not a claim that an invocation occurred or that the
annotation was persisted.

## Required targeted execution

Use the repository `just test` wrapper on the integrated source and locked graph:

```sh
just test -p codex-core --lib --locked attempted_mcp_metadata_is_prompt_local_even_for_a_blocked_output
just test -p codex-core --test all --locked -E 'test(token_budget_guidance_precedes_standalone_context_window) | test(view_image::user_turn) | test(hooks_mcp::pre_tool_use) | test(context_annotations::)'
```

The normal Linux runner must supply the real `test_stdio_server` test binary and
ordinary test prerequisites. Do not change sandbox environment variables, skip a
test or expand the production endpoint allowlist to obtain a pass. Further
`has_content_kinds` and prompt-local executed-call assertions are inventoried for
follow-up rather than declared fixed by this first group.
