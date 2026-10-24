# Independent ordinary Responses normalization review

Reviewer: `/root/codex_architecture`. Read-only review of implementation sources;
no credentials, provider request, remote process or Rust test was invoked.

## Reviewed candidate and verdict

The reviewed installer is `backend_normalization_driver.py`, SHA-256
`a59a30199810d89d0c20e7d127885a5415a3a560f795cefc881ff8e5e07bfe68`.
Its bytes match `backend_normalization_stage/MANIFEST.json`, as do every staged
postimage. The unchanged model-provider Cargo manifest is a guarded dependency
preimage. No concrete source/API, authority, ownership, privacy or claim-scope
blocker was found. This is source clearance, not a Rust or live-provider result.

## Checks that support the conclusion

- The shared pure helper preserves the existing Core effort mapping: only
  `Ultra` becomes `Max`; explicit Max and custom values remain intact. Core
  passes its already resolved per-turn summary as `Some`, preserving its old
  summary behavior. Unsupported and explicit None summaries remain omitted.
- Verbosity support/default rules match the original code. Core retains its
  existing warning when a configured verbosity is unsupported. The existing
  `ModelInfo::service_tier_for_request` continues to determine allowed tiers;
  no default tier or fallback profile support is invented.
- The qualifier obtains metadata from its original configured provider's model
  manager, with `raw_model_catalog(Offline, ...)`, followed by the original
  `get_model_info`. The original manager's Offline branches only try its cache;
  `get_model_info` uses the active metadata snapshot. Original auth inspection
  or refresh may still contact its service, as the documentation discloses.
- The model identity check precedes request construction. Responses Lite is
  refused before provider admission because its full request transformation is
  not implemented by this ordinary fixed-marker qualifier.
- The body digest, model-settings evidence digest and explicit absence of both
  routing/Lite headers are bound into a versioned wire-semantic identity.
  Existing `RequestDispatchMetadata` validates exact absence after applying
  auth and before marking physical transport invoked. The exact encoded-body
  observer remains a separate byte-level check.
- Metadata lookup, evidence recording, header parsing and semantic encoding all
  finish before the original attempt is admitted. No new fallible operation or
  await is inserted between receiving the admitted lease and handing it to the
  existing managed attempt supervisor.
- The new tests and public APIs use existing dependencies and types. Golden
  expectations match the original fallback metadata and tier implementation.
  Existing API header tests remain the actual header-enforcement unit tests;
  no local fixture is described as a hosted provider result.

The supporting original definitions were checked in `hepta-private-ci` at
`ee8abfb41496bd7a8b14334f29a684e448bed2c8`: models-manager's `manager.rs` and
`model_info.rs`, protocol's `openai_models.rs`, and the locally retained API
`common.rs` / `dispatch_metadata.rs` / endpoint enforcement sources. The staged
Core diff was checked against its guarded current preimage.

## Deliberately limited conclusion

This fixes ordinary body-settings composition. Offline metadata can differ
from Core paths that refresh online. Fallback metadata is not evidence of a
cache miss, remote support or the cause of a prior failure. Expected-absent
routing headers are a deliberate ordinary qualifier contract and do not claim
full first-party Core routing parity. Session metadata, compression, Lite,
production owner integration and same-task Codex comparison remain separate.

The previous live attempt at source `466416c` remains Indeterminate. This patch
does not retry, relabel or reconcile it. Any subsequent authorized qualification
must have its own explicit evidence directory/admission and retain its actual
outcome. The actual Rust gates must precede any such provider request.
