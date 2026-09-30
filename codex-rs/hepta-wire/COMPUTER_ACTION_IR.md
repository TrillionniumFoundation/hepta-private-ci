# ComputerActionIRV1: canonical HAC1 profile

The registered protocol is `ComputerActionIRV1`. Rust calls its native value
`ComputerActionFrameV1`; JavaScript decodes `kind: "ComputerActionIRV1"`.
Neither value grants authority. This is a closed semantic-action transport, not
CPU machine code, shell input or an additional effect executor.

## Layout and limits

All integers are big-endian. The body is, in order: `HAC1` (four ASCII bytes),
version/opcode/flags/reserved (four u16 values), body generation, session generation,
observation revision and monotonic deadline (four u64 values), operation/subject/
actuator IDs, optional target ID, precondition/argument/final-payload/postcondition
SHA-256 digests, payload length (u32), then exactly that many payload bytes.
A final 32-byte checksum is SHA-256 of `hepta.computer-action.frame.v1` followed
by the complete body. It is unkeyed integrity metadata, not authentication.

Version is 1. Flag bit 0 means target present; other bits and reserved are zero.
The four u64 semantic fields must be in 1..=9007199254740991 so JavaScript cannot
round an identity or deadline. IDs have a u16 byte length and 1..128 ASCII bytes
from `[A-Za-z0-9._:-]`. Total encoded size is at most 131072 bytes. Digests are raw
32-byte nonzero values, not 64-byte hexadecimal text. Extra bytes reject.

| Code | Action | Target | Payload |
| --- | --- | --- | --- |
| 1 | focus_target | required | empty |
| 2 | activate_target | required | empty |
| 3 | type_text_reference | required | length-prefixed text reference |
| 4 | scroll | required | two i32 milli-deltas, absolute value <=100000, not both zero |
| 5 | navigate_reference | absent | length-prefixed URL reference |
| 6 | open_path_reference | absent | length-prefixed path reference |
| 7 | reveal_path_reference | absent | length-prefixed path reference |
| 8 | copy_text_reference | absent | length-prefixed text reference |
| 9 | notify_reference | absent | length-prefixed notice reference |
| 10 | wait_observation | absent | u64 microseconds in 1..=60000000 |
| 11 | request_evidence | absent | empty |
| 12 | stop | absent | empty |

The argument digest is SHA-256 of `hepta.computer-action.payload.v1` followed
by the opcode-specific encoded payload. It differs from the final payload digest:
the latter binds the actual owner-resolved action. A consumer checks both. A
reference never carries an ambient filesystem path, credential or executable text.

## Consumer and recovery contract

The existing browser owner consumes codes 1, 2, 3, 5 and 10. It rejects other
codes even if the codec recognizes them. Resolution is injected at host construction,
not supplied by an action caller. Subject, actuator, current document digest and
session/page generation must match its admitted context. In this digital browser
profile the frame body/observation generation maps to the admitted page generation;
this does not assert a global physical-body deployment or permit cross-host clocks.

The exact original frame digest is retained as `sourceActionDigest` in the
existing browser journal, separately from the resolved action digest. Final-use
authority still validates the actual target, payload, scope and current revocation.
A transport acknowledgement is not task success. Unknown effects use original
operation identity and reconciliation, not re-inference or a fresh operation ID.
Monotonic deadlines need a same-clock-domain host admission; no raw monotonic
instant may be replayed across reboot or interpreted as a remote wall-clock time.

## Verification and remaining integration

Rust coverage is in `src/computer_action_tests.rs`; the JS mirror and golden-frame
checks are in `js/computer-action-ir.test.mjs` and `js/computer-action-registry.test.mjs`.
Browser owner tests are in `apps/hepta-browser/test/computer-action.test.js`.
The native effect boundary, authenticated clock admission, selected real browser
worker, provider acceptance and production rollout require their own product tests.
A codec test cannot close those boundaries or prove speedup over MCP/tools.
