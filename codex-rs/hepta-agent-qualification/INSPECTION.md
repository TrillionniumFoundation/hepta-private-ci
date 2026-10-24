# Installed-owner metadata inspection

`--inspect` is a separate action of the qualification executable. It creates a
new private evidence directory, loads the installed configuration through
`ConfigBuilder`, constructs the original `AuthManager`, selects the configured
model provider, and queries that provider's actual `ModelsManager` with
`RefreshStrategy::Offline`. It then uses the original `get_model_info` and
`ModelInfo::service_tier_for_request` methods. It never constructs a Responses
client, admits an inference attempt, issues a grant or starts model generation.

Offline prevents a model-catalog endpoint fetch. It does **not** mean the entire
inspection is network-free: original auth initialization or the model owner's
auth-mode check may refresh credentials, resolve configured external auth or
contact the auth service. Inspection preserves those original restrictions and
does not substitute an `auth_cached` manager, another account or a weaker auth
configuration. It does not observe or claim zero authentication network calls.
An observed auth mode is only an enum, never a token/account/config dump.

## Invocation

The original no-action plan remains unchanged: without `--run` or `--inspect`,
the executable prints the existing generation plan without loading config/auth
or creating evidence. Plan/run still require all explicit generation bounds.
Inspection conflicts with `--run` and with generation budget flags:

```sh
hepta-native-provider-qualification \
  --inspect \
  --expected-model gpt-6.1-sol \
  --evidence-dir /absolute/private/new-owner-inspection \
  --inspection-setup-seconds 20
```

The setup wait bound defaults to 20 seconds and accepts 1–60 seconds. It applies
separately to configuration loading, auth-manager initialization, and the whole
catalog observation/metadata lookup. The maximum combined owner wait is three
times that setting, in addition to local evidence serialization/fsync. These are
await deadlines; they are not claims that an auth service acknowledged stopping
its work when the caller stops waiting. No generation call is involved.

The evidence directory must be new and absolute. The existing evidence owner
creates it privately and uses create-new records plus fsync. Inspection saves
`inspection-plan.json` followed by `inspection.json`. Failures retain a static
reason code and exit unsuccessfully; original owner error messages are excluded.
No automatic retry is performed by the inspector.

## Snapshot boundary

The snapshot explicitly selects model/provider labels, configured effort,
summary, verbosity and tier; original model default/support metadata; the Lite
flag; relevant feature booleans; compiled/package cache versions; and pre/post
catalog digests/counts. Symbolic string labels are bounded; URL-like, control-
containing or oversized values retain only their byte length and SHA-256.
Descriptions, instructions, prompt templates, URLs, headers, ETags, account IDs,
credential contents, arbitrary Config/Auth Debug, and original error bodies are
never included.

Catalog serialization for digesting is bounded to 8 MiB, catalog count to 512,
reported setting-choice arrays to 64, and the resulting snapshot to 64 KiB.
Digests identify the observed typed serialization; they are not signed provider
profiles or tokenizer attestations. The resolved model's fallback marker is
retained explicitly because that internal field is skipped by normal model
serialization.

The public original model manager does not expose the cache-load decision or
rejection reason. The snapshot therefore reports configured-static versus
provider-owner-offline, before/after value changes, and the actual fallback
marker. `cache_hit` and `cache_rejection_reason` remain unknown. An unchanged
catalog can represent a valid equivalent cache; it must not be labelled a miss.
The original owner still enforces its version/TTL eligibility rules. The
inspector neither reimplements them nor opens a second cache.

This is metadata inspection only. It does not normalize/send a new generation
request, qualify provider model availability, certify exact tokenization, repair
the previous indeterminate attempt, or establish native/Codex A/B parity.

## Offline gate

```sh
just test -p codex-hepta-agent-qualification inspection
```

The new tests exercise the actual original `OpenAiModelsManager` and its file
cache with fresh, stale, wrong-version and equivalent snapshots. A controlled
endpoint records any catalog-fetch attempt; all Offline cases require zero.
They check that the cache bytes remain unchanged, original config overrides
apply, unsupported service tiers are filtered by the original model method,
private prompt/description/ETag sentinels never reach the projection, deadline
and error results are static, action modes conflict, and an existing evidence
directory blocks before installed-owner initialization. No installed auth or
real model endpoint is used by these tests.
