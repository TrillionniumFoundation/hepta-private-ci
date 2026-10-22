# Attestation reverse-RPC integration test

`attestation_generate_round_trip_adds_header_to_responses_websocket_handshake`
starts the real App Server and a local WebSocket server. It advertises the original
attestation capability, answers the server's typed `AttestationGenerate` request
with `v1.integration-test`, and checks the complete handshake header:

```json
{"v":1,"s":0,"t":"v1.integration-test"}
```

The production provider in `src/attestation.rs` has a 100 millisecond callback
deadline. Waiting for thread/start or turn/start responses must therefore service
reverse RPCs concurrently with that wait. The test-local response pump answers
each consumed request once; it retains other messages in a FIFO for the original
completion loop, including an early `turn/completed` notification. The existing
60 second test waits and production timeout are unchanged.

The earlier generic response reader buffered the reverse request until both
responses arrived. The original Windows failure was status `s:1` (timeout),
followed by a late token response whose callback had already been canceled.
The opaque token is an existing fixture: this test verifies protocol and header
propagation, not a production cryptographic attestation.

Run the original case through the repository test entrypoint:

```sh
just test --locked -p codex-app-server --test all -E 'test(=suite::v2::attestation::attestation_generate_round_trip_adds_header_to_responses_websocket_handshake)' --no-tests fail --success-output immediate
```

The dedicated `.github/workflows/hepta-attestation-rpc-fixture.yml` runs this case
on Linux and native Windows. It retains the original `local` profile, default
one-retry policy and runner deadline. A retry pass is reported separately from a
first-attempt pass, with the original JUnit history and complete output retained.

The nextest report is under the Rust workspace at
`target/nextest/local/junit.xml`, independently of `CARGO_TARGET_DIR`. CI preserves
any prior report and requires a fresh regular report with exactly this testcase,
successful process and log-capture exits, no JUnit failure/skip, and no internal
network-skip message. Preflight requires real loopback access and records the
reviewed Git content plus actual checkout bytes; postflight requires tracked
source and checkout bytes to remain unchanged.

Both platform results are required. A skipped network test, missing testcase,
stale report or Linux-only result cannot close the original Windows regression.
