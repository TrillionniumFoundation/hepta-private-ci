# Native provider qualification

This executable performs one small live Responses request through the installed
Codex configuration, existing `AuthManager`, scoped model provider and the native
managed Responses adapter. It uses the actual Hepta governance contributor in
`Enforce` mode and a new private qualification evidence directory. The policy
lease and exact encoded-body observation are bound to the same model, request,
auth policy and reservations.

Core is linked here only for its real configuration loader. The native loop and
managed Responses library remain independent of Core and App Server. The memory
or binary size of this executable is **not** a measurement of a Core-free agent.

## Scope

The first probe asks for the fixed marker `HEPTA_NATIVE_STREAM_OK`. It executes no
tools and imports no user files or conversation. Compiled native context is empty;
the entire qualification task is in the explicitly admitted API template. Its
compiled-context count is therefore zero. Actual provider input, including the
template and provider framing, is reserved separately and recorded from the
terminal usage observation. This does not qualify the context compiler, a
production native turn owner, a tool loop or same-model Codex A/B performance.

There is one physical Responses attempt, with no transparent transport retry.
Normal configured authentication/bootstrap may make its own auth requests. The
configured model must equal `--expected-model`, and the configured reasoning
settings and service tier are preserved. The executable never constructs a
permissive substitute AuthConfig, chooses another account, prints credentials or
creates a new credential store.

Input and output token settings are local reservations. The current
`ResponsesApiRequest` exposes no hard output-token-cap field. The local stream
wall deadline and byte bounds are enforced, but local cancellation does not prove
the provider stopped work. Missing terminal usage remains unresolved. Usage is
retained before checking reservations, including cache, reasoning and separately
serialized provider rollout-budget units.

## Run

Run the offline tests before the explicitly requested live probe:

```sh
just test -p codex-hepta-agent-qualification
```

Omit `--run` to print the plan without loading auth or sending a request. Supply
a new absolute evidence directory for an actual qualification:

```sh
cargo run -p codex-hepta-agent-qualification --bin hepta-native-provider-qualification -- \
  --expected-model gpt-6.1-sol \
  --evidence-dir /absolute/private/new-qualification-directory \
  --maximum-provider-input-tokens 8192 \
  --maximum-output-tokens 1024 \
  --maximum-elapsed-seconds 60 \
  --run
```

The directory must not already exist. It holds the explicit plan/admission,
original exact encoded request, actual existing governance evidence database,
complete supported typed provider continuation, encoded terminal disposition and result report.
Files are created privately and fsynced before acknowledging retention. Original
artifacts are not overwritten. This is a qualification artifact owner with no
production recovery entry point or FinalUse authority. A crashed or incomplete
probe is inspected under its original evidence; the executable does not resume it
by sending another request.

The report separates requested and observed model identity, local reservations
and actual provider usage, terminal completion and unresolved cancellation. A
successful marker probe establishes actual auth/provider/stream composition for
this harness only.

Retention includes the supported `ResponseItem` fields exposed by the existing
parser. It does not claim lossless raw SSE or recovery of unknown metadata the
parser discarded. Evidence serialization preserves plain reasoning `Text`
content that the normal request serializer deliberately omits. Request wire
serialization is unchanged.
