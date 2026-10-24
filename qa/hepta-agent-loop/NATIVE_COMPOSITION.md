# Native agent composition and activation status

The native loop is an orchestration library over existing owners. Its source
does not grant model or tool authority, create a second conversation store, or
replace Codex's sandbox. A passing controlled fixture, an authenticated
single-provider probe, and a deployed native model/tool loop establish different
things. Report their results separately. The combined source passed 54 loop and
qualification tests plus 8 registry pipeline tests in isolated job
`1a16cb507fc-1b6abb-469c`. After splitting the unchanged TaskFlow test bodies into
small modules, all 8 TaskFlow tests, formatting, package-scoped Clippy and the
normal qualification executable build passed in `1a16cd294a5-1b6abb-46f5`.
The full dependency Clippy blocker in the original checkpoint owner is repaired
separately in commit `581db938c3061da9e01cbab0c32bfabda8e60f54` / PR #3671;
it is not part of this initial composition commit.

The Linux normal dependency tree with all loop features contains neither Core,
App Server nor Agentd. This is a dependency-boundary result, not a memory or
latency measurement. The separate qualification executable links Core for
configuration bootstrap. Its debug artifact is 761,171,552 bytes, SHA-256
`871dcf3486290329a806c42248c5f6b4b238f3577c9f4f90df8e70deb43ca5da`.
No live provider qualification or comparable native/Codex A/B is claimed by
these offline gates.

### Existing owners to compose

| Boundary | Concrete owner/API | Required composition |
| --- | --- | --- |
| Turn history and recovery | `TaskFlowTurnOwner::open(&AutomationStore, TaskFlowFence, TurnBinding, initial, Limits, preparer)`; existing `taskflow_cursor` / `commit_taskflow_cursor` | Retain the original run, fence, request and history; commit observations with the cursor. `TaskFlowContextPreparer::prepare_next` resolves the original continuation and output evidence without effects before its CAS. No second turn database. |
| Context | `compile_v2`, `record_serialization`, `build_attachment`, `prepare_delivery_v2`; registry `prepare_prompt_delivery_with_tokenizer_v1` | Supply authenticated current admission and the actual profile-bound tokenizer/serializer. The new registry seam validates registered selected-item counts and counts the complete serialized payload. It does not admit arbitrary dynamic history. |
| Inference | Existing `AuthManager`, `SharedModelProvider`, `ProviderAuthScope`; `ModelProviderPolicyContributor::begin`; managed `stream_admitted` | The original provider owner must bind the admitted attempt, exact encoded body, model, scope and context preparation, then retain terminal evidence. The managed adapter consumes the supplied lease; it cannot inspect or manufacture the lease's authority. |
| Effects | `AgentdClient::automation_execute_effect` / `automation_reconcile_effect`; `AutomationStore::execute_authorized_taskflow_effect` | Reuse the claimed TaskFlow step, exact intent, original signed grant and configured provider contract. A lost response reconciles the original attempt; a new grant is not permission to resend it. |

The current effect owner settles the entire effect TaskFlow run. It cannot be
called on the native conversation's own run and then expected to leave that run
open for the next model turn. A separately prepared and independently authorized
effect run is required by the optional status adapter under development; its
mapping digest binds data integrity but does not create parent/child authority.
That adds real owner-record and validation work, which belongs in later cost
measurements. An adapter preflight is also not proof of atomic cancellation
exclusion: the original owner's dispatch-admission transaction needs its own
concurrency qualification.

The context API's trust seams and exact-byte contract are defined in
[context compiler V2](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-context-compiler/src/v2.rs).
The existing registry path derives its candidates from exercised realizations and
rejects arbitrary `base_candidates`; its compatibility tokenizer is a stored
count lookup, not a general provider tokenizer
([prompt pipeline](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-intelligence/src/prompt_pipeline.rs)).
The provider owner must bind the exact input digest to its own exact-attempt
`ephemeral_input_witness_sha256`; the context preparation digest is not a
substitute witness.

### Work that can be implemented and tested in an isolated tree

- Compose the real TaskFlow cursor, full Responses continuation retention,
  existing V2 compiler, and original authorized-effect owner in a bounded
  controlled fixture. Test restart/reconciliation, duplicate operation keys,
  cancellation and stale owner fences. A fixture issuer/tokenizer remains a
  fixture and must not become a production bootstrap default.
- Implement production `prepare_next` in the existing context/admission owner:
  resolve retained provider items and actual effect output, classify dynamic
  content, preserve mandatory call/output pairs, and create the next admitted
  frame. Keep this policy out of the generic loop.
- Implement the original provider owner's preparation-to-attempt evidence
  resolver and encoded-body/terminal persistence. Completion requires retained
  continuation, actual usage and acknowledged terminal owner writes. An
  interrupted stream without terminal usage remains unresolved.
- Add a narrow input-count endpoint to `codex-api` if the configured provider
  supports it. `EndpointSession::execute_once_with` can preserve scoped auth,
  route headers and single-attempt accounting. Add bounded request/response
  evidence and an explicit unsupported outcome; do not infer capability from a
  compatible URL. This endpoint is not presently exposed by `ResponsesClient`
  or `ProviderCapabilities`
  ([session](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/codex-api/src/endpoint/session.rs),
  [provider](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/model-provider/src/provider.rs)).
- For an output-bearing tool, wire the original artifact/output resolver at the
  effect owner. `ProviderEffectAck` contains an operation digest and status, not
  command output bytes. A tool explicitly defined to return execution status may
  return the authenticated owner receipt itself; a general tool must not present
  that digest as recovered output
  ([effect contract](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-contracts/src/provider_effect.rs)).

### Independent evidence required before deployment

The source already exposes the intended authority bootstrap; an implementation
test does not provision it. `AgentdConfig` defaults the external-effect host to
absent. The explicit host file configures the provider destination, signed
provider contract, verifying key and revocation head. Only then does startup
attach `AgentdAutomationEffectHost`, which consumes the original signed grant
through the automation owner
([config](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-agentd/src/config.rs),
[host](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-agentd/src/automation_effect_host.rs)).

The trusted launcher must provide the original issuer capability.
`AgentdUnixFinalUseGrantProvider::from_stream` requires an already connected,
peer-pinned private descriptor; `from_root_stream` additionally requires the
launcher's pre-held UID-0 process descriptor. These APIs do not discover an
issuer or mint a grant. The existing inference authorizer registers the specific
operation `runtime.codex.turn_start`. A native dispatch must be covered by an
existing correctly bound operation or an explicitly registered operation in the
original issuer; it cannot reinterpret that grant as a different model/tool
operation
([issuer transport](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-agentd/src/final_use_issuer.rs),
[Root lane](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-agentd/src/root_issuer_client.rs),
[inference authorizer](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/332d8b448758ad45e516a208d940f2358f888e32/codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs)).

Production V2 activation also needs authenticated dynamic admission and an actual
tokenizer/profile binding. OpenAI documents
[`POST /v1/responses/input_tokens`](https://developers.openai.com/api/docs/guides/token-counting),
which counts the full processed structured request, including tools and framing.
That scalar is not a tokenizer artifact or a raw-fragment count. It can support
a separate full-request provider-count receipt after route qualification. It
cannot silently populate the existing registry's per-fragment tokenizer table.
Current ChatGPT OAuth route support has not been established; credentials must
stay on their configured route. No byte ratio substitutes for exact provider
tokenization.

The bounded live template probe remains useful before this integration is
activated: it exercises actual configured auth, provider streaming and durable
continuation/usage retention. It does not establish production V2 admission,
tool authority, provider cancellation acknowledgement, or OS sandbox parity.
Dropping a stream only establishes a local stop; without a provider terminal
receipt, remote completion and token usage are unresolved. The qualification
executable links Core for official configuration bootstrap, so its RSS/binary
size cannot demonstrate a Core-free native agent. Same-model comparisons must
also match effort, context, tool definitions and actual host permissions, and
report observed token/cache usage rather than reservations.
