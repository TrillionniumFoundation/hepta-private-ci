# Agent protocol: technical and development guide

`codex-hepta-agent-protocol` supplies the bounded local control wire types used
between one Agentd and its supervisor. It owns no socket, execution queue,
signature issuer, model turn or external effect. Source baseline: `7673ea62`.

## Technical contract

The public entry is [src/lib.rs](src/lib.rs); [Cargo.toml](Cargo.toml) declares a
library with doctests disabled. `AgentdRequest` binds control schema version,
request ID and spawn generation to a tagged `AgentdMethod`. Responses preserve
their request/generation identity; payloads and events are typed separately
([request:212](src/lib.rs#L212), [methods:580](src/lib.rs#L580), [response:735](src/lib.rs#L735)).
Serde wire types reject unknown fields where declared. Constructing or decoding
a request does not itself authenticate the peer, verify a grant, enforce a
transport deadline, or perform the requested state transition.

| Surface | Meaning and boundary |
| --- | --- |
| `AgentdCapabilitySet` / `negotiate_capabilities` | Bounded, validated capability IDs; negotiate intersection at equal major version and the lower minor. Advertised support is not execution authority. [capabilities.rs:58](src/capabilities.rs#L58), [105](src/capabilities.rs#L105). |
| AuthBus ingress | Signed text/objective envelopes carry issuer/epoch/sequence/expiry and a host-derived-route body. Host verification remains outside this crate. `QueueAccepted` is Core admission, not model/effect completion. [authbus.rs:14](src/authbus.rs#L14), [85](src/authbus.rs#L85). |
| Run lifecycle | Typed snapshots bind run/request/objective/body/artifacts, authority epoch, generation, fence and deadline. Cancellation and terminal observation have distinct receipts. [lib.rs:135](src/lib.rs#L135), [186](src/lib.rs#L186). |
| Objective history | Queries retain the exact historical signed body and optional trusted journal anchor. Missing/unavailable/mismatched history stays `Unknown`; it never proves non-admission or permits automatic resubmission. [objective_history.rs:22](src/objective_history.rs#L22), [80](src/objective_history.rs#L80). |
| `HostTurnAuthorityBinding` | Strict transport witness with nonzero epochs/generation/expiry and bounded non-NUL identifiers. Its source comment explicitly says it is not a grant and is not yet consumed by Agentd runtime. [lib.rs:56](src/lib.rs#L56), [930](src/lib.rs#L930). |
| Kernel evidence envelopes | Append/query/verify material and results; serialization carries no approval to execute an effect. [evidence.rs:1](src/evidence.rs#L1). |

The run phase enum includes admitted, context-attached, dispatched, cancelling,
cancelled, succeeded, failed and indeterminate. These are representations;
the Agentd owner enforces transitions. A retained immutable objective publication
describes compiled/explicit-abstain/conflict disposition, not the current run
phase or an external provider result ([objective_history.rs:45](src/objective_history.rs#L45)).

| Declared bound | Baseline value |
| --- | --- |
| Control schema / frame | v2; 65,536 bytes |
| Cognitive context / automation effect | 8 KiB / 24 KiB |
| Event batch / federation list | 256 / 128 |
| Capability count / ID bytes | 64 / 128 |
| Run cancellation reason | 512 bytes |
| Kernel evidence envelope / required roles | 48 KiB / 32 |

Bounds are declared at [lib.rs:55](src/lib.rs#L55),
[capabilities.rs:12](src/capabilities.rs#L12), and [evidence.rs:4](src/evidence.rs#L4).
The transport owner must enforce frame bounds before unbounded parsing/allocation;
the constants and sample round trips alone do not enforce every ingress boundary.
The overload response is the existing bounded v2 `overloaded` frame with 50 ms
retry guidance, not admission or a new authority lease.

## Development and verification

Edit the owning wire module: `authbus.rs` for signed ingress shapes,
`objective_history.rs` for retained observations, `capabilities.rs` for compatible
feature negotiation, `evidence.rs` for evidence, or `lib.rs` for control payloads.
Preserve wire tags/field names and distinguish historical body generation from
the current outer control generation. Add a typed outcome instead of collapsing
`Unknown`, conflict, queue acceptance and terminal success into one boolean.

From repository root, use the actual package and original host flags; choose an
external `CARGO_TARGET_DIR` without changing test filters or case budgets:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline -p codex-hepta-agent-protocol \
  --test-threads 2 --retries 0 --cargo-profile dev-small
```

Useful exact test IDs (binary `codex-hepta-agent-protocol`):

- `capabilities::tests::negotiation_is_intersection_with_minor_downgrade` — [capabilities.rs:136](src/capabilities.rs#L136).
- `tests::host_turn_authority_binding_is_strict_and_fail_closed` — [lib.rs:1040](src/lib.rs#L1040).
- `objective_tests::signed_objective_control_request_round_trips_inside_frame_bound` — [objective_tests.rs:34](src/objective_tests.rs#L34).
- `objective_tests::history::history_unknown_is_nested_and_cannot_decode_as_non_admission` — [objective_history_tests.rs:31](src/objective_history_tests.rs#L31).

Fixtures are inline Rust/JSON constructors in those tests. They test strict wire
decoding, bounds and compatibility, not a real issuer, socket peer, revocation
service, device driver or persistent owner restart. This documentation-only
successor has not run Rust tests and inherits no product qualification; full
pair verification still includes all original 19 owning packages.
