# Core wire fixtures: connection boundaries and durable metadata

## Observed source and failures

The public source was `4be2e45d4c90fe539abf61814fa9b362d8922881`.
The normal workflow was `45616349339`. Its complete failed-test artifacts,
including all archived shard attempts, exposed failures omitted by the console's
last-200-line display:

- GNU artifact `15028617336`, SHA-256
  `ac86be2881fbc21c38dbd1fd3f1de147eff5ffacad6123609f95b335e00383fe`.
- musl artifact `15026703016`, SHA-256
  `ed96ee3794c92243ed18603da3b41ec72d59401d1abde51f0275241a8d8a8433`.
- Windows shard 4 artifact `15024642238`, SHA-256
  `1fcc0d43be3585915b8f0fc379279724a5e059f4aaf5c9f47b12f6b42ce4c308`.

The two `suite::turn_state::websocket_turn_state_*` cases observed one request
where their fixtures expected four or three. The ordinary test builder starts
with read-only permissions; `submit_turn` selects disabled permission enforcement
and never-ask approval. The production WebSocket compatibility identity retains
the sandbox and review fields. A prewarm socket therefore cannot be assumed to
serve the changed-permission turn. In addition, the sequential mock server's
`close_after_requests: false` waits for shutdown instead of accepting another
scripted connection.

The fixture now serves an explicit, non-generating prewarm on its first
connection, then the unchanged business response sequence on its second
connection. It asserts the exact `[1, 3]` distribution. The business requests
still share one physical connection. The original state arrays, request kinds,
sandbox modes, same-turn IDs and next-turn reset checks remain; the first
business request must not continue the prewarm response. No production socket
identity, retry, deadline or resource setting changes.

The remote-v2 cold-resume case compared a localhost wire request with persisted
history containing `internal_chat_message_metadata_passthrough`. The failure
diff showed that local field as the difference. Production deliberately removes
it from the request copy for endpoints that do not accept internal metadata.
The fixture now separately compares the complete resumed local prefix with the
unmodified persisted items, and compares the wire prefix with the existing
typed `responses::strip_metadata` projection. It does not drop messages, IDs or
positions. The full post-compaction wire prefix, both instruction fragments and
the selected instruction-source checks remain exact.

## Qualification boundary

These are test-only candidates. Formatting and whitespace checks are performed
locally; the Rust cases still require the normal scoped test gates. No local
Core build, model invocation or new CI run was started for this change.
Repeated log records and identical cached bytes across GNU and musl are not
independent experiments. The archived failures remain failures of the old
source; this fixture correction does not retroactively qualify that source.
