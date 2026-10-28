# Runtime intent projection into the existing execution ABI

`canonical_runtime_intent_v1` converts an already compiled and admitted
`RuntimeToolIntentV1` to the existing `ExecutionIntent` from execution-core.
It performs correlation checks and creates no permission, execution receipt,
operation identifier, generation, journal or replacement recovery record.

## Ownership and placement

The shared Cell/runtime contract belongs in `codex-hepta-types`. Its compatibility
exports may remain in the Codex adapter. The pure conversion belongs beside
the native implementation in `codex-hepta-native-agent`, with a dependency on
the existing small execution-core crate. Putting it in hepta-types would make
the DTO package depend on a particular execution integration; creating another
wire package would add an unnecessary contract to maintain.

| Field or state | Source and owner |
| --- | --- |
| Thread and turn | Existing session owner; the converter receives the canonical run/turn envelope from that owner |
| Tool operation and generation | Original runtime intent, compared exactly with the canonical binding |
| Principal, objective, policy, currentness and effect class | Trusted owner; the model cannot select or authenticate them |
| Compiled final payload | Runtime intent's final payload digest, whose equality with arguments digest is validated |
| Both Cell and organ identities, tool, source input and deadline | Full original runtime-intent digest in `candidate_digest` |
| Admission, attempted submission and loop checkpoint | Existing agent/session owner |
| Actual job ID, acceptance, output and terminal publication | Existing runtime jobs owner |
| FinalUse and physical entry | Independent production authority/verifier; projection grants nothing |

The canonical `ExecutionBinding` names exactly one Cell or organ. Runtime
intents contain both. The converter compares the selected subject directly
and commits the entire source intent in `candidate_digest`, retaining the
other subject without changing either version-one wire schema.

This candidate-digest convention is local to this new function. It must not
be applied retroactively to other execution adapters whose existing candidate
digests have different meanings.

## Acceptance and recovery semantics

An `ExecutionIntent` is a structural record. Successful projection does not
mean execution was accepted. A runtime acceptance does not mean the process
finished. A terminal result requires the original owner-observed terminal
publication and exact output binding.

On loss of an acknowledgement, the native loop retains the original compiled
request, operation, idempotency key and generation. Observation and cancellation
target that request. A missing local job record is not proof of non-admission
and does not authorize another start. The pure converter does not alter those
semantics or write a second execution journal.

The qualification owner deliberately does not synthesize a FinalUse grant.
The interoperability regression appends a projected durable intent and a
reservation to the canonical volatile journal, then verifies that a checked
start is denied while FinalUse is `NotGranted`. The journal cannot replace the
production durable authority ledger.

## Regression coverage

The projection tests check preservation of the caller's complete binding and
compiled payload; both possible subject projections; operation, subject, host,
generation, key and currentness drift; full-source drift in tool identity,
deadline, input, payload kind, the other subject and a different internally
valid compiled payload; and denial of a durable checked start without FinalUse.

These tests are intended to run in the composed Rust workspace. Scratch has
no Rust compiler, so source review alone is not recorded as a passing test.

## Production boundary still to compose

The native `TurnOwner` and `ToolPort` are in-process implementation seams using
the shared runtime DTOs. The canonical checked execution ports are authority
boundaries. This converter does not claim the former already implement the
latter. Production integration must supply the actual existing owner, checked
handles and final physical-entry verification; the qualification-only session
owner is sufficient only for the bounded read-only fixture experiment.
