# Structured input fixture qualification

The final patch changes only the setup of
`tools::handlers::multi_agents::tests::send_input_accepts_structured_items`
in `codex-rs/core/src/tools/handlers/multi_agents_tests.rs`.
It gives the thread manager and the started thread the same loopback HTTP
provider. The existing structured items, complete equality assertion, five-second
observation helper, submission, and shutdown remain byte-identical.

The final source is bound to SHA-256
`21b7592e5ac039b380423a467ff74211631c31fa7df3be31d9b0b02f0290900b`
and Git blob `d0743c8d967cd22584de4e9221424b51dbd211b6`.
Its original blob, `b9c77045746f18ea1bcdf7537bbc9e67446d3267`, is identical
at both native base `a91102d3639a5a1f02394bfc0331611e9ab101a1` and the
published integration parent `770179d123b879355b53db1d75f8f9f301280d3e`.

## Original CI evidence

The original Intel macOS log is from workflow run `44287117820`, workflow
attempt 1, job `134743268288`. The first attempt of Core unit shard 3 of 8
reported 285 passed and this one failure: its five-second wait for
`ItemCompleted(UserMessage)` expired. The overall Core target subsequently
finished **FLAKY**, with one failed target run out of nine target runs. These
are shard runs and the additional attempt, not nine retries of this one case.
The final hard failure in that job was the PTY unit target.

The failed case has one Tokio test attribute and no parameterized test
attributes. Its original failed-shard output has one test-result occurrence.
It therefore does not show the duplicate-registration defect diagnosed in the
separate multimodal integration test.

The original CI log does not record the event or request timeline needed to
identify that historical failure's unique cause. The controlled experiment
below establishes a fixture dependency and its repair separately.

## Controlled native experiment

The original fixture used the default provider with a dummy key. The pinned
provider supports WebSockets and has a default 15-second connection budget.
RegularTask emits TurnStarted, then awaits startup prewarm before input
recording. This can exceed the independent five-second test observation.

All new executions used a loopback provider. No live OpenAI service was probed.
The production source and its connection budget were unchanged.

| Phase             | Fixture                                                                                                 | Actual result                                                                                                                                         |
| ----------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Controlled RED    | Original WebSocket capability; local GET /v1/responses response delayed six seconds                     | Original assertion failed at 5.083 s. The log captured the WebSocket upgrade request and TurnStarted, with no user-message completion before timeout. |
| Same-trap GREEN   | The same delay and diagnostic source, with only the local fixture WebSocket capability changed to false | Passed at 0.066 s. No WebSocket request was observed; the exact Mention and Text UserMessage completed at 12 ms.                                      |
| Final clean GREEN | Minimal local HTTP fixture, with all control delays and diagnostic prints removed                       | The original case passed at 0.057 s.                                                                                                                  |

Each phase selected one test with zero retries. The 2,466 other library tests
were outside the filter and are not claimed as passed. The command was
`just test --offline --locked -p codex-core --lib -E 'test(=tools::handlers::multi_agents::tests::send_input_accepts_structured_items)' --no-tests fail --retries 0 --test-threads 1`.
The diagnostic GREEN additionally requested success-output logging.

The environment was Linux x86_64 on the existing ROG host, Rust 1.96.0,
Cargo Nextest 0.9.103, and Just 1.58.0. These executions do not establish a
new Intel macOS hosted-CI pass. They qualify this component fixture at its
recorded source.

## Maintenance and scope

After the final original case passed, `just fmt` completed successfully in
2.03 seconds. The tested source remained byte-identical. No test ran after
formatting. Git diff check passed and only the one test file was modified.

An independent static review accepted the same final source hash. No
production function, caller allowlist, permission, timeout, input item, or
assertion changed. No branch history parent was attached and no remote
reference was written by this investigation.

## Evidence

- `structured-input-local-provider.final.patch`: exact native final patch,
  1,226 bytes; SHA-256
  `a2c71d8bf1b484bfab65958c81d45caf2e110485ab04904f848f48140dc22b73`.
- `qualification.json`: final local review and source binding.
- `native-structured-input-originals.tar.gz`: 130,403 bytes; SHA-256
  `23498ab73b5e6f1ecd384e15b72fd6e6c885f0deb8024a87f0cbd06a63098d2a`.
  It contains 24 original files plus the complete native manifest, 25 regular
  members total. All member sets, lengths, SHA-256 values, source postimages,
  raw test logs, and maintenance records were rechecked after exact-byte transfer.
- `original-ci-classification.json` preserves the original job SHA and exact
  failure/FLAKY/PTY excerpts.
- `read-only-findings.json` and `source-provenance.json` preserve the initial
  bounded inference and 17 exact original source bindings.
- `independent-static-review.json` records the independent source review.

The original failure and every control remain retained. Earlier planning files
marked pending describe their time of creation; `qualification.json` is the
final qualification record. Hosted required checks on the combined integration
candidate remain necessary.
