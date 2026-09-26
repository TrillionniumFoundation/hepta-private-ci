# secrets.heptabao evidence history

This file retains historical validation observations that previously obscured
the current integration contract in the crate README. Historical evidence is
immutable context, not a substitute for exact-head and synthetic-merge receipts.

## 2026-09-08 initial exact-read qualification

The exact KV-v2 client completed an isolated real-service fixture using
synthetic credentials. The fixture exercised pinned TLS, exact headers/version,
receipt-only output, replay denial, forged signatures, denied provider tokens
and restart/unseal of the isolated service. It did not connect to production.

An early normal workspace run was blocked by shared disk exhaustion before tests
executed. A later locked workspace run executed 243 tests: 237 passed and six
pre-existing shared HTTP-client TLS classification/fallback cases failed. An
independent prior-source checkout reproduced those six failures; they were not
claimed as adapter regressions or as an all-pass repository gate.

A separate normal-workspace consumer binary passed the 20 isolated service
checks. Its receipt remained bound to its recorded source and binary digests;
it was not represented as a later final-commit binary.

The Bazel lock refresh was blocked by tool/approval conditions. An older source
run had passed real Bazel check/update/check commands, but that result was not
used to qualify the later dependency migration.

## 2026-09-25 dynamic-contract probe

The fixed provider source
`HeptaBao@eac9c608bfda77a8972e1e8a1343dfc21985d62b` was built with locked
dependencies and started as a fresh isolated TLS service. KV control write/read
returned HTTP 200. The tested database mount returned 501; database credentials
and lease lookup/renew/revoke routes returned 404. The probe exited 2 with
`blocked_provider_contract`.

The machine-readable evidence is
`codex-rs/hepta-bao-adapter/qa/evidence/dynamic-contract-probe-20260925.json`.
It proves a blocker, not dynamic-lease execution. The provider integration pin
was not silently changed.

## V3 reference owner candidate

The bounded JSON owner added single-writer fencing, immutable operation results,
migration without invented history, capacity reservation, private files,
post-rename uncertainty fencing, registered consumer profiles and observer-only
recovery. Native source-head and deterministic-merge jobs were introduced so a
document failure could not suppress actual module tests.

## V4 consumption saga candidate

The consumption history was split into `Claimed`, `Reserved` and
`DispatchFenced`; deterministic provider failures and evidence-bound consumer
`NotApplied` became immutable terminal outcomes; AuthBus gained operation-ID
reservation lookup; restart reconciliation was defined for every durable state.
The JSON owner remains a reference implementation pending SQLite production-owner
activation and exact-candidate qualification.
