# Complete the v1 remote-environment fixture conversation

Base: `752eae654d24345b0999a5b151250a2a60dbcd8e`.

Three original Windows attempts each contain ten response requests. The first
four received the fixture's four successful responses. A completed v1 child then
contributed a terminal notification to the parent conversation. The fifth request
and the five existing retry attempts received 404 because the fixture had no
response for that legal continuation. The resulting retry interval exceeded the
exec-server fixture's existing five-second idle read limit. That task panicked
before the test reached its original stop-signal assertion.

Only the v1 case now installs one optional response for that exact continuation.
It matches the real parent thread ID, the complete input prefix of the last
original parent request, the existing spawn call and child message, and the
returned child ID in an exact completed-notification payload. The two appended
items must be the original assistant `done` message and that user notification.
Unrelated or malformed requests do not match.

The original four-response sequence and its exact four-call expectation remain
unchanged. Its default priority precedes the new route. The new route can respond
at most once, and is optional because a notification can already be consumed in
the original parent response under a different schedule. Wiremock's fixed 0.6.5
source skips a route's matchers after its configured match limit; the completed
four-response recorder therefore remains the reference prefix. The v2 case does
not install the new route.

The shared exec-server reader, handshake, five-second limits, shutdown signal
checks, original client retry policy, environment/profile assertions, and all
production sources remain unchanged. This is a fixture response correction, not
an increase in a timeout or a production retry. The original failure logs remain
failed attempts. Static checks and replay of saved request bodies do not qualify
the new Rust source; the original v1 and v2 tests must pass in normal CI.
