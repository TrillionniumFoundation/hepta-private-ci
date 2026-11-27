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

The second source stage covers audio, skills, additional context, rollout-budget
and current-time reminders, model switching, resumed images, Responses Lite,
subagent message annotations and cross-turn local timestamps. All former
`has_content_kinds` calls in the integration suite now observe the appropriate
layer. This source inventory is not a test-pass claim.

## Explicit transformations, without widening the generic matcher

Two Lite image fixtures deliberately prepare Original-detail images. The actual
wire must omit `detail`; an expected persisted copy adds exactly the configured
`original` value. The ordinary strict matcher then compares that expectation to
real stored items, still ignoring only IDs and internal metadata. URLs, prepared
image bytes, text, roles and relative order remain exact. This does not modify a
captured request or accept arbitrary differences in media content.

The legacy-image resume fixture excludes only its named historical image message
from exact stored matching: `apply_rollout_reconstruction` prepares that image in
memory and intentionally leaves its old rollout unchanged. Its real request's
decoded dimensions remain checked, while the newly recorded image and resize
notice must match stored items.

Unsupported media labels are a `ContextManager::for_prompt` projection. The
existing `for_prompt_strips_media_when_model_does_not_support_it` unit checks the
exact projected kinds; the model-switch integration test checks retained original
local media, no wire metadata, no unsupported image/audio, and the exact ordered
placeholder contents. It does not call projected labels persisted annotations.

Base instructions are request-only. A request-builder unit constructs both the
allowed OpenAI endpoint and a localhost endpoint without making a request,
checks the entire instruction item and endpoint-specific metadata, and proves
the original prompt input is unchanged. Lite integration tests keep the actual
instruction text, order and tool payload checks. The Bedrock test now explicitly
checks its instruction text instead of relying on a vacuous metadata-absence
classification assertion.

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

The third source stage applies the same separation to namespaced custom tools
and nested Code Mode errors. Real integration requests retain exact attempted
custom-call names, namespaces and untruncated inputs, actual dispatch errors,
and replayed prior outputs; their metadata remains absent. Real local call/output
timestamps are read from matched persisted items. The final stored history must
contain no temporary `executed_tool_calls` annotations.

Recorder units verify three sequential prompt replays: namespaced custom input,
JSON-escaped input exceeding the 8 KiB annotation limit, and direct `exec` outside
Code Mode. They check exact names/arguments or truncation markers, retention of
earlier prompt annotations, and unchanged unannotated input history. Another unit
uses the actual nested-cell recorder for both Code Mode variants, verifies the
failed nested `exec_command({})` attempt, and excludes the outer `exec` wrapper.
The corresponding integration test still requires the real handler exception to
be caught. These unit inputs do not claim to execute the handler themselves.

## Compaction timestamps

The remote-v2 fixture now snapshots actual recorded response items before
compaction, and then applies its actual persisted `Compacted.replacement_history`
plus later recorded items. It compares the original user/delegated-task timestamps
against this new replacement boundary and checks a fresh post-compaction item.
Selected local and actual wire objects must agree except for top-level ID and
internal metadata, and every actual request must omit metadata. This fixture has
one explicit compaction and no rollback; its small reader is not a replacement
for the production history reconstruction algorithm.

Current inter-agent writes persist the converted `AgentMessage` as a
`RolloutItem::ResponseItem`; they are not treated as merely hypothetical in-memory
projections. Legacy communication records remain outside this fixture's scope.

## Required targeted execution

Use the repository `just test` wrapper on the integrated source and locked graph:

```sh
just test -p codex-core --lib --locked attempted_mcp_metadata_is_prompt_local_even_for_a_blocked_output
just test -p codex-core --test all --locked -E 'test(token_budget_guidance_precedes_standalone_context_window) | test(view_image::user_turn) | test(hooks_mcp::pre_tool_use) | test(context_annotations::)'
just test -p codex-core --lib --locked -E 'test(responses_lite_base_instructions_are_request_only_and_obey_endpoint_metadata_policy) | test(for_prompt_strips_media_when_model_does_not_support_it)'
just test -p codex-core --test all --locked -E 'test(additional_context_is_model_visible) | test(user_turn_includes_skill_instructions) | test(adds_weighted_initial_and_threshold_reminders) | test(current_time_reminder::) | test(sends_audio_urls_to_responses) | test(sends_local_audio_to_responses) | test(stateless_requests_preserve_local_item_turn_metadata_across_turns) | test(resumed_history_only_emits_resize_notices_for_new_images) | test(model_switching::) | test(responses_lite::) | test(subagent_notification_is_included_without_wait) | test(spawned_full_history_v2_child_uses_model_precedence)'
just test -p codex-core --lib --locked -E 'test(custom_attempt_metadata_retains_namespaces_and_bounds_escaped_arguments_on_prompt_replay) | test(failed_nested_attempt_is_prompt_local_and_omits_the_code_mode_wrapper)'
just test -p codex-core --test all --locked -E 'test(custom_tool_unknown_returns_custom_output_error) | test(namespaced_custom_tool_call_preserves_namespace_through_dispatch_and_replay) | test(code_mode_only_can_call_nested_tools) | test(code_mode_exec_surfaces_handler_errors_as_exceptions) | test(remote_compact_v2_reuses_compaction_trigger_for_followups)'
```

The normal Linux runner must supply the real `test_stdio_server` test binary and
ordinary test prerequisites. Do not change sandbox environment variables, skip a
test or expand the production endpoint allowlist to obtain a pass. All three
stages require qualification on the integrated source and lock graph. No local
runtime execution is claimed by the source inventory, formatting or diff checks.
