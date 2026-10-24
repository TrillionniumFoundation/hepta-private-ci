# Ordinary Responses settings qualification

The original model provider now exports a pure typed settings helper. Core and
the isolated native qualifier use the same effort, summary and verbosity rules;
the helper calls the existing `ModelInfo::service_tier_for_request` for tier
filtering. This is a bounded body-settings integration, not full Core request,
authentication, routing, model catalog, task or performance parity.

## Observed reason for the change

The actual offline owner inspector resolved configured `gpt-6.1-sol` / `max`,
unset summary and verbosity, and configured `priority` tier. Its original model
owner produced fallback metadata: summary supported with default `auto`, no
supported tiers, no verbosity support and Responses Lite disabled. For that
metadata snapshot the request rules are:

| Field | Previous qualifier | Shared original rule |
| --- | --- | --- |
| Reasoning effort | `max` | `max`; only the legacy `ultra` spelling becomes `max` |
| Reasoning summary | omitted | `auto` from the original model default |
| Service tier | `priority` | omitted because the original model does not list it |
| Verbosity | omitted | omitted because the model does not support it |
| Lite reasoning context | omitted | omitted for an ordinary request |

`used_fallback_model_metadata=true` is not evidence of a cache miss, a provider
rejection or remote model availability. The inspection did not expose a cache
hit or rejection reason; both remain unknown. The version `0.0.0` and the
catalog snapshot are observed owner state, not values changed by this patch.
These field differences do not establish the cause of the earlier failed
fixed-marker request at source `466416c`. Its durable Indeterminate receipt
remains an independent original attempt and is not retried or relabelled by
this change.

## Original metadata and policy ownership

Before any generation admission, the qualifier creates the model manager from
the same configured `SharedModelProvider` used for its managed Responses client.
It calls the original `raw_model_catalog(Offline, ...)` and then original
`get_model_info` with `Config::to_models_manager_config()`, under a bounded
20-second setup wait. It neither opens a replacement cache nor changes the
account, auth policy, configured model, client version or catalog file.
Original auth bootstrap or refresh can still contact its service. Offline
means that this model catalog path does not fetch the `/models` endpoint.

The shared helper does not perform lookup, authentication, admission, I/O or
transport. Core retains its own already resolved `ModelInfo`, turn summary,
refresh policy and original service-tier filter. Its existing unsupported
verbosity warning is retained. Core also has `OnlineIfUncached` and `Online`
catalog paths, including model switching and ETag refresh; an explicitly
Offline qualifier does not establish that its metadata equals every Core
turn. No cache-success inference or fallback catalog replacement is added.

The qualifier writes `request-settings.json` before admission. It records only
bounded symbolic labels or their length/digest, original fallback/version
observations and configured/normalized settings. It excludes endpoint URLs,
auth headers, credentials, prompts and owner error bodies. This evidence is a
settings observation, not a model support certificate.

## Dispatch binding and unsupported scope

The ordinary probe does not construct a Core routing hint or Lite body. A model
requiring Responses Lite is rejected before provider admission because Lite
also changes instructions, input, tools and parallel-call semantics. The
ordinary request freezes explicit absence of both `x-codex-routing-hint` and
`x-openai-internal-codex-responses-lite` using the original
`RequestDispatchMetadata::new_with_expected_headers`. The API checks these
exact states after applying auth and before marking physical transport invoked;
an injected, overridden or duplicate header cannot be treated as admitted.

Admission v2 and logical-request v2 bind an ordinary-wire v2 digest containing
the exact encoded-body digest, settings-evidence digest, null routing hint,
Lite false and both expected absent headers. The existing exact-body observer
still checks encoded bytes separately. This intentionally differs from the
older body-only wire identity. The existing Hepta governance Enforce owner,
managed one-attempt supervisor, no-redirect transport, cancellation uncertainty
and redacted typed failure diagnostics remain in place.

All fallible metadata lookup, normalization, evidence writing, header parsing
and semantic encoding finish before an original attempt lease is admitted.
The consumed lease then transfers immediately into the managed AttemptOwner.
There is no new metadata await or fallible header preparation in that gap.

Eligible Core first-party requests may add a routing hint using their resolved
auth/provider scope and already normalized tier. This qualifier explicitly
does not claim that header parity. Full Lite, routing, client metadata,
compression/feature settings, session identities, tool execution, original
production TurnOwner and same-task Codex A/B remain separate qualification
requirements. A future request uses a fresh explicit evidence directory and
admission, retains the prior attempt unchanged, and is not automatic recovery
of an Indeterminate request.

## Validation and evidence

The staged source adds six pure owner-rule golden tests, two qualifier metadata
privacy/Lite tests and one versioned ordinary-wire identity test. The original
API's dispatch-metadata tests remain the enforcement tests for header absence,
exact values and duplicate rejection. Existing Core client, inspector and safe
HTTP/SSE diagnostics tests must remain passing. These are source tests and do
not establish a successful hosted request.

The source installer checks every original preimage before any write, preserves
unrelated worktree files and production services, and performs no auth, provider,
Git or build action. Its local guards check mismatch/partial-install rejection,
no mutation on failed preflight and exact idempotent installation. Rust compile,
formatting, focused tests and any fresh request outcome are reported separately
by the actual isolated execution owner. No result is implied by this document.
